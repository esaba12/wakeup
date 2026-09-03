"""Routine step state machine and routine schema. See docs/06-routine-engine.md.

Design note (proposed spec addition): a curve-based `light` block has no way
in docs/06's examples to say "run this curve backwards" — the wind-down
`dim` step (`curve: reverse-sunrise`) only makes sense reversed, per
docs/03-sunrise-engine.md ("the same engine with t -> 1-t"), and that's an
*execution* parameter of the ramp, not a property of the curve file itself
(the same curve could in principle run forward elsewhere). `LightBlock`
below adds an explicit `reverse: bool = false` key to make that
unambiguous; `routines/winddown.yaml` sets it on `dim`. Proposing this as an
addition to docs/06's schema rather than silently guessing direction from
brightness deltas.

Tick-driven executor (docs/00-overview.md rule 1: nothing sleeps until an
event). `RoutineEngine` has no per-step timer or task — like `Scheduler`,
its `tick()` recomputes the active run's step windows from the wall clock
every time it's called, applies whatever they say, and forgets. That's what
makes `until_cancel` steps free (there's nothing to leak) and restarts a
non-event: `resume()` just adopts a `RoutineRun` built from
`(routine, started_at, trigger_at, state)` and the next `tick()` picks up
exactly where the wall clock says it should.

YAML gotcha worth documenting for routine authors: PyYAML's default (1.1)
resolver treats the bare words `off`/`on`/`yes`/`no` as booleans, so a
`light` block's `off: true` key — written exactly as docs/06-routine-engine.md
shows it — parses to the boolean key `False`, not the string `"off"`, and
fails loudly at load (a `ConfigError` about "keys should be strings", not a
silent misparse). Routine authors must write `"off": true`; both shipped
routines do. Flagging this as a spec-example fix rather than a loader
workaround, since silently special-casing the resolver would just move the
surprise from "load-time error" to "this one bareword behaves differently
than every other YAML file on the system."
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from openrestore.core.clock import Clock
from openrestore.core.curves import Curve, load_curve
from openrestore.core.errors import ConfigError, RoutineError
from openrestore.core.events import Event, EventBus, EventType
from openrestore.core.sunrise import color_at, off_state
from openrestore.drivers.audio.base import AudioOutput, AudioSource, parse_audio_source
from openrestore.drivers.light.base import Light, LightState

# --- duration parsing --------------------------------------------------

_DURATION_RE = re.compile(r"^(-?)(\d+)(h|m|s)$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def parse_duration(value: str) -> timedelta:
    """Parse a signed or unsigned duration like `30m`, `90s`, `-3m`."""
    match = _DURATION_RE.match(value)
    if match is None:
        raise ValueError(f"invalid duration {value!r}; expected e.g. '30m', '90s', '-3m'")
    sign, amount, unit = match.groups()
    seconds = int(amount) * _UNIT_SECONDS[unit]
    if sign == "-":
        seconds = -seconds
    return timedelta(seconds=seconds)


def _coerce_duration(v: Any) -> Any:
    if isinstance(v, str):
        return parse_duration(v)
    return v


def _coerce_step_duration(v: Any) -> Any:
    if v in ("until_cancel", "until_next_step"):
        return v
    if isinstance(v, str):
        return parse_duration(v)
    return v


Duration = Annotated[timedelta, BeforeValidator(_coerce_duration)]
StepDuration = Annotated[
    "timedelta | Literal['until_cancel', 'until_next_step']", BeforeValidator(_coerce_step_duration)
]

# --- schema --------------------------------------------------------------


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["alarm", "time"]
    ref: str | None = None
    at: str | None = None
    days: list[int] | None = None

    @model_validator(mode="after")
    def _check_fields_for_type(self) -> Trigger:
        if self.type == "alarm" and self.ref is None:
            raise ValueError("trigger.type == 'alarm' requires 'ref'")
        if self.type == "time" and self.at is None:
            raise ValueError("trigger.type == 'time' requires 'at'")
        return self


class LightTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brightness: float | None = None
    cct: int | None = None


class LightBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    curve: str | None = None
    to: LightTarget | None = None
    brightness: float | None = None
    cct: int | None = None
    transition: Duration | None = None
    off: bool | None = None
    hold: bool | None = None
    reverse: bool = False


class AudioBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    source: str | None = None
    gain_db: float | None = None
    ramp_to_db: float | None = None
    over: Duration | None = None
    fade_in: Duration | None = None
    fade_out: Duration | None = None
    continue_: bool | None = Field(None, alias="continue")
    sleep_timer: Duration | None = None
    stop: bool | None = None


class OnCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    light: LightBlock | None = None
    audio: AudioBlock | None = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    duration: StepDuration | None = None
    at_offset: Duration | None = None
    ends_at: Literal["trigger"] | None = None
    light: LightBlock | None = None
    audio: AudioBlock | None = None
    on_cancel: OnCancel | None = None
    escalate_after: Duration | None = None

    @model_validator(mode="after")
    def _check_anchor(self) -> Step:
        if (self.duration is None) == (self.at_offset is None):
            raise ValueError(
                f"step {self.id!r} must set exactly one of 'duration' or 'at_offset'"
            )
        if self.ends_at is not None and self.duration is None:
            raise ValueError(f"step {self.id!r}: 'ends_at' is only valid on duration-based steps")
        return self


class Snooze(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration: Duration
    max: int
    light: LightBlock | None = None
    audio: AudioBlock | None = None

    @field_validator("max")
    @classmethod
    def _max_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("snooze.max must be >= 1")
        return v


class Routine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    name: str
    id: str
    trigger: Trigger
    steps: list[Step]
    snooze: Snooze | None = None

    @model_validator(mode="after")
    def _check_steps(self) -> Routine:
        if not self.steps:
            raise ValueError("routine must have at least one step")
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        if self.trigger.type == "time" and any(s.at_offset is not None for s in self.steps):
            raise ValueError("a time-triggered routine cannot have 'at_offset' steps (no anchor)")
        return self


# --- YAML loading, with line-numbered unknown-key errors -------------------
# Mirrors core/curves.py's `_validate_curve_yaml_shape`: walk the raw node
# tree (not the constructed dict) so an unknown key is reported with its
# source line, per docs/06 "a typo... should fail loudly at load, not
# silently at 6am."

_ROUTINE_KEYS = {"version", "name", "id", "trigger", "steps", "snooze"}
_TRIGGER_KEYS = {"type", "ref", "at", "days"}
_STEP_KEYS = {
    "id",
    "duration",
    "at_offset",
    "ends_at",
    "light",
    "audio",
    "on_cancel",
    "escalate_after",
}
_LIGHT_KEYS = {"curve", "to", "brightness", "cct", "transition", "off", "hold", "reverse"}
_LIGHT_TARGET_KEYS = {"brightness", "cct"}
_AUDIO_KEYS = {
    "source",
    "gain_db",
    "ramp_to_db",
    "over",
    "fade_in",
    "fade_out",
    "continue",
    "sleep_timer",
    "stop",
}
_ON_CANCEL_KEYS = {"light", "audio"}
_SNOOZE_KEYS = {"duration", "max", "light", "audio"}


def _node_line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


def _check_mapping_keys(node: yaml.Node, allowed: set[str], path: Path) -> None:
    if not isinstance(node, yaml.MappingNode):
        raise ConfigError(f"{path}:{_node_line(node)}: expected a mapping")
    for key_node, _value_node in node.value:
        key = key_node.value
        if key not in allowed:
            raise ConfigError(
                f"{path}:{_node_line(key_node)}: unknown key {key!r} "
                f"(expected one of {sorted(allowed)})"
            )


def _find_value(node: yaml.MappingNode, key: str) -> yaml.Node | None:
    for key_node, value_node in node.value:
        if key_node.value == key:
            result: yaml.Node = value_node
            return result
    return None


def _check_light_node(node: yaml.Node, path: Path) -> None:
    _check_mapping_keys(node, _LIGHT_KEYS, path)
    assert isinstance(node, yaml.MappingNode)
    to_node = _find_value(node, "to")
    if to_node is not None:
        _check_mapping_keys(to_node, _LIGHT_TARGET_KEYS, path)


def _check_audio_node(node: yaml.Node, path: Path) -> None:
    _check_mapping_keys(node, _AUDIO_KEYS, path)


def _check_device_block_holder(node: yaml.MappingNode, path: Path, allowed: set[str]) -> None:
    """Shared by `on_cancel` and `snooze`: both are `{light: ..., audio:
    ...}`-shaped mappings layered over the same light/audio vocabulary a
    step uses."""
    _check_mapping_keys(node, allowed, path)
    light_node = _find_value(node, "light")
    if light_node is not None:
        _check_light_node(light_node, path)
    audio_node = _find_value(node, "audio")
    if audio_node is not None:
        _check_audio_node(audio_node, path)


def _validate_routine_yaml_shape(text: str, path: Path) -> None:
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if root is None:
        raise ConfigError(f"{path}: empty routine file")
    if not isinstance(root, yaml.MappingNode):
        raise ConfigError(f"{path}:{_node_line(root)}: expected a mapping")
    _check_mapping_keys(root, _ROUTINE_KEYS, path)

    trigger_node = _find_value(root, "trigger")
    if trigger_node is not None:
        _check_mapping_keys(trigger_node, _TRIGGER_KEYS, path)

    steps_node = _find_value(root, "steps")
    if steps_node is not None:
        if not isinstance(steps_node, yaml.SequenceNode):
            raise ConfigError(f"{path}:{_node_line(steps_node)}: 'steps' must be a list")
        for step_node in steps_node.value:
            _check_mapping_keys(step_node, _STEP_KEYS, path)
            assert isinstance(step_node, yaml.MappingNode)
            light_node = _find_value(step_node, "light")
            if light_node is not None:
                _check_light_node(light_node, path)
            audio_node = _find_value(step_node, "audio")
            if audio_node is not None:
                _check_audio_node(audio_node, path)
            on_cancel_node = _find_value(step_node, "on_cancel")
            if on_cancel_node is not None:
                assert isinstance(on_cancel_node, yaml.MappingNode)
                _check_device_block_holder(on_cancel_node, path, _ON_CANCEL_KEYS)

    snooze_node = _find_value(root, "snooze")
    if snooze_node is not None:
        assert isinstance(snooze_node, yaml.MappingNode)
        _check_device_block_holder(snooze_node, path, _SNOOZE_KEYS)


def parse_routine_text(text: str, source: str | Path) -> Routine:
    """Validate and parse routine YAML/JSON already in memory — the shared
    core of `load_routine` (a file on disk) and the task 07 REST upload
    endpoint (`PUT /api/routines/{id}`, a request body). `source` is only
    used to name the offending file/upload in error messages; JSON is valid
    YAML 1.1, so no separate JSON code path is needed."""
    path = Path(source)
    _validate_routine_yaml_shape(text, path)
    data = yaml.safe_load(text)
    try:
        return Routine.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def load_routine(path: str | Path) -> Routine:
    """Load and validate a routine YAML file. An unknown key at any nesting
    level is a hard `ConfigError` naming the offending file and line."""
    path = Path(path)
    text = path.read_text()
    return parse_routine_text(text, path)


def export_schema() -> dict[str, Any]:
    """The routine JSON Schema (published to routines/schema.json),
    generated from the same Pydantic models the loader validates against —
    one source of truth, per CLAUDE.md "config over code"."""
    return Routine.model_json_schema(by_alias=True)


# --- state machine -----------------------------------------------------


class RoutineState(StrEnum):
    IDLE = "IDLE"
    WINDDOWN = "WINDDOWN"
    ASLEEP = "ASLEEP"
    SUNRISE = "SUNRISE"
    ALARM = "ALARM"
    SNOOZE = "SNOOZE"
    AWAKE = "AWAKE"


@dataclass(frozen=True, slots=True)
class StepWindow:
    step: Step
    start: datetime
    end: datetime | None  # None = open-ended (until_cancel, or an unbounded at_offset step)

    def is_active(self, now: datetime) -> bool:
        if now < self.start:
            return False
        return self.end is None or now < self.end

    def progress(self, now: datetime) -> float:
        """Fraction elapsed through this window, clamped to [0, 1]."""
        if self.end is None:
            return 1.0
        total = (self.end - self.start).total_seconds()
        if total <= 0:
            return 1.0
        return max(0.0, min(1.0, (now - self.start).total_seconds() / total))


def compute_step_windows(
    routine: Routine, started_at: datetime, trigger_at: datetime | None
) -> list[StepWindow]:
    """Every step's `[start, end)` in wall-clock time, derived fresh from
    `started_at`/`trigger_at` and the routine's own steps — no accumulator,
    so this is safe to call on every tick and after a restart
    (docs/06-routine-engine.md: "position recomputed from wall clock on
    every tick and on startup"). Duration steps chain sequentially from
    `started_at`; `at_offset` steps anchor independently to `trigger_at` and
    may overlap the chain (docs/06: "the chime overlaps the tail of the
    sunrise, which is the point")."""
    windows: list[StepWindow] = []
    cursor = started_at
    for step in routine.steps:
        if step.at_offset is not None:
            if trigger_at is None:
                raise RoutineError(
                    f"step {step.id!r} uses 'at_offset' but the routine has no trigger_at"
                )
            windows.append(StepWindow(step, trigger_at + step.at_offset, None))
            continue

        start = cursor
        end: datetime | None
        if step.ends_at == "trigger":
            if trigger_at is None:
                raise RoutineError(f"step {step.id!r} has ends_at: trigger but no trigger_at")
            end = trigger_at
        elif step.duration in ("until_cancel", "until_next_step"):
            end = None  # "until_next_step" is backfilled below
        else:
            assert isinstance(step.duration, timedelta)
            end = start + step.duration
        windows.append(StepWindow(step, start, end))
        if end is not None:
            cursor = end

    for i, window in enumerate(windows):
        if (
            window.step.duration == "until_next_step"
            and window.end is None
            and i + 1 < len(windows)
        ):
            windows[i] = StepWindow(window.step, window.start, windows[i + 1].start)

    return windows


@dataclass(slots=True)
class RoutineRun:
    """The state of one routine execution. Reconstructible in full from
    `(routine, started_at, trigger_at, state, snooze_count, snooze_until,
    alarm_entered_at, escalated)` — `compute_step_windows` derives the
    active step and its progress fresh from those fields plus the wall
    clock every time, so nothing else about a run's position is ever
    carried across a restart (docs/06-routine-engine.md `RoutineRun`)."""

    routine: Routine
    started_at: datetime
    trigger_at: datetime | None
    state: RoutineState
    current_step: str | None = None
    snooze_count: int = 0
    snooze_until: datetime | None = None
    alarm_entered_at: datetime | None = None
    escalated: bool = False


_SILENT_FLOOR_DB = -60.0
_DEFAULT_INITIAL_GAIN_DB = -45.0
_ESCALATION_STEP_DB = 6.0


def _parse_audio_source(raw: str) -> AudioSource:
    """Thin wrapper over the shared `drivers.audio.base.parse_audio_source`
    (task 07 factored it out so the REST `audio.play` action parses sources
    the same way) that re-raises as `RoutineError` — a routine's own domain
    exception — rather than the driver layer's plain `ValueError`."""
    try:
        return parse_audio_source(raw)
    except ValueError as exc:
        raise RoutineError(str(exc)) from exc


class RoutineEngine:
    """Executes routine runs. Tick-driven like `Scheduler` — see the module
    docstring. Exactly one `RoutineRun` is active at a time; starting a new
    one cancels the current run, running its active step's `on_cancel`
    first (docs/06: "each step gets an on_cancel that restores or releases
    devices")."""

    def __init__(
        self,
        light: Light,
        audio: AudioOutput,
        clock: Clock,
        event_bus: EventBus,
        *,
        curves_dir: Path,
        tick_s: float = 5.0,
    ) -> None:
        self._light = light
        self._audio = audio
        self._clock = clock
        self._event_bus = event_bus
        self._curves_dir = curves_dir
        self._tick_s = tick_s
        self._curve_cache: dict[str, Curve] = {}
        self._run: RoutineRun | None = None
        self._entered_step_ids: set[str] = set()
        self._sleep_timer_fired: set[str] = set()
        self._previously_active_ids: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def current_run(self) -> RoutineRun | None:
        return self._run

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            await self._clock.sleep(self._tick_s)
            if not self._running:
                return
            await self.tick()

    # --- lifecycle -----------------------------------------------------

    async def start_routine(
        self, routine: Routine, *, trigger_at: datetime | None = None
    ) -> RoutineRun:
        """Start `routine`, cancelling and cleaning up any run already in
        progress (tasks/05-routine-engine.md: "starting another cancels the
        first and runs its on_cancel")."""
        if routine.trigger.type == "alarm" and trigger_at is None:
            raise RoutineError(f"routine {routine.id!r} has an alarm trigger and needs trigger_at")

        now = self._clock.now()
        if self._run is not None:
            await self._cancel_current(now)

        state = self._initial_state(routine, now, trigger_at)
        run = RoutineRun(routine=routine, started_at=now, trigger_at=trigger_at, state=state)
        if state == RoutineState.ALARM:
            run.alarm_entered_at = now
        self._begin_run(run)
        await self._emit_transition(run, previous_state=None)
        await self.tick()
        return run

    def resume(self, run: RoutineRun) -> None:
        """Adopt an already-constructed `RoutineRun` after a restart. No
        cancellation, no transition event — the process crashed, it didn't
        transition. The next `tick()` recomputes position from the wall
        clock exactly as it would have if the process had never died."""
        self._begin_run(run)

    def _begin_run(self, run: RoutineRun) -> None:
        self._run = run
        self._entered_step_ids = set()
        self._sleep_timer_fired = set()
        self._previously_active_ids = set()

    def _initial_state(
        self, routine: Routine, now: datetime, trigger_at: datetime | None
    ) -> RoutineState:
        if routine.trigger.type == "alarm":
            assert trigger_at is not None
            return RoutineState.ALARM if now >= trigger_at else RoutineState.SUNRISE
        return RoutineState.WINDDOWN

    async def stop_routine(self) -> None:
        """Cancel the active run outright (e.g. a manual stop), running its
        active step's `on_cancel`."""
        if self._run is None:
            return
        await self._cancel_current(self._clock.now())
        self._run = None

    async def _cancel_current(self, now: datetime) -> None:
        run = self._run
        if run is None:
            return
        for window in self._active_windows(run, now):
            on_cancel = window.step.on_cancel
            if on_cancel is not None:
                await self._apply_light_action(on_cancel.light)
                await self._apply_audio_action(on_cancel.audio)

    def _active_windows(self, run: RoutineRun, now: datetime) -> list[StepWindow]:
        windows = compute_step_windows(run.routine, run.started_at, run.trigger_at)
        return [w for w in windows if w.is_active(now)]

    # --- ticking ---------------------------------------------------------

    async def tick(self) -> None:
        run = self._run
        if run is None:
            return
        now = self._clock.now()

        previous_state = run.state
        new_state = self._recompute_state(run, now)
        if new_state != previous_state:
            run.state = new_state
            if new_state == RoutineState.ALARM:
                run.alarm_entered_at = now
                run.escalated = False
                # Re-arm currently active steps' edge-triggered actions so a
                # re-fire from SNOOZE actually sounds again — their `audio`
                # was already "entered" the first time the alarm fired, and
                # `stop()` was called on snooze, so without this the chime
                # would stay silent forever after the first snooze.
                for window in self._active_windows(run, now):
                    self._entered_step_ids.discard(window.step.id)
                    self._sleep_timer_fired.discard(window.step.id)
            await self._emit_transition(run, previous_state)

        if run.state in (RoutineState.IDLE, RoutineState.AWAKE):
            return

        active = self._active_windows(run, now)
        if active:
            run.current_step = active[-1].step.id

        active_ids = {w.step.id for w in active}
        exited_ids = self._previously_active_ids - active_ids
        if exited_ids:
            await self._finalize_exited_steps(run, exited_ids)
        self._previously_active_ids = active_ids

        for window in active:
            await self._apply_step(window, now)

        await self._maybe_escalate(run, active, now)

    async def _finalize_exited_steps(self, run: RoutineRun, exited_ids: set[str]) -> None:
        """A curve-based ramp's window ending mid-tick (the common case,
        since ticks land on a fixed cadence, not on the window's exact
        boundary) must still land on its exact target — mirroring
        `sunrise.run_ramp`'s own final apply after its loop exits, so a
        30-minute sunrise really ends at `to.brightness`, not at whatever
        the last 15-second-early sample happened to compute."""
        all_windows = compute_step_windows(run.routine, run.started_at, run.trigger_at)
        windows_by_id = {w.step.id: w for w in all_windows}
        for step_id in exited_ids:
            window = windows_by_id.get(step_id)
            if window is None or window.step.light is None or window.step.light.curve is None:
                continue
            await self._finalize_curve_step(window.step.light)

    async def _finalize_curve_step(self, light: LightBlock) -> None:
        assert light.curve is not None
        curve = self._get_curve(light.curve)
        target_brightness = 1.0
        if light.to is not None and light.to.brightness is not None:
            target_brightness = light.to.brightness
        final_curve_t = 0.0 if light.reverse else 1.0
        brightness = max(
            curve.brightness(final_curve_t) * target_brightness,
            self._light.capabilities.min_brightness,
        )
        state = color_at(curve, self._light, final_curve_t, brightness)
        await self._light.apply(state, transition_ms=1000)

    def _recompute_state(self, run: RoutineRun, now: datetime) -> RoutineState:
        state = run.state
        if state == RoutineState.WINDDOWN:
            windows = compute_step_windows(run.routine, run.started_at, run.trigger_at)
            if windows and now >= windows[-1].start:
                return RoutineState.ASLEEP
            return state
        if state == RoutineState.SUNRISE:
            if run.trigger_at is not None and now >= run.trigger_at:
                return RoutineState.ALARM
            return state
        if state == RoutineState.SNOOZE:
            if run.snooze_until is not None and now >= run.snooze_until:
                return RoutineState.ALARM
            return state
        return state

    async def _apply_step(self, window: StepWindow, now: datetime) -> None:
        step = window.step
        first_tick = step.id not in self._entered_step_ids
        self._entered_step_ids.add(step.id)

        if step.light is not None:
            await self._apply_light_block(step.light, window, now, first_tick=first_tick)
        if step.audio is not None:
            if first_tick:
                await self._apply_audio_action(step.audio)
            if step.audio.continue_ and step.audio.sleep_timer is not None:
                await self._apply_sleep_timer(step, window, now)

    async def _apply_light_block(
        self, light: LightBlock, window: StepWindow, now: datetime, *, first_tick: bool
    ) -> None:
        """Curve-based blocks are level-driven: reapplied every tick the
        step is active, since they're a ramp in progress. Direct-target
        blocks (`off`, fixed `brightness`/`cct`) are edge-driven: applied
        once on entry, since there's nothing to progress toward."""
        if light.hold:
            return
        if light.curve is not None:
            curve = self._get_curve(light.curve)
            target_brightness = 1.0
            if light.to is not None and light.to.brightness is not None:
                target_brightness = light.to.brightness
            wall_t = window.progress(now)
            curve_t = (1.0 - wall_t) if light.reverse else wall_t
            brightness = max(
                curve.brightness(curve_t) * target_brightness,
                self._light.capabilities.min_brightness,
            )
            state = color_at(curve, self._light, curve_t, brightness)
            await self._light.apply(state, transition_ms=self._transition_ms(light))
            return
        if not first_tick:
            return
        if light.off:
            await self._light.apply(off_state())
        elif light.brightness is not None or light.cct is not None:
            await self._light.apply(
                LightState(
                    on=True,
                    brightness=light.brightness if light.brightness is not None else 1.0,
                    cct=light.cct,
                    rgb=None,
                ),
                transition_ms=self._transition_ms(light),
            )

    def _transition_ms(self, light: LightBlock) -> int:
        if light.transition is not None:
            return int(light.transition.total_seconds() * 1000)
        return self._light.capabilities.recommended_step_interval_ms

    def _get_curve(self, name: str) -> Curve:
        curve = self._curve_cache.get(name)
        if curve is None:
            curve = load_curve(self._curves_dir / f"{name}.yaml")
            self._curve_cache[name] = curve
        return curve

    async def _apply_light_action(self, light: LightBlock | None) -> None:
        """One-shot light application used by `on_cancel` and snooze —
        those blocks only ever say `off` or `hold`, never `curve`."""
        if light is None or light.hold:
            return
        if light.off:
            await self._light.apply(off_state())
        elif light.brightness is not None or light.cct is not None:
            await self._light.apply(
                LightState(
                    on=True,
                    brightness=light.brightness if light.brightness is not None else 1.0,
                    cct=light.cct,
                    rgb=None,
                )
            )

    async def _apply_audio_action(self, audio: AudioBlock | None) -> None:
        if audio is None:
            return
        if audio.stop:
            await self._audio.stop()
            return
        if audio.source is not None:
            source = _parse_audio_source(audio.source)
            initial_gain = audio.gain_db if audio.gain_db is not None else _DEFAULT_INITIAL_GAIN_DB
            if audio.fade_in is not None:
                await self._audio.play(source, gain_db=_SILENT_FLOOR_DB)
                await self._audio.ramp_gain(
                    to_db=initial_gain, over_s=audio.fade_in.total_seconds()
                )
            else:
                await self._audio.play(source, gain_db=initial_gain)
            if audio.ramp_to_db is not None and audio.over is not None:
                await self._audio.ramp_gain(
                    to_db=audio.ramp_to_db, over_s=audio.over.total_seconds()
                )

    async def _apply_sleep_timer(self, step: Step, window: StepWindow, now: datetime) -> None:
        assert step.audio is not None and step.audio.sleep_timer is not None
        if step.id in self._sleep_timer_fired:
            return
        elapsed = now - window.start
        fade_out = step.audio.fade_out or timedelta(0)
        if elapsed >= step.audio.sleep_timer + fade_out:
            self._sleep_timer_fired.add(step.id)
            await self._audio.stop()
        elif elapsed >= step.audio.sleep_timer:
            self._sleep_timer_fired.add(step.id)
            await self._audio.ramp_gain(to_db=_SILENT_FLOOR_DB, over_s=fade_out.total_seconds())

    async def _maybe_escalate(
        self, run: RoutineRun, active: list[StepWindow], now: datetime
    ) -> None:
        """docs/04-audio-subsystem.md "Escalation": step the ceiling up once
        if the alarm has sounded for `escalate_after` with no interaction."""
        if run.state != RoutineState.ALARM or run.escalated or run.alarm_entered_at is None:
            return
        escalate_after = next(
            (w.step.escalate_after for w in active if w.step.escalate_after is not None), None
        )
        if escalate_after is None or now - run.alarm_entered_at < escalate_after:
            return
        run.escalated = True
        ceiling = next(
            (
                w.step.audio.ramp_to_db
                for w in active
                if w.step.audio is not None and w.step.audio.ramp_to_db is not None
            ),
            _DEFAULT_INITIAL_GAIN_DB,
        )
        await self._audio.ramp_gain(to_db=ceiling + _ESCALATION_STEP_DB, over_s=1.0)

    async def _force_escalate(self, run: RoutineRun) -> None:
        run.escalated = True
        await self._audio.ramp_gain(
            to_db=_DEFAULT_INITIAL_GAIN_DB + 2 * _ESCALATION_STEP_DB, over_s=1.0
        )

    # --- user actions ------------------------------------------------------

    async def snooze(self) -> None:
        """Snooze semantics from docs/06-routine-engine.md: during `ALARM`,
        stop audio and schedule a re-fire; during `SUNRISE` (before the
        alarm has actually fired) it's dismiss-for-today, not snooze;
        `max` snoozes forces full escalation and refuses further snoozes."""
        run = self._require_run()
        if run.state == RoutineState.SUNRISE:
            await self.dismiss()
            return
        if run.state != RoutineState.ALARM:
            raise RoutineError(f"cannot snooze while in state {run.state}")
        snooze_cfg = run.routine.snooze
        if snooze_cfg is None:
            raise RoutineError(f"routine {run.routine.id!r} has no snooze configuration")

        run.snooze_count += 1
        if run.snooze_count > snooze_cfg.max:
            await self._force_escalate(run)
            return

        now = self._clock.now()
        previous = run.state
        run.snooze_until = now + snooze_cfg.duration
        run.state = RoutineState.SNOOZE
        await self._apply_light_action(snooze_cfg.light)
        await self._apply_audio_action(snooze_cfg.audio)
        await self._emit(
            EventType.ALARM_SNOOZED,
            {"routine_id": run.routine.id, "snooze_count": run.snooze_count},
        )
        await self._emit_transition(run, previous)

    async def dismiss(self) -> None:
        run = self._require_run()
        if run.state not in (RoutineState.ALARM, RoutineState.SNOOZE, RoutineState.SUNRISE):
            raise RoutineError(f"cannot dismiss while in state {run.state}")
        previous = run.state
        await self._audio.stop()
        run.state = RoutineState.AWAKE
        await self._emit_transition(run, previous)

    async def complete(self) -> None:
        """Return an `AWAKE` run to `IDLE`, per the state diagram's
        "complete / cancel" edge back to `IDLE`."""
        run = self._require_run()
        if run.state != RoutineState.AWAKE:
            raise RoutineError(f"cannot complete while in state {run.state}")
        previous = run.state
        run.state = RoutineState.IDLE
        await self._emit_transition(run, previous)
        self._run = None

    def _require_run(self) -> RoutineRun:
        if self._run is None:
            raise RoutineError("no routine is currently running")
        return self._run

    async def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        await self._event_bus.publish(Event(type=event_type, payload=payload))

    async def _emit_transition(
        self, run: RoutineRun, previous_state: RoutineState | None
    ) -> None:
        await self._emit(
            EventType.ROUTINE_TRANSITION,
            {
                "routine_id": run.routine.id,
                "from": previous_state.value if previous_state is not None else None,
                "to": run.state.value,
                "step": run.current_step,
            },
        )

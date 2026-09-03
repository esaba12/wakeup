"""The single authoritative in-memory state object. See docs/07-api-and-state.md.

`AppState` is built fresh, on demand, from the live components it reflects
(`Scheduler`, `RoutineEngine`, `Light`, `AudioOutput`, `Clock`) — never
cached and never mutated in place, per docs/00-overview.md rule 1 ("wall
clock is truth... recomputes its position from `datetime.now(tz)` on every
tick"). `progress` and `in_s` in particular are recomputed here, server-side,
every time `build_state()` runs, so a client with a wrong clock — or a
WebSocket delta arriving late — still renders correctly (docs/07: "clients
never compute derived state; they render what they're given").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from openrestore.core.clock import Clock
from openrestore.core.routines import RoutineEngine, RoutineRun, compute_step_windows
from openrestore.core.scheduler import Scheduler
from openrestore.drivers.audio.base import AudioOutput, format_audio_source
from openrestore.drivers.light.base import Light


@dataclass(frozen=True, slots=True)
class ClockView:
    now: datetime
    tz: str
    synced: bool
    source: str | None


@dataclass(frozen=True, slots=True)
class RoutineView:
    id: str | None
    state: str
    step: str | None
    started_at: datetime | None
    trigger_at: datetime | None
    progress: float | None


@dataclass(frozen=True, slots=True)
class LightView:
    id: str
    reachable: bool
    on: bool
    brightness: float
    cct: int | None


@dataclass(frozen=True, slots=True)
class AudioView:
    output: str
    available: bool
    playing: str | None
    gain_db: float


@dataclass(frozen=True, slots=True)
class NextAlarmView:
    id: str
    at: datetime
    in_s: int
    skipped: bool


@dataclass(frozen=True, slots=True)
class AppState:
    clock: ClockView
    routine: RoutineView
    light: LightView
    audio: AudioView
    next_alarm: NextAlarmView | None
    health: str


def _routine_view(run: RoutineRun | None, now: datetime) -> RoutineView:
    if run is None:
        return RoutineView(
            id=None, state="IDLE", step=None, started_at=None, trigger_at=None, progress=None
        )
    windows = compute_step_windows(run.routine, run.started_at, run.trigger_at)
    active = [w for w in windows if w.is_active(now)]
    progress = active[-1].progress(now) if active else None
    return RoutineView(
        id=run.routine.id,
        state=run.state.value,
        step=run.current_step,
        started_at=run.started_at,
        trigger_at=run.trigger_at,
        progress=progress,
    )


async def _light_view(light: Light) -> LightView:
    state = await light.get()
    reachable = await light.is_reachable()
    return LightView(
        id=light.id, reachable=reachable, on=state.on, brightness=state.brightness, cct=state.cct
    )


async def _audio_view(audio: AudioOutput) -> AudioView:
    state = await audio.get()
    available = await audio.is_available()
    return AudioView(
        output=audio.id,
        available=available,
        playing=format_audio_source(state.playing),
        gain_db=state.gain_db,
    )


async def _next_alarm_view(scheduler: Scheduler, now: datetime) -> NextAlarmView | None:
    """The soonest upcoming `alarm_fire` (not `ramp_start`) across every
    enabled alarm — read-only, via `Scheduler.next_events()`, which never
    mutates occurrence state (docs/05-scheduler.md)."""
    alarm_count = len(scheduler.list_alarms())
    for scheduled in await scheduler.next_events(limit=max(1, alarm_count * 2)):
        if scheduled.kind != "alarm_fire":
            continue
        alarm = scheduler.get_alarm(scheduled.alarm_id)
        skipped = alarm.skip_next if alarm is not None else False
        in_s = max(0, round((scheduled.at - now).total_seconds()))
        return NextAlarmView(id=scheduled.alarm_id, at=scheduled.at, in_s=in_s, skipped=skipped)
    return None


async def build_state(
    *,
    clock: Clock,
    tz: str,
    scheduler: Scheduler,
    routine_engine: RoutineEngine,
    light: Light,
    audio: AudioOutput,
    clock_source: str = "system",
) -> AppState:
    """Assemble the full state object fresh. Called on every `GET
    /api/state`, on every new WebSocket connection, and on every periodic
    or event-driven WebSocket tick — cheap enough (a handful of driver
    round-trips) to never cache."""
    now = clock.now()
    synced = scheduler.clock_synced
    clock_view = ClockView(now=now, tz=tz, synced=synced, source=clock_source if synced else None)
    routine_view = _routine_view(routine_engine.current_run, now)
    light_view = await _light_view(light)
    audio_view = await _audio_view(audio)
    next_alarm = await _next_alarm_view(scheduler, now)
    return AppState(
        clock=clock_view,
        routine=routine_view,
        light=light_view,
        audio=audio_view,
        next_alarm=next_alarm,
        health=scheduler.health,
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def state_to_dict(state: AppState) -> dict[str, Any]:
    """The exact JSON shape from docs/07-api-and-state.md. JSON only,
    ISO-8601 timestamps with UTC offsets (never naive, never `Z`)."""
    return {
        "clock": {
            "now": _iso(state.clock.now),
            "tz": state.clock.tz,
            "synced": state.clock.synced,
            "source": state.clock.source,
        },
        "routine": {
            "id": state.routine.id,
            "state": state.routine.state,
            "step": state.routine.step,
            "started_at": _iso(state.routine.started_at),
            "trigger_at": _iso(state.routine.trigger_at),
            "progress": state.routine.progress,
        },
        "light": {
            "id": state.light.id,
            "reachable": state.light.reachable,
            "on": state.light.on,
            "brightness": state.light.brightness,
            "cct": state.light.cct,
        },
        "audio": {
            "output": state.audio.output,
            "available": state.audio.available,
            "playing": state.audio.playing,
            "gain_db": state.audio.gain_db,
        },
        "next_alarm": (
            None
            if state.next_alarm is None
            else {
                "id": state.next_alarm.id,
                "at": _iso(state.next_alarm.at),
                "in_s": state.next_alarm.in_s,
                "skipped": state.next_alarm.skipped,
            }
        ),
        "health": state.health,
    }


def state_delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Shallow top-level diff: a changed top-level key (`clock`, `routine`,
    `light`, `audio`, `next_alarm`, `health`) carries its whole sub-object,
    unchanged keys are omitted entirely. Keeps WebSocket deltas well under
    1 KB during a ramp (docs/07 acceptance criteria) since each sub-object
    is a handful of scalar fields, and most ticks only change `clock` and
    one of `routine`/`light`."""
    return {key: value for key, value in current.items() if previous.get(key) != value}

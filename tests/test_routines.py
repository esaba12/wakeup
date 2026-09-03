from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from openrestore.core.clock import FakeClock
from openrestore.core.errors import ConfigError, RoutineError
from openrestore.core.events import Event, EventBus, EventType, Handler
from openrestore.core.routines import (
    RoutineEngine,
    RoutineRun,
    RoutineState,
    compute_step_windows,
    load_routine,
    parse_duration,
)
from openrestore.drivers.audio.mock import MockAudioOutput
from openrestore.drivers.light.mock import MockLight

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTINES_DIR = REPO_ROOT / "routines"
CURVES_DIR = REPO_ROOT / "curves"


def _events_collector(events: list[Event]) -> Handler:
    async def _collect(event: Event) -> None:
        events.append(event)

    return _collect


def _engine(
    clock: FakeClock,
) -> tuple[RoutineEngine, MockLight, MockAudioOutput, list[Event]]:
    light = MockLight(clock)
    audio = MockAudioOutput(clock)
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(_events_collector(events))
    engine = RoutineEngine(light, audio, clock, bus, curves_dir=CURVES_DIR)
    return engine, light, audio, events


def _weekday_wake():
    return load_routine(ROUTINES_DIR / "weekday-wake.yaml")


def _winddown():
    return load_routine(ROUTINES_DIR / "winddown.yaml")


# --- duration parsing --------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_seconds"),
    [("30m", 1800), ("90s", 90), ("-3m", -180), ("1h", 3600), ("0s", 0)],
)
def test_parse_duration(raw: str, expected_seconds: int) -> None:
    assert parse_duration(raw) == timedelta(seconds=expected_seconds)


def test_parse_duration_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_duration("thirty minutes")


# --- schema validation ---------------------------------------------------


def test_shipped_routines_validate() -> None:
    wake = _weekday_wake()
    assert wake.id == "weekday-wake"
    assert [s.id for s in wake.steps] == ["sunrise", "chime"]
    winddown = _winddown()
    assert winddown.id == "winddown"
    assert [s.id for s in winddown.steps] == ["settle", "dim", "sleep"]


def test_typo_key_fails_at_load_with_line_number(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: 1\n"
        "name: bad\n"
        "id: bad\n"
        "trigger: { type: time, at: '22:30' }\n"
        "steps:\n"
        "  - id: only\n"
        "    duration: 10m\n"
        "    ligth: { brightness: 0.5 }\n"  # typo: ligth
    )
    with pytest.raises(ConfigError) as excinfo:
        load_routine(bad)
    message = str(excinfo.value)
    assert "ligth" in message
    assert f"{bad}:8" in message


def test_missing_version_is_a_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\nid: bad\ntrigger: { type: time, at: '22:30' }\n"
        "steps:\n  - id: only\n    duration: 10m\n"
    )
    with pytest.raises(ConfigError):
        load_routine(bad)


def test_step_must_set_exactly_one_of_duration_or_at_offset(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: 1\nname: bad\nid: bad\ntrigger: { type: time, at: '22:30' }\n"
        "steps:\n  - id: only\n    duration: 10m\n    at_offset: -3m\n"
    )
    with pytest.raises(ConfigError):
        load_routine(bad)


def test_at_offset_step_without_trigger_ref_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: 1\nname: bad\nid: bad\ntrigger: { type: time, at: '22:30' }\n"
        "steps:\n  - id: only\n    at_offset: -3m\n"
    )
    with pytest.raises(ConfigError):
        load_routine(bad)


# --- step windows ----------------------------------------------------------


def test_sequential_duration_steps_chain() -> None:
    routine = _winddown()
    start = FakeClock().now()
    windows = compute_step_windows(routine, start, None)
    assert windows[0].start == start
    assert windows[0].end == start + timedelta(minutes=10)
    assert windows[1].start == windows[0].end
    assert windows[1].end == windows[1].start + timedelta(minutes=20)
    assert windows[2].start == windows[1].end
    assert windows[2].end is None  # until_cancel


def test_at_offset_step_anchors_to_trigger_and_overlaps() -> None:
    routine = _weekday_wake()
    start = FakeClock().now()
    trigger_at = start + timedelta(minutes=30)
    windows = compute_step_windows(routine, start, trigger_at)
    sunrise, chime = windows
    assert sunrise.start == start
    assert sunrise.end == trigger_at  # ends_at: trigger
    assert chime.start == trigger_at - timedelta(minutes=3)
    # chime overlaps the tail of sunrise
    assert chime.start < sunrise.end


def test_until_next_step_ends_when_the_next_step_starts() -> None:
    routine = _winddown()
    routine.steps[2].duration = "until_next_step"  # type: ignore[assignment]
    routine.steps.append(
        routine.steps[2].model_copy(update={"id": "extra", "duration": timedelta(minutes=5)})
    )
    start = FakeClock().now()
    windows = compute_step_windows(routine, start, None)
    assert windows[2].end == windows[3].start


# --- executor: full run end-to-end -----------------------------------------


async def test_weekday_wake_runs_end_to_end_under_two_seconds_wall_time(
    fake_clock: FakeClock,
) -> None:
    import time

    engine, light, audio, events = _engine(fake_clock)
    routine = _weekday_wake()
    trigger_at = fake_clock.now() + timedelta(minutes=30)

    wall_start = time.monotonic()
    run = await engine.start_routine(routine, trigger_at=trigger_at)
    assert run.state == RoutineState.SUNRISE

    for _ in range(200):  # 200 * 15s = 50 minutes of routine wall time
        fake_clock.advance(15)
        await engine.tick()
    wall_elapsed = time.monotonic() - wall_start

    assert wall_elapsed < 2.0
    assert run.state == RoutineState.ALARM
    assert light.history, "sunrise ramp should have applied light states"
    assert light.history[-1].state.brightness == pytest.approx(0.9)
    assert any(call.action == "play" for call in audio.history)
    transitions = [e for e in events if e.type == EventType.ROUTINE_TRANSITION]
    assert [t.payload["to"] for t in transitions] == ["SUNRISE", "ALARM"]


async def test_winddown_transitions_windown_to_asleep(fake_clock: FakeClock) -> None:
    engine, light, audio, _events = _engine(fake_clock)
    routine = _winddown()

    run = await engine.start_routine(routine)
    assert run.state == RoutineState.WINDDOWN

    for _ in range(200):  # 200*15s = 50 minutes, covers 10+20m then into sleep
        fake_clock.advance(15)
        await engine.tick()
        if run.state == RoutineState.ASLEEP:
            break

    assert run.state == RoutineState.ASLEEP
    assert run.current_step == "sleep"
    assert light.history[-1].state.on is False


# --- restart / resume -------------------------------------------------------


async def test_kill_and_reconstruct_resumes_at_correct_step_and_position(
    fake_clock: FakeClock,
) -> None:
    routine = _weekday_wake()
    trigger_at = fake_clock.now() + timedelta(minutes=30)

    engine_a, light_a, _audio_a, _ = _engine(fake_clock)
    run_a = await engine_a.start_routine(routine, trigger_at=trigger_at)

    # advance to 10 different points and, at each, "kill" the engine and
    # reconstruct a fresh one purely from (routine, started_at, trigger_at,
    # state) — no shared state with engine_a.
    checkpoints = [30, 45, 60, 90, 150, 300, 600, 900, 1200, 1750]
    previous_elapsed = 0.0
    for elapsed_s in checkpoints:
        fake_clock.advance(elapsed_s - previous_elapsed)
        previous_elapsed = elapsed_s
        await engine_a.tick()

        snapshot = RoutineRun(
            routine=run_a.routine,
            started_at=run_a.started_at,
            trigger_at=run_a.trigger_at,
            state=run_a.state,
            snooze_count=run_a.snooze_count,
            snooze_until=run_a.snooze_until,
            alarm_entered_at=run_a.alarm_entered_at,
            escalated=run_a.escalated,
        )

        engine_b, light_b, _audio_b, _ = _engine(fake_clock)
        engine_b.resume(snapshot)
        await engine_b.tick()

        assert engine_b.current_run is not None
        assert engine_b.current_run.state == run_a.state
        assert engine_b.current_run.current_step == run_a.current_step
        if light_a.history and light_b.history:
            assert light_b.history[-1].state == light_a.history[-1].state


# --- until_cancel steps don't leak timers -----------------------------------


async def test_until_cancel_step_runs_indefinitely_without_leaking_timers(
    fake_clock: FakeClock,
) -> None:
    engine, light, _audio, _events = _engine(fake_clock)
    routine = _winddown()
    run = await engine.start_routine(routine)

    for _ in range(200):
        fake_clock.advance(15)
        await engine.tick()
        if run.state == RoutineState.ASLEEP:
            break
    assert run.state == RoutineState.ASLEEP

    # a RoutineEngine has no per-step asyncio.Task: only its own background
    # loop task exists (and only once started). Ticking hundreds more times
    # while parked in an until_cancel step must not grow any task/timer set.
    import asyncio

    tasks_before = len(asyncio.all_tasks())
    for _ in range(500):
        fake_clock.advance(3600)
        await engine.tick()
    tasks_after = len(asyncio.all_tasks())

    assert tasks_after == tasks_before
    assert run.state == RoutineState.ASLEEP
    assert light.history[-1].state.on is False


# --- starting routine B while A runs ---------------------------------------


async def test_starting_routine_b_cancels_a_and_runs_on_cancel(fake_clock: FakeClock) -> None:
    engine, light, _audio, _events = _engine(fake_clock)
    wake = _weekday_wake()
    winddown = _winddown()

    trigger_at = fake_clock.now() + timedelta(minutes=30)
    await engine.start_routine(wake, trigger_at=trigger_at)

    # advance partway into the sunrise ramp so the light is mid-brightness
    for _ in range(10):
        fake_clock.advance(15)
        await engine.tick()
    mid_ramp_brightness = light.history[-1].state.brightness
    assert 0.0 < mid_ramp_brightness < 0.9

    # starting winddown cancels the sunrise run; sunrise's on_cancel says
    # `light: { off: true }`, so no orphaned mid-ramp brightness is left.
    run_b = await engine.start_routine(winddown)

    assert run_b.routine.id == "winddown"
    off_call = next(h for h in light.history if h.state.on is False)
    assert off_call is light.history[-2] or light.history[-2].state.on is False
    assert light.history[-2].state.on is False


# --- snooze semantics --------------------------------------------------------


async def test_snooze_during_alarm_stops_audio_and_schedules_refire(
    fake_clock: FakeClock,
) -> None:
    engine, _light, audio, _events = _engine(fake_clock)
    routine = _weekday_wake()
    trigger_at = fake_clock.now()  # start already at alarm time
    run = await engine.start_routine(routine, trigger_at=trigger_at)
    assert run.state == RoutineState.ALARM

    await engine.snooze()
    assert run.state == RoutineState.SNOOZE
    assert run.snooze_count == 1
    assert run.snooze_until == fake_clock.now() + timedelta(minutes=9)
    assert audio.playing is None

    history_len_before_refire = len(audio.history)
    fake_clock.advance(9 * 60)
    await engine.tick()
    assert run.state == RoutineState.ALARM

    # the re-fire must actually sound again, not stay silent because the
    # chime step's one-shot "play" was already consumed the first time.
    replayed = audio.history[history_len_before_refire:]
    assert any(call.action == "play" for call in replayed)


async def test_snooze_during_sunrise_dismisses_instead_of_snoozing(
    fake_clock: FakeClock,
) -> None:
    engine, _light, audio, events = _engine(fake_clock)
    routine = _weekday_wake()
    trigger_at = fake_clock.now() + timedelta(minutes=30)
    run = await engine.start_routine(routine, trigger_at=trigger_at)
    assert run.state == RoutineState.SUNRISE

    await engine.snooze()

    assert run.state == RoutineState.AWAKE
    assert run.snooze_count == 0  # never counted as a real snooze
    assert audio.playing is None
    snoozed_events = [e for e in events if e.type == EventType.ALARM_SNOOZED]
    assert snoozed_events == []


async def test_max_snoozes_forces_escalation_and_refuses_further_snoozes(
    fake_clock: FakeClock,
) -> None:
    engine, _light, audio, _events = _engine(fake_clock)
    routine = _weekday_wake()
    trigger_at = fake_clock.now()
    run = await engine.start_routine(routine, trigger_at=trigger_at)
    assert routine.snooze is not None
    max_snoozes = routine.snooze.max

    for _ in range(max_snoozes):
        await engine.snooze()
        assert run.state == RoutineState.SNOOZE
        fake_clock.advance(9 * 60)
        await engine.tick()
        assert run.state == RoutineState.ALARM

    history_len_before = len(audio.history)
    await engine.snooze()  # one snooze beyond max
    assert run.state == RoutineState.ALARM  # refused: stays in ALARM
    assert run.snooze_count == max_snoozes + 1
    assert len(audio.history) > history_len_before
    assert audio.history[-1].action == "ramp_gain"


async def test_snooze_without_an_active_run_raises() -> None:
    clock = FakeClock()
    engine, _light, _audio, _events = _engine(clock)
    with pytest.raises(RoutineError):
        await engine.snooze()

from __future__ import annotations

import json
from datetime import UTC, datetime, time
from pathlib import Path

from openrestore.core.clock import FakeClock
from openrestore.core.events import EventBus
from openrestore.core.routines import RoutineEngine, load_routine
from openrestore.core.scheduler import Alarm, Scheduler
from openrestore.core.state import build_state, state_delta, state_to_dict
from openrestore.core.store import Store
from openrestore.drivers.audio.mock import MockAudioOutput
from openrestore.drivers.light.mock import MockLight

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTINES_DIR = REPO_ROOT / "routines"
CURVES_DIR = REPO_ROOT / "curves"
NY = "America/New_York"


async def _components(
    db_path: Path, start: datetime, *, clock_synced: bool = True
) -> tuple[Scheduler, RoutineEngine, MockLight, MockAudioOutput, FakeClock, Store]:
    clock = FakeClock(start)
    store = await Store.open(db_path)
    bus = EventBus()
    scheduler = Scheduler(store, clock, bus, clock_synced=clock_synced)
    await scheduler.load()
    light = MockLight(clock)
    audio = MockAudioOutput(clock)
    engine = RoutineEngine(light, audio, clock, bus, curves_dir=CURVES_DIR)
    return scheduler, engine, light, audio, clock, store


async def test_build_state_idle_shape(tmp_path: Path) -> None:
    scheduler, engine, light, audio, clock, store = await _components(
        tmp_path / "db.sqlite", datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    )
    state = await build_state(
        clock=clock, tz="UTC", scheduler=scheduler, routine_engine=engine, light=light, audio=audio
    )
    assert state.routine.id is None
    assert state.routine.state == "IDLE"
    assert state.routine.progress is None
    assert state.next_alarm is None
    assert state.health == "ok"
    assert state.light.id == light.id
    assert state.audio.output == audio.id
    await store.close()


async def test_build_state_degraded_when_clock_unsynced(tmp_path: Path) -> None:
    scheduler, engine, light, audio, clock, store = await _components(
        tmp_path / "db.sqlite", datetime(2024, 6, 3, 6, 0, tzinfo=UTC), clock_synced=False
    )
    state = await build_state(
        clock=clock, tz="UTC", scheduler=scheduler, routine_engine=engine, light=light, audio=audio
    )
    assert state.health == "degraded"
    assert state.clock.synced is False
    assert state.clock.source is None
    await store.close()


async def test_next_alarm_reflects_soonest_alarm_fire(tmp_path: Path) -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)  # Monday
    scheduler, engine, light, audio, clock, store = await _components(
        tmp_path / "db.sqlite", start
    )
    await scheduler.upsert(
        Alarm(
            id="a1",
            enabled=True,
            time=time(6, 40),
            days={1, 2, 3, 4, 5},
            routine_id="weekday-wake",
            pre_roll_s=0,
            timezone=NY,
        )
    )
    state = await build_state(
        clock=clock, tz="UTC", scheduler=scheduler, routine_engine=engine, light=light, audio=audio
    )
    assert state.next_alarm is not None
    assert state.next_alarm.id == "a1"
    assert state.next_alarm.skipped is False
    assert state.next_alarm.in_s > 0
    await store.close()


async def test_next_alarm_skipped_flag(tmp_path: Path) -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    scheduler, engine, light, audio, clock, store = await _components(
        tmp_path / "db.sqlite", start
    )
    await scheduler.upsert(
        Alarm(
            id="a1",
            enabled=True,
            time=time(6, 40),
            days={1, 2, 3, 4, 5},
            routine_id="weekday-wake",
            pre_roll_s=0,
            timezone=NY,
        )
    )
    await scheduler.skip_next("a1")
    state = await build_state(
        clock=clock, tz="UTC", scheduler=scheduler, routine_engine=engine, light=light, audio=audio
    )
    assert state.next_alarm is not None
    assert state.next_alarm.skipped is True
    await store.close()


async def test_routine_progress_recomputed_from_wall_clock(tmp_path: Path) -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    scheduler, engine, light, audio, clock, store = await _components(
        tmp_path / "db.sqlite", start
    )
    routine = load_routine(ROUTINES_DIR / "winddown.yaml")
    await engine.start_routine(routine)

    state0 = await build_state(
        clock=clock, tz="UTC", scheduler=scheduler, routine_engine=engine, light=light, audio=audio
    )
    assert state0.routine.state == "WINDDOWN"
    assert state0.routine.step == "settle"
    assert state0.routine.progress == 0.0

    clock.advance(5 * 60)  # 5 of 10 minutes into "settle"
    state1 = await build_state(
        clock=clock, tz="UTC", scheduler=scheduler, routine_engine=engine, light=light, audio=audio
    )
    assert state1.routine.progress is not None
    assert abs(state1.routine.progress - 0.5) < 1e-9
    await store.close()


async def test_state_to_dict_uses_iso8601_with_offset(tmp_path: Path) -> None:
    scheduler, engine, light, audio, clock, store = await _components(
        tmp_path / "db.sqlite", datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    )
    state = await build_state(
        clock=clock, tz="UTC", scheduler=scheduler, routine_engine=engine, light=light, audio=audio
    )
    payload = state_to_dict(state)
    assert payload["clock"]["now"] == "2024-06-03T06:00:00+00:00"
    # round-trips through json without error, and every top-level key from
    # the spec's shape is present.
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert set(decoded.keys()) == {
        "clock",
        "routine",
        "light",
        "audio",
        "next_alarm",
        "health",
    }
    await store.close()


def test_state_delta_omits_unchanged_top_level_keys() -> None:
    previous = {
        "clock": {"now": "t0"},
        "routine": {"state": "IDLE"},
        "light": {"on": False},
        "audio": {"playing": None},
        "next_alarm": None,
        "health": "ok",
    }
    current = dict(previous)
    current["clock"] = {"now": "t1"}
    current["routine"] = {"state": "WINDDOWN"}
    delta = state_delta(previous, current)
    assert delta == {"clock": {"now": "t1"}, "routine": {"state": "WINDDOWN"}}


def test_state_delta_empty_when_nothing_changed() -> None:
    state = {"clock": {"now": "t0"}, "health": "ok"}
    assert state_delta(state, dict(state)) == {}

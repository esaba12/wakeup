from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from openrestore.core.clock import FakeClock
from openrestore.core.events import Event, EventBus, EventType, Handler
from openrestore.core.scheduler import (
    Alarm,
    Scheduler,
    candidate_dates,
    resolve_local_time,
)
from openrestore.core.store import Store

NY = "America/New_York"


def _alarm(
    *,
    id: str = "a1",
    hour: int,
    minute: int,
    days: set[int] | None = None,
    pre_roll_s: int = 0,
    timezone: str = NY,
    skip_next: bool = False,
) -> Alarm:
    return Alarm(
        id=id,
        enabled=True,
        time=time(hour, minute),
        days=days if days is not None else set(),
        routine_id="sunrise",
        pre_roll_s=pre_roll_s,
        timezone=timezone,
        skip_next=skip_next,
    )


def _events_collector(events: list[Event]) -> Handler:
    async def _collect(event: Event) -> None:
        events.append(event)

    return _collect


async def _make_scheduler(
    db_path: Path,
    start: datetime,
    *,
    catchup_s: float = 600.0,
    clock_synced: bool = True,
) -> tuple[Scheduler, FakeClock, Store, list[Event]]:
    clock = FakeClock(start)
    store = await Store.open(db_path)
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(_events_collector(events))
    scheduler = Scheduler(
        store, clock, bus, catchup_s=catchup_s, clock_synced=clock_synced
    )
    return scheduler, clock, store, events


def _fired(events: list[Event]) -> list[Event]:
    return [e for e in events if e.type == EventType.ALARM_FIRED]


def _missed(events: list[Event]) -> list[Event]:
    return [e for e in events if e.type == EventType.ALARM_MISSED]


# --- pure helpers ------------------------------------------------------


def test_resolve_local_time_returns_existing_time_unchanged() -> None:
    tz = ZoneInfo(NY)
    result = resolve_local_time(date(2024, 6, 1), time(6, 40), tz)
    assert (result.hour, result.minute) == (6, 40)


def test_resolve_local_time_spring_forward_gap_jumps_to_first_valid_instant() -> None:
    tz = ZoneInfo(NY)
    # 2024-03-10: US spring-forward Sunday. 02:00 -> 03:00, so 02:30 doesn't exist.
    result = resolve_local_time(date(2024, 3, 10), time(2, 30), tz)
    assert (result.hour, result.minute, result.second) == (3, 0, 0)
    assert result.utcoffset() == timedelta(hours=-4)  # EDT, confirms it's past the jump


def test_resolve_local_time_fall_back_ambiguous_resolves_to_first_occurrence() -> None:
    tz = ZoneInfo(NY)
    # 2024-11-03: US fall-back Sunday. 01:30 occurs twice; fold=0 (first pass, EDT) wins.
    result = resolve_local_time(date(2024, 11, 3), time(1, 30), tz)
    assert result.utcoffset() == timedelta(hours=-4)  # EDT: the earlier of the two passes


def test_candidate_dates_one_shot_yields_only_today() -> None:
    alarm = _alarm(hour=7, minute=0, days=set())
    dates = list(candidate_dates(alarm, date(2024, 6, 1)))
    assert dates == [date(2024, 6, 1)]


def test_candidate_dates_recurring_finds_next_matching_weekday() -> None:
    alarm = _alarm(hour=7, minute=0, days={3})  # Wednesday
    dates = list(candidate_dates(alarm, date(2024, 6, 1)))  # a Saturday
    assert dates[0] == date(2024, 6, 5)  # next Wednesday
    assert dates[0].isoweekday() == 3


# --- interface: upsert / delete / next_events -----------------------------


async def test_next_events_orders_ramp_start_before_alarm_fire(tmp_path: Path) -> None:
    now = datetime(2024, 6, 3, 5, 0, tzinfo=ZoneInfo(NY))  # a Monday
    scheduler, _clock, store, _events = await _make_scheduler(tmp_path / "db.sqlite", now)
    await scheduler.upsert(_alarm(hour=6, minute=40, days={1}, pre_roll_s=1200))
    await scheduler.start()
    await scheduler.stop()

    events = await scheduler.next_events(limit=5)
    assert [e.kind for e in events] == ["ramp_start", "alarm_fire"]
    assert events[0].at < events[1].at
    assert events[1].at == datetime(2024, 6, 3, 6, 40, tzinfo=ZoneInfo(NY))

    await store.close()


async def test_delete_removes_alarm_from_next_events(tmp_path: Path) -> None:
    now = datetime(2024, 6, 3, 5, 0, tzinfo=ZoneInfo(NY))
    scheduler, _clock, store, _events = await _make_scheduler(tmp_path / "db.sqlite", now)
    alarm = await scheduler.upsert(_alarm(hour=6, minute=40, days={1}))
    await scheduler.start()
    await scheduler.stop()

    assert await scheduler.next_events() != []
    await scheduler.delete(alarm.id)
    assert await scheduler.next_events() == []

    await store.close()


# --- acceptance criteria -------------------------------------------------


async def test_spring_forward_fires_once_at_0300(tmp_path: Path) -> None:
    # 2024-03-10 is a Sunday; drive from just before the gap.
    start = datetime(2024, 3, 10, 1, 0, tzinfo=ZoneInfo(NY))
    scheduler, clock, store, events = await _make_scheduler(
        tmp_path / "db.sqlite", start
    )
    await scheduler.upsert(_alarm(hour=2, minute=30, days={7}))  # Sunday
    await scheduler.start()
    # `stop()` immediately: with a FakeClock, the background loop's
    # `clock.sleep()` returns instantly, so left running it would spin
    # forever racing the manual `tick()` calls below. Tests drive ticks
    # by hand instead (see PROGRESS.md task 04 notes).
    await scheduler.stop()
    try:
        for _ in range(60):  # 60 * 5min = 5h of simulated time, well past the gap
            clock.advance(300)
            await scheduler.tick()
    finally:
        await scheduler.stop()
        await store.close()

    fired = _fired(events)
    assert len(fired) == 1
    fired_at = datetime.fromisoformat(fired[0].payload["fired_at"])
    local = fired_at.astimezone(ZoneInfo(NY))
    assert (local.hour, local.minute) == (3, 0)


async def test_fall_back_fires_exactly_once(tmp_path: Path) -> None:
    # 2024-11-03 is a Sunday; drive from just before 01:30 EDT (the first pass).
    start = datetime(2024, 11, 3, 1, 0, tzinfo=ZoneInfo(NY))
    scheduler, clock, store, events = await _make_scheduler(
        tmp_path / "db.sqlite", start
    )
    await scheduler.upsert(_alarm(hour=1, minute=30, days={7}))
    await scheduler.start()
    await scheduler.stop()  # see note in test_spring_forward_fires_once_at_0300
    try:
        for _ in range(60):  # well past both the 01:30 EDT and 01:30 EST passes
            clock.advance(300)
            await scheduler.tick()
    finally:
        await scheduler.stop()
        await store.close()

    assert len(_fired(events)) == 1


async def _seed_alarm_store(db_path: Path, alarm: Alarm) -> None:
    """Simulate "a previous process created this alarm": open the store,
    upsert via a throwaway scheduler, close it — like a real restart."""
    clock = FakeClock(datetime(2024, 1, 1, tzinfo=UTC))
    store = await Store.open(db_path)
    bus = EventBus()
    scheduler = Scheduler(store, clock, bus)
    await scheduler.upsert(alarm)
    await store.close()


async def test_restart_2min_before_fire_still_fires_on_time(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    fire_at = datetime(2024, 6, 3, 6, 40, tzinfo=ZoneInfo(NY))  # a Monday
    await _seed_alarm_store(db_path, _alarm(hour=6, minute=40, days={1}))

    store = await Store.open(db_path)
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(_events_collector(events))
    clock = FakeClock(fire_at - timedelta(minutes=2))
    scheduler = Scheduler(store, clock, bus, clock_synced=True)
    await scheduler.start()  # "restart" 2 minutes before fire time
    await scheduler.stop()  # see note in test_spring_forward_fires_once_at_0300
    assert _fired(events) == []  # not due yet

    try:
        for _ in range(9):  # 9 * 15s = 135s, comfortably past the 2-minute mark
            clock.advance(15)
            await scheduler.tick()
    finally:
        await scheduler.stop()
        await store.close()

    fired = _fired(events)
    assert len(fired) == 1
    fired_at = datetime.fromisoformat(fired[0].payload["fired_at"])
    assert fired_at >= fire_at
    assert (fired_at - fire_at).total_seconds() < 30  # fired "on time", not late


async def test_restart_3min_after_fire_fires_immediately_once(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    fire_at = datetime(2024, 6, 3, 6, 40, tzinfo=ZoneInfo(NY))
    await _seed_alarm_store(db_path, _alarm(hour=6, minute=40, days={1}))

    store = await Store.open(db_path)
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(_events_collector(events))
    clock = FakeClock(fire_at + timedelta(minutes=3))
    scheduler = Scheduler(store, clock, bus, clock_synced=True, catchup_s=600.0)

    await scheduler.start()  # the initial catch-up tick should fire immediately
    await scheduler.stop()  # see note in test_spring_forward_fires_once_at_0300
    assert len(_fired(events)) == 1
    assert _missed(events) == []

    await scheduler.tick()  # a further tick must not double-fire
    assert len(_fired(events)) == 1

    await scheduler.stop()
    await store.close()


async def test_restart_3hours_after_marks_missed_not_fired(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    fire_at = datetime(2024, 6, 3, 6, 40, tzinfo=ZoneInfo(NY))
    await _seed_alarm_store(db_path, _alarm(hour=6, minute=40, days={1}))

    store = await Store.open(db_path)
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(_events_collector(events))
    clock = FakeClock(fire_at + timedelta(hours=3))
    scheduler = Scheduler(store, clock, bus, clock_synced=True, catchup_s=600.0)

    await scheduler.start()
    await scheduler.stop()  # see note in test_spring_forward_fires_once_at_0300
    assert _fired(events) == []
    assert len(_missed(events)) == 1

    await scheduler.tick()  # must stay resolved, not retried
    assert len(_missed(events)) == 1
    assert _fired(events) == []

    await scheduler.stop()
    await store.close()


async def test_clock_stepped_backward_mid_day_no_double_fire(tmp_path: Path) -> None:
    fire_at = datetime(2024, 6, 3, 14, 0, tzinfo=ZoneInfo(NY))  # mid-day, no DST involved
    scheduler, clock, store, events = await _make_scheduler(
        tmp_path / "db.sqlite", fire_at - timedelta(minutes=1)
    )
    await scheduler.upsert(_alarm(hour=14, minute=0, days={1}))
    await scheduler.start()
    await scheduler.stop()  # see note in test_spring_forward_fires_once_at_0300
    try:
        clock.advance(90)  # past fire time
        await scheduler.tick()
        assert len(_fired(events)) == 1

        clock.advance(-3600)  # NTP correction steps the clock back an hour
        await scheduler.tick()
        assert len(_fired(events)) == 1  # still just one

        clock.advance(3700)  # clock "catches back up" through 14:00 a second time
        await scheduler.tick()
        assert len(_fired(events)) == 1  # no double fire
    finally:
        await scheduler.stop()
        await store.close()


async def test_unsafe_clock_blocks_firing_and_reports_degraded(tmp_path: Path) -> None:
    fire_at = datetime(2024, 6, 3, 7, 0, tzinfo=ZoneInfo(NY))
    scheduler, clock, store, events = await _make_scheduler(
        tmp_path / "db.sqlite", fire_at, clock_synced=False
    )
    await scheduler.upsert(_alarm(hour=7, minute=0, days={1}))
    await scheduler.start()
    await scheduler.stop()  # see note in test_spring_forward_fires_once_at_0300
    try:
        assert scheduler.health == "degraded"
        clock.advance(60)
        await scheduler.tick()
        assert _fired(events) == []  # refuses to fire on an unsafe clock

        scheduler.mark_clock_synced()
        assert scheduler.health == "ok"
        await scheduler.tick()
        assert len(_fired(events)) == 1  # fires once the clock is trustworthy
    finally:
        await scheduler.stop()
        await store.close()


async def test_skip_next_skips_one_occurrence_and_clears(tmp_path: Path) -> None:
    first_fire = datetime(2024, 6, 3, 7, 0, tzinfo=ZoneInfo(NY))  # Monday
    scheduler, clock, store, events = await _make_scheduler(
        tmp_path / "db.sqlite", first_fire - timedelta(minutes=1)
    )
    alarm = await scheduler.upsert(_alarm(hour=7, minute=0, days={1}))
    await scheduler.skip_next(alarm.id)
    await scheduler.start()
    await scheduler.stop()  # see note in test_spring_forward_fires_once_at_0300
    try:
        clock.advance(120)
        await scheduler.tick()
        assert _fired(events) == []  # the first Monday's occurrence was skipped

        clock.advance(7 * 24 * 3600)  # advance to the following Monday
        await scheduler.tick()
        assert len(_fired(events)) == 1  # skip_next auto-cleared; this one fires
    finally:
        await scheduler.stop()
        await store.close()

"""Tests for `openrestore.app.AppContext`'s own responsibilities: the
centralized `events` table logging (tasks/07-api.md) and the scheduler ->
routine engine wiring that makes an alarm actually start something (see the
design note in `AppContext._start_bound_routine`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, time

from openrestore.app import AppContext
from openrestore.core.events import EventType
from openrestore.core.routines import RoutineState
from openrestore.core.scheduler import Alarm
from tests._helpers import build_test_context


async def test_ramp_start_starts_the_bound_routine() -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)  # Monday
    ctx, clock = await build_test_context(start=start)
    await ctx.start(background=False)
    await ctx.scheduler.upsert(
        Alarm(
            id="a1",
            enabled=True,
            time=time(6, 10),
            days={1, 2, 3, 4, 5},
            routine_id="weekday-wake",
            pre_roll_s=300,
            timezone="UTC",
        )
    )
    assert ctx.routine_engine.current_run is None

    clock.advance(5 * 60)  # 06:05 UTC == the ramp-start instant
    await ctx.tick()

    run = ctx.routine_engine.current_run
    assert run is not None
    assert run.routine.id == "weekday-wake"
    assert run.state == RoutineState.SUNRISE
    await ctx.stop()


async def test_missing_bound_routine_reports_preflight_failed_without_crashing() -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    ctx, clock = await build_test_context(start=start)
    await ctx.start(background=False)
    await ctx.scheduler.upsert(
        Alarm(
            id="a1",
            enabled=True,
            time=time(6, 10),
            days={1, 2, 3, 4, 5},
            routine_id="does-not-exist",
            pre_roll_s=300,
            timezone="UTC",
        )
    )
    clock.advance(5 * 60)
    await ctx.tick()  # must not raise

    assert ctx.routine_engine.current_run is None
    rows = [
        row
        async for row in _events(ctx)
        if row[0] == EventType.PREFLIGHT_FAILED.value
    ]
    assert len(rows) == 1
    await ctx.stop()


async def test_every_bus_event_is_logged_to_the_events_table_exactly_once() -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    ctx, clock = await build_test_context(start=start)
    await ctx.start(background=False)
    await ctx.scheduler.upsert(
        Alarm(
            id="a1",
            enabled=True,
            time=time(6, 10),
            days={1, 2, 3, 4, 5},
            routine_id="weekday-wake",
            pre_roll_s=300,
            timezone="UTC",
        )
    )
    clock.advance(5 * 60)
    await ctx.tick()

    ramp_start_rows = [row async for row in _events(ctx) if row[0] == EventType.RAMP_START.value]
    assert len(ramp_start_rows) == 1  # logged exactly once, not once per producer

    transition_rows = [
        row async for row in _events(ctx) if row[0] == EventType.ROUTINE_TRANSITION.value
    ]
    # RoutineEngine's own events (never logged by Scheduler) land in the
    # table too, via the same centralized subscriber.
    assert len(transition_rows) >= 1
    await ctx.stop()


async def _events(ctx: AppContext) -> AsyncIterator[tuple[str, str, str]]:
    cur = await ctx.store._conn.execute("SELECT type, payload, at FROM events ORDER BY id")
    async for row in cur:
        yield (row["type"], row["payload"], row["at"])

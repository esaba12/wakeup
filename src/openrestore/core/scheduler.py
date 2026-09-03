"""Alarm scheduling: recurrence, DST handling, persistence, drift. See docs/05-scheduler.md.

The component most likely to embarrass the project (tasks/04-scheduler.md), so
nothing here is cached across ticks: `Scheduler.tick()` recomputes every
alarm's next occurrence fresh from `clock.now()` every time it runs, which is
what makes restarts, DST transitions, and clock steps non-events instead of
special cases (docs/00-overview.md rule 1).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from openrestore.core.clock import Clock
from openrestore.core.events import Event, EventBus, EventType, Handler
from openrestore.core.store import AlarmRow, Store

# How far past a spring-forward gap to search, in one-minute steps, for the
# first valid local instant. Real-world DST gaps are at most a couple of
# hours; this is a generous ceiling, not a tuned constant.
_DST_GAP_SEARCH_MINUTES = 180

# How many calendar days ahead to search for a recurring alarm's next
# matching weekday. One full week guarantees a hit whenever `days` is
# non-empty.
_RECURRENCE_HORIZON_DAYS = 8


@dataclass(slots=True)
class Alarm:
    """See docs/05-scheduler.md `Alarm`. Field order here differs from the
    spec's literal listing — `timezone` is required and moves before the
    defaulted fields — because Python dataclasses require non-default fields
    before defaulted ones; the spec's order isn't valid Python as written."""

    id: str
    enabled: bool
    time: time
    days: set[int]  # ISO weekday 1-7; empty = one-shot
    routine_id: str
    pre_roll_s: int
    timezone: str  # IANA, e.g. "America/Detroit"
    skip_next: bool = False
    last_fired_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(1 <= d <= 7 for d in self.days):
            raise ValueError(f"days must be ISO weekdays 1-7, got {self.days!r}")
        if self.pre_roll_s < 0:
            raise ValueError(f"pre_roll_s must be >= 0, got {self.pre_roll_s!r}")
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValueError(f"invalid IANA timezone {self.timezone!r}") from exc


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    """One upcoming instant from `Scheduler.next_events()` — either the
    pre-roll ramp start or the alarm fire itself."""

    alarm_id: str
    kind: str  # "ramp_start" | "alarm_fire"
    at: datetime


def _local_time_exists(naive: datetime, tz: ZoneInfo) -> bool:
    """Whether `naive`, interpreted as a wall-clock time in `tz`, actually
    occurs. A spring-forward gap time round-trips to a *different* wall time
    once converted through UTC and back (PEP 495 fold=0 resolves it using
    the pre-transition offset, landing past the transition); a normal or
    ambiguous (fall-back) time round-trips to itself."""
    aware = naive.replace(tzinfo=tz)
    return aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive


def resolve_local_time(day: date, wall_time: time, tz: ZoneInfo) -> datetime:
    """Combine `day` and `wall_time` into an aware datetime in `tz`, per
    docs/05-scheduler.md rules 3-4:

    - If the local time exists, return it. An ambiguous fall-back time
      (occurs twice) resolves to its first — fold=0 — occurrence, which is
      Python's default; the second occurrence is deduplicated by the
      `(alarm_id, local_date)` occurrence key, not by fold, since both
      occurrences share the same local date.
    - If the local time falls in a spring-forward gap (does not exist),
      return the first valid instant after it — e.g. a 02:30 alarm on a
      gap day fires at 03:00, not 03:30 (naive-plus-gap-size).
    """
    naive = datetime.combine(day, wall_time)
    if _local_time_exists(naive, tz):
        return naive.replace(tzinfo=tz)
    candidate = naive
    for _ in range(_DST_GAP_SEARCH_MINUTES):
        candidate += timedelta(minutes=1)
        if _local_time_exists(candidate, tz):
            return candidate.replace(tzinfo=tz)
    raise AssertionError(f"could not resolve DST gap for {naive} in {tz.key}")


def candidate_dates(
    alarm: Alarm, local_today: date, *, horizon_days: int = _RECURRENCE_HORIZON_DAYS
) -> Iterator[date]:
    """Calendar dates, starting today, that could be `alarm`'s next
    occurrence: every weekday in `alarm.days` within the next week, or just
    today for a one-shot (empty `days`).

    A one-shot alarm's only-ever candidate is today's date; `Scheduler`
    separately tracks whether a one-shot has already been resolved (fired,
    missed, or skipped) *at all*, on any date, so it doesn't get silently
    re-armed on some later day this generator happens to be asked about
    again (see `Scheduler._one_shot_resolved_ids`).
    """
    if not alarm.days:
        yield local_today
        return
    for offset in range(horizon_days):
        day = local_today + timedelta(days=offset)
        if day.isoweekday() in alarm.days:
            yield day


def _alarm_to_row(alarm: Alarm) -> AlarmRow:
    return AlarmRow(
        id=alarm.id,
        enabled=alarm.enabled,
        time=alarm.time.isoformat(),
        days=json.dumps(sorted(alarm.days)),
        routine_id=alarm.routine_id,
        pre_roll_s=alarm.pre_roll_s,
        skip_next=alarm.skip_next,
        last_fired_at=alarm.last_fired_at.isoformat() if alarm.last_fired_at else None,
        timezone=alarm.timezone,
    )


def _row_to_alarm(row: AlarmRow) -> Alarm:
    return Alarm(
        id=row.id,
        enabled=row.enabled,
        time=time.fromisoformat(row.time),
        days=set(json.loads(row.days)),
        routine_id=row.routine_id,
        pre_roll_s=row.pre_roll_s,
        timezone=row.timezone,
        skip_next=row.skip_next,
        last_fired_at=datetime.fromisoformat(row.last_fired_at) if row.last_fired_at else None,
    )


class Scheduler:
    """See docs/05-scheduler.md `Scheduler`. Ticks every `tick_s` seconds
    (never a long sleep) and never fires while `clock_synced` is `False`
    (`UNSAFE_CLOCK`, docs/00-overview.md rule 6) — nothing has told it a
    time source has synced this boot until `mark_clock_synced()` is called,
    so the safe default is to refuse.

    Preflight hooks (T-5min before `alarm_fire`) are out of scope here per
    tasks/04-scheduler.md; task 10 fills them in.
    """

    def __init__(
        self,
        store: Store,
        clock: Clock,
        event_bus: EventBus,
        *,
        tick_s: float = 15.0,
        catchup_s: float = 600.0,
        clock_synced: bool = False,
    ) -> None:
        self._store = store
        self._clock = clock
        self._event_bus = event_bus
        self._tick_s = tick_s
        self._catchup_s = catchup_s
        self._clock_synced = clock_synced
        self._alarms: dict[str, Alarm] = {}
        self._occurrences: set[tuple[str, str]] = set()
        self._one_shot_resolved_ids: set[str] = set()
        self._ramp_started: set[tuple[str, str]] = set()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def health(self) -> str:
        return "ok" if self._clock_synced else "degraded"

    @property
    def clock_synced(self) -> bool:
        return self._clock_synced

    def mark_clock_synced(self) -> None:
        """Call once a time source (NTP or RTC) has provided a time this
        boot. Idempotent; emits nothing (only the transition *into*
        `UNSAFE_CLOCK` is an event worth raising)."""
        self._clock_synced = True

    async def mark_clock_unsafe(self) -> None:
        was_synced = self._clock_synced
        self._clock_synced = False
        if was_synced:
            await self._emit(EventType.CLOCK_UNSAFE, {})

    def subscribe(self, handler: Handler) -> None:
        self._event_bus.subscribe(handler)

    async def start(self) -> None:
        alarm_rows = await self._store.list_alarms()
        self._alarms = {row.id: _row_to_alarm(row) for row in alarm_rows}
        occurrence_rows = await self._store.list_occurrences()
        self._occurrences = {(o.alarm_id, o.local_date) for o in occurrence_rows}
        self._one_shot_resolved_ids = {
            o.alarm_id
            for o in occurrence_rows
            if o.alarm_id in self._alarms and not self._alarms[o.alarm_id].days
        }
        self._running = True
        # Run one tick synchronously before returning: this is what resolves
        # startup catch-up (fire or mark-missed) deterministically, rather
        # than racing the background loop's first scheduled tick.
        await self.tick()
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

    async def tick(self) -> None:
        """Process every enabled alarm once, against `clock.now()` right
        now. Safe to call directly (e.g. from tests, after advancing a
        `FakeClock`) instead of waiting on the background loop."""
        if not self._clock_synced:
            return
        now = self._clock.now()
        for alarm in list(self._alarms.values()):
            if alarm.enabled:
                await self._process_alarm(alarm, now)

    async def _process_alarm(self, alarm: Alarm, now: datetime) -> None:
        if not alarm.days and alarm.id in self._one_shot_resolved_ids:
            return
        tz = ZoneInfo(alarm.timezone)
        local_today = now.astimezone(tz).date()
        for day in candidate_dates(alarm, local_today):
            key = (alarm.id, day.isoformat())
            if key in self._occurrences:
                continue
            if alarm.skip_next:
                await self._skip_occurrence(alarm, day)
                continue

            fire_dt = resolve_local_time(day, alarm.time, tz)
            ramp_start_dt = fire_dt - timedelta(seconds=alarm.pre_roll_s)
            if now >= ramp_start_dt and key not in self._ramp_started:
                self._ramp_started.add(key)
                await self._emit(
                    EventType.RAMP_START,
                    {
                        "alarm_id": alarm.id,
                        "local_date": day.isoformat(),
                        "routine_id": alarm.routine_id,
                        "fire_at": fire_dt.isoformat(),
                    },
                )
            if now < fire_dt:
                return
            await self._fire_or_miss(alarm, day, fire_dt, now)
            return

    async def _skip_occurrence(self, alarm: Alarm, day: date) -> None:
        key = (alarm.id, day.isoformat())
        newly = await self._store.reserve_occurrence(
            alarm.id, day.isoformat(), outcome="skipped", fired_at=None
        )
        if newly:
            self._occurrences.add(key)
            if not alarm.days:
                self._one_shot_resolved_ids.add(alarm.id)
        alarm.skip_next = False
        await self._store.upsert_alarm(_alarm_to_row(alarm))

    async def _fire_or_miss(
        self, alarm: Alarm, day: date, fire_dt: datetime, now: datetime
    ) -> None:
        key = (alarm.id, day.isoformat())
        age_s = (now - fire_dt).total_seconds()
        if age_s <= self._catchup_s:
            newly = await self._store.reserve_occurrence(
                alarm.id, day.isoformat(), outcome="fired", fired_at=now.isoformat()
            )
            if not newly:
                return
            self._occurrences.add(key)
            if not alarm.days:
                self._one_shot_resolved_ids.add(alarm.id)
            alarm.last_fired_at = now
            await self._store.upsert_alarm(_alarm_to_row(alarm))
            await self._emit(
                EventType.ALARM_FIRED,
                {
                    "alarm_id": alarm.id,
                    "local_date": day.isoformat(),
                    "routine_id": alarm.routine_id,
                    "fired_at": now.isoformat(),
                },
            )
        else:
            newly = await self._store.reserve_occurrence(
                alarm.id, day.isoformat(), outcome="missed", fired_at=None
            )
            if not newly:
                return
            self._occurrences.add(key)
            if not alarm.days:
                self._one_shot_resolved_ids.add(alarm.id)
            await self._emit(
                EventType.ALARM_MISSED,
                {
                    "alarm_id": alarm.id,
                    "local_date": day.isoformat(),
                    "routine_id": alarm.routine_id,
                    "due_at": fire_dt.isoformat(),
                },
            )

    async def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        event = Event(type=event_type, payload=payload)
        await self._store.log_event(event, self._clock.now())
        await self._event_bus.publish(event)

    async def next_events(self, limit: int = 5) -> list[ScheduledEvent]:
        now = self._clock.now()
        events: list[ScheduledEvent] = []
        for alarm in self._alarms.values():
            if not alarm.enabled:
                continue
            preview = self._preview_next_fire(alarm, now)
            if preview is None:
                continue
            _day, fire_dt = preview
            ramp_start_dt = fire_dt - timedelta(seconds=alarm.pre_roll_s)
            if ramp_start_dt > now:
                events.append(
                    ScheduledEvent(alarm_id=alarm.id, kind="ramp_start", at=ramp_start_dt)
                )
            events.append(ScheduledEvent(alarm_id=alarm.id, kind="alarm_fire", at=fire_dt))
        events.sort(key=lambda e: e.at)
        return events[:limit]

    def _preview_next_fire(self, alarm: Alarm, now: datetime) -> tuple[date, datetime] | None:
        """Read-only preview of the next occurrence for `next_events()` —
        unlike `_process_alarm`, never writes an occurrence or clears
        `skip_next`; it just simulates skipping the first candidate."""
        if not alarm.days and alarm.id in self._one_shot_resolved_ids:
            return None
        tz = ZoneInfo(alarm.timezone)
        local_today = now.astimezone(tz).date()
        skip_pending = alarm.skip_next
        for day in candidate_dates(alarm, local_today):
            key = (alarm.id, day.isoformat())
            if key in self._occurrences:
                continue
            if skip_pending:
                skip_pending = False
                continue
            return day, resolve_local_time(day, alarm.time, tz)
        return None

    async def upsert(self, alarm: Alarm) -> Alarm:
        await self._store.upsert_alarm(_alarm_to_row(alarm))
        self._alarms[alarm.id] = alarm
        return alarm

    async def delete(self, alarm_id: str) -> None:
        await self._store.delete_alarm(alarm_id)
        self._alarms.pop(alarm_id, None)

    async def skip_next(self, alarm_id: str) -> None:
        alarm = self._alarms[alarm_id]
        alarm.skip_next = True
        await self._store.upsert_alarm(_alarm_to_row(alarm))

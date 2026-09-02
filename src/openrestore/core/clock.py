"""Wall-clock time source. Every timed component depends on a Clock instead of
calling datetime.now() or asyncio.sleep() directly, so tests can control time
and nothing in the system ever sleeps until an event (docs/00-overview.md)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current, timezone-aware wall-clock time."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Suspend the caller for approximately `seconds`."""
        ...


class SystemClock:
    """Clock backed by the real OS clock, in the local timezone."""

    def now(self) -> datetime:
        return datetime.now(UTC).astimezone()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FakeClock:
    """Clock for tests. Time only moves when `advance()` is called explicitly —
    `sleep()` yields control to the event loop but never advances `now()`."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

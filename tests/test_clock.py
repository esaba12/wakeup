from __future__ import annotations

from datetime import UTC, datetime

from openrestore.core.clock import FakeClock, SystemClock


def test_fake_clock_does_not_advance_on_its_own(fake_clock: FakeClock) -> None:
    first = fake_clock.now()
    second = fake_clock.now()
    assert first == second


async def test_fake_clock_does_not_advance_across_sleep(fake_clock: FakeClock) -> None:
    before = fake_clock.now()
    await fake_clock.sleep(3600)
    assert fake_clock.now() == before


def test_fake_clock_advances_only_when_told(fake_clock: FakeClock) -> None:
    before = fake_clock.now()
    fake_clock.advance(60)
    assert (fake_clock.now() - before).total_seconds() == 60


def test_system_clock_returns_timezone_aware_datetime() -> None:
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None


def test_system_clock_now_is_close_to_utc_now() -> None:
    clock = SystemClock()
    delta = abs((clock.now() - datetime.now(UTC)).total_seconds())
    assert delta < 5

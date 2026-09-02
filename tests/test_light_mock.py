from __future__ import annotations

from datetime import timedelta

import pytest

from openrestore.core.clock import FakeClock
from openrestore.core.errors import DeviceUnreachable
from openrestore.drivers.light.base import LightState
from openrestore.drivers.light.mock import MockLight
from tests.conformance.light import LightConformanceSuite


class TestMockLightConformance(LightConformanceSuite):
    @pytest.fixture
    def light(self, fake_clock: FakeClock) -> MockLight:
        return MockLight(fake_clock)


async def test_records_applied_states_with_clock_timestamp(fake_clock: FakeClock) -> None:
    light = MockLight(fake_clock)
    state_a = LightState(on=True, brightness=0.1, cct=1800, rgb=None)
    state_b = LightState(on=True, brightness=0.2, cct=2000, rgb=None)

    await light.apply(state_a, transition_ms=15_000)
    fake_clock.advance(15)
    await light.apply(state_b, transition_ms=15_000)

    assert [entry.state for entry in light.history] == [state_a, state_b]
    assert [entry.transition_ms for entry in light.history] == [15_000, 15_000]
    assert light.history[1].at == light.history[0].at + timedelta(seconds=15)


async def test_configurable_min_brightness_impersonates_a_high_floor_bulb(
    fake_clock: FakeClock,
) -> None:
    light = MockLight(fake_clock, min_brightness=0.10)
    assert light.capabilities.min_brightness == 0.10


async def test_configurable_supports_native_transition_impersonates_wiz(
    fake_clock: FakeClock,
) -> None:
    light = MockLight(fake_clock, supports_native_transition=False)
    assert light.capabilities.supports_native_transition is False


async def test_unreachable_light_raises_on_apply(fake_clock: FakeClock) -> None:
    light = MockLight(fake_clock, reachable=False)
    with pytest.raises(DeviceUnreachable):
        await light.apply(LightState(on=True, brightness=0.5, cct=3000, rgb=None))


async def test_set_reachable_toggles_apply_behavior(fake_clock: FakeClock) -> None:
    light = MockLight(fake_clock)
    assert await light.is_reachable() is True

    light.set_reachable(False)
    assert await light.is_reachable() is False
    with pytest.raises(DeviceUnreachable):
        await light.apply(LightState(on=True, brightness=0.5, cct=3000, rgb=None))

    light.set_reachable(True)
    await light.apply(LightState(on=True, brightness=0.5, cct=3000, rgb=None))

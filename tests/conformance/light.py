"""Conformance suite every `Light` implementation must pass.

Subclass `LightConformanceSuite` and override the `light` fixture to return
your implementation, reachable and freshly constructed. Every implementation
in `docs/02-light-driver.md`'s "Required implementations" table — including
future real drivers — runs this suite unchanged."""

from __future__ import annotations

import pytest

from openrestore.drivers.light.base import Light, LightCapabilities, LightState


class LightConformanceSuite:
    @pytest.fixture
    def light(self) -> Light:
        raise NotImplementedError("subclasses must override the `light` fixture")

    async def test_has_id(self, light: Light) -> None:
        assert isinstance(light.id, str) and light.id

    async def test_capabilities_are_well_formed(self, light: Light) -> None:
        caps = light.capabilities
        assert isinstance(caps, LightCapabilities)
        assert 0.0 <= caps.min_brightness <= 1.0
        low, high = caps.cct_range
        assert 0 < low < high
        assert caps.max_transition_ms > 0
        assert caps.recommended_step_interval_ms > 0

    async def test_starts_reachable(self, light: Light) -> None:
        assert await light.is_reachable() is True

    async def test_apply_then_get_roundtrips(self, light: Light) -> None:
        state = LightState(on=True, brightness=0.5, cct=3000, rgb=None)
        await light.apply(state)
        assert await light.get() == state

    async def test_apply_is_absolute_not_relative(self, light: Light) -> None:
        low = LightState(on=True, brightness=0.2, cct=2000, rgb=None)
        high = LightState(on=True, brightness=0.9, cct=4000, rgb=None)
        await light.apply(low)
        await light.apply(high)
        assert await light.get() == high

    async def test_apply_is_idempotent(self, light: Light) -> None:
        state = LightState(on=True, brightness=0.3, cct=2500, rgb=None)
        await light.apply(state)
        await light.apply(state)
        assert await light.get() == state

    async def test_apply_off(self, light: Light) -> None:
        await light.apply(LightState(on=True, brightness=0.5, cct=3000, rgb=None))
        off = LightState(on=False, brightness=0.0, cct=3000, rgb=None)
        await light.apply(off)
        assert await light.get() == off

    async def test_apply_at_min_brightness_succeeds(self, light: Light) -> None:
        floor = light.capabilities.min_brightness
        state = LightState(on=True, brightness=floor, cct=light.capabilities.cct_range[0], rgb=None)
        await light.apply(state)
        assert await light.get() == state

    async def test_close_does_not_raise(self, light: Light) -> None:
        await light.close()

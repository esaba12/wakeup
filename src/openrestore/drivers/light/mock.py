"""In-memory light for development and tests. Requires no hardware."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openrestore.core.clock import Clock
from openrestore.core.errors import DeviceUnreachable
from openrestore.drivers.light.base import LightCapabilities, LightState


@dataclass(frozen=True, slots=True)
class AppliedState:
    """One recorded `apply()` call, timestamped by the injected clock so
    tests can assert on the whole state timeline a ramp produced."""

    at: datetime
    state: LightState
    transition_ms: int


class MockLight:
    """In-memory `Light`. Configurable `min_brightness` and
    `supports_native_transition` so it can impersonate a LIFX (native
    transition, low floor) or a WiZ (emulated transition, high floor)."""

    def __init__(
        self,
        clock: Clock,
        id: str = "mock-1",
        *,
        min_brightness: float = 0.0,
        cct_range: tuple[int, int] = (1500, 9000),
        supports_rgb: bool = True,
        supports_native_transition: bool = True,
        max_transition_ms: int = 60_000,
        recommended_step_interval_ms: int = 15_000,
        reachable: bool = True,
    ) -> None:
        self.id = id
        self.capabilities = LightCapabilities(
            min_brightness=min_brightness,
            cct_range=cct_range,
            supports_rgb=supports_rgb,
            supports_native_transition=supports_native_transition,
            max_transition_ms=max_transition_ms,
            recommended_step_interval_ms=recommended_step_interval_ms,
        )
        self._clock = clock
        self._state = LightState(on=False, brightness=0.0, cct=cct_range[0], rgb=None)
        self._reachable = reachable
        self._closed = False
        self.history: list[AppliedState] = []

    async def apply(self, state: LightState, transition_ms: int = 0) -> None:
        if not self._reachable:
            raise DeviceUnreachable(f"{self.id} is unreachable")
        self._state = state
        self.history.append(
            AppliedState(at=self._clock.now(), state=state, transition_ms=transition_ms)
        )

    async def get(self) -> LightState:
        return self._state

    async def is_reachable(self) -> bool:
        return self._reachable

    async def close(self) -> None:
        self._closed = True

    def set_reachable(self, reachable: bool) -> None:
        """Test hook: simulate the bulb dropping off or rejoining the network."""
        self._reachable = reachable

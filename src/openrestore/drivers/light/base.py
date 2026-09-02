"""Light driver Protocol. No vendor concepts (dimming, hsbk, mirek) above this
layer. See docs/02-light-driver.md."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LightState:
    on: bool
    brightness: float  # 0.0-1.0, PERCEPTUAL (see docs/03-sunrise-engine.md), not raw device units
    cct: int | None  # kelvin, None if in rgb mode
    rgb: tuple[int, int, int] | None

    def __post_init__(self) -> None:
        if not 0.0 <= self.brightness <= 1.0:
            raise ValueError(f"brightness must be in 0.0-1.0, got {self.brightness!r}")
        if self.cct is not None and self.cct <= 0:
            raise ValueError(f"cct must be positive kelvin, got {self.cct!r}")
        if self.rgb is not None and not all(0 <= c <= 255 for c in self.rgb):
            raise ValueError(f"rgb components must be 0-255, got {self.rgb!r}")


@dataclass(frozen=True, slots=True)
class LightCapabilities:
    min_brightness: float  # lowest reliably-renderable perceptual brightness, 0.0-1.0
    cct_range: tuple[int, int]  # e.g. (1500, 9000)
    supports_rgb: bool
    supports_native_transition: bool
    max_transition_ms: int
    recommended_step_interval_ms: int


@dataclass(frozen=True, slots=True)
class LightRef:
    """A light found by discovery, not yet connected to. Enough to construct
    a `Light` implementation from; vendor-specific fields belong on the
    concrete driver's own ref subclass, not here."""

    id: str
    address: str
    name: str | None = None


@runtime_checkable
class Light(Protocol):
    id: str
    capabilities: LightCapabilities

    async def apply(self, state: LightState, transition_ms: int = 0) -> None:
        """Idempotent and absolute, never relative. Must not raise on a
        transient network failure; retries internally and raises only after
        exhausting its retry budget. A raise means "the light is gone" and
        triggers the escalation path in docs/10-reliability.md."""
        ...

    async def get(self) -> LightState: ...

    async def is_reachable(self) -> bool: ...

    async def close(self) -> None: ...


@runtime_checkable
class LightDiscovery(Protocol):
    @staticmethod
    async def discover(timeout_s: float = 5.0) -> list[LightRef]: ...

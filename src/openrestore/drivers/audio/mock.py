"""In-memory audio output for development and tests. Requires no hardware."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openrestore.core.clock import Clock
from openrestore.core.errors import DeviceUnreachable
from openrestore.drivers.audio.base import AudioSource


@dataclass(frozen=True, slots=True)
class Call:
    """One recorded driver call, timestamped by the injected clock so tests
    can assert on the whole call timeline a routine produced."""

    at: datetime
    action: str  # "play" | "stop" | "set_gain" | "ramp_gain" | "test_tone"
    args: tuple[object, ...]


class MockAudioOutput:
    """In-memory `AudioOutput`. Tracks the currently "playing" source and
    gain so a step's `light: hold`-style no-ops have an audio equivalent
    to reason about in tests."""

    def __init__(
        self,
        clock: Clock,
        id: str = "mock-audio-1",
        *,
        available: bool = True,
    ) -> None:
        self.id = id
        self._clock = clock
        self._available = available
        self._playing: AudioSource | None = None
        self._gain_db: float = -60.0
        self.history: list[Call] = []

    async def play(self, source: AudioSource, gain_db: float) -> None:
        if not self._available:
            raise DeviceUnreachable(f"{self.id} is unavailable")
        self._playing = source
        self._gain_db = gain_db
        self.history.append(Call(self._clock.now(), "play", (source, gain_db)))

    async def stop(self, fade_out_s: float = 0.0) -> None:
        self._playing = None
        self.history.append(Call(self._clock.now(), "stop", (fade_out_s,)))

    async def set_gain(self, gain_db: float) -> None:
        self._gain_db = gain_db
        self.history.append(Call(self._clock.now(), "set_gain", (gain_db,)))

    async def ramp_gain(self, to_db: float, over_s: float) -> None:
        self._gain_db = to_db
        self.history.append(Call(self._clock.now(), "ramp_gain", (to_db, over_s)))

    async def is_available(self) -> bool:
        return self._available

    async def is_playing(self) -> bool:
        return self._playing is not None

    async def test_tone(self, seconds: float = 1.0) -> None:
        self.history.append(Call(self._clock.now(), "test_tone", (seconds,)))

    def set_available(self, available: bool) -> None:
        """Test hook: simulate the dongle dropping off or rejoining."""
        self._available = available

    @property
    def playing(self) -> AudioSource | None:
        return self._playing

    @property
    def gain_db(self) -> float:
        return self._gain_db

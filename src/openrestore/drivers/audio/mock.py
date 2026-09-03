"""In-memory audio output for development and tests. Requires no hardware."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openrestore.core.clock import Clock
from openrestore.core.errors import DeviceUnreachable
from openrestore.drivers.audio.base import AudioOutputState, AudioSource, clamp_gain_db


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
        max_gain_db: float = 0.0,
    ) -> None:
        self.id = id
        self.max_gain_db = max_gain_db
        self._clock = clock
        self._available = available
        self._playing: AudioSource | None = None
        self._gain_db: float = -60.0
        self.history: list[Call] = []
        self.fallback_engaged_count: int = 0

    async def play(self, source: AudioSource, gain_db: float) -> None:
        if not self._available:
            raise DeviceUnreachable(f"{self.id} is unavailable")
        applied = clamp_gain_db(gain_db, self.max_gain_db)
        self._playing = source
        self._gain_db = applied
        self.history.append(Call(self._clock.now(), "play", (source, applied)))

    async def stop(self, fade_out_s: float = 0.0) -> None:
        self._playing = None
        self.history.append(Call(self._clock.now(), "stop", (fade_out_s,)))

    async def set_gain(self, gain_db: float) -> None:
        applied = clamp_gain_db(gain_db, self.max_gain_db)
        self._gain_db = applied
        self.history.append(Call(self._clock.now(), "set_gain", (applied,)))

    async def ramp_gain(self, to_db: float, over_s: float) -> None:
        applied = clamp_gain_db(to_db, self.max_gain_db)
        self._gain_db = applied
        self.history.append(Call(self._clock.now(), "ramp_gain", (applied, over_s)))

    async def get(self) -> AudioOutputState:
        return AudioOutputState(playing=self._playing, gain_db=self._gain_db)

    async def is_available(self) -> bool:
        return self._available

    async def is_playing(self) -> bool:
        return self._playing is not None

    async def test_tone(self, seconds: float = 1.0) -> None:
        self.history.append(Call(self._clock.now(), "test_tone", (seconds,)))

    async def engage_fallback(self) -> None:
        """Stub: records that the fallback path would have engaged. Task 10
        wires an actual buzzer driver and the `panic_after` trigger; nothing
        calls this yet."""
        self.fallback_engaged_count += 1
        self.history.append(Call(self._clock.now(), "engage_fallback", ()))

    def set_available(self, available: bool) -> None:
        """Test hook: simulate the dongle dropping off or rejoining."""
        self._available = available

    @property
    def playing(self) -> AudioSource | None:
        return self._playing

    @property
    def gain_db(self) -> float:
        return self._gain_db

"""Audio driver Protocol: output paths, player control, volume ramping. See
docs/04-audio-subsystem.md.

Defined here ahead of any real implementation (task 06 builds `MpvOutput`)
because the routine engine (task 05) already needs to call *something* for
`audio` blocks. No vendor concept (mpv IPC commands, ALSA device strings)
appears above this layer, matching the light driver's `Light` Protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class AudioSource:
    kind: Literal["file", "url", "stream"]
    ref: str
    loop: bool = True


@runtime_checkable
class AudioOutput(Protocol):
    id: str

    async def play(self, source: AudioSource, gain_db: float) -> None:
        """Start `source` playing at `gain_db`. Idempotent: calling it again
        with a different source replaces what's playing; the same source is
        a no-op restart avoided by the caller checking `is_playing()` first
        if that matters to them."""
        ...

    async def stop(self, fade_out_s: float = 0.0) -> None: ...

    async def set_gain(self, gain_db: float) -> None: ...

    async def ramp_gain(self, to_db: float, over_s: float) -> None:
        """Ramp gain to `to_db` over `over_s` seconds. The driver owns the
        timing of this ramp (docs/04-audio-subsystem.md "Volume behavior") —
        callers invoke it once and move on, the same way `Light.apply()`'s
        `transition_ms` is a fire-and-forget instruction to the driver."""
        ...

    async def is_available(self) -> bool: ...

    async def is_playing(self) -> bool: ...

    async def test_tone(self, seconds: float = 1.0) -> None: ...

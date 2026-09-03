"""Audio driver Protocol: output paths, player control, volume ramping. See
docs/04-audio-subsystem.md.

Defined here ahead of any real implementation (task 06 builds `MpvOutput`)
because the routine engine (task 05) already needs to call *something* for
`audio` blocks. No vendor concept (mpv IPC commands, ALSA device strings)
appears above this layer, matching the light driver's `Light` Protocol.

Task 06 adds `max_gain_db` and `gain_at`/`clamp_gain_db`: docs/04-audio-subsystem.md
"Volume behavior" describes an "absolute ceiling ... the routine engine
cannot exceed" — enforced here, below the routine engine, so the engine
(task 05, not touched by task 06) never has to know about it. Every
`AudioOutput` implementation clamps every gain it's asked to apply to
`min(requested, max_gain_db)` before sending it to hardware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class AudioSource:
    kind: Literal["file", "url", "stream"]
    ref: str
    loop: bool = True


@dataclass(frozen=True, slots=True)
class AudioDeviceInfo:
    """One sink from `AudioOutput` device enumeration (docs/04-audio-subsystem.md
    "Device enumeration"): an ALSA/PulseAudio/CoreAudio sink id and its
    human-readable description, as reported by the platform."""

    id: str
    description: str


def gain_at(t: float, start_db: float, end_db: float) -> float:
    """Linear interpolation in dB space, per docs/04-audio-subsystem.md
    "Volume behavior": `t` in [0, 1]. Perceived loudness is roughly
    logarithmic, so ramping *this* linearly (rather than the linear-amplitude
    value) is what makes a ramp sound gradual instead of silence-then-jolt."""
    return start_db + (end_db - start_db) * t


def db_to_linear(gain_db: float) -> float:
    """Convert a dB gain to a linear amplitude multiplier (1.0 == unity),
    per docs/04-audio-subsystem.md's `linear = 10 ** (gain_db / 20)`."""
    return 10 ** (gain_db / 20)


def clamp_gain_db(gain_db: float, max_gain_db: float) -> float:
    """Enforce the "absolute ceiling" a routine can never exceed
    (docs/04-audio-subsystem.md "Volume behavior")."""
    return min(gain_db, max_gain_db)


@runtime_checkable
class AudioOutput(Protocol):
    id: str
    max_gain_db: float

    async def play(self, source: AudioSource, gain_db: float) -> None:
        """Start `source` playing at `gain_db`. Idempotent: calling it again
        with a different source replaces what's playing; the same source is
        a no-op restart avoided by the caller checking `is_playing()` first
        if that matters to them. `gain_db` is clamped to `max_gain_db`."""
        ...

    async def stop(self, fade_out_s: float = 0.0) -> None: ...

    async def set_gain(self, gain_db: float) -> None:
        """Set gain immediately, clamped to `max_gain_db`."""
        ...

    async def ramp_gain(self, to_db: float, over_s: float) -> None:
        """Ramp gain to `min(to_db, max_gain_db)` over `over_s` seconds. The
        driver owns the timing of this ramp (docs/04-audio-subsystem.md
        "Volume behavior") — callers invoke it once and move on, the same way
        `Light.apply()`'s `transition_ms` is a fire-and-forget instruction to
        the driver."""
        ...

    async def is_available(self) -> bool:
        """Device present AND openable — must actually attempt to open the
        device, not just check that it's enumerated (a dongle can be listed
        and still be claimed by another process)."""
        ...

    async def is_playing(self) -> bool: ...

    async def test_tone(self, seconds: float = 1.0) -> None:
        """Play a short, quiet (docs/04: -60dB, effectively inaudible) tone
        to verify the playback pipeline actually opens, per the T-5min
        preflight health check. Not sound-library content, so it's exempt
        from the "no runtime synthesis" rule in docs/00-overview.md/spec 15 —
        that rule scopes the sounds a user hears (white noise, soundscapes),
        not an internal diagnostic signal."""
        ...

    async def engage_fallback(self) -> None:
        """Stub for docs/10-reliability.md's fallback path (e.g. a physical
        buzzer), engaged after `panic_after` of an unacknowledged, fully
        escalated alarm. Task 06 only stubs this hook on the driver; nothing
        calls it yet, and the buzzer/fallback device itself is task 10's."""
        ...

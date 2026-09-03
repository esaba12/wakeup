"""MockAudioOutput's task-06 additions: `max_gain_db` clamping and the
`engage_fallback` stub. Playback/timestamp recording itself predates this
task (task 05) and is already exercised by tests/test_routines.py."""

from __future__ import annotations

from openrestore.core.clock import FakeClock
from openrestore.drivers.audio.base import AudioSource
from openrestore.drivers.audio.mock import MockAudioOutput


async def test_play_clamps_gain_to_max_gain_db(fake_clock: FakeClock) -> None:
    audio = MockAudioOutput(fake_clock, max_gain_db=-10.0)
    source = AudioSource(kind="file", ref="white.flac")

    await audio.play(source, gain_db=0.0)  # asks for more than the ceiling

    assert audio.gain_db == -10.0
    assert audio.history[-1].args[1] == -10.0


async def test_set_gain_clamps_to_max_gain_db(fake_clock: FakeClock) -> None:
    audio = MockAudioOutput(fake_clock, max_gain_db=-10.0)

    await audio.set_gain(5.0)

    assert audio.gain_db == -10.0


async def test_ramp_gain_clamps_target_to_max_gain_db(fake_clock: FakeClock) -> None:
    audio = MockAudioOutput(fake_clock, max_gain_db=-6.0)

    await audio.ramp_gain(to_db=6.0, over_s=1.0)

    assert audio.gain_db == -6.0
    assert audio.history[-1].action == "ramp_gain"
    assert audio.history[-1].args[0] == -6.0


async def test_gain_within_ceiling_is_unaffected(fake_clock: FakeClock) -> None:
    audio = MockAudioOutput(fake_clock, max_gain_db=0.0)

    await audio.set_gain(-20.0)

    assert audio.gain_db == -20.0


def test_default_max_gain_db_is_unity(fake_clock: FakeClock) -> None:
    """The default ceiling (0 dB == unity) means every normal alarm/wind-down
    ramp in the shipped routines (all well below 0 dB) is unaffected, but a
    misconfigured routine asking for a positive gain still gets capped."""
    audio = MockAudioOutput(fake_clock)
    assert audio.max_gain_db == 0.0


async def test_engage_fallback_is_a_no_op_stub_that_records_the_call(
    fake_clock: FakeClock,
) -> None:
    audio = MockAudioOutput(fake_clock)

    await audio.engage_fallback()

    assert audio.fallback_engaged_count == 1
    assert audio.history[-1].action == "engage_fallback"

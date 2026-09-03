"""`MpvOutput` and the shared gain math in `drivers/audio/base.py`.

The pure math and parsing tests always run. Everything that actually spawns
mpv is guarded with `_requires_mpv` and skipped when `mpv` isn't on PATH
(e.g. a CI runner that hasn't installed it) — see tasks/06-audio.md's note
that hardware/audible verification needs a human with real speakers, but
these at least verify the *mechanism* (respawn, IPC, gain clamping, device
enumeration) against a real mpv process where one is available.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from openrestore.core.clock import SystemClock
from openrestore.core.errors import DeviceUnreachable
from openrestore.drivers.audio.base import AudioSource, clamp_gain_db, db_to_linear, gain_at
from openrestore.drivers.audio.mpv import (
    MpvOutput,
    _gain_db_to_mpv_volume,
    _parse_device_list,
    list_output_devices,
)

_requires_mpv = pytest.mark.skipif(
    shutil.which("mpv") is None, reason="mpv is not installed on this machine"
)


def _socket_path() -> Path:
    # AF_UNIX paths have a short OS-level length limit (~104 bytes on
    # macOS); pytest's `tmp_path` is nested too deep to fit, so sockets for
    # these tests live directly under the system temp dir instead.
    return Path(tempfile.gettempdir()) / f"ort-{uuid.uuid4().hex[:10]}.sock"


# --- pure math: docs/04-audio-subsystem.md "Volume behavior" -------------


def test_gain_at_interpolates_linearly_in_db_space() -> None:
    assert gain_at(0.0, -45.0, -12.0) == -45.0
    assert gain_at(1.0, -45.0, -12.0) == -12.0
    assert gain_at(0.5, -45.0, -12.0) == pytest.approx(-28.5)


def test_db_to_linear_matches_spec_formula() -> None:
    assert db_to_linear(0.0) == pytest.approx(1.0)
    assert db_to_linear(-20.0) == pytest.approx(0.1)
    assert db_to_linear(20.0) == pytest.approx(10.0)


def test_clamp_gain_db_enforces_ceiling() -> None:
    assert clamp_gain_db(10.0, max_gain_db=0.0) == 0.0
    assert clamp_gain_db(-30.0, max_gain_db=0.0) == -30.0
    assert clamp_gain_db(-5.0, max_gain_db=-10.0) == -10.0


def test_gain_db_to_mpv_volume_is_percentage_and_clamped() -> None:
    assert _gain_db_to_mpv_volume(0.0) == pytest.approx(100.0)
    assert _gain_db_to_mpv_volume(-20.0) == pytest.approx(10.0)
    assert _gain_db_to_mpv_volume(20.0) == 100.0  # clamped, never exceeds mpv's 100


def test_parse_device_list_matches_mpv_audio_device_help_format() -> None:
    text = (
        "List of detected audio devices:\n"
        "  'auto' (Autoselect device)\n"
        "  'coreaudio/BuiltInSpeakerDevice' (MacBook Pro Speakers)\n"
    )
    devices = _parse_device_list(text)
    assert devices[0].id == "auto"
    assert devices[0].description == "Autoselect device"
    assert devices[1].id == "coreaudio/BuiltInSpeakerDevice"
    assert devices[1].description == "MacBook Pro Speakers"


# --- real mpv process, skipped if unavailable -----------------------------


@pytest.fixture
async def mpv_output(tmp_path: Path) -> MpvOutput:
    out = MpvOutput(SystemClock(), sounds_dir=tmp_path, socket_path=_socket_path())
    await out.start()
    yield out
    await out.close()


@_requires_mpv
async def test_list_output_devices_returns_at_least_auto() -> None:
    devices = await list_output_devices()
    assert any(d.id == "auto" for d in devices)


async def test_list_output_devices_raises_when_binary_missing() -> None:
    with pytest.raises(DeviceUnreachable):
        await list_output_devices(mpv_bin="definitely-not-a-real-binary")


@_requires_mpv
async def test_start_and_is_available(mpv_output: MpvOutput) -> None:
    assert await mpv_output.is_available()


@_requires_mpv
async def test_play_synthetic_tone_and_stop(mpv_output: MpvOutput) -> None:
    # av://lavfi is mpv's own synthesized input (used here as a stand-in for
    # a real file so the test needs no shipped audio asset); the driver
    # treats a "stream"-kind source's ref as an opaque string passed
    # straight to mpv, exactly like an http(s) URL would be.
    source = AudioSource(kind="stream", ref="av://lavfi:sine=frequency=440:duration=5", loop=False)
    await mpv_output.play(source, gain_db=-40.0)
    assert await mpv_output.is_playing()
    await mpv_output.stop()
    assert not await mpv_output.is_playing()


@_requires_mpv
async def test_max_gain_db_is_enforced_even_when_asked_for_more(tmp_path: Path) -> None:
    out = MpvOutput(
        SystemClock(),
        sounds_dir=tmp_path,
        socket_path=_socket_path(),
        max_gain_db=-10.0,
    )
    await out.start()
    try:
        source = AudioSource(
            kind="stream", ref="av://lavfi:sine=frequency=440:duration=5", loop=False
        )
        await out.play(source, gain_db=0.0)  # routine asks for 0dB, ceiling is -10dB
        assert out._gain_db <= -10.0

        await out.set_gain(5.0)
        assert out._gain_db <= -10.0

        await out.ramp_gain(to_db=5.0, over_s=0.2)
        import asyncio

        await asyncio.sleep(0.4)
        assert out._gain_db <= -10.0
    finally:
        await out.close()


@_requires_mpv
async def test_mpv_death_is_respawned_within_5s(tmp_path: Path) -> None:
    import asyncio
    import os
    import signal
    import time

    out = MpvOutput(
        SystemClock(), sounds_dir=tmp_path, socket_path=_socket_path()
    )
    await out.start()
    try:
        source = AudioSource(
            kind="stream", ref="av://lavfi:sine=frequency=220:duration=30", loop=True
        )
        await out.play(source, gain_db=-40.0)
        old_pid = out._proc.pid  # type: ignore[union-attr]

        os.kill(old_pid, signal.SIGKILL)

        deadline = time.monotonic() + 5.0
        respawned = False
        while time.monotonic() < deadline:
            if await out.is_available():
                respawned = True
                break
            await asyncio.sleep(0.1)

        assert respawned, "mpv was not respawned within 5s"
        assert await out.is_playing()
    finally:
        await out.close()


async def test_is_available_false_when_never_started(tmp_path: Path) -> None:
    out = MpvOutput(SystemClock(), sounds_dir=tmp_path, socket_path=_socket_path())
    assert not await out.is_available()


async def test_start_raises_device_unreachable_when_binary_missing(tmp_path: Path) -> None:
    out = MpvOutput(
        SystemClock(),
        sounds_dir=tmp_path,
        socket_path=_socket_path(),
        mpv_bin="definitely-not-a-real-binary",
    )
    with pytest.raises(DeviceUnreachable):
        await out.start()

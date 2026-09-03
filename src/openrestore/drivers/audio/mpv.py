"""`MpvOutput`: mpv as a supervised child process, controlled over a unix
JSON-IPC socket. See docs/04-audio-subsystem.md "Player: mpv over IPC".

Only `mpv` itself (a system binary, not a Python dependency) and stdlib are
imported here, and only inside this module — never at package import time —
matching docs/00-overview.md rule 3 ("the daemon must start on any host").
mpv talks to ALSA/PipeWire/CoreAudio itself; this driver never imports an
audio library directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from openrestore.core.clock import Clock
from openrestore.core.errors import DeviceUnreachable
from openrestore.drivers.audio.base import (
    AudioDeviceInfo,
    AudioOutputState,
    AudioSource,
    clamp_gain_db,
    db_to_linear,
    gain_at,
)

logger = structlog.get_logger()

# docs/04-audio-subsystem.md "Volume behavior": ramps are updated every 500ms.
_RAMP_STEP_S = 0.5
# tasks/06-audio.md "Done when": respawned within 5s if mpv dies.
_RESPAWN_TIMEOUT_S = 5.0
_IPC_CONNECT_RETRY_S = 0.1
_IPC_RESPONSE_TIMEOUT_S = 2.0
# docs/04-audio-subsystem.md "Health checks": test_tone() at -60dB, inaudible.
_TEST_TONE_GAIN_DB = -60.0
_SILENT_FLOOR_DB = -60.0


def _gain_db_to_mpv_volume(gain_db: float) -> float:
    """mpv's `volume` property is a linear percentage where 100 == unity
    (softvol). Convert from dB via `db_to_linear` and clamp to mpv's valid
    range; every gain this driver ever sends is <= 0dB by construction
    (`max_gain_db` default 0.0), so 100 is a safe ceiling in practice."""
    return max(0.0, min(100.0, db_to_linear(gain_db) * 100))


_DEVICE_LIST_RE = re.compile(r"^\s*'([^']+)'\s+\(([^)]*)\)\s*$")


def _parse_device_list(text: str) -> list[AudioDeviceInfo]:
    devices: list[AudioDeviceInfo] = []
    for line in text.splitlines():
        match = _DEVICE_LIST_RE.match(line)
        if match:
            devices.append(AudioDeviceInfo(id=match.group(1), description=match.group(2)))
    return devices


async def list_output_devices(mpv_bin: str = "mpv") -> list[AudioDeviceInfo]:
    """Enumerate ALSA/PulseAudio/CoreAudio sinks mpv can see
    (docs/04-audio-subsystem.md "Device enumeration"), via
    `mpv --audio-device=help`. Doesn't require an `MpvOutput` instance to be
    running — usable from config/onboarding to populate a device picker."""
    if shutil.which(mpv_bin) is None:
        raise DeviceUnreachable(f"{mpv_bin!r} not found on PATH")
    proc = await asyncio.create_subprocess_exec(
        mpv_bin,
        "--audio-device=help",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return _parse_device_list(stdout.decode(errors="replace"))


@dataclass(slots=True)
class _IpcState:
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    next_request_id: int = 0
    pending: dict[int, asyncio.Future[Any]] = field(default_factory=dict)
    reader_task: asyncio.Task[None] | None = None


class MpvOutput:
    """`AudioOutput` backed by a supervised `mpv --idle` process. One mpv
    process per `MpvOutput`; `play()` uses `loadfile` rather than spawning a
    new process per track so looping is gapless (docs/04)."""

    id: str
    max_gain_db: float

    def __init__(
        self,
        clock: Clock,
        *,
        id: str = "mpv-1",
        sounds_dir: Path,
        audio_device: str = "auto",
        socket_path: Path | None = None,
        max_gain_db: float = 0.0,
        mpv_bin: str = "mpv",
    ) -> None:
        self.id = id
        self.max_gain_db = max_gain_db
        self._clock = clock
        self._sounds_dir = sounds_dir
        self._audio_device = audio_device
        self._mpv_bin = mpv_bin
        self._socket_path = (
            socket_path or Path(tempfile.gettempdir()) / f"openrestore-mpv-{uuid.uuid4().hex}.sock"
        )
        self._proc: asyncio.subprocess.Process | None = None
        self._ipc = _IpcState()
        self._supervisor_task: asyncio.Task[None] | None = None
        self._ramp_task: asyncio.Task[None] | None = None
        self._gain_db: float = _SILENT_FLOOR_DB
        self._playing: AudioSource | None = None
        self._closed = False

    # --- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        """Spawn mpv, connect the IPC socket, and start the respawn
        supervisor. Idempotent."""
        if self._proc is not None and self._proc.returncode is None:
            return
        self._closed = False
        await self._spawn_and_connect()
        if self._supervisor_task is None or self._supervisor_task.done():
            self._supervisor_task = asyncio.ensure_future(self._supervise())

    async def close(self) -> None:
        """Stop the supervisor and terminate mpv. Not part of the
        `AudioOutput` Protocol (which has no lifecycle methods) — an extra
        for callers (tests, the daemon shutdown path) that spawned this
        driver via `start()`."""
        self._closed = True
        self._cancel_ramp()
        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor_task
            self._supervisor_task = None
        await self._disconnect()
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        self._proc = None
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()

    async def _spawn_and_connect(self) -> None:
        if shutil.which(self._mpv_bin) is None:
            raise DeviceUnreachable(f"{self._mpv_bin!r} not found on PATH")
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()
        self._proc = await asyncio.create_subprocess_exec(
            self._mpv_bin,
            "--idle=yes",
            "--no-video",
            "--no-terminal",
            "--loop-file=inf",
            f"--audio-device={self._audio_device}",
            f"--input-ipc-server={self._socket_path}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._connect(timeout_s=_RESPAWN_TIMEOUT_S)

    async def _connect(self, *, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                reader, writer = await asyncio.open_unix_connection(str(self._socket_path))
            except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
                last_exc = exc
                await asyncio.sleep(_IPC_CONNECT_RETRY_S)
                continue
            self._ipc = _IpcState(reader=reader, writer=writer)
            self._ipc.reader_task = asyncio.ensure_future(self._read_loop())
            return
        raise DeviceUnreachable(f"{self.id}: could not connect to mpv IPC socket: {last_exc}")

    async def _disconnect(self) -> None:
        if self._ipc.reader_task is not None:
            self._ipc.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ipc.reader_task
        for fut in self._ipc.pending.values():
            if not fut.done():
                fut.set_exception(DeviceUnreachable(f"{self.id}: mpv IPC disconnected"))
        if self._ipc.writer is not None:
            with contextlib.suppress(OSError):
                self._ipc.writer.close()
        self._ipc = _IpcState()

    async def _supervise(self) -> None:
        """Respawn mpv (within `_RESPAWN_TIMEOUT_S`) whenever the process
        dies, restoring whatever was playing. tasks/06-audio.md 'Done when':
        'killing the mpv process mid-playback -> respawned and playing again
        within 5s.'"""
        while not self._closed:
            assert self._proc is not None
            returncode = await self._proc.wait()
            if self._closed:
                return
            logger.warning("audio.mpv_died", id=self.id, returncode=returncode)
            await self._disconnect()
            try:
                await self._spawn_and_connect()
            except DeviceUnreachable:
                logger.error("audio.mpv_respawn_failed", id=self.id)
                await asyncio.sleep(1.0)
                continue
            if self._playing is not None:
                with contextlib.suppress(DeviceUnreachable):
                    await self._load(self._playing)
                    await self._apply_volume(self._gain_db)
            logger.info("audio.mpv_respawned", id=self.id)

    # --- IPC -------------------------------------------------------------

    async def _read_loop(self) -> None:
        reader = self._ipc.reader
        assert reader is not None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                request_id = msg.get("request_id")
                if request_id is not None and request_id in self._ipc.pending:
                    fut = self._ipc.pending.pop(request_id)
                    if not fut.done():
                        if msg.get("error") != "success":
                            fut.set_exception(
                                DeviceUnreachable(f"{self.id}: mpv error: {msg.get('error')}")
                            )
                        else:
                            fut.set_result(msg.get("data"))
                # else: an unsolicited event notification (property change,
                # end-of-file, ...) -- nothing in this driver subscribes yet.
        except asyncio.CancelledError:
            raise
        except OSError:
            pass
        finally:
            for fut in self._ipc.pending.values():
                if not fut.done():
                    fut.set_exception(DeviceUnreachable(f"{self.id}: mpv IPC connection closed"))

    async def _send(self, command: list[Any], *, timeout_s: float = _IPC_RESPONSE_TIMEOUT_S) -> Any:
        writer = self._ipc.writer
        if writer is None:
            raise DeviceUnreachable(f"{self.id}: mpv IPC not connected")
        self._ipc.next_request_id += 1
        request_id = self._ipc.next_request_id
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._ipc.pending[request_id] = fut
        payload = {"command": command, "request_id": request_id}
        try:
            writer.write((json.dumps(payload) + "\n").encode())
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            self._ipc.pending.pop(request_id, None)
            raise DeviceUnreachable(f"{self.id}: mpv IPC write failed: {exc}") from exc
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except TimeoutError as exc:
            self._ipc.pending.pop(request_id, None)
            raise DeviceUnreachable(f"{self.id}: mpv IPC response timeout") from exc

    def _resolve(self, source: AudioSource) -> str:
        if source.kind == "file":
            path = Path(source.ref)
            if not path.is_absolute():
                path = self._sounds_dir / path
            return str(path)
        return source.ref

    async def _load(self, source: AudioSource) -> None:
        await self._send(["set_property", "loop-file", "inf" if source.loop else "no"])
        await self._send(["loadfile", self._resolve(source)])
        await self._send(["set_property", "pause", False])

    async def _apply_volume(self, gain_db: float) -> None:
        await self._send(["set_property", "volume", _gain_db_to_mpv_volume(gain_db)])

    def _cancel_ramp(self) -> None:
        if self._ramp_task is not None and not self._ramp_task.done():
            self._ramp_task.cancel()
        self._ramp_task = None

    # --- AudioOutput -----------------------------------------------------

    async def play(self, source: AudioSource, gain_db: float) -> None:
        self._cancel_ramp()
        applied = clamp_gain_db(gain_db, self.max_gain_db)
        await self._load(source)
        await self._apply_volume(applied)
        self._playing = source
        self._gain_db = applied

    async def stop(self, fade_out_s: float = 0.0) -> None:
        self._cancel_ramp()
        if fade_out_s > 0:
            self._ramp_task = asyncio.ensure_future(self._run_fade_out_and_stop(fade_out_s))
            return
        await self._send(["stop"])
        self._playing = None

    async def set_gain(self, gain_db: float) -> None:
        self._cancel_ramp()
        applied = clamp_gain_db(gain_db, self.max_gain_db)
        await self._apply_volume(applied)
        self._gain_db = applied

    async def ramp_gain(self, to_db: float, over_s: float) -> None:
        """Fire-and-forget: schedules a background task that steps volume
        every 500ms and returns immediately (base.py's `ramp_gain`
        docstring)."""
        self._cancel_ramp()
        applied_target = clamp_gain_db(to_db, self.max_gain_db)
        if over_s <= 0:
            await self.set_gain(applied_target)
            return
        self._ramp_task = asyncio.ensure_future(self._run_ramp(applied_target, over_s))

    async def _run_ramp(self, to_db: float, over_s: float) -> None:
        start_db = self._gain_db
        steps = max(1, round(over_s / _RAMP_STEP_S))
        try:
            for i in range(1, steps + 1):
                t = i / steps
                gain = gain_at(t, start_db, to_db)
                await self._apply_volume(gain)
                self._gain_db = gain
                if i < steps:
                    await self._clock.sleep(_RAMP_STEP_S)
        except asyncio.CancelledError:
            raise
        except DeviceUnreachable:
            logger.warning("audio.ramp_failed", id=self.id, to_db=to_db)

    async def _run_fade_out_and_stop(self, over_s: float) -> None:
        try:
            await self._run_ramp(_SILENT_FLOOR_DB, over_s)
            await self._send(["stop"])
            self._playing = None
        except asyncio.CancelledError:
            raise
        except DeviceUnreachable:
            logger.warning("audio.stop_failed", id=self.id)

    async def get(self) -> AudioOutputState:
        return AudioOutputState(playing=self._playing, gain_db=self._gain_db)

    async def is_available(self) -> bool:
        """Actually round-trips through the live mpv IPC connection (not
        just "the process exists") — a claimed/removed device will fail this
        even if the mpv process itself is still up, per base.py's
        `is_available` contract."""
        if self._proc is None or self._proc.returncode is not None:
            return False
        try:
            await self._send(["get_property", "audio-device"], timeout_s=1.0)
            return True
        except DeviceUnreachable:
            return False

    async def is_playing(self) -> bool:
        return self._playing is not None

    async def test_tone(self, seconds: float = 1.0) -> None:
        """A synthesized sine tone via mpv's own `av://lavfi:` input, not a
        file on disk. This is a diagnostic health-check signal, not
        sound-library content, so it's exempt from spec 15's
        "no runtime synthesis" rule (see base.py's `test_tone` docstring)."""
        applied = clamp_gain_db(_TEST_TONE_GAIN_DB, self.max_gain_db)
        await self._send(["set_property", "loop-file", "no"])
        await self._send(["loadfile", f"av://lavfi:sine=frequency=440:duration={seconds}"])
        await self._apply_volume(applied)
        await self._send(["set_property", "pause", False])

    async def engage_fallback(self) -> None:
        """Stub: docs/10-reliability.md's fallback buzzer is task 10's.
        Logs and returns; not wired to anything in this task."""
        logger.warning("audio.fallback_stub_engaged", id=self.id)

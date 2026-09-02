> Scope note: audio is **file-based playback only**. There is no runtime noise synthesis — white noise and soundscapes are ordinary audio files on disk, played and looped like any other track. Sourcing and preparing those files is spec 15.

## Purpose
Get sound out of the host and into a speaker the user already owns, reliably enough that an alarm can depend on it.

## Output paths, ranked by alarm reliability

**1. USB audio adapter → 3.5mm → powered speaker. Default.**
A CM108/CM6533-class $8 dongle enumerates as an ALSA device with no configuration. Deterministic, no pairing, no reconnect. Note the Pi Zero family has no analog jack at all, so on the reference host this (or I²S) is mandatory, not optional.
*Risk:* speakers that auto-sleep and won't wake on signal. Mitigate with a smart plug or a speaker without the behavior.

**2. I²S DAC or DAC+amp HAT.**
Better quality, leaves USB free. `MAX98357A` is a combined DAC + ~3W class-D amp — right for driving a bare driver, wrong for feeding an already-powered speaker (use a line-level DAC HAT for that). Enabled by device-tree overlay:
```
# /boot/firmware/config.txt
dtparam=audio=off
dtoverlay=max98357a        # or hifiberry-dac for line-level
dtoverlay=i2s-mmap
```

**3. Network sink — AirPlay (`pyatv`), Chromecast (`pychromecast`), Snapcast.**
Zero audio hardware on the host; good for Tier 3 deployments and for people with a HomePod or Sonos. Adds a network dependency to alarm delivery.

**4. Bluetooth A2DP source → BT speaker. Supported, discouraged.**
3–10s reconnect latency, pairing loss, speakers that power off. The Pi's internal Bluetooth radio shares silicon with Wi-Fi and is widely reported as unreliable for audio — use a USB BT dongle if you go this route. **Never the only path for an alarm.**

## Interface

```python
@dataclass
class AudioSource:
    kind: Literal["file", "url", "stream"]
    ref: str
    loop: bool = True

class AudioOutput(Protocol):
    id: str
    async def play(self, source: AudioSource, gain_db: float) -> None: ...
    async def stop(self, fade_out_s: float = 0.0) -> None: ...
    async def set_gain(self, gain_db: float) -> None: ...
    async def ramp_gain(self, to_db: float, over_s: float) -> None: ...
    async def is_available(self) -> bool: ...   # device present AND openable
    async def test_tone(self, seconds: float = 1.0) -> None: ...
```

Implementations: `MpvOutput` (local ALSA/PipeWire), `AirplayOutput`, `ChromecastOutput`, `BluetoothOutput`, `MockOutput`.

`is_available()` must actually attempt to open the device, not just check that it's enumerated. A dongle can be listed and still be claimed by another process.

## Player: mpv over IPC

One long-lived process, controlled by JSON-RPC over a unix socket. Plays every format, loops gaplessly, survives track changes.

```bash
mpv --idle=yes --no-video --no-terminal --loop-file=inf \
    --audio-device=alsa/plughw:1,0 \
    --input-ipc-server=/run/openrestore/mpv.sock
```
```
{"command":["loadfile","/var/lib/openrestore/sounds/rain.flac"]}
{"command":["set_property","volume",35]}
{"command":["get_property","audio-device"]}
```

Why mpv over gstreamer or a Python audio lib: one dependency, one process to supervise, format handling is free, and if it dies systemd restarts it and the daemon reconnects to the socket.

## Volume behavior

Perceived loudness is roughly logarithmic, so linear volume ramps sound like silence then a jolt. Ramp in dB:

```python
def gain_at(t: float, start_db: float, end_db: float) -> float:
    return start_db + (end_db - start_db) * t          # t in [0,1]

linear = 10 ** (gain_db / 20)
```

Defaults:
- **Alarm ramp:** −45 dB → −12 dB over 90 s, updated every 500 ms.
- **Wind-down fade-in:** −40 dB → target over 30 s.
- **Sleep timer fade-out:** target → −60 dB over 5 min, then stop. Never hard-cut audio on a sleeping person.
- **Absolute ceiling:** a configurable `max_gain_db` the routine engine cannot exceed, so a bad config can't blast someone at 3am.

## Escalation
If the alarm has been sounding for `escalate_after` (default 60 s) with no interaction, step the ceiling up by 6 dB, once. If still nothing after `panic_after` (default 5 min), engage the fallback buzzer (spec 10).

## Health checks
The scheduler queries the audio output at **T−5 minutes** before every alarm:
1. `is_available()`
2. `test_tone()` at −60 dB (inaudible) to verify the pipeline actually opens
3. For network/BT sinks, verify the link is up and pre-connect

Any failure transitions to the fallback chain in spec 10 and records an event.

## Acceptance criteria
- [ ] Same behavior across USB, I²S, and mock outputs; output selectable at runtime from config
- [ ] Unplugging the USB dongle mid-playback is detected within 10s and reported, without crashing the daemon
- [ ] dB ramp verified by capture: measured RMS follows the intended curve within 2 dB
- [ ] mpv process death is recovered automatically within 5s

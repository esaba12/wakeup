# 01 — Hardware Platform

## Purpose
Define the minimum host, the reference host, and the portability contract so the daemon runs on far more than a Pi Zero 2 W.

## Reference host
**Raspberry Pi Zero 2 W** — quad-core Cortex-A53 @1GHz, 512MB RAM, Wi-Fi 4, Bluetooth 4.2, 40-pin GPIO, no analog audio out, no RTC.

Chosen for: cost (~$18), power draw (~0.7W idle), GPIO for the physical controls, and enough headroom for Python + audio decode + a tiny web server with room to spare.

## Minimum host requirements

| Requirement | Value | Why |
|---|---|---|
| CPU | Any 64-bit ARM or x86, ≥600 MHz single core | Ramp loop is <1% CPU; audio decode dominates |
| RAM | 256 MB free | Python + mpv + SQLite |
| Storage | 2 GB | OS excluded; app + sounds + db ≈ 200 MB |
| Network | Any IP network reachable by the bulb | UDP unicast + broadcast on the same L2 segment |
| Audio out | Any ALSA/PulseAudio/PipeWire sink, **or** a network sink | See spec 04 |
| Clock | NTP **or** an RTC | See spec 05 |
| Python | 3.11+ | `zoneinfo`, `asyncio.TaskGroup` |

Explicitly **not** required: GPIO, a display, Bluetooth, a soundcard, internet access.

## Portability tiers

**Tier 1 — full feature set.** Pi Zero 2 W / Pi 3 / Pi 4 / Pi 5 / any SBC with GPIO. Physical controls available natively via the GPIO input adapter.

**Tier 2 — headless, no GPIO.** x86 mini PC, NAS, an old laptop, a VPS on the same LAN, a Docker container, WSL. Everything works except native GPIO input; physical controls come from an MQTT/WebSocket puck instead (spec 09).

**Tier 3 — no local audio hardware.** Any host with a network audio target (AirPlay/Chromecast/Snapcast/Bluetooth). Light + schedule + routines fully functional; audio goes over the network with a mandatory pre-alarm health check.

**Tier 4 — development.** macOS or Linux laptop. All drivers have a `Mock` implementation; `--mock-light --mock-audio` runs the whole system with no hardware at all and a fake clock for testing.

The portability contract: **tiers 2–4 must be first-class, tested in CI, and documented in the README.** A project that only runs on one board is a gist, not a project.

## Pi Zero 2 W specific notes

- **No analog audio jack.** HDMI, USB, or I²S only. A USB audio dongle is effectively mandatory (spec 04).
- **One data-capable USB port** (micro-USB OTG). If you use it for audio, you have none left — plan a hub, or use I²S so USB stays free.
- **512 MB RAM.** Fine, but don't run Home Assistant alongside. Use Raspberry Pi OS **Lite** (64-bit), no desktop.
- **Internal Bluetooth shares silicon with Wi-Fi** and is widely reported as unreliable for audio. If you must do Bluetooth audio, use a USB dongle.
- **No RTC.** Add a DS3231 (spec 09) or accept that a boot without internet has no idea what time it is.
- **SD card wear** is the leading cause of death for always-on Pis. Read-only root is specified in spec 12, not optional.

## Power
5V ≥2.0A supply. Undervoltage on a Zero 2 W manifests as Wi-Fi dropping out at 4am, which reads as a scheduler bug and isn't. Log `vcgencmd get_throttled` in the health endpoint (spec 10).

## Acceptance criteria
- [ ] Daemon starts and passes `/api/health` on Pi Zero 2 W, on x86 Docker, and on macOS with mocks
- [ ] Cold boot to alarm-capable in <60s on the reference host
- [ ] Idle CPU <3%, RSS <120 MB on the reference host
- [ ] No GPIO import at module scope — GPIO libs are imported lazily inside the GPIO adapter only

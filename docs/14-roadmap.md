# 14 — Roadmap & Acceptance Gates

Each milestone has a gate. Don't start the next one until the gate passes — especially v0, which is the only one that can invalidate a hardware decision.

---

## v0 — Curve validation (one weekend, one file)
**Goal:** prove the bulb and the curves before writing any architecture.

A single script: discover the LIFX bulb, run a 30-minute perceptual sunrise ending at a hardcoded time, play a file through the USB dongle with a dB ramp. Triggered by `cron`. No UI, no scheduler, no abstractions.

Also run the bulb acceptance test from spec 02 (dim floor, PWM banding, packet loss, power-cycle behavior) and write the results into `hardware/bulb-compatibility.md`.

**Gate:** you watch a full sunrise in a dark room and it feels like dawn, not like a lamp turning on. If it doesn't, iterate on curves — or change bulbs — before proceeding. Everything after this is plumbing; this is the part that determines whether the product is good.

---

## v1 — The daemon (the shippable open-source project)
Specs 01–08, 11, 12.

- `Light` interface + LIFX driver + Mock driver
- Sunrise engine with YAML curves
- Audio via mpv with dB ramps
- Bundled sound library: generated noise files + CC0 rain/chime (spec 15)
- DST-correct scheduler with SQLite persistence
- Routine engine + YAML schema
- FastAPI REST + WebSocket
- React PWA: Now / Alarms / Routines / Settings
- `install.sh`, systemd unit, onboarding flow with identify-by-blink and test-by-tone

**Gate:** a stranger flashes an SD card, follows the README, and is woken by a sunrise the next morning without reading source. Tag v1.0, README leads with a GIF of the compressed sunrise preview.

---

## v2 — The object
Specs 09, 10.

- DS3231 RTC, hardware watchdog, read-only root
- Preflight health checks + buzzer fallback + audit trail + morning-after notice
- Rotary encoder, big button, display with lux-driven dimming
- AP-mode Wi-Fi onboarding
- Chaos test suite

**Gate:** 30 consecutive nights, no phone touched, zero missed alarms — and every degradation that did occur is visible in the history table with the correct `path_used`.

---

## v3 — Ecosystem
- Second and third light drivers (Hue, zigbee2mqtt) + published compatibility table
- MQTT / Home Assistant discovery bridge
- Routine sharing: a `routines/` gallery, import/export from the UI
- ESP32-C3 puck with ESPHome config, wiring diagram, printable case
- Spotify (librespot) and podcast-RSS sources

---

## v4 — Beyond the product
- Contactless sleep tracking via 60GHz mmWave (Seeed MR60BHA2) or LD2410 presence, on the puck via ESPHome
- Adaptive routines: shift tomorrow's wind-down based on when you actually fell asleep
- Data never leaves the house — the strongest pitch against a subscription device with a consumer-health-data privacy policy

---

## Ordering discipline
The two most common ways this project dies:
1. **Skipping v0** — building beautiful architecture on a bulb that can't dim below 10%.
2. **Skipping v2** — a working web app that nobody uses at night, because the whole premise was not picking up your phone.

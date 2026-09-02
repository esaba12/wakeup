# Task 10 — Deployment and reliability

**Read:** `docs/10-reliability.md`, `docs/12-packaging-deployment.md`, `docs/11-config-and-onboarding.md`

**Hardware:** the Raspberry Pi Zero 2 W, plus a USB audio dongle and a DS3231 RTC

## Build

**Config and onboarding** (spec 11): `config.yaml` schema with the documented precedence chain, `!env` secret references, parallel LAN discovery across drivers, and the first-run flow — identify-by-blink for bulbs, test-by-tone for audio outputs, then a 60-second compressed sunrise preview. `plughw:1,0` means nothing to a human; the test buttons are what make setup take 3 minutes instead of 40.

**Packaging** (spec 12): `install.sh` for Raspberry Pi OS Lite, the systemd unit with `Type=notify` and `WatchdogSec`, multi-arch Docker image, `openrestore update` with symlink-swap rollback, and read-only root with overlayfs plus a writable partition for `/var/lib/openrestore`.

**Reliability** (spec 10): preflight at T−5min (clock, light round-trip, audio open + inaudible test tone, buzzer GPIO, disk), the full fallback chain `light+audio → audio only → buzzer → logged failure`, `/api/health` with the exact shape in spec 10, the occurrence audit trail surfaced in the UI, and the morning-after banner explaining any overnight degradation.

**Chaos suite:** kill the daemon, unplug the bulb, unplug the dongle, step the clock, and cut power — at 10 points across a routine. The user is still woken in every case, or the log says precisely why not.

## Done when

- [ ] `install.sh` on a clean Pi OS Lite image → working daemon, no manual steps
- [ ] Flash to woken-by-a-sunrise in under 10 minutes for someone who has never seen the project
- [ ] Physically unplug audio 4 minutes before an alarm → buzzer fires at alarm time
- [ ] 100 forced power cuts, no filesystem corruption, alarm still fires
- [ ] Watchdog verified with a deliberate hang
- [ ] Update and rollback both verified

## After this

`docs/14-roadmap.md` v2 and v3: physical controls (spec 09), Hue and zigbee2mqtt drivers, the MQTT/Home Assistant bridge, and the ESP32 puck.

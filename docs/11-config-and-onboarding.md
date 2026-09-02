# 11 — Configuration & Onboarding

## Purpose
Get from a flashed SD card to a working alarm without editing YAML over SSH — while keeping everything file-backed and version-controllable for people who prefer that.

## Config file

`/etc/openrestore/config.yaml`, hot-reloadable, schema-validated, with every key optional and a sane default.

```yaml
version: 1
timezone: America/Detroit          # default: system tz

light:
  driver: lifx                     # lifx | hue | wiz | zigbee2mqtt | wled | mock
  id: d073d5xxxxxx                 # MAC or IP; discovered on first run
  # driver-specific
  # bridge: 192.168.1.40           (hue)
  # app_key: !env HUE_APP_KEY      (hue)

audio:
  output: alsa                     # alsa | airplay | chromecast | bluetooth | mock
  device: "plughw:1,0"
  max_gain_db: -6                  # hard ceiling the routine engine cannot exceed
  fallback: buzzer                 # buzzer | none

input:
  adapter: gpio                    # gpio | mqtt | none
  gpio:
    encoder: { a: 17, b: 27, sw: 22 }
    button: { in: 23, led: 24 }
    buzzer: 18
    i2c: { display: 0x3C, rtc: 0x68, lux: 0x23 }

server:
  bind: 0.0.0.0
  port: 8080
  bearer_token: null               # null = LAN, no auth

mqtt:                              # optional HA bridge
  enabled: false
  host: 192.168.1.10

paths:
  data: /var/lib/openrestore
  routines: /var/lib/openrestore/routines
  curves: /var/lib/openrestore/curves
```

Precedence: **defaults < config.yaml < environment (`OPENRESTORE_*`) < CLI flags < runtime API changes**, with runtime changes written back to `config.yaml` so the UI and the file never disagree.

Secrets (Hue app key, MQTT password, bearer token) resolve via `!env` references and never land in the file, so a user can commit their config.

## First-run flow

```
1. Flash Raspberry Pi OS Lite (64-bit). Wi-Fi + SSH set in Raspberry Pi Imager.
2. curl -sSL https://.../install.sh | bash
3. Daemon starts, detects no config → ONBOARDING mode
4. Browser → http://openrestore.local:8080
   a. Timezone (prefilled from system)
   b. "Looking for lights…"  ← LAN discovery across all drivers in parallel
        - shows each found bulb with an [Identify] button that blinks it
        - user picks one → binding written
   c. "Which speaker?"       ← enumerate audio outputs
        - [Test] plays a tone through each so the user picks by ear, not by name
   d. Set first alarm time
   e. "Preview sunrise (60s compressed)" ← runs the real curve, sped up
5. Done. Health check runs, home screen shows next alarm.
```

Design notes:
- **Identify-by-blink and test-by-tone** are the difference between a 3-minute setup and a 40-minute one. `plughw:1,0` means nothing to a human.
- The compressed sunrise preview is also the single best demo of the project — put a GIF of it at the top of the README.
- If the host has no Wi-Fi configured, boot into AP mode (`hostapd` + `dnsmasq`, or `wifi-connect`), serve the same onboarding page, take credentials, reboot into normal mode. This is what makes it a device rather than a Linux project.
- Onboarding must be re-enterable: `POST /api/setup/reset` or a config flag, for when someone changes bulbs.

## Discovery
Runs all drivers concurrently with a 5s budget:
- LIFX: UDP broadcast `GetService` on :56700
- WiZ: UDP broadcast `registration` on :38899
- Hue: mDNS `_hue._tcp` + the discovery endpoint fallback
- zigbee2mqtt: read `bridge/devices` from the broker
- WLED: mDNS `_wled._tcp`

Results are cached with a TTL; re-discovery runs every 5 min in the background so DHCP lease changes don't break the binding. **Bind by MAC/unique ID, never by IP.**

## Acceptance criteria
- [ ] Flash → working alarm in under 10 minutes for someone who has never seen the project
- [ ] Config file absent ⇒ onboarding; config file present ⇒ straight to running
- [ ] Every runtime setting change persists across restart
- [ ] Bulb IP changes via DHCP ⇒ rediscovered and rebound automatically within 5 min

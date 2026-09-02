# Task 09 — LIFX driver

**Read:** `docs/02-light-driver.md` (all of it), `docs/11-config-and-onboarding.md`

**Hardware:** the LIFX Color A19 bulb, on the same LAN

## Before writing any code

Run the bulb acceptance test in spec 02 Part A and write the results into `hardware/bulb-compatibility.md`:

1. Lowest non-zero brightness at lowest CCT in a dark room — candle, or reading lamp?
2. Phone camera at 5%, 10%, 20% — any rolling-shutter banding? That's PWM flicker.
3. 200 state changes over 10 minutes — count drops, watch for stutter.
4. Power-cycle it. Does it return to last state, or 100% white at 3am?

If it fails test 1, stop and reconsider the bulb before building on it.

## Build

- `drivers/light/lifx.py` — the LIFX LAN protocol over UDP:56700.
  - Broadcast `GetService` discovery, collect `StateService`, cache MAC→IP, re-discover every 5 min because DHCP moves things. **Bind by MAC, never by IP.**
  - `Light::SetColor` with HSBK plus `duration_ms` — the bulb does the fade. Map perceptual brightness through the curve to uint16.
  - Acknowledgement flags on important transitions (ramp start, ramp end), fire-and-forget for intermediate steps.
  - Report real `LightCapabilities`: measured `min_brightness`, `cct_range` starting at 1500, `supports_native_transition=True`, step interval 10–30s.
- Discovery wired into `POST /api/devices/lights/discover` with an identify-by-blink action.
- Run the existing conformance suite from task 02 against the real driver, unchanged.

## Done when

- [ ] `hardware/bulb-compatibility.md` has real measured numbers
- [ ] Real driver passes the same conformance suite as `MockLight`
- [ ] A 30-minute ramp sends fewer than 200 packets and shows no visible stepping to someone watching it
- [ ] Kill the daemon at t=12min, restart, and the ramp resumes within 5s at the correct brightness
- [ ] Unplug the bulb mid-ramp → `is_reachable()` goes false within 30s, routine survives
- [ ] Bulb's IP changes → rediscovered and rebound within 5 min

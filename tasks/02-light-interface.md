# Task 02 — Light interface, curves, and MockLight

**Read:** `docs/02-light-driver.md` (Part B especially), `docs/03-sunrise-engine.md`

**Hardware:** none

## Build

The abstraction every later light feature depends on, plus a fake bulb good enough to develop the whole product against.

- `drivers/light/base.py` — `LightState`, `LightCapabilities`, and the `Light` and `LightDiscovery` Protocols exactly as specified in spec 02 Part B. Brightness is perceptual 0.0–1.0 everywhere above the driver; device units never leak upward.
- `drivers/light/mock.py` — `MockLight`. Records every `apply()` call with the fake-clock timestamp so tests can assert on the whole state timeline. Configurable `min_brightness` and `supports_native_transition` so it can impersonate a LIFX or a WiZ.
- `core/curves.py` — load curve YAML, interpolate CCT keyframes, and implement the three brightness models (`cie`, `gamma:2.2`, `linear`). Pure functions, no I/O, no clock.
- `curves/sunrise-classic.yaml` and `curves/reverse-sunrise.yaml`, matching the keyframe table in spec 03.
- A driver conformance test suite that any `Light` implementation must pass — later tasks will run the real LIFX driver against it unchanged.

## Done when

- [ ] `MockLight` passes the conformance suite
- [ ] Curve YAML loads and validates; an unknown key is a hard error with the offending line
- [ ] `cie` model matches the CIE L* formula in spec 03 to 4 decimal places at t = 0, 0.25, 0.5, 0.75, 1
- [ ] CCT interpolation hits every keyframe exactly and is monotonic between them
- [ ] No vendor library is imported anywhere in this task

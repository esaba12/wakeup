# Task 03 — Sunrise engine

**Read:** `docs/03-sunrise-engine.md`, `docs/02-light-driver.md` (Part B)

**Hardware:** none

## Build

The component that turns a curve and a time window into `Light.apply()` calls. This is what determines whether the product is good.

- `core/sunrise.py` — `run_ramp(light, curve, start, end, target_brightness, clock)` per the pseudocode in spec 03.
  - `t` derived from wall clock every tick, never from an accumulator
  - brightness clamped up to `light.capabilities.min_brightness`
  - `transition_ms` set ~10% longer than the step interval so bulb-side fades overlap
  - step interval taken from driver capabilities
- Reverse ramp (wind-down) via the same code path with inverted `t` and different keyframes.
- Presets: `nightlight`, `reading`, `off`, expressed in the same state vocabulary, not as special cases.

## Done when

All of these are tests against `MockLight` with a fake clock:

- [ ] Golden timeline test: a 30-minute ramp produces monotonically increasing brightness with no step exceeding 1.5 L\* units
- [ ] Restart test: run to t=0.4, throw the engine away, reconstruct from persisted start/end, assert the next state is on the original trajectory
- [ ] Floor test: with `min_brightness=0.10`, no emitted brightness is below the floor and the curve is still monotonic
- [ ] The ramp ends exactly at `end`, at the target brightness and target CCT
- [ ] Engine imports nothing from `drivers/light/` except `base`

## Then, before task 04

Open `tools/sunrise-visualizer.html` and tune the CCT keyframes in `curves/sunrise-classic.yaml` until a ramp looks right to you. The visualizer implements the same math; use it as the design surface. This is the last cheap moment to change the curve.

# 03 — Sunrise / Light Curve Engine

## Purpose
Turn "wake me at 6:40 with a 30-minute sunrise" into a sequence of `Light.apply()` calls that *feels* like dawn. This is the component that determines whether the product is good.

## The problem
Human brightness perception is approximately a power law. A linear brightness ramp appears to do nothing for two thirds of its duration and then surge. Every bad DIY sunrise clock is a linear ramp.

## Perceptual model

Lightness (what you perceive) must be linear in time; luminance (what you command) is derived from it.

```python
def cie_luminance(lstar: float) -> float:
    """CIE L* (0..100 perceived lightness) -> relative luminance (0..1)."""
    if lstar > 8.0:
        return ((lstar + 16.0) / 116.0) ** 3
    return lstar / 903.3

def sunrise_brightness(t: float) -> float:      # t in [0,1]
    return cie_luminance(100.0 * t)
```

Cheap approximation, acceptable and one line: `brightness = t ** 2.2`.

The `Light` interface takes **perceptual** brightness 0.0–1.0 and each driver applies its own device mapping, so this conversion lives in exactly one place per driver, not in the engine.

## Color temperature ramp

Dawn is not a brightness ramp with fixed color. The circadian-relevant short-wavelength content belongs at the *end*; blue at minute 2 is what makes cheap wake-up lights feel harsh.

| Phase | t | Brightness | Color |
|---|---|---|---|
| Ember | 0.00–0.15 | floor → 0.5% | RGB deep red/amber (or 1500–1800K if the bulb reaches it) |
| Dawn | 0.15–0.50 | 0.5% → 8% | 1800 → 2400 K |
| Rise | 0.50–0.85 | 8% → 45% | 2400 → 3500 K |
| Day | 0.85–1.00 | 45% → target | 3500 → target CCT (default 4500 K) |

Implement as a piecewise-linear keyframe list over `t`, interpolated — not as four hard-coded branches — so curves are **data** and users can ship their own:

```yaml
# curves/sunrise-classic.yaml
name: sunrise-classic
brightness: cie          # cie | gamma:2.2 | linear | custom keyframes
keyframes:
  - { t: 0.00, cct: 1600, rgb: [255, 60, 0] }
  - { t: 0.15, cct: 1800 }
  - { t: 0.50, cct: 2400 }
  - { t: 0.85, cct: 3500 }
  - { t: 1.00, cct: 4500 }
```

## Execution

```python
async def run_ramp(light, curve, start: datetime, end: datetime, target_brightness: float):
    interval = light.capabilities.recommended_step_interval_ms / 1000
    while (now := clock.now()) < end:
        t = clamp((now - start) / (end - start), 0.0, 1.0)
        b = max(curve.brightness(t) * target_brightness, light.capabilities.min_brightness)
        state = curve.color_at(t, b)
        await light.apply(state, transition_ms=int(interval * 1000 * 1.1))
        await sleep_until(now + interval)
    await light.apply(curve.color_at(1.0, target_brightness), transition_ms=1000)
```

Non-negotiable properties:
- **`t` is derived from wall clock, never from an accumulator.** This is what makes the ramp resumable after a restart and immune to scheduler jitter and clock steps.
- `transition_ms` is set slightly *longer* than the step interval so consecutive bulb-side fades overlap instead of leaving a stutter gap.
- Step interval comes from driver capabilities: 10–30s for bulbs with native transitions, 2–4s for emulated ones.
- Brightness is clamped up to `min_brightness`, so on a bulb with a high floor the ramp starts at the floor rather than staying dark and then popping on.

## Reverse ramp (wind-down)
The same engine with `t → 1-t` and different keyframes: from 2700K/40% down to 1800K/night-light, then off. Duration typically 20–45 min. This is half the product's value and almost no DIY project implements it.

## Presets
Expressed in the same curve/state vocabulary, not as special cases:
- `nightlight` — ~1% at the bulb's minimum CCT, or pure red RGB. Must be usable for navigation without waking the visual system.
- `reading` — 70% at 2900 K.
- `off`.

## Testing
This component is pure, deterministic, and clock-injected, so it's fully testable:
- Golden-file test: 30-minute ramp against `MockLight` produces a state timeline; assert monotonic brightness, no step exceeding 1.5 L\* units, correct endpoint, correct CCT keyframe interpolation.
- Restart test: run to t=0.4, discard the engine, reconstruct from persisted start/end, assert the next emitted state is within tolerance of the pre-restart trajectory.
- Floor test: with `min_brightness=0.10` (WiZ), assert no emitted brightness is below the floor and the curve is still monotonic.

## Acceptance criteria
- [ ] Curves are loaded from YAML, not hard-coded
- [ ] A 30-min ramp on real hardware shows no perceptible step change to a person watching it
- [ ] Ramp completes exactly at alarm time, not starting at it
- [ ] Engine has zero knowledge of any vendor

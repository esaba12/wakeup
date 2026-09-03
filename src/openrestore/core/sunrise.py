"""Turns a curve and a time window into `Light.apply()` calls — the component
that determines whether the product is good. See docs/03-sunrise-engine.md.

Engine imports nothing from `drivers/light/` except `base`: it knows a
`Light`'s capabilities, never its vendor. `MockLight`, `LifxLight`, and every
future driver run through this unchanged."""

from __future__ import annotations

from datetime import datetime

from openrestore.core.clock import Clock
from openrestore.core.curves import Curve
from openrestore.drivers.light.base import Light, LightState


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def ramp_progress(now: datetime, start: datetime, end: datetime) -> float:
    """Fraction of the ramp elapsed, in [0.0, 1.0], derived from wall clock
    on every call — never from an accumulator. This is what makes a ramp
    resumable after a restart and immune to scheduler jitter and clock
    steps (docs/00-overview.md rule 2)."""
    total = (end - start).total_seconds()
    if total <= 0:
        return 1.0
    return _clamp01((now - start).total_seconds() / total)


def color_at(curve: Curve, light: Light, t: float, brightness: float) -> LightState:
    """Compose the `LightState` for curve position `t` at perceptual
    `brightness`, for this specific `light`.

    Falls back to a keyframe's `rgb` when the curve's interpolated CCT is
    below what `light` can render — e.g. the sunrise-classic ember keyframe
    wants 1600K, which only a LIFX-class bulb reaches natively (see
    docs/02-light-driver.md Part A: "1500-1800K if the bulb reaches it").
    Once the interpolated CCT rises back into the light's range, color
    reverts to CCT mode — a self-limiting crossover with no extra state.
    """
    cct = curve.cct_at(t)
    min_cct = light.capabilities.cct_range[0]
    if cct < min_cct and light.capabilities.supports_rgb:
        rgb = curve.rgb_at(t)
        if rgb is not None:
            return LightState(on=brightness > 0.0, brightness=brightness, cct=None, rgb=rgb)
    return LightState(on=brightness > 0.0, brightness=brightness, cct=cct, rgb=None)


async def run_ramp(
    light: Light,
    curve: Curve,
    start: datetime,
    end: datetime,
    target_brightness: float,
    clock: Clock,
    *,
    reverse: bool = False,
) -> None:
    """Run a ramp from `start` to `end`, driving `light` toward
    `target_brightness` along `curve`.

    Safe to call after a restart with the same `start`/`end`: every tick
    recomputes its position from `clock.now()`, so calling this again after
    a crash resumes wherever the wall clock says the ramp should be — there
    is no ramp-internal state to reconstruct.

    `reverse=True` runs a wind-down: per docs/03-sunrise-engine.md ("the
    same engine with t -> 1-t and different keyframes"), curve position is
    `1 - wall_progress`, so the curve is read from its t=1 end toward its
    t=0 end as wall time advances from `start` to `end`.
    """
    interval_s = light.capabilities.recommended_step_interval_ms / 1000
    # Slightly longer than the step interval so consecutive bulb-side fades
    # overlap instead of leaving a stutter gap (docs/03-sunrise-engine.md).
    transition_ms = int(interval_s * 1000 * 1.1)

    async def apply_at(curve_t: float, transition: int) -> None:
        # curve.brightness(1.0) == 1.0 for every model (cie/linear/gamma all
        # hit their ceiling at t=1), so this is exactly target_brightness at
        # the forward end — matching spec 03's pseudocode — and correctly
        # falls to the floor (or 0) at a reverse ramp's end (curve_t=0.0),
        # rather than jumping back up to the wind-down's starting brightness.
        brightness = max(
            curve.brightness(curve_t) * target_brightness,
            light.capabilities.min_brightness,
        )
        state = color_at(curve, light, curve_t, brightness)
        await light.apply(state, transition_ms=transition)

    while (now := clock.now()) < end:
        wall_t = ramp_progress(now, start, end)
        curve_t = (1.0 - wall_t) if reverse else wall_t
        await apply_at(curve_t, transition_ms)
        await clock.sleep(interval_s)

    final_curve_t = 0.0 if reverse else 1.0
    await apply_at(final_curve_t, 1000)


# --- Presets ---------------------------------------------------------------
# Expressed in the same LightState vocabulary as a ramp step, not as special
# cases (docs/03-sunrise-engine.md "Presets").


def nightlight_state(light: Light) -> LightState:
    """~1% brightness, pure red if the light supports RGB — usable for
    navigation without waking the visual system — else its lowest CCT."""
    brightness = max(0.01, light.capabilities.min_brightness)
    if light.capabilities.supports_rgb:
        return LightState(on=True, brightness=brightness, cct=None, rgb=(255, 0, 0))
    return LightState(
        on=True, brightness=brightness, cct=light.capabilities.cct_range[0], rgb=None
    )


def reading_state() -> LightState:
    """70% at 2900K."""
    return LightState(on=True, brightness=0.70, cct=2900, rgb=None)


def off_state() -> LightState:
    return LightState(on=False, brightness=0.0, cct=None, rgb=None)

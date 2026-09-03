from __future__ import annotations

import ast
import asyncio
import contextlib
from collections.abc import Coroutine
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from openrestore.core.clock import FakeClock
from openrestore.core.curves import load_curve
from openrestore.core.sunrise import (
    color_at,
    nightlight_state,
    off_state,
    ramp_progress,
    reading_state,
    run_ramp,
)
from openrestore.drivers.light.mock import MockLight

REPO_ROOT = Path(__file__).resolve().parent.parent
CURVES_DIR = REPO_ROOT / "curves"
SUNRISE_PY = REPO_ROOT / "src" / "openrestore" / "core" / "sunrise.py"


def _sunrise_classic():
    return load_curve(CURVES_DIR / "sunrise-classic.yaml")


def _reverse_sunrise():
    return load_curve(CURVES_DIR / "reverse-sunrise.yaml")


async def _drive(
    fake_clock: FakeClock,
    coro: Coroutine[Any, Any, None],
    step_s: float,
    max_iterations: int = 20_000,
) -> None:
    """Run `coro` (a `run_ramp` call) to completion against `fake_clock`,
    advancing it in `step_s` increments and yielding to the event loop
    between advances so the coroutine's internal `clock.sleep()` calls get
    scheduled. `step_s` need not match the ramp's own step interval."""
    task = asyncio.ensure_future(coro)
    iterations = 0
    while not task.done():
        await asyncio.sleep(0)
        if task.done():
            break
        fake_clock.advance(step_s)
        iterations += 1
        if iterations > max_iterations:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise AssertionError("run_ramp did not finish driving in time")
    await task


# --- ramp_progress -----------------------------------------------------


def test_ramp_progress_clamps_before_start_and_after_end() -> None:
    start = FakeClock().now()
    end = start + timedelta(minutes=10)
    assert ramp_progress(start - timedelta(minutes=1), start, end) == 0.0
    assert ramp_progress(end + timedelta(minutes=1), start, end) == 1.0


def test_ramp_progress_is_linear_in_wall_time() -> None:
    start = FakeClock().now()
    end = start + timedelta(minutes=10)
    assert ramp_progress(start + timedelta(minutes=5), start, end) == pytest.approx(0.5)


# --- color_at ------------------------------------------------------------


def test_color_at_uses_cct_when_light_can_reach_it(fake_clock: FakeClock) -> None:
    curve = _sunrise_classic()
    light = MockLight(fake_clock, cct_range=(1500, 9000))
    state = color_at(curve, light, 0.0, 0.005)
    assert state.rgb is None
    assert state.cct == 1600


def test_color_at_falls_back_to_rgb_when_cct_unreachable(fake_clock: FakeClock) -> None:
    curve = _sunrise_classic()
    light = MockLight(fake_clock, cct_range=(2200, 6500))  # e.g. a Hue-class floor
    at_start = color_at(curve, light, 0.0, 0.005)
    assert at_start.cct is None
    assert at_start.rgb == (255, 60, 0)

    # once the curve's interpolated cct clears the light's floor, cct mode returns
    at_midpoint = color_at(curve, light, 0.5, 0.5)
    assert at_midpoint.rgb is None
    assert at_midpoint.cct == 2400


def test_color_at_never_falls_back_to_rgb_if_light_lacks_rgb(fake_clock: FakeClock) -> None:
    curve = _sunrise_classic()
    light = MockLight(fake_clock, cct_range=(2200, 6500), supports_rgb=False)
    state = color_at(curve, light, 0.0, 0.005)
    assert state.rgb is None
    assert state.cct == 1600  # unreachable in reality, but the engine doesn't lie for it


# --- run_ramp: golden timeline --------------------------------------------


async def test_golden_timeline_monotonic_brightness_and_small_steps(fake_clock: FakeClock) -> None:
    curve = _sunrise_classic()
    light = MockLight(fake_clock, cct_range=(1500, 9000))
    start = fake_clock.now()
    end = start + timedelta(minutes=30)

    await _drive(
        fake_clock, run_ramp(light, curve, start, end, target_brightness=1.0, clock=fake_clock), 15
    )

    brightnesses = [entry.state.brightness for entry in light.history]
    assert brightnesses == sorted(brightnesses)

    total_s = (end - start).total_seconds()
    for prev, curr in zip(light.history, light.history[1:], strict=False):
        dt = (curr.at - prev.at).total_seconds()
        lstar_step = 100.0 * dt / total_s
        assert lstar_step <= 1.5

    assert light.history[-1].state.brightness == pytest.approx(1.0)
    assert light.history[-1].state.cct == 4500


async def test_ramp_ends_at_target_brightness_and_cct(fake_clock: FakeClock) -> None:
    curve = _sunrise_classic()
    light = MockLight(fake_clock, cct_range=(1500, 9000))
    start = fake_clock.now()
    end = start + timedelta(minutes=10)

    await _drive(
        fake_clock, run_ramp(light, curve, start, end, target_brightness=0.8, clock=fake_clock), 15
    )

    final = light.history[-1].state
    assert final.brightness == pytest.approx(0.8)
    assert final.cct == 4500


# --- run_ramp: floor -------------------------------------------------------


async def test_floor_clamps_brightness_but_stays_monotonic(fake_clock: FakeClock) -> None:
    curve = _sunrise_classic()
    light = MockLight(fake_clock, cct_range=(1500, 9000), min_brightness=0.10)
    start = fake_clock.now()
    end = start + timedelta(minutes=30)

    await _drive(
        fake_clock, run_ramp(light, curve, start, end, target_brightness=1.0, clock=fake_clock), 30
    )

    brightnesses = [entry.state.brightness for entry in light.history]
    assert all(b >= 0.10 for b in brightnesses)
    assert brightnesses == sorted(brightnesses)


# --- run_ramp: restart -----------------------------------------------------


async def test_restart_resumes_on_original_trajectory(fake_clock: FakeClock) -> None:
    curve = _sunrise_classic()
    start = fake_clock.now()
    end = start + timedelta(minutes=30)
    target_brightness = 1.0

    crashed_light = MockLight(fake_clock, cct_range=(1500, 9000))
    task = asyncio.ensure_future(
        run_ramp(crashed_light, curve, start, end, target_brightness, clock=fake_clock)
    )
    # advance to t=0.4 of the ramp (12 of 30 minutes)
    for _ in range(48):
        await asyncio.sleep(0)
        fake_clock.advance(15)
    await asyncio.sleep(0)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert ramp_progress(fake_clock.now(), start, end) == pytest.approx(0.4)
    expected_t = ramp_progress(fake_clock.now(), start, end)
    expected_brightness = max(
        curve.brightness(expected_t) * target_brightness,
        crashed_light.capabilities.min_brightness,
    )
    expected_state = color_at(curve, crashed_light, expected_t, expected_brightness)

    # "discard the engine": a fresh light instance, reconstructed only from
    # the persisted start/end — no state carried over from crashed_light.
    resumed_light = MockLight(fake_clock, cct_range=(1500, 9000))
    resumed_task = asyncio.ensure_future(
        run_ramp(resumed_light, curve, start, end, target_brightness, clock=fake_clock)
    )
    await asyncio.sleep(0)

    assert resumed_light.history, "expected the resumed ramp to apply immediately"
    assert resumed_light.history[0].state == expected_state

    resumed_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await resumed_task


# --- run_ramp: reverse (wind-down) -----------------------------------------


async def test_reverse_ramp_reads_the_curve_backwards(fake_clock: FakeClock) -> None:
    curve = _reverse_sunrise()
    light = MockLight(fake_clock, cct_range=(1500, 9000))
    start = fake_clock.now()
    end = start + timedelta(minutes=20)

    await _drive(
        fake_clock,
        run_ramp(
            light, curve, start, end, target_brightness=0.4, clock=fake_clock, reverse=True
        ),
        15,
    )

    assert light.history[0].state.cct == 2700
    assert light.history[0].state.brightness == pytest.approx(0.4)
    assert light.history[-1].state.cct == 1800
    assert light.history[-1].state.brightness == pytest.approx(0.0, abs=1e-9)

    brightnesses = [entry.state.brightness for entry in light.history]
    assert brightnesses == sorted(brightnesses, reverse=True)


# --- presets ----------------------------------------------------------------


def test_nightlight_prefers_red_rgb_when_supported(fake_clock: FakeClock) -> None:
    light = MockLight(fake_clock)
    state = nightlight_state(light)
    assert state.rgb == (255, 0, 0)
    assert state.cct is None
    assert state.brightness == pytest.approx(0.01)


def test_nightlight_falls_back_to_min_cct_without_rgb(fake_clock: FakeClock) -> None:
    light = MockLight(fake_clock, supports_rgb=False, cct_range=(2000, 6500))
    state = nightlight_state(light)
    assert state.rgb is None
    assert state.cct == 2000


def test_nightlight_never_goes_below_the_lights_floor(fake_clock: FakeClock) -> None:
    light = MockLight(fake_clock, min_brightness=0.05)
    state = nightlight_state(light)
    assert state.brightness == pytest.approx(0.05)


def test_reading_state_is_70_percent_at_2900k() -> None:
    state = reading_state()
    assert state.brightness == pytest.approx(0.70)
    assert state.cct == 2900


def test_off_state_is_off() -> None:
    state = off_state()
    assert state.on is False
    assert state.brightness == 0.0


# --- layering rule ---------------------------------------------------------


def test_engine_imports_nothing_from_drivers_light_except_base() -> None:
    tree = ast.parse(SUNRISE_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("openrestore.drivers.light"):
                assert node.module == "openrestore.drivers.light.base"
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("openrestore.drivers.light"):
                    assert alias.name == "openrestore.drivers.light.base"

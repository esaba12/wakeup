"""Shared test-only helpers for the API/state test suite (tests/test_state.py,
tests/test_api_rest.py, tests/test_api_ws.py, tests/test_app.py). Not a test
module itself (no `test_` prefix), so pytest never collects it directly —
mirrors the inline-helper convention `tests/test_scheduler.py`'s
`_make_scheduler` already established, just shared across several files
since task 07's harness is bigger than one scheduler."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI

from openrestore.app import AppContext, build_context, create_app
from openrestore.core.clock import FakeClock
from openrestore.drivers.audio.mock import MockAudioOutput
from openrestore.drivers.light.mock import MockLight

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTINES_DIR = REPO_ROOT / "routines"
CURVES_DIR = REPO_ROOT / "curves"


async def build_test_context(
    *,
    start: datetime | None = None,
    clock_synced: bool = True,
    routines_dir: Path | None = None,
    db_path: str | Path = ":memory:",
    bearer_token: str | None = None,
    background: bool = False,
) -> tuple[AppContext, FakeClock]:
    """A fully-wired `AppContext` on mock light/audio drivers and a
    `FakeClock` — the API-layer equivalent of `--mock-light --mock-audio`.
    `background=False` (the default) hydrates the scheduler and runs one
    catch-up tick without spawning the real ticking loops, which would spin
    at full speed forever under a clock whose `sleep()` never really
    advances time; call `ctx.tick()` after `clock.advance()` to drive it
    instead."""
    clock = FakeClock(start) if start is not None else FakeClock()
    light = MockLight(clock)
    audio = MockAudioOutput(clock)
    ctx = await build_context(
        clock=clock,
        light=light,
        audio=audio,
        db_path=db_path,
        routines_dir=routines_dir or ROUTINES_DIR,
        curves_dir=CURVES_DIR,
        clock_synced=clock_synced,
        background=background,
        bearer_token=bearer_token,
    )
    return ctx, clock


def build_test_app(ctx: AppContext) -> FastAPI:
    return create_app(ctx)

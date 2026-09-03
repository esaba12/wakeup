"""Assembles the running daemon: `Store`, `Clock`, `EventBus`, `Scheduler`,
`RoutineEngine`, drivers, and the wiring between them — the "new small
app-assembly module" tasks/07-api.md calls for. `cli.py`'s `serve` command
and the test suite both build an `AppContext` through `build_context()` and
hand it to `create_app()`; nothing about the FastAPI app itself is aware of
mock vs. real drivers.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI

from openrestore.core.clock import Clock
from openrestore.core.errors import ConfigError, RoutineError
from openrestore.core.events import Event, EventBus, EventType
from openrestore.core.routines import Routine, RoutineEngine, load_routine
from openrestore.core.scheduler import Scheduler
from openrestore.core.store import Store
from openrestore.drivers.audio.base import AudioOutput
from openrestore.drivers.light.base import Light

logger = structlog.get_logger()

EventListener = Callable[[Event], Awaitable[None]]

# docs/07-api-and-state.md: "idempotency keys on POSTs that fire actions".
# Retry collapsing for a client's own request, not crash recovery —
# Store.reserve_occurrence already owns the crash-safe gate for alarm
# firing — so an in-memory, unbounded-but-capped cache is enough.
_IDEMPOTENCY_MAX_ENTRIES = 512


class IdempotencyStore:
    """Replay cache keyed by `f"{method}:{path}:{Idempotency-Key}"`. A
    second POST with the same key on the same route returns the first
    response verbatim instead of re-running the side effect."""

    def __init__(self, max_entries: int = _IDEMPOTENCY_MAX_ENTRIES) -> None:
        self._cache: dict[str, tuple[int, Any]] = {}
        self._order: list[str] = []
        self._max_entries = max_entries

    def get(self, key: str) -> tuple[int, Any] | None:
        return self._cache.get(key)

    def put(self, key: str, status_code: int, body: Any) -> None:
        if key not in self._cache:
            self._order.append(key)
            if len(self._order) > self._max_entries:
                oldest = self._order.pop(0)
                self._cache.pop(oldest, None)
        self._cache[key] = (status_code, body)


class AppContext:
    """Owns every long-lived component for one running daemon: the event
    bus's centralized `events` table logging, and the glue that starts a
    routine when the scheduler says it's time to."""

    def __init__(
        self,
        *,
        store: Store,
        clock: Clock,
        event_bus: EventBus,
        scheduler: Scheduler,
        routine_engine: RoutineEngine,
        light: Light,
        audio: AudioOutput,
        routines_dir: Path,
        tz: str = "UTC",
        clock_source: str = "system",
        bearer_token: str | None = None,
        background: bool = True,
    ) -> None:
        self.store = store
        self.clock = clock
        self.event_bus = event_bus
        self.scheduler = scheduler
        self.routine_engine = routine_engine
        self.light = light
        self.audio = audio
        self.routines_dir = routines_dir
        self.tz = tz
        self.clock_source = clock_source
        self.bearer_token = bearer_token
        # Whether `create_app()`'s lifespan should spawn the scheduler's and
        # routine engine's real background ticking loops. `False` for tests
        # under a `FakeClock` (see `start()`'s docstring).
        self.background = background
        self.idempotency = IdempotencyStore()
        self._listeners: list[EventListener] = []
        self._sleep_timer_tasks: set[asyncio.Task[None]] = set()
        self._started = False

    def add_event_listener(self, listener: EventListener) -> None:
        """Registered by the WebSocket layer (`api/ws.py`) to be notified of
        every published event, for event-driven delta pushes."""
        self._listeners.append(listener)

    def load_routine(self, routine_id: str) -> Routine:
        path = self.routines_dir / f"{routine_id}.yaml"
        if not path.exists():
            raise ConfigError(f"no routine {routine_id!r} at {path}")
        return load_routine(path)

    def schedule_sleep_timer(self, seconds: float) -> None:
        """A manual `POST /api/audio/play` with a `sleep_timer` has no
        routine step behind it to run `RoutineEngine`'s own sleep-timer
        logic, so this is the API layer's equivalent: stop `audio` after
        `seconds`, via the injected `Clock` so tests stay deterministic."""
        task = asyncio.ensure_future(self._run_sleep_timer(seconds))
        self._sleep_timer_tasks.add(task)
        task.add_done_callback(self._sleep_timer_tasks.discard)

    async def _run_sleep_timer(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await self.clock.sleep(seconds)
            await self.audio.stop()

    async def start(self, *, background: bool = True) -> None:
        """`background=True` (the default; used by `cli.py`) spawns the
        scheduler's and routine engine's real ticking loops. Tests under a
        `FakeClock` — whose `sleep()` never advances real time, so a
        background loop built on it would spin at full speed forever —
        pass `background=False` and drive ticks manually instead, matching
        the convention `tests/test_scheduler.py` and `tests/test_routines.py`
        already established for those components individually."""
        self.event_bus.subscribe(self._on_event)
        if background:
            await self.scheduler.start()
            await self.routine_engine.start()
        else:
            await self.scheduler.load()
            await self.scheduler.tick()
        self._started = True

    async def stop(self) -> None:
        if self._started:
            await self.scheduler.stop()
            await self.routine_engine.stop()
            self._started = False
        for task in list(self._sleep_timer_tasks):
            task.cancel()
        for task in list(self._sleep_timer_tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.store.close()

    async def tick(self) -> None:
        """Manual combined tick for tests: advance the `FakeClock` first,
        then call this so both engines notice."""
        await self.scheduler.tick()
        await self.routine_engine.tick()

    async def _on_event(self, event: Event) -> None:
        # Centralized event-log persistence (tasks/07-api.md: "Event log:
        # every bus event written to the `events` table") — the scheduler
        # used to do this itself; now every producer's events land here,
        # exactly once, from one place.
        await self.store.log_event(event, self.clock.now())
        if event.type == EventType.RAMP_START:
            await self._start_bound_routine(event)
        for listener in list(self._listeners):
            await listener(event)

    async def _start_bound_routine(self, event: Event) -> None:
        """The scheduler's `ramp.start` fires `pre_roll_s` before an alarm's
        target time — exactly when the bound routine's sunrise ramp should
        begin, with `trigger_at` set to the alarm's actual fire time so the
        routine engine's own state machine (docs/06-routine-engine.md)
        transitions SUNRISE -> ALARM on its own once the wall clock catches
        up. This wiring isn't a named endpoint or event in docs/07 — without
        it, an alarm never starts anything, so building it was necessary to
        make the API's state object meaningful; flagged in the task report.

        A missing or invalid routine file can't be allowed to silently
        swallow an alarm (docs/00-overview.md rule 4, "the alarm is the
        product"): report `preflight.failed` and keep going. Task 10 owns
        the actual fallback path; this only guarantees the daemon doesn't
        crash and the failure is visible in the event log.
        """
        routine_id = event.payload["routine_id"]
        try:
            routine = self.load_routine(routine_id)
        except ConfigError as exc:
            await self._report_preflight_failure(routine_id, str(exc))
            return

        trigger_at = self.clock.now()
        fire_at_raw = event.payload.get("fire_at")
        if fire_at_raw is not None:
            trigger_at = datetime.fromisoformat(fire_at_raw)

        try:
            await self.routine_engine.start_routine(routine, trigger_at=trigger_at)
        except RoutineError as exc:
            await self._report_preflight_failure(routine_id, str(exc))

    async def _report_preflight_failure(self, routine_id: str, reason: str) -> None:
        logger.error("routine.preflight_failed", routine_id=routine_id, reason=reason)
        await self.event_bus.publish(
            Event(
                type=EventType.PREFLIGHT_FAILED,
                payload={"routine_id": routine_id, "reason": reason},
            )
        )


async def build_context(
    *,
    clock: Clock,
    light: Light,
    audio: AudioOutput,
    db_path: str | Path,
    routines_dir: Path,
    curves_dir: Path | None = None,
    tz: str = "UTC",
    clock_source: str = "system",
    bearer_token: str | None = None,
    clock_synced: bool = True,
    background: bool = True,
) -> AppContext:
    """Convenience factory: open the store, build the event bus, scheduler,
    and routine engine, and wrap them all in one `AppContext`. Used by both
    `cli.py` (real drivers or mocks, `SystemClock`) and the test suite
    (mocks, `FakeClock`) so there's exactly one place that wires these
    components together."""
    store = await Store.open(db_path)
    event_bus = EventBus()
    scheduler = Scheduler(store, clock, event_bus, clock_synced=clock_synced)
    routine_engine = RoutineEngine(
        light, audio, clock, event_bus, curves_dir=curves_dir or _curves_dir()
    )
    return AppContext(
        store=store,
        clock=clock,
        event_bus=event_bus,
        scheduler=scheduler,
        routine_engine=routine_engine,
        light=light,
        audio=audio,
        routines_dir=routines_dir,
        tz=tz,
        clock_source=clock_source,
        bearer_token=bearer_token,
        background=background,
    )


def _curves_dir() -> Path:
    """The shipped `curves/` directory at the repo root (docs/00-overview.md
    layout). Not configurable yet — spec 11 (config & onboarding, not built
    by this task) is where a `paths.curves` override belongs."""
    return Path(__file__).resolve().parents[2] / "curves"


def create_app(ctx: AppContext) -> FastAPI:
    """Build the FastAPI app around an already-constructed `AppContext`.
    Import the routers lazily (inside the function) rather than at module
    scope, so importing `openrestore.app` alone never requires `fastapi` to
    already have `api.rest`/`api.ws` fully wired — mirrors docs/00-overview.md
    rule 3's "imported lazily" spirit for the transport layer."""
    from openrestore.api.rest import router as rest_router
    from openrestore.api.ws import ConnectionManager
    from openrestore.api.ws import router as ws_router

    manager = ConnectionManager(ctx)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        await ctx.start(background=ctx.background)
        if ctx.background:
            # Under a `FakeClock` (tests, `ctx.background=False`) this loop's
            # `clock.sleep()` never actually advances time, so it would spin
            # at full speed for as long as the app is up. Tests drive the
            # WebSocket delta stream manually instead (`ConnectionManager
            # .broadcast_delta()`), the same way they drive `Scheduler`/
            # `RoutineEngine` via manual `tick()` rather than their loops.
            await manager.start_ticker()
        yield
        if ctx.background:
            await manager.stop_ticker()
        await ctx.stop()

    app = FastAPI(title="OpenRestore", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    app.state.ws_manager = manager
    app.include_router(rest_router)
    app.include_router(ws_router)
    return app

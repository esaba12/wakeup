"""WebSocket state fan-out. See docs/07-api-and-state.md.

`GET /api/events` upgrades. On connect the server sends the full state
object; after that, only deltas — the same shared broadcast stream every
connected client sees, computed at ~1 Hz while a routine is actively
ramping and pushed immediately whenever the event bus fires otherwise
(docs/07: "~1 Hz during a ramp, event-driven otherwise"). Client -> server
messages are dispatched through `api/actions.py`, the same functions the
REST layer's POST handlers call, so a physical puck and the web UI speak
one protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from openrestore.api import actions
from openrestore.api.auth import is_authorized
from openrestore.app import AppContext
from openrestore.core.events import Event
from openrestore.core.routines import RoutineState
from openrestore.core.state import build_state, state_delta, state_to_dict

logger = structlog.get_logger()

router = APIRouter()

# docs/07-api-and-state.md: "~1 Hz during a ramp, event-driven otherwise".
_RAMP_TICK_S = 1.0
_ACTIVE_ROUTINE_STATES = {
    RoutineState.WINDDOWN,
    RoutineState.SUNRISE,
    RoutineState.ALARM,
    RoutineState.SNOOZE,
}


class ConnectionManager:
    """Owns every connected `/api/events` socket and the shared "last
    broadcast" snapshot deltas are diffed against."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._connections: set[WebSocket] = set()
        self._last_broadcast: dict[str, Any] | None = None
        self._ticker_task: asyncio.Task[None] | None = None
        ctx.add_event_listener(self._on_event)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        state = await self._current_state_dict()
        self._last_broadcast = state
        await ws.send_json({"type": "state", "data": state})

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def _on_event(self, event: Event) -> None:
        await self.broadcast_delta()

    async def broadcast_delta(self) -> None:
        if not self._connections:
            return
        state = await self._current_state_dict()
        delta = state if self._last_broadcast is None else state_delta(self._last_broadcast, state)
        self._last_broadcast = state
        if not delta:
            return
        message = {"type": "delta", "data": delta}
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - a dead socket must not break the others
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def _current_state_dict(self) -> dict[str, Any]:
        state = await build_state(
            clock=self._ctx.clock,
            tz=self._ctx.tz,
            scheduler=self._ctx.scheduler,
            routine_engine=self._ctx.routine_engine,
            light=self._ctx.light,
            audio=self._ctx.audio,
            clock_source=self._ctx.clock_source,
        )
        return state_to_dict(state)

    def _ramp_active(self) -> bool:
        run = self._ctx.routine_engine.current_run
        return run is not None and run.state in _ACTIVE_ROUTINE_STATES

    async def start_ticker(self) -> None:
        self._ticker_task = asyncio.ensure_future(self._tick_loop())

    async def stop_ticker(self) -> None:
        if self._ticker_task is not None:
            self._ticker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ticker_task
            self._ticker_task = None

    async def _tick_loop(self) -> None:
        while True:
            await self._ctx.clock.sleep(_RAMP_TICK_S)
            if self._ramp_active():
                await self.broadcast_delta()


async def _handle_action_message(ctx: AppContext, message: dict[str, Any]) -> dict[str, Any]:
    action = message.get("action")
    if not isinstance(action, str):
        return {"type": "error", "error": "missing 'action'"}
    try:
        result = await actions.dispatch(ctx, action, message)
    except actions.ActionError as exc:
        return {"type": "error", "action": action, "error": str(exc)}
    return {"type": "ack", "action": action, "data": result}


@router.websocket("/api/events")
async def events_ws(ws: WebSocket) -> None:
    ctx: AppContext = ws.app.state.ctx
    manager: ConnectionManager = ws.app.state.ws_manager
    if not is_authorized(ctx, ws.headers.get("authorization"), ws.query_params.get("token")):
        await ws.close(code=4401)
        return
    await manager.connect(ws)
    try:
        while True:
            message = await ws.receive_json()
            reply = await _handle_action_message(ctx, message)
            await ws.send_json(reply)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)

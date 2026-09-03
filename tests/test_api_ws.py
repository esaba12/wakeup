"""WebSocket tests, per tasks/07-api.md's "Done when" list: full state on
connect, deltas thereafter, reconnect resync, deltas under 1 KB during a
ramp, and client -> server actions.

`ConnectionManager`'s own periodic ticker is disabled under a `FakeClock`
(see `app.py`'s `create_app`, `ctx.background`), so a "live 60x-compressed
ramp" is simulated the same way `tests/test_scheduler.py` and
`tests/test_routines.py` simulate real time: `clock.advance()` + `ctx.tick()`
+ an explicit `ws_manager.broadcast_delta()` — standing in for what the real
~1 Hz ticker would have done on its own.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from starlette.testclient import TestClient

from tests._helpers import build_test_app, build_test_context

# weekday-wake.yaml's "sunrise" step spans exactly [ramp_start, trigger_at)
# (`ends_at: trigger`, docs/06-routine-engine.md) — its nominal `duration:
# 30m` is only there to satisfy the schema, not the actual window size — so
# `pre_roll_s` must be 1800 for a real 30-minute ramp to simulate.
_ALARM_BODY = {
    "id": "a1",
    "time": "06:40:00",
    "days": [1, 2, 3, 4, 5],
    "routine_id": "weekday-wake",
    "pre_roll_s": 1800,
    "timezone": "UTC",
}


async def test_full_state_on_connect() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client, client.websocket_connect("/api/events") as ws:
        message = ws.receive_json()
        assert message["type"] == "state"
        assert set(message["data"].keys()) == {
            "clock",
            "routine",
            "light",
            "audio",
            "next_alarm",
            "health",
        }


async def test_reconnect_resyncs_from_full_state_without_a_restart() -> None:
    """tasks/07-api.md "Done when": a WebSocket client reconnects and
    resyncs from full state without a restart."""
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        with client.websocket_connect("/api/events") as ws1:
            first = ws1.receive_json()
            assert first["type"] == "state"

        # change something while disconnected
        client.post("/api/light/preset/nightlight")

        with client.websocket_connect("/api/events") as ws2:
            second = ws2.receive_json()
            assert second["type"] == "state"
            assert second["data"]["light"]["on"] is True


async def test_action_over_websocket_dismiss() -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    ctx, _clock = await build_test_context(start=start)
    app = build_test_app(ctx)
    with TestClient(app) as client:
        client.post(
            "/api/routines/weekday-wake/start", json={"trigger_at": start.isoformat()}
        )
        with client.websocket_connect("/api/events") as ws:
            ws.receive_json()  # initial full state
            ws.send_json({"action": "dismiss"})
            # `dismiss()` itself fires a `routine.transition` event, which
            # the same connection sees as an event-driven delta *before*
            # the handler's own ack reply goes out — both messages arrive,
            # in that order.
            pushed_delta = ws.receive_json()
            assert pushed_delta["type"] == "delta"
            assert pushed_delta["data"]["routine"]["state"] == "AWAKE"
            ack = ws.receive_json()
            assert ack == {"type": "ack", "action": "dismiss", "data": None}
        state = client.get("/api/state")
        assert state.json()["routine"]["state"] == "AWAKE"


async def test_unknown_action_returns_an_error_not_a_disconnect() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client, client.websocket_connect("/api/events") as ws:
        ws.receive_json()
        ws.send_json({"action": "not.a.real.action"})
        reply = ws.receive_json()
        assert reply["type"] == "error"
        # the socket is still alive after an error
        ws.send_json({"action": "dismiss"})
        reply2 = ws.receive_json()
        assert reply2["type"] == "error"  # no active run, but still a clean error


def _drain_until_settled(ws: object, *, expected_state: str, max_messages: int = 5) -> dict:
    """A tick that crosses a routine state transition (IDLE -> SUNRISE, here)
    fires more than one event on the bus — the transition itself, plus the
    routine engine's own first-tick step application — so more than one
    delta lands for a single `ctx.tick()`. Every one of them must still be
    small; only the *last* one is the settled state a UI should render."""
    last: dict | None = None
    for _ in range(max_messages):
        message = ws.receive_json()  # type: ignore[attr-defined]
        assert message["type"] == "delta"
        assert len(json.dumps(message).encode()) < 1024
        last = message
        if message["data"].get("routine", {}).get("state") == expected_state and message[
            "data"
        ]["routine"].get("step") is not None:
            break
    assert last is not None
    return last


async def test_delta_after_ramp_start_is_small_and_reflects_progress() -> None:
    """tasks/07-api.md "Done when": state deltas stay under 1 KB during a
    ramp; a client sees the ramp update as time advances."""
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    ctx, clock = await build_test_context(start=start)
    app = build_test_app(ctx)
    with TestClient(app) as client:
        client.post("/api/alarms", json=_ALARM_BODY)
        with client.websocket_connect("/api/events") as ws:
            initial = ws.receive_json()
            assert initial["data"]["routine"]["state"] == "IDLE"

            clock.advance(30 * 60)  # 06:30 -> ramp_start instant (30 min pre-roll)
            await ctx.tick()  # the RAMP_START/transition events push their own deltas

            settled = _drain_until_settled(ws, expected_state="SUNRISE")
            assert settled["data"]["routine"]["step"] == "sunrise"
            assert settled["data"]["routine"]["progress"] == 0.0

            # A plain tick partway through the ramp — no state transition, so
            # no event fires — produces exactly one delta, from this
            # connection's own `ConnectionManager` (what the real ~1 Hz
            # ticker does in production; disabled here under `FakeClock`,
            # see app.py's `create_app`).
            clock.advance(3 * 60)  # 3 of the 10-minute [06:30, 06:40) window
            await ctx.tick()
            manager = app.state.ws_manager
            await manager.broadcast_delta()

            progressed = ws.receive_json()
            assert progressed["type"] == "delta"
            assert len(json.dumps(progressed).encode()) < 1024
            assert abs(progressed["data"]["routine"]["progress"] - 0.3) < 1e-9


async def test_no_delta_sent_when_nothing_changed() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    manager = app.state.ws_manager
    with TestClient(app) as client, client.websocket_connect("/api/events") as ws:
        ws.receive_json()  # initial state
        await manager.broadcast_delta()  # nothing changed since connect
        # No message should be waiting; send a no-op action and confirm the
        # very next message is its own ack, not a stray empty delta.
        ws.send_json({"action": "dismiss"})
        reply = ws.receive_json()
        assert reply["type"] == "error"

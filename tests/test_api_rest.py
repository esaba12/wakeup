"""REST endpoint tests, per tasks/07-api.md's "Done when" list. Drives the
FastAPI app in-process via `starlette.testclient.TestClient` — no real
network socket, no real time (`FakeClock` throughout), no real hardware
(`MockLight`/`MockAudioOutput`)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from starlette.testclient import TestClient

from tests._helpers import build_test_app, build_test_context

_ALARM_BODY = {
    "id": "a1",
    "time": "06:40:00",
    "days": [1, 2, 3, 4, 5],
    "routine_id": "weekday-wake",
    "pre_roll_s": 300,
    "timezone": "UTC",
}


async def test_get_state_returns_a_sane_object_with_mock_drivers() -> None:
    """tasks/07-api.md "Done when": `curl localhost:8080/api/state` with
    `--mock-light --mock-audio` returns a sane object on a laptop."""
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.get("/api/state")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "clock",
            "routine",
            "light",
            "audio",
            "next_alarm",
            "health",
        }
        assert body["health"] == "ok"
        assert body["routine"]["state"] == "IDLE"
        assert body["light"]["id"]
        assert body["audio"]["output"]


async def test_get_health() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# --- alarm CRUD ------------------------------------------------------------


async def test_alarm_crud_round_trip() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        created = client.post("/api/alarms", json=_ALARM_BODY)
        assert created.status_code == 201
        assert created.json()["id"] == "a1"
        assert created.json()["time"] == "06:40:00"

        listed = client.get("/api/alarms")
        assert listed.status_code == 200
        assert [a["id"] for a in listed.json()] == ["a1"]

        updated_body = dict(_ALARM_BODY, enabled=False)
        updated = client.put("/api/alarms/a1", json=updated_body)
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False

        deleted = client.delete("/api/alarms/a1")
        assert deleted.status_code == 204

        listed_after = client.get("/api/alarms")
        assert listed_after.json() == []


async def test_delete_unknown_alarm_is_404() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.delete("/api/alarms/does-not-exist")
        assert response.status_code == 404


async def test_skip_next_sets_the_flag() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        client.post("/api/alarms", json=_ALARM_BODY)
        response = client.post("/api/alarms/a1/skip-next")
        assert response.status_code == 200
        assert response.json()["skip_next"] is True


async def test_alarms_persist_across_restart(tmp_path: Path) -> None:
    """tasks/07-api.md "Done when": full alarm CRUD over REST, persisted
    across restart."""
    db_path = tmp_path / "openrestore.db"
    ctx1, _clock1 = await build_test_context(db_path=db_path)
    app1 = build_test_app(ctx1)
    with TestClient(app1) as client1:
        response = client1.post("/api/alarms", json=_ALARM_BODY)
        assert response.status_code == 201

    # A brand-new AppContext against the same on-disk database, as if the
    # process had restarted.
    ctx2, _clock2 = await build_test_context(db_path=db_path)
    app2 = build_test_app(ctx2)
    with TestClient(app2) as client2:
        listed = client2.get("/api/alarms")
        assert [a["id"] for a in listed.json()] == ["a1"]


async def test_alarm_mutation_503s_when_clock_unsynced() -> None:
    ctx, _clock = await build_test_context(clock_synced=False)
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.post("/api/alarms", json=_ALARM_BODY)
        assert response.status_code == 503
        # GET /api/state must still work and report the degraded status.
        state = client.get("/api/state")
        assert state.status_code == 200
        assert state.json()["health"] == "degraded"


# --- idempotency -----------------------------------------------------------


async def test_idempotency_key_collapses_a_repeated_post() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        headers = {"Idempotency-Key": "retry-1"}
        first = client.post("/api/alarms", json=_ALARM_BODY, headers=headers)
        second = client.post("/api/alarms", json=_ALARM_BODY, headers=headers)
        assert first.status_code == second.status_code == 201
        assert first.json() == second.json()
        # only one alarm exists — the second POST never re-ran the action.
        listed = client.get("/api/alarms")
        assert len(listed.json()) == 1


async def test_idempotency_key_is_scoped_per_route() -> None:
    """The same `Idempotency-Key` value reused on two different routes must
    not collide — the cache key includes the request path."""
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        headers = {"Idempotency-Key": "shared-key"}
        alarm_response = client.post("/api/alarms", json=_ALARM_BODY, headers=headers)
        assert alarm_response.status_code == 201
        light_response = client.post(
            "/api/light/preset/nightlight", headers=headers
        )
        assert light_response.status_code == 200


# --- routines ----------------------------------------------------------


async def test_start_routine_conflict_when_already_running() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        first = client.post("/api/routines/winddown/start")
        assert first.status_code == 200
        again = client.post("/api/routines/winddown/start")
        assert again.status_code == 409


async def test_starting_a_different_routine_replaces_the_current_run() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        client.post("/api/routines/winddown/start")
        response = client.post(
            "/api/routines/weekday-wake/start",
            json={"trigger_at": "2024-06-03T07:00:00+00:00"},
        )
        assert response.status_code == 200
        state = client.get("/api/state")
        assert state.json()["routine"]["id"] == "weekday-wake"


async def test_start_unknown_routine_is_404() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.post("/api/routines/does-not-exist/start")
        assert response.status_code == 404


async def test_stop_current_routine() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        client.post("/api/routines/winddown/start")
        response = client.post("/api/routines/current/stop")
        assert response.status_code == 200
        state = client.get("/api/state")
        assert state.json()["routine"]["state"] == "IDLE"


async def test_list_and_get_routines() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        listed = client.get("/api/routines")
        assert listed.status_code == 200
        ids = {r["id"] for r in listed.json()}
        assert {"winddown", "weekday-wake"} <= ids

        detail = client.get("/api/routines/winddown")
        assert detail.status_code == 200
        assert detail.json()["id"] == "winddown"

        missing = client.get("/api/routines/does-not-exist")
        assert missing.status_code == 404


async def test_put_routine_validates_and_saves(tmp_path: Path) -> None:
    routines_dir = tmp_path / "routines"
    routines_dir.mkdir()
    ctx, _clock = await build_test_context(routines_dir=routines_dir)
    app = build_test_app(ctx)
    valid_yaml = """
version: 1
name: "Test"
id: test-routine
trigger: { type: time, at: "22:00" }
steps:
  - id: only
    duration: 5m
    light: { brightness: 0.5, cct: 2700 }
"""
    with TestClient(app) as client:
        response = client.put("/api/routines/test-routine", content=valid_yaml)
        assert response.status_code == 200
        assert response.json()["id"] == "test-routine"
        assert (routines_dir / "test-routine.yaml").exists()

        mismatched = client.put("/api/routines/other-id", content=valid_yaml)
        assert mismatched.status_code == 400

        invalid = client.put("/api/routines/test-routine", content="not: [valid, routine")
        assert invalid.status_code == 400


# --- snooze / dismiss --------------------------------------------------


async def test_snooze_without_active_alarm_is_409() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.post("/api/snooze")
        assert response.status_code == 409


async def test_dismiss_without_active_alarm_is_409() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.post("/api/dismiss")
        assert response.status_code == 409


async def test_snooze_during_alarm_state() -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    ctx, clock = await build_test_context(start=start)
    app = build_test_app(ctx)
    with TestClient(app) as client:
        client.post(
            "/api/routines/weekday-wake/start",
            json={"trigger_at": start.isoformat()},
        )
        response = client.post("/api/snooze")
        assert response.status_code == 200
        state = client.get("/api/state")
        assert state.json()["routine"]["state"] == "SNOOZE"


# --- light / audio -------------------------------------------------------


async def test_light_preset_and_manual_state() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        preset = client.post("/api/light/preset/nightlight")
        assert preset.status_code == 200
        state = client.get("/api/state")
        assert state.json()["light"]["on"] is True

        off = client.post("/api/light/preset/off")
        assert off.status_code == 200
        state = client.get("/api/state")
        assert state.json()["light"]["on"] is False

        manual = client.post("/api/light/state", json={"brightness": 0.4, "cct": 3200})
        assert manual.status_code == 200
        state = client.get("/api/state")
        assert state.json()["light"]["brightness"] == 0.4
        assert state.json()["light"]["cct"] == 3200


async def test_unknown_light_preset_is_rejected() -> None:
    """`{nightlight|reading|off}` is a closed set at the routing layer (a
    `Literal` path param), so an unknown value fails FastAPI's own request
    validation (422) before the handler ever runs — not a 404, since the
    *value* is invalid, not a missing resource."""
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.post("/api/light/preset/disco")
        assert response.status_code == 422


async def test_audio_play_and_stop() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        play = client.post(
            "/api/audio/play", json={"source": "file:rain.flac", "gain_db": -20}
        )
        assert play.status_code == 200
        state = client.get("/api/state")
        assert state.json()["audio"]["playing"] == "file:rain.flac"

        stop = client.post("/api/audio/stop")
        assert stop.status_code == 200
        state = client.get("/api/state")
        assert state.json()["audio"]["playing"] is None


async def test_audio_play_bad_source_is_400() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.post("/api/audio/play", json={"source": "not-a-valid-source"})
        assert response.status_code == 400


# --- devices & history ---------------------------------------------------


async def test_devices_endpoints() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        lights = client.get("/api/devices/lights")
        assert lights.status_code == 200
        assert lights.json()["configured"][0]["id"] == ctx.light.id

        discover = client.post("/api/devices/lights/discover")
        assert discover.status_code == 200
        assert discover.json()["discovered"] == []

        audio_devices = client.get("/api/devices/audio")
        assert audio_devices.status_code == 200

        test_tone = client.post("/api/devices/audio/test")
        assert test_tone.status_code == 200


async def test_history_filters_by_days(tmp_path: Path) -> None:
    start = datetime(2024, 6, 3, 6, 0, tzinfo=UTC)
    ctx, _clock = await build_test_context(start=start)
    await ctx.store.reserve_occurrence(
        "a1", "2024-06-03", outcome="fired", fired_at=start.isoformat()
    )
    await ctx.store.reserve_occurrence("a1", "2024-05-01", outcome="fired", fired_at=None)
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.get("/api/history", params={"days": 7})
        assert response.status_code == 200
        dates = {row["local_date"] for row in response.json()}
        assert dates == {"2024-06-03"}


# --- auth ------------------------------------------------------------------


async def test_bearer_token_required_when_configured() -> None:
    ctx, _clock = await build_test_context(bearer_token="secret")
    app = build_test_app(ctx)
    with TestClient(app) as client:
        unauthorized = client.get("/api/state")
        assert unauthorized.status_code == 401

        authorized = client.get(
            "/api/state", headers={"Authorization": "Bearer secret"}
        )
        assert authorized.status_code == 200


async def test_no_auth_required_by_default() -> None:
    ctx, _clock = await build_test_context()
    app = build_test_app(ctx)
    with TestClient(app) as client:
        response = client.get("/api/state")
        assert response.status_code == 200

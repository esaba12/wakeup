# Task 07 — API and state

**Read:** `docs/07-api-and-state.md`

**Hardware:** none

## Build

- `core/state.py` — the single authoritative state object with the exact shape in spec 07. Clients never compute derived values; `progress` and `in_s` are computed server-side.
- `api/rest.py` — FastAPI routes, the full endpoint list from spec 07. JSON only, ISO-8601 with offsets, `409` on conflicting routine starts, `503` when the clock is unsafe, idempotency keys on action POSTs.
- `api/ws.py` — `/api/events` upgrade. Full state on connect, then deltas at ~1 Hz during a ramp and event-driven otherwise. Client→server messages limited to the same actions as the REST verbs, so a physical puck and the web UI speak one protocol.
- Event log: every bus event written to the `events` table.
- Optional bearer token from config; no auth by default (LAN-only). Do not build an account system.
- Generate and commit the OpenAPI schema.

Skip the MQTT bridge for now.

## Done when

- [ ] Full alarm CRUD over REST, persisted across restart
- [ ] A WebSocket client sees a live 60×-compressed ramp update smoothly
- [ ] Reconnect resyncs from full state without a restart
- [ ] State deltas stay under 1 KB during a ramp
- [ ] `curl localhost:8080/api/state` with `--mock-light --mock-audio` returns a sane object on a laptop

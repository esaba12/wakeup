# 07 — API, State & Event Bus

## Purpose
One authoritative in-memory state object, one event bus, and a transport that lets the web UI and the physical puck be interchangeable clients.

## State shape

```jsonc
{
  "clock": { "now": "2026-09-02T22:14:03-04:00", "tz": "America/Detroit", "synced": true, "source": "ntp" },
  "routine": {
    "id": "winddown", "state": "WINDDOWN", "step": "dim",
    "started_at": "...", "trigger_at": null, "progress": 0.42
  },
  "light":  { "id": "lifx-d073d5...", "reachable": true, "on": true, "brightness": 0.11, "cct": 2100 },
  "audio":  { "output": "usb-cm108", "available": true, "playing": "file:rain.flac", "gain_db": -28 },
  "next_alarm": { "id": "a1", "at": "2026-09-03T06:40:00-04:00", "in_s": 30117, "skipped": false },
  "health": "ok"
}
```

Single source of truth in the daemon. Clients never compute derived state; they render what they're given. `progress` and `in_s` are recomputed server-side so a client with a wrong clock still displays correctly.

## Event bus
In-process async pub/sub. Producers: scheduler, routine engine, drivers. Consumers: WebSocket fan-out, MQTT bridge, SQLite event log, physical puck adapter.

Event types: `state.changed` (delta), `routine.transition`, `ramp.start`, `alarm.fired`, `alarm.missed`, `alarm.snoozed`, `preflight.failed`, `device.unreachable`, `device.recovered`, `clock.unsafe`.

Every event is written to the `events` table with a timestamp. That table is how you debug a 6am failure at 9am.

## REST

```
GET    /api/state
GET    /api/health                      # see spec 10
GET    /api/alarms
POST   /api/alarms                      # create
PUT    /api/alarms/{id}
DELETE /api/alarms/{id}
POST   /api/alarms/{id}/skip-next
GET    /api/routines
GET    /api/routines/{id}
PUT    /api/routines/{id}               # upload YAML/JSON, validated
POST   /api/routines/{id}/start
POST   /api/routines/current/stop
POST   /api/snooze
POST   /api/dismiss
POST   /api/light/preset/{nightlight|reading|off}
POST   /api/light/state                 # {brightness, cct} manual override
POST   /api/audio/play                  # {source, gain_db, sleep_timer}
POST   /api/audio/stop
GET    /api/devices/lights              # configured + discovered
POST   /api/devices/lights/discover
GET    /api/devices/audio               # enumerated outputs
POST   /api/devices/audio/test          # test tone
GET    /api/history?days=7              # occurrences + outcomes
```

Conventions: JSON only, ISO-8601 with offsets, `409` on conflicting routine starts, `503` when the clock is unsafe, idempotency keys on POSTs that fire actions.

## WebSocket
`GET /api/events` upgrades. Server sends the full state on connect, then deltas. ~1 Hz during a ramp, event-driven otherwise. Client→server messages are limited to the same actions as the REST verbs, so the puck and the UI use one protocol.

## Auth
LAN-only by default, no auth — matching how people actually run this. Optional `bearer_token` in config for anyone exposing it via Tailscale or a reverse proxy. Never invent an account system.

## MQTT bridge (optional, ~150 lines)
Publish Home Assistant discovery payloads so the device appears in HA as a light + a switch + sensors, and subscribe to command topics. Every HA user becomes a potential contributor for the cost of one module.

## Acceptance criteria
- [ ] OpenAPI schema generated and committed
- [ ] WebSocket client reconnects and resyncs without a full page reload
- [ ] State object is serializable and diffable; deltas are <1 KB during a ramp

# OpenRestore

An open-source bedside sleep clock: sunrise alarm, wind-down routines, and a sound machine, built from a smart bulb in a lamp the user already owns and a speaker they already own. Self-hosted, LAN-only, no cloud, no subscription. It replaces a $170 Hatch Restore plus a $60/year content subscription.

## The specs are the source of truth

`docs/` holds 16 numbered specs. `docs/00-overview.md` is the index — read it first, then read only the specs the current task names. Do not read all sixteen; most tasks need two or three.

If the code and a spec disagree, the spec wins. If a spec is wrong or ambiguous, say so and propose an edit to the spec rather than silently working around it.

## Stack

- **Python 3.11+**, asyncio, single process, single event loop
- **FastAPI** for REST + WebSocket, **SQLite** (WAL) for persistence
- **mpv** as a supervised child process for audio, controlled over a unix IPC socket
- **React + TypeScript + Vite** for the web UI, built to static assets and served by the daemon
- **pytest** with an injected clock; **ruff** and **mypy --strict** on `src/openrestore/core`

Hard constraint: no dependency that lacks a prebuilt arm64 wheel. The target host is a Raspberry Pi Zero 2 W with no compiler.

## Non-negotiable design rules

1. **Wall clock is truth.** Nothing sleeps until an event. Every timed component recomputes its position from `datetime.now(tz)` on every tick and on startup, so restarts, clock steps, and DST are non-events. A restart at minute 17 of a 30-minute sunrise resumes at minute 17.
2. **Drivers are swappable.** Light, audio output, and physical input are Protocols with at least two implementations each, one of which is a mock. No vendor concept — no `dimming`, no `hsbk`, no `mirek` — appears above the driver layer.
3. **The daemon must start on any host.** GPIO, I²C, and ALSA libraries are imported lazily inside their adapters, never at module scope. `--mock-light --mock-audio` runs the entire system on a laptop with no hardware.
4. **The alarm is the product.** Any change that could compromise alarm delivery needs a fallback path. See `docs/10-reliability.md`.
5. **Config over code.** Curves and routines are YAML files a user can edit and share, not Python constants.
6. **Never fire on a bad clock.** If neither NTP nor an RTC has provided a time this boot, refuse to fire alarms and report degraded health.

## Layout

```
src/openrestore/
  core/      scheduler, routines, curves, state, store, event bus
  drivers/   light/  audio/  input/     (each: base.py + implementations + mock)
  api/       rest.py, ws.py, mqtt.py
  cli.py
web/         React PWA
docs/        the specs
tasks/       ordered build briefs
tools/       sunrise-visualizer.html — standalone curve simulator, no hardware
routines/    shipped routine YAML
curves/      shipped curve YAML
tests/
```

## Conventions

- Type hints everywhere in `core/` and driver base classes; `mypy --strict` must pass on `core/`.
- Every timed component takes a `Clock` dependency. Tests inject a fake clock and never call `sleep()`.
- Drivers own their retries, sockets, and rate limits. Engines own curves and timing. Don't mix them.
- Raise domain exceptions from `core/errors.py`, not vendor library exceptions.
- Log through `structlog` with event names that match the bus events in `docs/07-api-and-state.md`.
- Commit messages: `task NN: <what>`.

## Working style

- One task per session. Read the task file, read the specs it names, then build.
- Write the tests the task's acceptance criteria describe. Tests that assert real behavior, not that a function was called.
- Don't build ahead. If a task doesn't mention the web UI, don't touch the web UI.
- Ask before adding a dependency that isn't already in `pyproject.toml`.

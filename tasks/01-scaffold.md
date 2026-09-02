# Task 01 — Scaffold

**Read:** `docs/00-overview.md`, `docs/01-hardware-platform.md`

**Hardware:** none

## Build

The empty skeleton of the project, so every later task has a place to put things.

- `pyproject.toml` — package `openrestore`, Python ≥3.11, entry point `openrestore = openrestore.cli:main`. Dependencies: `fastapi`, `uvicorn`, `pydantic`, `pyyaml`, `structlog`, `aiosqlite`. Dev extras: `pytest`, `pytest-asyncio`, `ruff`, `mypy`.
- The directory layout in `CLAUDE.md`, with `__init__.py` files and empty module stubs.
- `core/clock.py` — a `Clock` Protocol with `now() -> datetime` and `sleep(s)`, a `SystemClock`, and a `FakeClock` that advances only when a test tells it to. Everything timed in this project depends on this.
- `core/errors.py` — `DeviceUnreachable`, `ConfigError`, `UnsafeClock`.
- `core/events.py` — an async pub/sub bus: `publish(event)`, `subscribe(handler)`. Event types per `docs/07-api-and-state.md`.
- `cli.py` — `openrestore serve` (stub that starts and logs), `openrestore --version`. Accepts `--mock-light` and `--mock-audio` flags, stored on a config object for now.
- `tests/conftest.py` with a `fake_clock` fixture.
- `.github/workflows/ci.yml` — ruff, mypy on `core/`, pytest.
- `.gitignore`, `README.md` (short: what it is, link to `docs/00-overview.md`).

## Done when

- [ ] `pip install -e ".[dev]"` succeeds in a clean venv
- [ ] `openrestore serve` starts, logs a line, exits cleanly on Ctrl-C
- [ ] `ruff check`, `mypy src/openrestore/core`, and `pytest` all pass with zero findings
- [ ] `FakeClock` has a test proving time does not advance on its own

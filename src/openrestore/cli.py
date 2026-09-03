"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import signal
from dataclasses import dataclass
from pathlib import Path

import structlog

from openrestore import __version__

logger = structlog.get_logger()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ROUTINES_DIR = _REPO_ROOT / "routines"


@dataclass(slots=True)
class Config:
    mock_light: bool = False
    mock_audio: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    db: str = "openrestore.db"
    tz: str = "UTC"
    bearer_token: str | None = None
    routines_dir: Path = _DEFAULT_ROUTINES_DIR


async def _serve(config: Config) -> None:
    logger.info(
        "daemon.starting",
        mock_light=config.mock_light,
        mock_audio=config.mock_audio,
        host=config.host,
        port=config.port,
    )

    # Imported lazily, inside the function that actually needs them, per
    # docs/00-overview.md rule 3 ("the daemon must start on any host") —
    # `--version`/`--help` must never require fastapi/uvicorn to import
    # cleanly, let alone a driver's hardware libraries.
    import uvicorn

    from openrestore.app import build_context, create_app
    from openrestore.core.clock import SystemClock

    if not (config.mock_light and config.mock_audio):
        # No real light or audio driver is wired into the CLI yet — the
        # LIFX driver is task 09's. Refusing loudly here beats silently
        # doing nothing.
        raise SystemExit(
            "openrestore serve currently requires both --mock-light and "
            "--mock-audio; no real driver is wired into the CLI yet "
            "(the LIFX driver is a later task)"
        )

    from openrestore.drivers.audio.mock import MockAudioOutput
    from openrestore.drivers.light.mock import MockLight

    clock = SystemClock()
    light = MockLight(clock)
    audio = MockAudioOutput(clock)

    ctx = await build_context(
        clock=clock,
        light=light,
        audio=audio,
        db_path=config.db,
        routines_dir=config.routines_dir,
        tz=config.tz,
        bearer_token=config.bearer_token,
        # No NTP/RTC watcher exists yet (docs/10-reliability.md, a later
        # task) to call `mark_clock_synced()` at the right moment, so a
        # freshly-booted SystemClock is trusted by default here rather than
        # refusing to ever fire alarms on every laptop/dev run.
        clock_synced=True,
    )
    app = create_app(ctx)

    server_config = uvicorn.Config(app, host=config.host, port=config.port, log_level="warning")
    server = uvicorn.Server(server_config)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    server_task = asyncio.ensure_future(server.serve())
    await stop.wait()
    server.should_exit = True
    await server_task
    logger.info("daemon.stopped")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openrestore")
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the openrestore daemon")
    serve_parser.add_argument("--mock-light", action="store_true")
    serve_parser.add_argument("--mock-audio", action="store_true")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.add_argument("--db", default="openrestore.db")
    serve_parser.add_argument("--tz", default="UTC")
    serve_parser.add_argument("--bearer-token", default=None)
    serve_parser.add_argument(
        "--routines-dir", type=Path, default=_DEFAULT_ROUTINES_DIR
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        config = Config(
            mock_light=args.mock_light,
            mock_audio=args.mock_audio,
            host=args.host,
            port=args.port,
            db=args.db,
            tz=args.tz,
            bearer_token=args.bearer_token,
            routines_dir=args.routines_dir,
        )
        asyncio.run(_serve(config))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

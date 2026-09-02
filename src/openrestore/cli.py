"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import signal
from dataclasses import dataclass

import structlog

from openrestore import __version__

logger = structlog.get_logger()


@dataclass(slots=True)
class Config:
    mock_light: bool = False
    mock_audio: bool = False


async def _serve(config: Config) -> None:
    logger.info("daemon.starting", mock_light=config.mock_light, mock_audio=config.mock_audio)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    logger.info("daemon.stopped")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openrestore")
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the openrestore daemon")
    serve_parser.add_argument("--mock-light", action="store_true")
    serve_parser.add_argument("--mock-audio", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        config = Config(mock_light=args.mock_light, mock_audio=args.mock_audio)
        asyncio.run(_serve(config))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

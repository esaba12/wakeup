from __future__ import annotations

import pytest

from openrestore import __version__
from openrestore.cli import _build_parser


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    assert __version__ in capsys.readouterr().out


def test_serve_parses_mock_flags() -> None:
    parser = _build_parser()
    args = parser.parse_args(["serve", "--mock-light", "--mock-audio"])
    assert args.command == "serve"
    assert args.mock_light is True
    assert args.mock_audio is True

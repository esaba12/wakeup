"""tasks/06-audio.md 'Done when': 'CI fails if any manifest entry lacks a
source URL and a CC0-or-generated license'. `tools/generate_credits.py` is a
standalone script (not part of the `openrestore` package), so it's imported
here by file path rather than as a normal module."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "sounds" / "manifest.yaml"


def _load_generate_credits() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_credits", REPO_ROOT / "tools" / "generate_credits.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gc = _load_generate_credits()


def test_manifest_is_valid_and_nonempty() -> None:
    entries = gc.load_manifest()
    assert len(entries) >= 4  # white, pink, brown, fan at minimum
    gc.validate_manifest(entries)  # raises on any bad entry


def test_shipped_generated_tracks_present() -> None:
    entries = {e["id"]: e for e in gc.load_manifest()}
    for expected in ("white", "pink", "brown", "fan"):
        assert expected in entries, f"manifest is missing {expected!r}"
        assert entries[expected]["license"] == "none"
        assert "generated" in entries[expected]["source"].lower()


def test_generated_entry_without_generated_source_description_fails() -> None:
    with pytest.raises(gc.ManifestError):
        gc.validate_entry(
            {
                "id": "bad",
                "title": "Bad",
                "file": "bad.flac",
                "category": "noise",
                "source": "who knows",
                "license": "none",
            }
        )


def test_cc0_entry_without_url_fails() -> None:
    with pytest.raises(gc.ManifestError):
        gc.validate_entry(
            {
                "id": "rain",
                "title": "Rain",
                "file": "rain.flac",
                "category": "nature",
                "source": "some guy's website",
                "license": "CC0",
            }
        )


def test_cc0_entry_with_source_url_passes() -> None:
    gc.validate_entry(
        {
            "id": "rain",
            "title": "Rain",
            "file": "rain.flac",
            "category": "nature",
            "source": "https://freesound.org/s/123456/",
            "license": "CC0",
        }
    )


def test_non_cc0_license_fails() -> None:
    with pytest.raises(gc.ManifestError):
        gc.validate_entry(
            {
                "id": "rain",
                "title": "Rain",
                "file": "rain.flac",
                "category": "nature",
                "source": "https://freesound.org/s/123456/",
                "license": "CC-BY",
            }
        )


def test_entry_missing_a_required_field_fails() -> None:
    with pytest.raises(gc.ManifestError):
        gc.validate_entry(
            {
                "id": "white",
                "title": "White noise",
                "file": "white.flac",
                "category": "noise",
                "source": "generated (ffmpeg anoisesrc)",
                # no license
            }
        )


def test_duplicate_ids_fail() -> None:
    entry = {
        "id": "white",
        "title": "White noise",
        "file": "white.flac",
        "category": "noise",
        "source": "generated (ffmpeg anoisesrc)",
        "license": "none",
    }
    with pytest.raises(gc.ManifestError):
        gc.validate_manifest([entry, dict(entry)])


def test_render_credits_lists_every_entry() -> None:
    entries = gc.load_manifest()
    credits = gc.render_credits(entries)
    for entry in entries:
        assert entry["title"] in credits
        assert entry["file"] in credits
        assert entry["license"] in credits


def test_manifest_is_a_yaml_list_of_mappings() -> None:
    raw = yaml.safe_load(MANIFEST_PATH.read_text())
    assert isinstance(raw, list)
    for entry in raw:
        assert isinstance(entry, dict)


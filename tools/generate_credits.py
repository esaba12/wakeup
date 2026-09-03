#!/usr/bin/env python3
"""Generate sounds/CREDITS.md from sounds/manifest.yaml. See
docs/15-sound-library.md "Manifest": "sounds/CREDITS.md is generated from the
manifest at build time. Every file must have a source URL and a license, or
CI fails."

Standalone script (not part of the `openrestore` package, like
tools/sunrise-visualizer.html) so it has no runtime dependency on the app
being installed. Run directly, or via `make credits` / `make sounds`.

The same validation this script enforces is asserted by
tests/test_sounds.py, so a manifest edit that breaks a license/source rule
fails `pytest` in CI even without ffmpeg or mpv installed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "sounds" / "manifest.yaml"
CREDITS_PATH = REPO_ROOT / "sounds" / "CREDITS.md"

_GENERATED_LICENSE = "none"
_ACCEPTABLE_LICENSES = {"cc0", "public domain"}


class ManifestError(ValueError):
    """A manifest entry fails spec 15's "every file must have a source URL
    and a license" rule."""


def load_manifest(path: Path = MANIFEST_PATH) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, list) or not raw:
        raise ManifestError(f"{path}: expected a non-empty list of sound entries")
    return raw


def validate_entry(entry: dict[str, Any]) -> None:
    entry_id = entry.get("id", "<no id>")
    for key in ("id", "title", "file", "category", "source", "license"):
        if not entry.get(key):
            raise ManifestError(f"{entry_id}: missing required field {key!r}")

    license_ = str(entry["license"])
    source = str(entry["source"])

    if license_.lower() == _GENERATED_LICENSE:
        # Generated assets (ffmpeg anoisesrc, ...): no source URL required,
        # since nobody owns a noise file you generated -- but the source
        # description must actually say so, not just claim "none" for a
        # file that was really downloaded from somewhere.
        if "generated" not in source.lower():
            raise ManifestError(
                f"{entry_id}: license 'none' requires a source description "
                f"that says how it was generated, got {source!r}"
            )
        return

    if license_.lower() not in _ACCEPTABLE_LICENSES:
        raise ManifestError(
            f"{entry_id}: license must be CC0, public domain, or 'none' "
            f"(generated), got {license_!r}"
        )
    if not (source.startswith("http://") or source.startswith("https://")):
        raise ManifestError(
            f"{entry_id}: non-generated entries need a real source URL, got {source!r}"
        )


def validate_manifest(entries: list[dict[str, Any]]) -> None:
    seen_ids: set[str] = set()
    for entry in entries:
        validate_entry(entry)
        entry_id = entry["id"]
        if entry_id in seen_ids:
            raise ManifestError(f"{entry_id}: duplicate id in manifest")
        seen_ids.add(entry_id)


def render_credits(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# Sound Library Credits",
        "",
        "Generated from `sounds/manifest.yaml` by `tools/generate_credits.py`. "
        "Do not edit by hand -- edit the manifest and regenerate (`make credits`).",
        "",
        "| Sound | File | Category | Source | Author | License |",
        "|---|---|---|---|---|---|",
    ]
    for entry in entries:
        author = entry.get("author", "")
        lines.append(
            f"| {entry['title']} | `{entry['file']}` | {entry['category']} "
            f"| {entry['source']} | {author} | {entry['license']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    try:
        entries = load_manifest()
        validate_manifest(entries)
    except ManifestError as exc:
        print(f"sounds/manifest.yaml is invalid: {exc}", file=sys.stderr)
        return 1
    CREDITS_PATH.write_text(render_credits(entries))
    print(f"wrote {CREDITS_PATH} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

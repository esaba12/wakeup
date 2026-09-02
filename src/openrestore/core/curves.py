"""Sunrise brightness/CCT curve definitions and interpolation. Pure functions:
no I/O beyond `load_curve`, no clock. See docs/03-sunrise-engine.md.

Scope note: this module owns the brightness models and CCT keyframe
interpolation described in tasks/02-light-interface.md. Combining a curve's
brightness and CCT/RGB into a `LightState` for a running ramp (spec 03's
`curve.color_at(t, b)`) is left to core/sunrise.py (task 03) — the spec does
not define how an isolated `rgb` keyframe (e.g. the t=0 ember amber) should
blend with the surrounding CCT keyframes over a step interval, and guessing
that semantics here risks a design task 03 would just redo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from openrestore.core.errors import ConfigError

_ALLOWED_TOP_KEYS = {"name", "brightness", "keyframes"}
_ALLOWED_KEYFRAME_KEYS = {"t", "cct", "rgb"}


def cie_luminance(lstar: float) -> float:
    """CIE L* (0..100 perceived lightness) -> relative luminance (0..1)."""
    if lstar > 8.0:
        return ((lstar + 16.0) / 116.0) ** 3
    return lstar / 903.3


def _clamp01(t: float) -> float:
    return max(0.0, min(1.0, t))


def brightness_model(name: str) -> Callable[[float], float]:
    """Resolve a brightness model name to a pure `t -> luminance` function."""
    if name == "cie":
        return lambda t: cie_luminance(100.0 * _clamp01(t))
    if name == "linear":
        return lambda t: _clamp01(t)
    if name.startswith("gamma:"):
        raw_exponent = name.removeprefix("gamma:")
        try:
            exponent = float(raw_exponent)
        except ValueError as exc:
            raise ConfigError(f"invalid gamma exponent {raw_exponent!r} in {name!r}") from exc
        return lambda t: _clamp01(t) ** exponent
    raise ConfigError(f"unknown brightness model {name!r}")


@dataclass(frozen=True, slots=True)
class Keyframe:
    t: float
    cct: int | None = None
    rgb: tuple[int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class Curve:
    name: str
    brightness_model_name: str
    keyframes: tuple[Keyframe, ...]

    def __post_init__(self) -> None:
        # Resolve eagerly so a bad model name fails at load time, not first use.
        brightness_model(self.brightness_model_name)
        cct_keyframes = [k for k in self.keyframes if k.cct is not None]
        if not cct_keyframes:
            raise ConfigError(f"curve {self.name!r} has no keyframe with a cct")
        ts = [k.t for k in cct_keyframes]
        if ts != sorted(ts):
            raise ConfigError(f"curve {self.name!r} keyframes must be sorted by ascending t")
        if len(set(ts)) != len(ts):
            raise ConfigError(f"curve {self.name!r} has duplicate keyframe t values")

    def brightness(self, t: float) -> float:
        """Perceptual brightness (0..1) at position `t` (0..1) per this
        curve's brightness model. Independent of the CCT/RGB keyframes."""
        return brightness_model(self.brightness_model_name)(t)

    def cct_at(self, t: float) -> int:
        """Interpolated color temperature (kelvin) at position `t` (0..1).
        Exact at every keyframe that defines a cct, monotonic between them,
        held constant before the first and after the last."""
        cct_keyframes = [k for k in self.keyframes if k.cct is not None]
        t = _clamp01(t)
        if t <= cct_keyframes[0].t:
            assert cct_keyframes[0].cct is not None
            return cct_keyframes[0].cct
        if t >= cct_keyframes[-1].t:
            assert cct_keyframes[-1].cct is not None
            return cct_keyframes[-1].cct
        for lo, hi in zip(cct_keyframes, cct_keyframes[1:], strict=False):
            if lo.t <= t <= hi.t:
                assert lo.cct is not None and hi.cct is not None
                span = hi.t - lo.t
                fraction = (t - lo.t) / span if span > 0 else 0.0
                return round(lo.cct + (hi.cct - lo.cct) * fraction)
        raise AssertionError("unreachable: t is within [first.t, last.t]")


def _node_line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


def _check_mapping_keys(node: yaml.Node, allowed: set[str], path: Path) -> None:
    if not isinstance(node, yaml.MappingNode):
        raise ConfigError(f"{path}:{_node_line(node)}: expected a mapping")
    for key_node, _value_node in node.value:
        key = key_node.value
        if key not in allowed:
            raise ConfigError(
                f"{path}:{_node_line(key_node)}: unknown key {key!r} "
                f"(expected one of {sorted(allowed)})"
            )


def _validate_curve_yaml_shape(text: str, path: Path) -> None:
    """Walk the raw YAML node tree (not the constructed data) so an unknown
    key can be reported with its source line, per tasks/02-light-interface.md."""
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if root is None:
        raise ConfigError(f"{path}: empty curve file")
    _check_mapping_keys(root, _ALLOWED_TOP_KEYS, path)
    for key_node, value_node in root.value:
        if key_node.value != "keyframes":
            continue
        if not isinstance(value_node, yaml.SequenceNode):
            raise ConfigError(f"{path}:{_node_line(value_node)}: 'keyframes' must be a list")
        for item_node in value_node.value:
            _check_mapping_keys(item_node, _ALLOWED_KEYFRAME_KEYS, path)


def _parse_keyframe(raw: dict[str, Any], path: Path) -> Keyframe:
    if "t" not in raw:
        raise ConfigError(f"{path}: keyframe missing required key 't': {raw!r}")
    rgb = raw.get("rgb")
    return Keyframe(
        t=float(raw["t"]),
        cct=int(raw["cct"]) if "cct" in raw else None,
        rgb=tuple(rgb) if rgb is not None else None,
    )


def load_curve(path: str | Path) -> Curve:
    """Load and validate a curve YAML file. An unknown top-level or keyframe
    key is a hard `ConfigError` naming the offending file and line."""
    path = Path(path)
    text = path.read_text()
    _validate_curve_yaml_shape(text, path)

    data = yaml.safe_load(text)
    if "name" not in data:
        raise ConfigError(f"{path}: missing required key 'name'")
    if "brightness" not in data:
        raise ConfigError(f"{path}: missing required key 'brightness'")
    if "keyframes" not in data or not data["keyframes"]:
        raise ConfigError(f"{path}: missing or empty 'keyframes'")

    keyframes = tuple(_parse_keyframe(raw, path) for raw in data["keyframes"])
    return Curve(
        name=data["name"],
        brightness_model_name=data["brightness"],
        keyframes=keyframes,
    )

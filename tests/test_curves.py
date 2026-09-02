from __future__ import annotations

from pathlib import Path

import pytest

from openrestore.core.curves import Curve, Keyframe, cie_luminance, load_curve
from openrestore.core.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
CURVES_DIR = REPO_ROOT / "curves"


# --- brightness models -------------------------------------------------


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (0.00, 0.0000),
        (0.25, 0.0442),
        (0.50, 0.1842),
        (0.75, 0.4828),
        (1.00, 1.0000),
    ],
)
def test_cie_model_matches_reference_to_four_decimal_places(t: float, expected: float) -> None:
    curve = Curve(name="c", brightness_model_name="cie", keyframes=(Keyframe(t=0.0, cct=2000),))
    assert round(curve.brightness(t), 4) == expected


def test_cie_luminance_formula_matches_spec_piecewise_definition() -> None:
    # spec 03: lstar <= 8.0 uses the linear branch, not the cube-root branch.
    assert cie_luminance(4.0) == pytest.approx(4.0 / 903.3)
    assert cie_luminance(8.0) == pytest.approx(8.0 / 903.3)


def test_linear_model_is_identity() -> None:
    curve = Curve(name="c", brightness_model_name="linear", keyframes=(Keyframe(t=0.0, cct=2000),))
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert curve.brightness(t) == pytest.approx(t)


def test_gamma_model_applies_exponent() -> None:
    curve = Curve(
        name="c", brightness_model_name="gamma:2.2", keyframes=(Keyframe(t=0.0, cct=2000),)
    )
    assert curve.brightness(0.5) == pytest.approx(0.5**2.2)
    assert curve.brightness(1.0) == pytest.approx(1.0)


def test_unknown_brightness_model_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        Curve(name="c", brightness_model_name="nonsense", keyframes=(Keyframe(t=0.0, cct=2000),))


# --- CCT interpolation ---------------------------------------------------


def _sunrise_classic() -> Curve:
    return load_curve(CURVES_DIR / "sunrise-classic.yaml")


def test_cct_interpolation_hits_every_keyframe_exactly() -> None:
    curve = _sunrise_classic()
    assert curve.cct_at(0.00) == 1600
    assert curve.cct_at(0.15) == 1800
    assert curve.cct_at(0.50) == 2400
    assert curve.cct_at(0.85) == 3500
    assert curve.cct_at(1.00) == 4500


def test_cct_interpolation_is_monotonic_between_keyframes() -> None:
    curve = _sunrise_classic()
    samples = [curve.cct_at(t / 200) for t in range(201)]
    assert samples == sorted(samples)


def test_cct_interpolation_holds_before_first_and_after_last_keyframe() -> None:
    curve = Curve(
        name="c",
        brightness_model_name="linear",
        keyframes=(Keyframe(t=0.2, cct=2000), Keyframe(t=0.8, cct=3000)),
    )
    assert curve.cct_at(0.0) == 2000
    assert curve.cct_at(1.0) == 3000


# --- YAML loading and validation -----------------------------------------


def test_shipped_curves_load(tmp_path: Path) -> None:
    for name in ("sunrise-classic.yaml", "reverse-sunrise.yaml"):
        curve = load_curve(CURVES_DIR / name)
        assert curve.name == name.removesuffix(".yaml")


def test_unknown_top_level_key_is_a_hard_error_with_line(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\n"
        "brightness: cie\n"
        "flavor: strawberry\n"
        "keyframes:\n"
        "  - { t: 0.0, cct: 2000 }\n"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_curve(bad)
    message = str(excinfo.value)
    assert "flavor" in message
    assert f"{bad}:3" in message


def test_unknown_keyframe_key_is_a_hard_error_with_line(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\n"
        "brightness: cie\n"
        "keyframes:\n"
        "  - { t: 0.0, cct: 2000 }\n"
        "  - { t: 1.0, cct: 3000, wattage: 9 }\n"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_curve(bad)
    message = str(excinfo.value)
    assert "wattage" in message
    assert f"{bad}:5" in message


def test_missing_required_key_is_a_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("brightness: cie\nkeyframes:\n  - { t: 0.0, cct: 2000 }\n")
    with pytest.raises(ConfigError):
        load_curve(bad)


def test_out_of_order_keyframes_is_a_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\n"
        "brightness: cie\n"
        "keyframes:\n"
        "  - { t: 0.5, cct: 3000 }\n"
        "  - { t: 0.2, cct: 2000 }\n"
    )
    with pytest.raises(ConfigError):
        load_curve(bad)

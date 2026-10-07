"""Tests for detect_primer.py — shadow geometry primer detection."""
import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2
import numpy as np
from detect_primer import detect_primer_shadow


_DIE_CENTER = (200, 200)
_DIE_OUTER_R = 150
_DIE_INNER_R = 145


def _make_die_image(with_shadow=True):
    """Return a 400x400 grayscale synthetic die cavity image."""
    img = np.ones((400, 400), dtype=np.uint8) * 180
    cv2.circle(img, _DIE_CENTER, _DIE_OUTER_R, 30, 8)
    cv2.circle(img, _DIE_CENTER, _DIE_INNER_R, 160, 8)
    if with_shadow:
        cv2.ellipse(img, (190, 195), (110, 80), 0, 0, 300, 30, -1)
    return img


def test_empty_frame_returns_error():
    present, debug = detect_primer_shadow(np.array([]))
    assert not present
    assert "error" in debug


def test_none_frame_returns_error():
    present, debug = detect_primer_shadow(None)
    assert not present
    assert "error" in debug


def test_solid_bright_frame_no_die():
    img = np.ones((400, 400), dtype=np.uint8) * 200
    present, debug = detect_primer_shadow(img)
    assert not present
    assert debug.get("die_contour") == "not found"


def test_no_shadow_returns_absent():
    img = _make_die_image(with_shadow=False)
    present, debug = detect_primer_shadow(img)
    assert not present
    assert "die_area" in debug
    assert debug.get("shadow_contour") == "not found"


def test_shadow_present_returns_true():
    img = _make_die_image(with_shadow=True)
    present, debug = detect_primer_shadow(img)
    assert present
    assert "area_ratio" in debug
    assert 0.15 < debug["area_ratio"] < 0.85


def test_color_frame_handled():
    img_gray = _make_die_image(with_shadow=True)
    img_color = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
    present, debug = detect_primer_shadow(img_color)
    assert present


def test_default_threshold_works():
    img = _make_die_image(with_shadow=True)
    present, _ = detect_primer_shadow(img, threshold=0.3)
    assert present


def test_strict_threshold_can_reject():
    img = _make_die_image(with_shadow=True)
    present, debug = detect_primer_shadow(img, min_area_ratio=0.9)
    assert not present
    assert debug["area_ratio"] < 0.9


def test_lenient_threshold_accepts():
    img = _make_die_image(with_shadow=True)
    present, _ = detect_primer_shadow(img, min_area_ratio=0.01)
    assert present


def test_debug_info_structure():
    img = _make_die_image(with_shadow=True)
    _, debug = detect_primer_shadow(img)
    expected = {
        "die_contour_area", "shadow_contour_area", "area_ratio",
        "expected_min", "expected_max", "threshold",
        "num_inner_contours",
    }
    assert expected.issubset(set(debug.keys()))


def test_cli_with_image():
    """Run detect_primer.py as __main__ with a synthetic image."""
    img = _make_die_image(with_shadow=True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        cv2.imwrite(f.name, img)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "detect_primer", tmp],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent / "src"),
        )
        assert result.returncode == 0
        assert "Primer present" in result.stdout
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_tiny_frame_doesnt_crash():
    img = np.ones((10, 10), dtype=np.uint8) * 180
    present, debug = detect_primer_shadow(img)
    assert isinstance(present, bool)
    assert isinstance(debug, dict)

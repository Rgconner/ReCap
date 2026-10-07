"""Tests for detector_v3.py — the TemplateMatcher used by the live trigger
pipeline (main.py). This is the detector actually wired to
hardware; detect_primer.py is a separate, superseded approach with its own
tests (test_detect_primer.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2
import numpy as np
import pytest
from detector_v3 import TemplateMatcher
from roi_config import ROIS, ROLE_NECK_EXPAND, ROLE_PRIMER_1, ROLE_PRIMER_2, ROLE_SWAGE

FRAME_SHAPE = (450, 700)  # (h, w) — big enough to hold every ROI + search padding

# Fixed background so every synthetic frame shares identical "empty" texture;
# without per-pixel noise, a flat template matches ANY flat region equally
# well and the present/absent comparison becomes meaningless.
_rng = np.random.default_rng(seed=42)
_BACKGROUND = (100 + _rng.integers(-15, 15, size=(*FRAME_SHAPE, 3))).astype(np.uint8)


def _draw_marker(frame, roi_key):
    """Draws the 'present' marker pattern into an ROI in place."""
    x1, y1, x2, y2 = ROIS[roi_key]
    cv2.rectangle(frame, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (230, 230, 230), -1)
    cv2.rectangle(frame, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (10, 10, 10), 2)


def _make_frame(present_keys):
    """A background frame with the 'present' marker drawn into each ROI in
    present_keys; every other ROI is left as plain background (= absent)."""
    frame = _BACKGROUND.copy()
    for roi_key in present_keys:
        _draw_marker(frame, roi_key)
    return frame


def _make_template_dir(tmp_dir):
    """Writes present/absent templates for every ROI, cropped from the same
    fixed background used by _make_frame so they're realistic matches."""
    present_source = _make_frame(list(ROIS.keys()))
    for roi_key, (x1, y1, x2, y2) in ROIS.items():
        absent = _BACKGROUND[y1:y2, x1:x2]
        cv2.imwrite(str(tmp_dir / f"{roi_key}_absent.png"), absent)

        present = present_source[y1:y2, x1:x2]
        cv2.imwrite(str(tmp_dir / f"{roi_key}_present.png"), present)


def _make_matcher(tmp_path):
    _make_template_dir(tmp_path)
    return TemplateMatcher(str(tmp_path))


# --- detect_state ---

def test_loads_all_templates(tmp_path):
    matcher = _make_matcher(tmp_path)
    assert len(matcher.templates) == 8


def test_detects_present(tmp_path):
    matcher = _make_matcher(tmp_path)
    frame = _make_frame(present_keys=[ROLE_PRIMER_1])
    has_primer, present_score, absent_score = matcher.detect_state(
        frame, ROLE_PRIMER_1, f"{ROLE_PRIMER_1}_present", f"{ROLE_PRIMER_1}_absent"
    )
    assert has_primer
    assert present_score > absent_score


def test_detects_absent(tmp_path):
    matcher = _make_matcher(tmp_path)
    frame = _make_frame(present_keys=[])
    has_primer, present_score, absent_score = matcher.detect_state(
        frame, ROLE_PRIMER_1, f"{ROLE_PRIMER_1}_present", f"{ROLE_PRIMER_1}_absent"
    )
    assert not has_primer
    assert absent_score > present_score


# --- analyze_frame ---

def test_ok_condition(tmp_path):
    matcher = _make_matcher(tmp_path)
    # Primer present at ROLE_PRIMER_2, nothing else — nominal running state.
    frame = _make_frame(present_keys=[ROLE_PRIMER_2])
    results = matcher.analyze_frame(frame)
    assert results["condition"] == "OK"
    assert results["action"] == "NONE"


def test_no_primer_condition(tmp_path):
    matcher = _make_matcher(tmp_path)
    frame = _make_frame(present_keys=[])
    results = matcher.analyze_frame(frame)
    assert results["condition"] == "NO_PRIMER"
    assert results["action"] == "NONE"


def test_misload_condition(tmp_path):
    matcher = _make_matcher(tmp_path)
    # Primer already seated at ROLE_PRIMER_1 AND brass already advanced to
    # ROLE_NECK_EXPAND means a primer is about to be pressed into loaded brass.
    frame = _make_frame(present_keys=[ROLE_PRIMER_1, ROLE_NECK_EXPAND])
    results = matcher.analyze_frame(frame)
    assert results["condition"] == "MISLOAD"
    assert results["action"] == "STOP"


def test_about_to_fail_condition(tmp_path):
    matcher = _make_matcher(tmp_path)
    # Brass at ROLE_SWAGE but ROLE_PRIMER_2 has no primer to feed it next.
    frame = _make_frame(present_keys=[ROLE_SWAGE])
    results = matcher.analyze_frame(frame)
    assert results["condition"] == "ABOUT_TO_FAIL"
    assert results["action"] == "STOP"


def test_misload_and_about_to_fail_condition(tmp_path):
    matcher = _make_matcher(tmp_path)
    frame = _make_frame(present_keys=[ROLE_PRIMER_1, ROLE_NECK_EXPAND, ROLE_SWAGE])
    results = matcher.analyze_frame(frame)
    assert results["condition"] == "MISLOAD_AND_ABOUT_TO_FAIL"
    assert results["action"] == "STOP"


# --- config-driven construction (rois=/template_names=, for main.py) ---

def test_default_construction_uses_roi_config(tmp_path):
    matcher = _make_matcher(tmp_path)
    assert matcher.rois == ROIS


def test_custom_rois_and_template_names_override_defaults(tmp_path):
    custom_rois = {"stationA": (10, 10, 60, 60)}
    x1, y1, x2, y2 = custom_rois["stationA"]

    absent = _BACKGROUND[y1:y2, x1:x2]
    cv2.imwrite(str(tmp_path / "stationA_absent.png"), absent)

    present_frame = _BACKGROUND.copy()
    cv2.rectangle(present_frame, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (230, 230, 230), -1)
    cv2.rectangle(present_frame, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (10, 10, 10), 2)
    cv2.imwrite(str(tmp_path / "stationA_present.png"), present_frame[y1:y2, x1:x2])

    matcher = TemplateMatcher(
        str(tmp_path), rois=custom_rois, template_names=["stationA_present", "stationA_absent"]
    )

    assert matcher.rois == custom_rois
    assert set(matcher.templates.keys()) == {"stationA_present", "stationA_absent"}

    frame = present_frame.copy()
    has_marker, present_score, absent_score = matcher.detect_state(
        frame, "stationA", "stationA_present", "stationA_absent"
    )
    assert has_marker
    assert present_score > absent_score


# --- validate_ready() / analyze_frame() guard against mismatched config ---

def test_validate_ready_passes_with_default_rois(tmp_path):
    matcher = _make_matcher(tmp_path)
    matcher.validate_ready()  # should not raise


def test_analyze_frame_raises_clear_error_on_missing_roi(tmp_path):
    _make_template_dir(tmp_path)
    custom_rois = {"stationA": (10, 10, 60, 60)}
    matcher = TemplateMatcher(
        str(tmp_path), rois=custom_rois, template_names=["stationA_present", "stationA_absent"]
    )
    with pytest.raises(ValueError, match=ROLE_SWAGE):
        matcher.analyze_frame(_make_frame([]))


def test_analyze_frame_raises_clear_error_on_missing_template(tmp_path):
    # ROIs match the required set, but templates for one of them were
    # never captured — e.g. setup app config saved before all templates
    # were extracted.
    _make_template_dir(tmp_path)
    (tmp_path / f"{ROLE_PRIMER_2}_present.png").unlink()
    matcher = TemplateMatcher(str(tmp_path))
    with pytest.raises(ValueError, match=f"{ROLE_PRIMER_2}_present"):
        matcher.analyze_frame(_make_frame([]))

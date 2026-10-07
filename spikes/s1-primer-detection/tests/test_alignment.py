"""Tests for alignment.py's AlignmentChecker."""
import sys
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alignment import AlignmentChecker


def _make_frame_with_markers(positions):
    """A black frame with a filled yellow circle at each (x, y)."""
    frame = np.zeros((500, 700, 3), dtype=np.uint8)
    for (cx, cy) in positions:
        cv2.circle(frame, (cx, cy), 15, (0, 255, 255), -1)  # BGR yellow
    return frame


# --- find_markers: real cv2 image processing, order not asserted since
# cv2.findContours' discovery order for same-area contours isn't guaranteed. ---

def test_find_markers_detects_two_as_a_set():
    frame = _make_frame_with_markers([(100, 100), (400, 300)])
    checker = AlignmentChecker(expected_markers=[(0, 0), (0, 0)], threshold=50)
    markers = checker.find_markers(frame)
    assert set(markers) == {(100, 100), (400, 300)}


def test_find_markers_ignores_small_noise():
    frame = _make_frame_with_markers([(100, 100), (400, 300)])
    cv2.circle(frame, (200, 200), 3, (0, 255, 255), -1)  # area well under the 100px filter
    checker = AlignmentChecker(expected_markers=[(0, 0), (0, 0)], threshold=50)
    markers = checker.find_markers(frame)
    assert set(markers) == {(100, 100), (400, 300)}


def test_find_markers_none_on_blank_frame():
    frame = np.zeros((500, 700, 3), dtype=np.uint8)
    checker = AlignmentChecker(expected_markers=[(0, 0), (0, 0)], threshold=50)
    assert checker.find_markers(frame) == []


# --- check_and_correct / apply_offset: pure arithmetic, so find_markers is
# mocked to a known order rather than relying on real contour discovery. ---

def test_check_and_correct_updates_offset_within_threshold():
    checker = AlignmentChecker(expected_markers=[(100, 100), (400, 300)], threshold=50)
    with patch.object(checker, "find_markers", return_value=[(105, 105), (405, 305)]):
        corrected = checker.check_and_correct(frame=None, base_rois={"a": (0, 0, 10, 10)})
    assert checker.cumulative_offset == (5, 5)
    assert corrected["a"] == (5, 5, 15, 15)


def test_check_and_correct_ignores_large_drift():
    checker = AlignmentChecker(expected_markers=[(100, 100), (400, 300)], threshold=50)
    with patch.object(checker, "find_markers", return_value=[(300, 300), (600, 500)]):
        checker.check_and_correct(frame=None, base_rois={"a": (0, 0, 10, 10)})
    assert checker.cumulative_offset == (0, 0)  # left unchanged, drift exceeds threshold


def test_check_and_correct_keeps_last_offset_when_markers_missing():
    checker = AlignmentChecker(expected_markers=[(100, 100), (400, 300)], threshold=50)
    checker.cumulative_offset = (7, -3)
    with patch.object(checker, "find_markers", return_value=[]):
        corrected = checker.check_and_correct(frame=None, base_rois={"a": (0, 0, 10, 10)})
    assert corrected["a"] == (7, -3, 17, 7)


# --- C3 regression: main.py must always call check_and_correct() against
# the original calibration ROIs, never the previous check's corrected output,
# or the same drift gets applied on top of itself every check. ---

def test_repeated_checks_from_fixed_base_do_not_compound():
    checker = AlignmentChecker(expected_markers=[(100, 100), (400, 300)], threshold=50)
    base_rois = {"a": (0, 0, 10, 10)}

    with patch.object(checker, "find_markers", return_value=[(105, 105), (405, 305)]):
        checker.check_and_correct(frame=None, base_rois=base_rois)
    with patch.object(checker, "find_markers", return_value=[(105, 105), (405, 305)]):
        corrected = checker.check_and_correct(frame=None, base_rois=base_rois)

    # Same 5px drift measured twice against the original box -> still a
    # single 5px shift, not 10px.
    assert checker.cumulative_offset == (5, 5)
    assert corrected["a"] == (5, 5, 15, 15)


def test_feeding_corrected_rois_back_in_compounds_the_offset():
    """Documents the exact failure mode C3 fixed in main.py: pass the
    previous check's *corrected* ROIs back in as base_rois, and the same
    measured drift gets applied a second time on top of itself."""
    checker = AlignmentChecker(expected_markers=[(100, 100), (400, 300)], threshold=50)
    rois = {"a": (0, 0, 10, 10)}

    with patch.object(checker, "find_markers", return_value=[(105, 105), (405, 305)]):
        rois = checker.check_and_correct(frame=None, base_rois=rois)
    with patch.object(checker, "find_markers", return_value=[(105, 105), (405, 305)]):
        rois = checker.check_and_correct(frame=None, base_rois=rois)

    assert rois["a"] == (10, 10, 20, 20)  # 5px drift compounded to 10px


def test_apply_offset_shifts_all_rois():
    checker = AlignmentChecker(expected_markers=[(0, 0), (0, 0)], threshold=50)
    checker.cumulative_offset = (10, -5)
    rois = {"x": (0, 0, 20, 20), "y": (5, 5, 25, 25)}
    corrected = checker.apply_offset(rois)
    assert corrected == {"x": (10, -5, 30, 15), "y": (15, 0, 35, 20)}

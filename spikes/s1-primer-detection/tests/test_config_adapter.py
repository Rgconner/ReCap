"""Tests for config_adapter.py's SetupConfig -> detector-input shaping."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config_adapter import build_expected_markers, build_rois, build_template_names


def _roi(id_, x1, y1, x2, y2):
    return SimpleNamespace(id=id_, x1=x1, y1=y1, x2=x2, y2=y2)


def _marker(id_, x, y):
    return SimpleNamespace(id=id_, x=x, y=y)


def _config(rois=None, alignment=None):
    return SimpleNamespace(rois=rois or [], alignment=alignment or [])


def test_build_rois():
    config = _config(rois=[_roi("12", 420, 270, 491, 326), _roi("6", 213, 314, 285, 369)])
    assert build_rois(config) == {
        "12": (420, 270, 491, 326),
        "6": (213, 314, 285, 369),
    }


def test_build_rois_empty():
    assert build_rois(_config()) == {}


def test_build_template_names_present_and_absent_per_roi():
    config = _config(rois=[_roi("12", 0, 0, 1, 1), _roi("6", 0, 0, 1, 1)])
    names = build_template_names(config)
    assert set(names) == {"12_present", "12_absent", "6_present", "6_absent"}
    assert len(names) == 4


def test_build_expected_markers():
    config = _config(alignment=[_marker("M1", 139, 435), _marker("M2", 551, 285)])
    assert build_expected_markers(config) == [(139, 435), (551, 285)]


def test_build_expected_markers_uses_first_two_when_more_configured():
    config = _config(alignment=[_marker("M1", 1, 1), _marker("M2", 2, 2), _marker("M3", 3, 3)])
    assert build_expected_markers(config) == [(1, 1), (2, 2)]


def test_build_expected_markers_raises_when_fewer_than_two():
    config = _config(alignment=[_marker("M1", 1, 1)])
    with pytest.raises(ValueError, match="at least 2"):
        build_expected_markers(config)

"""End-to-end: a SetupConfig as the setup app would actually save it, run
through config_adapter into TemplateMatcher. Covers C1 from
spikes/s1-primer-detection/audit_report.md — analyze_frame() hardcodes the
four station/position names, so this proves a real SetupConfig produces a
condition without KeyError, and that a config missing one of those names
fails with a clear, actionable error (not a bare KeyError) instead.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(REPO_ROOT / "setup"))

from config_adapter import build_rois, build_template_names
from detector_v3 import TemplateMatcher
from roi_config import ROIS, ROLE_PRIMER_2
from setup_config import ROI, CameraConfig, SetupConfig

FRAME_SHAPE = (450, 700)  # (h, w) — matches test_detector_v3's fixture frame
_rng = np.random.default_rng(seed=42)
_BACKGROUND = (100 + _rng.integers(-15, 15, size=(*FRAME_SHAPE, 3))).astype(np.uint8)


def _setup_config(roi_ids):
    """A SetupConfig carrying only the given roi_ids, at their real
    calibrated coordinates from roi_config.ROIS — as if an operator had
    configured just those stations/positions in the setup app.
    """
    return SetupConfig(
        schema_version=1,
        detector_cmd="python main.py",
        camera=CameraConfig(by_path="usb-1", video_index=0, resolution={"w": 1280, "h": 720}),
        search_padding=20,
        created_at=datetime.now(timezone.utc).isoformat(),
        rois=[ROI(id=roi_id, x1=x1, y1=y1, x2=x2, y2=y2) for roi_id, (x1, y1, x2, y2) in
              ((roi_id, ROIS[roi_id]) for roi_id in roi_ids)],
    )


def _write_templates(tmp_dir, roi_ids, present_keys=()):
    """Present/absent template pair per roi_id, cropped from _BACKGROUND —
    mirrors test_detector_v3.py's _make_template_dir/_make_frame fixtures.
    """
    present_source = _BACKGROUND.copy()
    for roi_id in present_keys:
        x1, y1, x2, y2 = ROIS[roi_id]
        cv2.rectangle(present_source, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (230, 230, 230), -1)
        cv2.rectangle(present_source, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (10, 10, 10), 2)

    for roi_id in roi_ids:
        x1, y1, x2, y2 = ROIS[roi_id]
        cv2.imwrite(str(tmp_dir / f"{roi_id}_absent.png"), _BACKGROUND[y1:y2, x1:x2])
        cv2.imwrite(str(tmp_dir / f"{roi_id}_present.png"), present_source[y1:y2, x1:x2])

    return present_source


def test_full_setup_config_analyzes_without_keyerror(tmp_path):
    config = _setup_config(ROIS.keys())
    _write_templates(tmp_path, ROIS.keys(), present_keys=[ROLE_PRIMER_2])

    matcher = TemplateMatcher(
        str(tmp_path), rois=build_rois(config), template_names=build_template_names(config)
    )
    frame = _BACKGROUND.copy()
    x1, y1, x2, y2 = ROIS[ROLE_PRIMER_2]
    cv2.rectangle(frame, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (230, 230, 230), -1)
    cv2.rectangle(frame, (x1 + 2, y1 + 2), (x2 - 3, y2 - 3), (10, 10, 10), 2)

    results = matcher.analyze_frame(frame)  # would previously raise KeyError if IDs mismatched

    assert results["condition"] == "OK"
    assert results["action"] == "NONE"


def test_setup_config_missing_a_required_station_fails_clearly(tmp_path):
    # Operator never added the ROLE_PRIMER_2 ROI in the setup app UI.
    roi_ids = [r for r in ROIS.keys() if r != ROLE_PRIMER_2]
    config = _setup_config(roi_ids)
    _write_templates(tmp_path, roi_ids)

    matcher = TemplateMatcher(
        str(tmp_path), rois=build_rois(config), template_names=build_template_names(config)
    )

    with pytest.raises(ValueError, match=ROLE_PRIMER_2):
        matcher.analyze_frame(_BACKGROUND.copy())

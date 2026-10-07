"""Shapes a setup_config.SetupConfig into the plain values detector_v3 and
alignment expect. Kept separate from main.py so this logic is testable
without touching GPIO, the camera, or the filesystem.
"""
from typing import Dict, List, Tuple


def build_rois(config) -> Dict[str, Tuple[int, int, int, int]]:
    """SetupConfig.rois -> {roi_id: (x1, y1, x2, y2)} for TemplateMatcher."""
    return {roi.id: (roi.x1, roi.y1, roi.x2, roi.y2) for roi in config.rois}


def build_template_names(config) -> List[str]:
    """Every configured ROI needs a present/absent template pair."""
    names = []
    for roi in config.rois:
        names.append(f"{roi.id}_present")
        names.append(f"{roi.id}_absent")
    return names


def build_expected_markers(config) -> List[Tuple[int, int]]:
    """SetupConfig.alignment -> the two (x, y) points AlignmentChecker needs.

    Raises ValueError if fewer than 2 markers are configured — alignment
    correction can't run without both reference points.
    """
    markers = [(m.x, m.y) for m in config.alignment]
    if len(markers) < 2:
        raise ValueError(
            f"Need at least 2 alignment markers, got {len(markers)} — set them in the setup app"
        )
    return markers[:2]

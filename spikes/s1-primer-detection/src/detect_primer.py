"""Shadow-geometry primer detection — an early S1 approach.

Superseded operationally by detector_v3.py's template-matching approach,
which is what main.py actually wires to the GPIO trigger loop.
Kept alongside its tests (test_detect_primer.py) as a working alternative
for comparison; not currently used by the live pipeline.
"""
import cv2
import numpy as np
from typing import Tuple


def detect_primer_shadow(
    frame: np.ndarray,
    threshold: float = 0.3,
    min_area_ratio: float = 0.15,
    max_area_ratio: float = 0.85,
) -> Tuple[bool, dict]:
    """
    Detect primer presence by analyzing the shadow geometry in a borehole camera frame.
    
    The borehole camera looks down into the die cavity. When a primer is present,
    it casts a crescent-shaped shadow on the metal surface. Missing or misloaded
    primers produce detectable deviations in shadow edge continuity, area,
    and aspect ratio.
    
    Args:
        frame: Grayscale numpy array from the borehole camera.
        threshold: Grayscale threshold for edge detection (0-1).
        min_area_ratio: Minimum expected shadow area ratio of the die region.
        max_area_ratio: Maximum expected shadow area ratio of the die region.
    
    Returns:
        Tuple of (primer_present: bool, debug_info: dict).
    """
    if frame is None or frame.size == 0:
        return False, {"error": "empty frame"}
    
    # Work in grayscale
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame.copy()
    
    # Normalize and threshold to find the die region
    _, binary = cv2.threshold(
        gray, int(threshold * 255), 255, cv2.THRESH_BINARY_INV
    )
    
    # Find the outermost contour (die cavity boundary)
    contours, _ = cv2.findContours(
        binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    
    if not contours:
        return False, {"die_contour": "not found"}
    
    # Take the largest contour as the die region
    die_contour = max(contours, key=cv2.contourArea)
    die_area = cv2.contourArea(die_contour)
    
    # Find inner shadow contour (primer shadow)
    # The shadow appears as a hole/dark region within the die contour
    # OpenCV 3.x returns (_, contours, hierarchy); 4.x returns (contours, hierarchy).
    # On 4.x hierarchy is ndarray of shape (1, N, 4) — grab the N x 4 slice.
    result = cv2.findContours(
        binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    if len(result) == 3:
        _, all_contours, hdata = result
    else:
        all_contours, hdata = result
    # hdata may be (1, N, 4) — flatten to (N, 4) for standard indexing.
    if hdata is not None and hdata.ndim == 3:
        hdata = hdata[0]
    
    inner_contours = []
    if hdata is not None:
        for i, cnt in enumerate(all_contours):
            if hdata[i][3] > 0:  # parent index > 0 = this contour is inside another
                inner_contours.append(cnt)
    
    if not inner_contours:
        # No shadow detected — likely missing primer
        return False, {"shadow_contour": "not found", "die_area": die_area}
    
    # Take the largest inner contour as the primary shadow
    shadow_contour = max(inner_contours, key=cv2.contourArea)
    shadow_area = cv2.contourArea(shadow_contour)
    
    area_ratio = shadow_area / die_area
    
    # Primer present if shadow area is within expected range
    # The exact thresholds will be calibrated from real data
    is_present = min_area_ratio <= area_ratio <= max_area_ratio
    
    debug = {
        "die_contour_area": die_area,
        "shadow_contour_area": shadow_area,
        "area_ratio": area_ratio,
        "expected_min": min_area_ratio,
        "expected_max": max_area_ratio,
        "threshold": threshold,
        "num_inner_contours": len(inner_contours),
    }
    
    return is_present, debug


def capture_and_analyze(camera_path: str) -> Tuple[bool, dict]:
    """
    Capture a single frame from the specified camera and analyze for primer presence.
    
    Args:
        camera_path: Path to the camera, e.g. "/dev/v4l/by-path/usb-0:1.2.4:1.0-video-index0".
    
    Returns:
        Tuple of (primer_present: bool, full_debug: dict).
    """
    # In production, this would use the audit_paths.py camera mapping
    # For now, placeholder for GPIO end-stop integration
    raise NotImplementedError(
        "Integrate with GPIO end-stop and camera path stability from S0"
    )


if __name__ == "__main__":
    # Simple test harness when run directly
    import sys
    if len(sys.argv) > 1:
        img_path = sys.argv[1]
        frame = cv2.imread(img_path, cv2.IMREAD_COLOR)
        if frame is not None:
            present, debug = detect_primer_shadow(frame)
            print(f"Primer present: {present}")
            print(f"Debug: {debug}")
        else:
            print(f"Failed to load image: {img_path}")
    else:
        print("Usage: python detect_primer.py <image_path>")


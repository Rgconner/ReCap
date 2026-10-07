import cv2
import os
from pathlib import Path

from roi_config import ROIS

REPO_ROOT = Path(__file__).resolve().parents[3]

TEMPLATES = {
    "Position-4_absent": ("empty", "Position-4"),
    "Position-4_present": ("misload", "Position-4"),
    "Position-2_absent": ("empty", "Position-2"),
    "Position-2_present": ("ideal", "Position-2"),
    "Station-6-Neck-Expand_absent": ("empty", "Station-6-Neck-Expand"),
    "Station-6-Neck-Expand_present": ("misload", "Station-6-Neck-Expand"),
    "Station-4-Swage_absent": ("empty", "Station-4-Swage"),
    "Station-4-Swage_present": ("ideal", "Station-4-Swage"),
}

base_path = REPO_ROOT / "baseline"
output_dir = REPO_ROOT / "templates"

os.makedirs(output_dir, exist_ok=True)

print("=== Extracting SMALL Templates (Detection Only) ===\n")

for template_name, (condition, roi_key) in TEMPLATES.items():
    frame_path = base_path / condition / "capture" / "captured_frame.png"
    img = cv2.imread(str(frame_path))

    if img is None:
        print(f"ERROR: Cannot load {frame_path}")
        continue

    x1, y1, x2, y2 = ROIS[roi_key]
    roi = img[y1:y2, x1:x2]

    output_path = output_dir / f"{template_name}.png"
    cv2.imwrite(str(output_path), roi)

    print(f"Saved: {template_name} ({roi.shape[1]}x{roi.shape[0]})")

print(f"\nAll templates saved to: {output_dir}")

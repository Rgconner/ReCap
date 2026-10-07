import cv2
import numpy as np
from pathlib import Path

from roi_config import ROIS

REPO_ROOT = Path(__file__).resolve().parents[3]

def find_yellow_markers(frame):
    """Find yellow X markers in the frame."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Yellow range in HSV
    lower_yellow = np.array([20, 100, 100])
    upper_yellow = np.array([35, 255, 255])
    mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    markers = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 100:  # Filter small noise
            M = cv2.moments(cnt)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                markers.append((cx, cy, area))
    
    # Sort by area (largest first) and return top 2
    markers.sort(key=lambda x: x[2], reverse=True)
    return [(m[0], m[1]) for m in markers[:2]]

def draw_rois(frame, rois):
    """Draw ROI boxes on the frame."""
    colors = {
        "Station-4-Swage": (0, 255, 0),          # Green
        "Station-6-Neck-Expand": (255, 255, 0),  # Yellow
        "Position-4": (0, 0, 255),               # Red
        "Position-2": (255, 0, 0),                 # Blue
    }
    for key, (x1, y1, x2, y2) in rois.items():
        color = colors.get(key, (255, 255, 255))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, key, (x1+5, y1+20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

def draw_markers(frame, markers):
    """Draw circles on detected markers."""
    for i, (cx, cy) in enumerate(markers):
        cv2.circle(frame, (cx, cy), 15, (0, 255, 255), 3)  # Cyan circle
        cv2.putText(frame, f"M{i+1}", (cx+20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

# Capture frame
camera = cv2.VideoCapture('/dev/video0')
if not camera.isOpened():
    print("ERROR: Cannot open camera")
    exit(1)

ret, frame = camera.read()
if not ret:
    print("ERROR: Failed to capture frame")
    exit(1)

camera.release()

# Find markers
markers = find_yellow_markers(frame)
print(f"Found {len(markers)} markers:")
for i, (cx, cy) in enumerate(markers):
    print(f"  Marker {i+1}: ({cx}, {cy})")

# Draw ROIs and markers
draw_rois(frame, ROIS)
draw_markers(frame, markers)

# Save result
output_path = str(REPO_ROOT / "alignment_check.png")
cv2.imwrite(output_path, frame)
print(f"\nSaved alignment check to: {output_path}")
print("Push to git and review on Windows to see if ROIs need adjustment.")

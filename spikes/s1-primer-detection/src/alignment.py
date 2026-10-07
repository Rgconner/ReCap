"""Camera-drift correction using two reference markers, applied to detection
ROIs at startup and periodically between triggers. Moved out of
integration_test.py unchanged.
"""
import cv2
import numpy as np


class AlignmentChecker:
    def __init__(self, expected_markers, threshold):
        self.expected_markers = expected_markers
        self.threshold = threshold
        self.cumulative_offset = (0, 0)

    def find_markers(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower = np.array([15, 50, 50])
        upper = np.array([40, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        markers = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 100:
                M = cv2.moments(cnt)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    markers.append((cx, cy, area))

        markers.sort(key=lambda x: x[2], reverse=True)
        return [(m[0], m[1]) for m in markers[:2]]

    def check_and_correct(self, frame, base_rois):
        current_markers = self.find_markers(frame)

        if len(current_markers) < 2:
            print("[ALIGNMENT] Markers not found - keeping last offset")
            return self.apply_offset(base_rois)

        offsets = []
        for i in range(2):
            dx = current_markers[i][0] - self.expected_markers[i][0]
            dy = current_markers[i][1] - self.expected_markers[i][1]
            offsets.append((dx, dy))

        avg_dx = int(np.mean([o[0] for o in offsets]))
        avg_dy = int(np.mean([o[1] for o in offsets]))
        distance = np.sqrt(avg_dx**2 + avg_dy**2)

        # FIX: Only update offset if drift is reasonable
        if distance > self.threshold:
            print(f"[ALIGNMENT] WARNING: Drift {distance:.1f}px exceeds threshold. Ignoring.")
        else:
            print(f"[ALIGNMENT] OK (drift: {distance:.1f}px)")
            self.cumulative_offset = (avg_dx, avg_dy)

        return self.apply_offset(base_rois)

    def apply_offset(self, base_rois):
        dx, dy = self.cumulative_offset
        corrected = {}
        for key, (x1, y1, x2, y2) in base_rois.items():
            corrected[key] = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        return corrected

import cv2
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

def capture_baseline(condition_name):
    base_dir = REPO_ROOT / "baseline"
    output_dir = os.path.join(base_dir, condition_name, "capture")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "captured_frame.png")
    
    print(f"Capturing baseline for: {condition_name}")
    print("Saving to: " + output_path)
    
    # Open camera
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return False
    
    # Read a few frames to let auto-exposure/white balance settle
    for _ in range(10):
        cap.read()
        
    # Capture the actual frame
    ret, frame = cap.read()
    cap.release()
    
    if ret:
        cv2.imwrite(output_path, frame)
        print(f"Success! Saved to {output_path}")
        return True
    else:
        print("Error: Failed to capture frame.")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python capture_baseline.py <condition_name>")
        print("Example: python capture_baseline.py ideal")
        sys.exit(1)
    
    capture_baseline(sys.argv[1])

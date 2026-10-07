#!/usr/bin/env python3
"""
S1 Primer Detection Test Harness

Calibration/evaluation harness for detect_primer.py's shadow-geometry
approach, which is superseded operationally by detector_v3.py's template
matching (see detect_primer.py's module docstring). Kept for comparing the
two approaches, not currently used by the live pipeline.

Captures labeled images from the borehole camera, runs detection, and reports
metrics for algorithm calibration. Can be run in three modes:

1. --capture: Live camera capture (requires Pi + camera)
2. --images-dir: Process a directory of pre-labeled images
3. --synthetic: Generate synthetic test images on the fly

Usage:
    python test_harness.py --capture
    python test_harness.py --images-dir /path/to/test_images
    python test_harness.py --synthetic --count 20
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np
from detect_primer import detect_primer_shadow


def parse_label_file(label_path: Path) -> Dict[str, bool]:
    """Parse a labels.csv file: image_path, primer_present (0/1/True/False)."""
    labels: Dict[str, bool] = {}
    if not label_path.exists():
        return labels
    with open(label_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_path = row.get("image_path", "")
            if img_path:
                img_path = Path(img_path)
                try:
                    present = row.get("primer_present", "0").lower() in (
                        "1", "true", "yes", "y"
                    )
                except Exception:
                    present = False
                labels[str(img_path)] = present
    return labels


def capture_frame(camera_path: str) -> Tuple[np.ndarray, str]:
    """Capture a single frame from the specified camera path."""
    cap = cv2.VideoCapture(camera_path, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Camera not opened at {camera_path}")
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"Failed to read frame from {camera_path}")
    return frame, str(camera_path)


def process_image(image_path: Path, threshold: float = 0.3) -> Tuple[bool, dict]:
    """Run detection on a single image file."""
    frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        return False, {"error": "empty or unreadable frame"}
    return detect_primer_shadow(frame, threshold=threshold)


def process_images_dir(
    images_dir: Path, label_path: Path = None, threshold: float = 0.3
) -> Dict[str, Tuple[bool, dict]]:
    """Process all images in a directory. Labels for metrics are loaded and
    compared separately by the caller (see main()'s --images-dir branch)."""
    results: Dict[str, Tuple[bool, dict]] = {}
    images = sorted(images_dir.glob("*.*"))

    for img_path in images:
        if img_path.is_dir():
            continue
        try:
            present, debug = process_image(img_path, threshold=threshold)
            results[str(img_path)] = (present, debug)
        except Exception as e:
            results[str(img_path)] = (False, {"error": str(e)})

    return results


def compute_metrics(
    results: Dict[str, Tuple[bool, dict]], true_labels: Dict[str, bool]
) -> Dict[str, float]:
    """Compute precision, recall, specificity, F1, and confusion matrix."""
    tp = fp = tn = fn = 0
    for img_path, (pred, _) in results.items():
        if img_path in true_labels:
            true = true_labels[img_path]
            if pred and true:
                tp += 1
            elif pred and not true:
                fp += 1
            elif not pred and not true:
                tn += 1
            else:
                fn += 1

    metrics: Dict[str, float] = {}
    if tp + fp > 0:
        metrics["precision"] = tp / (tp + fp)
    else:
        metrics["precision"] = 0.0
    if tp + fn > 0:
        metrics["recall"] = tp / (tp + fn)
    else:
        metrics["recall"] = 0.0
    if tn + fn > 0:
        metrics["specificity"] = tn / (tn + fn)
    else:
        metrics["specificity"] = 0.0
    if tp + fp + tn + fn > 0:
        metrics["accuracy"] = (tp + tn) / (tp + fp + tn + fn)
    else:
        metrics["accuracy"] = 0.0
    if metrics["precision"] > 0 and metrics["recall"] > 0:
        metrics["f1_score"] = 2 * (metrics["precision"] * metrics["recall"])
        metrics["f1_score"] /= metrics["precision"] + metrics["recall"]
    else:
        metrics["f1_score"] = 0.0

    metrics["confusion_matrix"] = {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
    return metrics


def save_results(
    results: Dict[str, Tuple[bool, dict]],
    metrics: Dict[str, float],
    out_dir: Path,
    threshold: float,
) -> None:
    """Save results to CSV and summary report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "detection_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "image_path",
            "predicted_present",
            "die_contour_area",
            "shadow_contour_area",
            "area_ratio",
            "expected_min",
            "expected_max",
            "threshold",
            "num_inner_contours",
            "debug_notes",
        ])
        for img_path, (pred, debug) in results.items():
            writer.writerow([
                img_path,
                pred,
                debug.get("die_contour_area", ""),
                debug.get("shadow_contour_area", ""),
                debug.get("area_ratio", ""),
                debug.get("expected_min", threshold),
                debug.get("expected_max", threshold),
                debug.get("threshold", threshold),
                debug.get("num_inner_contours", ""),
                debug.get("error", ""),
            ])
    report_path = out_dir / "summary.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("S1 Primer Detection Test Harness\n")
        f.write(f"Threshold: {threshold}\n\n")
        f.write("Confusion Matrix:\n")
        cm = metrics["confusion_matrix"]
        f.write(f"  TP (primer present AND predicted): {cm['tp']}\n")
        f.write(f"  FP (primer absent AND predicted): {cm['fp']}\n")
        f.write(f"  TN (primer absent AND not predicted): {cm['tn']}\n")
        f.write(f"  FN (primer present AND not predicted): {cm['fn']}\n\n")
        f.write("Metrics:\n")
        f.write(f"  Precision: {metrics['precision']:.4f}\n")
        f.write(f"  Recall: {metrics['recall']:.4f}\n")
        f.write(f"  Specificity: {metrics['specificity']:.4f}\n")
        f.write(f"  Accuracy: {metrics['accuracy']:.4f}\n")
        f.write(f"  F1 Score: {metrics['f1_score']:.4f}\n")
    print(f"Results saved to: {out_dir}/\n")
    print(f"  - {csv_path.name}\n")
    print(f"  - {report_path.name}\n")


def generate_synthetic_test_set(
    count: int, out_dir: Path, seed: int = 42, with_primer: bool = True
) -> Tuple[Dict[str, bool], List[Path]]:
    """Generate synthetic die images for testing. Returns labels and paths.

    When ``with_primer`` is False (the default for --synthetic mode), half the
    images get a crescent shadow (primer present) and half get no shadow
    (primer absent), providing a balanced test set for meaningful metrics.
    Pass ``with_primer=True`` for legacy single-class generation.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    labels: Dict[str, bool] = {}
    image_paths: List[Path] = []

    for i in range(count):
        img = np.ones((400, 400), dtype=np.uint8) * 180
        cv2.circle(img, (200, 200), 150, 30, 8)
        cv2.circle(img, (200, 200), 145, 160, 8)
        if with_primer:
            has_primer = True
        else:
            has_primer = (i % 2 == 0)  # balanced: even-indexed have primer
        if has_primer:
            cv2.ellipse(img, (190, 195), (110, 80), 0, 0, 300, 30, -1)
        img_path = out_dir / f"synthetic_{i:04d}.png"
        cv2.imwrite(str(img_path), img)
        image_paths.append(img_path)
        labels[str(img_path)] = has_primer

    return labels, image_paths



def main() -> int:
    parser = argparse.ArgumentParser(
        description="S1 Primer Detection Test Harness"
    )
    parser.add_argument(
        "--capture", action="store_true",
        help="Capture live frames from camera (requires /dev/video* device)"
    )
    parser.add_argument(
        "--images-dir", type=Path,
        help="Path to directory of pre-labeled test images"
    )
    parser.add_argument(
        "--label-file", type=Path,
        help="Path to labels.csv (if not in images-dir)"
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Generate synthetic test images instead of capturing"
    )
    parser.add_argument(
        "--count", type=int, default=10,
        help="Number of synthetic images (default: 10)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.3,
        help="Detection threshold 0-1 (default: 0.3)"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("test_results"),
        help="Output directory (default: ./test_results)"
    )
    parser.add_argument(
        "--camera-path", type=str, default="/dev/video0",
        help="Camera device path (default: /dev/video0)"
    )
    args = parser.parse_args()

    if args.capture:
        print(f"Capturing from {args.camera_path}...")
        try:
            frame, src = capture_frame(args.camera_path)
            print(f"Got frame from {src}")
            out = args.out_dir / "capture"
            out.mkdir(parents=True, exist_ok=True)
            fp = out / "captured_frame.png"
            cv2.imwrite(str(fp), frame)
            print(f"Saved: {fp}")
            present, debug = process_image(fp, threshold=args.threshold)
            label = "present" if present else "absent"
            print(f"Primer {label}, debug={debug}")
            return 0
        except Exception as e:
            print(f"Capture failed: {e}")
            return 1

    if args.synthetic:
        print(f"Generating {args.count} synthetic images...")
        labels, _ = generate_synthetic_test_set(
            count=args.count, out_dir=args.out_dir, with_primer=False, seed=42
        )
        results = {}
        for img_path in labels:
            try:
                present, debug = process_image(
                    Path(img_path), threshold=args.threshold
                )
                results[img_path] = (present, debug)
            except Exception as e:
                results[img_path] = (False, {"error": str(e)})
        print("\nSynthetic test results:")
        for img_path, (pred, debug) in sorted(results.items()):
            label = "present" if labels.get(img_path, False) else "absent"
            status = "OK" if pred == labels.get(img_path, False) else "MISMATCH"
            print(f"  {Path(img_path).name}: true={label} pred={pred} [{status}]")
        metrics = compute_metrics(results, labels)
        print("\n--- Metrics ---")
        cm = metrics.get("confusion_matrix", {})
        print(f"  TP={cm.get('tp', 0)} FP={cm.get('fp', 0)} TN={cm.get('tn', 0)} FN={cm.get('fn', 0)}")
        print(f"  Precision: {metrics.get('precision', 0):.3f}")
        print(f"  Recall:    {metrics.get('recall', 0):.3f}")
        print(f"  Accuracy:  {metrics.get('accuracy', 0):.3f}")
        print(f"  F1 Score:  {metrics.get('f1_score', 0):.3f}")
        save_results(results, metrics, args.out_dir, args.threshold)
        return 0

    if args.images_dir:
        d = args.images_dir
        if not d.exists() or not d.is_dir():
            print(f"Error: not a directory: {d}")
            return 1
        lp = args.label_file if args.label_file else d / "labels.csv"
        print(f"Processing: {d}\nLabels: {lp}")
        results = process_images_dir(d, lp, threshold=args.threshold)
        true_labels = parse_label_file(lp)
        if not true_labels:
            print("Warning: no labels found, detection only.")
            metrics = {}
        else:
            metrics = compute_metrics(results, true_labels)
        save_results(results, metrics, args.out_dir, args.threshold)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

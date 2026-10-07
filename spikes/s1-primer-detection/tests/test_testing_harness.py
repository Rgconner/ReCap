"""Tests for testing_harness.py utilities."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2
import numpy as np
from testing_harness import (
    parse_label_file,
    compute_metrics,
    generate_synthetic_test_set,
    process_image,
    save_results,
)


def _tmpdir():
    return Path(tempfile.mkdtemp())


# --- parse_label_file ---

def test_valid_csv():
    d = _tmpdir()
    p = d / "labels.csv"
    p.write_text(
        "image_path,primer_present\n"
        "img001.png,1\nimg002.png,0\n"
    )
    labels = parse_label_file(p)
    assert labels == {"img001.png": True, "img002.png": False}


def test_missing_file():
    labels = parse_label_file(Path("/nonexistent__/labels.csv"))
    assert labels == {}


def test_empty_csv():
    d = _tmpdir()
    p = d / "labels.csv"
    p.write_text("image_path,primer_present\n")
    labels = parse_label_file(p)
    assert labels == {}


def test_default_to_false():
    d = _tmpdir()
    p = d / "labels.csv"
    p.write_text("image_path,primer_present\nx.png,unknown\n")
    labels = parse_label_file(p)
    assert labels == {"x.png": False}


# --- compute_metrics ---

def test_perfect():
    results = {"a": (True, {}), "b": (False, {})}
    true = {"a": True, "b": False}
    m = compute_metrics(results, true)
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["accuracy"] == 1.0
    assert m["f1_score"] == 1.0


def test_all_wrong():
    results = {"a": (True, {}), "b": (False, {})}
    true = {"a": False, "b": True}
    m = compute_metrics(results, true)
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0


def test_empty():
    m = compute_metrics({}, {})
    assert m["precision"] == 0.0


def test_fp_only():
    results = {"a": (True, {}), "b": (True, {})}
    true = {"a": False, "b": False}
    m = compute_metrics(results, true)
    assert m["precision"] == 0.0
    assert m["confusion_matrix"]["fp"] == 2


def test_partial_labels():
    results = {"a": (True, {}), "z": (False, {})}
    true = {"a": True}
    m = compute_metrics(results, true)
    assert m["confusion_matrix"]["tp"] == 1
    assert m["confusion_matrix"]["fp"] == 0


# --- process_image ---

def test_valid_image():
    img = np.ones((400, 400), dtype=np.uint8) * 180
    cv2.circle(img, (200, 200), 150, 30, 8)
    cv2.circle(img, (200, 200), 145, 160, 8)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        cv2.imwrite(f.name, img)
        tmp = f.name
    try:
        present, debug = process_image(Path(tmp))
        assert isinstance(present, bool)
        assert isinstance(debug, dict)
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_nonexistent_file():
    present, debug = process_image(Path("/nonexistent/img.png"))
    assert not present
    assert "error" in debug


# --- generate_synthetic_test_set ---

def test_balanced():
    d = _tmpdir()
    labels, paths = generate_synthetic_test_set(
        count=20, out_dir=d, with_primer=False, seed=42)
    assert len(labels) == 20
    n_present = sum(1 for v in labels.values() if v)
    n_absent = sum(1 for v in labels.values() if not v)
    assert n_present == 10
    assert n_absent == 10
    for p in paths:
        assert p.exists()


def test_single_class():
    d = _tmpdir()
    labels, _ = generate_synthetic_test_set(
        count=10, out_dir=d, with_primer=True, seed=42)
    assert all(v for v in labels.values())


def test_deterministic():
    d1 = _tmpdir()
    d2 = _tmpdir()
    labels1, _ = generate_synthetic_test_set(
        count=10, out_dir=d1, with_primer=False, seed=42)
    labels2, _ = generate_synthetic_test_set(
        count=10, out_dir=d2, with_primer=False, seed=42)
    vals1 = [v for _, v in sorted(
        labels1.items(), key=lambda x: Path(x[0]).name)]
    vals2 = [v for _, v in sorted(
        labels2.items(), key=lambda x: Path(x[0]).name)]
    assert vals1 == vals2


# --- save_results ---

def test_saves_both_files():
    d = _tmpdir()
    out = d / "results"
    metrics = {
        "precision": 1.0, "recall": 1.0, "specificity": 1.0,
        "accuracy": 1.0, "f1_score": 1.0,
        "confusion_matrix": {"tp": 1, "fp": 0, "tn": 0, "fn": 0},
    }
    results = {"img.png": (True, {"area_ratio": 0.3})}
    save_results(results, metrics, out, threshold=0.3)
    assert (out / "detection_results.csv").exists()
    assert (out / "summary.txt").exists()


def test_empty_doesnt_crash():
    d = _tmpdir()
    out = d / "results"
    metrics = {
        "precision": 0.0, "recall": 0.0, "specificity": 0.0,
        "accuracy": 0.0, "f1_score": 0.0,
        "confusion_matrix": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
    }
    save_results({}, metrics, out, threshold=0.3)
    assert (out / "detection_results.csv").exists()

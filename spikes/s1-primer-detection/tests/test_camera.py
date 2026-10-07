"""Tests for camera.py's by-path -> live device resolution, and the
broker's atomic frame write/read (see its module docstring for why the
broker exists -- multi-process camera contention + stale-buffer bugs found
live 2026-09-06)."""
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import camera


def test_resolves_symlink_to_real_device(tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "BY_PATH_DIR", tmp_path)
    # Real by-path names contain colons (Linux-only chars); avoid them here
    # so this test can create the stand-in file on any OS.
    link_name = "usb-0-1.2.4-1.0-video-index0"
    (tmp_path / link_name).write_text("")  # stand-in for the by-path symlink

    monkeypatch.setattr(
        camera.os.path, "realpath",
        lambda p: "/dev/video2" if str(p) == str(tmp_path / link_name) else str(p),
    )

    assert camera.resolve_video_capture_target(link_name) == "/dev/video2"


def test_missing_symlink_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "BY_PATH_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        camera.resolve_video_capture_target("does-not-exist")


# --- write_frame_atomic / read_latest_frame ---

def _fake_frame():
    return (np.random.default_rng(seed=1).integers(0, 255, size=(10, 10, 3))).astype(np.uint8)


def test_write_then_read_round_trips(tmp_path):
    path = tmp_path / "latest_frame.jpg"
    camera.write_frame_atomic(_fake_frame(), path=path)

    assert path.exists()
    tmp_path = path.with_name(path.stem + ".tmp" + path.suffix)
    assert not tmp_path.exists()  # temp file renamed away, not left behind

    frame = camera.read_latest_frame(path=path, max_age_s=10.0)
    assert frame is not None
    assert frame.shape[:2] == (10, 10)


def test_read_missing_frame_raises_file_not_found(tmp_path):
    path = tmp_path / "does_not_exist.jpg"
    with pytest.raises(FileNotFoundError):
        camera.read_latest_frame(path=path, max_age_s=10.0)


def test_read_stale_frame_raises(tmp_path):
    path = tmp_path / "latest_frame.jpg"
    camera.write_frame_atomic(_fake_frame(), path=path)

    # Back-date the file's mtime so it looks like the broker hasn't
    # refreshed it in a while, without needing to actually sleep in the test.
    stale_mtime = time.time() - 10.0
    os.utime(path, (stale_mtime, stale_mtime))

    with pytest.raises(camera.StaleFrameError):
        camera.read_latest_frame(path=path, max_age_s=2.0)


def test_read_fresh_frame_within_max_age_succeeds(tmp_path):
    path = tmp_path / "latest_frame.jpg"
    camera.write_frame_atomic(_fake_frame(), path=path)
    # Just-written -- well within any reasonable max_age_s.
    camera.read_latest_frame(path=path, max_age_s=2.0)


def test_read_undecodable_frame_raises_file_not_found(tmp_path):
    path = tmp_path / "latest_frame.jpg"
    path.write_bytes(b"not a real image")
    with pytest.raises(FileNotFoundError):
        camera.read_latest_frame(path=path, max_age_s=10.0)

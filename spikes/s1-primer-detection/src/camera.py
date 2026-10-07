"""Resolves a camera's stable by-path identity to a live capture target,
and brokers exclusive access to it.

Mirrors the by-path resolution spikes/s0-camera-path-stability/audit_paths.py
already does (scan_by_path()) — /dev/v4l/by-path/<name> symlinks to the
current /dev/videoN node, which can renumber across reboots/replugs while
the by-path name stays stable. video_index alone (as recorded by the setup
app) isn't trustworthy across a reboot; by_path is.

Broker design (added 2026-09-06): main.py and the
setup app (server.py) each used to open their own cv2.VideoCapture on the
same physical camera. Two independent processes fighting over one USB/UVC
device produced three genuinely different, none-current images -- confirmed
live. A single-owner fix isn't enough on its own either: even with exactly
one process reading, a plain camera.read() on trigger can return a frame
the driver already had queued from before that instant, unless the buffer
is continuously drained.

run_broker() is meant to run forever as its own process, the camera's only
owner, continuously reading frames and writing the latest one to disk with
an atomic rename. Consumers never touch cv2.VideoCapture at all -- they
call read_latest_frame(), which just reads that file and checks it isn't
stale. No request/response round-trip, no socket: same same-filesystem,
same-Pi assumption runtime_state.py already makes for alarm state.
"""
import os
import time
from pathlib import Path

import cv2

BY_PATH_DIR = Path("/dev/v4l/by-path")

REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = REPO_ROOT / "setup" / "setup_state"
LATEST_FRAME_PATH = STATE_DIR / "latest_frame.jpg"

# How old the broker's last-written frame is allowed to be before a reader
# should treat it as untrustworthy (broker died, camera unplugged, etc.)
# rather than silently detecting against a stale picture.
MAX_FRAME_AGE_S = 2.0


def resolve_video_capture_target(by_path: str) -> str:
    """Resolves a by-path symlink name to a real /dev/videoN path, suitable
    for passing straight to cv2.VideoCapture().

    Raises FileNotFoundError if the symlink doesn't exist (camera unplugged
    or not yet enumerated by udev).
    """
    link = BY_PATH_DIR / by_path
    if not link.exists():
        raise FileNotFoundError(f"No camera at {link} — check it's plugged in and enumerated")
    return os.path.realpath(link)


class StaleFrameError(RuntimeError):
    """The broker's last-written frame is older than MAX_FRAME_AGE_S --
    treat this the same as no frame being available at all."""


def write_frame_atomic(frame, path: Path = LATEST_FRAME_PATH) -> None:
    """Writes frame so a concurrent reader never sees a half-written file --
    write to a temp path in the same directory, then os.replace() (atomic
    on POSIX) onto the real path. The temp path keeps path's real suffix
    (.jpg) rather than appending .tmp after it -- cv2.imwrite picks its
    encoder from the final suffix, so a literal ".jpg.tmp" would silently
    fail to encode as JPEG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.stem + ".tmp" + path.suffix)
    cv2.imwrite(str(tmp_path), frame)
    os.replace(tmp_path, path)


def read_latest_frame(path: Path = LATEST_FRAME_PATH, max_age_s: float = MAX_FRAME_AGE_S):
    """Returns the broker's most recent frame as a numpy array.

    Raises FileNotFoundError if the broker has never written a frame (not
    running, or hasn't started up yet), or StaleFrameError if the last
    write is older than max_age_s (broker died, camera unplugged) -- either
    way, callers should treat these as "no current frame available", not
    silently detect against whatever's on disk.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No frame at {path} — is camera.py's broker running?"
        )
    age_s = time.time() - path.stat().st_mtime
    if age_s > max_age_s:
        raise StaleFrameError(
            f"Latest frame at {path} is {age_s:.1f}s old (limit {max_age_s}s) — "
            "broker may have died or the camera may be disconnected"
        )
    frame = cv2.imread(str(path))
    if frame is None:
        raise FileNotFoundError(f"Frame at {path} exists but failed to decode")
    return frame


def run_broker(by_path: str) -> None:
    """Runs forever as the camera's sole owner, continuously refreshing
    LATEST_FRAME_PATH. Reconnects on transient read failures rather than
    exiting, since this is meant to be a long-lived background service."""
    camera_target = resolve_video_capture_target(by_path)
    camera = cv2.VideoCapture(camera_target)
    if not camera.isOpened():
        raise RuntimeError(f"Cannot open camera at {camera_target}")

    print(f"camera.py broker: reading {by_path} -> {camera_target}, "
          f"writing {LATEST_FRAME_PATH}")
    frame_count = 0
    try:
        while True:
            ret, frame = camera.read()
            if not ret:
                print("WARNING: camera read failed, retrying...")
                time.sleep(0.5)
                continue
            write_frame_atomic(frame)
            frame_count += 1
            if frame_count % 300 == 0:
                print(f"camera.py broker: {frame_count} frames written")
    except KeyboardInterrupt:
        print("\ncamera.py broker: shutting down")
    finally:
        camera.release()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(REPO_ROOT / "setup"))
    from setup_config import load_config

    config_path = STATE_DIR / "config.json"
    if not config_path.exists():
        print(f"ERROR: No config found at {config_path}. Run the setup app first.")
        sys.exit(1)

    config = load_config(config_path)
    run_broker(config.camera.by_path)

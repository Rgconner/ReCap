import json
import os

import pytest

os.environ.setdefault("RECAP_SETUP_TOKEN", "test-token")

import cv2
import numpy as np
from fastapi.testclient import TestClient

import runtime_state
import server

TOKEN = os.environ["RECAP_SETUP_TOKEN"]
AUTH = {"X-Setup-Token": TOKEN}


class FakeCap:
    """Stand-in for cv2.VideoCapture — no real camera in CI."""

    opens = True
    reads = True
    frame_shape = (480, 640, 3)

    def __init__(self, index):
        self.index = index

    def isOpened(self):
        return FakeCap.opens

    def read(self):
        if not FakeCap.reads:
            return False, None
        return True, np.zeros(FakeCap.frame_shape, dtype=np.uint8)

    def release(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    # BASE_DIR must stay an ancestor of TEMPLATES_DIR: capture_template()
    # computes template_path.relative_to(BASE_DIR), which raises if it isn't.
    state_dir = tmp_path / "setup_state"
    templates_dir = state_dir / "templates"
    snapshots_dir = state_dir / "snapshots"
    templates_dir.mkdir(parents=True)
    snapshots_dir.mkdir(parents=True)
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<html>ReCap Setup</html>")

    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(server, "STATE_DIR", state_dir)
    monkeypatch.setattr(server, "CONFIG_PATH", state_dir / "config.json")
    monkeypatch.setattr(server, "TEMPLATES_DIR", templates_dir)
    monkeypatch.setattr(server, "SNAPSHOTS_DIR", snapshots_dir)
    monkeypatch.setattr(runtime_state, "STATE_DIR", state_dir)
    monkeypatch.setattr(runtime_state, "ALARM_STATE_PATH", state_dir / "alarm_state.json")
    monkeypatch.setattr(runtime_state, "ACK_REQUEST_PATH", state_dir / "ack_request.flag")
    monkeypatch.setattr(server.cv2, "VideoCapture", FakeCap)
    FakeCap.opens = True
    FakeCap.reads = True

    return TestClient(server.app)


def _write_config(client, rois=None):
    config = {
        "schema_version": 1,
        "detector_cmd": "python detector.py",
        "camera": {"by_path": "usb-1", "video_index": 0, "resolution": {"w": 640, "h": 480}},
        "search_padding": 20,
        "created_at": "2026-08-31T00:00:00Z",
        "rois": rois or [{"id": "12", "x1": 0, "y1": 0, "x2": 10, "y2": 10}],
        "alignment": [],
        "templates": [],
    }
    server.CONFIG_PATH.write_text(json.dumps(config))
    return config


# --- auth ---

def test_missing_token_rejected(client):
    r = client.get("/api/config")
    assert r.status_code == 422


def test_wrong_token_rejected(client):
    r = client.get("/api/config", headers={"X-Setup-Token": "wrong"})
    assert r.status_code == 401


# --- /api/config ---

def test_get_config_no_file_returns_none(client):
    r = client.get("/api/config", headers=AUTH)
    assert r.status_code == 200
    assert r.json() is None


def test_update_then_get_config_roundtrip(client):
    config = _write_config(client)
    server.CONFIG_PATH.unlink()  # start clean, let the POST create it

    r = client.post("/api/config", json=config, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"status": "success"}

    r = client.get("/api/config", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["camera"]["by_path"] == "usb-1"


def test_update_config_missing_field_returns_400(client):
    r = client.post("/api/config", json={"schema_version": 1}, headers=AUTH)
    assert r.status_code == 400


def test_update_config_runs_validate_not_just_from_dict(client):
    """Regression test: update_config() must call SetupConfig.validate(),
    not just from_dict() — a syntactically-valid-but-semantically-invalid
    config (like an alarm policy pointing at a nonexistent output) must be
    rejected at save time, not silently written and only fail later on
    the next load."""
    config = _write_config(client)
    server.CONFIG_PATH.unlink()
    config["alarm_outputs"] = []
    config["alarm_policies"] = [{"action": "STOP", "mode": "latch", "pulse_ms": 300, "outputs": ["ghost"]}]

    r = client.post("/api/config", json=config, headers=AUTH)

    assert r.status_code == 400
    assert "unknown output id" in r.json()["detail"]
    assert not server.CONFIG_PATH.exists()  # must not have been written


# --- /api/snapshot ---

def test_snapshot_requires_video_index_or_by_path(client):
    r = client.get("/api/snapshot", headers=AUTH)
    assert r.status_code == 400


def test_snapshot_by_path_unsupported_on_windows(client):
    r = client.get("/api/snapshot", params={"by_path": "usb-1"}, headers=AUTH)
    assert r.status_code == 400


def test_snapshot_success(client):
    r = client.get("/api/snapshot", params={"video_index": 0}, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 0


def test_snapshot_camera_wont_open(client):
    FakeCap.opens = False
    r = client.get("/api/snapshot", params={"video_index": 0}, headers=AUTH)
    assert r.status_code == 500


def test_snapshot_camera_read_fails(client):
    FakeCap.reads = False
    r = client.get("/api/snapshot", params={"video_index": 0}, headers=AUTH)
    assert r.status_code == 500


# --- /api/capture-template ---

def test_capture_template_no_config_returns_404(client):
    r = client.post(
        "/api/capture-template",
        json={"by_path": "usb-1", "roi_id": "12", "kind": "present"},
        headers=AUTH,
    )
    assert r.status_code == 404


def test_capture_template_wrong_by_path_returns_400(client):
    _write_config(client)
    r = client.post(
        "/api/capture-template",
        json={"by_path": "wrong-cam", "roi_id": "12", "kind": "present"},
        headers=AUTH,
    )
    assert r.status_code == 400


def test_capture_template_unknown_roi_returns_404(client):
    _write_config(client)
    r = client.post(
        "/api/capture-template",
        json={"by_path": "usb-1", "roi_id": "99", "kind": "present"},
        headers=AUTH,
    )
    assert r.status_code == 404


def test_capture_template_rejects_path_traversal_roi_id(client):
    _write_config(client)
    r = client.post(
        "/api/capture-template",
        json={"by_path": "usb-1", "roi_id": "../../evil", "kind": "present"},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_capture_template_rejects_invalid_kind(client):
    _write_config(client)
    r = client.post(
        "/api/capture-template",
        json={"by_path": "usb-1", "roi_id": "12", "kind": "bogus"},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_capture_template_success_writes_file_and_updates_config(client):
    _write_config(client)
    r = client.post(
        "/api/capture-template",
        json={"by_path": "usb-1", "roi_id": "12", "kind": "present"},
        headers=AUTH,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"

    template_path = server.TEMPLATES_DIR / "12_present.png"
    assert template_path.exists()
    assert cv2.imread(str(template_path)) is not None

    saved = json.loads(server.CONFIG_PATH.read_text())
    assert saved["templates"] == [{"roi_id": "12", "kind": "present", "rel": body["template_rel_path"]}]


def test_capture_template_overwrites_existing_entry(client):
    _write_config(client)
    for _ in range(2):
        r = client.post(
            "/api/capture-template",
            json={"by_path": "usb-1", "roi_id": "12", "kind": "present"},
            headers=AUTH,
        )
        assert r.status_code == 200

    saved = json.loads(server.CONFIG_PATH.read_text())
    assert len(saved["templates"]) == 1  # second capture updates, doesn't duplicate


def test_capture_template_empty_roi_returns_400(client):
    # ROI starts entirely outside the actual frame bounds -> numpy slicing
    # clips to an empty array rather than raising.
    _write_config(client, rois=[{"id": "z", "x1": 20, "y1": 20, "x2": 30, "y2": 30}])
    FakeCap.frame_shape = (10, 10, 3)
    try:
        r = client.post(
            "/api/capture-template",
            json={"by_path": "usb-1", "roi_id": "z", "kind": "present"},
            headers=AUTH,
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        # Actionable message: names the ROI, its bounds, and the actual frame size.
        assert "'z'" in detail
        assert "(20,20)-(30,30)" in detail
        assert "10x10" in detail
    finally:
        FakeCap.frame_shape = (480, 640, 3)


# --- /api/alarm-state, /api/alarm-ack ---

def test_get_alarm_state_requires_token(client):
    r = client.get("/api/alarm-state")
    assert r.status_code == 422


def test_get_alarm_state_no_data_returns_default(client):
    r = client.get("/api/alarm-state", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"condition": None, "action": "NONE", "latched": False}


def test_get_alarm_state_reflects_written_state(client):
    runtime_state.write_alarm_state("MISLOAD", "STOP", latched=True)

    r = client.get("/api/alarm-state", headers=AUTH)

    assert r.json() == {"condition": "MISLOAD", "action": "STOP", "latched": True}


def test_post_alarm_ack_requires_token(client):
    r = client.post("/api/alarm-ack")
    assert r.status_code == 422


def test_post_alarm_ack_drops_request_flag(client):
    r = client.post("/api/alarm-ack", headers=AUTH)
    assert r.status_code == 200
    assert runtime_state.consume_ack_request() is True


# --- / (static UI) ---

def test_index_serves_setup_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "ReCap Setup" in r.text

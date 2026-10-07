import sys
from pathlib import Path

import pytest

# Add the setup directory to sys.path so we can import setup_config
sys.path.append(str(Path(__file__).parent))

from setup_config import (
    ROI, AlignmentMarker, TemplateEntry, CameraConfig, SetupConfig,
    AlarmOutput, AlarmPolicy,
    save_config, load_config, get_template_filename,
)

def test_roi_conversion():
    print("Testing ROI conversion...")
    roi = ROI.from_xywh("test_roi", 10, 20, 30, 40)
    assert roi.id == "test_roi"
    assert roi.x1 == 10
    assert roi.y1 == 20
    assert roi.x2 == 40
    assert roi.y2 == 60
    
    xywh = roi.to_xywh()
    assert xywh == (10, 20, 30, 40)
    print("  ROI conversion passed.")

def test_template_filename():
    print("Testing template filename generation...")
    assert get_template_filename("12", "present") == "12_present.png"
    assert get_template_filename("-1", "absent") == "-1_absent.png"
    print("  Template filename passed.")

def test_atomic_save_load(tmp_path):
    print(f"Testing atomic save/load in {tmp_path}...")
    config_path = tmp_path / "config.json"
    
    camera = CameraConfig(by_path="usb-1", video_index=0, resolution={"w": 1280, "h": 720})
    config = SetupConfig(
        schema_version=1,
        detector_cmd="python detector.py",
        camera=camera,
        search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        rois=[ROI(id="R1", x1=0, y1=0, x2=10, y2=10)],
        alignment=[AlignmentMarker(id="M1", x=5, y=5)],
        templates=[TemplateEntry(roi_id="R1", kind="present", rel="templates/R1_present.png")],
        alarm_outputs=[AlarmOutput(id="primary", gpio_pin=27, active_high=True)],
        alarm_policies=[AlarmPolicy(action="STOP", mode="latch", pulse_ms=300, outputs=["primary"])]
    )

    save_config(config_path, config)
    assert config_path.exists()

    loaded = load_config(config_path)
    assert loaded.schema_version == 1
    assert loaded.camera.by_path == "usb-1"
    assert len(loaded.rois) == 1
    assert loaded.rois[0].id == "R1"
    assert loaded.alignment[0].id == "M1"
    assert loaded.templates[0].kind == "present"
    assert loaded.alarm_outputs[0].gpio_pin == 27
    assert loaded.alarm_policies[0].outputs == ["primary"]
    print("  Atomic save/load passed.")

def test_validation_errors():
    print("Testing validation errors...")
    camera = CameraConfig(by_path="usb-1", video_index=0, resolution={"w": 1280, "h": 720})
    
    # Invalid ROI (x2 < x1)
    config = SetupConfig(
        schema_version=1,
        detector_cmd="python detector.py",
        camera=camera,
        search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        rois=[ROI(id="bad_roi", x1=10, y1=10, x2=5, y2=5)]
    )
    
    with pytest.raises(ValueError, match="Invalid ROI bounds"):
        config.validate()
    print("  Invalid ROI validation passed.")

    # Invalid template kind
    config = SetupConfig(
        schema_version=1,
        detector_cmd="python detector.py",
        camera=camera,
        search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        templates=[TemplateEntry(roi_id="R1", kind="invalid", rel="rel")]
    )
    
    with pytest.raises(ValueError, match="Invalid template kind"):
        config.validate()
    print("  Invalid template kind validation passed.")


def _camera():
    return CameraConfig(by_path="usb-1", video_index=0, resolution={"w": 1280, "h": 720})


def test_alarm_validation_duplicate_output_ids():
    config = SetupConfig(
        schema_version=1, detector_cmd="x", camera=_camera(), search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        alarm_outputs=[
            AlarmOutput(id="primary", gpio_pin=27),
            AlarmOutput(id="primary", gpio_pin=22),
        ],
    )
    with pytest.raises(ValueError, match="Duplicate alarm_output ids"):
        config.validate()


def test_alarm_validation_duplicate_policy_actions():
    config = SetupConfig(
        schema_version=1, detector_cmd="x", camera=_camera(), search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        alarm_outputs=[AlarmOutput(id="primary", gpio_pin=27)],
        alarm_policies=[
            AlarmPolicy(action="STOP", mode="pulse", outputs=["primary"]),
            AlarmPolicy(action="STOP", mode="latch", outputs=["primary"]),
        ],
    )
    with pytest.raises(ValueError, match="Duplicate alarm_policy actions"):
        config.validate()


def test_alarm_validation_invalid_action():
    config = SetupConfig(
        schema_version=1, detector_cmd="x", camera=_camera(), search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        alarm_policies=[AlarmPolicy(action="INVALID", mode="pulse")],
    )
    with pytest.raises(ValueError, match="Invalid alarm policy action"):
        config.validate()


def test_alarm_validation_invalid_mode():
    config = SetupConfig(
        schema_version=1, detector_cmd="x", camera=_camera(), search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        alarm_policies=[AlarmPolicy(action="STOP", mode="explode")],
    )
    with pytest.raises(ValueError, match="Invalid alarm policy mode"):
        config.validate()


def test_alarm_validation_non_positive_pulse_ms():
    config = SetupConfig(
        schema_version=1, detector_cmd="x", camera=_camera(), search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        alarm_policies=[AlarmPolicy(action="WARN", mode="pulse", pulse_ms=0)],
    )
    with pytest.raises(ValueError, match="pulse_ms must be positive"):
        config.validate()


def test_alarm_validation_unknown_output_reference():
    config = SetupConfig(
        schema_version=1, detector_cmd="x", camera=_camera(), search_padding=20,
        created_at="2026-08-31T00:00:00Z",
        alarm_outputs=[AlarmOutput(id="primary", gpio_pin=27)],
        alarm_policies=[AlarmPolicy(action="STOP", mode="latch", outputs=["nonexistent"])],
    )
    with pytest.raises(ValueError, match="unknown output id"):
        config.validate()


def test_alarm_defaults_to_empty():
    config = SetupConfig(
        schema_version=1, detector_cmd="x", camera=_camera(), search_padding=20,
        created_at="2026-08-31T00:00:00Z",
    )
    config.validate()  # no alarm config at all must be valid
    assert config.alarm_outputs == []
    assert config.alarm_policies == []

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Tuple


@dataclass
class ROI:
    id: str
    x1: int
    y1: int
    x2: int
    y2: int

    def to_xywh(self) -> Tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2 - self.x1, self.y2 - self.y1

    @classmethod
    def from_xywh(cls, roi_id: str, x: int, y: int, w: int, h: int) -> ROI:
        return cls(id=roi_id, x1=x, y1=y, x2=x + w, y2=y + h)


@dataclass
class AlignmentMarker:
    id: str
    x: int
    y: int


@dataclass
class TemplateEntry:
    roi_id: str
    kind: str  # "present" or "absent"
    rel: str   # relative path to the template file


@dataclass
class CameraConfig:
    by_path: str
    video_index: int
    resolution: Dict[str, int]  # {"w": 1280, "h": 720}


@dataclass
class AlarmOutput:
    id: str
    gpio_pin: int
    active_high: bool = True  # True: drive HIGH to engage; False: drive LOW


@dataclass
class AlarmPolicy:
    action: str  # "WARN" or "STOP" — matches detector_v3's analyze_frame() action field
    mode: str    # "pulse" or "latch"
    pulse_ms: int = 300  # used when mode == "pulse"
    outputs: List[str] = field(default_factory=list)  # AlarmOutput ids to fire


@dataclass
class SetupConfig:
    schema_version: int
    detector_cmd: str
    camera: CameraConfig
    search_padding: int
    created_at: str
    rois: List[ROI] = field(default_factory=list)
    alignment: List[AlignmentMarker] = field(default_factory=list)
    templates: List[TemplateEntry] = field(default_factory=list)
    alarm_outputs: List[AlarmOutput] = field(default_factory=list)
    alarm_policies: List[AlarmPolicy] = field(default_factory=list)

    def validate(self):
        """Basic validation of the configuration."""
        if self.schema_version < 1:
            raise ValueError("Unsupported schema version")

        for roi in self.rois:
            if roi.x2 <= roi.x1 or roi.y2 <= roi.y1:
                raise ValueError(f"Invalid ROI bounds for {roi.id}: ({roi.x1},{roi.y1}) to ({roi.x2},{roi.y2})")

        for tmpl in self.templates:
            if tmpl.kind not in ("present", "absent"):
                raise ValueError(f"Invalid template kind: {tmpl.kind}")
            if tmpl.roi_id not in [r.id for r in self.rois]:
                 # We might allow it if it's a future ROI, but for now let's be strict
                 pass

        output_ids = [o.id for o in self.alarm_outputs]
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("Duplicate alarm_output ids")

        policy_actions = [p.action for p in self.alarm_policies]
        if len(policy_actions) != len(set(policy_actions)):
            raise ValueError("Duplicate alarm_policy actions")

        for policy in self.alarm_policies:
            if policy.action not in ("WARN", "STOP"):
                raise ValueError(f"Invalid alarm policy action: {policy.action}")
            if policy.mode not in ("pulse", "latch"):
                raise ValueError(f"Invalid alarm policy mode: {policy.mode}")
            if policy.pulse_ms <= 0:
                raise ValueError(f"alarm policy pulse_ms must be positive: {policy.pulse_ms}")
            for output_id in policy.outputs:
                if output_id not in output_ids:
                    raise ValueError(f"Alarm policy references unknown output id: {output_id}")

    @classmethod
    def from_dict(cls, d: dict) -> SetupConfig:
        """Converts a dictionary to a SetupConfig object."""
        camera = CameraConfig(**d["camera"])
        rois = [ROI(**r) for r in d.get("rois", [])]
        alignment = [AlignmentMarker(**a) for a in d.get("alignment", [])]
        templates = [TemplateEntry(**t) for t in d.get("templates", [])]
        alarm_outputs = [AlarmOutput(**o) for o in d.get("alarm_outputs", [])]
        alarm_policies = [AlarmPolicy(**p) for p in d.get("alarm_policies", [])]

        return cls(
            schema_version=d["schema_version"],
            detector_cmd=d["detector_cmd"],
            camera=camera,
            search_padding=d["search_padding"],
            created_at=d["created_at"],
            rois=rois,
            alignment=alignment,
            templates=templates,
            alarm_outputs=alarm_outputs,
            alarm_policies=alarm_policies
        )

    def to_dict(self) -> dict:
        """Converts the SetupConfig object to a dictionary."""
        return asdict(self)


def get_template_filename(roi_id: str, kind: str) -> str:
    """Returns the canonical filename for a template."""
    return f"{roi_id}_{kind}.png"


def load_config(path: Path) -> SetupConfig:
    """Loads the configuration from a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found at {path}")
    
    with open(path, "r") as f:
        data = json.load(f)
    
    config = SetupConfig.from_dict(data)
    config.validate()
    return config


def save_config(path: Path, config: SetupConfig):
    """Saves the configuration to a JSON file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w") as f:
            json.dump(config.to_dict(), f, indent=2)
        
        # Atomic rename
        os.replace(temp_path, path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise e

if __name__ == "__main__":
    # Quick test of the logic
    test_path = Path("test_config.json")
    test_config = SetupConfig(
        schema_version=1,
        detector_cmd="python detector.py",
        camera=CameraConfig(by_path="usb-1", video_index=0, resolution={"w": 1280, "h": 720}),
        search_padding=20,
        created_at=datetime.now(timezone.utc).isoformat(),
        rois=[ROI.from_xywh("-1", 10, 10, 50, 50)],
        templates=[TemplateEntry(" -1", "present", "templates/-1_present.png")]
    )
    
    print("Saving test config...")
    save_config(test_path, test_config)
    print("Loading test config...")
    loaded = load_config(test_path)
    print(f"Loaded ROI: {loaded.rois[0]}")
    
    assert loaded.rois[0].id == "-1"
    assert loaded.rois[0].x2 == 60
    
    print("Test passed!")
    test_path.unlink()

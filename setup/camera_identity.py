import subprocess
import json
import sys
from pathlib import Path
from typing import Dict, Any

# audit_paths.py --list --json inspects USB/sysfs topology only — it never
# opens the device, so it can't report resolution. These are just a
# starting point for the setup UI; the operator sets the real values there.
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


class CameraIdentityResolver:
    def __init__(self, audit_script_path: Path):
        self.audit_script_path = audit_script_path

    def list_cameras(self) -> Dict[str, Any]:
        if not self.audit_script_path.exists():
            return {'error': f'Audit script not found at {self.audit_script_path}'}

        try:
            result = subprocess.run(
                [sys.executable, str(self.audit_script_path), '--list', '--json'],
                capture_output=True,
                text=True,
                check=True
            )
            raw_data = json.loads(result.stdout)
            return self._process_raw_data(raw_data)
        except subprocess.CalledProcessError as e:
            return {'error': f'Audit script failed: {e.stderr}'}
        except json.JSONDecodeError:
            return {'error': 'Failed to parse audit script JSON output'}
        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}'}

    def _process_raw_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        processed_cameras = []
        raw_cameras = data.get('cameras', {})
        duplicate_serials = data.get('duplicate_serials', [])

        for port, info in raw_cameras.items():
            # audit_paths.py merges identity() fields directly into each
            # camera's dict (serial included) — there's no nested 'identity'
            # key. 'nodes'/'by_path' are dicts keyed by v4l index (as
            # strings, since they went through JSON).
            serial = info.get('serial')
            is_duplicate = serial in duplicate_serials if serial else False

            nodes = info.get('nodes') or {}
            by_path = info.get('by_path') or {}
            # `nodes` is keyed by the udev by-path index label ("0"/"1"),
            # not the real /dev/videoN minor number — the lower label is
            # the capture node (the higher one is UVC metadata), same rule
            # as Camera.capture_index in audit_paths.py. The dict *value*
            # (e.g. "/dev/video1") holds the actual device path; video_index
            # must come from that, not from the label, since they diverge
            # whenever the camera doesn't happen to enumerate at video0.
            capture_key = min(nodes, key=int, default=None)
            capture_node_path = nodes.get(capture_key) if capture_key is not None else None
            capture_index = int(capture_node_path.rsplit('video', 1)[-1]) if capture_node_path else None
            capture_by_path = by_path.get(capture_key) if capture_key is not None else None

            processed_cameras.append({
                'port': port,
                'by_path': capture_by_path,
                'video_index': capture_index,
                'w': DEFAULT_WIDTH,
                'h': DEFAULT_HEIGHT,
                'serial': serial,
                'duplicate': is_duplicate
            })

        return {
            'cameras': processed_cameras,
            'duplicate_serial_groups': duplicate_serials
        }

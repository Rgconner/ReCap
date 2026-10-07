"""On-disk alarm status shared between the detection runtime (main.py,
alerts.py) and the setup app's UI.

Same-filesystem, same-Pi assumption as config.json (see main.py's module
docstring) — the runtime writes these files, the setup app's HTTP
endpoints read/write them, no network hop or shared process needed.
"""
import json
from pathlib import Path

STATE_DIR = Path(__file__).parent / "setup_state"
ALARM_STATE_PATH = STATE_DIR / "alarm_state.json"
ACK_REQUEST_PATH = STATE_DIR / "ack_request.flag"


def write_alarm_state(condition: str, action: str, latched: bool) -> None:
    """Called by the runtime after every detection result and every ack."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ALARM_STATE_PATH.write_text(json.dumps({
        "condition": condition,
        "action": action,
        "latched": latched,
    }))


def read_alarm_state() -> dict:
    """Called by the setup app to serve GET /api/alarm-state."""
    if not ALARM_STATE_PATH.exists():
        return {"condition": None, "action": "NONE", "latched": False}
    return json.loads(ALARM_STATE_PATH.read_text())


def request_ack() -> None:
    """Called by the setup app on POST /api/alarm-ack. Just drops a flag
    file — the runtime's idle loop picks it up on its next poll."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ACK_REQUEST_PATH.touch()


def consume_ack_request() -> bool:
    """Called by the runtime's idle loop. True (and clears the flag) if an
    ack was requested since the last check."""
    if ACK_REQUEST_PATH.exists():
        ACK_REQUEST_PATH.unlink()
        return True
    return False

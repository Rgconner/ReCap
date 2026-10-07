"""Alert output for detection results.

Logs every result (console + an optional rotating file via
configure_logging()), and — if configure_alarm() was called — drives the
configured GPIO alarm outputs via alarm.AlarmController. handle_result() is
the single place main.py calls after each detection, so main.py's call
site doesn't change regardless of what's wired up behind it.

Also mirrors current alarm status out to runtime_state's shared status
file, so the setup app's UI can show it without talking to this process
directly.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "setup"))
from runtime_state import write_alarm_state  # noqa: E402

logger = logging.getLogger("recap.s1.alerts")

_alarm_controller = None
_last_condition = None
_last_action = "NONE"


def configure_alarm(controller) -> None:
    """Registers the AlarmController handle_result() drives. Call once at
    startup, only if alarm outputs are configured."""
    global _alarm_controller
    _alarm_controller = controller


def configure_logging(log_dir) -> None:
    """Adds console + rotating file handlers. Call once at startup."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(console)

    file_handler = RotatingFileHandler(log_dir / "alerts.log", maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(file_handler)


def handle_result(result: dict) -> None:
    """Logs a detection result. `action` is one of NONE/WARN/STOP (see
    detector_v3.TemplateMatcher.analyze_frame)."""
    global _last_condition, _last_action
    condition = result.get("condition", "UNKNOWN")
    action = result.get("action", "NONE")
    _last_condition = condition
    _last_action = action

    if action == "STOP":
        logger.warning("STOP REQUIRED — condition=%s", condition)
    elif action == "WARN":
        logger.warning("WARNING — condition=%s", condition)
    else:
        logger.info("OK — condition=%s", condition)

    if _alarm_controller:
        _alarm_controller.trigger(action)
        write_alarm_state(condition, action, latched=_alarm_controller.any_latched())


def run_detection_cycle(detector, frame) -> dict:
    """Runs detector.analyze_frame(frame) and reports it via handle_result().

    If analyze_frame() itself throws — bad config, a corrupt template,
    anything unanticipated — that must not mean detection silently does
    nothing this cycle (main.py previously just printed and moved on,
    forever, with no STOP). Failing safe here means treating "detection is
    broken" the same as the worst real condition it could report.
    """
    try:
        result = detector.analyze_frame(frame)
    except Exception as e:
        logger.error("Detection failed: %s — failing safe to STOP", e)
        result = {"condition": "DETECTION_ERROR", "action": "STOP"}
    handle_result(result)
    return result


def handle_ack() -> None:
    """Releases any latched alarm outputs. Wired to the physical
    acknowledge button (main.py's GPIO callback) and to the setup app's
    "Clear" button (via runtime_state's ack-request flag). No-op if no
    alarm controller is configured."""
    logger.info("ALARM ACKNOWLEDGED — clearing latched outputs")
    if _alarm_controller:
        _alarm_controller.clear()
        write_alarm_state(_last_condition, _last_action, latched=False)

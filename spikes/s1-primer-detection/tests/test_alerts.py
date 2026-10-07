"""Tests for alerts.py's log-based alert handler."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "setup"))

import alerts
import runtime_state


@pytest.fixture(autouse=True)
def reset_alarm_controller():
    """_alarm_controller/_last_condition/_last_action are module-level
    state — isolate tests from each other regardless of run order."""
    alerts._alarm_controller = None
    alerts._last_condition = None
    alerts._last_action = "NONE"
    yield
    alerts._alarm_controller = None
    alerts._last_condition = None
    alerts._last_action = "NONE"


@pytest.fixture(autouse=True)
def isolate_runtime_state(tmp_path, monkeypatch):
    """alerts.py writes real files via runtime_state — point those at a
    tmp dir so tests never touch the repo's setup_state/."""
    monkeypatch.setattr(runtime_state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(runtime_state, "ALARM_STATE_PATH", tmp_path / "alarm_state.json")
    monkeypatch.setattr(runtime_state, "ACK_REQUEST_PATH", tmp_path / "ack_request.flag")


def test_stop_action_logs_warning(caplog):
    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        alerts.handle_result({"condition": "MISLOAD", "action": "STOP"})
    assert "STOP REQUIRED" in caplog.text
    assert "MISLOAD" in caplog.text


def test_warn_action_logs_warning(caplog):
    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        alerts.handle_result({"condition": "ABOUT_TO_FAIL", "action": "WARN"})
    assert "WARNING" in caplog.text
    assert "ABOUT_TO_FAIL" in caplog.text


def test_none_action_logs_info(caplog):
    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        alerts.handle_result({"condition": "OK", "action": "NONE"})
    assert "OK" in caplog.text
    assert caplog.records[-1].levelno == logging.INFO


def test_missing_fields_default_gracefully(caplog):
    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        alerts.handle_result({})
    assert "UNKNOWN" in caplog.text


def test_no_alarm_controller_configured_is_noop(caplog):
    """Today's behavior (no S4 hardware configured yet) must keep working
    unchanged — handle_result() must not require an alarm controller."""
    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        alerts.handle_result({"condition": "OK", "action": "NONE"})
    assert "OK" in caplog.text


def _mock_controller(latched=False):
    controller = MagicMock()
    controller.any_latched.return_value = latched
    return controller


def test_configure_alarm_triggers_controller_with_action():
    controller = _mock_controller()
    alerts.configure_alarm(controller)

    alerts.handle_result({"condition": "MISLOAD", "action": "STOP"})

    controller.trigger.assert_called_once_with("STOP")


def test_configure_alarm_forwards_none_action_too():
    """Even a NONE action reaches the controller — trigger() itself decides
    whether that action has a policy configured."""
    controller = _mock_controller()
    alerts.configure_alarm(controller)

    alerts.handle_result({"condition": "OK", "action": "NONE"})

    controller.trigger.assert_called_once_with("NONE")


def test_handle_result_writes_alarm_state(monkeypatch):
    written = {}
    monkeypatch.setattr(
        alerts, "write_alarm_state",
        lambda condition, action, latched: written.update(
            condition=condition, action=action, latched=latched
        ),
    )
    alerts.configure_alarm(_mock_controller(latched=True))

    alerts.handle_result({"condition": "MISLOAD", "action": "STOP"})

    assert written == {"condition": "MISLOAD", "action": "STOP", "latched": True}


def test_handle_result_no_controller_does_not_write_state(monkeypatch):
    called = []
    monkeypatch.setattr(alerts, "write_alarm_state", lambda *a, **k: called.append((a, k)))

    alerts.handle_result({"condition": "OK", "action": "NONE"})

    assert called == []


def test_run_detection_cycle_reports_normal_result():
    detector = MagicMock()
    detector.analyze_frame.return_value = {"condition": "OK", "action": "NONE"}

    result = alerts.run_detection_cycle(detector, frame="fake-frame")

    detector.analyze_frame.assert_called_once_with("fake-frame")
    assert result == {"condition": "OK", "action": "NONE"}


def test_run_detection_cycle_fails_safe_to_stop_when_detector_raises(caplog):
    """Regression for C12: if analyze_frame() throws, main.py must not just
    log and move on with no alarm — that leaves the press with detection
    silently dead and never a software STOP."""
    detector = MagicMock()
    detector.analyze_frame.side_effect = ValueError("Config is missing required ROI(s)")
    controller = _mock_controller()
    alerts.configure_alarm(controller)

    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        result = alerts.run_detection_cycle(detector, frame="fake-frame")

    assert result == {"condition": "DETECTION_ERROR", "action": "STOP"}
    controller.trigger.assert_called_once_with("STOP")
    assert "STOP REQUIRED" in caplog.text
    assert "DETECTION_ERROR" in caplog.text


def test_handle_ack_clears_configured_controller():
    controller = _mock_controller()
    alerts.configure_alarm(controller)

    alerts.handle_ack()

    controller.clear.assert_called_once_with()


def test_handle_ack_writes_cleared_state_with_last_condition(monkeypatch):
    written = {}
    monkeypatch.setattr(
        alerts, "write_alarm_state",
        lambda condition, action, latched: written.update(
            condition=condition, action=action, latched=latched
        ),
    )
    alerts.configure_alarm(_mock_controller(latched=True))
    alerts.handle_result({"condition": "MISLOAD", "action": "STOP"})

    alerts.handle_ack()

    assert written == {"condition": "MISLOAD", "action": "STOP", "latched": False}


def test_handle_ack_logs(caplog):
    controller = _mock_controller()
    alerts.configure_alarm(controller)

    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        alerts.handle_ack()

    assert "ACKNOWLEDGED" in caplog.text


def test_handle_ack_no_alarm_controller_configured_is_noop(caplog):
    """Must not raise when no alarm hardware is configured — mirrors
    handle_result()'s no-controller behavior."""
    with caplog.at_level(logging.INFO, logger="recap.s1.alerts"):
        alerts.handle_ack()
    assert "ACKNOWLEDGED" in caplog.text

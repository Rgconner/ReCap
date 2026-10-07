"""Tests for alarm.py's AlarmController, against a mocked GPIO module —
no real hardware needed."""
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alarm import AlarmController


def _output(id_, gpio_pin, active_high=True):
    return SimpleNamespace(id=id_, gpio_pin=gpio_pin, active_high=active_high)


def _policy(action, mode, pulse_ms=300, outputs=None):
    return SimpleNamespace(action=action, mode=mode, pulse_ms=pulse_ms, outputs=outputs or [])


def _fake_gpio():
    gpio = MagicMock()
    gpio.OUT = "OUT"
    gpio.HIGH = 1
    gpio.LOW = 0
    return gpio


def test_init_sets_up_each_output_idle():
    gpio = _fake_gpio()
    AlarmController(gpio, [_output("a", 27), _output("b", 22, active_high=False)], [])
    gpio.setup.assert_any_call(27, "OUT", initial=0)  # active_high=True -> idle is LOW
    gpio.setup.assert_any_call(22, "OUT", initial=1)  # active_high=False -> idle is HIGH


def test_trigger_with_no_matching_policy_is_noop():
    gpio = _fake_gpio()
    controller = AlarmController(gpio, [_output("a", 27)], [])
    gpio.output.reset_mock()
    controller.trigger("STOP")
    gpio.output.assert_not_called()


def test_trigger_pulse_engages_then_releases():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio, [_output("a", 27)], [_policy("STOP", "pulse", pulse_ms=20, outputs=["a"])]
    )
    gpio.output.reset_mock()

    controller.trigger("STOP")
    gpio.output.assert_called_with(27, 1)  # engaged = HIGH (active_high default True)

    time.sleep(0.06)
    gpio.output.assert_called_with(27, 0)  # released back to idle after pulse_ms


def test_trigger_latch_stays_engaged_until_clear():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio, [_output("a", 27)], [_policy("STOP", "latch", outputs=["a"])]
    )
    gpio.output.reset_mock()

    controller.trigger("STOP")
    gpio.output.assert_called_with(27, 1)

    time.sleep(0.05)
    gpio.output.assert_called_with(27, 1)  # still engaged — nothing releases a latch on its own

    controller.clear()
    gpio.output.assert_called_with(27, 0)


def test_any_latched_reflects_latch_state():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio, [_output("a", 27)], [_policy("STOP", "latch", outputs=["a"])]
    )
    assert controller.any_latched() is False

    controller.trigger("STOP")
    assert controller.any_latched() is True

    controller.clear()
    assert controller.any_latched() is False


def test_any_latched_false_for_pulse_only():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio, [_output("a", 27)], [_policy("WARN", "pulse", pulse_ms=20, outputs=["a"])]
    )
    controller.trigger("WARN")
    assert controller.any_latched() is False


def test_clear_specific_output_only():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio,
        [_output("a", 27), _output("b", 22)],
        [_policy("STOP", "latch", outputs=["a", "b"])],
    )
    controller.trigger("STOP")
    gpio.output.reset_mock()

    controller.clear("a")

    gpio.output.assert_called_once_with(27, 0)  # only a released
    assert "a" not in controller._latched
    assert "b" in controller._latched  # b left engaged


def test_multiple_outputs_for_one_policy():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio,
        [_output("a", 27), _output("b", 22)],
        [_policy("WARN", "latch", outputs=["a", "b"])],
    )
    controller.trigger("WARN")
    gpio.output.assert_any_call(27, 1)
    gpio.output.assert_any_call(22, 1)


def test_unknown_output_id_in_policy_is_skipped():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio, [_output("a", 27)], [_policy("STOP", "latch", outputs=["a", "ghost"])]
    )
    controller.trigger("STOP")  # must not raise for the unconfigured "ghost" id
    gpio.output.assert_called_with(27, 1)


def test_test_pulse_bypasses_policy_lookup():
    gpio = _fake_gpio()
    controller = AlarmController(gpio, [_output("a", 27)], [])
    gpio.output.reset_mock()
    controller.test_pulse("a", pulse_ms=20)
    gpio.output.assert_called_with(27, 1)
    time.sleep(0.06)
    gpio.output.assert_called_with(27, 0)


def test_test_pulse_unknown_output_raises_keyerror():
    gpio = _fake_gpio()
    controller = AlarmController(gpio, [_output("a", 27)], [])
    try:
        controller.test_pulse("nonexistent")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_latch_cancels_a_pending_pulse_on_the_same_output():
    """Regression for C10: a WARN pulse followed by a STOP latch on the same
    output must not let the pulse's timer fire later and release the pin
    out from under the latch."""
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio,
        [_output("a", 27)],
        [
            _policy("WARN", "pulse", pulse_ms=20, outputs=["a"]),
            _policy("STOP", "latch", outputs=["a"]),
        ],
    )

    controller.trigger("WARN")  # schedules a release in 20ms
    controller.trigger("STOP")  # should cancel that pending release
    gpio.output.reset_mock()

    time.sleep(0.06)  # long past the pulse's 20ms

    gpio.output.assert_not_called()  # nothing released the pin behind the latch
    assert controller.any_latched() is True


def test_cleanup_cancels_timers_and_releases_all():
    gpio = _fake_gpio()
    controller = AlarmController(
        gpio,
        [_output("a", 27), _output("b", 22)],
        [_policy("STOP", "latch", outputs=["a"]), _policy("WARN", "pulse", pulse_ms=5000, outputs=["b"])],
    )
    controller.trigger("STOP")
    controller.trigger("WARN")
    gpio.output.reset_mock()

    controller.cleanup()

    gpio.output.assert_any_call(27, 0)
    gpio.output.assert_any_call(22, 0)
    # the long pending pulse timer must be cancelled, not left to fire later
    assert all(t.finished.is_set() for t in controller._timers.values())

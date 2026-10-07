#!/usr/bin/env python3
"""ReCap S1 primer-detection runtime.

Reads the camera/ROI/template config produced by the setup app (setup/)
and runs the GPIO-triggered detection loop against the physical press.
Replaces the old integration_test.py, which hardcoded all of this.

Deployment assumption: this and the setup app run on the same Pi, sharing
a filesystem — config lives at setup/setup_state/config.json, captured
templates at setup/setup_state/templates/.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "setup"))

from runtime_state import consume_ack_request
from setup_config import load_config

from alarm import AlarmController
from alerts import configure_alarm, configure_logging, handle_ack, run_detection_cycle
from alignment import AlignmentChecker
from camera import StaleFrameError, read_latest_frame
from config_adapter import build_expected_markers, build_rois, build_template_names
from detector_v3 import TemplateMatcher

REPO_ROOT = Path(__file__).resolve().parents[3]
SETUP_DIR = REPO_ROOT / "setup"
CONFIG_PATH = SETUP_DIR / "setup_state" / "config.json"
TEMPLATE_DIR = SETUP_DIR / "setup_state" / "templates"
CAPTURES_DIR = REPO_ROOT / "captures"
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"

TRIGGER_PIN = 17
ACK_BUTTON_PIN = 24  # momentary switch to ground, internal pull-up
ALIGNMENT_THRESHOLD = 50  # pixels
CHECK_INTERVAL = 10  # re-check alignment every N triggers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-alarm", metavar="OUTPUT_ID",
        help="Fire one configured alarm output once and exit — for hardware bring-up.",
    )
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        print(f"ERROR: No config found at {CONFIG_PATH}. Run the setup app first.")
        sys.exit(1)

    config = load_config(CONFIG_PATH)

    import RPi.GPIO as GPIO

    if args.test_alarm:
        GPIO.setmode(GPIO.BCM)
        controller = AlarmController(GPIO, config.alarm_outputs, config.alarm_policies)
        try:
            controller.test_pulse(args.test_alarm)
        except KeyError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        time.sleep(1)  # let the pulse complete before releasing GPIO
        controller.cleanup()
        GPIO.cleanup()
        return

    configure_logging(LOG_DIR)

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TRIGGER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Camera access goes through camera.py's broker (see its module
    # docstring) -- this process never opens cv2.VideoCapture itself, so it
    # can't contend with the setup app for the same device, and always gets
    # whatever the broker most recently read rather than a buffered-stale
    # frame off its own cold cv2.VideoCapture.

    # Never mutated: alignment.check_and_correct() must always measure drift
    # relative to these original calibrated boxes, not the last corrected
    # detector.rois, or the offset compounds every check (C3).
    base_rois = build_rois(config)

    detector = TemplateMatcher(
        str(TEMPLATE_DIR),
        rois=base_rois,
        template_names=build_template_names(config),
    )
    try:
        detector.validate_ready()
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    alignment = AlignmentChecker(build_expected_markers(config), ALIGNMENT_THRESHOLD)

    trigger_count = 0
    ack_requested = False

    # Both GPIO callbacks below only set a flag/counter — camera I/O,
    # detection, and AlarmController access all happen on the main thread's
    # loop instead (C9). RPi.GPIO runs callbacks on its own thread, which
    # isn't a safe place for OpenCV work and would otherwise race with the
    # ack button callback and the idle loop's own ack polling over the same
    # AlarmController state (no lock protects it).
    def on_tdc_reached(channel):
        nonlocal trigger_count
        trigger_count += 1

    def on_ack_button(channel):
        nonlocal ack_requested
        ack_requested = True

    def process_trigger(trigger_num):
        print(f"\n--- Trigger #{trigger_num} ---")

        try:
            frame = read_latest_frame()
        except (FileNotFoundError, StaleFrameError) as e:
            print(f"ERROR: {e}")
            return

        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        save_path = CAPTURES_DIR / f"trigger_{trigger_num:03d}_{timestamp}.png"
        cv2.imwrite(str(save_path), frame)
        print(f"Saved: {save_path}")

        if trigger_num % CHECK_INTERVAL == 1:
            detector.rois = alignment.check_and_correct(frame, base_rois)

        run_detection_cycle(detector, frame)

    alarm_controller = None
    if config.alarm_outputs:
        alarm_controller = AlarmController(GPIO, config.alarm_outputs, config.alarm_policies)
        configure_alarm(alarm_controller)

        GPIO.setup(ACK_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(ACK_BUTTON_PIN, GPIO.FALLING, callback=on_ack_button, bouncetime=300)

    GPIO.add_event_detect(TRIGGER_PIN, GPIO.FALLING, callback=on_tdc_reached, bouncetime=200)

    print("=== Primer Detection System ===")
    print(f"Trigger: GPIO {TRIGGER_PIN} (falling edge = TDC)")
    if alarm_controller:
        print(f"Ack button: GPIO {ACK_BUTTON_PIN} (falling edge = clear latched alarms)")
    print(f"Camera: {config.camera.by_path} (via camera.py broker)")
    print(f"Alignment check: every {CHECK_INTERVAL} triggers")
    print("Running startup alignment check...")
    try:
        frame = read_latest_frame()
        detector.rois = alignment.check_and_correct(frame, base_rois)
    except (FileNotFoundError, StaleFrameError) as e:
        print(f"WARNING: Could not capture frame for startup alignment: {e}")

    print("\nWaiting for triggers... (Ctrl+C to exit)")
    processed_count = 0
    try:
        while True:
            # Poll fast (not the old 1s idle-loop cadence) — the operator is
            # pacing the press by hand, and a trigger now waits on this loop
            # to notice it rather than running straight off the GPIO edge.
            if trigger_count > processed_count:
                processed_count += 1
                process_trigger(processed_count)

            if ack_requested:
                ack_requested = False
                handle_ack()

            if alarm_controller:
                try:
                    if consume_ack_request():
                        handle_ack()
                except Exception as e:
                    print(f"ERROR: Ack check failed: {e}")

            time.sleep(0.05)
    except KeyboardInterrupt:
        print(f"\n\nShutting down. Total triggers: {trigger_count}")
    finally:
        if alarm_controller:
            alarm_controller.cleanup()
        GPIO.cleanup()
        print("Cleanup complete.")


if __name__ == "__main__":
    main()

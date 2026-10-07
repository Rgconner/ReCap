> **Project:** ReCap — Visual QA inspection for progressive reloading presses
> **Target:** Frankford Arsenal X-10 (10-station), extensible to other presses
> **Platform:** Raspberry Pi Zero 2 W + borehole USB cameras
> **Date:** 2026-08-24
> **Status:** Research phase — no code written yet

---

## 1. Project Summary
ReCap provides automated visual inspection of ammunition reloading press stations to
detect missing or incorrect components before they become dangerous failures. The system
is mounted on a Frankford Arsenal X-10 (10-station) press, but is designed to be extensible
to other presses via a standard mount and configuration file.

## 2. Target Platform
| Component | Selection | Rationale |
|---|---|---|
| Compute | Raspberry Pi Zero 2 W | $15, quad A53, 512MB RAM. Proven on similar CV workloads (picker-vision pi-node). |
| Cameras | USB borehole/endoscope | ~$15-25 each. Built-in ring light. Narrow diameter for die-mounted inspection. |
| OS | Raspberry Pi OS Lite (64-bit) | Lightweight, stable USB stack, V4L2 support. |
| CV stack | Python 3.11 + OpenCV 4.8+ | Pre-built ARM64 wheels. No compilation needed. |
| Cycle trigger | 3D printer end-stop switch | Wired to GPIO. Mechanical, reliable, $1. |
| Alarm integration | 2.5mm jack → Pi relay/transistor | X-10 has built-in alarm (8 jacks). Pi shorts the connection to trigger. |
| Network | Wi-Fi (onboard) | PC companion connects over LAN. Pi operates standalone if PC is offline. |

## 3. Architecture Decisions
1. Hybrid camera identity — USB path symlinks + scene verification (QR code) for robustness.
2. QR code triple-purpose — setup ID, TDC confirmation, alignment check.
3. Open-core licensing — Pi software Apache 2.0, PC companion commercial.
4. No cloud dependency — all processing and QA decisions happen on-device.
5. Modular spike structure — each research spike (S0, S1, etc.) produces a standalone demo or proof of concept.

## 4. Research Spikes (Phase 0)
### S0: USB camera path stability validation on Pi Zero 2
Goal: Confirm that /dev/videoX paths remain stable across reboots, and that symlinks correctly track the physical camera.
Metrics: Reboot count, path resolution time, symlink resolution success rate.
Deliverable: Script that validates camera path stability; documentation of any workarounds.
Status: Harness ready — see `spikes/s0-camera-path-stability/` (hardware run pending).

### S1: Primer presence detection (via powder station crescent shadow analysis)
Goal: Detect missing/incorrect primer using shadow geometry from borehole camera.
Metrics: False positive/negative rates, detection latency, robustness to lighting variations.
Deliverable: CNN/shadow-analysis model; integration script with cycle trigger.

### S2: QR code alignment verification
Goal: Use QR code on press die to verify camera alignment and setup ID before each cycle.
Metrics: Alignment accuracy, QR decode success rate, time overhead.
Deliverable: QR verification module with fallback behavior.

### S3: End-stop switch reliability under press vibration
Goal: Ensure the 3D printer end-stop reliably detects press cycle start even with mechanical vibration.
Metrics: Missed cycle rate, debounce timing, failure modes.
Deliverable: Debounce algorithm; mechanical mounting guide.

### S4: Alarm integration via relay on Pi
Goal: Verify that the Pi can reliably short the alarm jack to trigger the X-10 alarm on detection.
Metrics: Signal rise time, GPIO drive strength, debounce.
Deliverable: GPIO control script; safety interlock documentation.

### S5: Network connectivity for PC companion (LAN)
Goal: Confirm stable Wi-Fi connection between Pi and PC companion for status/logs.
Metrics: Packet loss, latency, reconnection time.
Deliverable: Network status monitoring script; fallback logging.

### S6: Power stability for borehole cameras + Pi
Goal: Validate that the USB cameras and Pi have sufficient power on a 5V supply.
Metrics: Voltage drop, camera reset rate, Pi stability.
Deliverable: Power budget analysis; recommended PSU spec.

## 5. Preliminary Bill of Materials (BOM)
| Qty | Item | Part # / Link | Est. Cost (USD) | Notes |
|---|---|---|---|---|
| 1 | Raspberry Pi Zero 2 W | RPZ2W | 15.00 | Include heatsink, case |
| 1 | Raspberry Pi OS Lite (64-bit) | — | 0.00 | Download |
| 10 | USB borehole endoscope camera | generic 2MP USB endoscope | 20.00 each | ~$200 total for 10 |
| 10 | 3D printer end-stop switches | generic normally-open | 1.00 each | Wired to GPIO |
| 1 | Relay module (Pi-compatible) | 5V 2-channel relay | 8.00 | For alarm integration |
| 1 | 5V 3A power supply | — | 12.00 | For Pi + cameras |
| 1 | Micro-USB cables, GPIO breakouts | — | 10.00 | Wiring |
| — | Misc. (enclosure, mounting hardware) | — | 30.00 | Custom mount for press |
| **Total (est.)** | | | **~$285.00** |

## 6. Open Questions
1. Camera mounting method for X-10 die — How to securely attach borehole cameras to the die without interfering with the press cycle?
2. QR code placement and readability — Should the QR code be printed on the die, on a removable plate, or on the press frame?
3. Cycle timing precision — What is the actual cycle time of the X-10? Does it vary significantly between stations?
4. False positive rate tolerance — What is an acceptable false positive rate for primer detection? Is a 1% false positive acceptable given safety implications?
5. Power budget with 10 cameras — Will a single 5V 3A supply handle 10 cameras simultaneously? Do we need a powered USB hub?
6. Licensing boundaries — Exactly which parts of the Pi software will be Apache 2.0 vs. which will be commercial?
7. PC companion app architecture — Should it be a simple Electron app, a Qt app, or something else?

## 7. Phase 1 Preview (Post-Phase 0)
After Phase 0 spikes are complete:
- Integrate S1 (primer detection) as the core QA loop.
- Build the PC companion app to display live camera feeds and QA status.
- Implement full cycle: QR verification → primer detection → cycle start → alarm on failure.
- Deploy to physical X-10 press for field testing.
- Iterate based on field results.

## 8. Revision History
| Rev | Date | Author | Description |
|---|---|---|---|
| 0.1 | 2026-08-24 | ReCap Team | Initial research plan draft; Phase 0 spike definitions. |
| 0.2 | 2026-08-27 | ReCap Team | Added S0 spike harness reference and status. |

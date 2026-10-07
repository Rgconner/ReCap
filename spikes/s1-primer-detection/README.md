# Spike S1 — Primer presence detection

> **Status:** template-matching detector implemented and unit-tested;
> config-driven runtime (`main.py`) wired to the setup app's config —
> hardware run on the physical X-10 still pending.

**Goal** (phase-0 plan §S1): Detect missing/incorrect primer (and brass
presence at the adjacent stations) using the borehole cameras.

**Approach (current):** `detector_v3.py`'s `TemplateMatcher` captures a frame
per GPIO trigger and does present/absent template matching per configured
ROI, driven by `main.py`. ROIs, the camera identity, templates, and
alignment markers all come from the config the [setup app](../../setup/)
produces — see `config_adapter.py` for the SetupConfig → detector-input
shaping. `alignment.py`'s `AlignmentChecker` corrects for camera drift
between cycles using two reference markers.

An earlier shadow-geometry approach (`detect_primer.py` + its calibration
harness `testing_harness.py`) is kept alongside, tested, but not wired to
the live pipeline — see `detect_primer.py`'s module docstring.

**Files:**
| File | Purpose |
|---|---|
| `main.py` | Deployable entry point — GPIO trigger loop, wires everything below |
| `detector_v3.py` | Template-matching detector (`TemplateMatcher`) |
| `config_adapter.py` | Shapes `SetupConfig` into detector/alignment inputs |
| `alignment.py` | Camera-drift correction (`AlignmentChecker`) |
| `camera.py` | Resolves a camera's by-path identity to a live `/dev/videoN` |
| `alerts.py` | Logs detection results; the extension point for future GPIO alarm output (S4) |
| `roi_config.py` | Canonical ROI coordinates for the standalone calibration scripts below |
| `capture_baseline.py`, `extract_templates.py`, `verify_alignment.py` | Manual calibration tools against `baseline/`/`templates/` — a separate path from the config-driven one `main.py` uses |
| `detect_primer.py`, `testing_harness.py` | Superseded shadow-geometry approach, kept for comparison |

**Metrics:**
- False positive/negative rates
- Detection latency (< 100 ms target)
- Robustness to lighting variations
- Alignment tolerance (QR code verification in S2 provides cross-check)

**Hardware dependencies:** S0 (camera path stability), S2 (QR alignment), S3 (end-stop switch), S6 (power budget).

**Next steps:**
1. Deploy to the Pi, configure a station via the setup app, and validate `main.py` end-to-end against the physical press.
2. Calibrate detection thresholds against real hardware data (currently naive — see `TemplateMatcher.detect_state`).
3. Build the alarm/GPIO output (S4) — severity-per-condition design notes are captured in project memory, not yet implemented.

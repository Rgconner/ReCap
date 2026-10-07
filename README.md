# ReCap — Reload Press QA System

Automated visual QA inspection for progressive reloading presses to detect missing/incorrect components before dangerous failures.

## Project Summary

ReCap provides automated visual inspection of ammunition reloading press stations to
detect missing or incorrect components before they become dangerous failures. The system
is mounted on a Frankford Arsenal X-10 (10-station) press, but is designed to be extensible
to other presses via a standard mount and configuration file.

## Phase 0 — Research Plan

See the full research plan in [`docs/phase-0-research-plan.md`](docs/phase-0-research-plan.md).

### Key Decisions
- **Target platform:** Raspberry Pi Zero 2 W with USB borehole cameras
- **Hybrid camera identity:** USB path symlinks + QR code scene verification
- **Licensing:** Pi software under Apache 2.0; PC companion commercial, open-core model
- **BOM finalized:** ~$285 total for 10 stations

### Research Spikes (S0–S6)
1. **S0 (highest priority):** USB camera path stability validation on Pi Zero 2 W
2. **S1:** Primer presence detection via template matching on borehole camera frames
3. **S2:** QR code alignment verification
4. **S3:** End-stop switch reliability under press vibration
5. **S4:** Alarm integration via relay on Pi
6. **S5:** Network connectivity for PC companion (LAN)
7. **S6:** Power stability for borehole cameras + Pi

## Repository Layout

- [`docs/phase-0-research-plan.md`](docs/phase-0-research-plan.md) — Phase 0 research plan
- [`docs/pi-setup.md`](docs/pi-setup.md) — flash & bootstrap the Pi Zero 2 W (boxed → first audit)
- [`spikes/s0-camera-path-stability/`](spikes/s0-camera-path-stability/) — S0 harness: audit script, udev template, runbook
- [`spikes/s1-primer-detection/`](spikes/s1-primer-detection/) — S1 harness: `detector_v3.py` (template matching, wired to the GPIO trigger loop in `main.py`, config-driven from the setup app's `config.json`) plus a superseded shadow-geometry approach kept for comparison
- [`setup/`](setup/) — FastAPI companion app for interactive camera/ROI/template setup (runs on a PC, not the Pi)
- `baseline/`, `templates/` — curated reference captures and detection templates used by S1 (tracked in git); `captures/` holds transient per-trigger debug snapshots and is gitignored

Each of `setup/` and `spikes/s1-primer-detection/` has its own `requirements.txt`; install per-component (`pip install -r setup/requirements.txt`, etc.) rather than as one combined environment, since the Pi and the PC companion need different dependency sets. `ruff.toml` at the repo root configures linting (`ruff check .`), and [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs lint + tests on push — note the repo's remote is a self-hosted Gitea instance, so this requires Gitea Actions enabled on that instance to actually run.

## Next Steps

1. **S0 (harness ready):** run [`spikes/s0-camera-path-stability/`](spikes/s0-camera-path-stability/) on the Pi Zero 2 W once hardware arrives
2. Order hardware per finalized BOM (~$285 total)
3. **S1 (detector implemented, untested on real hardware):** calibrate `detector_v3.py`'s templates and ROIs against the physical press once cameras are mounted

---

*This project uses Git with `core.autocrlf=false` to preserve line endings.*
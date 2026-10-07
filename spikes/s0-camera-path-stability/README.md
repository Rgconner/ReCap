# Spike S0 — USB camera path stability on Pi Zero 2 W

> **Status:** harness complete — hardware run pending (order per
> [phase-0 plan §5](../../docs/phase-0-research-plan.md))

**Goal** (phase-0 plan §4/S0): confirm that `/dev/videoX` node churn is
survivable because the physical-topology symlinks in `/dev/v4l/by-path/`
remain stable across reboots and replugs, and that they are a reliable
identity handle for 10 borehole cameras on one Pi.

## Background

- udev's persistent-v4l rules expose
  `/dev/v4l/by-path/<platform>-usb-0:1.2.4:1.0-video-index0` — a name
  derived from physical USB topology, not enumeration order.
- Every UVC camera registers **two** nodes: index 0 (capture) and index 1
  (metadata). Ten cameras ⇒ 20 `/dev/video*` nodes.
- Pi OS also registers platform V4L2 nodes (`bcm2835-isp`, codecs) — the
  audit lists these but ignores them.
- `/dev/videoN` renumbering across boots/replugs is *expected*; the spike
  measures whether the by-path handles stay valid when it happens.

## Files

| File | Purpose |
|---|---|
| `audit_paths.py` | Enumerate wiring, freeze a baseline, detect drift, summarize. Stdlib only. |
| `stability_run.sh` | Repeated-audit harness for non-reboot soak runs. |
| `udev/99-recap-cameras.rules.template` | Optional `/dev/recap-cam/station-NN` symlinks for production wiring. |

Runtime artifacts (`state/baseline.json`, `state/audit-log.jsonl`,
`frames/`) are per-machine and gitignored.

## Method (on the Pi)

First time? Follow [`docs/pi-setup.md`](../../docs/pi-setup.md) to flash the
SD card and clone the repo onto the Pi. Then:

1. `./audit_paths.py --list` — confirm all 10 cameras appear with distinct
   USB ports; note each port.
2. `./audit_paths.py --set-baseline` — freeze the known-good wiring.
3. `./audit_paths.py` — audit. Add `--grab-frames shots/` to also verify
   each camera streams one frame (`pip install opencv-python-headless`).
4. Reboot (`sudo reboot`), re-run step 3. Repeat for **≥ 10 boots**.
5. Unplug/replug test: 5 cycles per port, audit after each.
6. `./audit_paths.py --summary` — aggregate verdict over the whole log.

### Optional: automatic audit at every boot

Install both systemd units, substituting `<repo>` for the absolute clone
path (e.g. `/home/<user>/recap`):

```ini
# /etc/systemd/system/recap-s0-audit.service
[Unit]
Description=ReCap S0 camera path audit
After=multi-user.target

[Service]
Type=oneshot
ExecStart=<repo>/spikes/s0-camera-path-stability/audit_paths.py
```

```ini
# /etc/systemd/system/recap-s0-audit.timer
[Unit]
Description=Periodic ReCap S0 audit

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
```

`sudo systemctl enable --now recap-s0-audit.timer`

## Metrics & pass/fail

| Metric | Pass criterion |
|---|---|
| by-path symlink resolution (capture nodes) | 100% across ≥ 10 boots |
| Identity mapping (port → serial / VID:PID) | no unexplained changes |
| Replug recovery | symlink valid again within 5 s of replug, 5/5 cycles |
| Resolution latency | < 1 ms mean (informational) |
| `/dev/videoN` churn | recorded; churn alone is **not** a failure |

## Workarounds / risks to watch

- Cheap endoscopes ship **duplicate USB serials** (F2: two units both
  reported `20201212000000`) — by-id is actively unsafe; the port is the
  only stable handle (hence the hybrid scheme, plan §3), with QR scene
  verification (S2) as the cross-check.
- 10 cameras on one Pi may exceed the power/TT budget → overlaps spike
  **S6**; if cameras drop off, retest with a powered hub.
- USB autosuspend can stall UVC streams; if frames stall, try
  `usbcore.autosuspend=-1` on the kernel cmdline and re-audit.

## Findings

**F1 — first hardware run (2026-08-28, Pi Zero 2 W, Pi OS Lite 64-bit,
zero cameras attached):**

- `audit_paths.py --list` exited 0 with 0 USB cameras and 13 platform
  nodes (video10–16, 18, 20–23, 31) correctly identified and ignored —
  the sysfs USB-vs-platform classification works on target hardware.
- Observed node numbering: platform drivers claim video10+ and leave
  video0–9 unused, and the platform allocation itself is gapped (17, 19,
  24–30 free). Consequence: UVC capture/metadata node numbers will
  scatter across non-contiguous minors as cameras are added — raw
  `/dev/videoN` indices are unusable for identity, confirming the
  by-path symlink is the right stable handle (the S0 hypothesis).
- Executable bit + direct invocation via absolute path: working.

**F2 — first camera-attached run (2026-08-28, 2 cameras via USB hub):**

- Two "HD camera" units (VID:PID `349c:0411`, generic OEM endoscope)
  detected behind a hub at ports `1-1.4.1` / `1-1.4.3`; capture+metadata
  pairs grouped correctly (video0/1, video2/3).
- **Both units report the identical USB serial `20201212000000`.**
  Duplicate serials — worse than none: `/dev/v4l/by-id` names collide
  and get order-dependent suffixes, making by-id actively unsafe. Port
  identity is confirmed as the only stable handle; QR scene verification
  (S2) becomes the only wiring cross-check. The audit tool now warns
  about duplicate serials automatically (`find_duplicate_serials`).
- by-path symlink resolution: 0.12 ms per node — passes the < 1 ms
  informational criterion with two orders of magnitude to spare.
- Hub topology works as designed: hub ports (`1-1.4.x`) are the stable
  identity anchors — camera-to-hub-port wiring is now the production
  rule.

**Fleet state (2026-08-28):** powered hub confirmed; 2 cameras for now —
camera A at `1-1.4.1`, camera B at `1-1.4.3`. 10-station wiring deferred:
station count can be re-scoped after S0 (identity scales with hub-port
wiring either way), and a powered hub already de-risks the S6 power
budget for any realistic fleet size.

**F3 — hardware run completed (2026-08-29, 2 cameras, >= 10 reboots):**

- Baseline established, audit-log verified across all 10+ reboot cycles.
- by-path symlink resolution: 0.12 ms per node, 100% resolution success.
- Replug recovery: symlinks valid again within 5 s, 5/5 cycles passed.
- /dev/videoN churn recorded; churn alone is not a failure.

**USB physical reorder note:** If cameras are moved to new USB ports, /dev/videoN indices will renumber and the existing baseline may no longer match. The by-path symlinks remain stable because they derive from USB topology, not enumeration order. A camera relocation requires re-running --set-baseline and a new audit log. This will be addressed in S2 (QR code alignment verification) and S6 (power/USB budget) when full 10-station wiring is scoped.

_Pending: replug test with all 10 stations, final verdict per metric, workarounds promoted into the production design._

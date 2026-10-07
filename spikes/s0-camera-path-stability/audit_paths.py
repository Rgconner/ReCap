#!/usr/bin/env python3
"""ReCap Phase 0 spike S0 — USB camera path stability audit.

Enumerates V4L2 devices, maps every USB camera to its physical USB port
(sysfs topology), and audits the stability of the /dev/v4l/by-path/
symlinks that udev's persistent-v4l rules provide. Run repeatedly —
including across reboots — on the Pi Zero 2 W target to quantify:

  * by-path symlink resolution success rate   (must stay at 100%)
  * by-path symlink resolution latency        (informational)
  * /dev/videoN node-number churn             (expected, tolerated, recorded)
  * camera identity-mapping breakage          (must never happen)

Standard library only, so it runs on a bare Pi OS Lite image. OpenCV is
optional and used solely by --grab-frames.

Usage
-----
  ./audit_paths.py --list                 inspect current wiring
  ./audit_paths.py --set-baseline         freeze the known-good wiring
  ./audit_paths.py --install-udev         write udev port-pinning rules
  ./audit_paths.py                        audit against the baseline
  ./audit_paths.py --grab-frames shots/   audit + one frame per camera
  ./audit_paths.py --summary              aggregate the audit log
  ./audit_paths.py --json                 machine-readable report

Exit codes:  0 pass   1 drift/failure   2 environment/usage error

Why two nodes per camera
------------------------
The UVC driver registers a capture node (v4l index 0) and a metadata node
(v4l index 1) per streaming interface, so 10 cameras produce 20 /dev/video*
nodes. Pi OS also registers platform nodes (bcm2835-isp, codecs) which this
tool lists but otherwise ignores.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

V4L_CLASS = Path("/sys/class/video4linux")
BY_PATH_DIR = Path("/dev/v4l/by-path")
BOOT_ID_FILE = Path("/proc/sys/kernel/random/boot_id")

# A USB device directory is named "<bus>-<port.port.port>", e.g. "1-1.2.4".
USB_DEVICE_RE = re.compile(r"^(\d+)-(\d+(?:\.\d+)*)$")

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ENV = 2


def _read(path: Path) -> str | None:
    """Read a small sysfs/proc attribute; None on any failure."""
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def boot_id() -> str:
    return _read(BOOT_ID_FILE) or "unknown"


def _node_sort_key(dev: str) -> int:
    m = re.search(r"(\d+)$", dev)
    return int(m.group(1)) if m else 10 ** 9


@dataclass
class NodeInfo:
    """One /dev/videoN node as seen through sysfs."""

    node: str                    # "video0"
    dev: str                     # "/dev/video0"
    card: str                    # sysfs 'name' attribute
    index: int | None            # sysfs 'index' (UVC: 0 = capture, 1 = metadata)
    usb_port: str | None         # e.g. "1-1.2.4"; None for platform devices
    usb_dev_dir: Path | None     # sysfs dir of the parent USB device


@dataclass
class Camera:
    """A physical USB camera: one USB device, one or more V4L2 nodes."""

    usb_port: str
    card: str
    vendor_id: str | None = None
    product_id: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    serial: str | None = None
    # v4l index -> "/dev/videoN"
    nodes: dict[int, str] = field(default_factory=dict)
    # v4l index -> by-path symlink name
    by_path: dict[int, str] = field(default_factory=dict)
    # v4l index -> symlink resolve latency in ms
    by_path_ms: dict[int, float] = field(default_factory=dict)

    @property
    def capture_index(self) -> int:
        return min(self.nodes) if self.nodes else -1

    @property
    def capture_dev(self) -> str | None:
        return self.nodes.get(self.capture_index)

    def identity(self) -> dict:
        return {
            "usb_port": self.usb_port,
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "manufacturer": self.manufacturer,
            "product": self.product,
            "serial": self.serial,
        }


def scan_by_path() -> dict[str, tuple[str, float]]:
    """Map each /dev/v4l/by-path entry to (resolved device, latency ms)."""
    out: dict[str, tuple[str, float]] = {}
    if not BY_PATH_DIR.is_dir():
        return out
    for entry in sorted(BY_PATH_DIR.iterdir()):
        try:
            t0 = time.perf_counter()
            target = os.path.realpath(entry)
            ms = (time.perf_counter() - t0) * 1000.0
        except OSError:
            continue
        out[entry.name] = (target, ms)
    return out


def scan_nodes() -> tuple[list[NodeInfo], list[NodeInfo]]:
    """Split /dev/video* nodes into USB-backed and platform-backed lists."""
    usb_nodes: list[NodeInfo] = []
    platform_nodes: list[NodeInfo] = []
    for dev in sorted(glob.glob("/dev/video*"), key=_node_sort_key):
        node = os.path.basename(dev)
        if not re.fullmatch(r"video\d+", node):
            continue
        sysdir = V4L_CLASS / node
        if not sysdir.is_dir():
            continue

        index_raw = _read(sysdir / "index")
        try:
            index = int(index_raw) if index_raw is not None else None
        except ValueError:
            index = None

        # The 'device' symlink points at the USB *interface* dir
        # (.../usb1/1-1.2.4/1-1.2.4:1.0); its parent is the USB device dir.
        usb_port: str | None = None
        usb_dev_dir: Path | None = None
        try:
            iface = (sysdir / "device").resolve()
        except OSError:
            iface = None
        if iface is not None and USB_DEVICE_RE.match(iface.parent.name):
            usb_port = iface.parent.name
            usb_dev_dir = iface.parent

        info = NodeInfo(
            node=node,
            dev=dev,
            card=_read(sysdir / "name") or "?",
            index=index,
            usb_port=usb_port,
            usb_dev_dir=usb_dev_dir,
        )
        (usb_nodes if usb_dev_dir else platform_nodes).append(info)
    return usb_nodes, platform_nodes


def build_cameras(
    usb_nodes: list[NodeInfo],
    by_path: dict[str, tuple[str, float]],
) -> dict[str, Camera]:
    """Group USB video nodes into one Camera per USB device."""
    cameras: dict[str, Camera] = {}
    for n in usb_nodes:
        cam = cameras.get(n.usb_port)
        if cam is None:
            d = n.usb_dev_dir
            assert d is not None
            cam = Camera(
                usb_port=n.usb_port,
                card=n.card,
                vendor_id=_read(d / "idVendor"),
                product_id=_read(d / "idProduct"),
                manufacturer=_read(d / "manufacturer"),
                product=_read(d / "product"),
                serial=_read(d / "serial"),
            )
            cameras[n.usb_port] = cam
        if n.index is not None:
            cam.nodes[n.index] = n.dev

    by_target = {target: (name, ms) for name, (target, ms) in by_path.items()}
    for cam in cameras.values():
        for idx, dev in cam.nodes.items():
            hit = by_target.get(dev)
            if hit:
                cam.by_path[idx] = hit[0]
                cam.by_path_ms[idx] = hit[1]
    return cameras


def find_duplicate_serials(cameras: dict[str, Camera]) -> list[str]:
    """Serials reported by more than one camera.

    Cheap OEM camera firmware often hardcodes one serial across the whole
    production run (observed: two units both reporting '20201212000000').
    Duplicate serials make /dev/v4l/by-id actively unsafe — colliding
    names get order-dependent suffixes. When duplicates exist, the physical
    port (by-path) is the only stable identity handle.
    """
    by_serial: dict[str, list[str]] = {}
    for cam in cameras.values():
        if cam.serial:
            by_serial.setdefault(cam.serial, []).append(cam.usb_port)
    return sorted(s for s, ports in by_serial.items() if len(ports) > 1)


class State:
    """Baseline snapshot + append-only JSONL audit log on disk."""

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.baseline_path = state_dir / "baseline.json"
        self.log_path = state_dir / "audit-log.jsonl"

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def load_baseline(self) -> dict | None:
        try:
            return json.loads(self.baseline_path.read_text())
        except (OSError, ValueError):
            return None

    def save_baseline(self, cameras: dict[str, Camera]) -> dict:
        self.ensure()
        data = {
            "created": _now_iso(),
            "boot_id": boot_id(),
            "cameras": {
                port: {
                    "identity": cam.identity(),
                    "card": cam.card,
                    "nodes": dict(cam.nodes),
                    "by_path": dict(cam.by_path),
                }
                for port, cam in sorted(cameras.items())
            },
        }
        self.baseline_path.write_text(json.dumps(data, indent=2) + "\n")
        return data

    def append_log(self, record: dict) -> None:
        self.ensure()
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def read_log(self) -> list[dict]:
        try:
            lines = self.log_path.read_text().splitlines()
        except OSError:
            return []
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return records


def compare_baseline(
    baseline: dict, cameras: dict[str, Camera]
) -> tuple[list[dict], list[dict]]:
    """Return (issues, churn) between the baseline snapshot and live scan.

    Issues are drift that matters (missing/new camera, unresolvable by-path
    symlink, identity change). Churn is /dev/videoN renumbering — expected
    and tolerated, because the by-path symlink is the stable handle.
    """
    issues: list[dict] = []
    churn: list[dict] = []
    base: dict = baseline.get("cameras", {})

    for port, cam in sorted(cameras.items()):
        b = base.get(port)
        if b is None:
            issues.append({
                "severity": "error", "type": "new-camera", "camera": port,
                "detail": "not in baseline — rewired? re-baseline deliberately",
            })
            continue

        ident_then = b.get("identity", {})
        for key in ("vendor_id", "product_id", "serial"):
            now_val = cam.identity().get(key)
            if now_val != ident_then.get(key):
                issues.append({
                    "severity": "error", "type": "identity-change",
                    "camera": port,
                    "detail": f"{key}: baseline={ident_then.get(key)!r} now={now_val!r}",
                })

        capture = cam.capture_index
        if capture < 0 or capture not in cam.by_path:
            issues.append({
                "severity": "error", "type": "by-path-missing",
                "camera": port,
                "detail": f"capture node {cam.capture_dev} has no by-path symlink",
            })

        for idx, dev in cam.nodes.items():
            was = b.get("nodes", {}).get(idx)
            if was is not None and was != dev:
                churn.append({"camera": port, "index": idx, "was": was, "now": dev})
            if idx != capture and idx not in cam.by_path:
                issues.append({
                    "severity": "warn", "type": "by-path-missing",
                    "camera": port,
                    "detail": f"node {dev} (index {idx}) has no by-path symlink",
                })

    for port in sorted(set(base) - set(cameras)):
        issues.append({
            "severity": "error", "type": "camera-missing", "camera": port,
            "detail": "in baseline but absent now",
        })
    return issues, churn


def grab_frames(cameras: dict[str, Camera], out_dir: Path) -> dict:
    """Capture one frame per camera. Optional; needs opencv-python-headless."""
    try:
        import cv2
    except ImportError:
        return {"error": "OpenCV not installed — pip install opencv-python-headless"}

    # Force the V4L2 backend: without the hint OpenCV tries the FFMPEG
    # device backend, which opencv-python-headless does not include.
    v4l2 = getattr(cv2, "CAP_V4L2", 200)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    for port, cam in sorted(cameras.items()):
        dev = cam.capture_dev
        entry = {"device": dev, "opened": False, "frame": False, "saved": None}
        if dev:
            t0 = time.perf_counter()
            cap = cv2.VideoCapture(dev, v4l2)
            entry["opened"] = cap.isOpened()
            if entry["opened"]:
                ok, frame = cap.read()
                entry["frame"] = bool(ok and frame is not None and frame.size)
                if entry["frame"]:
                    fname = out_dir / (port.replace(".", "-") + ".jpg")
                    entry["saved"] = (
                        str(fname) if cv2.imwrite(str(fname), frame) else None
                    )
            cap.release()
            entry["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        results[port] = entry
    return results


def compute_metrics(
    cameras: dict[str, Camera],
    issues: list[dict],
    churn: list[dict],
    log_records: list[dict],
) -> dict:
    latencies = [ms for cam in cameras.values() for ms in cam.by_path_ms.values()]
    total = len(cameras)
    ok = sum(
        1 for cam in cameras.values()
        if cam.capture_index >= 0 and cam.capture_index in cam.by_path
    )
    boots = {r.get("boot_id") for r in log_records if r.get("boot_id")}
    return {
        "cameras": total,
        "capture_symlink_ok": ok,
        "capture_symlink_rate": round(ok / total, 4) if total else 0.0,
        "symlink_resolve_ms_mean": (
            round(sum(latencies) / len(latencies), 3) if latencies else None
        ),
        "symlink_resolve_ms_max": round(max(latencies), 3) if latencies else None,
        "errors": sum(1 for i in issues if i.get("severity") == "error"),
        "warnings": sum(1 for i in issues if i.get("severity") == "warn"),
        "node_churn_events": len(churn),
        "audits_logged": len(log_records),
        "boots_observed": len(boots),
    }


def print_cameras(
    cameras: dict[str, Camera],
    platform_nodes: list[NodeInfo],
    dupe_serials: list[str] | None = None,
) -> None:
    print(f"USB cameras: {len(cameras)}")
    for i, (port, cam) in enumerate(sorted(cameras.items()), 1):
        vid = f"{cam.vendor_id or '????'}:{cam.product_id or '????'}"
        label = cam.product or cam.manufacturer or cam.card
        print(f"  [{i:>2}] port {port:<12} {vid}  serial={cam.serial or '—'}  \"{label}\"")
        for idx in sorted(cam.nodes):
            kind = "capture" if idx == cam.capture_index else "metadata"
            bp = cam.by_path.get(idx)
            ms = cam.by_path_ms.get(idx)
            tail = f"{bp}  ({ms:.2f} ms)" if bp else "NO by-path SYMLINK"
            print(f"        {kind:<8} {cam.nodes[idx]:<14} {tail}")
    if platform_nodes:
        names = ", ".join(
            n.node for n in sorted(platform_nodes, key=lambda x: _node_sort_key(x.dev))
        )
        print(f"Platform V4L2 nodes (ignored): {names}")
    if dupe_serials:
        for s in dupe_serials:
            print(f"WARNING: duplicate USB serial {s!r} shared by multiple cameras")
        print("         /dev/v4l/by-id is UNSAFE for this fleet (ambiguous,")
        print("         order-dependent); port identity (by-path) is required.")


def generate_udev_rules(cameras: dict[str, Camera]) -> str:
    """Render the text of /etc/udev/rules.d/99-recap-cameras.rules.

    Maps each detected camera to a stable symlink /dev/recap-cam/station-<n>,
    numbered by sorted physical-port order. The cheap borehole cameras ship
    DUPLICATE USB serials (observed: identical across units — spike Findings
    F2), so /dev/v4l/by-id is unsafe. The physical USB port is the stable
    identity, so each rule pins a press station to its port via KERNELS==.

    Returns the complete rule text, or "" when no cameras are given.
    """
    if not cameras:
        return ""

    lines: list[str] = [
        "# Generated by audit_paths.py --install-udev",
        "# Date: " + _now_iso(),
        "",
    ]
    for idx, port in enumerate(sorted(cameras.keys()), start=1):
        cam = cameras[port]
        # Each camera has two video nodes (capture + metadata); only the
        # capture node (v4l index 0) is symlinked. KERNELS matches the parent
        # USB device directory (e.g. "1-1.2.4"), i.e. the physical port.
        lines.append(
            f'SUBSYSTEM=="video4linux", KERNEL=="video*", KERNELS=="{port}", '
            f'SYMLINK+="recap-cam/station-{idx}"  # {cam.card}'
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def install_udev_rules(cameras: dict[str, Camera]) -> None:
    """Generate and install /etc/udev/rules.d/99-recap-cameras.rules.

    Rules are generated from the CURRENT wiring (not the baseline), so this
    works standalone via --install-udev once cameras are plugged into their
    final ports. Needs root: tries a direct write first, then falls back to
    sudo. Afterwards reload udev:
      sudo udevadm control --reload && sudo udevadm trigger
    """
    if not cameras:
        print("warning: no USB cameras detected — nothing to install",
              file=sys.stderr)
        return

    rules_text = generate_udev_rules(cameras)
    if not rules_text.strip():
        print("warning: generated empty udev rules", file=sys.stderr)
        return

    rules_dir = Path("/etc/udev/rules.d")
    rules_path = rules_dir / "99-recap-cameras.rules"

    try:
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write(rules_text)
        os.chmod(rules_path, 0o644)
    except PermissionError:
        print("Installing udev rules requires root privileges. Trying sudo ...",
              file=sys.stderr)
        result = subprocess.run(
            ["sudo", "tee", str(rules_path)],
            input=rules_text,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"error: sudo install failed: {result.stderr.strip()}",
                  file=sys.stderr)
            print(f"Write the file manually:  sudo tee {rules_path}", file=sys.stderr)
            return
    print(f"udev rules installed: {rules_path}")
    print("Apply with:  sudo udevadm control --reload && sudo udevadm trigger")


def print_summary(records: list[dict]) -> None:
    audits = [r for r in records if r.get("event") == "audit"]
    print(f"Audit log: {len(records)} record(s), {len(audits)} audit run(s)")
    if not audits:
        return
    boots = {r.get("boot_id") for r in audits if r.get("boot_id")}
    fails = [r for r in audits if not r.get("pass")]
    total_issues = sum(len(r.get("issues", [])) for r in audits)
    total_churn = sum(len(r.get("churn", [])) for r in audits)
    lat_max = max(
        (r.get("metrics", {}).get("symlink_resolve_ms_max") or 0.0) for r in audits
    )
    print(f"Boots observed:           {len(boots)}")
    print(f"Failed runs:              {len(fails)}/{len(audits)}")
    print(f"Total issues (all runs):  {total_issues}")
    print(f"Total node churn events:  {total_churn}")
    print(f"Max symlink resolve time: {lat_max:.2f} ms")
    for r in fails[-5:]:
        detail = "; ".join(
            f"{i.get('type')}({i.get('camera')})" for i in r.get("issues", [])
        ) or "unknown"
        print(f"  FAIL {r.get('ts')} boot={str(r.get('boot_id'))[:8]} — {detail}")
    last = audits[-1]
    verdict = "PASS" if last.get("pass") else "FAIL"
    print(f"Last run: {last.get('ts')} boot={str(last.get('boot_id'))[:8]} — {verdict}")


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="ReCap S0 — USB camera path stability audit (run on the Pi)"
    )
    parser.add_argument(
        "--state-dir", type=Path, default=here / "state",
        help="baseline + audit-log directory (default: ./state next to this script)",
    )
    parser.add_argument("--list", action="store_true",
                        help="print current wiring and exit")
    parser.add_argument("--set-baseline", action="store_true",
                        help="record current wiring as the reference snapshot")
    parser.add_argument("--summary", action="store_true",
                        help="aggregate the audit log and exit")
    parser.add_argument("--grab-frames", type=Path, metavar="DIR",
                        help="also capture one frame per camera into DIR")
    parser.add_argument("--json", action="store_true",
                        help="emit a JSON report instead of text")
    parser.add_argument("--install-udev", action="store_true",
                        help="generate and install /etc/udev/rules.d/99-recap-cameras.rules "
                             "from current camera wiring (standalone, or after --set-baseline)")
    args = parser.parse_args(argv)

    state = State(args.state_dir)

    if args.summary:
        records = state.read_log()
        if args.json:
            print(json.dumps(records, indent=2))
        else:
            print_summary(records)
        return EXIT_OK if (not records or records[-1].get("pass")) else EXIT_DRIFT

    if os.name != "posix" or not glob.glob("/dev/video*"):
        print("error: must run on Linux with /dev/video* devices present",
              file=sys.stderr)
        return EXIT_ENV

    usb_nodes, platform_nodes = scan_nodes()
    cameras = build_cameras(usb_nodes, scan_by_path())
    dupe_serials = find_duplicate_serials(cameras)

    if args.list:
        if args.json:
            payload = {
                "cameras": {
                    p: c.identity() | {"nodes": c.nodes, "by_path": c.by_path}
                    for p, c in sorted(cameras.items())
                },
                "platform_nodes": [n.node for n in platform_nodes],
                "duplicate_serials": dupe_serials,
            }
            print(json.dumps(payload, indent=2))
        else:
            print_cameras(cameras, platform_nodes, dupe_serials)
        return EXIT_OK

    if args.set_baseline:
        if not cameras:
            print("error: no USB cameras found — nothing to baseline",
                  file=sys.stderr)
            return EXIT_ENV
        state.save_baseline(cameras)
        print(f"Baseline saved ({len(cameras)} cameras) -> {state.baseline_path}")
        print_cameras(cameras, platform_nodes, dupe_serials)
        if args.install_udev:
            install_udev_rules(cameras)
        return EXIT_OK

    if args.install_udev:
        # Standalone --install-udev (no --set-baseline): pin the current
        # wiring with udev rules; no baseline required.
        install_udev_rules(cameras)
        return EXIT_OK

    baseline = state.load_baseline()
    if baseline is None:
        print("error: no baseline — run with --set-baseline on known-good wiring",
              file=sys.stderr)
        return EXIT_ENV

    issues, churn = compare_baseline(baseline, cameras)
    frames = grab_frames(cameras, args.grab_frames) if args.grab_frames else None
    metrics = compute_metrics(cameras, issues, churn, state.read_log())
    metrics["duplicate_serials"] = len(dupe_serials)
    passed = metrics["errors"] == 0

    record = {
        "ts": _now_iso(),
        "boot_id": boot_id(),
        "event": "audit",
        "pass": passed,
        "cameras": len(cameras),
        "issues": issues,
        "churn": churn,
        "metrics": metrics,
    }
    if frames is not None:
        record["frames"] = frames
    state.append_log(record)

    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print_cameras(cameras, platform_nodes, dupe_serials)
        print()
        print(f"Baseline: {baseline.get('created')} "
              f"({len(baseline.get('cameras', {}))} cameras)")
        if issues:
            print(f"Issues ({len(issues)}):")
            for i in issues:
                print(f"  [{i['severity']}] {i['type']}: {i['camera']} — {i['detail']}")
        else:
            print("Issues: none")
        if churn:
            pairs = ", ".join(f"{c['camera']}:{c['was']}->{c['now']}" for c in churn)
            print(f"Node churn ({len(churn)}): {pairs}")
        if frames and "error" not in frames:
            ok = sum(1 for f in frames.values() if f.get("frame"))
            print(f"Frames: {ok}/{len(frames)} cameras delivered a frame")
            for port, f in sorted(frames.items()):
                if not f.get("frame"):
                    print(f"  NO FRAME: {port} ({f.get('device')})")
        print()
        print(f"Metrics: {json.dumps(metrics)}")
        print(f"RESULT: {'PASS' if passed else 'DRIFT DETECTED'}")

    return EXIT_OK if passed else EXIT_DRIFT


if __name__ == "__main__":
    sys.exit(main())

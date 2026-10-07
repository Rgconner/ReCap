# ReCap Pi Setup — from boxed hardware to first audit

Target: Raspberry Pi Zero 2 W, Pi OS Lite (64-bit). Written for Windows
workstations. Total time: ~15 minutes, most of it waiting on the flash.

## 1. What you need

| Item | Notes |
|---|---|
| Pi Zero 2 W | The compute target per the Phase 0 plan |
| microSD card ≥ 8 GB + reader | Class 10 / A1 is plenty |
| 5 V PSU (≥ 2.5 A) | Pi-only; cameras come off the powered hub later |
| micro-USB **OTG adapter** | The Pi's power port doubles as the only data port — cameras plug in here |
| USB borehole camera(s) | One is enough to start S0 |
| Powered USB hub (later) | Required for multi-camera runs — see "USB topology" below |

## 2. Flash the card (Raspberry Pi Imager)

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on the
   Windows machine and insert the card.
2. Choose OS → **Raspberry Pi OS Lite (64-bit)** — no desktop needed.
3. Choose storage → the microSD card.
4. Click the gear icon (or "Edit settings") **before** writing, and set:
   - Hostname: `recap-pi`
   - Username / password: your choice (Bookworm requires you to set one; the
     old `pi`/`raspberry` default no longer exists)
   - Wi-Fi: your SSID + password, and the right wireless country
   - **Enable SSH** (password auth is fine for the lab; key-only later)
   - Locale/timezone
5. Write, wait, insert into the Pi, power on. First boot takes 1–2 min.

## 3. First login

From Windows (OpenSSH client is built in):

```
ssh <user>@recap-pi.local
```

If `.local` doesn't resolve, find the IP from your router (or `ping recap-pi.local`).

## 4. Clone the repo

On the Pi, install git if needed and clone:

```
sudo apt install -y git
git clone https://github.com/Rgconner/recap.git ~/recap
```

Mark the S0 scripts executable:

```
chmod +x ~/recap/spikes/s0-camera-path-stability/audit_paths.py           ~/recap/spikes/s0-camera-path-stability/stability_run.sh
```

## 5. USB topology (read before plugging in cameras)

- **One camera** (early S0 work): plug it directly into the Pi's data port
  via the OTG adapter. You should see two nodes per camera (capture + metadata)
  in the `--list` output.
- **Multiple cameras**: the Pi Zero 2 W has exactly one data port, so a
  **powered USB hub** is mandatory. This also answers BOM open question #5 in
  practice: 10 cameras on a single 5 V 3 A supply is not realistic without
  one. Prefer a hub with per-port power switches for the S6 power spike.
- **Topology is identity**: the udev/audit scheme keys on physical port
  (e.g. `1-1.2.4`). Behind a hub, hub ports become the stable anchors —
  plug each station's camera into a *dedicated hub port* and never move it.
- **Validation trick**: with zero cameras attached, `audit_paths.py --list`
  still lists the Pi's platform V4L2 nodes (bcm2835-isp etc.) — that alone
  proves the sysfs scan works on real hardware before any camera arrives.

## 6. Run the spike

Follow [`spikes/s0-camera-path-stability/README.md`](../spikes/s0-camera-path-stability/README.md):

```
cd ~/recap/spikes/s0-camera-path-stability
./audit_paths.py --list           # confirm wiring, note each camera's port
./audit_paths.py --set-baseline   # freeze known-good wiring
sudo reboot                       # audit again after each boot; >= 10 boots
./audit_paths.py --summary        # aggregate verdict
```

Optional: auto-audit every boot + 30 min — see the manual systemd unit
setup in [the S0 README](../spikes/s0-camera-path-stability/README.md#optional-automatic-audit-at-every-boot).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ssh: connection refused` | Pi still booting; wait 60 s. Confirm it's on your Wi-Fi (same subnet) |
| `audit_paths.py: Permission denied` | `chmod +x audit_paths.py stability_run.sh` |
| Camera absent from `--list` | Check the OTG adapter (data-capable, not charge-only); try `lsusb` |
| Frames stall during `--grab-frames` | USB autosuspend — add `usbcore.autosuspend=-1` to `/boot/firmware/cmdline.txt`, reboot |
| Clone auth loops | Make sure the Gitea token has repo scope; re-enter it as the password prompt |

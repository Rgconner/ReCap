#!/usr/bin/env bash
# ReCap spike S0 — run the camera path audit repeatedly without rebooting.
#
# Usage:
#   ./stability_run.sh [iterations] [delay_seconds]
#
# For reboot coverage (the important half of S0), either re-run
# ./audit_paths.py manually after each `sudo reboot`, or install the
# systemd units from README.md so every boot records an audit.

set -uo pipefail

ITER="${1:-10}"
DELAY="${2:-30}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILED=0

if ! [[ "$ITER" =~ ^[0-9]+$ && "$DELAY" =~ ^[0-9]+$ ]]; then
    echo "usage: $0 [iterations] [delay_seconds]" >&2
    exit 2
fi

echo "ReCap S0 stability run — ${ITER} iteration(s), ${DELAY}s apart"
for i in $(seq 1 "$ITER"); do
    echo
    echo "=== iteration ${i}/${ITER} — $(date -Is) ==="
    if ! python3 "${HERE}/audit_paths.py"; then
        FAILED=$((FAILED + 1))
    fi
    if [ "$i" -lt "$ITER" ]; then
        sleep "$DELAY"
    fi
done

echo
echo "=== aggregate summary ==="
python3 "${HERE}/audit_paths.py" --summary
echo
echo "Failed audits: ${FAILED}/${ITER}"
[ "$FAILED" -eq 0 ]

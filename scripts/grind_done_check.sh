#!/bin/bash
# DVC grind done-gate. Exit 0 only when the paper is genuinely finished.
#
# Three conditions, in order:
#   1. the executable findings-freeze gate is GREEN;
#   2. paper/main.pdf and deck/main.pdf both exist;
#   3. both were rebuilt AFTER the freeze first went green.
#
# (3) uses logs/freeze-green.stamp, which this script — not the worker — creates
# the first time the gate passes. A worker therefore cannot satisfy the gate with
# PDFs it built while the evidence was still red; it has to rebuild them after.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

./scripts/run scripts/audit_findings_freeze.py >/dev/null 2>&1 || exit 1

STAMP=logs/freeze-green.stamp
mkdir -p logs
[ -f "$STAMP" ] || { touch "$STAMP"; echo "freeze gate green; stamped $STAMP" >&2; }

[ -f paper/main.pdf ] || exit 1
[ -f deck/main.pdf ] || exit 1
[ paper/main.pdf -nt "$STAMP" ] || exit 1
[ deck/main.pdf -nt "$STAMP" ] || exit 1
exit 0

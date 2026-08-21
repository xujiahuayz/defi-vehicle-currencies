#!/usr/bin/env python3
"""Run the complete vehicle-transition E0 family through its two owners."""

from __future__ import annotations

from run_entry_vehicle_price_alignment import main as run_entry_price_alignment
from run_vehicle_rotation_adjacent_years import main as run_adjacent_years
from run_vehicle_rotation_composition_e0 import main as run_composition
from run_vehicle_transition_e0 import main as run_transition


def main() -> int:
    status = run_transition()
    if status != 0:
        return status
    status = run_composition()
    if status != 0:
        return status
    status = run_adjacent_years()
    if status != 0:
        return status
    return run_entry_price_alignment()


if __name__ == "__main__":
    raise SystemExit(main())

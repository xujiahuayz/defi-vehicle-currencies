#!/usr/bin/env python3
"""Build the cached native inventory of persisted raw AMM records."""

from __future__ import annotations

from pathlib import Path

from ddvc.analysis.raw_data_inventory import publish_raw_data_inventory
from ddvc.paths import DATA_DIR


OUTPUT = DATA_DIR / "processed" / "raw_data_inventory.parquet"
inventory = publish_raw_data_inventory(DATA_DIR / "raw", OUTPUT, progress=print)
print(
    f"wrote {OUTPUT} ({len(inventory):,} files; "
    f"{int(inventory['records'].sum()):,} raw records)"
)

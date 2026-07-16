#!/usr/bin/env python3
"""Build the cached native inventory of persisted raw AMM records."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ddvc.analysis.raw_data_inventory import build_raw_data_inventory
from ddvc.paths import DATA_DIR


OUTPUT = DATA_DIR / "processed" / "raw_data_inventory.parquet"
previous = pd.read_parquet(OUTPUT) if OUTPUT.exists() else None
inventory = build_raw_data_inventory(
    DATA_DIR / "raw",
    previous=previous,
    progress=print,
)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
temporary = Path(f"{OUTPUT}.tmp")
inventory.to_parquet(temporary, index=False)
temporary.replace(OUTPUT)
print(
    f"wrote {OUTPUT} ({len(inventory):,} files; "
    f"{int(inventory['records'].sum()):,} raw records)"
)

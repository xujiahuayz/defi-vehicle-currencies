#!/usr/bin/env python3
"""Fetch DeFiLlama's daily Ethereum DEX-volume breakdown.

Writes  data/raw/external/defillama/ethereum_dex_overview.json

Run     ./scripts/run scripts/fetch/fetch_defillama_ethereum_dex_volume.py
"""

from __future__ import annotations

import json
import urllib.request

from ddvc.paths import DATA_DIR
from ddvc.runtime import atomic_output


URL = "https://api.llama.fi/overview/dexs/Ethereum"
OUTPUT = DATA_DIR / "raw" / "external" / "defillama" / "ethereum_dex_overview.json"


def main() -> int:
    request = urllib.request.Request(URL, headers={"User-Agent": "ddvc-research/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    breakdown = payload.get("totalDataChartBreakdown")
    if not isinstance(breakdown, list) or not breakdown:
        raise ValueError("DeFiLlama response lacks a daily protocol breakdown")
    with atomic_output(OUTPUT) as temporary:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    print(f"wrote {len(breakdown):,} daily rows to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build annual Ethereum DEX-volume coverage for the route-panel families.

Reads   data/raw/external/defillama/ethereum_dex_overview.json
Writes  output/exhibits/ethereum_dex_market_coverage.jsonl
"""

from __future__ import annotations

import json

from ddvc.market_coverage import annual_market_coverage
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.runtime import atomic_output


INPUT = DATA_DIR / "raw" / "external" / "defillama" / "ethereum_dex_overview.json"
OUTPUT = OUTPUT_DIR / "exhibits" / "ethereum_dex_market_coverage.jsonl"


def main() -> int:
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    rows = annual_market_coverage(payload.get("totalDataChartBreakdown", []))
    with atomic_output(OUTPUT) as temporary:
        temporary.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
    print(f"wrote {len(rows)} annual rows to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

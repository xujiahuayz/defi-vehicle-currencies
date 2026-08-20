#!/usr/bin/env python3
"""Build the exact Uniswap V1 exchange-to-token crosswalk.

Reads   data/raw/thegraph/uniswap_v1/uniswap_v1_exchange_registry.jsonl.gz
        data/processed/v1_exchange_day.parquet
Writes  data/processed/v1_exchange_token_crosswalk.parquet

Run     ./scripts/run scripts/process/build_v1_exchange_token_crosswalk.py
"""

from __future__ import annotations

import gzip
import json

import pandas as pd

from ddvc.paths import DATA_DIR
from ddvc.tables import write_panel


RAW = (
    DATA_DIR
    / "raw"
    / "thegraph"
    / "uniswap_v1"
    / "uniswap_v1_exchange_registry.jsonl.gz"
)
EXCHANGE_DAY = DATA_DIR / "processed" / "v1_exchange_day.parquet"
OUTPUT = DATA_DIR / "processed" / "v1_exchange_token_crosswalk.parquet"
V2_LAUNCH = pd.Timestamp("2020-05-05")


def read_registry(path=RAW) -> pd.DataFrame:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    frame = pd.DataFrame(rows).rename(
        columns={"id": "exchange", "tokenAddress": "token", "tokenSymbol": "symbol"}
    )
    required = {"exchange", "token", "symbol"}
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("V1 exchange registry lacks exchange, token, or symbol")
    frame["exchange"] = frame.exchange.astype(str).str.lower()
    frame["token"] = frame.token.astype(str).str.lower()
    if frame.exchange.duplicated().any() or frame.token.duplicated().any():
        raise ValueError("V1 exchange registry is not one-to-one")
    return frame.sort_values("exchange").reset_index(drop=True)


def build_crosswalk(registry: pd.DataFrame, exchange_day: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    observed = set(exchange_day.exchange.astype(str).str.lower())
    registered = set(registry.exchange)
    missing = observed - registered
    if missing:
        raise ValueError(
            f"V1 registry misses {len(missing):,}/{len(observed):,} observed exchanges; "
            f"first={sorted(missing)[0]}"
        )
    active_before_v2 = set(
        exchange_day.loc[
            (pd.to_datetime(exchange_day.date) < V2_LAUNCH)
            & ((exchange_day.n_pair.fillna(0) + exchange_day.n_t2t.fillna(0)) > 0),
            "exchange",
        ].astype(str).str.lower()
    )
    out = registry.copy()
    out["status"] = "exact_subgraph_registry"
    out["resolved"] = True
    out["observed_in_daily_panel"] = out.exchange.isin(observed)
    out["v1_era"] = out.exchange.isin(active_before_v2)
    return out, {
        "registry_rows": len(out),
        "observed_exchanges": len(observed),
        "observed_exchanges_resolved": len(observed),
        "v1_era_exchanges": len(active_before_v2),
    }


def main() -> int:
    registry = read_registry()
    exchange_day = pd.read_parquet(EXCHANGE_DAY)
    crosswalk, summary = build_crosswalk(registry, exchange_day)
    write_panel(crosswalk, OUTPUT)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

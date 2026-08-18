#!/usr/bin/env python3
"""Build a processed Uniswap v3 pool-day fee panel from retained raw records."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from ddvc.paths import DATA_DIR
from ddvc.tables import write_panel


RAW_INPUT = DATA_DIR / "raw/archive/defi-dominant-currency/uniswap_v3/raw_pool_day_fee"
OUTPUT = DATA_DIR / "processed/v3_pool_day_fees.parquet"
CODE_SOURCES = ["scripts/process/build_v3_pool_day_fees.py"]
INPUTS = [
    "data/raw/archive/defi-dominant-currency/uniswap_v3/raw_pool_day_fee/*.jsonl.gz"
]


def _raw_glob(path: Path) -> str:
    if path.is_dir():
        return str(path / "*.jsonl*")
    return str(path)


def build_v3_pool_day_fees(raw_path: Path = RAW_INPUT) -> pd.DataFrame:
    """Return one row per v3 pool-day with raw-reported fees and volume."""

    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        frame = connection.execute(
            """
            WITH raw_rows AS (
                SELECT DISTINCT
                    to_timestamp(date)::DATE AS origin_date,
                    lower(pool.id) AS pool,
                    lower(pool.token0.id) AS token0_address,
                    pool.token0.symbol AS token0_symbol,
                    lower(pool.token1.id) AS token1_address,
                    pool.token1.symbol AS token1_symbol,
                    TRY_CAST(feesUSD AS DOUBLE) AS fees_usd,
                    TRY_CAST(volumeUSD AS DOUBLE) AS volume_usd,
                    TRY_CAST(tvlUSD AS DOUBLE) AS tvl_usd
                FROM read_json_auto(?, format='newline_delimited')
                WHERE pool.id IS NOT NULL
                  AND pool.token0.id IS NOT NULL
                  AND pool.token1.id IS NOT NULL
            )
            SELECT
                origin_date,
                pool,
                min(token0_address) AS token0_address,
                min(token0_symbol) AS token0_symbol,
                min(token1_address) AS token1_address,
                min(token1_symbol) AS token1_symbol,
                max(fees_usd) AS fees_usd,
                max(volume_usd) AS volume_usd,
                max(tvl_usd) AS tvl_usd
            FROM raw_rows
            WHERE fees_usd IS NOT NULL
              AND volume_usd IS NOT NULL
              AND tvl_usd IS NOT NULL
              AND tvl_usd > 0
            GROUP BY origin_date, pool
            ORDER BY origin_date, pool
            """,
            [_raw_glob(raw_path)],
        ).fetchdf()
    finally:
        connection.close()
    validate_v3_pool_day_fees(frame)
    return frame


def validate_v3_pool_day_fees(frame: pd.DataFrame) -> None:
    required = {
        "origin_date",
        "pool",
        "token0_address",
        "token1_address",
        "fees_usd",
        "volume_usd",
        "tvl_usd",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"v3 pool-day fee panel lacks columns: {missing}")
    if frame.empty:
        raise ValueError("v3 pool-day fee panel is empty")
    duplicated = frame.duplicated(["origin_date", "pool"])
    if duplicated.any():
        raise ValueError("v3 pool-day fee panel has duplicate pool-days")
    for column in ("fees_usd", "volume_usd", "tvl_usd"):
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"v3 pool-day fee panel has missing {column}")
        if (values < 0).any():
            raise ValueError(f"v3 pool-day fee panel has negative {column}")
    if (pd.to_numeric(frame["tvl_usd"], errors="coerce") <= 0).any():
        raise ValueError("v3 pool-day fee panel has nonpositive TVL")


def run(*, raw_path: Path = RAW_INPUT, output_path: Path = OUTPUT) -> int:
    frame = build_v3_pool_day_fees(raw_path)
    write_panel(
        frame,
        output_path,
        code_sources=CODE_SOURCES,
        inputs=[raw_path if raw_path.is_file() else Path(INPUTS[0])],
        notes=(
            "Processed Uniswap v3 pool-day fee and volume panel; one row per "
            "pool-day from retained raw poolDayData snapshots."
        ),
        preinstall_validator=lambda path: validate_v3_pool_day_fees(
            pd.read_parquet(path)
        ),
    )
    print(f"wrote {len(frame):,} v3 pool-day fee rows to {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    return run(raw_path=args.raw, output_path=args.output)


if __name__ == "__main__":
    raise SystemExit(main())

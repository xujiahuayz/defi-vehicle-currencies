#!/usr/bin/env python3
"""Build the full-history Uniswap V3 pool-day fee, volume, and TVL panel."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR
from ddvc.fetch.pool_daily import require_pool_daily_coverage
from ddvc.tables import write_panel


RAW_INPUT = DATA_DIR / "raw/thegraph/uniswap_v3"
STATIC_INPUT = RAW_INPUT / "uniswap_v3_pool_statics_20260630.jsonl.gz"
OUTPUT = DATA_DIR / "processed/v3_pool_day_fees.parquet"
CODE_SOURCES = ["scripts/process/build_v3_pool_day_fees.py"]
INPUTS = [
    "data/raw/thegraph/uniswap_v3/uniswap_v3_daily_*.jsonl.gz",
    "data/raw/thegraph/uniswap_v3/uniswap_v3_pool_statics_20260630.jsonl.gz",
]
FEE_RECONCILIATION_TOLERANCE = 1.0e-8
EXPECTED_FIRST_DATE = pd.Timestamp("2021-05-04")
EXPECTED_LAST_DATE = pd.Timestamp("2026-06-30")


def _daily_glob(path: Path) -> str:
    if path.is_dir():
        return str(path / "uniswap_v3_daily_*.jsonl.gz")
    return str(path)


def build_v3_pool_day_fees(
    raw_path: Path = RAW_INPUT,
    static_path: Path = STATIC_INPUT,
) -> pd.DataFrame:
    """Return one row per V3 pool update-day using the static pool registry.

    ``volumeUSD`` is a daily flow and ``tvlUSD`` is the last reported stock for
    that update-day.  Gross fee opportunity is reconstructed from the static
    fee tier in pips.  Historical raw ``feesUSD`` is retained only to verify
    that reconstruction where the source happens to include it.
    """

    if not static_path.is_file():
        raise FileNotFoundError(static_path)
    connection = duckdb.connect()
    try:
        connection.execute("PRAGMA threads=8")
        connection.execute("PRAGMA preserve_insertion_order=false")
        frame = connection.execute(
            """
            WITH daily AS (
                SELECT
                    to_timestamp(TRY_CAST(date AS BIGINT))::DATE AS origin_date,
                    lower(pool.id) AS pool,
                    TRY_CAST(feesUSD AS DOUBLE) AS reported_fees_usd,
                    TRY_CAST(volumeUSD AS DOUBLE) AS volume_usd,
                    TRY_CAST(tvlUSD AS DOUBLE) AS tvl_usd
                FROM read_json_auto(
                    ?, format='newline_delimited', union_by_name=true
                )
                WHERE pool.id IS NOT NULL
            ),
            statics AS (
                SELECT
                    lower(id) AS pool,
                    TRY_CAST(feeTier AS INTEGER) AS fee_tier,
                    lower(token0.id) AS token0_address,
                    token0.symbol AS token0_symbol,
                    lower(token1.id) AS token1_address,
                    token1.symbol AS token1_symbol
                FROM read_json_auto(
                    ?, format='newline_delimited', union_by_name=true
                )
            )
            SELECT
                d.origin_date,
                d.pool,
                s.token0_address,
                s.token0_symbol,
                s.token1_address,
                s.token1_symbol,
                s.fee_tier,
                d.volume_usd * s.fee_tier / 1000000.0 AS gross_fees_usd,
                d.volume_usd * s.fee_tier / 1000000.0 AS fees_usd,
                d.volume_usd,
                d.tvl_usd,
                d.reported_fees_usd,
                abs(
                    d.reported_fees_usd
                    - d.volume_usd * s.fee_tier / 1000000.0
                ) AS fee_reconciliation_abs_error,
                'volume_x_static_fee_tier' AS fees_source,
                'deprecated_alias_of_gross_fees_usd' AS fees_usd_semantics,
                'last_reported_update_day_stock' AS tvl_measure
            FROM daily d
            JOIN statics s USING (pool)
            WHERE d.origin_date IS NOT NULL
              AND d.volume_usd IS NOT NULL
              AND d.volume_usd >= 0
              AND d.tvl_usd IS NOT NULL
              AND d.tvl_usd >= 0
              AND s.token0_address IS NOT NULL
              AND s.token1_address IS NOT NULL
              AND s.fee_tier > 0
              AND s.fee_tier <= 1000000
            ORDER BY d.origin_date, d.pool
            """,
            [_daily_glob(raw_path), str(static_path)],
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
        "fee_tier",
        "gross_fees_usd",
        "fees_usd",
        "volume_usd",
        "tvl_usd",
        "fees_source",
        "fees_usd_semantics",
        "tvl_measure",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V3 pool-day fee panel lacks columns: {missing}")
    if frame.empty:
        raise ValueError("V3 pool-day fee panel is empty")
    if frame.duplicated(["origin_date", "pool"]).any():
        raise ValueError("V3 pool-day fee input has duplicate pool-days")
    for column in (
        "gross_fees_usd",
        "fees_usd",
        "volume_usd",
        "tvl_usd",
        "fee_tier",
    ):
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"V3 pool-day fee panel has missing {column}")
        if (values < 0).any():
            raise ValueError(f"V3 pool-day fee panel has negative {column}")
    if not np.allclose(frame["gross_fees_usd"], frame["fees_usd"]):
        raise ValueError("V3 compatibility fee field differs from gross fees")
    if not frame["fees_source"].eq("volume_x_static_fee_tier").all():
        raise ValueError("V3 pool-day fee panel has an unknown fee source")
    if not frame["fees_usd_semantics"].eq(
        "deprecated_alias_of_gross_fees_usd"
    ).all():
        raise ValueError("V3 compatibility fee alias is not explicitly labelled")
    reported = pd.to_numeric(frame.get("reported_fees_usd"), errors="coerce")
    derived = pd.to_numeric(frame["fees_usd"], errors="coerce")
    comparable = reported.notna()
    if comparable.any() and not np.isclose(
        reported[comparable],
        derived[comparable],
        rtol=FEE_RECONCILIATION_TOLERANCE,
        atol=FEE_RECONCILIATION_TOLERANCE,
    ).all():
        raise ValueError("derived V3 fees disagree with retained raw fees")


def run(
    *,
    raw_path: Path = RAW_INPUT,
    static_path: Path = STATIC_INPUT,
    output_path: Path = OUTPUT,
) -> int:
    if raw_path.is_dir():
        require_pool_daily_coverage(
            "uniswap_v3",
            sorted(raw_path.glob("uniswap_v3_daily_*.jsonl.gz")),
        )
    frame = build_v3_pool_day_fees(raw_path, static_path)
    first_date = pd.Timestamp(frame["origin_date"].min()).normalize()
    last_date = pd.Timestamp(frame["origin_date"].max()).normalize()
    if raw_path.is_dir() and (
        first_date != EXPECTED_FIRST_DATE or last_date != EXPECTED_LAST_DATE
    ):
        raise ValueError(
            "full-history V3 daily coverage mismatch: "
            f"{first_date.date()} through {last_date.date()}"
        )
    write_panel(
        frame,
        output_path,
        code_sources=CODE_SOURCES,
        inputs=[raw_path, static_path],
        notes=(
            "Full-history Uniswap V3 pool update-day panel. Gross fee "
            "opportunity equals daily volume times the validated static fee "
            "tier; TVL is the last reported stock on an observed update-day."
        ),
        preinstall_validator=lambda path: validate_v3_pool_day_fees(
            pd.read_parquet(path)
        ),
    )
    print(f"wrote {len(frame):,} V3 pool-day fee rows to {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_INPUT)
    parser.add_argument("--statics", type=Path, default=STATIC_INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    return run(
        raw_path=args.raw,
        static_path=args.statics,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

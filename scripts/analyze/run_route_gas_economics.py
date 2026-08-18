#!/usr/bin/env python3
"""Measure the fixed gas hurdle attached to extra-hop vehicle routes.

This exploratory exhibit is narrower than the route-cost benchmark. It does not
quote the direct and vehicle alternatives at a common pool state. It asks only
how much receipt-measured gas the executed route used, and how large the
extra-hop gas toll is at contemporaneous gas and WETH prices.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


ROUTE_GAS_INPUT = DATA_DIR / "processed/route_gas_units.parquet"
WETH_PRICE_INPUT = DATA_DIR / "processed/v2_token_price_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/route_gas_economics.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/route_gas_economics_support.jsonl"

WETH_ADDRESS = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
FOCUS_CLASS = "stable_vehicle"
FEASIBILITY_BPS_THRESHOLDS = (1, 10, 25)
CODE_SOURCES = [
    "scripts/analyze/run_route_gas_economics.py",
    "src/ddvc/ethereum_receipts.py",
]
INPUTS = [
    "data/processed/route_gas_units.parquet",
    "data/processed/v2_token_price_daily.parquet",
]


ROUTE_CLASS_BY_MID_TYPE = {
    "direct": "direct",
    "stable": "stable_vehicle",
    "native": "native_vehicle",
    "multi": "multi_vehicle",
    "imported": "other_vehicle",
    "staked_native": "other_vehicle",
    "other": "other_vehicle",
}


def load_route_gas(path: Path = ROUTE_GAS_INPUT) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = {
        "date",
        "year",
        "tx_hash",
        "legs",
        "mid_type",
        "gas_vehicle",
        "route_notional_usd",
        "effective_gas_price_wei",
        "gas_used",
        "status",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"route-gas panel lacks columns: {missing}")
    return frame.copy()


def load_weth_prices(path: Path = WETH_PRICE_INPUT) -> pd.DataFrame:
    frame = pd.read_parquet(path, filters=[("token", "=", WETH_ADDRESS)])
    required = {"date", "token", "price_usd"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"WETH price panel lacks columns: {missing}")
    prices = frame.loc[:, ["date", "price_usd"]].copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    prices = prices.dropna(subset=["price_usd"])
    prices = prices[prices["price_usd"].astype(float).gt(0.0)]
    if prices.empty:
        raise ValueError("WETH price panel has no positive observations")
    return prices.drop_duplicates("date", keep="last")


def prepared_gas_panel(
    route_gas: pd.DataFrame,
    weth_prices: pd.DataFrame,
) -> pd.DataFrame:
    panel = route_gas.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="raise").dt.normalize()
    panel = panel.merge(weth_prices, on="date", how="left", validate="many_to_one")
    panel["route_class"] = (
        panel["mid_type"].astype(str).map(ROUTE_CLASS_BY_MID_TYPE).fillna("other_vehicle")
    )
    numeric = [
        "year",
        "legs",
        "route_notional_usd",
        "effective_gas_price_wei",
        "gas_used",
        "price_usd",
    ]
    for column in numeric:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    panel = panel[
        panel["status"].eq(1)
        & panel["gas_used"].gt(0.0)
        & panel["route_notional_usd"].gt(0.0)
        & panel["effective_gas_price_wei"].ge(0.0)
        & panel["price_usd"].gt(0.0)
    ].copy()
    if panel.empty:
        raise ValueError("route-gas economics panel is empty after support filters")
    panel["gas_price_gwei"] = panel["effective_gas_price_wei"].astype(float) / 1e9
    panel["gas_cost_usd"] = (
        panel["gas_used"].astype(float)
        * panel["effective_gas_price_wei"].astype(float)
        / 1e18
        * panel["price_usd"].astype(float)
    )
    panel["gas_cost_bps"] = (
        10_000.0
        * panel["gas_cost_usd"].astype(float)
        / panel["route_notional_usd"].astype(float)
    )
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["gas_price_gwei", "gas_cost_usd", "gas_cost_bps"]
    )
    if panel.empty:
        raise ValueError("route-gas economics panel lost all finite cost rows")
    return panel


def annual_route_class_summaries(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (year, route_class), group in panel.groupby(["year", "route_class"], sort=True):
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "annual_route_class_gas",
                "year": int(year),
                "route_class": str(route_class),
                "observations": int(len(group)),
                "median_gas_units": float(group["gas_used"].median()),
                "p75_gas_units": float(group["gas_used"].quantile(0.75)),
                "median_gas_price_gwei": float(group["gas_price_gwei"].median()),
                "median_weth_price_usd": float(group["price_usd"].median()),
                "median_route_notional_usd": float(group["route_notional_usd"].median()),
                "median_gas_cost_usd": float(group["gas_cost_usd"].median()),
                "median_gas_cost_bps": float(group["gas_cost_bps"].median()),
                "interpretation": (
                    "executed-route receipt gas by observed route class; not a "
                    "same-state direct-versus-vehicle quote comparison"
                ),
            }
        )
    return pd.DataFrame(rows)


def extra_hop_hurdles(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, group in panel.groupby("year", sort=True):
        direct = group[group["route_class"].eq("direct")]
        if direct.empty:
            continue
        direct_median_gas = float(direct["gas_used"].median())
        median_gas_price_gwei = float(group["gas_price_gwei"].median())
        median_weth_price_usd = float(group["price_usd"].median())
        for route_class in ("stable_vehicle", "native_vehicle", "multi_vehicle"):
            route_group = group[group["route_class"].eq(route_class)]
            if route_group.empty:
                continue
            route_median_gas = float(route_group["gas_used"].median())
            extra_gas_units = route_median_gas - direct_median_gas
            extra_gas_cost_usd = (
                extra_gas_units * median_gas_price_gwei * 1e-9 * median_weth_price_usd
            )
            rows.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "record_type": "extra_hop_gas_hurdle",
                    "year": int(year),
                    "route_class": route_class,
                    "direct_median_gas_units": direct_median_gas,
                    "route_median_gas_units": route_median_gas,
                    "extra_gas_units": extra_gas_units,
                    "extra_gas_units_pct_of_direct": extra_gas_units / direct_median_gas,
                    "median_gas_price_gwei": median_gas_price_gwei,
                    "median_weth_price_usd": median_weth_price_usd,
                    "extra_gas_cost_usd_at_year_medians": extra_gas_cost_usd,
                    "notional_for_extra_gas_1bp_usd": extra_gas_cost_usd * 10_000.0,
                    "notional_for_extra_gas_10bp_usd": extra_gas_cost_usd * 1_000.0,
                    "route_median_notional_usd": float(route_group["route_notional_usd"].median()),
                    "observations": int(len(route_group)),
                    "direct_observations": int(len(direct)),
                    "interpretation": (
                        "fixed extra-hop gas toll evaluated at annual median gas and WETH prices; "
                        "not a full route-cost comparison"
                    ),
                }
            )
    return pd.DataFrame(rows)


def endpoint_hurdle_change(hurdles: pd.DataFrame) -> pd.DataFrame:
    focus = hurdles[
        hurdles["record_type"].eq("extra_hop_gas_hurdle")
        & hurdles["route_class"].eq(FOCUS_CLASS)
        & hurdles["year"].isin([BASELINE_YEAR, COMPARISON_YEAR])
    ].copy()
    if len(focus) != 2:
        raise ValueError("stable-vehicle endpoint gas hurdle rows are missing")
    base = focus[focus["year"].eq(BASELINE_YEAR)].iloc[0]
    end = focus[focus["year"].eq(COMPARISON_YEAR)].iloc[0]
    rows = [
        {
            "analysis_status": "exploratory_descriptive",
            "record_type": "endpoint_extra_hop_hurdle_change",
            "route_class": FOCUS_CLASS,
            "baseline_year": BASELINE_YEAR,
            "comparison_year": COMPARISON_YEAR,
            "baseline_extra_gas_units": float(base["extra_gas_units"]),
            "comparison_extra_gas_units": float(end["extra_gas_units"]),
            "baseline_extra_gas_cost_usd_at_year_medians": float(
                base["extra_gas_cost_usd_at_year_medians"]
            ),
            "comparison_extra_gas_cost_usd_at_year_medians": float(
                end["extra_gas_cost_usd_at_year_medians"]
            ),
            "baseline_notional_for_extra_gas_1bp_usd": float(
                base["notional_for_extra_gas_1bp_usd"]
            ),
            "comparison_notional_for_extra_gas_1bp_usd": float(
                end["notional_for_extra_gas_1bp_usd"]
            ),
            "baseline_notional_for_extra_gas_10bp_usd": float(
                base["notional_for_extra_gas_10bp_usd"]
            ),
            "comparison_notional_for_extra_gas_10bp_usd": float(
                end["notional_for_extra_gas_10bp_usd"]
            ),
            "extra_gas_cost_usd_change": float(
                end["extra_gas_cost_usd_at_year_medians"]
                - base["extra_gas_cost_usd_at_year_medians"]
            ),
            "one_bp_notional_ratio": float(
                end["notional_for_extra_gas_1bp_usd"]
                / base["notional_for_extra_gas_1bp_usd"]
            ),
            "interpretation": (
                "endpoint-year change in stable-vehicle fixed gas hurdle; "
                "descriptive execution-friction evidence only"
            ),
        }
    ]
    return pd.DataFrame(rows)


def stable_route_feasibility_distribution(
    panel: pd.DataFrame,
    hurdles: pd.DataFrame,
) -> pd.DataFrame:
    """Measure how often the fixed stable-vehicle gas toll is economically small.

    The annual hurdle supplies a stable-minus-direct median gas-unit difference.
    Each executed stable-vehicle route then prices that fixed unit toll using
    its own receipt gas price and same-day WETH price. The result is still not a
    same-state direct-versus-vehicle quote comparison: it excludes pool price
    impact, fee-tier differences, and untraded alternatives.
    """

    stable_hurdles = hurdles[
        hurdles["record_type"].eq("extra_hop_gas_hurdle")
        & hurdles["route_class"].eq(FOCUS_CLASS)
    ].loc[:, ["year", "extra_gas_units"]]
    sample = panel[panel["route_class"].eq(FOCUS_CLASS)].merge(
        stable_hurdles,
        on="year",
        how="left",
        validate="many_to_one",
    )
    sample = sample[
        sample["extra_gas_units"].gt(0.0)
        & sample["route_notional_usd"].gt(0.0)
        & sample["gas_price_gwei"].ge(0.0)
        & sample["price_usd"].gt(0.0)
    ].copy()
    if sample.empty:
        raise ValueError("stable route gas-feasibility sample is empty")
    sample["fixed_extra_hop_toll_usd"] = (
        sample["extra_gas_units"].astype(float)
        * sample["gas_price_gwei"].astype(float)
        * 1e-9
        * sample["price_usd"].astype(float)
    )
    sample["fixed_extra_hop_toll_bps"] = (
        10_000.0
        * sample["fixed_extra_hop_toll_usd"].astype(float)
        / sample["route_notional_usd"].astype(float)
    )
    sample = sample.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["fixed_extra_hop_toll_usd", "fixed_extra_hop_toll_bps"]
    )
    if sample.empty:
        raise ValueError("stable route gas-feasibility sample lost all finite rows")

    rows: list[dict[str, object]] = []
    yearly_rows: dict[int, dict[str, object]] = {}
    for year, group in sample.groupby("year", sort=True):
        row: dict[str, object] = {
            "analysis_status": "exploratory_descriptive",
            "record_type": "stable_route_fixed_toll_feasibility",
            "route_class": FOCUS_CLASS,
            "year": int(year),
            "observations": int(len(group)),
            "median_route_notional_usd": float(group["route_notional_usd"].median()),
            "median_fixed_extra_hop_toll_usd": float(
                group["fixed_extra_hop_toll_usd"].median()
            ),
            "median_fixed_extra_hop_toll_bps": float(
                group["fixed_extra_hop_toll_bps"].median()
            ),
            "p75_fixed_extra_hop_toll_bps": float(
                group["fixed_extra_hop_toll_bps"].quantile(0.75)
            ),
            "interpretation": (
                "annual median stable-minus-direct gas-unit toll priced at each "
                "executed stable-vehicle route's receipt gas price and WETH price; "
                "not an all-in direct-versus-vehicle quote comparison"
            ),
        }
        for threshold in FEASIBILITY_BPS_THRESHOLDS:
            row[f"share_fixed_toll_le_{threshold}bp"] = float(
                group["fixed_extra_hop_toll_bps"].le(threshold).mean()
            )
        rows.append(row)
        yearly_rows[int(year)] = row

    if BASELINE_YEAR in yearly_rows and COMPARISON_YEAR in yearly_rows:
        base = yearly_rows[BASELINE_YEAR]
        end = yearly_rows[COMPARISON_YEAR]
        rows.append(
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "stable_route_fixed_toll_feasibility_change",
                "route_class": FOCUS_CLASS,
                "baseline_year": BASELINE_YEAR,
                "comparison_year": COMPARISON_YEAR,
                "baseline_median_route_notional_usd": float(
                    base["median_route_notional_usd"]
                ),
                "comparison_median_route_notional_usd": float(
                    end["median_route_notional_usd"]
                ),
                "baseline_median_fixed_extra_hop_toll_bps": float(
                    base["median_fixed_extra_hop_toll_bps"]
                ),
                "comparison_median_fixed_extra_hop_toll_bps": float(
                    end["median_fixed_extra_hop_toll_bps"]
                ),
                "baseline_share_fixed_toll_le_10bp": float(
                    base["share_fixed_toll_le_10bp"]
                ),
                "comparison_share_fixed_toll_le_10bp": float(
                    end["share_fixed_toll_le_10bp"]
                ),
                "baseline_share_fixed_toll_le_25bp": float(
                    base["share_fixed_toll_le_25bp"]
                ),
                "comparison_share_fixed_toll_le_25bp": float(
                    end["share_fixed_toll_le_25bp"]
                ),
                "median_notional_ratio": float(
                    end["median_route_notional_usd"]
                    / base["median_route_notional_usd"]
                ),
                "median_toll_bps_change": float(
                    end["median_fixed_extra_hop_toll_bps"]
                    - base["median_fixed_extra_hop_toll_bps"]
                ),
                "share_10bp_change": float(
                    end["share_fixed_toll_le_10bp"]
                    - base["share_fixed_toll_le_10bp"]
                ),
                "share_25bp_change": float(
                    end["share_fixed_toll_le_25bp"]
                    - base["share_fixed_toll_le_25bp"]
                ),
                "interpretation": (
                    "change in stable-vehicle route-level fixed gas-feasibility "
                    "distribution; descriptive execution-friction evidence only"
                ),
            }
        )
    return pd.DataFrame(rows)


def support_rows(panel: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "analysis_status": "exploratory_descriptive",
                "record_type": "support",
                "route_gas_input": str(ROUTE_GAS_INPUT.relative_to(REPO_ROOT)),
                "weth_price_input": str(WETH_PRICE_INPUT.relative_to(REPO_ROOT)),
                "rows": int(len(panel)),
                "first_date": panel["date"].min().strftime("%Y-%m-%d"),
                "last_date": panel["date"].max().strftime("%Y-%m-%d"),
                "years": ",".join(str(year) for year in sorted(panel["year"].unique())),
                "route_classes": ",".join(sorted(panel["route_class"].unique())),
                "boundary": (
                    "receipt gas and contemporaneous WETH price only; excludes pool price impact, "
                    "fee-tier quote differences, private order flow, and reverted alternatives"
                ),
            }
        ]
    )


def run(
    *,
    route_gas_path: Path = ROUTE_GAS_INPUT,
    weth_price_path: Path = WETH_PRICE_INPUT,
    output_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    panel = prepared_gas_panel(
        load_route_gas(route_gas_path),
        load_weth_prices(weth_price_path),
    )
    annual = annual_route_class_summaries(panel)
    hurdles = extra_hop_hurdles(panel)
    feasibility = stable_route_feasibility_distribution(panel, hurdles)
    results = pd.concat(
        [annual, hurdles, endpoint_hurdle_change(hurdles), feasibility],
        ignore_index=True,
    )
    write_exhibit(results, output_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support_rows(panel), support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    print(f"wrote {len(results)} route-gas economics rows and 1 support row")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-gas", type=Path, default=ROUTE_GAS_INPUT)
    parser.add_argument("--weth-prices", type=Path, default=WETH_PRICE_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        route_gas_path=args.route_gas,
        weth_price_path=args.weth_prices,
        output_path=args.output,
        support_path=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())

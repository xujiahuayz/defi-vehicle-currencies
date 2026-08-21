#!/usr/bin/env python3
"""Compare gross and gas-adjusted stablecoin-versus-WETH path output.

The unit is a realised exact two-leg route for which both vehicle families are
feasible at the same input and pre-transaction state.  Receipt gas is predicted
from a separate sample of single-component route transactions using the ordered
venue sequence, the observed transaction callee, and route complexity.  The
executed transaction's effective gas price and the same-day WETH price convert
gas units to dollars.  Results are descriptive execution-cost comparisons.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.route_gas import RouteGasEstimator
from ddvc.tables import write_report
from scripts.analyze.run_contestable_vehicle_choice import prepare_frontier


FRONTIER = DATA_DIR / "processed/exact_vehicle_frontier_monthly.parquet"
ROUTE_GAS = DATA_DIR / "processed/route_gas_units.parquet"
RECEIPTS = DATA_DIR / "processed/contestable_route_receipts.parquet"
WETH_PRICES = DATA_DIR / "processed/v2_token_price_daily.parquet"
UNIFIED = DATA_DIR / "unified"
OUTPUT = OUTPUT_DIR / "exhibits/gas_adjusted_vehicle_consequences.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/gas_adjusted_vehicle_consequences_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
MIN_SHORTFALL_BPS = 1.0
SIZE_BINS = (
    ("usd_100_to_999", 100.0, 1_000.0),
    ("usd_1k_to_9_999", 1_000.0, 10_000.0),
    ("usd_10k_to_99_999", 10_000.0, 100_000.0),
    ("usd_100k_plus", 100_000.0, float("inf")),
)


def output_token_prices(frontier: pd.DataFrame, unified: Path) -> pd.DataFrame:
    """Recover the output-token dollar price already used by each realised route."""

    wanted = set(frontier["route_id"].astype(str))
    rows: list[pd.DataFrame] = []
    for day in sorted(frontier["day"].astype(str).unique()):
        path = unified / f"{day}.parquet"
        if not path.is_file():
            continue
        legs = pd.read_parquet(path, columns=LINEAR_ROUTE_COLUMNS)
        routes = extract_linear_realised_routes(legs)
        routes = routes[routes["route_id"].astype(str).isin(wanted)]
        if routes.empty:
            continue
        rows.append(
            routes.loc[:, ["route_id", "realised_amount_out", "output_usd"]]
        )
    if not rows:
        raise RuntimeError("unified route days supply no output-token prices")
    prices = pd.concat(rows, ignore_index=True)
    if prices["route_id"].duplicated().any():
        raise ValueError("realised route output prices are duplicated")
    prices["output_token_price_usd"] = (
        pd.to_numeric(prices["output_usd"], errors="coerce")
        / pd.to_numeric(prices["realised_amount_out"], errors="coerce")
    )
    prices = prices[
        prices["output_token_price_usd"].gt(0)
        & np.isfinite(prices["output_token_price_usd"])
    ].copy()
    return prices.loc[:, ["route_id", "output_token_price_usd"]]


def load_weth_prices(path: Path) -> pd.DataFrame:
    prices = pd.read_parquet(path, filters=[("token", "=", WETH)])
    prices = prices.loc[:, ["date", "price_usd"]].copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    prices["weth_price_usd"] = pd.to_numeric(prices["price_usd"], errors="coerce")
    prices = prices[prices["weth_price_usd"].gt(0)].drop_duplicates("date", keep="last")
    return prices.loc[:, ["date", "weth_price_usd"]]


def validation_rows(route_gas: pd.DataFrame) -> pd.DataFrame:
    """Evaluate gas predictions on a deterministic transaction-level holdout."""

    data = route_gas.copy()
    data["tx_hash"] = data["tx_hash"].astype(str).str.lower()
    test_mask = data["tx_hash"].str[-1].isin(list("012"))
    training = data[~test_mask].copy()
    test = data[test_mask].copy()
    estimator = RouteGasEstimator(training)
    prediction = estimator.predict(test)
    actual = pd.to_numeric(test["gas_used"], errors="raise").to_numpy(dtype=float)
    baseline_lookup = training.groupby("legs")["gas_used"].median()
    baseline = test["legs"].map(baseline_lookup).to_numpy(dtype=float)
    test = test.assign(
        predicted=prediction.median,
        predicted_p25=prediction.p25,
        predicted_p75=prediction.p75,
        actual=actual,
        baseline=baseline,
    )
    rows: list[dict[str, object]] = []
    for sample, group in (
        ("all_routes", test),
        ("exact_two_leg_routes", test[test["legs"].eq(2)]),
    ):
        if group.empty:
            continue
        absolute = (group["predicted"] - group["actual"]).abs()
        baseline_absolute = (group["baseline"] - group["actual"]).abs()
        rows.append(
            {
                "record_type": "held_out_gas_validation",
                "sample": sample,
                "training_transactions": int(len(training)),
                "test_transactions": int(len(group)),
                "median_actual_gas_units": float(group["actual"].median()),
                "median_absolute_error_gas_units": float(absolute.median()),
                "median_absolute_percentage_error": float(
                    (absolute / group["actual"]).median()
                ),
                "legs_only_median_absolute_error_gas_units": float(
                    baseline_absolute.median()
                ),
                "legs_only_median_absolute_percentage_error": float(
                    (baseline_absolute / group["actual"]).median()
                ),
                "interquartile_interval_coverage": float(
                    group["actual"].between(
                        group["predicted_p25"], group["predicted_p75"]
                    ).mean()
                ),
                "holdout_rule": "transaction_hash_final_hex_in_0_1_2",
                "predictors": (
                    "transaction_callee_class+ordered_venue_sequence+year+"
                    "route_legs+cross_venue_indicator"
                ),
            }
        )
    return pd.DataFrame(rows)


def attach_gas_predictions(
    frontier: pd.DataFrame,
    route_gas: pd.DataFrame,
    receipts: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    validation = validation_rows(route_gas)
    estimator = RouteGasEstimator(route_gas)
    receipt_columns = [
        "tx_hash",
        "tx_to",
        "effective_gas_price_wei",
        "gas_used",
        "status",
    ]
    missing = sorted(set(receipt_columns) - set(receipts.columns))
    if missing:
        raise ValueError(f"contestable receipt panel lacks columns: {missing}")
    data = frontier.merge(
        receipts.loc[:, receipt_columns],
        on="tx_hash",
        how="left",
        validate="many_to_one",
    )
    data["receipt_matched"] = data["tx_to"].notna()
    data = data[
        data["receipt_matched"]
        & data["status"].eq(1)
        & pd.to_numeric(data["effective_gas_price_wei"], errors="coerce").gt(0)
    ].copy()
    if data.empty:
        raise ValueError("no contestable routes have usable receipt attributes")

    common = {
        "year": data["year"].astype(int),
        "legs": 2,
        "tx_to": data["tx_to"],
    }
    stable_request = pd.DataFrame(
        {**common, "venue_sequence": data["stable_public_venues"]}
    )
    native_request = pd.DataFrame(
        {**common, "venue_sequence": data["native_public_venues"]}
    )
    stable = estimator.predict(stable_request)
    native = estimator.predict(native_request)
    for family, prediction in (("stable", stable), ("native", native)):
        data[f"{family}_gas_median"] = prediction.median
        data[f"{family}_gas_p25"] = prediction.p25
        data[f"{family}_gas_p75"] = prediction.p75
        data[f"{family}_gas_support"] = prediction.support
    return data, validation


def _scenario_units(data: pd.DataFrame, scenario: str) -> tuple[np.ndarray, np.ndarray]:
    chosen_stable = data["chosen_stable"].to_numpy(dtype=bool)
    if scenario == "gross":
        zeros = np.zeros(len(data), dtype=float)
        return zeros, zeros
    if scenario == "central":
        stable = data["stable_gas_median"].to_numpy(dtype=float)
        native = data["native_gas_median"].to_numpy(dtype=float)
    elif scenario == "chosen_favorable_bound":
        stable = np.where(
            chosen_stable, data["stable_gas_p25"], data["stable_gas_p75"]
        ).astype(float)
        native = np.where(
            chosen_stable, data["native_gas_p75"], data["native_gas_p25"]
        ).astype(float)
    elif scenario == "chosen_unfavorable_bound":
        stable = np.where(
            chosen_stable, data["stable_gas_p75"], data["stable_gas_p25"]
        ).astype(float)
        native = np.where(
            chosen_stable, data["native_gas_p25"], data["native_gas_p75"]
        ).astype(float)
    else:
        raise ValueError(f"unknown gas scenario: {scenario}")
    return stable, native


def consequence_panel(data: pd.DataFrame, scenario: str) -> pd.DataFrame:
    stable_units, native_units = _scenario_units(data, scenario)
    gas_price = pd.to_numeric(data["effective_gas_price_wei"], errors="raise").to_numpy(dtype=float)
    eth_price = pd.to_numeric(data["weth_price_usd"], errors="raise").to_numpy(dtype=float)
    stable_gas_usd = stable_units * gas_price / 1e18 * eth_price
    native_gas_usd = native_units * gas_price / 1e18 * eth_price
    output_price = data["output_token_price_usd"].to_numpy(dtype=float)
    stable_gross = data["stable_public_out"].to_numpy(dtype=float) * output_price
    native_gross = data["native_public_out"].to_numpy(dtype=float) * output_price
    stable_net = stable_gross - stable_gas_usd
    native_net = native_gross - native_gas_usd
    chosen_stable = data["chosen_stable"].to_numpy(dtype=bool)
    chosen_net = np.where(chosen_stable, stable_net, native_net)
    rival_net = np.where(chosen_stable, native_net, stable_net)
    shortfall_usd = np.maximum(rival_net - chosen_net, 0.0)
    shortfall_bps = np.divide(
        10_000.0 * shortfall_usd,
        chosen_net,
        out=np.full(len(data), np.nan),
        where=chosen_net > 0,
    )
    gross_chosen = np.where(chosen_stable, stable_gross, native_gross)
    gross_rival = np.where(chosen_stable, native_gross, stable_gross)
    gross_lower = gross_rival - gross_chosen > gross_chosen * MIN_SHORTFALL_BPS / 10_000.0
    out = data.copy()
    out["gas_scenario"] = scenario
    out["chosen_path_gas_usd"] = np.where(chosen_stable, stable_gas_usd, native_gas_usd)
    out["rival_path_gas_usd"] = np.where(chosen_stable, native_gas_usd, stable_gas_usd)
    out["chosen_net_output_usd"] = chosen_net
    out["rival_net_output_usd"] = rival_net
    out["net_shortfall_usd"] = shortfall_usd
    out["net_shortfall_bps"] = shortfall_bps
    out["net_lower_output"] = shortfall_bps > MIN_SHORTFALL_BPS
    out["gross_lower_output"] = gross_lower
    out["ranking_changes_after_gas"] = out["net_lower_output"].ne(gross_lower)
    out["positive_net_outputs"] = (stable_net > 0) & (native_net > 0)
    return out


def summary_row(
    frame: pd.DataFrame,
    *,
    scenario: str,
    size_group: str,
) -> dict[str, object]:
    valid = frame[
        frame["positive_net_outputs"]
        & frame["net_shortfall_bps"].notna()
        & np.isfinite(frame["net_shortfall_bps"])
    ].copy()
    if valid.empty:
        raise ValueError(f"gas consequence cell is empty: {scenario}/{size_group}")
    lower = valid["net_lower_output"].astype(bool)
    thresholded_bps = valid["net_shortfall_bps"].where(lower, 0.0)
    conditional = valid.loc[lower, "net_shortfall_bps"]
    weights = valid["input_usd"].astype(float)
    return {
        "record_type": "gas_adjusted_vehicle_consequence",
        "gas_scenario": scenario,
        "size_group": size_group,
        "routes": int(len(valid)),
        "ordered_pairs": int(valid["ordered_pair"].nunique()),
        "dates": int(valid["day"].nunique()),
        "input_value_usd": float(weights.sum()),
        "lower_output_routes": int(lower.sum()),
        "lower_output_route_share": float(lower.mean()),
        "input_value_weighted_shortfall_bps": float(
            np.average(thresholded_bps, weights=weights)
        ),
        "median_shortfall_bps_if_over_1bp": (
            float(conditional.median()) if len(conditional) else np.nan
        ),
        "p90_shortfall_bps_if_over_1bp": (
            float(conditional.quantile(0.9)) if len(conditional) else np.nan
        ),
        "total_shortfall_usd": float(
            valid["net_shortfall_usd"].where(lower, 0.0).sum()
        ),
        "median_chosen_path_gas_usd": float(valid["chosen_path_gas_usd"].median()),
        "median_rival_path_gas_usd": float(valid["rival_path_gas_usd"].median()),
        "ranking_change_share_after_gas": float(
            valid["ranking_changes_after_gas"].mean()
        ),
        "positive_net_output_share_before_cell_filter": float(
            frame["positive_net_outputs"].mean()
        ),
        "shortfall_threshold_bps": MIN_SHORTFALL_BPS,
        "weighting": "observed_route_input_value_usd",
        "causal_interpretation": False,
    }


def consequence_rows(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for scenario in (
        "gross",
        "central",
        "chosen_favorable_bound",
        "chosen_unfavorable_bound",
    ):
        panel = consequence_panel(data, scenario)
        rows.append(summary_row(panel, scenario=scenario, size_group="all"))
        for label, lower, upper in SIZE_BINS:
            cell = panel[
                panel["input_usd"].ge(lower) & panel["input_usd"].lt(upper)
            ]
            if not cell.empty:
                rows.append(summary_row(cell, scenario=scenario, size_group=label))
    return pd.DataFrame(rows)


def run(
    *,
    frontier_path: Path,
    route_gas_path: Path,
    receipts_path: Path,
    weth_prices_path: Path,
    unified: Path,
    output: Path,
    support: Path,
) -> int:
    raw_frontier = pd.read_parquet(frontier_path)
    frontier, selection = prepare_frontier(raw_frontier)
    frontier = frontier[frontier["symmetric_common_support"]].copy()
    frontier["year"] = frontier["date"].dt.year.astype(int)
    frontier["tx_hash"] = frontier["route_id"].astype(str).str.split(":", n=1).str[0]
    prices = output_token_prices(frontier, unified)
    frontier = frontier.merge(prices, on="route_id", how="left", validate="one_to_one")
    frontier = frontier.merge(
        load_weth_prices(weth_prices_path), on="date", how="left", validate="many_to_one"
    )
    frontier = frontier.dropna(subset=["output_token_price_usd", "weth_price_usd"])
    route_gas = pd.read_parquet(route_gas_path)
    receipts = pd.read_parquet(receipts_path)
    panel, validation = attach_gas_predictions(frontier, route_gas, receipts)
    results = consequence_rows(panel)
    support_rows = pd.concat(
        [
            validation,
            pd.DataFrame(
                [
                    {
                        "record_type": "gas_adjusted_vehicle_consequence_support",
                        **selection,
                        "common_support_rows_with_output_price": int(len(frontier)),
                        "rows_with_receipt_and_gas_prediction": int(len(panel)),
                        "receipt_match_share": float(len(panel) / len(frontier)),
                        "gas_training_transactions": int(len(route_gas)),
                        "gas_training_routers": int(route_gas["tx_to"].nunique()),
                        "gas_training_first_date": str(pd.to_datetime(route_gas["date"]).min().date()),
                        "gas_training_last_date": str(pd.to_datetime(route_gas["date"]).max().date()),
                        "gas_measure": "total successful transaction receipt gas",
                        "gas_price_measure": "executed_transaction_effective_gas_price",
                        "native_price_measure": "same_day_weth_usd",
                        "boundary": (
                            "total transaction gas includes router transfers and bookkeeping; "
                            "predicted rival-path gas is descriptive and is not an execution trace"
                        ),
                    }
                ]
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    write_report(results, output)
    write_report(support_rows, support)
    print(results.to_string(index=False))
    print(f"wrote {len(results)} gas consequence rows and {len(support_rows)} support rows")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier", type=Path, default=FRONTIER)
    parser.add_argument("--route-gas", type=Path, default=ROUTE_GAS)
    parser.add_argument("--receipts", type=Path, default=RECEIPTS)
    parser.add_argument("--weth-prices", type=Path, default=WETH_PRICES)
    parser.add_argument("--unified", type=Path, default=UNIFIED)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    args = parser.parse_args()
    return run(
        frontier_path=args.frontier,
        route_gas_path=args.route_gas,
        receipts_path=args.receipts,
        weth_prices_path=args.weth_prices,
        unified=args.unified,
        output=args.output,
        support=args.support,
    )


if __name__ == "__main__":
    raise SystemExit(main())

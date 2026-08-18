#!/usr/bin/env python3
"""Screen stable-vehicle identity around the March 2023 USDC stress weekend.

This is an exploratory stress-event screen. It asks whether route use inside the
stablecoin vehicle class immediately left USDC during the SVB/USDC depeg window.
It is descriptive: the episode changed prices, arbitrage incentives, and token
demand at the same time, so it is not a treatment design.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/stable_stress_event.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/stable_stress_event_support.jsonl"
CODE_SOURCES = ["scripts/analyze/run_stable_stress_event.py"]
INPUTS = ["data/processed/liquidity_capital_v2_candidate_day.parquet"]
STABLE_SYMBOLS = ("DAI", "USDC", "USDT")
FIVE_CANDIDATE_SYMBOLS = ("DAI", "USDC", "USDT", "WBTC", "WETH")


@dataclass(frozen=True)
class StressWindow:
    label: str
    start: pd.Timestamp
    end: pd.Timestamp
    order: int
    interpretation: str


WINDOWS = (
    StressWindow(
        "pre_30d",
        pd.Timestamp("2023-02-08"),
        pd.Timestamp("2023-03-09"),
        1,
        "thirty calendar days before the public USDC/SVB stress window",
    ),
    StressWindow(
        "stress_4d",
        pd.Timestamp("2023-03-10"),
        pd.Timestamp("2023-03-13"),
        2,
        "USDC/SVB stress weekend from disclosure through repeg",
    ),
    StressWindow(
        "post_30d",
        pd.Timestamp("2023-03-14"),
        pd.Timestamp("2023-04-12"),
        3,
        "thirty calendar days after the stress window",
    ),
)


def prepare_stable_route_days(frame: pd.DataFrame) -> pd.DataFrame:
    """Return stable-candidate daily route counts from the released panel."""

    required = {
        "origin_date",
        "candidate_symbol",
        "route_day_supported",
        "intermediate_route_count",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"stable stress input lacks columns: {missing}")
    out = frame.copy()
    out["origin_date"] = pd.to_datetime(out["origin_date"]).dt.normalize()
    out["candidate_symbol"] = out["candidate_symbol"].astype(str)
    out["intermediate_route_count"] = pd.to_numeric(
        out["intermediate_route_count"], errors="coerce"
    )
    out = out[
        out["route_day_supported"].astype(bool)
        & out["candidate_symbol"].isin(STABLE_SYMBOLS)
    ].copy()
    out = out.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["intermediate_route_count"]
    )
    if out.empty:
        raise ValueError("stable stress sample is empty")
    if (out["intermediate_route_count"] < 0).any():
        raise ValueError("stable stress sample has negative route counts")
    return out


def prepare_stress_candidate_days(frame: pd.DataFrame) -> pd.DataFrame:
    """Return five-candidate daily route counts and V2 deposited capital."""

    required = {
        "origin_date",
        "candidate_symbol",
        "route_day_supported",
        "v2_capital_day_supported",
        "intermediate_route_count",
        "v2_deposited_capital_usd",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"stable stress capital input lacks columns: {missing}")
    out = frame.copy()
    out["origin_date"] = pd.to_datetime(out["origin_date"]).dt.normalize()
    out["candidate_symbol"] = out["candidate_symbol"].astype(str)
    out["intermediate_route_count"] = pd.to_numeric(
        out["intermediate_route_count"], errors="coerce"
    )
    out["v2_deposited_capital_usd"] = pd.to_numeric(
        out["v2_deposited_capital_usd"], errors="coerce"
    )
    out = out[
        out["route_day_supported"].astype(bool)
        & out["v2_capital_day_supported"].astype(bool)
        & out["candidate_symbol"].isin(FIVE_CANDIDATE_SYMBOLS)
    ].copy()
    out = out.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["intermediate_route_count", "v2_deposited_capital_usd"]
    )
    if out.empty:
        raise ValueError("stable stress capital sample is empty")
    if (out["intermediate_route_count"] < 0).any():
        raise ValueError("stable stress capital sample has negative route counts")
    if (out["v2_deposited_capital_usd"] < 0).any():
        raise ValueError("stable stress capital sample has negative deposited capital")
    return out


def _window_label(date: pd.Timestamp) -> str | None:
    for window in WINDOWS:
        if window.start <= date <= window.end:
            return window.label
    return None


def stress_window_summaries(stable_routes: pd.DataFrame) -> pd.DataFrame:
    """Summarise stable route identity before, during, and after the stress."""

    sample = stable_routes[
        stable_routes["origin_date"].between(WINDOWS[0].start, WINDOWS[-1].end)
    ].copy()
    sample["stress_window"] = sample["origin_date"].map(_window_label)
    sample = sample.dropna(subset=["stress_window"])
    if sample.empty:
        raise ValueError("stable stress windows have no route rows")
    daily_totals = (
        sample.groupby(["stress_window", "origin_date"], as_index=False, sort=True)[
            "intermediate_route_count"
        ]
        .sum()
        .rename(columns={"intermediate_route_count": "stable_routes"})
    )
    totals = (
        sample.groupby(["stress_window", "candidate_symbol"], as_index=False, sort=True)
        .agg(candidate_routes=("intermediate_route_count", "sum"))
    )
    window_totals = daily_totals.groupby("stress_window", as_index=False).agg(
        days=("origin_date", "nunique"),
        stable_routes=("stable_routes", "sum"),
        mean_daily_stable_routes=("stable_routes", "mean"),
    )
    summaries = totals.merge(window_totals, on="stress_window", validate="many_to_one")
    summaries["stable_route_share"] = (
        summaries["candidate_routes"].astype(float)
        / summaries["stable_routes"].astype(float)
    )
    metadata = pd.DataFrame(
        [
            {
                "stress_window": window.label,
                "window_order": window.order,
                "window_start": window.start.date().isoformat(),
                "window_end": window.end.date().isoformat(),
                "interpretation": window.interpretation,
            }
            for window in WINDOWS
        ]
    )
    summaries = summaries.merge(metadata, on="stress_window", validate="many_to_one")
    summaries.insert(0, "analysis_status", "exploratory_stress_event")
    summaries.insert(1, "record_type", "stable_identity_window")
    return summaries.sort_values(
        ["window_order", "candidate_symbol"], ignore_index=True
    )


def stress_window_contrasts(summaries: pd.DataFrame) -> pd.DataFrame:
    """Return headline contrasts against the pre-window."""

    required = {
        "stress_window",
        "candidate_symbol",
        "stable_route_share",
        "mean_daily_stable_routes",
    }
    missing = sorted(required - set(summaries.columns))
    if missing:
        raise ValueError(f"stable stress summaries lack columns: {missing}")
    usdc = summaries[summaries["candidate_symbol"].eq("USDC")].set_index(
        "stress_window"
    )
    usdt = summaries[summaries["candidate_symbol"].eq("USDT")].set_index(
        "stress_window"
    )
    for label in ("pre_30d", "stress_4d", "post_30d"):
        if label not in usdc.index or label not in usdt.index:
            raise ValueError(f"stable stress contrast missing window {label}")
    pre_usdc = float(usdc.loc["pre_30d", "stable_route_share"])
    event_usdc = float(usdc.loc["stress_4d", "stable_route_share"])
    post_usdc = float(usdc.loc["post_30d", "stable_route_share"])
    pre_daily = float(usdc.loc["pre_30d", "mean_daily_stable_routes"])
    event_daily = float(usdc.loc["stress_4d", "mean_daily_stable_routes"])
    rows = [
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_contrast",
            "contrast": "stress_minus_pre_usdc_share",
            "estimate": event_usdc - pre_usdc,
            "baseline": pre_usdc,
            "comparison": event_usdc,
            "unit": "share_point",
            "interpretation": "USDC share of stable vehicle routes during stress minus pre-window share",
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_contrast",
            "contrast": "post_minus_pre_usdc_share",
            "estimate": post_usdc - pre_usdc,
            "baseline": pre_usdc,
            "comparison": post_usdc,
            "unit": "share_point",
            "interpretation": "USDC share of stable vehicle routes after stress minus pre-window share",
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_contrast",
            "contrast": "stress_mean_daily_stable_routes_vs_pre",
            "estimate": event_daily / pre_daily - 1.0,
            "baseline": pre_daily,
            "comparison": event_daily,
            "unit": "relative_change",
            "interpretation": "mean daily stable vehicle route count during stress relative to pre-window",
        },
        {
            "analysis_status": "exploratory_stress_event",
            "record_type": "stable_identity_contrast",
            "contrast": "post_minus_pre_usdt_share",
            "estimate": float(usdt.loc["post_30d", "stable_route_share"])
            - float(usdt.loc["pre_30d", "stable_route_share"]),
            "baseline": float(usdt.loc["pre_30d", "stable_route_share"]),
            "comparison": float(usdt.loc["post_30d", "stable_route_share"]),
            "unit": "share_point",
            "interpretation": "USDT share of stable vehicle routes after stress minus pre-window share",
        },
    ]
    return pd.DataFrame(rows)


def stress_lp_window_summaries(candidate_days: pd.DataFrame) -> pd.DataFrame:
    """Summarise route and capital shares before, during, and after stress."""

    sample = candidate_days[
        candidate_days["origin_date"].between(WINDOWS[0].start, WINDOWS[-1].end)
    ].copy()
    sample["stress_window"] = sample["origin_date"].map(_window_label)
    sample = sample.dropna(subset=["stress_window"])
    if sample.empty:
        raise ValueError("stable stress capital windows have no rows")
    daily_candidates = (
        sample.groupby(["stress_window", "origin_date"], sort=True)["candidate_symbol"]
        .nunique()
        .rename("candidate_count")
        .reset_index()
    )
    if daily_candidates["candidate_count"].min() < len(FIVE_CANDIDATE_SYMBOLS):
        raise ValueError("stable stress capital windows lost five-candidate support")
    totals = sample.groupby("stress_window", as_index=False).agg(
        five_candidate_routes=("intermediate_route_count", "sum"),
        five_candidate_capital_usd=("v2_deposited_capital_usd", "sum"),
        window_days=("origin_date", "nunique"),
    )
    if (totals["five_candidate_routes"] <= 0).any() or (
        totals["five_candidate_capital_usd"] <= 0
    ).any():
        raise ValueError("stable stress capital windows have non-positive totals")
    candidates = sample.groupby(
        ["stress_window", "candidate_symbol"], as_index=False, sort=True
    ).agg(
        routes=("intermediate_route_count", "sum"),
        deposited_capital_usd=("v2_deposited_capital_usd", "sum"),
        mean_daily_routes=("intermediate_route_count", "mean"),
        mean_daily_deposited_capital_usd=("v2_deposited_capital_usd", "mean"),
        candidate_days=("origin_date", "nunique"),
    )
    candidates["asset_group"] = candidates["candidate_symbol"].astype(str)
    stable = (
        sample[sample["candidate_symbol"].isin(STABLE_SYMBOLS)]
        .groupby("stress_window", as_index=False, sort=True)
        .agg(
            routes=("intermediate_route_count", "sum"),
            deposited_capital_usd=("v2_deposited_capital_usd", "sum"),
            mean_daily_routes=("intermediate_route_count", "sum"),
            mean_daily_deposited_capital_usd=("v2_deposited_capital_usd", "sum"),
            candidate_days=("origin_date", "nunique"),
        )
    )
    stable["mean_daily_routes"] = (
        stable["routes"].astype(float) / stable["candidate_days"].astype(float)
    )
    stable["mean_daily_deposited_capital_usd"] = (
        stable["deposited_capital_usd"].astype(float)
        / stable["candidate_days"].astype(float)
    )
    stable["candidate_symbol"] = "STABLE"
    stable["asset_group"] = "stable_basket"
    combined = pd.concat([candidates, stable], ignore_index=True, sort=False)
    combined = combined.merge(totals, on="stress_window", validate="many_to_one")
    combined["route_share_5"] = (
        combined["routes"].astype(float)
        / combined["five_candidate_routes"].astype(float)
    )
    combined["capital_share_5"] = (
        combined["deposited_capital_usd"].astype(float)
        / combined["five_candidate_capital_usd"].astype(float)
    )
    metadata = pd.DataFrame(
        [
            {
                "stress_window": window.label,
                "window_order": window.order,
                "window_start": window.start.date().isoformat(),
                "window_end": window.end.date().isoformat(),
                "interpretation": window.interpretation,
            }
            for window in WINDOWS
        ]
    )
    combined = combined.merge(metadata, on="stress_window", validate="many_to_one")
    combined.insert(0, "analysis_status", "exploratory_stress_event")
    combined.insert(1, "record_type", "stress_lp_window")
    return combined.sort_values(
        ["window_order", "asset_group"], ignore_index=True
    )


def stress_lp_contrasts(summaries: pd.DataFrame) -> pd.DataFrame:
    """Return route-versus-capital stress-window contrasts."""

    required = {"stress_window", "asset_group", "route_share_5", "capital_share_5"}
    missing = sorted(required - set(summaries.columns))
    if missing:
        raise ValueError(f"stable stress LP summaries lack columns: {missing}")
    indexed = summaries.set_index(["stress_window", "asset_group"])
    for label in ("pre_30d", "stress_4d", "post_30d"):
        for asset_group in ("stable_basket", "USDC", "WETH"):
            if (label, asset_group) not in indexed.index:
                raise ValueError(
                    f"stable stress LP contrast missing {label}/{asset_group}"
                )

    def value(label: str, asset_group: str, column: str) -> float:
        return float(indexed.loc[(label, asset_group), column])

    definitions = [
        (
            "stress_minus_pre_stable_route_share_5",
            "route_share_5",
            "stable_basket",
            "stress_4d",
            "pre_30d",
            "stable basket route share during stress minus pre-window share",
        ),
        (
            "stress_minus_pre_stable_capital_share_5",
            "capital_share_5",
            "stable_basket",
            "stress_4d",
            "pre_30d",
            "stable basket deposited-capital share during stress minus pre-window share",
        ),
        (
            "post_minus_pre_stable_capital_share_5",
            "capital_share_5",
            "stable_basket",
            "post_30d",
            "pre_30d",
            "stable basket deposited-capital share after stress minus pre-window share",
        ),
        (
            "post_minus_pre_weth_capital_share_5",
            "capital_share_5",
            "WETH",
            "post_30d",
            "pre_30d",
            "WETH deposited-capital share after stress minus pre-window share",
        ),
        (
            "post_minus_pre_usdc_capital_share_5",
            "capital_share_5",
            "USDC",
            "post_30d",
            "pre_30d",
            "USDC deposited-capital share after stress minus pre-window share",
        ),
    ]
    rows: list[dict[str, object]] = []
    for contrast, column, asset_group, comparison_window, baseline_window, interpretation in definitions:
        baseline = value(baseline_window, asset_group, column)
        comparison = value(comparison_window, asset_group, column)
        rows.append(
            {
                "analysis_status": "exploratory_stress_event",
                "record_type": "stress_lp_contrast",
                "contrast": contrast,
                "asset_group": asset_group,
                "metric": column,
                "estimate": comparison - baseline,
                "baseline": baseline,
                "comparison": comparison,
                "baseline_window": baseline_window,
                "comparison_window": comparison_window,
                "unit": "share_point",
                "interpretation": interpretation,
            }
        )
    return pd.DataFrame(rows)


def support_rows(stable_routes: pd.DataFrame, candidate_days: pd.DataFrame) -> pd.DataFrame:
    """Return one support row for the stress-event screen."""

    sample = stable_routes[
        stable_routes["origin_date"].between(WINDOWS[0].start, WINDOWS[-1].end)
    ].copy()
    capital_sample = candidate_days[
        candidate_days["origin_date"].between(WINDOWS[0].start, WINDOWS[-1].end)
    ].copy()
    return pd.DataFrame(
        [
            {
                "analysis_status": "exploratory_stress_event",
                "record_type": "support",
                "input": str(CANDIDATE_DAY_INPUT.relative_to(REPO_ROOT)),
                "stable_symbols": ",".join(STABLE_SYMBOLS),
                "first_date": WINDOWS[0].start.date().isoformat(),
                "last_date": WINDOWS[-1].end.date().isoformat(),
                "days": int(sample["origin_date"].nunique()),
                "candidate_day_rows": int(len(sample)),
                "capital_candidate_day_rows": int(len(capital_sample)),
                "five_candidate_symbols": ",".join(FIVE_CANDIDATE_SYMBOLS),
                "quantity": (
                    "daily route counts for stable vehicle candidates plus "
                    "five-candidate V2 deposited-capital shares"
                ),
            }
        ]
    )


def run(
    *,
    input_path: Path = CANDIDATE_DAY_INPUT,
    result_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    frame = pd.read_parquet(input_path)
    stable_routes = prepare_stable_route_days(frame)
    candidate_days = prepare_stress_candidate_days(frame)
    summaries = stress_window_summaries(stable_routes)
    contrasts = stress_window_contrasts(summaries)
    lp_summaries = stress_lp_window_summaries(candidate_days)
    lp_contrasts = stress_lp_contrasts(lp_summaries)
    result = pd.concat(
        [summaries, contrasts, lp_summaries, lp_contrasts],
        ignore_index=True,
        sort=False,
    )
    write_exhibit(result, result_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(
        support_rows(stable_routes, candidate_days),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(f"wrote {len(result)} stable stress rows and 1 support row")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=CANDIDATE_DAY_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(input_path=args.input, result_path=args.output, support_path=args.support)


if __name__ == "__main__":
    raise SystemExit(main())

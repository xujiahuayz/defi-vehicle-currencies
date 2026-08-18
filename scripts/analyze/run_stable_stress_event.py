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


def support_rows(stable_routes: pd.DataFrame) -> pd.DataFrame:
    """Return one support row for the stress-event screen."""

    sample = stable_routes[
        stable_routes["origin_date"].between(WINDOWS[0].start, WINDOWS[-1].end)
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
                "quantity": "daily route counts for stable vehicle candidates",
            }
        ]
    )


def run(
    *,
    input_path: Path = CANDIDATE_DAY_INPUT,
    result_path: Path = RESULT_OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
) -> int:
    stable_routes = prepare_stable_route_days(pd.read_parquet(input_path))
    summaries = stress_window_summaries(stable_routes)
    contrasts = stress_window_contrasts(summaries)
    result = pd.concat([summaries, contrasts], ignore_index=True, sort=False)
    write_exhibit(result, result_path, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support_rows(stable_routes), support_path, code_sources=CODE_SOURCES, inputs=INPUTS)
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

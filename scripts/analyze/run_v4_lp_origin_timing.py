#!/usr/bin/env python3
"""Separate near-term incumbent activity from later V4 origin participation.

Reads raw Uniswap V4 modify-liquidity events and the existing V4
flash-accounting, LP-flow, LP-action, and vehicle-linked TVL panels. The unit is
a vehicle-day. The primary sample excludes zero-liquidity updates, requires a
180-day prior-activity window, and measures responses over days 1--30 and
31--120.

The address field is the transaction origin. It can proxy for a market
participant but does not identify the beneficial owner of an LP position.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit
from scripts.analyze.run_v4_flash_lp_mechanism_exploration import (
    CONTROLS,
    PREDICTORS,
    build_mechanism_panel,
    load_inputs,
)
from scripts.process.build_v4_lp_action_candidate_daily import (
    _candidate_sides,
    _decimal,
    _event_date,
    vehicle_candidate_map,
)


EVENT_DIR = REPO_ROOT / "data/raw/thegraph/uniswap_v4"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_origin_timing.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_origin_timing_support.jsonl"

NEAR_DAYS = 30
LATE_DAYS = 120
PRIMARY_PRIOR_DAYS = 180
ROBUSTNESS_PRIOR_DAYS = 90
OUTCOMES = (
    "near_log1p_new_origins",
    "near_log1p_incumbent_actions",
    "late_log1p_first_active_origins",
    "late_log1p_incumbent_actions",
)
SAMPLE_VARIANTS = (
    ("primary_nonzero_180", False, PRIMARY_PRIOR_DAYS),
    ("nonzero_90", False, ROBUSTNESS_PRIOR_DAYS),
    ("all_updates_180", True, PRIMARY_PRIOR_DAYS),
    ("all_updates_90", True, ROBUSTNESS_PRIOR_DAYS),
)
CODE_SOURCES = [
    "scripts/analyze/run_v4_lp_origin_timing.py",
    "scripts/analyze/run_v4_flash_lp_mechanism_exploration.py",
    "scripts/process/build_v4_lp_action_candidate_daily.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/raw/thegraph/uniswap_v4",
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
    "data/processed/v4_lp_flow_candidate_daily.parquet",
    "data/processed/v4_lp_action_candidate_daily.parquet",
    "data/processed/v4_candidate_linked_pool_tvl_daily.parquet",
]

OriginDaily = dict[str, dict[pd.Timestamp, dict[str, int]]]


def load_raw_origin_actions(
    *,
    event_dir: Path = EVENT_DIR,
    candidate_map: dict[str, tuple[str, str]],
) -> tuple[OriginDaily, OriginDaily, dict[str, object]]:
    """Return all and nonzero action counts by vehicle, day, and origin."""

    all_updates: OriginDaily = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    nonzero_updates: OriginDaily = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    event_files = 0
    raw_events = 0
    candidate_assignments = 0
    nonzero_candidate_assignments = 0
    blank_origin_assignments = 0
    for path in sorted(event_dir.glob("uniswap_v4_modify_liquidities_*.jsonl.gz")):
        event_files += 1
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_events += 1
                event = json.loads(line)
                sides = _candidate_sides(event, candidate_map)
                if not sides:
                    continue
                origin = str(event.get("origin") or "").lower()
                if not origin:
                    blank_origin_assignments += len(sides)
                    continue
                date = _event_date(event)
                is_nonzero = _decimal(event.get("amount")) != 0
                for address, _symbol in sides:
                    all_updates[address][date][origin] += 1
                    candidate_assignments += 1
                    if is_nonzero:
                        nonzero_updates[address][date][origin] += 1
                        nonzero_candidate_assignments += 1
    if not all_updates or not nonzero_updates:
        raise ValueError("raw V4 events contain no candidate origin actions")
    support = {
        "event_files": event_files,
        "raw_modify_liquidity_events": raw_events,
        "candidate_event_assignments": candidate_assignments,
        "nonzero_candidate_event_assignments": nonzero_candidate_assignments,
        "blank_origin_assignments": blank_origin_assignments,
    }
    return all_updates, nonzero_updates, support


def build_origin_timing_panel(
    daily: OriginDaily,
    base: pd.DataFrame,
    *,
    prior_days: int,
    near_days: int = NEAR_DAYS,
    late_days: int = LATE_DAYS,
) -> pd.DataFrame:
    """Classify future origin activity using only information available at t."""

    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        *PREDICTORS,
        *CONTROLS,
    }
    missing = sorted(required - set(base.columns))
    if missing:
        raise ValueError(f"V4 origin-timing base lacks required columns: {missing}")
    if not 0 < near_days < late_days:
        raise ValueError("origin-timing windows must satisfy 0 < near < late")
    if prior_days <= 0:
        raise ValueError("prior activity window must be positive")

    rows: list[dict[str, object]] = []
    base_columns = [
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        *PREDICTORS,
        *CONTROLS,
    ]
    for address, group in base[base_columns].drop_duplicates().groupby(
        "candidate_address", sort=True
    ):
        address_daily = daily.get(str(address), {})
        active_dates = sorted(address_daily)
        if not active_dates:
            continue
        first_available = active_dates[0]
        last_available = active_dates[-1]
        for record in group.itertuples(index=False):
            date = pd.Timestamp(record.origin_date).normalize()
            if date < first_available + pd.Timedelta(days=prior_days):
                continue
            if date + pd.Timedelta(days=late_days) > last_available:
                continue
            prior_start = date - pd.Timedelta(days=prior_days)
            near_end = date + pd.Timedelta(days=near_days)
            late_end = date + pd.Timedelta(days=late_days)
            prior_origins: set[str] = set()
            near_counts: dict[str, int] = defaultdict(int)
            late_counts: dict[str, int] = defaultdict(int)
            for active_date in active_dates:
                if active_date < prior_start:
                    continue
                if active_date <= date:
                    prior_origins.update(address_daily[active_date])
                elif active_date <= near_end:
                    for origin, count in address_daily[active_date].items():
                        near_counts[origin] += count
                elif active_date <= late_end:
                    for origin, count in address_daily[active_date].items():
                        late_counts[origin] += count
                else:
                    break
            near_origins = set(near_counts)
            late_origins = set(late_counts)
            near_new = near_origins - prior_origins
            late_first_active = late_origins - prior_origins - near_origins
            near_incumbent_actions = sum(
                near_counts[origin] for origin in near_origins & prior_origins
            )
            late_incumbent_actions = sum(
                late_counts[origin] for origin in late_origins & prior_origins
            )
            row = {column: getattr(record, column) for column in base_columns}
            row.update(
                {
                    "prior_days": int(prior_days),
                    "near_days": int(near_days),
                    "late_days": int(late_days),
                    "near_new_origins": len(near_new),
                    "near_incumbent_actions": near_incumbent_actions,
                    "late_first_active_origins": len(late_first_active),
                    "late_incumbent_actions": late_incumbent_actions,
                }
            )
            rows.append(row)
    if not rows:
        raise ValueError("V4 origin-timing panel is empty")
    panel = pd.DataFrame(rows)
    for outcome in OUTCOMES:
        source = outcome.replace("_log1p_", "_")
        panel[outcome] = np.log1p(panel[source].astype(float))
    return panel


def fit_origin_timing(
    panel: pd.DataFrame,
    *,
    sample_variant: str,
    predictors: Sequence[str] = PREDICTORS,
    outcomes: Sequence[str] = OUTCOMES,
    controls: Sequence[str] = CONTROLS,
    min_observations: int = 300,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate the four registered participation margins and adjust jointly."""

    rows: list[dict[str, object]] = []
    for predictor in predictors:
        for outcome in outcomes:
            columns = [outcome, predictor, *controls]
            data = panel[
                ["origin_date", "candidate_symbol", *columns]
            ].dropna()
            residual = absorb_fixed_effects(
                data[columns], data["candidate_symbol"], data["origin_date"]
            )
            model = ols_clustered(
                residual[outcome],
                residual[[predictor, *controls]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_symbol"], data["origin_date"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            rows.append(
                {
                    "record_type": "v4_lp_origin_timing_regression",
                    "analysis_status": "exploratory_mechanism",
                    "sample_variant": sample_variant,
                    "predictor": predictor,
                    "outcome": outcome,
                    "coefficient": float(model.beta[0]),
                    "standard_error": float(model.standard_errors[0]),
                    "p_value": float(model.p_values[0]),
                    "effect_per_10pp_predictor": float(0.1 * model.beta[0]),
                    "standard_error_per_10pp_predictor": float(
                        0.1 * model.standard_errors[0]
                    ),
                    "n_observations": int(model.n_observations),
                    "date_clusters": int(model.n_clusters),
                    "fixed_effects": "candidate+origin_date",
                    "controls": "+".join(controls),
                }
            )
    if not rows:
        raise ValueError("no V4 origin-timing regressions were estimated")
    result = pd.DataFrame(rows)
    result["holm_p_value"] = holm_adjusted_pvalues(result["p_value"])
    return result


def run(
    *,
    event_dir: Path = EVENT_DIR,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> tuple[pd.DataFrame, dict[str, object]]:
    flash, flow, actions, tvl = load_inputs()
    base = build_mechanism_panel(flash, flow, actions, tvl, horizons=(LATE_DAYS,))
    all_updates, nonzero_updates, raw_support = load_raw_origin_actions(
        event_dir=event_dir,
        candidate_map=vehicle_candidate_map(),
    )
    result_frames: list[pd.DataFrame] = []
    variant_support: dict[str, dict[str, int]] = {}
    for variant, include_zero, prior_days in SAMPLE_VARIANTS:
        daily = all_updates if include_zero else nonzero_updates
        panel = build_origin_timing_panel(daily, base, prior_days=prior_days)
        result_frames.append(
            fit_origin_timing(panel, sample_variant=variant)
        )
        variant_support[variant] = {
            "candidate_days": int(len(panel)),
            "dates": int(panel["origin_date"].nunique()),
            "candidates": int(panel["candidate_address"].nunique()),
            "prior_days": int(prior_days),
            "includes_zero_liquidity_updates": int(include_zero),
        }
    results = pd.concat(result_frames, ignore_index=True)
    support = {
        "record_type": "v4_lp_origin_timing_support",
        "analysis_status": "exploratory_mechanism",
        **raw_support,
        "near_window": "days_1_30",
        "late_window": "days_31_120",
        "identity_boundary": (
            "transaction origin is a market-participation proxy, not verified "
            "LP-position beneficial ownership"
        ),
        "primary_sample": "nonzero modify-liquidity actions; 180 prior days",
        "multiple_testing": "Holm across 12 predictor-outcome tests within sample variant",
        "sample_variants": variant_support,
    }
    write_exhibit(
        results,
        result_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(
        pd.DataFrame([support]),
        support_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    return results, support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-dir", type=Path, default=EVENT_DIR)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    results, support = run(
        event_dir=args.event_dir,
        result_output=args.output,
        support_output=args.support_output,
    )
    print(
        f"wrote {len(results):,} V4 origin-timing estimates; "
        f"primary sample has "
        f"{support['sample_variants']['primary_nonzero_180']['candidate_days']:,} "
        "vehicle-days"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

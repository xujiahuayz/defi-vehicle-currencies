#!/usr/bin/env python3
"""Run the bounded open-discovery E0 audit on the released route-only panels."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    require_released_model_inputs,
    write_model_exhibit,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT


INTERMEDIATION = REPO_ROOT / "data/processed/intermediation_by_type_daily.parquet"
LIQUIDITY = REPO_ROOT / "data/processed/liquidity_capital_v2_exact_horizons.parquet"
RESULT = OUTPUT_DIR / "exhibits/e0_open_question_anomaly_diagnostics.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/e0_open_question_anomaly_support.jsonl"
CODE_SOURCES = [
    "scripts/run_open_question_anomaly_e0.py",
    "src/ddvc/model_artifacts.py",
]


def run() -> tuple[object, object]:
    context = model_artifact_context()
    with require_released_model_inputs(
        context,
        [INTERMEDIATION, LIQUIDITY],
        consumer="E0 open-question anomaly audit",
    ) as inputs:
        routes = pd.read_parquet(
            INTERMEDIATION,
            columns=[
                "date",
                "episodes",
                "cnt_native",
                "cnt_stable",
                "cnt_single_venue_stable",
                "cnt_cross_venue_stable",
                "share_stable",
                "cnt_WETH",
                "cnt_USDC",
                "cnt_USDT",
                "cnt_DAI",
                "cnt_WBTC",
            ],
        )
        liquidity = pd.read_parquet(
            LIQUIDITY,
            columns=[
                "origin_date",
                "candidate_address",
                "horizon_days",
                "intermediary_episode_share",
                "v2_five_candidate_capital_share",
            ],
        )
        stable_total = float(routes["cnt_stable"].sum())
        native_stable_total = float((routes["cnt_stable"] + routes["cnt_native"]).sum())
        pooled_stable_share = stable_total / native_stable_total
        daily_stable_share = routes["cnt_stable"] / (routes["cnt_stable"] + routes["cnt_native"])
        candidate_totals = routes[["cnt_WETH", "cnt_USDC", "cnt_USDT", "cnt_DAI", "cnt_WBTC"]].sum()
        candidate_weights = candidate_totals / candidate_totals.sum()
        one_horizon = liquidity.loc[liquidity["horizon_days"].eq(1)].drop_duplicates(
            ["origin_date", "candidate_address"]
        )
        correlation = one_horizon[
            ["intermediary_episode_share", "v2_five_candidate_capital_share"]
        ].corr().iloc[0, 1]
        values = {
            "immutable_reproduction": float(len(routes)),
            "economic_magnitude_concentration": float(daily_stable_share.max()),
            "denominator_weighting": float(daily_stable_share.mean() - pooled_stable_share),
            "time_venue_stability": float(
                routes["cnt_cross_venue_stable"].sum()
                / (routes["cnt_cross_venue_stable"].sum() + routes["cnt_single_venue_stable"].sum())
            ),
            "integrity_screens": float(
                (~np.isfinite(routes["share_stable"]) | ~routes["share_stable"].between(0, 1)).sum()
            ),
            "strongest_literature_rival": float(correlation),
            "centrality_and_triage": float((candidate_weights**2).sum()),
        }
        diagnostics = pd.DataFrame(
            [
                {
                    "family": "open_question_anomaly_e0",
                    "attack_id": attack_id,
                    "statistic": statistic,
                    "disposition": "retain_diagnostic_no_new_claim",
                }
                for attack_id, statistic in values.items()
            ]
        )
        diagnostics = attach_spec_ids(
            diagnostics,
            prefix="open_question_anomaly_e0",
            columns=("attack_id",),
        )
        support = pd.DataFrame(
            [
                {
                    "route_days": int(len(routes)),
                    "route_episodes": int(routes["episodes"].sum()),
                    "liquidity_rows": int(len(liquidity)),
                    "liquidity_origin_dates": int(liquidity["origin_date"].nunique()),
                    "new_claim_promoted": False,
                    "scope": "released route-only and V2 deposited-capital panels",
                }
            ]
        )
        notes = (
            "Bounded open-discovery audit of reproduction, magnitude concentration, "
            "weighting, venue stability, integrity, the capital-share rival, and "
            "candidate concentration; diagnostics do not create a paper claim"
        )
        write_model_exhibit(
            diagnostics,
            RESULT,
            role="diagnostic",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=notes,
        )
        write_model_exhibit(
            support,
            SUPPORT,
            role="support",
            context=context,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes=notes,
        )
    print(f"wrote {len(diagnostics)} open-discovery diagnostics")
    return RESULT, SUPPORT


if __name__ == "__main__":
    run()

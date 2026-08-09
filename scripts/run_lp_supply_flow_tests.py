#!/usr/bin/env python3
"""Estimate vehicle-use responses from the canonical V3 LP supply-flow panel."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import CANONICAL_RESPONSE_HORIZONS, value_at_day_offset
from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paper_tables import _int, _num, _p, _write_table
from ddvc.paths import (
    DATA_DIR,
    LP_LIQUIDITY_FLOW_DAILY,
)
from ddvc.provenance import require_current_artifacts
from ddvc.tables import write_panel


BRIDGE_PANEL = DATA_DIR / "empirical" / "bridge_daily.parquet"
OUTPUT = DATA_DIR / "empirical" / "lp_supply_flow_tests.parquet"
REGRESSORS = (
    "net_flow_pressure",
    "active_net_flow_pressure",
    "near_net_flow_pressure",
    "near_gross_flow_share",
    "gross_candidate_flow_share",
)


def daily_liquidity_flow_panel() -> pd.DataFrame:
    """Load the canonical candidate-day flow panel without a capital-stock proxy."""

    require_current_artifacts(
        [LP_LIQUIDITY_FLOW_DAILY, BRIDGE_PANEL],
        consumer="LP supply-flow estimator",
    )
    panel = pd.read_parquet(LP_LIQUIDITY_FLOW_DAILY)
    return panel.rename(columns={"day": "date", "candidate": "token"})


def run() -> pd.DataFrame:
    panel = daily_liquidity_flow_panel()
    vehicle = pd.read_parquet(
        BRIDGE_PANEL,
        columns=["date", "token", "BridgeShare"],
    ).rename(columns={"BridgeShare": "vehicle_share"})
    panel["date"] = pd.to_datetime(panel["date"])
    vehicle["date"] = pd.to_datetime(vehicle["date"])
    panel = panel.merge(vehicle, on=["date", "token"], how="left")
    panel = panel.sort_values(["token", "date"]).reset_index(drop=True)
    rows: list[dict[str, object]] = []
    for horizon in CANONICAL_RESPONSE_HORIZONS:
        outcome = value_at_day_offset(panel, "vehicle_share", horizon)
        for regressor in REGRESSORS:
            y = absorb_fixed_effects(outcome, panel["token"], panel["date"])
            x = absorb_fixed_effects(panel[regressor], panel["token"], panel["date"])
            fit = ols_clustered(
                y,
                x,
                panel["date"],
                absorbed_groups=(panel["token"], panel["date"]),
                min_observations=10,
            )
            rows.append(
                {
                    "Horizon (days)": horizon,
                    "Regressor": regressor.replace("_", " "),
                    "N": _int(fit.n_observations),
                    "Date clusters": _int(fit.n_clusters),
                    "Beta": _num(fit.beta[1], 3),
                    "SE": _num(fit.standard_errors[1], 3),
                    "t": _num(fit.t_statistics[1], 2),
                    "p": _p(fit.p_values[1]),
                }
            )
    result = pd.DataFrame(rows)
    write_panel(
        result,
        OUTPUT,
        code_sources=[
            "scripts/run_lp_supply_flow_tests.py",
            "src/ddvc/analysis/lp_liquidity_flow.py",
            "src/ddvc/analysis/dynamics.py",
            "src/ddvc/analysis/regression.py",
        ],
        inputs=[
            LP_LIQUIDITY_FLOW_DAILY,
            BRIDGE_PANEL,
        ],
        notes="exact 1/7/30/120-day LP supply-flow response specifications",
    )
    _write_table(
        result,
        "table_r13_lp_supply_flow",
        "LP supply flows and subsequent vehicle use.",
        "tab:lp-supply-flow",
        note=(
            "The canonical event panel values each V3 mint or burn once from a canonical candidate day-price anchor and the exact prior pool price, allocates multi-candidate pools once by exact token address, and classifies range activity at the latest strictly prior swap state with an exclusive upper bound. These are liquidity supply flows, not wallet-linked burn-mint repositioning episodes. Because provider V3 TVL failed the independent holdings audit, no capital-stock proxy enters these measures: net pressure is net divided by gross candidate flow, near-range intensity is measured within gross flow, and gross candidate flow share is measured across candidates. Responses are measured at exact 1-, 7-, 30-, and 120-day horizons. Specifications include token and date fixed effects and cluster by date."
        ),
    )
    return result


def main() -> int:
    result = run()
    finite = int(np.isfinite(pd.to_numeric(result["Beta"], errors="coerce")).sum())
    print(f"LP supply-flow specifications: {len(result)}; finite coefficients: {finite}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

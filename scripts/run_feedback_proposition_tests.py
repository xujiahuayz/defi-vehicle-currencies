#!/usr/bin/env python3
"""Empirical tests for liquidity-route feedback and netting-related LP response."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import value_at_day_offset
from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import LP_CAPITAL_CONCENTRATION_PANEL

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

from ddvc.paper_tables import _int, _num, _p, _write_table


def p2_feedback_loop() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "BridgeShare"])
    lp = pd.read_parquet(LP_CAPITAL_CONCENTRATION_PANEL).rename(columns={"token_symbol": "token"})
    d = bridge.merge(
        lp[["date", "token", "lp_capital_share", "total_lp_capital_usd"]],
        on=["date", "token"],
        how="inner",
    )
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    rows = []
    for h in [1, 7, 14, 30]:
        dd = d.copy()
        dd["future_bridge_share"] = value_at_day_offset(dd, "BridgeShare", h)
        dd["future_lp_capital_share"] = value_at_day_offset(
            dd, "lp_capital_share", h
        )
        dd["future_log_lp_capital"] = np.log1p(
            value_at_day_offset(dd, "total_lp_capital_usd", h)
        )
        x = pd.DataFrame(
            {
                "lp_capital_share": absorb_fixed_effects(dd["lp_capital_share"], dd["token"], dd["date"]),
                "current_bridge_share": absorb_fixed_effects(dd["BridgeShare"], dd["token"], dd["date"]),
            }
        )
        fit = ols_clustered(
            absorb_fixed_effects(dd["future_bridge_share"], dd["token"], dd["date"]),
            x,
            dd["date"],
            absorbed_groups=(dd["token"], dd["date"]),
            min_observations=20,
        )
        n, clusters = fit.n_observations, fit.n_clusters
        res = fit.named_statistics(list(x.columns), offset=1)
        rows.append(
            {
                "Panel": "A. Lagged LP capital -> VehicleShare",
                "Horizon (days)": h,
                "Outcome": "VehicleShare",
                "N": _int(n),
                "Date clusters": _int(clusters),
                "Main regressor": "Lagged LP capital share",
                "Beta": _num(res["lp_capital_share_beta"], 3),
                "SE": _num(res["lp_capital_share_se"], 3),
                "t": _num(res["lp_capital_share_t"], 2),
                "p": _p(res["lp_capital_share_p"]),
                "Control": f"Lagged VehicleShare beta { _num(res['current_bridge_share_beta'], 3) }",
            }
        )
        x_rev = pd.DataFrame(
            {
                "current_bridge_share": absorb_fixed_effects(dd["BridgeShare"], dd["token"], dd["date"]),
                "lp_capital_share": absorb_fixed_effects(dd["lp_capital_share"], dd["token"], dd["date"]),
            }
        )
        for outcome, label in [
            ("future_lp_capital_share", "LP capital share"),
            ("future_log_lp_capital", "log LP capital"),
        ]:
            fit = ols_clustered(
                absorb_fixed_effects(dd[outcome], dd["token"], dd["date"]),
                x_rev,
                dd["date"],
                absorbed_groups=(dd["token"], dd["date"]),
                min_observations=20,
            )
            n, clusters = fit.n_observations, fit.n_clusters
            res = fit.named_statistics(list(x_rev.columns), offset=1)
            rows.append(
                {
                    "Panel": "B. Lagged VehicleShare -> LP capital",
                    "Horizon (days)": h,
                    "Outcome": label,
                    "N": _int(n),
                    "Date clusters": _int(clusters),
                    "Main regressor": "Lagged VehicleShare",
                    "Beta": _num(res["current_bridge_share_beta"], 3),
                    "SE": _num(res["current_bridge_share_se"], 3),
                    "t": _num(res["current_bridge_share_t"], 2),
                    "p": _p(res["current_bridge_share_p"]),
                    "Control": f"Lagged LP capital-share beta { _num(res['lp_capital_share_beta'], 3) }",
                }
            )
    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    out.to_pickle(EMP / "p2_liquidity_route_feedback.pkl")
    _write_table(
        out,
        "table_r32_p2_liquidity_route_feedback",
        "Bidirectional LP-capital and route-use feedback.",
        "tab:p2-liquidity-route-feedback",
        note=(
            "All regressions residualize by token and date fixed effects and cluster by date. "
            "Panel A asks whether lagged vehicle-linked LP capital share predicts VehicleShare. "
            "Panel B asks whether lagged VehicleShare predicts LP capital share or log LP capital."
        ),
    )
    return out


def _vehicle_key(s: object) -> str:
    value = str(s)
    return "WETH" if value == "ETH/WETH" else value


def p4b_netting_lp_response() -> pd.DataFrame:
    detail = pd.read_parquet(DATA / "empirical" / "v4_settlement_transfer_detail.parquet")
    v4 = detail[detail["dex"].eq("uniswap_v4") & detail["receipt_found"]].copy()
    v4["token"] = v4["vehicle"].map(_vehicle_key)
    exposure = (
        v4.groupby("token", as_index=False)
        .agg(
            v4_routes=("has_matching_transfer", "size"),
            netting_exposure=("has_matching_transfer", lambda x: 1.0 - float(pd.Series(x).mean())),
            median_route_usd=("route_usd", "median"),
        )
    )
    lp = pd.read_parquet(LP_CAPITAL_CONCENTRATION_PANEL).rename(columns={"token_symbol": "token"})
    lp["date"] = pd.to_datetime(lp["date"])
    lp["week"] = lp["date"].dt.to_period("W-MON").dt.start_time
    event_week = pd.Timestamp("2025-01-20")
    lo = event_week - pd.Timedelta(weeks=52)
    hi = event_week + pd.Timedelta(weeks=74)
    weekly = (
        lp[(lp["week"] >= lo) & (lp["week"] <= hi)]
        .groupby(["week", "token"], as_index=False)
        .agg(
            lp_capital_share=("lp_capital_share", "mean"),
            total_lp_capital_usd=("total_lp_capital_usd", "mean"),
        )
    )
    d = weekly.merge(exposure, on="token", how="inner")
    d["post"] = (d["week"] >= event_week).astype(float)
    d["post_x_netting_exposure"] = d["post"] * d["netting_exposure"]
    d["log_lp_capital"] = np.log1p(d["total_lp_capital_usd"])
    rows = []
    for outcome, label in [
        ("lp_capital_share", "LP capital share"),
        ("log_lp_capital", "log LP capital"),
    ]:
        x = pd.DataFrame(
            {
                "post_x_netting_exposure": absorb_fixed_effects(d["post_x_netting_exposure"], d["token"], d["week"]),
            }
        )
        fit = ols_clustered(
            absorb_fixed_effects(d[outcome], d["token"], d["week"]),
            x,
            d["week"],
            absorbed_groups=(d["token"], d["week"]),
            min_observations=20,
        )
        n, clusters = fit.n_observations, fit.n_clusters
        res = fit.named_statistics(list(x.columns), offset=1)
        beta = res["post_x_netting_exposure_beta"]
        rows.append(
            {
                "Panel": "A. LP response around settlement-netting architecture",
                "Outcome": label,
                "N": _int(n),
                "Week clusters": _int(clusters),
                "Vehicles": _int(d["token"].nunique()),
                "Treatment / exposure": "post x netting exposure",
                "Beta": _num(beta, 3),
                "SE": _num(res["post_x_netting_exposure_se"], 3),
                "t": _num(res["post_x_netting_exposure_t"], 2),
                "p": _p(res["post_x_netting_exposure_p"]),
                "Interpretation": "token and week fixed effects; suggestive event evidence",
            }
        )
    for _, r in exposure.sort_values("netting_exposure", ascending=False).iterrows():
        rows.append(
            {
                "Panel": "B. Netting exposure by vehicle",
                "Outcome": r["token"],
                "N": _int(r["v4_routes"]),
                "Week clusters": "",
                "Vehicles": "",
                "Treatment / exposure": "1 - V4 transfer incidence",
                "Beta": _num(r["netting_exposure"], 3),
                "SE": "",
                "t": "",
                "p": "",
                "Interpretation": f"median route ${_int(r['median_route_usd'])}",
            }
        )
    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    exposure.to_pickle(EMP / "p4b_netting_exposure_by_vehicle.pkl")
    out.to_pickle(EMP / "p4b_netting_lp_response.pkl")
    _write_table(
        out,
        "table_r33_p4b_netting_lp_response",
        "Settlement netting exposure and LP response.",
        "tab:p4b-netting-lp-response",
        note=(
            "Panel A estimates whether vehicles with higher V4 no-transfer exposure show stronger post-launch LP "
            "concentration or log-liquidity changes, residualizing by token and week fixed effects. This is suggestive "
            "mechanism evidence, not a clean exogenous adoption design. Panel B reports the exposure measure."
        ),
    )
    return out


def main() -> int:
    p2_feedback_loop()
    p4b_netting_lp_response()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

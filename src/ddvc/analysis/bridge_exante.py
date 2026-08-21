"""Forward-dated bridge formation statistics.

The event date in this module is fixed by deposited capital observed before the
route date.  Later route use never enters the event definition.  The helpers
then summarize adoption, later use, paired changes, and the continuous relation
between route allocation and relative weak-leg depth.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered


PERIODS = ("pre_30", "post_0_29", "post_30_119")


def prepare_exante_bridge_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate event rows and add route-share and depth quantities."""

    required = {
        "event_id",
        "ordered_pair",
        "event_date",
        "origin_date",
        "event_time",
        "first_supported_stable_route_date",
        "native_routes",
        "stable_routes",
        "native_value_usd",
        "stable_value_usd",
        "stable_bridge_min_capital_usd",
        "native_bridge_min_capital_usd",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"ex-ante bridge panel lacks columns: {missing}")
    data = frame.copy()
    for column in ("event_date", "origin_date"):
        data[column] = pd.to_datetime(data[column], errors="raise").dt.normalize()
    data["first_supported_stable_route_date"] = pd.to_datetime(
        data["first_supported_stable_route_date"], errors="coerce"
    ).dt.normalize()
    numeric = [
        "event_time",
        "native_routes",
        "stable_routes",
        "native_value_usd",
        "stable_value_usd",
        "stable_bridge_min_capital_usd",
        "native_bridge_min_capital_usd",
    ]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="raise")
    data["total_routes"] = data["native_routes"] + data["stable_routes"]
    data["total_value_usd"] = data["native_value_usd"] + data["stable_value_usd"]
    data = data[data["total_routes"].gt(0)].copy()
    data["stable_share"] = data["stable_routes"] / data["total_routes"]
    data["stable_value_share"] = np.divide(
        data["stable_value_usd"],
        data["total_value_usd"],
        out=np.full(len(data), np.nan, dtype=float),
        where=data["total_value_usd"].gt(0),
    )
    depth_total = (
        data["stable_bridge_min_capital_usd"]
        + data["native_bridge_min_capital_usd"]
    )
    data["stable_bridge_depth_share"] = np.divide(
        data["stable_bridge_min_capital_usd"],
        depth_total,
        out=np.full(len(data), np.nan, dtype=float),
        where=depth_total.gt(0),
    )
    data["stable_to_native_depth_ratio"] = np.divide(
        data["stable_bridge_min_capital_usd"],
        data["native_bridge_min_capital_usd"],
        out=np.full(len(data), np.nan, dtype=float),
        where=data["native_bridge_min_capital_usd"].gt(0),
    )
    data["period"] = pd.cut(
        data["event_time"],
        bins=[-31, -1, 29, 119],
        labels=list(PERIODS),
    ).astype(str)
    if data.empty:
        raise ValueError("ex-ante bridge panel is empty after validation")
    before_event = data["first_supported_stable_route_date"].notna() & data[
        "first_supported_stable_route_date"
    ].lt(data["event_date"])
    if before_event.any():
        raise ValueError("supported stable route predates the ex-ante bridge event")
    event_columns = [
        "event_date",
        "first_supported_stable_route_date",
    ]
    if data.groupby("event_id")[event_columns].nunique(dropna=False).gt(1).any().any():
        raise ValueError("event dates must be constant within an ex-ante event")
    return data.reset_index(drop=True)


def adoption_and_retention_summaries(panel: pd.DataFrame) -> pd.DataFrame:
    """Summarize subsequent adoption and later use from one row per event."""

    event_columns = [
        "event_id",
        "ordered_pair",
        "event_date",
        "first_supported_stable_route_date",
    ]
    events = panel[event_columns].drop_duplicates("event_id").copy()
    events["adoption_lag_days"] = (
        events["first_supported_stable_route_date"] - events["event_date"]
    ).dt.days
    rows: list[dict[str, object]] = []
    for model_id, horizon in (("within_30_days", 29), ("within_120_days", 119)):
        adopted = events["adoption_lag_days"].between(0, horizon)
        rows.append(
            {
                "record_type": "exante_bridge_adoption",
                "model_id": model_id,
                "horizon_days": horizon + 1,
                "estimate": float(adopted.mean()),
                "events": int(len(events)),
                "adopting_events": int(adopted.sum()),
            }
        )

    early_ids = set(
        events.loc[events["adoption_lag_days"].between(0, 29), "event_id"]
    )
    later = panel[
        panel["event_id"].isin(early_ids)
        & panel["event_time"].between(30, 119)
    ]
    later_event = (
        later.groupby("event_id", as_index=False)
        .agg(
            stable_routes=("stable_routes", "sum"),
            total_routes=("total_routes", "sum"),
        )
    )
    if later_event.empty:
        raise ValueError("ex-ante bridge panel has no later observations for early adopters")
    retained = later_event["stable_routes"].gt(0)
    rows.extend(
        [
            {
                "record_type": "exante_bridge_retention",
                "model_id": "stable_route_observed_days_30_119",
                "horizon_days": 90,
                "estimate": float(retained.mean()),
                "events": int(len(later_event)),
                "adopting_events": int(retained.sum()),
                "conditioning": "stable route first observed during days 0--29 and pair trades during days 30--119",
            },
            {
                "record_type": "exante_bridge_retention",
                "model_id": "stable_route_share_days_30_119",
                "horizon_days": 90,
                "estimate": float(
                    later_event["stable_routes"].sum()
                    / later_event["total_routes"].sum()
                ),
                "events": int(len(later_event)),
                "adopting_events": int(retained.sum()),
                "conditioning": "stable route first observed during days 0--29 and pair trades during days 30--119",
            },
        ]
    )
    return pd.DataFrame(rows)


def paired_share_change_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 30,
    min_clusters: int = 20,
) -> pd.DataFrame:
    """Estimate activity-weighted event-level changes from the prior 30 days."""

    collapsed = (
        panel[panel["period"].isin(PERIODS)]
        .groupby(
            ["event_id", "ordered_pair", "event_date", "period"],
            observed=True,
            as_index=False,
        )
        .agg(
            stable_routes=("stable_routes", "sum"),
            total_routes=("total_routes", "sum"),
        )
    )
    collapsed["stable_share"] = collapsed["stable_routes"] / collapsed["total_routes"]
    wide = collapsed.pivot(
        index=["event_id", "ordered_pair", "event_date"],
        columns="period",
        values=["stable_share", "total_routes"],
    )
    wide.columns = [f"{quantity}__{period}" for quantity, period in wide.columns]
    wide = wide.reset_index()
    rows: list[dict[str, object]] = []
    for period in ("post_0_29", "post_30_119"):
        needed = [
            "stable_share__pre_30",
            f"stable_share__{period}",
            "total_routes__pre_30",
            f"total_routes__{period}",
        ]
        data = wide.dropna(subset=needed).copy()
        data["change"] = data[f"stable_share__{period}"] - data["stable_share__pre_30"]
        pre = data["total_routes__pre_30"].astype(float)
        post = data[f"total_routes__{period}"].astype(float)
        data["harmonic_route_mass"] = pre * post / (pre + post)
        data["mean_change"] = 1.0
        fit = ols_clustered(
            data["change"],
            data[["mean_change"]],
            data["ordered_pair"],
            add_constant=False,
            additional_clusters=(data["event_date"],),
            weights=data["harmonic_route_mass"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        rows.append(
            {
                "record_type": "exante_bridge_paired_change",
                "model_id": "stable_route_share_change",
                "period": period,
                "coefficient": float(fit.beta[0]),
                "standard_error": float(fit.standard_errors[0]),
                "p_value": float(fit.p_values[0]),
                "coefficient_pp": float(100.0 * fit.beta[0]),
                "standard_error_pp": float(100.0 * fit.standard_errors[0]),
                "n_observations": int(fit.n_observations),
                "events": int(len(data)),
                "ordered_pair_clusters": int(fit.cluster_counts[0]),
                "date_clusters": int(fit.cluster_counts[1]),
                "weight": "harmonic pre/post route mass",
            }
        )
    return pd.DataFrame(rows)


def relative_depth_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 100,
    min_clusters: int = 20,
) -> pd.DataFrame:
    """Relate stable-route share to prior-day relative weak-leg capital."""

    rows: list[dict[str, object]] = []
    for period in ("post_0_29", "post_30_119"):
        data = panel[
            panel["period"].eq(period)
            & panel["stable_bridge_min_capital_usd"].gt(0)
            & panel["native_bridge_min_capital_usd"].gt(0)
        ].replace([np.inf, -np.inf], np.nan).dropna(
            subset=[
                "stable_share",
                "stable_bridge_depth_share",
                "total_routes",
                "event_id",
                "ordered_pair",
                "origin_date",
                "event_time",
            ]
        ).copy()
        data["event_week"] = np.floor(data["event_time"] / 7).astype(int)
        data["calendar_month"] = data["origin_date"].dt.to_period("M").astype(str)
        controls = pd.concat(
            [
                pd.get_dummies(
                    data["event_week"], prefix="event_week", drop_first=True, dtype=float
                ),
                pd.get_dummies(
                    data["calendar_month"],
                    prefix="calendar_month",
                    drop_first=True,
                    dtype=float,
                ),
            ],
            axis=1,
        )
        variables = pd.concat(
            [data[["stable_share", "stable_bridge_depth_share"]], controls], axis=1
        )
        residual = absorb_fixed_effects(
            variables, data["event_id"], weights=data["total_routes"]
        )
        regressors = ["stable_bridge_depth_share"]
        design = residual[regressors].to_numpy(dtype=float)
        rank = int(np.linalg.matrix_rank(design))
        for control in controls.columns:
            proposal = np.column_stack([design, residual[control].to_numpy(dtype=float)])
            proposal_rank = int(np.linalg.matrix_rank(proposal))
            if proposal_rank > rank:
                regressors.append(control)
                design = proposal
                rank = proposal_rank
        fit = ols_clustered(
            residual["stable_share"],
            residual[regressors],
            data["ordered_pair"],
            add_constant=False,
            absorbed_groups=(data["event_id"],),
            additional_clusters=(data["origin_date"],),
            weights=data["total_routes"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        rows.append(
            {
                "record_type": "exante_bridge_relative_depth",
                "model_id": "stable_route_share_on_relative_depth",
                "period": period,
                "coefficient": float(fit.beta[0]),
                "standard_error": float(fit.standard_errors[0]),
                "p_value": float(fit.p_values[0]),
                "coefficient_pp_per_10pp_depth_share": float(10.0 * fit.beta[0]),
                "standard_error_pp_per_10pp_depth_share": float(
                    10.0 * fit.standard_errors[0]
                ),
                "n_observations": int(fit.n_observations),
                "events": int(data["event_id"].nunique()),
                "ordered_pair_clusters": int(fit.cluster_counts[0]),
                "date_clusters": int(fit.cluster_counts[1]),
                "fixed_effects": "bridge event and calendar month",
                "event_age_controls": "seven-day bins",
                "weight": "route count",
            }
        )
    return pd.DataFrame(rows)

#!/usr/bin/env python3
"""Audit adoption, abandonment, and persistence of V4 architecture use.

Calendar time is not treatment.  The treatment state is the realised V4 share
inside an ordered endpoint-pair x candidate-vehicle x week cell.  A cell may
enter V4, leave it, or re-enter it.  The outcome is the candidate's share of all
V3+V4 intermediary routes for the same ordered endpoint pair; it is deliberately
not the V4 share itself.

This is an E0 support and temporal-ordering diagnostic, not a causal estimate.
Entry can respond to anticipated demand.  Causal promotion requires cost/depth
first stages, pair-week comparisons, and non-adopter/placebo validation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import current_artifacts, stamp
from ddvc.tables import write_exhibit


ROOT = Path(__file__).resolve().parents[1]
ROUTES = DATA_DIR / "empirical" / "v4_settlement_route_units.parquet"
PANEL = DATA_DIR / "processed" / "architecture_state_weekly.parquet"
EXHIBITS = OUTPUT_DIR / "exhibits"
DEXES = ("uniswap_v3", "uniswap_v4")
KEYS = ["src", "sink", "vehicle"]
CODE = ["scripts/run_architecture_state_transitions.py"]


def build_full_risk_panel(routes: pd.DataFrame, *, min_total_routes: int = 10) -> pd.DataFrame:
    """Keep cells observed on either architecture; fill the other side with zero."""
    required = {"week", "src", "sink", "vehicle", "dex", "route_usd"}
    missing = sorted(required - set(routes.columns))
    if missing:
        raise ValueError(f"route-unit input missing columns: {', '.join(missing)}")
    d = routes[routes["dex"].isin(DEXES)].copy()
    d["week"] = pd.to_datetime(d["week"]).dt.normalize()
    grouped = (
        d.groupby(["week", *KEYS, "dex"], observed=True, as_index=False)
        .agg(routes=("dex", "size"), route_usd=("route_usd", "sum"))
    )
    wide = grouped.pivot(index=["week", *KEYS], columns="dex", values=["routes", "route_usd"])
    wide.columns = [f"{measure}_{dex}" for measure, dex in wide.columns]
    wide = wide.reset_index()
    for measure in ("routes", "route_usd"):
        for dex in DEXES:
            column = f"{measure}_{dex}"
            if column not in wide:
                wide[column] = 0.0
            wide[column] = wide[column].fillna(0.0)
    wide["total_routes"] = wide["routes_uniswap_v3"] + wide["routes_uniswap_v4"]
    wide["total_route_usd"] = wide["route_usd_uniswap_v3"] + wide["route_usd_uniswap_v4"]
    wide = wide[wide["total_routes"] >= min_total_routes].copy()
    wide["v4_route_share"] = wide["routes_uniswap_v4"] / wide["total_routes"]
    wide["v4_value_share"] = np.divide(
        wide["route_usd_uniswap_v4"],
        wide["total_route_usd"],
        out=np.full(len(wide), np.nan),
        where=wide["total_route_usd"].to_numpy() > 0,
    )
    pair_totals = wide.groupby(["week", "src", "sink"])["total_routes"].transform("sum")
    wide["vehicle_route_share"] = wide["total_routes"] / pair_totals
    return wide.sort_values([*KEYS, "week"], kind="stable").reset_index(drop=True)


def _consecutive(weeks: pd.Series) -> bool:
    return bool(weeks.diff().dropna().dt.days.eq(7).all())


def transition_events(
    panel: pd.DataFrame,
    *,
    threshold: float = 0.10,
    confirmation_weeks: int = 3,
) -> pd.DataFrame:
    """Find sustained 0->1 entries and 1->0 exits without a calendar-time dummy."""
    if not 0 < threshold < 1:
        raise ValueError("architecture-state threshold must lie strictly between zero and one")
    if confirmation_weeks < 2:
        raise ValueError("confirmation_weeks must be at least two")
    rows: list[dict] = []
    for key, group in panel.groupby(KEYS, sort=False, observed=True):
        group = group.sort_values("week", kind="stable").reset_index(drop=True)
        state = group["v4_route_share"].ge(threshold).astype(int).to_numpy()
        run = confirmation_weeks
        for position in range(run, len(group) - run + 1):
            window = group.iloc[position - run : position + run]
            if not _consecutive(window["week"]):
                continue
            before = state[position - run : position]
            after = state[position : position + run]
            kind = None
            if before.sum() == 0 and after.sum() == run:
                kind = "entry"
            elif before.sum() == run and after.sum() == 0:
                kind = "exit"
            if kind:
                rows.append(
                    {
                        **dict(zip(KEYS, key, strict=True)),
                        "event_week": group.loc[position, "week"],
                        "kind": kind,
                        "threshold": threshold,
                        "confirmation_weeks": run,
                    }
                )
    columns = [*KEYS, "event_week", "kind", "threshold", "confirmation_weeks"]
    return pd.DataFrame(rows, columns=columns)


def event_contrasts(panel: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Within-cell dynamics in overall vehicle use around entry and exit."""
    rows: list[dict] = []
    if events.empty:
        return pd.DataFrame()
    indexed = {key: group.set_index("week") for key, group in panel.groupby(KEYS, observed=True)}
    for event in events.itertuples(index=False):
        key = tuple(getattr(event, column) for column in KEYS)
        group = indexed[key]
        event_week = pd.Timestamp(event.event_week)
        wanted = pd.date_range(event_week - pd.Timedelta(weeks=8), event_week + pd.Timedelta(weeks=7), freq="7D")
        window = group.reindex(wanted)
        if window["vehicle_route_share"].isna().any():
            continue
        early_pre = float(window.iloc[0:4]["vehicle_route_share"].mean())
        late_pre = float(window.iloc[4:8]["vehicle_route_share"].mean())
        immediate = float(window.iloc[8:12]["vehicle_route_share"].mean())
        persistent = float(window.iloc[12:16]["vehicle_route_share"].mean())
        rows.append(
            {
                **dict(zip(KEYS, key, strict=True)),
                "event_week": event_week,
                "kind": event.kind,
                "threshold": event.threshold,
                "confirmation_weeks": event.confirmation_weeks,
                "outcome": "overall V3+V4 vehicle route share",
                "early_pre": early_pre,
                "late_pre": late_pre,
                "pretrend_change": late_pre - early_pre,
                "immediate_post": immediate,
                "persistent_post": persistent,
                "immediate_change": immediate - late_pre,
                "persistent_change": persistent - late_pre,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, default=ROUTES)
    parser.add_argument("--min-total-routes", type=int, default=10)
    parser.add_argument("--thresholds", default="0.05,0.10,0.25")
    parser.add_argument("--confirmation-weeks", type=int, default=3)
    args = parser.parse_args()
    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]

    with current_artifacts([args.routes], consumer="architecture-state transition audit"):
        routes = pd.read_parquet(args.routes)
        panel = build_full_risk_panel(routes, min_total_routes=args.min_total_routes)
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL, index=False)
    stamp(PANEL, code_sources=CODE, inputs=[args.routes], rows=len(panel))

    all_events = []
    for threshold in thresholds:
        all_events.append(
            transition_events(
                panel,
                threshold=threshold,
                confirmation_weeks=args.confirmation_weeks,
            )
        )
    events = pd.concat(all_events, ignore_index=True)
    contrasts = event_contrasts(panel, events)
    write_exhibit(events, EXHIBITS / "architecture_transition_events.jsonl", code_sources=CODE, inputs=[PANEL])
    write_exhibit(contrasts, EXHIBITS / "architecture_transition_contrasts.jsonl", code_sources=CODE, inputs=[PANEL])
    support = (
        events.groupby(["threshold", "kind"], as_index=False).size()
        if not events.empty
        else pd.DataFrame(columns=["threshold", "kind", "size"])
    )
    print(support.to_string(index=False))
    print("E0 support audit only: calendar time is not treatment; no causal claim promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

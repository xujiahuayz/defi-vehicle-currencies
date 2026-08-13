#!/usr/bin/env python3
"""Audit adoption, abandonment, and persistence of V4 architecture use.

Calendar time is not treatment.  The treatment state is the realised V4 share
inside an ordered endpoint-pair x candidate-vehicle x week cell.  A cell may
enter V4, leave it, or re-enter it.  The outcome is the candidate's share of all
V3+V4 intermediary routes for the same ordered endpoint pair; it is deliberately
not the V4 share itself.

This is an E0 support and temporal-ordering diagnostic, not a causal estimate.
Entry can respond to anticipated demand.  The primary outcome removes the
ordered-pair x week mean across candidate vehicles, but causal promotion still
requires cost/depth first stages and non-adopter/placebo validation.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import current_artifacts, portable_content_sha256, stamp
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


ROOT = Path(__file__).resolve().parents[1]
ROUTES = DATA_DIR / "empirical" / "v4_settlement_route_units.parquet"
PANEL = DATA_DIR / "processed" / "architecture_state_weekly.parquet"
ROLE_PANEL = DATA_DIR / "processed" / "architecture_role_risk_weekly.parquet"
EXHIBITS = OUTPUT_DIR / "exhibits"
DECK_VALUES = EXHIBITS / "architecture_transition_deck_values.tex"
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
    wide["v4_route_share"] = wide["routes_uniswap_v4"] / wide["total_routes"]
    wide["v4_value_share"] = np.divide(
        wide["route_usd_uniswap_v4"],
        wide["total_route_usd"],
        out=np.full(len(wide), np.nan),
        where=wide["total_route_usd"].to_numpy() > 0,
    )
    pair_keys = ["week", "src", "sink"]
    pair_totals = wide.groupby(pair_keys)["total_routes"].transform("sum")
    wide["vehicle_route_share"] = wide["total_routes"] / pair_totals
    pair_week = wide.groupby(pair_keys)["vehicle_route_share"]
    wide["pair_week_candidate_count"] = pair_week.transform("size")
    vehicle_sets = wide.groupby(pair_keys)["vehicle"].transform(
        lambda values: hashlib.sha256(
            "\n".join(sorted(map(str, values))).encode()
        ).hexdigest()
    )
    wide["pair_week_vehicle_set_sha256"] = vehicle_sets
    wide["pair_week_adjusted_vehicle_share"] = (
        wide["vehicle_route_share"] - pair_week.transform("mean")
    ).where(wide["pair_week_candidate_count"].ge(2))
    wide = wide[wide["total_routes"] >= min_total_routes].copy()
    return wide.sort_values([*KEYS, "week"], kind="stable").reset_index(drop=True)


def build_role_risk_panel(
    routes: pd.DataFrame,
    *,
    min_state_routes: int = 10,
) -> pd.DataFrame:
    """Fill zero-use candidate weeks while the ordered pair remains active.

    A candidate enters the risk set if it is observed at least once for an
    ordered pair.  It then receives an explicit zero in every active pair-week,
    including before first use and after last use.  A week in which the ordered
    pair itself is absent remains outside the risk set; it is not evidence that
    the candidate vehicle disappeared.
    """
    observed = build_full_risk_panel(routes, min_total_routes=0)
    if observed.empty:
        return observed
    pair_weeks = observed[["week", "src", "sink"]].drop_duplicates()
    pair_vehicles = observed[["src", "sink", "vehicle"]].drop_duplicates()
    grid = pair_weeks.merge(pair_vehicles, on=["src", "sink"], how="inner")
    value_columns = [
        f"{measure}_{dex}"
        for measure in ("routes", "route_usd")
        for dex in DEXES
    ]
    balanced = grid.merge(
        observed[["week", *KEYS, *value_columns]],
        on=["week", *KEYS],
        how="left",
        validate="one_to_one",
    )
    balanced[value_columns] = balanced[value_columns].fillna(0.0)
    balanced["total_routes"] = (
        balanced["routes_uniswap_v3"] + balanced["routes_uniswap_v4"]
    )
    balanced["total_route_usd"] = (
        balanced["route_usd_uniswap_v3"] + balanced["route_usd_uniswap_v4"]
    )
    balanced["v4_route_share"] = np.divide(
        balanced["routes_uniswap_v4"],
        balanced["total_routes"],
        out=np.full(len(balanced), np.nan),
        where=balanced["total_routes"].to_numpy() > 0,
    )
    balanced["v4_value_share"] = np.divide(
        balanced["route_usd_uniswap_v4"],
        balanced["total_route_usd"],
        out=np.full(len(balanced), np.nan),
        where=balanced["total_route_usd"].to_numpy() > 0,
    )
    pair_keys = ["week", "src", "sink"]
    pair_totals = balanced.groupby(pair_keys)["total_routes"].transform("sum")
    balanced["vehicle_route_share"] = balanced["total_routes"] / pair_totals
    pair_week = balanced.groupby(pair_keys)["vehicle_route_share"]
    balanced["pair_week_candidate_count"] = pair_week.transform("size")
    balanced["pair_week_vehicle_set_sha256"] = balanced.groupby(pair_keys)[
        "vehicle"
    ].transform(
        lambda values: hashlib.sha256(
            "\n".join(sorted(map(str, values))).encode()
        ).hexdigest()
    )
    balanced["pair_week_adjusted_vehicle_share"] = (
        balanced["vehicle_route_share"] - pair_week.transform("mean")
    ).where(balanced["pair_week_candidate_count"].ge(2))
    balanced["cell_support_state"] = np.select(
        [
            balanced["total_routes"].eq(0),
            balanced["total_routes"].ge(min_state_routes),
        ],
        ["absent", "supported"],
        default="low_support",
    )
    return balanced.sort_values([*KEYS, "week"], kind="stable").reset_index(drop=True)


def _consecutive(weeks: pd.Series) -> bool:
    return bool(weeks.diff().dropna().dt.days.eq(7).all())


def transition_events(
    panel: pd.DataFrame,
    *,
    threshold: float = 0.10,
    confirmation_weeks: int = 3,
) -> pd.DataFrame:
    """Find sustained 0->1 entries and 1->0 exits among observed route cells.

    Because the input panel contains positive-use cells, an exit here is
    architecture substitution within a surviving vehicle cell.  Exit through
    disappearance of the vehicle role is a separate extensive-margin estimand,
    not silently coded as a below-threshold week.
    """
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
                        "transition_margin": "within_observed_vehicle_cell",
                        "threshold": threshold,
                        "confirmation_weeks": run,
                    }
                )
    columns = [
        *KEYS,
        "event_week",
        "kind",
        "transition_margin",
        "threshold",
        "confirmation_weeks",
    ]
    return pd.DataFrame(rows, columns=columns)


def role_margin_events(
    panel: pd.DataFrame,
    *,
    threshold: float = 0.10,
    confirmation_weeks: int = 3,
) -> pd.DataFrame:
    """Find V4-active vehicle-role appearance and disappearance events."""
    if not 0 < threshold < 1:
        raise ValueError("architecture-state threshold must lie strictly between zero and one")
    if confirmation_weeks < 2:
        raise ValueError("confirmation_weeks must be at least two")
    rows: list[dict] = []
    run = confirmation_weeks
    for key, group in panel.groupby(KEYS, sort=False, observed=True):
        group = group.sort_values("week", kind="stable").reset_index(drop=True)
        active = (
            group["cell_support_state"].eq("supported")
            & group["v4_route_share"].ge(threshold)
        ).to_numpy()
        absent = group["cell_support_state"].eq("absent").to_numpy()
        for position in range(run, len(group) - run + 1):
            window = group.iloc[position - run : position + run]
            if not _consecutive(window["week"]):
                continue
            before_active = bool(active[position - run : position].all())
            after_active = bool(active[position : position + run].all())
            before_absent = bool(absent[position - run : position].all())
            after_absent = bool(absent[position : position + run].all())
            if before_absent and after_active:
                kind = "entry"
                margin = "vehicle_role_appearance"
            elif before_active and after_absent:
                kind = "exit"
                margin = "vehicle_role_disappearance"
            else:
                continue
            rows.append(
                {
                    **dict(zip(KEYS, key, strict=True)),
                    "event_week": group.loc[position, "week"],
                    "kind": kind,
                    "transition_margin": margin,
                    "threshold": threshold,
                    "confirmation_weeks": run,
                }
            )
    columns = [
        *KEYS,
        "event_week",
        "kind",
        "transition_margin",
        "threshold",
        "confirmation_weeks",
    ]
    return pd.DataFrame(rows, columns=columns)


def event_contrasts(panel: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Pair-week-adjusted vehicle-use dynamics around isolated entry and exit."""
    rows: list[dict] = []
    if events.empty:
        return pd.DataFrame()
    indexed = {key: group.set_index("week") for key, group in panel.groupby(KEYS, observed=True)}
    event_index = {
        key: group["event_week"].map(pd.Timestamp).tolist()
        for key, group in events.groupby([*KEYS, "threshold"], observed=True)
    }
    for event in events.itertuples(index=False):
        key = tuple(getattr(event, column) for column in KEYS)
        group = indexed[key]
        event_week = pd.Timestamp(event.event_week)
        event_key = (*key, event.threshold)
        nearby = [
            week
            for week in event_index[event_key]
            if week != event_week and abs(week - event_week) < pd.Timedelta(weeks=16)
        ]
        base = {
            **dict(zip(KEYS, key, strict=True)),
            "event_week": event_week,
            "kind": event.kind,
            "transition_margin": event.transition_margin,
            "threshold": event.threshold,
            "confirmation_weeks": event.confirmation_weeks,
            "outcome": "pair-week-adjusted overall V3+V4 vehicle route share",
            "early_pre": np.nan,
            "late_pre": np.nan,
            "pretrend_change": np.nan,
            "immediate_post": np.nan,
            "persistent_post": np.nan,
            "immediate_change": np.nan,
            "persistent_change": np.nan,
            "raw_immediate_change": np.nan,
            "raw_persistent_change": np.nan,
        }
        if nearby:
            rows.append({**base, "status": "overlapping_transition"})
            continue
        wanted = pd.date_range(event_week - pd.Timedelta(weeks=8), event_week + pd.Timedelta(weeks=7), freq="7D")
        window = group.reindex(wanted)
        if window["pair_week_vehicle_set_sha256"].nunique(dropna=False) != 1:
            rows.append({**base, "status": "composition_shift"})
            continue
        if window["pair_week_adjusted_vehicle_share"].isna().any():
            rows.append({**base, "status": "incomplete_window"})
            continue

        def periods(column: str) -> tuple[float, float, float, float]:
            return tuple(
                float(section[column].mean())
                for section in (
                    window.iloc[0:4],
                    window.iloc[4:8],
                    window.iloc[8:12],
                    window.iloc[12:16],
                )
            )

        early_pre, late_pre, immediate, persistent = periods(
            "pair_week_adjusted_vehicle_share"
        )
        _, raw_late_pre, raw_immediate, raw_persistent = periods(
            "vehicle_route_share"
        )
        rows.append(
            {
                **base,
                "status": "usable",
                "early_pre": early_pre,
                "late_pre": late_pre,
                "pretrend_change": late_pre - early_pre,
                "immediate_post": immediate,
                "persistent_post": persistent,
                "immediate_change": immediate - late_pre,
                "persistent_change": persistent - late_pre,
                "raw_immediate_change": raw_immediate - raw_late_pre,
                "raw_persistent_change": raw_persistent - raw_late_pre,
            }
        )
    return pd.DataFrame(rows)


def summarize_transition_support(
    contrasts: pd.DataFrame,
    *,
    thresholds: Iterable[float],
    transition_kinds: Iterable[tuple[str, str]] = (
        ("entry", "within_observed_vehicle_cell"),
        ("exit", "within_observed_vehicle_cell"),
    ),
) -> pd.DataFrame:
    """Build the presentation-facing support and E0 contrast table.

    The full threshold-by-kind grid is retained, including zero-event cells.
    Means are descriptive across usable events; they are not causal estimates
    and deliberately carry no model-based significance stars.
    """
    rows: list[dict] = []
    statuses = (
        "usable",
        "overlapping_transition",
        "incomplete_window",
        "composition_shift",
    )
    for threshold in thresholds:
        for kind, transition_margin in transition_kinds:
            if contrasts.empty:
                group = contrasts
            else:
                group = contrasts[
                    contrasts["threshold"].eq(threshold)
                    & contrasts["kind"].eq(kind)
                    & contrasts["transition_margin"].eq(transition_margin)
                ]
            usable = group[group["status"].eq("usable")] if not group.empty else group
            row = {
                "threshold": threshold,
                "kind": kind,
                "transition_margin": transition_margin,
                "detected_events": int(len(group)),
                "distinct_cells": (
                    int(group[KEYS].drop_duplicates().shape[0]) if not group.empty else 0
                ),
                **{
                    f"{status}_events": int(group["status"].eq(status).sum())
                    if not group.empty
                    else 0
                    for status in statuses
                },
            }
            for column in ("pretrend_change", "immediate_change", "persistent_change"):
                row[f"mean_{column}"] = (
                    float(usable[column].mean()) if not usable.empty else np.nan
                )
            rows.append(row)
    return pd.DataFrame(rows)


def render_transition_deck_values(
    support: pd.DataFrame,
    role_support: pd.DataFrame,
    *,
    generation: str,
) -> str:
    """Render projection-facing macros from the two audited support tables."""
    thresholds = ((0.05, "Five"), (0.10, "Ten"), (0.25, "TwentyFive"))

    def row(
        frame: pd.DataFrame,
        threshold: float,
        kind: str,
        margin: str,
    ) -> pd.Series | None:
        selected = frame[
            frame["threshold"].eq(threshold)
            & frame["kind"].eq(kind)
            & frame["transition_margin"].eq(margin)
        ]
        return None if selected.empty else selected.iloc[0]

    def support_cell(record: pd.Series | None) -> str:
        if record is None:
            return "--"
        return f"{int(record.detected_events):,} ({int(record.usable_events):,})"

    def contrast_cell(record: pd.Series | None, column: str) -> str:
        if record is None or pd.isna(record[column]):
            return "--"
        value = 100 * float(record[column])
        return f"{value:+.2f}\\,pp"

    lines = [
        "% Generated by scripts/run_architecture_state_transitions.py; do not edit.",
        f"\\newcommand{{\\ArchRouteGeneration}}{{\\texttt{{{generation[:12]}}}}}",
    ]
    for threshold, suffix in thresholds:
        entry = row(
            support,
            threshold,
            "entry",
            "within_observed_vehicle_cell",
        )
        exit_record = row(
            support,
            threshold,
            "exit",
            "within_observed_vehicle_cell",
        )
        disappearance = row(
            role_support,
            threshold,
            "exit",
            "vehicle_role_disappearance",
        )
        values = {
            f"ArchEntrySupport{suffix}": support_cell(entry),
            f"ArchExitSupport{suffix}": support_cell(exit_record),
            f"ArchDisappearSupport{suffix}": support_cell(disappearance),
            f"ArchEntryImmediate{suffix}": contrast_cell(entry, "mean_immediate_change"),
            f"ArchExitImmediate{suffix}": contrast_cell(
                exit_record,
                "mean_immediate_change",
            ),
        }
        lines.extend(
            f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in values.items()
        )
    return "\n".join(lines) + "\n"


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
        role_panel = build_role_risk_panel(
            routes,
            min_state_routes=args.min_total_routes,
        )
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL, index=False)
    stamp(PANEL, code_sources=CODE, inputs=[args.routes], rows=len(panel))
    ROLE_PANEL.parent.mkdir(parents=True, exist_ok=True)
    role_panel.to_parquet(ROLE_PANEL, index=False)
    stamp(ROLE_PANEL, code_sources=CODE, inputs=[args.routes], rows=len(role_panel))

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
    support = summarize_transition_support(contrasts, thresholds=thresholds)
    write_exhibit(
        support,
        EXHIBITS / "architecture_transition_support.jsonl",
        code_sources=CODE,
        inputs=[PANEL],
        notes=(
            "Presentation-facing E0 support table. Mean changes are descriptive "
            "across usable events, not causal estimates."
        ),
    )
    role_events = pd.concat(
        [
            role_margin_events(
                role_panel,
                threshold=threshold,
                confirmation_weeks=args.confirmation_weeks,
            )
            for threshold in thresholds
        ],
        ignore_index=True,
    )
    role_contrasts = event_contrasts(role_panel, role_events)
    role_support = summarize_transition_support(
        role_contrasts,
        thresholds=thresholds,
        transition_kinds=(
            ("entry", "vehicle_role_appearance"),
            ("exit", "vehicle_role_disappearance"),
        ),
    )
    write_exhibit(
        role_events,
        EXHIBITS / "architecture_role_margin_events.jsonl",
        code_sources=CODE,
        inputs=[ROLE_PANEL],
    )
    write_exhibit(
        role_contrasts,
        EXHIBITS / "architecture_role_margin_contrasts.jsonl",
        code_sources=CODE,
        inputs=[ROLE_PANEL],
    )
    write_exhibit(
        role_support,
        EXHIBITS / "architecture_role_margin_support.jsonl",
        code_sources=CODE,
        inputs=[ROLE_PANEL],
        notes=(
            "E0 extensive-margin support among active ordered-pair weeks. "
            "Candidate risk sets condition on ever being observed for the pair; "
            "pair disappearance is not coded as vehicle-role disappearance."
        ),
    )
    deck_source = render_transition_deck_values(
        support,
        role_support,
        generation=portable_content_sha256(args.routes),
    )
    with atomic_output(DECK_VALUES) as temporary:
        temporary.write_text(deck_source, encoding="utf-8")
    stamp(
        DECK_VALUES,
        code_sources=CODE,
        inputs=[
            args.routes,
            EXHIBITS / "architecture_transition_support.jsonl",
            EXHIBITS / "architecture_role_margin_support.jsonl",
        ],
        rows=len(support) + len(role_support),
        notes="Generated provisional-deck macros; support cells are detected (usable).",
    )
    print(support.to_string(index=False))
    print(role_support.to_string(index=False))
    print("E0 support audit only: calendar time is not treatment; no causal claim promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

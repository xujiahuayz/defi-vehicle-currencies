#!/usr/bin/env python3
"""Test whether an entry vehicle persists against an executable price leader.

The exact-price panel holds endpoint pair, input amount, and pretrade state
fixed. Joining it to each pair's first observed native-or-stable vehicle lets us
ask whether the incumbent still carries a route when the other vehicle gives
more output and both hypothetical legs satisfy the five-percent impact bound.

Reads   data/processed/exact_vehicle_frontier_monthly.parquet
        data/processed/endpoint_candidate_pair_support.parquet
Writes  output/exhibits/entry_vehicle_exact_price_alignment.jsonl
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import atomic_output, exclusive_job


FRONTIER = DATA_DIR / "processed/exact_vehicle_frontier_monthly.parquet"
PAIR_SUPPORT = DATA_DIR / "processed/endpoint_candidate_pair_support.parquet"
OUTPUT = OUTPUT_DIR / "exhibits/entry_vehicle_exact_price_alignment.jsonl"
LOCK = SHARED_RUNTIME_DIR / "entry-vehicle-price-alignment.lock"
HORIZONS = (30, 120)
MIN_INPUT_USD = 100.0
MIN_GAIN_BPS = 1.0
MAX_PRICE_IMPACT = 0.05
VEHICLE_TYPES = ("native", "stable")


def entry_vehicle_panel(pair_support: pd.DataFrame) -> pd.DataFrame:
    """Return one first-observed majority vehicle for each ordered pair."""

    required = {
        "date",
        "src",
        "tgt",
        "pair_entry_on_day",
        "primary_choice_route_count",
        "stable_choice_route_count",
        "native_choice_route_count",
    }
    missing = sorted(required - set(pair_support.columns))
    if missing:
        raise ValueError(f"pair-support input lacks entry columns: {missing}")
    entries = pair_support[
        pair_support["pair_entry_on_day"].astype(bool)
        & pd.to_numeric(
            pair_support["primary_choice_route_count"], errors="coerce"
        ).gt(0)
    ].copy()
    entries["entry_date"] = pd.to_datetime(entries["date"], errors="raise").dt.normalize()
    stable = pd.to_numeric(entries["stable_choice_route_count"], errors="raise")
    native = pd.to_numeric(entries["native_choice_route_count"], errors="raise")
    entries["entry_vehicle_type"] = np.select(
        [stable.gt(native), native.gt(stable)],
        ["stable", "native"],
        default="mixed",
    )
    entries = entries[entries["entry_vehicle_type"].isin(VEHICLE_TYPES)].copy()
    entries = entries.sort_values(["entry_date", "src", "tgt"], kind="stable")
    if entries.duplicated(["src", "tgt"]).any():
        duplicates = entries[entries.duplicated(["src", "tgt"], keep=False)]
        raise ValueError(
            "pair-support input has multiple entry dates for "
            f"{duplicates[['src', 'tgt']].drop_duplicates().shape[0]} pairs"
        )
    return entries[["src", "tgt", "entry_date", "entry_vehicle_type"]]


def prepare_alignment_panel(
    frontier: pd.DataFrame,
    pair_support: pd.DataFrame,
) -> pd.DataFrame:
    """Join exact route prices to pair entry state and define the price leader."""

    required = {
        "day",
        "token_in",
        "token_out",
        "route_id",
        "input_usd",
        "within_20pct",
        "chosen_max_price_impact",
        "chosen_vehicle_type",
        "public_vehicle_type",
        "public_path_regret_bps",
    }
    missing = sorted(required - set(frontier.columns))
    if missing:
        raise ValueError(f"exact-price panel lacks alignment columns: {missing}")
    routes = frontier.copy()
    day_text = routes["day"].astype(str).str.replace(r"\.0$", "", regex=True)
    routes["date"] = pd.to_datetime(day_text, format="%Y%m%d", errors="raise")
    for column in ("input_usd", "chosen_max_price_impact", "public_path_regret_bps"):
        routes[column] = pd.to_numeric(routes[column], errors="raise")
    routes = routes[
        routes["within_20pct"].astype(bool)
        & routes["input_usd"].ge(MIN_INPUT_USD)
        & routes["chosen_max_price_impact"].le(MAX_PRICE_IMPACT)
        & routes["chosen_vehicle_type"].isin(VEHICLE_TYPES)
    ].copy()
    entries = entry_vehicle_panel(pair_support)
    panel = routes.merge(
        entries,
        left_on=["token_in", "token_out"],
        right_on=["src", "tgt"],
        how="inner",
        validate="many_to_one",
    )
    if panel.empty:
        raise ValueError("entry-price alignment join is empty")
    panel["pair_age_days"] = (panel["date"] - panel["entry_date"]).dt.days
    panel = panel[panel["pair_age_days"].ge(min(HORIZONS))].copy()
    if panel.empty:
        raise ValueError("entry-price alignment has no mature pair observations")
    improved = panel["public_path_regret_bps"].gt(MIN_GAIN_BPS)
    binary_public = panel["public_vehicle_type"].isin(VEHICLE_TYPES)
    panel["price_leader_type"] = panel["chosen_vehicle_type"].where(
        ~(improved & binary_public), panel["public_vehicle_type"]
    )
    panel.loc[improved & ~binary_public, "price_leader_type"] = pd.NA
    panel["chosen_matches_entry"] = panel["chosen_vehicle_type"].eq(
        panel["entry_vehicle_type"]
    )
    panel["price_leader_matches_entry"] = panel["price_leader_type"].eq(
        panel["entry_vehicle_type"]
    )
    panel["price_leader_relation"] = np.where(
        panel["price_leader_matches_entry"], "incumbent", "challenger"
    )
    panel["exact_vehicle_challenge"] = (
        improved
        & binary_public
        & panel["public_vehicle_type"].ne(panel["entry_vehicle_type"])
        & panel["chosen_matches_entry"]
    )
    return panel


def summarize_alignment(panel: pd.DataFrame) -> pd.DataFrame:
    """Report route- and pair-day-weighted incumbent use by exact price leader."""

    rows: list[dict[str, object]] = []

    def append_groups(frame: pd.DataFrame, *, horizon: int, weighting: str) -> None:
        entry_groups = [("pooled", frame), *frame.groupby("entry_vehicle_type", sort=True)]
        for entry_type, entry_frame in entry_groups:
            for relation, group in entry_frame.groupby("price_leader_relation", sort=True):
                rows.append(
                    {
                        "record_type": "entry_price_leader_alignment",
                        "horizon_days": horizon,
                        "weighting": weighting,
                        "entry_vehicle_type": str(entry_type),
                        "price_leader_relation": str(relation),
                        "observations": int(len(group)),
                        "pairs": int(group[["src", "tgt"]].drop_duplicates().shape[0]),
                        "incumbent_vehicle_share": float(group["chosen_matches_entry"].mean()),
                        "median_public_gain_bps": float(
                            pd.to_numeric(group["public_path_regret_bps"]).median()
                        ),
                    }
                )

    for horizon in HORIZONS:
        selected = panel[panel["pair_age_days"].ge(horizon)].copy()
        selected = selected[selected["price_leader_type"].isin(VEHICLE_TYPES)].copy()
        if selected.empty:
            continue
        append_groups(selected, horizon=horizon, weighting="route")
        pair_day = (
            selected.groupby(
                [
                    "date",
                    "src",
                    "tgt",
                    "entry_vehicle_type",
                    "price_leader_relation",
                ],
                as_index=False,
                sort=True,
            )
            .agg(
                chosen_matches_entry=("chosen_matches_entry", "mean"),
                public_path_regret_bps=("public_path_regret_bps", "median"),
            )
        )
        append_groups(pair_day, horizon=horizon, weighting="pair_day")

        incumbent = selected[selected["chosen_matches_entry"]].copy()
        for entry_type, group in [("pooled", incumbent), *incumbent.groupby("entry_vehicle_type", sort=True)]:
            rows.append(
                {
                    "record_type": "incumbent_route_challenge_rate",
                    "horizon_days": horizon,
                    "weighting": "route",
                    "entry_vehicle_type": str(entry_type),
                    "price_leader_relation": "challenger_offer_over_1bp",
                    "observations": int(len(group)),
                    "pairs": int(group[["src", "tgt"]].drop_duplicates().shape[0]),
                    "incumbent_vehicle_share": float(group["exact_vehicle_challenge"].mean()),
                    "median_public_gain_bps": float(
                        group.loc[group["exact_vehicle_challenge"], "public_path_regret_bps"].median()
                    ),
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("entry-price alignment summaries are empty")
    result["minimum_input_usd"] = MIN_INPUT_USD
    result["minimum_gain_bps"] = MIN_GAIN_BPS
    result["maximum_leg_price_impact"] = MAX_PRICE_IMPACT
    result["estimand"] = "incumbent_vehicle_use_conditional_on_exact_pretrade_price_leader"
    return result


def run(
    *,
    root: Path = REPO_ROOT,
    frontier_path: Path = FRONTIER,
    pair_support_path: Path = PAIR_SUPPORT,
    output_path: Path = OUTPUT,
) -> int:
    paths = []
    for path in (frontier_path, pair_support_path, output_path):
        paths.append(path if path.is_absolute() else root / path)
    frontier_path, pair_support_path, output_path = paths
    for path in (frontier_path, pair_support_path):
        if not path.is_file():
            raise FileNotFoundError(f"entry-price input is missing: {path}")
    frontier = pd.read_parquet(frontier_path)
    pair_support = pd.read_parquet(
        pair_support_path,
        columns=[
            "date",
            "src",
            "tgt",
            "pair_entry_on_day",
            "primary_choice_route_count",
            "stable_choice_route_count",
            "native_choice_route_count",
        ],
    )
    result = summarize_alignment(prepare_alignment_panel(frontier, pair_support))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output_path) as temporary:
        result.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    print(f"wrote {len(result):,} entry-price alignment rows")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    with exclusive_job(LOCK, job="entry-vehicle exact-price alignment"):
        raise SystemExit(main())

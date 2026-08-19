#!/usr/bin/env python3
"""Compare V3 and V4 candidate-linked reported TVL on the same V4-active origins.

Reads:
  data/processed/liquidity_capital_v2_candidate_day.parquet
  data/processed/v3_pool_day_fees.parquet
  data/processed/v4_candidate_linked_pool_tvl_daily.parquet
  data/processed/v4_flash_accounting_candidate_daily.parquet

Writes:
  output/exhibits/v3_v4_tvl_protocol_contrast.jsonl
  output/exhibits/v3_v4_tvl_protocol_contrast_support.jsonl

The unit is a stacked protocol--candidate--origin-day row. The sample is
restricted to candidate-origin days with observed V4 singleton swap activity and
with strict origin/target support in both protocols. The quantity is
candidate-linked reported pool TVL, not reconstructed deposited capital or
side-specific LP inventory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit
from scripts.analyze.run_v3_v4_lp_protocol_contrast import (
    load_share_gap_panel,
    load_v4_active_origins,
)
from scripts.process.build_v4_candidate_linked_pool_tvl_daily import (
    TVL_USD_UPPER_BOUND,
    vehicle_candidate_map,
)


V3_POOL_DAY_INPUT = REPO_ROOT / "data/processed/v3_pool_day_fees.parquet"
V4_TVL_INPUT = REPO_ROOT / "data/processed/v4_candidate_linked_pool_tvl_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_tvl_protocol_contrast.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_tvl_protocol_contrast_support.jsonl"

HORIZONS = (7, 30, 120)
OUTCOMES = ("future_delta_log1p_tvl", "future_delta_log1p_pool_count")
CONTROLS = ("origin_log1p_tvl", "origin_log1p_pool_count")
CODE_SOURCES = [
    "scripts/analyze/run_v3_v4_tvl_protocol_contrast.py",
    "scripts/process/build_v4_candidate_linked_pool_tvl_daily.py",
    "scripts/analyze/run_v3_v4_lp_protocol_contrast.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
    "data/processed/v3_pool_day_fees.parquet",
    "data/processed/v4_candidate_linked_pool_tvl_daily.parquet",
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
]


def _normalise_address(frame: pd.DataFrame, column: str) -> None:
    frame[column] = frame[column].astype(str).str.lower()


def build_v3_candidate_linked_tvl(
    pool_day: pd.DataFrame,
    *,
    candidates: Mapping[str, tuple[str, str]],
) -> pd.DataFrame:
    """Return V3 candidate-linked reported TVL daily rows.

    A pool containing a candidate token contributes its full reported TVL to the
    candidate side, matching the V4 candidate-linked TVL construction. This is a
    stock-side footprint proxy, not side-specific deposited capital.
    """

    required = {
        "origin_date",
        "pool",
        "token0_address",
        "token1_address",
        "tvl_usd",
        "volume_usd",
    }
    missing = sorted(required - set(pool_day.columns))
    if missing:
        raise ValueError(f"V3 pool-day fee panel lacks columns: {missing}")
    frame = pool_day.copy()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    _normalise_address(frame, "token0_address")
    _normalise_address(frame, "token1_address")
    linked_rows: list[pd.DataFrame] = []
    for side in ("token0", "token1"):
        candidate_lookup = frame[f"{side}_address"].map(candidates)
        side_frame = frame[candidate_lookup.notna()].copy()
        if side_frame.empty:
            continue
        side_candidates = candidate_lookup[candidate_lookup.notna()]
        side_frame["candidate_address"] = [value[0] for value in side_candidates]
        side_frame["candidate_symbol"] = [value[1] for value in side_candidates]
        side_frame["candidate_linked_pool_tvl_usd"] = pd.to_numeric(
            side_frame["tvl_usd"], errors="coerce"
        )
        side_frame["candidate_linked_pool_volume_usd"] = pd.to_numeric(
            side_frame["volume_usd"], errors="coerce"
        )
        linked_rows.append(
            side_frame[
                [
                    "origin_date",
                    "pool",
                    "candidate_address",
                    "candidate_symbol",
                    "candidate_linked_pool_tvl_usd",
                    "candidate_linked_pool_volume_usd",
                ]
            ]
        )
    if not linked_rows:
        raise ValueError("V3 pool-day panel contains no vehicle-candidate pools")
    linked = pd.concat(linked_rows, ignore_index=True, sort=False)
    linked = linked[
        np.isfinite(linked["candidate_linked_pool_tvl_usd"])
        & linked["candidate_linked_pool_tvl_usd"].between(0.0, TVL_USD_UPPER_BOUND)
    ].copy()
    if linked.empty:
        raise ValueError("V3 candidate-linked TVL panel is empty after screens")
    return (
        linked.groupby(
            ["origin_date", "candidate_address", "candidate_symbol"],
            as_index=False,
            sort=True,
        )
        .agg(
            tvl_usd=("candidate_linked_pool_tvl_usd", "sum"),
            volume_usd=("candidate_linked_pool_volume_usd", "sum"),
            pool_count=("pool", "nunique"),
        )
    )


def load_v4_candidate_linked_tvl(path: Path = V4_TVL_INPUT) -> pd.DataFrame:
    """Return V4 candidate-linked reported TVL daily rows."""

    frame = pd.read_parquet(path)
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "candidate_linked_pool_tvl_usd",
        "candidate_linked_pool_volume_usd",
        "capital_valid",
        "pool",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V4 candidate-linked TVL panel lacks columns: {missing}")
    frame = frame[frame["capital_valid"].astype(bool)].copy()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    _normalise_address(frame, "candidate_address")
    if frame.empty:
        raise ValueError("V4 candidate-linked TVL panel is empty after screens")
    return (
        frame.groupby(
            ["origin_date", "candidate_address", "candidate_symbol"],
            as_index=False,
            sort=True,
        )
        .agg(
            tvl_usd=("candidate_linked_pool_tvl_usd", "sum"),
            volume_usd=("candidate_linked_pool_volume_usd", "sum"),
            pool_count=("pool", "nunique"),
        )
    )


def protocol_horizon_panel(
    share_gap_panel: pd.DataFrame,
    tvl_daily: pd.DataFrame,
    *,
    protocol: str,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Attach future strict-support reported TVL outcomes for one protocol."""

    if protocol not in {"v3", "v4"}:
        raise ValueError("protocol must be v3 or v4")
    if tvl_daily.empty:
        raise ValueError(f"{protocol} TVL daily panel is empty")
    min_date = pd.to_datetime(tvl_daily["origin_date"]).min()
    max_date = pd.to_datetime(tvl_daily["origin_date"]).max()
    tvl_frame = tvl_daily.copy()
    tvl_frame["origin_date"] = pd.to_datetime(tvl_frame["origin_date"]).dt.normalize()
    _normalise_address(tvl_frame, "candidate_address")
    horizon_rows: list[pd.DataFrame] = []
    for candidate_address, candidate_gap in share_gap_panel.groupby(
        "candidate_address", sort=True
    ):
        candidate_tvl = tvl_frame[
            tvl_frame["candidate_address"].eq(candidate_address)
        ][["origin_date", "candidate_address", "tvl_usd", "volume_usd", "pool_count"]]
        if candidate_tvl.empty:
            continue
        for horizon in horizons:
            origin = candidate_gap[
                candidate_gap["origin_date"].between(
                    min_date, max_date - pd.Timedelta(days=int(horizon))
                )
            ].copy()
            if origin.empty:
                continue
            origin = origin.merge(
                candidate_tvl.rename(
                    columns={
                        "tvl_usd": "origin_tvl_usd",
                        "volume_usd": "origin_volume_usd",
                        "pool_count": "origin_pool_count",
                    }
                ),
                on=["origin_date", "candidate_address"],
                how="inner",
                validate="one_to_one",
            )
            target = candidate_tvl.copy()
            target["origin_date"] = target["origin_date"] - pd.Timedelta(
                days=int(horizon)
            )
            joined = origin.merge(
                target.rename(
                    columns={
                        "tvl_usd": "target_tvl_usd",
                        "volume_usd": "target_volume_usd",
                        "pool_count": "target_pool_count",
                    }
                ),
                on=["origin_date", "candidate_address"],
                how="inner",
                validate="one_to_one",
            )
            if joined.empty:
                continue
            joined["protocol"] = protocol
            joined["horizon_days"] = int(horizon)
            joined["future_delta_log1p_tvl"] = np.log1p(
                joined["target_tvl_usd"].astype(float)
            ) - np.log1p(joined["origin_tvl_usd"].astype(float))
            joined["future_delta_log1p_pool_count"] = np.log1p(
                joined["target_pool_count"].astype(float)
            ) - np.log1p(joined["origin_pool_count"].astype(float))
            joined["origin_log1p_tvl"] = np.log1p(
                joined["origin_tvl_usd"].astype(float)
            )
            joined["origin_log1p_pool_count"] = np.log1p(
                joined["origin_pool_count"].astype(float)
            )
            horizon_rows.append(joined)
    if not horizon_rows:
        raise ValueError(f"{protocol} TVL horizon panel is empty")
    return pd.concat(horizon_rows, ignore_index=True, sort=False)


def load_design_panel(
    *,
    v3_path: Path = V3_POOL_DAY_INPUT,
    v4_path: Path = V4_TVL_INPUT,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return stacked V3/V4 TVL contrast panel and daily inputs."""

    share_gap = load_share_gap_panel()
    share_gap["origin_date"] = pd.to_datetime(share_gap["origin_date"]).dt.normalize()
    _normalise_address(share_gap, "candidate_address")
    active = load_v4_active_origins()
    active["origin_date"] = pd.to_datetime(active["origin_date"]).dt.normalize()
    _normalise_address(active, "candidate_address")
    share_gap = share_gap.merge(
        active[["origin_date", "candidate_address"]].drop_duplicates(),
        on=["origin_date", "candidate_address"],
        how="inner",
        validate="many_to_one",
    )
    v3_daily = build_v3_candidate_linked_tvl(
        pd.read_parquet(v3_path),
        candidates=vehicle_candidate_map(),
    )
    v4_daily = load_v4_candidate_linked_tvl(v4_path)
    panels = [
        protocol_horizon_panel(share_gap, v3_daily, protocol="v3"),
        protocol_horizon_panel(share_gap, v4_daily, protocol="v4"),
    ]
    stacked = pd.concat(panels, ignore_index=True, sort=False)
    stacked["is_v4"] = stacked["protocol"].eq("v4").astype(float)
    stacked["stable_gap"] = stacked["route_capital_gap_5"].where(
        stacked["is_stable"].astype(bool),
        0.0,
    )
    stacked["v4_x_stable_gap"] = stacked["is_v4"] * stacked["stable_gap"]
    stacked["candidate_date"] = (
        stacked["candidate_address"].astype(str)
        + "|"
        + pd.to_datetime(stacked["origin_date"]).dt.strftime("%Y%m%d")
    )
    return stacked, v3_daily, v4_daily


def fit_protocol_contrast(panel: pd.DataFrame) -> pd.DataFrame:
    """Estimate V4-minus-V3 TVL/footprint protocol contrasts."""

    rows: list[dict[str, object]] = []
    for horizon in HORIZONS:
        horizon_panel = panel[panel["horizon_days"].eq(horizon)].copy()
        for outcome in OUTCOMES:
            columns = [outcome, "v4_x_stable_gap", *CONTROLS]
            data = horizon_panel[
                [
                    "origin_date",
                    "candidate_date",
                    "protocol",
                    *columns,
                ]
            ].replace([np.inf, -np.inf], np.nan).dropna()
            protocol_counts = data.groupby("candidate_date")["protocol"].nunique()
            supported_candidate_dates = protocol_counts[protocol_counts.eq(2)].index
            data = data[data["candidate_date"].isin(supported_candidate_dates)]
            if data.empty:
                continue
            residual = absorb_fixed_effects(
                data[columns],
                data["candidate_date"],
                data["protocol"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[["v4_x_stable_gap", *CONTROLS]],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_date"], data["protocol"]),
                min_observations=100,
                min_clusters=30,
            )
            rows.append(
                {
                    "record_type": "v3_v4_tvl_protocol_contrast",
                    "analysis_status": "exploratory_protocol_contrast",
                    "horizon_days": int(horizon),
                    "outcome": outcome,
                    "term": "v4_x_stable_gap",
                    "effect_per_10pp_stable_gap_v4_minus_v3": float(0.1 * fit.beta[0]),
                    "standard_error_per_10pp_stable_gap_v4_minus_v3": float(
                        0.1 * fit.standard_errors[0]
                    ),
                    "t_statistic": float(fit.t_statistics[0]),
                    "p_value": float(fit.p_values[0]),
                    "n_observations": int(fit.n_observations),
                    "date_clusters": int(fit.n_clusters),
                    "fixed_effects": "candidate-date+protocol",
                    "controls": "+".join(CONTROLS),
                    "quantity": "candidate-linked reported pool TVL and pool count",
                    "interpretation": (
                        "V4-minus-V3 difference in the association between a "
                        "stable route-minus-capital gap and future reported "
                        "TVL or pool-footprint growth; not reconstructed "
                        "deposited capital or a causal protocol-adoption effect"
                    ),
                }
            )
    if not rows:
        raise ValueError("no V3/V4 TVL protocol contrasts were estimated")
    return pd.DataFrame(rows)


def support_record(
    *,
    panel: pd.DataFrame,
    v3_daily: pd.DataFrame,
    v4_daily: pd.DataFrame,
    results: pd.DataFrame,
) -> dict[str, object]:
    return {
        "record_type": "v3_v4_tvl_protocol_contrast_support",
        "analysis_status": "exploratory_protocol_contrast",
        "stacked_rows": int(len(panel)),
        "result_rows": int(len(results)),
        "v3_candidate_days": int(v3_daily[["origin_date", "candidate_address"]].drop_duplicates().shape[0]),
        "v4_candidate_days": int(v4_daily[["origin_date", "candidate_address"]].drop_duplicates().shape[0]),
        "candidate_count": int(panel["candidate_address"].nunique()),
        "first_origin_date": panel["origin_date"].min().strftime("%Y-%m-%d"),
        "last_origin_date": panel["origin_date"].max().strftime("%Y-%m-%d"),
        "horizons": ",".join(str(value) for value in HORIZONS),
        "outcomes": "+".join(OUTCOMES),
        "fixed_effects": "candidate-date+protocol",
        "controls": "+".join(CONTROLS),
        "cluster": "origin_date",
        "quantity_boundary": (
            "candidate-linked reported full-pool TVL; candidate-candidate pools "
            "can link to both candidate series; not side-specific LP inventory"
        ),
    }


def run(
    *,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    v3_path: Path = V3_POOL_DAY_INPUT,
    v4_path: Path = V4_TVL_INPUT,
) -> int:
    panel, v3_daily, v4_daily = load_design_panel(v3_path=v3_path, v4_path=v4_path)
    results = fit_protocol_contrast(panel)
    support = pd.DataFrame(
        [support_record(panel=panel, v3_daily=v3_daily, v4_daily=v4_daily, results=results)]
    )
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    display_output = result_output.resolve()
    try:
        display_output = display_output.relative_to(REPO_ROOT)
    except ValueError:
        pass
    print(f"wrote {len(results):,} V3/V4 TVL protocol-contrast rows to {display_output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--v3", type=Path, default=V3_POOL_DAY_INPUT)
    parser.add_argument("--v4", type=Path, default=V4_TVL_INPUT)
    args = parser.parse_args()
    return run(
        result_output=args.result_output,
        support_output=args.support_output,
        v3_path=args.v3,
        v4_path=args.v4,
    )


if __name__ == "__main__":
    raise SystemExit(main())

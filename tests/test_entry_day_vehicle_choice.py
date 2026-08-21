from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ddvc.pricing.tick_replay import initialization_root
from scripts.analyze.run_contestable_vehicle_choice import DAI
from scripts.analyze.run_entry_day_vehicle_choice import (
    _fit_entry_model,
    load_material_entries,
    regression_results,
)


def _support_row(
    date: str,
    src: str,
    tgt: str,
    *,
    primary: int,
    native: int,
    stable: int,
    coherent_value: float,
) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "primary_choice_route_count": primary,
        "native_choice_route_count": native,
        "stable_choice_route_count": stable,
        "native_within_20pct_routes": native,
        "stable_within_20pct_routes": stable,
        "native_within_20pct_value_usd": coherent_value * native / primary,
        "stable_within_20pct_value_usd": coherent_value * stable / primary,
    }


def test_material_entries_use_first_primary_day_and_exclude_vehicle_endpoints(
    tmp_path,
) -> None:
    frame = pd.DataFrame(
        [
            _support_row(
                "2024-01-01",
                "src-a",
                "tgt-a",
                primary=2,
                native=2,
                stable=0,
                coherent_value=120_000.0,
            ),
            _support_row(
                "2024-01-02",
                "src-a",
                "tgt-a",
                primary=5,
                native=0,
                stable=5,
                coherent_value=500_000.0,
            ),
            _support_row(
                "2024-01-01",
                "src-b",
                "tgt-b",
                primary=1,
                native=1,
                stable=0,
                coherent_value=99_999.0,
            ),
            _support_row(
                "2024-01-01",
                DAI,
                "tgt-c",
                primary=2,
                native=0,
                stable=2,
                coherent_value=200_000.0,
            ),
        ]
    )
    path = tmp_path / "pair_support.parquet"
    frame.to_parquet(path, index=False)

    entries = load_material_entries(
        path,
        minimum_entry_value_usd=100_000.0,
        start="20240101",
        end="20241231",
    )

    assert len(entries) == 1
    row = entries.iloc[0]
    assert row["day"] == "20240101"
    assert row["ordered_pair"] == "src-a>tgt-a"
    assert row["entry_stable_share"] == 0.0
    assert row["entry_stable"] == 0.0
    assert bool(row["entry_exclusive"])
    assert not bool(row["entry_mixed"])
    assert row["entry_coherent_value_usd"] == pytest.approx(120_000.0)


def test_tick_initializations_follow_the_selected_raw_root(tmp_path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"

    assert initialization_root(raw_root) == (
        tmp_path / "raw" / "ethereum" / "tick_initializations" / "daily"
    )


def _synthetic_panel() -> pd.DataFrame:
    rng = np.random.default_rng(20260821)
    rows: list[dict[str, object]] = []
    pair_index = 0
    for date_index in range(30):
        day = (pd.Timestamp("2023-01-01") + pd.Timedelta(days=date_index)).strftime(
            "%Y%m%d"
        )
        for local_pair in range(6):
            pair_index += 1
            token_in = f"source-{(date_index + local_pair) % 12}"
            token_out = f"destination-{(2 * date_index + local_pair) % 13}"
            ordered_pair = f"{token_in}>{token_out}>{pair_index}"
            pair_shift = rng.normal(scale=0.15)
            for route_index in range(4):
                price = rng.normal()
                capital = rng.normal()
                noise = rng.normal(scale=0.45)
                latent = 0.35 * price + 0.20 * capital + pair_shift + noise
                rows.append(
                    {
                        "chosen_stable": float(latent > 0),
                        "stable_output_advantage_100bp": price,
                        "stable_v2_capital_share_10pp": capital,
                        "log_input_usd": np.log(1_000.0 + 100.0 * route_index),
                        "ordered_pair": ordered_pair,
                        "day": day,
                        "token_in": token_in,
                        "token_out": token_out,
                        "route_scope": (
                            "uniswap_v2>uniswap_v2"
                            if route_index % 2 == 0
                            else "uniswap_v3>uniswap_v2"
                        ),
                        "both_v2_bridge_capitals_positive": route_index != 0,
                        "entry_coherent_value_usd": 100_000.0,
                    }
                )
    return pd.DataFrame(rows)


def test_entry_model_absorbs_declared_controls_and_clusters_pair_date() -> None:
    panel = _synthetic_panel()
    result = _fit_entry_model(
        panel,
        model_id="joint",
        predictors=(
            "stable_output_advantage_100bp",
            "stable_v2_capital_share_10pp",
        ),
        sample="synthetic",
    )

    key = result.set_index("regressor")
    assert key.loc["stable_output_advantage_100bp", "coefficient"] > 0
    assert key.loc["stable_v2_capital_share_10pp", "coefficient"] > 0
    assert (result["fixed_effects"] == (
        "calendar_date+source_token+destination_token+observed_route_scope"
    )).all()
    assert (result["covariance"] == "two_way_ordered_pair_calendar_date_cr1").all()
    assert (result["ordered_pair_clusters"] == panel["ordered_pair"].nunique()).all()
    assert (result["date_clusters"] == panel["day"].nunique()).all()


def test_regression_ladder_uses_one_capital_complete_sample() -> None:
    panel = _synthetic_panel()
    result = regression_results(panel)
    common = result[result["model_id"].str.startswith("m")]
    observations = common.groupby("model_id")["observations"].first()

    assert observations.nunique() == 1
    assert set(observations.index) == {
        "m1_price_only_common_capital_sample",
        "m2_capital_only_common_sample",
        "m3_price_and_capital_common_sample",
    }
    broad = result[result["model_id"].eq("price_only_all_exact_contestable")]
    assert broad["observations"].iloc[0] > observations.iloc[0]

from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_vehicle_formation_exploration import (
    entry_driver_panel,
    entry_follow_panel,
    entry_regime_hysteresis,
    entry_route_architecture_regressions,
    entry_stable_candidate_persistence,
    entry_stable_candidate_summary,
    endpoint_class,
    persistence_contrasts,
    persistence_summary,
)


def _row(
    date: str,
    src: str,
    tgt: str,
    *,
    entry: bool,
    stable: int,
    native: int,
) -> dict[str, object]:
    primary = stable + native
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "market_route_count": primary,
        "primary_choice_route_count": primary,
        "stable_choice_route_count": stable,
        "native_choice_route_count": native,
        "direct_route_count": 0,
        "multiple_intermediary_route_count": 0,
        "split_or_join_route_count": 0,
        "nonsequential_two_leg_route_count": 0,
        "pair_entry_on_day": entry,
    }


@pytest.fixture
def pair_support_path(tmp_path):
    frame = pd.DataFrame(
        [
            _row("2026-01-01", "a", "b", entry=True, stable=0, native=10),
            _row("2026-01-15", "a", "b", entry=False, stable=0, native=5),
            _row("2026-01-31", "a", "b", entry=False, stable=0, native=5),
            _row("2026-01-01", "c", "d", entry=True, stable=8, native=2),
            _row("2026-01-15", "c", "d", entry=False, stable=7, native=3),
            _row("2026-01-31", "c", "d", entry=False, stable=7, native=3),
            _row("2026-06-20", "e", "f", entry=True, stable=10, native=0),
            _row("2024-01-01", "g", "h", entry=True, stable=0, native=10),
        ]
    )
    path = tmp_path / "pair_support.parquet"
    frame.to_parquet(path, index=False)
    return path


@pytest.fixture
def candidate_choices_path(tmp_path):
    frame = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-01-01"),
                "src": "c",
                "tgt": "d",
                "candidate_symbol": "USDC",
                "candidate_type": "stable",
                "route_count": 8,
                "within_20pct_routes": 7,
                "within_20pct_value_usd": 70.0,
            },
            {
                "date": pd.Timestamp("2026-01-01"),
                "src": "c",
                "tgt": "d",
                "candidate_symbol": "USDT",
                "candidate_type": "stable",
                "route_count": 2,
                "within_20pct_routes": 2,
                "within_20pct_value_usd": 20.0,
            },
            {
                "date": pd.Timestamp("2026-01-15"),
                "src": "c",
                "tgt": "d",
                "candidate_symbol": "USDC",
                "candidate_type": "stable",
                "route_count": 6,
                "within_20pct_routes": 6,
                "within_20pct_value_usd": 60.0,
            },
            {
                "date": pd.Timestamp("2026-01-15"),
                "src": "c",
                "tgt": "d",
                "candidate_symbol": "USDT",
                "candidate_type": "stable",
                "route_count": 1,
                "within_20pct_routes": 1,
                "within_20pct_value_usd": 10.0,
            },
            {
                "date": pd.Timestamp("2026-01-01"),
                "src": "a",
                "tgt": "b",
                "candidate_symbol": "WETH",
                "candidate_type": "native",
                "route_count": 10,
                "within_20pct_routes": 10,
                "within_20pct_value_usd": 100.0,
            },
            {
                "date": pd.Timestamp("2024-01-01"),
                "src": "g",
                "tgt": "h",
                "candidate_symbol": "USDT",
                "candidate_type": "stable",
                "route_count": 1,
                "within_20pct_routes": 1,
                "within_20pct_value_usd": 10.0,
            },
        ]
    )
    path = tmp_path / "candidate_choices.parquet"
    frame.to_parquet(path, index=False)
    return path


def test_entry_stable_candidate_summary_splits_stable_entry_routes(
    pair_support_path, candidate_choices_path
) -> None:
    summary = entry_stable_candidate_summary(pair_support_path, candidate_choices_path)
    usdc = summary[
        summary["entry_year"].eq(2026) & summary["candidate_symbol"].eq("USDC")
    ].iloc[0]
    assert usdc["candidate_routes"] == 8
    assert usdc["stable_entry_routes"] == 10
    assert usdc["stable_entry_route_share"] == pytest.approx(0.8)


def test_entry_stable_candidate_persistence_tracks_entry_candidate_identity(
    pair_support_path, candidate_choices_path
) -> None:
    summary = entry_stable_candidate_persistence(
        30,
        pair_support_path=pair_support_path,
        candidate_choices_path=candidate_choices_path,
        sample_end=pd.Timestamp("2026-06-30"),
    )
    usdc = summary[
        summary["entry_year"].eq(2026)
        & summary["entry_candidate_symbol"].eq("USDC")
    ].iloc[0]
    assert usdc["stable_followup_routes"] == 17
    assert usdc["own_candidate_followup_routes"] == 14
    assert usdc["own_candidate_followup_share"] == pytest.approx(14 / 17)


def test_entry_follow_panel_requires_complete_horizon(pair_support_path) -> None:
    follow = entry_follow_panel(
        30,
        pair_support_path=pair_support_path,
        sample_end=pd.Timestamp("2026-06-30"),
    )
    assert set(follow["src"]) == {"a", "c", "g"}
    assert follow["horizon_days"].eq(30).all()


def test_persistence_summary_separates_native_and_stable_births(pair_support_path) -> None:
    follow = entry_follow_panel(
        30,
        pair_support_path=pair_support_path,
        sample_end=pd.Timestamp("2026-06-30"),
    )
    summary = persistence_summary(follow)
    native = summary[summary["entry_type"].eq("native_only_entry")].iloc[0]
    stable = summary[summary["entry_type"].eq("stable_dominant_entry")].iloc[0]
    assert native["stable_share"] == pytest.approx(0.0)
    assert stable["stable_share"] == pytest.approx(22 / 30)


def test_persistence_contrast_uses_pair_level_followup(pair_support_path) -> None:
    follow = entry_follow_panel(
        30,
        pair_support_path=pair_support_path,
        sample_end=pd.Timestamp("2026-06-30"),
    )
    contrast = persistence_contrasts(follow)
    row = contrast.iloc[0]
    assert row["coefficient"] == pytest.approx(22 / 30)
    assert row["comparison"] == "stable_dominant_entry_minus_native_only_entry"


def test_entry_regime_hysteresis_counts_only_active_days(pair_support_path) -> None:
    summary = entry_regime_hysteresis(
        30,
        pair_support_path=pair_support_path,
        sample_end=pd.Timestamp("2026-06-30"),
    )
    stable = summary[
        summary["entry_year"].eq(2026)
        & summary["entry_type"].eq("stable_dominant_entry")
    ].iloc[0]
    assert stable["pairs"] == 1
    assert stable["pairs_trading_again"] == 1
    assert stable["never_left_share_retrade"] == pytest.approx(1.0)
    assert stable["mean_stable_majority_day_share"] == pytest.approx(1.0)


def test_endpoint_class_separates_weth_from_other_stable_endpoints() -> None:
    assert (
        endpoint_class(
            "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        )
        == "weth_endpoint"
    )
    assert (
        endpoint_class(
            "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "0x1111111111111111111111111111111111111111",
        )
        == "stable_endpoint"
    )


def test_entry_driver_panel_adds_comparison_year_flag(pair_support_path) -> None:
    panel = entry_driver_panel(pair_support_path)
    assert set(panel["entry_year"]) == {2024, 2026}
    assert "is_2026" in panel
    assert "is_2026_x_direct_share" in panel
    assert "is_2026_x_complex_share" in panel
    assert panel.loc[panel["entry_year"].eq(2026), "is_2026"].eq(1.0).all()


def test_entry_route_architecture_regressions_publish_interactions() -> None:
    rows = []
    for day in range(1, 7):
        for is_2026 in (0.0, 1.0):
            for direct_share in (0.0, 0.5):
                for complex_share in (0.0, 0.4):
                    stable_endpoint = float(direct_share > 0)
                    stable_share = (
                        0.02
                        + 0.03 * is_2026
                        + 0.02 * stable_endpoint
                        + 0.20 * complex_share
                        + 0.15 * is_2026 * direct_share
                    )
                    rows.append(
                        {
                            "date": pd.Timestamp(
                                f"{2024 + int(2 * is_2026)}-01-{day:02d}"
                            ),
                            "primary_routes": 10.0,
                            "stable_share": stable_share,
                            "stable_dominant_entry": float(stable_share > 0.05),
                            "is_2026": is_2026,
                            "stable_endpoint": stable_endpoint,
                            "is_2026_x_stable_endpoint": is_2026 * stable_endpoint,
                            "log_entry_routes": 1.0 + direct_share + complex_share,
                            "direct_share": direct_share,
                            "complex_share": complex_share,
                            "is_2026_x_direct_share": is_2026 * direct_share,
                            "is_2026_x_complex_share": is_2026 * complex_share,
                        }
                    )
    result = entry_route_architecture_regressions(
        pd.DataFrame(rows), min_observations=10, min_clusters=2
    )
    assert {
        "is_2026_x_direct_share",
        "is_2026_x_complex_share",
    }.issubset(set(result["predictor"]))
    assert result["record_type"].eq("entry_route_architecture_regression").all()

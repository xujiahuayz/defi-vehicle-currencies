from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_vehicle_formation_exploration import (
    endpoint_claim_class,
    endpoint_claim_class_summaries,
    entry_driver_panel,
    entry_endpoint_history_panel,
    entry_endpoint_history_regressions,
    entry_endpoint_history_summaries,
    entry_follow_panel,
    entry_path_dependence_regressions,
    entry_regime_hysteresis,
    entry_route_architecture_regressions,
    entry_secure_volume_regressions,
    entry_secure_volume_summary,
    entry_stable_candidate_persistence,
    entry_stable_candidate_summary,
    entry_value_follow_panel,
    entry_value_path_dependence_regressions,
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


def test_entry_value_follow_panel_uses_within_band_value_support(
    pair_support_path, candidate_choices_path
) -> None:
    follow = entry_value_follow_panel(
        30,
        pair_support_path=pair_support_path,
        candidate_choices_path=candidate_choices_path,
        sample_end=pd.Timestamp("2026-06-30"),
    )
    assert set(follow["src"]) == {"a", "c", "g"}
    stable = follow[follow["src"].eq("c")].iloc[0]
    native = follow[follow["src"].eq("a")].iloc[0]
    assert stable["entry_stable_value_share"] == pytest.approx(1.0)
    assert stable["stable_value_share"] == pytest.approx(1.0)
    assert stable["primary_value"] == pytest.approx(160.0)
    assert native["entry_stable_value_share"] == pytest.approx(0.0)
    assert native["stable_value_share"] == pytest.approx(0.0)


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


def test_endpoint_claim_class_summaries_split_entry_and_active_routes(tmp_path) -> None:
    stable = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    imported = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
    staked = "0xae78736cd615f374d3085123a210448e74fc6393"
    other = "0x1111111111111111111111111111111111111111"
    frame = pd.DataFrame(
        [
            _row("2024-01-01", stable, other, entry=True, stable=1, native=9),
            _row("2026-01-01", imported, other, entry=True, stable=3, native=7),
            _row("2026-01-02", imported, other, entry=False, stable=5, native=5),
            _row("2026-01-03", staked, other, entry=True, stable=4, native=6),
            _row("2026-01-04", weth, imported, entry=True, stable=10, native=0),
        ]
    )
    path = tmp_path / "claim_classes.parquet"
    frame.to_parquet(path, index=False)

    summary = endpoint_claim_class_summaries(path)
    imported_entry = summary[
        summary["sample_scope"].eq("entry_pair_days")
        & summary["year"].eq(2026)
        & summary["endpoint_claim_class"].eq("imported_endpoint")
    ].iloc[0]
    imported_active = summary[
        summary["sample_scope"].eq("active_pair_days")
        & summary["year"].eq(2026)
        & summary["endpoint_claim_class"].eq("imported_endpoint")
    ].iloc[0]

    assert endpoint_claim_class(weth, stable) == "weth_endpoint"
    assert endpoint_claim_class(imported, staked) == "imported_endpoint"
    assert imported_entry["stable_share"] == pytest.approx(0.3)
    assert imported_active["stable_share"] == pytest.approx(8 / 20)
    assert imported_active["pair_days"] == 2


def test_entry_secure_volume_summary_excludes_weth_and_reports_gap_change(tmp_path) -> None:
    stable = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    other = "0x1111111111111111111111111111111111111111"
    frame = pd.DataFrame(
        [
            _row("2024-01-01", stable, other, entry=True, stable=2, native=8),
            _row("2024-01-02", other, other[::-1], entry=True, stable=0, native=10),
            _row("2026-01-01", stable, other[::-1], entry=True, stable=6, native=4),
            _row("2026-01-02", other, other, entry=True, stable=1, native=9),
            _row("2026-01-03", weth, other, entry=True, stable=10, native=0),
        ]
    )
    path = tmp_path / "secure_volume.parquet"
    frame.to_parquet(path, index=False)

    summary = entry_secure_volume_summary(path)
    stable_2026 = summary[
        summary["record_type"].eq("entry_secure_volume_class")
        & summary["entry_year"].eq(2026)
        & summary["secure_volume_class"].eq("stable_endpoint")
    ].iloc[0]
    change = summary[summary["record_type"].eq("entry_secure_volume_gap_change")].iloc[0]

    assert stable_2026["stable_share"] == pytest.approx(0.6)
    assert stable_2026["route_mass_share"] == pytest.approx(0.5)
    assert change["gap_change"] == pytest.approx(0.3)


def test_entry_driver_panel_adds_comparison_year_flag(pair_support_path) -> None:
    panel = entry_driver_panel(pair_support_path)
    assert set(panel["entry_year"]) == {2024, 2026}
    assert "is_2026" in panel
    assert "is_2026_x_direct_share" in panel
    assert "is_2026_x_complex_share" in panel
    assert panel.loc[panel["entry_year"].eq(2026), "is_2026"].eq(1.0).all()


def test_entry_path_dependence_regressions_publish_entry_state_driver() -> None:
    follow_rows = []
    driver_rows = []
    for day in range(1, 61):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day - 1)
        entry_shares = (
            0.01 * (day % 4),
            0.20 + 0.02 * (day % 5),
            0.62 + 0.03 * (day % 6),
        )
        for index, entry_share in enumerate(entry_shares):
            src = f"src-{day}-{index}"
            tgt = f"tgt-{day}-{index}"
            dominant = float(entry_share > 0.5)
            stable_endpoint = float(index == 1)
            direct_share = 0.05 * ((day + index) % 5)
            complex_share = 0.04 * ((day + 2 * index) % 6)
            is_2026 = float(day % 2 == 0)
            follow_share = (
                0.02
                + 0.70 * entry_share
                + 0.08 * dominant
                + 0.01 * is_2026
                + 0.02 * direct_share
                - 0.01 * complex_share
            )
            follow_rows.append(
                {
                    "horizon_days": 120,
                    "entry_date": date,
                    "src": src,
                    "tgt": tgt,
                    "entry_primary_routes": 10.0 + day,
                    "entry_stable_share": entry_share,
                    "entry_type": (
                        "stable_dominant_entry"
                        if dominant
                        else (
                            "stable_present_entry"
                            if entry_share > 0
                            else "native_only_entry"
                        )
                    ),
                    "stable_share": follow_share,
                    "stable_dominant_followup": float(follow_share > 0.5),
                }
            )
            driver_rows.append(
                {
                    "date": date,
                    "src": src,
                    "tgt": tgt,
                    "stable_endpoint": stable_endpoint,
                    "is_2026": is_2026,
                    "log_entry_routes": np.log1p(10.0 + day),
                    "direct_share": direct_share,
                    "complex_share": complex_share,
                }
            )
    result = entry_path_dependence_regressions(
        pd.DataFrame(follow_rows),
        pd.DataFrame(driver_rows),
        min_observations=100,
        min_clusters=20,
    )
    share_driver = result[
        result["outcome"].eq("stable_share")
        & result["predictor"].eq("entry_stable_share")
    ].iloc[0]
    dominant_driver = result[
        result["outcome"].eq("stable_dominant_followup")
        & result["predictor"].eq("entry_stable_dominant")
    ].iloc[0]

    assert result["record_type"].eq("entry_path_dependence_regression").all()
    assert share_driver["coefficient"] > 0.6
    assert dominant_driver["coefficient"] > 0
    assert np.isfinite(share_driver["standard_error"])


def test_entry_value_path_dependence_regressions_publish_value_driver() -> None:
    follow_rows = []
    driver_rows = []
    for day in range(1, 61):
        date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day - 1)
        entry_value_shares = (
            0.02 * (day % 4),
            0.25 + 0.02 * (day % 5),
            0.64 + 0.03 * (day % 6),
        )
        for index, entry_share in enumerate(entry_value_shares):
            src = f"value-src-{day}-{index}"
            tgt = f"value-tgt-{day}-{index}"
            dominant = float(entry_share > 0.5)
            stable_endpoint = float(index == 1)
            direct_share = 0.04 * ((day + index) % 5)
            complex_share = 0.03 * ((day + 2 * index) % 6)
            is_2026 = float(day % 2 == 0)
            follow_share = (
                0.03
                + 0.75 * entry_share
                + 0.04 * dominant
                + 0.01 * is_2026
                + 0.02 * direct_share
                - 0.01 * complex_share
            )
            follow_rows.append(
                {
                    "horizon_days": 120,
                    "entry_date": date,
                    "src": src,
                    "tgt": tgt,
                    "entry_primary_value": 1000.0 + day,
                    "entry_stable_value_share": entry_share,
                    "entry_stable_value_dominant": dominant,
                    "stable_value_share": follow_share,
                    "stable_value_dominant_followup": float(follow_share > 0.5),
                }
            )
            driver_rows.append(
                {
                    "date": date,
                    "src": src,
                    "tgt": tgt,
                    "stable_endpoint": stable_endpoint,
                    "is_2026": is_2026,
                    "log_entry_routes": np.log1p(10.0 + day),
                    "direct_share": direct_share,
                    "complex_share": complex_share,
                }
            )
    result = entry_value_path_dependence_regressions(
        pd.DataFrame(follow_rows),
        pd.DataFrame(driver_rows),
        min_observations=100,
        min_clusters=20,
    )
    share_driver = result[
        result["outcome"].eq("stable_value_share")
        & result["predictor"].eq("entry_stable_value_share")
    ].iloc[0]

    assert result["record_type"].eq("entry_value_path_dependence_regression").all()
    assert share_driver["coefficient"] > 0.7
    assert share_driver["weighted_by"] == "entry_primary_within_20pct_value_usd"
    assert np.isfinite(share_driver["standard_error"])


def test_entry_endpoint_history_panel_flags_missing_endpoint_price_history(
    tmp_path,
) -> None:
    old = "0x0000000000000000000000000000000000000001"
    old_peer = "0x0000000000000000000000000000000000000002"
    new = "0x0000000000000000000000000000000000000003"
    panel = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-02-01"),
                "src": old,
                "tgt": old_peer,
                "entry_year": 2026,
                "endpoint_class": "other_endpoint",
                "primary_routes": 10.0,
                "stable_routes": 2.0,
                "native_routes": 8.0,
                "stable_share": 0.2,
                "stable_dominant_entry": 0.0,
                "is_2026": 1.0,
                "log_entry_routes": 1.0,
                "direct_share": 0.0,
                "complex_share": 0.0,
                "is_2026_x_direct_share": 0.0,
                "is_2026_x_complex_share": 0.0,
            },
            {
                "date": pd.Timestamp("2026-02-01"),
                "src": new,
                "tgt": old_peer,
                "entry_year": 2026,
                "endpoint_class": "other_endpoint",
                "primary_routes": 20.0,
                "stable_routes": 10.0,
                "native_routes": 10.0,
                "stable_share": 0.5,
                "stable_dominant_entry": 1.0,
                "is_2026": 1.0,
                "log_entry_routes": 1.0,
                "direct_share": 0.0,
                "complex_share": 0.0,
                "is_2026_x_direct_share": 0.0,
                "is_2026_x_complex_share": 0.0,
            },
        ]
    )
    price_path = tmp_path / "token_price_daily.parquet"
    pd.DataFrame(
        [
            {
                "day": "20260115",
                "token": old,
                "price_usd": 1.0,
                "n_observations": 3.0,
                "validation_status": "minimum_observations_and_price_consensus_passed",
            },
            {
                "day": "20260115",
                "token": old_peer,
                "price_usd": 2.0,
                "n_observations": 4.0,
                "validation_status": "minimum_observations_and_price_consensus_passed",
            },
        ]
    ).to_parquet(price_path, index=False)

    enriched = entry_endpoint_history_panel(panel, token_price_path=price_path)
    summary = entry_endpoint_history_summaries(enriched)
    no_history = summary[summary["no_prior_price_history_30"].eq(True)].iloc[0]
    with_history = summary[summary["no_prior_price_history_30"].eq(False)].iloc[0]

    assert enriched.loc[enriched["src"].eq(old), "no_prior_price_history_30"].iloc[
        0
    ] == pytest.approx(0.0)
    assert enriched.loc[enriched["src"].eq(new), "no_prior_price_history_30"].iloc[
        0
    ] == pytest.approx(1.0)
    assert no_history["stable_share"] == pytest.approx(0.5)
    assert with_history["mean_min_prior_price_days_30"] == pytest.approx(1.0)


def test_entry_endpoint_history_regressions_publish_missing_history_driver() -> None:
    rows = []
    for day in range(1, 17):
        for is_2026 in (0.0, 1.0):
            for no_history in (0.0, 1.0):
                for direct_share in (0.0, 0.35):
                    for complex_share in (0.0, 0.25):
                        log_obs = (
                            0.2 * day
                            if no_history
                            else 1.0 + 0.1 * day + direct_share
                        )
                        price_sd = (
                            0.005 * day
                            if no_history
                            else 0.01 * day + 0.02 * complex_share
                        )
                        stable_share = (
                            0.01
                            + 0.03 * is_2026
                            + 0.04 * no_history
                            + 0.02 * direct_share
                            + 0.03 * complex_share
                            + 0.01 * log_obs
                            - 0.01 * price_sd
                        )
                        rows.append(
                            {
                                "date": pd.Timestamp(
                                    f"{2024 + int(2 * is_2026)}-01-{day:02d}"
                                ),
                                "endpoint_class": "other_endpoint",
                                "primary_routes": 10.0 + day,
                                "stable_share": stable_share,
                                "stable_dominant_entry": float(stable_share > 0.06),
                                "is_2026": is_2026,
                                "log_entry_routes": np.log1p(
                                    10.0 + day + direct_share + complex_share
                                ),
                                "direct_share": direct_share,
                                "complex_share": complex_share,
                                "is_2026_x_direct_share": is_2026 * direct_share,
                                "is_2026_x_complex_share": is_2026 * complex_share,
                                "no_prior_price_history_30": no_history,
                                "log_min_prior_price_obs_30": log_obs,
                                "endpoint_log_price_sd_30": price_sd,
                            }
                        )
    result = entry_endpoint_history_regressions(
        pd.DataFrame(rows), min_observations=50, min_clusters=4
    )
    driver = result[
        result["outcome"].eq("stable_share")
        & result["predictor"].eq("no_prior_price_history_30")
    ].iloc[0]

    assert result["record_type"].eq("entry_endpoint_history_regression").all()
    assert driver["coefficient"] > 0
    assert np.isfinite(driver["standard_error"])


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


def test_entry_secure_volume_regressions_publish_conditional_driver() -> None:
    rows = []
    for day in range(1, 8):
        for is_2026 in (0.0, 1.0):
            for stable_endpoint in (0.0, 1.0):
                for direct_share in (0.0, 0.5):
                    for complex_share in (0.0, 0.3):
                        stable_share = (
                            0.01
                            + 0.04 * is_2026
                            + 0.02 * stable_endpoint
                            + 0.04 * is_2026 * stable_endpoint
                            + 0.12 * complex_share
                            + 0.10 * is_2026 * direct_share
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
                                "is_2026_x_stable_endpoint": (
                                    is_2026 * stable_endpoint
                                ),
                                "log_entry_routes": 1.0 + 0.01 * day,
                                "direct_share": direct_share,
                                "complex_share": complex_share,
                                "is_2026_x_direct_share": is_2026 * direct_share,
                                "is_2026_x_complex_share": is_2026 * complex_share,
                            }
                        )
    result = entry_secure_volume_regressions(
        pd.DataFrame(rows), min_observations=10, min_clusters=2
    )
    driver = result[
        result["outcome"].eq("stable_share")
        & result["predictor"].eq("is_2026_x_stable_endpoint")
    ].iloc[0]
    assert result["record_type"].eq("entry_secure_volume_regression").all()
    assert driver["coefficient"] > 0

from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.analyze.run_v3_v4_internal_routing_participation import (
    CONTROLS,
    build_protocol_timing_panel,
    fit_protocol_comparison,
    fit_protocol_volatility_comparison,
    load_processed_origin_actions,
)


ADDRESS = "0x0000000000000000000000000000000000000001"


def test_processed_origin_actions_reconstructs_protocol_daily_counts(tmp_path) -> None:
    path = tmp_path / "origins.parquet"
    pd.DataFrame(
        [
            {
                "protocol": "v3",
                "candidate_address": ADDRESS,
                "candidate_symbol": "AAA",
                "origin_date": "2025-01-01",
                "origin": "0xaaa",
                "action_count": 2,
            },
            {
                "protocol": "v4",
                "candidate_address": ADDRESS,
                "candidate_symbol": "AAA",
                "origin_date": "2025-01-01",
                "origin": "0xbbb",
                "action_count": 3,
            },
        ]
    ).to_parquet(path, index=False)
    v3, v4, support = load_processed_origin_actions(path)
    day = pd.Timestamp("2025-01-01")
    assert v3[ADDRESS][day] == {"0xaaa": 2}
    assert v4[ADDRESS][day] == {"0xbbb": 3}
    assert support["v3"]["candidate_event_assignments"] == 2
    assert support["v4"]["candidate_event_assignments"] == 3


def test_protocol_timing_classifies_incumbent_and_late_entry() -> None:
    origin_date = pd.Timestamp("2025-07-01")
    routing = pd.DataFrame(
        [
            {
                "origin_date": origin_date,
                "candidate_address": ADDRESS,
                "candidate_symbol": "AAA",
                "candidate_tx_count": 10,
                "swap_leg_assignments": 14,
                "multi_leg_tx_share": 0.4,
                "internal_tx_share": 0.2,
            }
        ]
    )
    daily = {
        ADDRESS: {
            pd.Timestamp("2025-01-02"): {"old": 1},
            origin_date: {"old": 1},
            pd.Timestamp("2025-07-02"): {"old": 2, "early": 1},
            pd.Timestamp("2025-08-10"): {"old": 1, "early": 2, "late": 3},
            pd.Timestamp("2025-10-29"): {"late": 1},
        }
    }
    panel = build_protocol_timing_panel(
        daily, routing, protocol="v3", prior_days=180
    )
    row = panel.iloc[0]
    assert np.isclose(row["near_log1p_incumbent_actions"], np.log(3))
    assert np.isclose(row["late_log1p_first_active_origins"], np.log(2))
    assert np.isclose(row["log1p_current_actions"], np.log(2))
    assert np.isclose(row["log1p_prior_30d_actions"], np.log(2))


def test_protocol_comparison_recovers_positive_v4_slope_difference() -> None:
    rng = np.random.default_rng(4815)
    dates = pd.date_range("2025-01-01", periods=80, freq="D")
    rows = []
    for candidate_index, symbol in enumerate(("AAA", "BBB", "CCC")):
        for day_index, day in enumerate(dates):
            for protocol, is_v4 in (("v3", 0.0), ("v4", 1.0)):
                signal = (
                    0.05
                    + 0.008 * candidate_index
                    + 0.02 * rng.uniform()
                )
                row = {
                    "origin_date": day,
                    "candidate_date_id": f"{symbol}|{day.date()}",
                    "candidate_address": f"0x{candidate_index + 1:040x}",
                    "candidate_symbol": symbol,
                    "protocol": protocol,
                    "is_v4": is_v4,
                    "internal_tx_share": signal,
                }
                for control_index, control in enumerate(CONTROLS):
                    row[control] = (
                        0.1 * candidate_index
                        + 0.03 * control_index
                        + 0.02 * rng.normal()
                    )
                common = 0.002 * day_index**2 + 0.1 * candidate_index
                control_effect = sum(
                    (index + 1) * 0.02 * row[control]
                    for index, control in enumerate(CONTROLS)
                )
                row["near_log1p_incumbent_actions"] = (
                    common + control_effect + 1.5 * signal + 2.5 * is_v4 * signal
                )
                row["late_log1p_first_active_origins"] = (
                    common + control_effect + 0.5 * signal + 3.0 * is_v4 * signal
                )
                rows.append(row)
    result = fit_protocol_comparison(
        pd.DataFrame(rows),
        sample_variant="test",
        min_observations=200,
        min_clusters=30,
    )
    assert len(result) == 2
    assert result["v4_minus_v3_per_10pp"].gt(0).all()
    assert result["v4_minus_v3_holm_p_value"].between(0, 1).all()


def test_protocol_state_comparison_recovers_stronger_v4_state_slope() -> None:
    rng = np.random.default_rng(828)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    rows = []
    volatility = []
    for day_index, day in enumerate(dates):
        state = np.sin(day_index / 9)
        volatility.append(
            {"origin_date": day, "lagged_30d_weth_volatility": 0.03 + 0.01 * state}
        )
        for candidate_index, symbol in enumerate(("AAA", "BBB", "CCC")):
            for protocol, is_v4 in (("v3", 0.0), ("v4", 1.0)):
                signal = 0.06 + 0.01 * candidate_index + 0.02 * rng.uniform()
                row = {
                    "origin_date": day,
                    "candidate_date_id": f"{symbol}|{day.date()}",
                    "candidate_address": f"0x{candidate_index + 1:040x}",
                    "candidate_symbol": symbol,
                    "protocol": protocol,
                    "is_v4": is_v4,
                    "internal_tx_share": signal,
                }
                for control_index, control in enumerate(CONTROLS):
                    row[control] = (
                        0.1 * candidate_index
                        + 0.02 * control_index
                        + 0.02 * rng.normal()
                    )
                common = 0.002 * day_index**2 + 0.1 * candidate_index
                protocol_state = (1.0 + 4.0 * is_v4) * signal * state
                row["near_log1p_incumbent_actions"] = (
                    common + 1.5 * signal + protocol_state
                )
                row["late_log1p_first_active_origins"] = (
                    common + 0.5 * signal + 1.2 * protocol_state
                )
                rows.append(row)
    result = fit_protocol_volatility_comparison(
        pd.DataFrame(rows),
        pd.DataFrame(volatility),
        sample_variant="test",
        min_observations=200,
        min_clusters=30,
    )
    assert len(result) == 2
    assert result[
        "v4_minus_v3_state_interaction_per_10pp_per_1sd"
    ].gt(0).all()
    assert result["v4_minus_v3_state_interaction_holm_p_value"].between(0, 1).all()

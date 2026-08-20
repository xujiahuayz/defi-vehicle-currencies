from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from scripts.analyze.run_v4_lp_origin_timing import (
    CONTROLS,
    OUTCOMES,
    PREDICTORS,
    build_origin_timing_panel,
    fit_origin_timing,
    load_raw_origin_actions,
)


ADDRESS = "0x0000000000000000000000000000000000000001"


def test_raw_origin_actions_separate_zero_liquidity_updates(tmp_path) -> None:
    path = tmp_path / "uniswap_v4_modify_liquidities_2025-01-01.jsonl.gz"
    events = [
        {
            "timestamp": 1_735_689_600,
            "origin": "0xaaa",
            "amount": "10",
            "pool": {"token0": {"id": ADDRESS}, "token1": {"id": "0xother"}},
        },
        {
            "timestamp": 1_735_689_601,
            "origin": "0xbbb",
            "amount": "0",
            "pool": {"token0": {"id": ADDRESS}, "token1": {"id": "0xother"}},
        },
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    all_updates, nonzero, support = load_raw_origin_actions(
        event_dir=tmp_path,
        candidate_map={ADDRESS: (ADDRESS, "AAA")},
    )
    day = pd.Timestamp("2025-01-01")
    assert set(all_updates[ADDRESS][day]) == {"0xaaa", "0xbbb"}
    assert set(nonzero[ADDRESS][day]) == {"0xaaa"}
    assert support["candidate_event_assignments"] == 2
    assert support["nonzero_candidate_event_assignments"] == 1


def test_origin_timing_classifies_near_and_late_activity() -> None:
    origin_date = pd.Timestamp("2025-07-01")
    daily = {
        ADDRESS: {
            pd.Timestamp("2025-01-02"): {"old": 1},
            pd.Timestamp("2025-07-02"): {"old": 2, "early": 1},
            pd.Timestamp("2025-08-10"): {"old": 1, "early": 2, "late": 3},
            pd.Timestamp("2025-10-29"): {"late": 1},
        }
    }
    base = pd.DataFrame(
        [
            {
                "origin_date": origin_date,
                "candidate_address": ADDRESS,
                "candidate_symbol": "AAA",
                **{predictor: 0.1 for predictor in PREDICTORS},
                **{control: 1.0 for control in CONTROLS},
            }
        ]
    )
    panel = build_origin_timing_panel(daily, base, prior_days=180)
    row = panel.iloc[0]
    assert row["near_new_origins"] == 1
    assert row["near_incumbent_actions"] == 2
    assert row["late_first_active_origins"] == 1
    assert row["late_incumbent_actions"] == 1
    assert np.isclose(row["near_log1p_new_origins"], np.log(2))
    assert np.isclose(row["late_log1p_first_active_origins"], np.log(2))


def test_origin_timing_regression_estimates_complete_family() -> None:
    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    rows = []
    for candidate_index, symbol in enumerate(("AAA", "BBB", "CCC")):
        for day_index, day in enumerate(dates):
            signal = 0.01 * candidate_index + 0.002 * (day_index % 9)
            row = {
                "origin_date": day,
                "candidate_symbol": symbol,
                **{predictor: signal * (index + 1) for index, predictor in enumerate(PREDICTORS)},
                **{control: 0.1 * day_index + candidate_index for control in CONTROLS},
            }
            for index, outcome in enumerate(OUTCOMES):
                row[outcome] = 2.0 + (index + 1) * signal + 0.001 * day_index**2
            rows.append(row)
    results = fit_origin_timing(
        pd.DataFrame(rows),
        sample_variant="test",
        predictors=("internal_tx_share",),
        outcomes=OUTCOMES,
        controls=("log1p_swap_leg_assignments",),
        min_observations=50,
        min_clusters=20,
    )
    assert len(results) == len(OUTCOMES)
    assert set(results["outcome"]) == set(OUTCOMES)
    assert results["holm_p_value"].between(0, 1).all()
    assert np.isfinite(results["coefficient"]).all()

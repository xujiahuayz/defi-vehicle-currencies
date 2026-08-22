from __future__ import annotations

import pandas as pd
import pytest

from ddvc.analysis.pair_composition_materiality import material_pair_composition


NATIVE = "0x0000000000000000000000000000000000000001"
STABLE = "0x0000000000000000000000000000000000000002"


def _choice(
    date: str,
    src: str,
    tgt: str,
    candidate_type: str,
    route_count: float,
    supported_value: float,
) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "candidate_address": NATIVE if candidate_type == "native" else STABLE,
        "candidate_type": candidate_type,
        "venue_sequence": "uniswap_v3>uniswap_v3",
        "integration_scope": "single_venue",
        "route_count": route_count,
        "within_20pct_routes": route_count,
        "within_20pct_value_usd": supported_value,
    }


def _choices() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _choice("2024-01-01", "a", "b", "native", 8, 80_000),
            _choice("2024-01-01", "a", "b", "stable", 2, 20_000),
            _choice("2026-01-01", "a", "b", "native", 5, 50_000),
            _choice("2026-01-01", "a", "b", "stable", 5, 50_000),
            _choice("2024-01-01", "c", "d", "native", 3, 3_000),
            _choice("2024-01-01", "c", "d", "stable", 1, 1_000),
            _choice("2026-01-01", "c", "d", "stable", 10, 60_000),
            _choice("2024-01-01", "e", "f", "stable", 20, 100_000),
            _choice("2026-01-01", "g", "h", "stable", 20, 100_000),
            _choice("2024-01-01", "i", "j", "native", 6, 10_000),
            _choice("2026-01-01", "i", "j", "stable", 6, 10_000),
        ]
    )


def _row(result: pd.DataFrame, spec_id: str) -> pd.Series:
    return result[result["robustness_spec_id"].eq(spec_id)].iloc[0]


def test_material_pair_floors_rerun_the_exact_identity() -> None:
    decomposition, support = material_pair_composition(_choices())
    assert len(decomposition) == 4
    assert decomposition["identity_error"].abs().max() < 1e-12
    assert set(support["support_status"]) == {
        "common",
        "baseline_exclusive",
        "comparison_exclusive",
    }

    route_5 = _row(decomposition, "route_count_floor_5")
    assert route_5["baseline_stable_share"] == pytest.approx(22 / 36)
    assert route_5["comparison_stable_share"] == pytest.approx(41 / 46)
    assert route_5["total_change"] == pytest.approx(41 / 46 - 22 / 36)
    assert route_5["baseline_retained_pair_periods"] == 3
    assert route_5["comparison_retained_pair_periods"] == 4

    route_10 = _row(decomposition, "route_count_floor_10")
    assert route_10["baseline_stable_share"] == pytest.approx(22 / 30)
    assert route_10["comparison_stable_share"] == pytest.approx(35 / 40)
    assert route_10["total_change"] == pytest.approx(35 / 40 - 22 / 30)

    value_5k = _row(decomposition, "supported_value_floor_5000")
    assert value_5k["baseline_stable_share"] == pytest.approx(120 / 210)
    assert value_5k["comparison_stable_share"] == pytest.approx(220 / 270)
    assert value_5k["total_change"] == pytest.approx(220 / 270 - 120 / 210)

    value_50k = _row(decomposition, "supported_value_floor_50000")
    assert value_50k["baseline_stable_share"] == pytest.approx(120 / 200)
    assert value_50k["comparison_stable_share"] == pytest.approx(210 / 260)
    assert value_50k["total_change"] == pytest.approx(210 / 260 - 120 / 200)
    assert value_50k["threshold_unit"] == "usd_supported_value"
    assert value_50k["threshold_rule"] == (
        "ordered_endpoint_pair_period_denominator_gte_threshold"
    )

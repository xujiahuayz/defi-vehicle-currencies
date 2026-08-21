from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_entry_vehicle_price_alignment import (
    entry_vehicle_panel,
    prepare_alignment_panel,
    summarize_alignment,
)


def _entry(
    date: str,
    src: str,
    tgt: str,
    *,
    stable: float,
    native: float,
) -> dict[str, object]:
    return {
        "date": date,
        "src": src,
        "tgt": tgt,
        "pair_entry_on_day": True,
        "primary_choice_route_count": stable + native,
        "stable_choice_route_count": stable,
        "native_choice_route_count": native,
    }


def _route(
    route_id: str,
    src: str,
    tgt: str,
    *,
    chosen: str,
    public: str,
    gain: float,
) -> dict[str, object]:
    return {
        "day": "20210115",
        "token_in": src,
        "token_out": tgt,
        "route_id": route_id,
        "input_usd": 1_000.0,
        "within_20pct": True,
        "chosen_max_price_impact": 0.01,
        "chosen_vehicle_type": chosen,
        "public_vehicle_type": public,
        "public_path_regret_bps": gain,
    }


def test_alignment_conditions_incumbent_use_on_exact_price_leader() -> None:
    pair_support = pd.DataFrame(
        [
            _entry("2020-01-01", "a", "b", stable=8, native=2),
            _entry("2020-01-01", "c", "d", stable=1, native=9),
        ]
    )
    frontier = pd.DataFrame(
        [
            _route("r1", "a", "b", chosen="stable", public="native", gain=10),
            _route("r2", "a", "b", chosen="native", public="native", gain=0),
            _route("r3", "c", "d", chosen="native", public="native", gain=0),
            _route("r4", "c", "d", chosen="native", public="direct", gain=20),
        ]
    )
    panel = prepare_alignment_panel(frontier, pair_support)
    assert dict(
        panel[["route_id", "price_leader_relation"]].itertuples(
            index=False, name=None
        )
    ) == {
        "r1": "challenger",
        "r2": "challenger",
        "r3": "incumbent",
        "r4": "challenger",
    }
    assert panel.set_index("route_id").loc["r1", "exact_vehicle_challenge"]
    assert pd.isna(panel.set_index("route_id").loc["r4", "price_leader_type"])

    result = summarize_alignment(panel)
    challenger = result[
        result["record_type"].eq("entry_price_leader_alignment")
        & result["horizon_days"].eq(120)
        & result["weighting"].eq("route")
        & result["entry_vehicle_type"].eq("pooled")
        & result["price_leader_relation"].eq("challenger")
    ].iloc[0]
    assert challenger["observations"] == 2
    assert challenger["incumbent_vehicle_share"] == pytest.approx(0.5)
    incumbent = result[
        result["record_type"].eq("entry_price_leader_alignment")
        & result["horizon_days"].eq(120)
        & result["weighting"].eq("route")
        & result["entry_vehicle_type"].eq("pooled")
        & result["price_leader_relation"].eq("incumbent")
    ].iloc[0]
    assert incumbent["incumbent_vehicle_share"] == 1.0


def test_entry_vehicle_panel_rejects_multiple_entry_dates() -> None:
    support = pd.DataFrame(
        [
            _entry("2020-01-01", "a", "b", stable=8, native=2),
            _entry("2020-01-02", "a", "b", stable=7, native=3),
        ]
    )
    with pytest.raises(ValueError, match="multiple entry dates"):
        entry_vehicle_panel(support)

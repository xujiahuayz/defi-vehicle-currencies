from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze import run_first_contestable_vehicle_choice as first_choice
from scripts.analyze.run_contestable_vehicle_choice import USDC, WETH
from scripts.analyze.run_first_contestable_vehicle_choice import (
    FOUR_PER_MONTH_DAYS,
    FOUR_PER_MONTH_OUTPUT,
    FOUR_PER_MONTH_PANEL,
    FOUR_PER_MONTH_SUPPORT,
    first_contestable_routes,
    four_per_month_days,
    four_per_month_schedule,
    four_per_month_support_results,
    prepare_four_per_month_panel,
    replay_four_per_month_schedule,
    support_results,
)


def _frontier_row(
    day: str,
    route_id: str,
    token_in: str,
    token_out: str,
    *,
    chosen_stable: bool,
    gap_bps: float,
) -> dict[str, object]:
    return {
        "day": day,
        "route_id": route_id,
        "token_in": token_in,
        "token_out": token_out,
        "chosen_vehicle": USDC if chosen_stable else WETH,
        "chosen_vehicle_type": "stable" if chosen_stable else "native",
        "input_usd": 1_000.0,
        "output_usd": 1_000.0,
        "within_20pct": True,
        "chosen_max_price_impact": 0.01,
        "vehicle_families_contestable": True,
        "stable_minus_native_bps": gap_bps,
        "native_public_out": 100.0,
        "native_public_vehicle": WETH,
        "native_public_venues": "uniswap_v2|uniswap_v3",
        "stable_public_out": 100.0 * (1 + gap_bps / 10_000.0),
        "stable_public_vehicle": USDC,
        "stable_public_venues": "uniswap_v3|uniswap_v2",
    }


def _entry(
    token_in: str,
    token_out: str,
    *,
    entry_stable: float,
) -> dict[str, object]:
    return {
        "day": "20240101",
        "entry_date": pd.Timestamp("2024-01-01"),
        "token_in": token_in,
        "token_out": token_out,
        "ordered_pair": f"{token_in}>{token_out}",
        "entry_primary_routes": 10.0,
        "entry_native_routes": 10.0 if entry_stable == 0 else 0.0,
        "entry_stable_routes": 10.0 if entry_stable == 1 else 0.0,
        "entry_stable_share": entry_stable,
        "entry_stable": entry_stable,
        "entry_tie": False,
        "entry_exclusive": True,
        "entry_mixed": False,
        "entry_coherent_routes": 10.0,
        "entry_coherent_value_usd": 100_000.0,
    }


def test_first_contestable_routes_keep_all_routes_on_first_supported_date(
    tmp_path,
) -> None:
    frontier = pd.DataFrame(
        [
            _frontier_row(
                "20240215", "first-native", "src-a", "tgt-a", chosen_stable=False, gap_bps=-5.0
            ),
            _frontier_row(
                "20240215", "first-stable", "src-a", "tgt-a", chosen_stable=True, gap_bps=5.0
            ),
            _frontier_row(
                "20240315", "later", "src-a", "tgt-a", chosen_stable=True, gap_bps=10.0
            ),
            _frontier_row(
                "20231215", "before-entry", "src-b", "tgt-b", chosen_stable=False, gap_bps=-2.0
            ),
        ]
    )
    path = tmp_path / "frontier.parquet"
    frontier.to_parquet(path, index=False)
    entries = pd.DataFrame(
        [
            _entry("src-a", "tgt-a", entry_stable=0.0),
            _entry("src-b", "tgt-b", entry_stable=1.0),
        ]
    )

    result = first_contestable_routes(path, entries)

    assert set(result["route_id"]) == {"first-native", "first-stable"}
    assert result["day"].eq("20240215").all()
    assert result["entry_to_contestability_days"].eq(45).all()
    retained = result.set_index("route_id")["entry_vehicle_retained"]
    assert retained["first-native"] == 1.0
    assert retained["first-stable"] == 0.0
    assert result["route_scope"].eq(
        "uniswap_v2|uniswap_v3||uniswap_v3|uniswap_v2"
    ).all()


def test_support_distinguishes_entry_from_first_contestability() -> None:
    entries = pd.DataFrame(
        [
            _entry("src-a", "tgt-a", entry_stable=0.0),
            _entry("src-b", "tgt-b", entry_stable=1.0),
            _entry("src-c", "tgt-c", entry_stable=0.0),
        ]
    )
    panel = pd.DataFrame(
        [
            {
                "ordered_pair": "src-a>tgt-a",
                "route_id": "a1",
                "day": "20240215",
                "chosen_stable": 0.0,
                "entry_stable": 0.0,
                "entry_vehicle_retained": 1.0,
                "entry_to_contestability_days": 45,
                "both_v2_bridge_capitals_positive": True,
            },
            {
                "ordered_pair": "src-a>tgt-a",
                "route_id": "a2",
                "day": "20240215",
                "chosen_stable": 0.0,
                "entry_stable": 0.0,
                "entry_vehicle_retained": 1.0,
                "entry_to_contestability_days": 45,
                "both_v2_bridge_capitals_positive": True,
            },
            {
                "ordered_pair": "src-b>tgt-b",
                "route_id": "b1",
                "day": "20240515",
                "chosen_stable": 0.0,
                "entry_stable": 1.0,
                "entry_vehicle_retained": 0.0,
                "entry_to_contestability_days": 135,
                "both_v2_bridge_capitals_positive": False,
            },
        ]
    )

    support = support_results(
        entries,
        panel,
        entry_value_threshold_usd=5_000.0,
        sampling_calendar="four_per_month",
    ).set_index("sample")

    cohort = support.loc["material_entry_cohort"]
    assert cohort["entry_pairs"] == 3
    assert cohort["pairs_reaching_sampled_contestability"] == 2
    assert cohort["contestability_coverage_share"] == pytest.approx(2 / 3)
    assert cohort["entry_value_threshold_usd"] == 5_000.0
    assert cohort["sampling_calendar"] == "four_per_month"
    survival = support.loc["entry_vehicle_survival"]
    assert survival["route_weighted_retention_share"] == pytest.approx(2 / 3)
    assert survival["equal_pair_retention_share"] == pytest.approx(0.5)
    lag = support.loc["entry_to_first_sampled_contestability_lag"]
    assert lag["median_days"] == pytest.approx(90.0)
    assert not bool(lag["monthly_sampling"])


def test_four_per_month_calendar_is_fixed_and_bounded() -> None:
    assert FOUR_PER_MONTH_DAYS == (1, 8, 15, 22)
    assert four_per_month_days("20240105", "20240209") == [
        "20240108",
        "20240115",
        "20240122",
        "20240201",
        "20240208",
    ]
    with pytest.raises(ValueError, match="ends before"):
        four_per_month_days("20240201", "20240101")


def test_four_per_month_schedule_keeps_active_post_entry_grid_dates(
    tmp_path,
) -> None:
    entries = pd.DataFrame(
        [
            _entry("src-a", "tgt-a", entry_stable=0.0),
            _entry("src-b", "tgt-b", entry_stable=1.0),
        ]
    )
    support = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2023-12-22"),
                "src": "src-a",
                "tgt": "tgt-a",
                "primary_choice_route_count": 1,
                "native_within_20pct_routes": 1,
                "stable_within_20pct_routes": 0,
                "native_within_20pct_value_usd": 100.0,
                "stable_within_20pct_value_usd": 0.0,
            },
            {
                "date": pd.Timestamp("2024-01-08"),
                "src": "src-a",
                "tgt": "tgt-a",
                "primary_choice_route_count": 3,
                "native_within_20pct_routes": 2,
                "stable_within_20pct_routes": 1,
                "native_within_20pct_value_usd": 200.0,
                "stable_within_20pct_value_usd": 100.0,
            },
            {
                "date": pd.Timestamp("2024-01-09"),
                "src": "src-a",
                "tgt": "tgt-a",
                "primary_choice_route_count": 4,
                "native_within_20pct_routes": 2,
                "stable_within_20pct_routes": 2,
                "native_within_20pct_value_usd": 200.0,
                "stable_within_20pct_value_usd": 200.0,
            },
            {
                "date": pd.Timestamp("2024-01-15"),
                "src": "src-b",
                "tgt": "tgt-b",
                "primary_choice_route_count": 2,
                "native_within_20pct_routes": 0,
                "stable_within_20pct_routes": 2,
                "native_within_20pct_value_usd": 0.0,
                "stable_within_20pct_value_usd": 500.0,
            },
        ]
    )
    path = tmp_path / "pair-support.parquet"
    support.to_parquet(path, index=False)

    schedule = four_per_month_schedule(
        entries,
        path,
        start="20240101",
        end="20240131",
    )

    assert schedule[["day", "ordered_pair"]].to_records(index=False).tolist() == [
        ("20240108", "src-a>tgt-a"),
        ("20240115", "src-b>tgt-b"),
    ]
    assert schedule["sampled_primary_routes"].tolist() == [3.0, 2.0]
    assert schedule["sampled_coherent_routes"].tolist() == [3.0, 2.0]


def test_four_per_month_replay_stops_pairs_after_first_contest_and_replays_v3(
    monkeypatch,
) -> None:
    schedule_rows: list[dict[str, object]] = []
    for day in ("20240101", "20240108", "20240115"):
        for token_in, token_out in (("src-a", "tgt-a"), ("src-b", "tgt-b")):
            schedule_rows.append(
                {
                    "day": day,
                    "token_in": token_in,
                    "token_out": token_out,
                }
            )
    schedule = pd.DataFrame(schedule_rows)
    loaded_days: list[str] = []
    scored: list[tuple[str, tuple[str, ...]]] = []

    class FakeReplay:
        def apply_all(self, events) -> None:
            loaded_days.extend(events)

    def fake_load(_path, day, **_kwargs):
        return [day]

    def fake_score(day, current, _replay):
        pairs = tuple(sorted(current["token_in"].astype(str)))
        scored.append((day, pairs))
        rows: list[dict[str, object]] = []
        if day == "20240108":
            rows = [
                {
                    "day": day,
                    "route_id": route_id,
                    "token_in": "src-a",
                    "token_out": "tgt-a",
                }
                for route_id in ("a-one", "a-two")
            ]
        elif day == "20240115":
            rows = [
                {
                    "day": day,
                    "route_id": "b-one",
                    "token_in": "src-b",
                    "token_out": "tgt-b",
                }
            ]
        return rows, {
            "day": day,
            "selected_pair_routes": len(current),
            "exact_contestable_rows": len(rows),
        }

    monkeypatch.setattr(first_choice, "TICK_START", "20240101")
    monkeypatch.setattr(first_choice, "TickReplayState", FakeReplay)
    monkeypatch.setattr(first_choice, "load_tick_day_events", fake_load)
    monkeypatch.setattr(first_choice, "score_entry_day", fake_score)

    panel, day_support = replay_four_per_month_schedule(schedule)

    assert set(panel["route_id"]) == {"a-one", "a-two", "b-one"}
    assert panel[panel["token_in"].eq("src-a")]["day"].eq("20240108").all()
    assert scored == [
        ("20240101", ("src-a", "src-b")),
        ("20240108", ("src-a", "src-b")),
        ("20240115", ("src-b",)),
    ]
    assert "20240102" in loaded_days
    assert "20240107" in loaded_days
    assert "20240109" in loaded_days
    assert "20240114" in loaded_days
    assert day_support["first_contestable_pairs"].tolist() == [0, 1, 1]


def test_prepare_four_per_month_panel_uses_alternative_route_scope() -> None:
    exact = pd.DataFrame(
        [
            {
                **_frontier_row(
                    "20240108",
                    "route-a",
                    "src-a",
                    "tgt-a",
                    chosen_stable=False,
                    gap_bps=-2.0,
                ),
                "entry_date": pd.Timestamp("2024-01-01"),
            }
        ]
    )
    entries = pd.DataFrame([_entry("src-a", "tgt-a", entry_stable=0.0)])

    panel = prepare_four_per_month_panel(exact, entries)

    assert panel["entry_to_contestability_days"].item() == 7
    assert panel["entry_vehicle_retained"].item() == 1.0
    assert panel["route_scope"].item() == (
        "uniswap_v2|uniswap_v3||uniswap_v3|uniswap_v2"
    )
    assert panel["fixed_sample_days"].item() == "1,8,15,22"


def test_four_per_month_support_adds_schedule_and_attrition_funnel() -> None:
    entries = pd.DataFrame(
        [
            _entry("src-a", "tgt-a", entry_stable=0.0),
            _entry("src-b", "tgt-b", entry_stable=1.0),
        ]
    )
    panel = pd.DataFrame(
        [
            {
                "ordered_pair": "src-a>tgt-a",
                "route_id": "a1",
                "day": "20240108",
                "chosen_stable": 0.0,
                "entry_stable": 0.0,
                "entry_vehicle_retained": 1.0,
                "entry_to_contestability_days": 7,
                "both_v2_bridge_capitals_positive": True,
            }
        ]
    )
    schedule = pd.DataFrame(
        [
            {
                "day": "20240108",
                "ordered_pair": "src-a>tgt-a",
                "sampled_primary_routes": 3.0,
                "sampled_coherent_routes": 2.0,
            },
            {
                "day": "20240115",
                "ordered_pair": "src-b>tgt-b",
                "sampled_primary_routes": 4.0,
                "sampled_coherent_routes": 4.0,
            },
        ]
    )
    day_support = pd.DataFrame(
        [
            {
                "day": "20240108",
                "linear_routes": 20,
                "exact_venue_routes": 18,
                "selected_pair_routes": 3,
                "mapped_selected_pair_routes": 3,
                "economic_targets": 2,
                "chosen_quote_reproduced": 2,
                "native_path_available": 2,
                "stable_path_available": 1,
                "both_paths_available": 1,
                "chosen_impact_supported": 2,
                "exact_contestable_rows": 1,
            }
        ]
    )

    result = four_per_month_support_results(
        entries,
        schedule,
        panel,
        day_support,
        elapsed_seconds=12.0,
    ).set_index("sample")

    scheduled = result.loc["four_per_month_sampling_schedule"]
    assert scheduled["scheduled_pairs"] == 2
    assert scheduled["scheduled_primary_routes"] == 7.0
    funnel = result.loc["four_per_month_exact_attrition"]
    assert funnel["linear_routes"] == 20
    assert funnel["selected_pair_routes"] == 3
    assert funnel["exact_contestable_routes"] == 1
    assert funnel["first_contestable_pairs"] == 1
    assert (result["fixed_sample_days"] == "1,8,15,22").all()
    assert FOUR_PER_MONTH_PANEL.name.endswith("_four_per_month.parquet")
    assert FOUR_PER_MONTH_OUTPUT.name.endswith("_four_per_month.jsonl")
    assert FOUR_PER_MONTH_SUPPORT.name.endswith("_four_per_month_support.jsonl")

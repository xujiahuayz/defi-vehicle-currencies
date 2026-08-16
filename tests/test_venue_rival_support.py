from __future__ import annotations

import unittest

import pandas as pd

from ddvc.venue_tables import (
    RIVAL_SCOPE_ORDER,
    ROUTER_EVENT_ORDER,
    render_routing_technology_windows,
    render_venue_technology_rival,
    router_event_date_text,
    routing_window_values,
    venue_technology_rival_values,
)
from scripts.test_venue_technology_rival import bounded_workers, support_status


def _row(year: int, scope: str, asset: str, count: float | None, value: float | None):
    return {
        "year": year,
        "scope": scope,
        "asset_type": asset,
        "support_status": "identified" if count is not None else "no_intermediation",
        "vehicle_excess_use_count_ratio": count,
        "vehicle_excess_use_ratio": value,
    }


def _minimal_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for year in range(2020, 2027):
        for asset, base in (("stable", 1.0), ("native", 0.8)):
            rows.append(_row(year, "all_venues", asset, base, base + 0.1))
            rows.append(_row(year, "constant_product_only", asset, base, base + 0.1))
            rows.append(_row(year, "curve_only", asset, None, None))
    return rows


class VenueTechnologyRivalTests(unittest.TestCase):
    def test_scope_with_no_intermediation_is_explicitly_unsupported(self) -> None:
        daily = pd.DataFrame(
            {
                "year": [2025, 2025, 2025, 2025],
                "scope": [
                    "curve_only",
                    "curve_only",
                    "constant_product_only",
                    "no_demand_scope",
                ],
                "intermediate_usd": [0.0, 0.0, 10.0, 0.0],
                "intermediate_routes": [0, 0, 1, 0],
                "endpoint_usd": [100.0, 200.0, 100.0, 0.0],
                "endpoint_routes": [1, 2, 1, 0],
            }
        )
        status = support_status(daily).set_index("scope")
        self.assertEqual(status.loc["curve_only", "support_status"], "no_intermediation")
        self.assertEqual(status.loc["constant_product_only", "support_status"], "identified")
        self.assertEqual(status.loc["no_demand_scope", "support_status"], "no_endpoint_demand")

    def test_workers_are_bounded(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(100), 8)

    def test_unidentified_scope_is_labelled_rather_than_blank(self) -> None:
        rendered = render_venue_technology_rival(_minimal_rows())
        self.assertIn("no intermediation", rendered)
        self.assertNotIn("& &", rendered)
        self.assertIn("Panel A: Stablecoins", rendered)
        self.assertIn("Panel B: Native asset", rendered)

    def test_an_absent_venue_year_is_distinguished_from_an_empty_one(self) -> None:
        # Balancer contributes no route component at all in the first sample year,
        # which is a different statement from contributing components that carry no
        # intermediary episode, as the all-Curve scope does throughout.
        rows = _minimal_rows()
        rows.extend(
            _row(year, "balancer_only", asset, 1.2, 1.3)
            for year in range(2021, 2027)
            for asset in ("stable", "native")
        )
        panels = venue_technology_rival_values(rows)
        first_year = dict(panels["stable"])["2020"]
        later_year = dict(panels["stable"])["2021"]
        balancer = RIVAL_SCOPE_ORDER.index("balancer_only")
        curve = RIVAL_SCOPE_ORDER.index("curve_only")
        self.assertEqual(first_year[balancer], "no routes")
        self.assertEqual(later_year[balancer], (1.2, 1.3))
        self.assertEqual(first_year[curve], "no intermediation")

    def test_an_identified_row_without_a_ratio_is_a_hard_failure(self) -> None:
        rows = _minimal_rows()
        broken = dict(rows[0])
        broken["vehicle_excess_use_ratio"] = None
        rows[0] = broken
        with self.assertRaisesRegex(ValueError, "labelled identified"):
            venue_technology_rival_values(rows)

    def test_a_year_with_no_supported_scope_is_a_hard_failure(self) -> None:
        rows = [
            row
            for row in _minimal_rows()
            if not (row["year"] == 2023 and row["scope"] != "curve_only")
        ]
        with self.assertRaisesRegex(ValueError, "no support in 2023"):
            venue_technology_rival_values(rows)

    def test_duplicate_scope_year_rows_are_rejected(self) -> None:
        rows = _minimal_rows()
        rows.append(_row(2024, "all_venues", "stable", 1.0, 1.1))
        with self.assertRaisesRegex(ValueError, "duplicate venue-rival row"):
            venue_technology_rival_values(rows)


if __name__ == "__main__":
    unittest.main()


def _window_row(event: str, period: str, scope: str, **moments):
    row = {
        "event": event,
        "event_date": "2021-09-16 00:00:00",
        "period": period,
        "scope": scope,
        "window_days": 60,
        "calendar_days": 60,
        "economic_multileg_share": 0.20,
        "intermediated_share": 0.18,
        "cross_venue_share": 0.09,
        "over_two_legs_share": 0.07,
        "mean_legs": 2.08,
        "mean_venues": 1.10,
    }
    row.update(moments)
    return row


def _window_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in ROUTER_EVENT_ORDER:
        for period in ("pre", "post"):
            for scope in ("full", "balanced"):
                rows.append(_window_row(event, period, scope))
    return rows


class RouterWindowTests(unittest.TestCase):
    def test_ordered_releases_carry_both_periods(self) -> None:
        windows = routing_window_values(_window_rows())
        self.assertEqual([window[0] for window in windows], list(ROUTER_EVENT_ORDER))
        for _event, _date, days, pre, post in windows:
            self.assertEqual(days, 60)
            self.assertEqual(set(pre), set(post))

    def test_a_diverging_balanced_perimeter_is_a_hard_failure(self) -> None:
        rows = _window_rows()
        for row in rows:
            if row["scope"] == "balanced" and row["period"] == "post":
                row["intermediated_share"] = 0.17
        with self.assertRaisesRegex(ValueError, "balanced perimeter"):
            routing_window_values(rows)

    def test_unequal_window_lengths_are_a_hard_failure(self) -> None:
        rows = _window_rows()
        for row in rows:
            if row["period"] == "post":
                row["calendar_days"] = 47
        with self.assertRaisesRegex(ValueError, "unequal observed calendars"):
            routing_window_values(rows)

    def test_a_missing_period_is_a_hard_failure(self) -> None:
        rows = [row for row in _window_rows() if row["period"] != "post"]
        with self.assertRaisesRegex(ValueError, "lacks"):
            routing_window_values(rows)

    def test_the_rendered_change_row_is_the_post_minus_pre_difference(self) -> None:
        rows = _window_rows()
        for row in rows:
            if row["period"] == "post":
                row["intermediated_share"] = 0.15
                row["mean_legs"] = 2.10
        rendered = render_routing_technology_windows(rows)
        self.assertIn(r"Change & $+0.0$ & $-3.0$", rendered)
        self.assertIn("$+0.02$", rendered)

    def test_the_release_date_is_rendered_for_a_finance_reader(self) -> None:
        self.assertEqual(router_event_date_text("2022-11-17"), "November 17, 2022")

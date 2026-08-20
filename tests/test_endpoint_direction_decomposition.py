from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_endpoint_direction_decomposition import (
    ENDPOINT_GROUPS,
    endpoint_direction_decomposition,
)


def _cells() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in (2024, 2026):
        for day in ("01-01", "01-02"):
            for index, group in enumerate(ENDPOINT_GROUPS, start=1):
                total = float(index * (2 if year == 2026 else 1))
                stable = total * (0.8 if year == 2026 else 0.4)
                date = pd.Timestamp(f"{year}-{day}")
                rows.extend(
                    [
                        {
                            "date": date,
                            "year": year,
                            "month_day": day,
                            "endpoint_group": group,
                            "candidate_type": "native",
                            "route_count": total - stable,
                            "within_20pct_value_usd": (total - stable) * 10,
                        },
                        {
                            "date": date,
                            "year": year,
                            "month_day": day,
                            "endpoint_group": group,
                            "candidate_type": "stable",
                            "route_count": stable,
                            "within_20pct_value_usd": stable * 10,
                        },
                    ]
                )
    return pd.DataFrame(rows)


def test_endpoint_direction_decomposition_is_exact() -> None:
    results = endpoint_direction_decomposition(_cells())
    assert len(results) == 2 * len(ENDPOINT_GROUPS)
    assert set(results["common_calendar_days"]) == {2}
    for _metric, rows in results.groupby("metric"):
        assert rows["route_mass_share_baseline"].sum() == pytest.approx(1.0)
        assert rows["route_mass_share_comparison"].sum() == pytest.approx(1.0)
        assert rows["stable_share_contribution_change"].sum() == pytest.approx(0.4)
        assert rows["share_of_total_stable_change"].sum() == pytest.approx(1.0)
        assert rows["conditional_stable_share_baseline"].tolist() == pytest.approx(
            [0.4] * len(ENDPOINT_GROUPS)
        )
        assert rows["conditional_stable_share_comparison"].tolist() == pytest.approx(
            [0.8] * len(ENDPOINT_GROUPS)
        )


def test_endpoint_direction_decomposition_uses_only_common_days() -> None:
    cells = _cells()
    extra = cells.iloc[[0]].copy()
    extra["date"] = pd.Timestamp("2024-01-03")
    extra["month_day"] = "01-03"
    results = endpoint_direction_decomposition(pd.concat([cells, extra], ignore_index=True))
    assert set(results["common_calendar_days"]) == {2}


def test_endpoint_direction_decomposition_rejects_negative_mass() -> None:
    cells = _cells()
    cells.loc[0, "route_count"] = -1
    with pytest.raises(ValueError, match="invalid route_count"):
        endpoint_direction_decomposition(cells)

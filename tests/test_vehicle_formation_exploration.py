from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_vehicle_formation_exploration import (
    entry_follow_panel,
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
        ]
    )
    path = tmp_path / "pair_support.parquet"
    frame.to_parquet(path, index=False)
    return path


def test_entry_follow_panel_requires_complete_horizon(pair_support_path) -> None:
    follow = entry_follow_panel(
        30,
        pair_support_path=pair_support_path,
        sample_end=pd.Timestamp("2026-06-30"),
    )
    assert set(follow["src"]) == {"a", "c"}
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

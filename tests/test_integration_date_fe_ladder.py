"""The within-day integration ladder must keep the claims its prose makes.

Section 3.5 and the venue-scope deck frame now report a LEVEL gap between the
single- and cross-exchange halves of the same trading day. Three things the prose
says out loud are properties of the estimator rather than of the data, and a
silent regeneration that broke any of them would leave the paper asserting
something the exhibit no longer supports:

  * the stack is balanced, so the pooled and day-absorbed point estimates are
    equal by arithmetic and the equality may never be sold as a survival test;
  * a day enters only when BOTH halves are measured, because the estimand is a
    paired difference;
  * the R5 year indicators partition the cross-exchange observations with no
    omitted base year, so each coefficient IS that year's gap.

The log-odds boundary case is included because a share pinned at zero or one
produces an infinity that a later mask can hide, and a hidden infinity is how a
day silently leaves a sample without anyone noticing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_integration_date_fe_ladder import (
    MIN_YEAR_DAYS,
    annual_path,
    fit,
    stacked,
)


def _panel(days: int = 400, *, seed: int = 7) -> pd.DataFrame:
    """A panel shaped like the committed one: two scopes, positive denominators."""

    generator = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=days, freq="D")
    frame = pd.DataFrame({"date": dates})
    for scope, stable_mean in (("single_venue", 30.0), ("cross_venue", 45.0)):
        stable = generator.gamma(4.0, stable_mean / 4.0, size=days)
        native = generator.gamma(4.0, 25.0, size=days)
        frame[f"cnt_{scope}_stable"] = stable
        frame[f"cnt_{scope}_native"] = native
    return frame


def _gap(frame: pd.DataFrame, spec_terms: list[str]) -> float:
    return float(fit(frame, spec_terms, date_fe=True).beta[0])


def test_day_effects_cannot_move_the_point_estimate_on_a_balanced_stack() -> None:
    """R1 and R2 coincide, which is why the prose never calls R2 a survival test."""

    frame = stacked(
        _panel(), column_prefix="cnt_", scopes=("single_venue", "cross_venue"),
        transformation="share_level",
    )
    pooled = float(fit(frame, ["cross_venue"], date_fe=False).beta[1])
    absorbed = float(fit(frame, ["cross_venue"], date_fe=True).beta[0])
    assert pooled == pytest.approx(absorbed, abs=1e-9)


def test_the_within_day_gap_is_the_mean_paired_difference() -> None:
    """The absorbed coefficient must equal the average of the daily differences."""

    frame = stacked(
        _panel(), column_prefix="cnt_", scopes=("single_venue", "cross_venue"),
        transformation="share_level",
    )
    wide = frame.pivot(index="date", columns="regime", values="y")
    expected = float((wide["cross_venue"] - wide["single_venue"]).mean())
    assert _gap(frame, ["cross_venue"]) == pytest.approx(expected, abs=1e-9)


def test_a_day_missing_one_half_leaves_the_sample_entirely() -> None:
    """A day that supports only one regime carries no information about the gap."""

    panel = _panel()
    panel.loc[5, ["cnt_cross_venue_stable", "cnt_cross_venue_native"]] = 0.0
    frame = stacked(
        panel, column_prefix="cnt_", scopes=("single_venue", "cross_venue"),
        transformation="share_level",
    )
    dropped = pd.Timestamp(panel.loc[5, "date"])
    assert dropped not in set(frame["date"])
    # Both halves leave together, so the stack stays balanced and the identity above
    # keeps holding. An unbalanced stack would break it silently.
    assert frame.groupby("date").size().eq(2).all()


def test_log_odds_drops_boundary_days_instead_of_carrying_an_infinity() -> None:
    """A share pinned at one must leave the sample, not arrive as a masked infinity."""

    panel = _panel()
    panel.loc[9, "cnt_cross_venue_native"] = 0.0
    frame = stacked(
        panel, column_prefix="cnt_", scopes=("single_venue", "cross_venue"),
        transformation="log_odds",
    )
    assert pd.Timestamp(panel.loc[9, "date"]) not in set(frame["date"])
    assert np.isfinite(frame["y"]).all()


def test_year_indicators_partition_the_cross_exchange_observations() -> None:
    """Each R5 coefficient is that year's gap, not a difference from a base year."""

    panel = _panel(days=3 * MIN_YEAR_DAYS + 400)
    frame = stacked(
        panel, column_prefix="cnt_", scopes=("single_venue", "cross_venue"),
        transformation="share_level",
    )
    rows = annual_path(
        frame,
        supported_days=int(frame["date"].nunique()),
        dropped_days=0,
        base={"routing_basis": "test", "weighting": "episode"},
    )
    assert rows, "the fixture must span at least two adequately supported years"
    assert all(row["term"].startswith("cross_venue_") for row in rows)

    wide = frame.pivot(index="date", columns="regime", values="y")
    difference = (wide["cross_venue"] - wide["single_venue"]).rename("gap").reset_index()
    difference["year"] = difference["date"].dt.year
    for row in rows:
        year = int(row["term"].removeprefix("cross_venue_"))
        expected = float(difference.loc[difference["year"].eq(year), "gap"].mean())
        assert row["beta"] == pytest.approx(expected, abs=1e-9)


def test_a_year_below_the_support_floor_is_omitted_rather_than_estimated_thin() -> None:
    """A handful of paired days must not be handed a coefficient of its own."""

    panel = _panel(days=500)  # spans 2023 and 2024, both well over the floor
    short = _panel(days=MIN_YEAR_DAYS - 10, seed=11)
    short["date"] = pd.date_range("2026-01-01", periods=len(short), freq="D")
    frame = stacked(
        pd.concat([panel, short], ignore_index=True),
        column_prefix="cnt_",
        scopes=("single_venue", "cross_venue"),
        transformation="share_level",
    )
    rows = annual_path(
        frame,
        supported_days=int(frame["date"].nunique()),
        dropped_days=0,
        base={"routing_basis": "test", "weighting": "episode"},
    )
    assert {row["term"] for row in rows} == {"cross_venue_2023", "cross_venue_2024"}

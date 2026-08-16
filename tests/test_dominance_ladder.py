"""The control-ladder producer must refuse to restate a claim the data dropped.

Every guard in `validated_ladder` stands for a clause the deck frame says out
loud. These tests move one estimate at a time and demand the producer stop,
because a silent regeneration would leave the slide asserting something the
exhibit no longer shows.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.figure.build_dominance_ladder import (
    CONTINUOUS,
    FIXED_EFFECTS,
    POOLED,
    SIZE,
    WINDOW_DAYS,
    WINDOW_SPEC,
    YEAR,
    render_dominance_ladder_deck_values,
    validated_ladder,
)


def _rows() -> list[dict[str, object]]:
    """A ladder shaped like the committed exhibit: pooled gap, imprecise FE."""

    pooled = {"coef": -0.0486, "se": 0.0182, "p": 0.008, "n": 102_845, "clusters": 3_654}
    fixed = {"coef": 0.0937, "se": 0.0847, "p": 0.269, "n": 3_865, "clusters": 158}
    rows: list[dict[str, object]] = [
        {"spec": POOLED, **pooled},
        {"spec": SIZE, **pooled},
        {"spec": YEAR, **pooled},
        {"spec": FIXED_EFFECTS, **fixed},
        {
            "spec": CONTINUOUS,
            "coef": 186.4,
            "se": 105.7,
            "p": 0.078,
            "n": 3_865,
            "clusters": 158,
        },
    ]
    for days in WINDOW_DAYS:
        widened = dict(fixed) if days == 1 else {**fixed, "n": 3_865 + days}
        rows.append(
            {
                "spec": WINDOW_SPEC.format(days=days),
                **widened,
                "identifying_cells": 703,
                "mde_80": 2.80 * fixed["se"],
            }
        )
    return rows


def _frame(**overrides: dict[str, object]) -> pd.DataFrame:
    rows = _rows()
    for spec, changes in overrides.items():
        for row in rows:
            if row["spec"] == spec:
                row.update(changes)
    return pd.DataFrame(rows)


def test_the_reference_ladder_validates() -> None:
    validated = validated_ladder(_frame())
    assert validated["rungs"][POOLED]["n"] == 102_845
    assert validated["windows"][1]["identifying_cells"] == 703


def test_macros_report_the_precision_loss_the_frame_states() -> None:
    rendered = render_dominance_ladder_deck_values(validated_ladder(_frame()))
    assert "\\newcommand{\\DomFEMDE}{$23.7$ points}" in rendered
    assert "\\newcommand{\\DomFECells}{703}" in rendered
    assert "\\newcommand{\\DomPooledCoef}{$-4.9$ points}" in rendered
    assert "\\newcommand{\\DomFECoef}{$+9.4$ points}" in rendered
    # The continuous outcome keeps its own units and never becomes a share.
    assert "\\newcommand{\\DomGapCoef}{$+186$ bps}" in rendered


def test_a_significant_identifying_estimate_stops_the_producer() -> None:
    with pytest.raises(ValueError, match="distinguishable from zero"):
        validated_ladder(_frame(**{FIXED_EFFECTS: {"p": 0.01}}))


def test_a_vanished_pooled_association_stops_the_producer() -> None:
    with pytest.raises(ValueError, match="no longer negative and significant"):
        validated_ladder(_frame(**{POOLED: {"p": 0.4}}))


def test_a_control_that_absorbs_the_gap_stops_the_producer() -> None:
    with pytest.raises(ValueError, match="no longer reproduces the pooled association"):
        validated_ladder(_frame(**{SIZE: {"coef": 0.01}}))


def test_a_recovered_identifying_precision_stops_the_producer() -> None:
    """If the strict column stops being a precision loss, the honest sentence changes."""

    with pytest.raises(ValueError, match="most of the precision"):
        validated_ladder(_frame(**{FIXED_EFFECTS: {"se": 0.02}}))


def test_a_daily_window_that_drifts_from_the_design_stops_the_producer() -> None:
    """The displayed cell count belongs to the displayed coefficient, or nothing."""

    drifted = WINDOW_SPEC.format(days=1)
    with pytest.raises(ValueError, match="no longer reproduces the pair-by-day"):
        validated_ladder(_frame(**{drifted: {"coef": 0.05}}))


def test_a_mislabelled_minimum_detectable_effect_stops_the_producer() -> None:
    daily = WINDOW_SPEC.format(days=1)
    with pytest.raises(ValueError, match="not 80% power"):
        validated_ladder(_frame(**{daily: {"mde_80": 0.10}}))


def test_a_functional_form_disagreement_stops_the_producer() -> None:
    """The frame claims the two outcomes agree; a split verdict must be rewritten."""

    with pytest.raises(ValueError, match="report that disagreement"):
        validated_ladder(_frame(**{CONTINUOUS: {"p": 0.02}}))


def test_a_significant_widened_window_stops_the_producer() -> None:
    widest = WINDOW_SPEC.format(days=WINDOW_DAYS[-1])
    with pytest.raises(ValueError, match="now significant"):
        validated_ladder(_frame(**{widest: {"p": 0.01}}))

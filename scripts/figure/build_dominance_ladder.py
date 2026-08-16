#!/usr/bin/env python3
"""Build the control ladder for dominance quality holding the trade fixed.

The estimand is narrow and is not the aggregate vehicle-share rotation: among
routes between the SAME two tokens on the SAME day, was the one that went
through the native asset less likely to be dominated by an available direct
pool? The ladder walks left to right from a pooled comparison to the identifying
pair-by-day design, and the raw association dissolves as the trade is held
fixed.

The frame this feeds must not read as an estimated null. Column (4) loses the
comparison as well as the association: the sample falls by more than an order of
magnitude and the standard error nearly quintuples, so the design could only
ever have detected an effect several times larger than the pooled one. The
producer therefore publishes the minimum detectable effect and the identifying
cell count alongside every displayed coefficient, and refuses to render if the
precision loss it describes is not there.

Panels:
  A  specification strictness, (1) pooled to (4) pair-by-day fixed effects
  B  the width of the matched cell, one day to one hundred and twenty days

Panel B is within-estimand robustness, not a specification curve: every rung is
the same estimator on the same outcome, and only the width of the conditioning
cell moves. Coefficients from other estimands never join this axis.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from ddvc.figure_outputs import PALETTE, load_current_jsonl, publish_pdf
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.presentation import require_certified_presentation_source
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ESTIMATES = OUTPUT_DIR / "exhibits" / "dominance_regressions.jsonl"
FIGURE = OUTPUT_DIR / "figures" / "dominance_control_ladder.pdf"
DECK_VALUES = OUTPUT_DIR / "exhibits" / "dominance_ladder_deck_values.tex"
CODE_SOURCES = ["scripts/figure/build_dominance_ladder.py"]

POOLED = "(1) pooled"
SIZE = "(2) + log notional"
YEAR = "(3) + year effects"
FIXED_EFFECTS = "(4) pair-by-day FE"
CONTINUOUS = "(5) pair-by-day FE, gap_bps outcome"
LADDER = (POOLED, SIZE, YEAR, FIXED_EFFECTS)
LADDER_LABELS = {
    POOLED: "Pooled",
    SIZE: "+ trade size",
    YEAR: "+ year",
    FIXED_EFFECTS: "Same pair,\nsame day",
}
WINDOW_DAYS = (1, 3, 7, 14, 30, 60, 120)
WINDOW_SPEC = "(4w) pair-by-{days}d FE"
# 80% power against a two-sided 5% test: (1.96 + 0.84) standard errors.
MDE_MULTIPLIER = 2.80
CRITICAL = 1.96


def _row(estimates: pd.DataFrame, spec: str) -> pd.Series:
    selected = estimates[estimates["spec"].eq(spec)]
    if len(selected) != 1:
        raise ValueError(f"dominance exhibit does not carry exactly one {spec!r} row")
    return selected.iloc[0]


def _finite(row: pd.Series, *columns: str) -> None:
    for column in columns:
        if not math.isfinite(float(row[column])):
            raise ValueError(f"{row['spec']!r} has a non-finite {column}")


def validated_ladder(estimates: pd.DataFrame) -> dict[str, pd.Series]:
    """Check the exhibit still supports the frame's economic sentence.

    Every guard here corresponds to a clause the slide says out loud. If one
    fails, the estimate has moved somewhere the prose has not followed, and the
    frame must be rewritten before its numbers are regenerated.
    """

    missing = {"spec", "coef", "se", "p", "n", "clusters"} - set(estimates.columns)
    if missing:
        raise ValueError(f"dominance exhibit missing columns: {sorted(missing)}")

    rungs = {spec: _row(estimates, spec) for spec in LADDER}
    for row in rungs.values():
        _finite(row, "coef", "se", "p")

    pooled = rungs[POOLED]
    if not (float(pooled["coef"]) < 0 and float(pooled["p"]) < 0.05):
        raise ValueError(
            "the pooled native advantage is no longer negative and significant; "
            "the frame's dissolving-association claim must be rewritten"
        )
    for spec in (SIZE, YEAR):
        if not (float(rungs[spec]["coef"]) < 0 and float(rungs[spec]["p"]) < 0.05):
            raise ValueError(
                f"{spec!r} no longer reproduces the pooled association; the frame "
                "claims the raw gap survives the observable controls"
            )
    fixed = rungs[FIXED_EFFECTS]
    if float(fixed["p"]) < 0.05:
        raise ValueError(
            "the pair-by-day estimate is now distinguishable from zero; the frame "
            "must be rewritten before its numbers are regenerated"
        )
    if not int(fixed["n"]) < int(pooled["n"]) / 10:
        raise ValueError(
            "the identifying design no longer costs an order of magnitude of "
            "sample; the frame's precision-loss statement is wrong"
        )
    if not float(fixed["se"]) > 4 * float(pooled["se"]):
        raise ValueError(
            "the identifying design no longer costs most of the precision; the "
            "frame's precision-loss statement is wrong"
        )

    windows = {}
    for days in WINDOW_DAYS:
        row = _row(estimates, WINDOW_SPEC.format(days=days))
        _finite(row, "coef", "se", "p", "mde_80", "identifying_cells")
        if float(row["p"]) < 0.05:
            raise ValueError(
                f"the {days}-day matched cell is now significant; the frame claims "
                "the non-result holds across every cell width"
            )
        windows[days] = row

    # The one-day window is the same partition as the pair-by-day design, so it
    # is the same estimate. That identity is what licenses reading the missing
    # identifying-cell count and minimum detectable effect off the window rung
    # rather than leaving the strictest column without either.
    daily = windows[1]
    for column in ("coef", "se", "n", "clusters"):
        if float(daily[column]) != float(fixed[column]):
            raise ValueError(
                "the one-day matched cell no longer reproduces the pair-by-day "
                f"design ({column}); the displayed cell count and minimum "
                "detectable effect would not belong to the displayed coefficient"
            )
    if abs(float(daily["mde_80"]) - MDE_MULTIPLIER * float(fixed["se"])) > 1e-12:
        raise ValueError("the recorded minimum detectable effect is not 80% power")
    if not float(daily["mde_80"]) > 4 * abs(float(pooled["coef"])):
        raise ValueError(
            "the identifying design can now detect an effect of the pooled size; "
            "the frame's what-we-could-have-seen sentence is wrong"
        )

    continuous = _row(estimates, CONTINUOUS)
    _finite(continuous, "coef", "se", "p")
    if int(continuous["n"]) != int(fixed["n"]):
        raise ValueError(
            "the continuous-outcome design no longer shares the binary design's "
            "sample; the two are not a functional-form comparison"
        )
    if float(continuous["p"]) < 0.05:
        raise ValueError(
            "the continuous outcome is now significant where the binary one is "
            "not; the frame must report that disagreement rather than agreement"
        )

    return {"rungs": rungs, "windows": windows, "continuous": continuous}


def render_dominance_ladder(validated: dict[str, object], output: Path) -> None:
    """Draw specification strictness and matched-cell width, both in points."""

    rungs = validated["rungs"]
    windows = validated["windows"]
    fixed = rungs[FIXED_EFFECTS]
    mde = 100 * float(windows[1]["mde_80"])

    # The slide gives this figure the full text width and a little under half the
    # text height, so the canvas is authored at that aspect ratio. A squarer
    # canvas would be scaled down to fit the height and land on the slide with
    # unreadable tick labels.
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        figure, axes = plt.subplots(
            1, 2, figsize=(7.4, 2.0), gridspec_kw={"width_ratios": (1.12, 1.0)}
        )
        try:
            strictness, width = axes

            positions = np.arange(len(LADDER))
            estimates = np.array([100 * float(rungs[spec]["coef"]) for spec in LADDER])
            intervals = np.array(
                [CRITICAL * 100 * float(rungs[spec]["se"]) for spec in LADDER]
            )
            # The detectable band belongs to the identifying column alone, so it is
            # drawn over that column only. Spread across the panel it would read as
            # a property of the pooled estimates, which are twenty times more precise.
            strictness.fill_between(
                [len(LADDER) - 1.48, len(LADDER) - 0.55],
                -mde,
                mde,
                color=PALETTE["other"],
                alpha=0.16,
                linewidth=0,
                zorder=0,
            )
            strictness.axhline(0, color="#111827", linestyle="--", linewidth=1)
            strictness.errorbar(
                positions[:-1],
                estimates[:-1],
                yerr=intervals[:-1],
                fmt="o",
                color=PALETTE["native"],
                ecolor="#64748B",
                capsize=3,
                markersize=7,
            )
            strictness.errorbar(
                positions[-1:],
                estimates[-1:],
                yerr=intervals[-1:],
                fmt="o",
                color=PALETTE["imported"],
                ecolor=PALETTE["imported"],
                capsize=3,
                markersize=8,
            )
            strictness.set_xticks(positions, [LADDER_LABELS[spec] for spec in LADDER])
            strictness.set_ylabel("Native routes dominated, points", fontsize=7.5)
            strictness.set_title(
                "A. Holding more of the trade fixed",
                loc="left",
                fontsize=9,
                fontweight="bold",
            )
            strictness.set_xlim(-0.45, len(LADDER) - 0.55)
            top = max(float(np.max(estimates + intervals)), mde) * 1.18
            bottom = min(float(np.min(estimates - intervals)), -mde) * 1.42
            strictness.set_ylim(bottom, top)
            for position, spec in zip(positions, LADDER, strict=True):
                strictness.annotate(
                    f"n = {int(rungs[spec]['n']):,}",
                    (position, 0.03),
                    xycoords=("data", "axes fraction"),
                    ha="center",
                    va="bottom",
                    fontsize=6.5,
                    color="#4B5563",
                )
            strictness.annotate(
                f"detectable here at 80% power: ±{mde:.1f} points",
                (len(LADDER) - 1.44, mde),
                xytext=(0, 5),
                textcoords="offset points",
                ha="left",
                fontsize=6.5,
                color="#4B5563",
            )
            strictness.annotate(
                f"{int(windows[1]['identifying_cells']):,} switching cells",
                (len(LADDER) - 1, 100 * float(fixed["coef"])),
                xytext=(-9, 0),
                textcoords="offset points",
                ha="right",
                va="center",
                fontsize=6.5,
                color=PALETTE["imported"],
            )

            days = np.array(WINDOW_DAYS, dtype=float)
            window_estimates = np.array(
                [100 * float(windows[day]["coef"]) for day in WINDOW_DAYS]
            )
            window_intervals = np.array(
                [CRITICAL * 100 * float(windows[day]["se"]) for day in WINDOW_DAYS]
            )
            width.axhline(0, color="#111827", linestyle="--", linewidth=1)
            width.fill_between(
                days,
                window_estimates - window_intervals,
                window_estimates + window_intervals,
                color=PALETTE["other"],
                alpha=0.18,
                linewidth=0,
            )
            width.plot(
                days,
                window_estimates,
                marker="o",
                color=PALETTE["native"],
                markersize=6,
                linewidth=1.8,
            )
            width.set_xscale("log")
            width.set_xticks(days, [f"{int(day)}d" for day in WINDOW_DAYS])
            width.minorticks_off()
            width.set_xlabel("Width of the matched cell", fontsize=7.5)
            width.set_ylabel("Native routes dominated, points", fontsize=7.5)
            width.set_ylim(
                float(np.min(window_estimates - window_intervals)) * 1.25,
                float(np.max(window_estimates + window_intervals)) * 1.25,
            )
            width.set_title(
                "B. Buying comparisons back", loc="left", fontsize=9, fontweight="bold"
            )
            for day, alignment in ((WINDOW_DAYS[0], "left"), (WINDOW_DAYS[-1], "right")):
                width.annotate(
                    f"n = {int(windows[day]['n']):,}",
                    (float(day), 0.02),
                    xycoords=("data", "axes fraction"),
                    ha=alignment,
                    va="bottom",
                    fontsize=6.5,
                    color="#4B5563",
                )

            for axis in axes:
                axis.grid(axis="y", color="#D1D5DB", linewidth=0.5)
                axis.spines[["top", "right"]].set_visible(False)
                axis.tick_params(labelsize=7.5)
            figure.tight_layout()
            figure.savefig(
                output,
                format="pdf",
                bbox_inches="tight",
                metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None},
            )
        finally:
            plt.close(figure)


def _signed_points(value: float, decimals: int = 1) -> str:
    points = 100 * value
    if abs(points) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}$ points"
    return f"${points:+.{decimals}f}$ points"


def _unsigned_points(value: float, decimals: int = 1) -> str:
    return f"${100 * value:.{decimals}f}$ points"


def _signed_bps(value: float) -> str:
    return f"${value:+.0f}$ bps"


def _unsigned_bps(value: float) -> str:
    return f"${value:.0f}$ bps"


def _integer(value: float) -> str:
    return f"{int(value):,}".replace(",", "{,}")


def render_dominance_ladder_deck_values(validated: dict[str, object]) -> str:
    """Render the slide's numeric cells; evidence identity stays in source."""

    rungs = validated["rungs"]
    windows = validated["windows"]
    continuous = validated["continuous"]
    pooled = rungs[POOLED]
    fixed = rungs[FIXED_EFFECTS]
    daily = windows[1]
    widest = windows[WINDOW_DAYS[-1]]
    lines = [
        "% Generated by scripts/figure/build_dominance_ladder.py; do not edit.",
        f"\\newcommand{{\\DomPooledCoef}}{{{_signed_points(float(pooled['coef']))}}}",
        f"\\newcommand{{\\DomPooledSE}}{{{_unsigned_points(float(pooled['se']), 2)}}}",
        f"\\newcommand{{\\DomPooledN}}{{{_integer(pooled['n'])}}}",
        f"\\newcommand{{\\DomFECoef}}{{{_signed_points(float(fixed['coef']))}}}",
        f"\\newcommand{{\\DomFESE}}{{{_unsigned_points(float(fixed['se']), 2)}}}",
        f"\\newcommand{{\\DomFEN}}{{{_integer(fixed['n'])}}}",
        f"\\newcommand{{\\DomFECells}}{{{_integer(daily['identifying_cells'])}}}",
        f"\\newcommand{{\\DomFEMDE}}{{{_unsigned_points(float(daily['mde_80']))}}}",
        f"\\newcommand{{\\DomGapCoef}}{{{_signed_bps(float(continuous['coef']))}}}",
        f"\\newcommand{{\\DomGapSE}}{{{_unsigned_bps(float(continuous['se']))}}}",
        f"\\newcommand{{\\DomWideDays}}{{{_integer(WINDOW_DAYS[-1])}}}",
        f"\\newcommand{{\\DomWideCoef}}{{{_signed_points(float(widest['coef']))}}}",
        f"\\newcommand{{\\DomWideSE}}{{{_unsigned_points(float(widest['se']), 2)}}}",
        f"\\newcommand{{\\DomWideN}}{{{_integer(widest['n'])}}}",
    ]
    return "\n".join(lines) + "\n"


def run(
    *,
    estimates_path: Path = ESTIMATES,
    figure_path: Path = FIGURE,
    values_path: Path = DECK_VALUES,
) -> int:
    provenance_path = require_certified_presentation_source(estimates_path)
    estimates, identity = load_current_jsonl(
        estimates_path, consumer="dominance control ladder"
    )
    validated = validated_ladder(estimates)

    publish_pdf(
        figure_path,
        renderer=lambda path: render_dominance_ladder(validated, path),
        input_path=estimates_path,
        input_identity=identity,
        code_sources=CODE_SOURCES,
        notes=(
            "Dominance-quality control ladder holding the traded pair and the day "
            "fixed; panel A walks specification strictness and panel B the width of "
            "the matched cell; shading is the 80 percent minimum detectable effect "
            "and bars are 95 percent pair-clustered intervals"
        ),
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    with atomic_output(values_path) as temporary:
        temporary.write_text(render_dominance_ladder_deck_values(validated), encoding="utf-8")
    stamp(
        values_path,
        code_sources=CODE_SOURCES,
        inputs=[estimates_path, provenance_path],
        rows=len(estimates),
        notes=(
            "Presentation macros for the dominance control ladder; evidence status "
            "and generation identity remain source-only."
        ),
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {figure_path}")
    print(f"wrote {values_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimates", type=Path, default=ESTIMATES)
    parser.add_argument("--figure", type=Path, default=FIGURE)
    parser.add_argument("--values", type=Path, default=DECK_VALUES)
    args = parser.parse_args()
    return run(
        estimates_path=args.estimates,
        figure_path=args.figure,
        values_path=args.values,
    )


if __name__ == "__main__":
    raise SystemExit(main())

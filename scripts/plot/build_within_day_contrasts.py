#!/usr/bin/env python3
"""Plot the within-day intermediary-role estimates with their intervals.

The figure exists to hold the project's reporting rule visible: a contrast the
cross-section cannot separate from zero is drawn at the same size, in the same
units and on the same axis as one it can. A reader who sees only the separable
contrasts has been shown a filtered sample of the evidence.

Two panels, both conditional on the currency's own trade demand and inside a day.

  A  Class premiums against the residual unclassified bucket, over every
     endpoint-supported currency-day. These say how much of the day's
     intermediary activity an asset class takes beyond what its own trade demand
     implies.
  B  The native asset against a stablecoin, on the five named candidates and on
     all classified currencies. Both rows appear because the samples put
     different amounts of the day's share mass behind the same dummy, so their
     magnitudes are not comparable and one does not stand for the other.
  C  Inside the stablecoin class: the backing regimes against a fiat-reserve
     claim, and USDT against USDC.

Reads   output/exhibits/excess_use_date_fe_ladder.jsonl
Writes  output/figures/within_day_role_contrasts.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import pandas as pd

from ddvc.figure_outputs import PALETTE, load_current_jsonl, publish_pdf
from ddvc.paths import OUTPUT_DIR, REPO_ROOT

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ESTIMATES = OUTPUT_DIR / "exhibits" / "excess_use_date_fe_ladder.jsonl"
FIGURE = OUTPUT_DIR / "figures" / "within_day_role_contrasts.pdf"
CODE_SOURCES = ["scripts/plot/build_within_day_contrasts.py"]

ALL = "all_endpoint_supported"
L3 = "L3 + date FE + own demand share"
CUT = "date FE + own demand share, stable base"
BACKING = "backing regime, date FE + own demand share"
TOKENS = "USDT versus USDC, date FE + own demand share"

# (label, spec, sample, term, palette key). Order is the drawing order from the
# top of each panel downwards.
PANEL_A = (
    ("Native", L3, ALL, "native", "native"),
    ("Stablecoin", L3, ALL, "stable", "stable"),
    ("Liquid-staking", L3, ALL, "staked_native", "staked_native"),
    ("Imported", L3, ALL, "imported", "imported"),
)
PANEL_B = (
    ("Five named vehicles", CUT, "five_named_candidates", "native", "native"),
    ("All classified", CUT, "classified_types_only", "native", "native"),
)
PANEL_C = (
    ("On-chain vs fiat reserve", BACKING, "stable_class_only", "backing_on_chain_collateralized", "stable"),
    ("Synthetic vs fiat reserve", BACKING, "stable_class_only", "backing_synthetic", "stable"),
    ("RWA-mixed vs fiat reserve", BACKING, "stable_class_only", "backing_mixed_including_rwa", "stable"),
    ("USDT vs USDC", TOKENS, "usdc_usdt_only", "usdt", "stable"),
)


def _row(frame: pd.DataFrame, spec: str, sample: str, term: str) -> pd.Series:
    selected = frame[
        frame["spec"].eq(spec) & frame["sample"].eq(sample) & frame["term"].eq(term)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"ladder exhibit requires one {spec}/{sample}/{term} row; found {len(selected)}"
        )
    return selected.iloc[0]


def _draw_panel(axis, frame: pd.DataFrame, rows, *, title: str) -> None:
    positions = list(range(len(rows)))[::-1]
    labels = []
    for position, (label, spec, sample, term, key) in zip(positions, rows):
        record = _row(frame, spec, sample, term)
        beta = float(record["beta"])
        lower = float(record["ci_lower"])
        upper = float(record["ci_upper"])
        separable = lower > 0 or upper < 0
        colour = PALETTE[key]
        axis.plot(
            [lower, upper],
            [position, position],
            color=colour,
            linewidth=1.6,
            solid_capstyle="butt",
            zorder=2,
        )
        # A filled marker means the interval clears zero and an open one means it
        # does not. The row is drawn either way, at the same weight.
        axis.plot(
            [beta],
            [position],
            marker="o",
            markersize=5.5,
            color=colour,
            markerfacecolor=colour if separable else "white",
            markeredgewidth=1.4,
            zorder=3,
        )
        labels.append(label)
    axis.axvline(0.0, color="#6B7280", linewidth=0.9, linestyle="--", zorder=1)
    axis.set_yticks(positions)
    axis.set_yticklabels(labels, fontsize=8)
    axis.set_ylim(-0.7, len(rows) - 0.3)
    axis.set_title(title, fontsize=9, loc="left")
    axis.tick_params(axis="x", labelsize=8)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(axis="x", color="#E5E7EB", linewidth=0.6)
    axis.set_axisbelow(True)


def render(frame: pd.DataFrame, output: Path) -> None:
    # Three axes rather than one, because the candidate-set contrast is an order of
    # magnitude larger than the others: sharing an axis would compress the
    # stablecoin-class rows into the zero line and hide the very intervals this
    # figure exists to show.
    figure, axes = plt.subplots(
        1, 3, figsize=(10.5, 2.9), gridspec_kw={"width_ratios": [1.0, 0.85, 1.15]}
    )
    _draw_panel(
        axes[0],
        frame,
        PANEL_A,
        title="A. Class premium over residual bucket",
    )
    _draw_panel(
        axes[1],
        frame,
        PANEL_B,
        title="B. Native against a stablecoin",
    )
    _draw_panel(
        axes[2],
        frame,
        PANEL_C,
        title="C. Inside the stablecoin class",
    )
    for axis in axes:
        axis.set_xlabel("Percentage points", fontsize=8)
    figure.tight_layout()
    figure.savefig(output, format="pdf", bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimates", type=Path, default=ESTIMATES)
    parser.add_argument("--figure", type=Path, default=FIGURE)
    arguments = parser.parse_args()

    frame, identity = load_current_jsonl(
        arguments.estimates, consumer="within-day intermediary-role contrasts"
    )
    publish_pdf(
        arguments.figure,
        renderer=lambda path: render(frame, path),
        input_path=arguments.estimates,
        input_identity=identity,
        code_sources=CODE_SOURCES,
        notes=(
            "within-day intermediary-role estimates with 95 percent intervals; open "
            "markers denote intervals covering zero and are drawn at the same weight "
            "as separable ones; all rows condition on the currency's own route-endpoint "
            "share inside a date fixed effect"
        ),
        script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
    )
    print(f"wrote {arguments.figure.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

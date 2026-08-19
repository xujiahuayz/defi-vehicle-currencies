#!/usr/bin/env python3
"""Render the monthly vehicle-currency contest as a short empirical film.

The moving lines are route-count shares among native and stable vehicle
currencies in exact two-atomic-trade routes.  The closing panel reuses the
registered 2024-to-2026 ordered-ultimate-pair decomposition; it is not inferred
from the animation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from matplotlib import animation
from matplotlib.ticker import PercentFormatter

from ddvc.paths import DATA_DIR, OUTPUT_DIR


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


CHOICES_INPUT = DATA_DIR / "processed/endpoint_candidate_choices.parquet"
DECOMPOSITION_INPUT = (
    OUTPUT_DIR / "exhibits/vehicle_transition_pair_decomposition.jsonl"
)
VIDEO_OUTPUT = OUTPUT_DIR / "figures/vehicle_dominance_timelapse.mp4"
POSTER_PDF_OUTPUT = OUTPUT_DIR / "figures/vehicle_dominance_timelapse_poster.pdf"
POSTER_PNG_OUTPUT = OUTPUT_DIR / "figures/vehicle_dominance_timelapse_poster.png"

START = pd.Timestamp("2024-01-01")
END = pd.Timestamp("2026-06-30")
SYMBOLS = ("WETH", "USDC", "USDT", "DAI")
COLORS = {
    "WETH": "#1F4E79",
    "USDC": "#238B78",
    "USDT": "#4F8A3C",
    "DAI": "#D97706",
}
BACKGROUND = "#FAFAF8"
INK = "#17191D"
MUTED = "#626974"
GRID = "#D9DDE3"
ACCENT = "#7C3AED"


def monthly_vehicle_shares(frame: pd.DataFrame) -> pd.DataFrame:
    """Return complete monthly shares for the four named vehicle currencies.

    The denominator includes every route classified as native or stable, so the
    named shares need not sum to one when smaller stablecoins are present.
    """

    required = {
        "date",
        "candidate_symbol",
        "candidate_type",
        "route_count",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"vehicle choices are missing {', '.join(missing)}")
    data = frame.loc[:, list(required)].copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data["route_count"] = pd.to_numeric(data["route_count"], errors="raise")
    data = data.loc[
        data["date"].between(START, END)
        & data["candidate_type"].isin(("native", "stable"))
    ].copy()
    if data.empty or data["route_count"].lt(0).any():
        raise ValueError("vehicle choices lack nonnegative 2024-to-2026 route counts")
    data["month"] = data["date"].dt.to_period("M").dt.to_timestamp()
    monthly = data.groupby(["month", "candidate_symbol"], observed=True)[
        "route_count"
    ].sum()
    denominator = monthly.groupby("month").sum()
    if denominator.le(0).any():
        raise ValueError("a vehicle-share month has no native-or-stable route mass")
    named = monthly.unstack(fill_value=0).reindex(columns=SYMBOLS, fill_value=0)
    named = named.reindex(pd.date_range(START, END, freq="MS"), fill_value=0)
    denominator = denominator.reindex(named.index)
    if denominator.isna().any():
        raise ValueError("vehicle-share timeline has a missing calendar month")
    shares = named.div(denominator, axis=0)
    shares.index.name = "month"
    shares["stable_share"] = (
        data.loc[data["candidate_type"].eq("stable")]
        .groupby("month", observed=True)["route_count"]
        .sum()
        .reindex(shares.index, fill_value=0)
        .div(denominator)
    )
    if shares.lt(0).any().any() or shares.gt(1 + 1e-12).any().any():
        raise ValueError("vehicle-share timeline contains a share outside zero and one")
    return shares


def select_endpoint_decomposition(records: pd.DataFrame) -> pd.Series:
    """Select the registered pooled route-count accounting identity."""

    required = {
        "metric",
        "source_column",
        "reporting_scope",
        "baseline_year",
        "comparison_year",
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "within_common",
        "common_pair_reweighting",
        "common_support_mass",
        "exclusive_pair_contribution",
        "common_month_days",
    }
    missing = sorted(required - set(records.columns))
    if missing:
        raise ValueError(f"vehicle decomposition is missing {', '.join(missing)}")
    selected = records.loc[
        records["metric"].eq("count_share")
        & records["source_column"].eq("route_count")
        & records["reporting_scope"].eq("pooled")
        & pd.to_numeric(records["baseline_year"], errors="coerce").eq(2024)
        & pd.to_numeric(records["comparison_year"], errors="coerce").eq(2026)
    ]
    if len(selected) != 1:
        raise ValueError("vehicle decomposition lacks one pooled route-count identity")
    row = selected.iloc[0].copy()
    components = (
        "within_common",
        "common_pair_reweighting",
        "common_support_mass",
        "exclusive_pair_contribution",
    )
    values = pd.to_numeric(row[list(components)], errors="raise")
    total = float(pd.to_numeric(row["total_change"], errors="raise"))
    if not np.isclose(float(values.sum()), total, atol=1e-10, rtol=0):
        raise ValueError("vehicle decomposition components do not sum to the total")
    return row


def load_inputs(
    choices_path: Path = CHOICES_INPUT,
    decomposition_path: Path = DECOMPOSITION_INPUT,
) -> tuple[pd.DataFrame, pd.Series]:
    """Load only the processed columns and registered result needed to render."""

    choices = pd.read_parquet(
        choices_path,
        columns=["date", "candidate_symbol", "candidate_type", "route_count"],
    )
    records = pd.read_json(decomposition_path, orient="records", lines=True)
    return monthly_vehicle_shares(choices), select_endpoint_decomposition(records)


def interpolated_timeline(monthly: pd.DataFrame, *, frames: int) -> pd.DataFrame:
    """Interpolate monthly observations onto a smooth, equally spaced film clock."""

    if frames < 2:
        raise ValueError("the timelapse requires at least two frames")
    monthly_days = (monthly.index - monthly.index[0]).days.to_numpy(dtype=float)
    film_days = np.linspace(monthly_days[0], monthly_days[-1], frames)
    values = {
        column: np.interp(film_days, monthly_days, monthly[column].to_numpy(dtype=float))
        for column in (*SYMBOLS, "stable_share")
    }
    timeline = pd.DataFrame(values)
    timeline["date"] = monthly.index[0] + pd.to_timedelta(film_days, unit="D")
    return timeline


def _percentage_point(value: float) -> str:
    return f"{value * 100:+.1f} pp".replace("+0.0", "0.0")


def spread_label_positions(
    values: dict[str, float], *, minimum_gap: float = 0.055
) -> dict[str, float]:
    """Separate current-value labels while retaining their vertical ordering."""

    ordered = sorted(values, key=values.get)
    positions = {symbol: float(values[symbol]) for symbol in ordered}
    for index in range(1, len(ordered)):
        lower, symbol = ordered[index - 1], ordered[index]
        positions[symbol] = max(positions[symbol], positions[lower] + minimum_gap)
    if ordered and positions[ordered[-1]] > 0.89:
        shift = positions[ordered[-1]] - 0.89
        positions = {symbol: position - shift for symbol, position in positions.items()}
    return positions


def _draw_frame(
    figure: plt.Figure,
    timeline: pd.DataFrame,
    decomposition: pd.Series,
    frame_index: int,
) -> None:
    """Draw one frame; shared by the MP4 writer and static poster."""

    figure.clear()
    figure.patch.set_facecolor(BACKGROUND)
    grid = figure.add_gridspec(
        1,
        2,
        left=0.055,
        right=0.965,
        bottom=0.18,
        top=0.79,
        width_ratios=(1.78, 1.0),
        wspace=0.18,
    )
    axis = figure.add_subplot(grid[0, 0])
    detail = figure.add_subplot(grid[0, 1])
    progress = frame_index / max(1, len(timeline) - 1)
    current = timeline.iloc[frame_index]
    history = timeline.iloc[: frame_index + 1]

    figure.text(
        0.055,
        0.92,
        "Vehicle leadership shifts across DeFi ultimate pairs",
        fontsize=27,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
    )
    figure.text(
        0.055,
        0.855,
        "Monthly route-count shares among native and stable vehicle currencies",
        fontsize=13.5,
        color=MUTED,
        ha="left",
        va="top",
    )
    figure.text(
        0.948,
        0.87,
        pd.Timestamp(current["date"]).strftime("%B %Y"),
        fontsize=16,
        fontweight="bold",
        color=ACCENT,
        ha="right",
        va="center",
    )

    full_start = pd.Timestamp(timeline.iloc[0]["date"])
    full_end = pd.Timestamp(timeline.iloc[-1]["date"])
    current_values = {symbol: float(current[symbol]) for symbol in SYMBOLS}
    label_positions = spread_label_positions(current_values)
    for symbol in SYMBOLS:
        axis.plot(
            history["date"],
            history[symbol],
            color=COLORS[symbol],
            linewidth=3.4 if symbol in ("WETH", "USDC", "USDT") else 2.5,
            solid_capstyle="round",
            zorder=3,
        )
        value = current_values[symbol]
        axis.scatter(
            [current["date"]],
            [value],
            s=64,
            color=COLORS[symbol],
            edgecolor=BACKGROUND,
            linewidth=1.3,
            zorder=4,
        )
        label_x = pd.Timestamp(current["date"]) + pd.Timedelta(days=18)
        axis.annotate(
            f"{symbol}  {value:.1%}",
            (current["date"], value),
            xytext=(label_x, label_positions[symbol]),
            textcoords="data",
            ha="left",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=COLORS[symbol],
            clip_on=False,
            arrowprops={
                "arrowstyle": "-",
                "color": COLORS[symbol],
                "linewidth": 0.8,
                "alpha": 0.75,
            },
        )
    axis.set_xlim(full_start, full_end + pd.Timedelta(days=105))
    axis.set_ylim(-0.01, 0.96)
    axis.set_yticks(np.arange(0, 1.0, 0.2))
    axis.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    axis.set_xticks(
        [
            pd.Timestamp("2024-01-01"),
            pd.Timestamp("2025-01-01"),
            pd.Timestamp("2026-01-01"),
        ],
        ["2024", "2025", "2026"],
    )
    axis.grid(axis="y", color=GRID, linewidth=0.8, alpha=0.9)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.spines["bottom"].set_color(GRID)
    axis.tick_params(axis="both", length=0, labelcolor=MUTED, labelsize=10)
    axis.set_title(
        "Which currency intermediates the route?",
        loc="left",
        fontsize=15,
        fontweight="bold",
        color=INK,
        pad=12,
    )

    detail.set_facecolor("#F1F3F6")
    detail.set_xlim(-0.01, 0.30)
    detail.set_ylim(-0.7, 4.9)
    detail.spines[:].set_visible(False)
    detail.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    start_share = float(timeline.iloc[0]["stable_share"])
    stable_share = float(current["stable_share"])
    detail.text(
        0.02,
        4.55,
        "Stablecoin route share",
        fontsize=14,
        fontweight="bold",
        color=INK,
        ha="left",
    )
    detail.text(
        0.02,
        3.95,
        f"{stable_share:.1%}",
        fontsize=31,
        fontweight="bold",
        color="#238B78",
        ha="left",
    )
    detail.text(
        0.02,
        3.55,
        f"{_percentage_point(stable_share - start_share)} since January 2024",
        fontsize=11.5,
        color=MUTED,
        ha="left",
    )

    reveal = float(np.clip((progress - 0.70) / 0.18, 0, 1))
    detail.text(
        0.02,
        2.98,
        "Sources of the 2024–2026 stablecoin gain",
        fontsize=12.3,
        fontweight="bold",
        color=INK,
        alpha=reveal,
        ha="left",
    )
    labels = (
        "Within continuing ultimate pairs",
        "Changing continuing ultimate-pair weights",
        "Continuing ultimate-pair mass",
        "Ultimate-pair entry and exit",
    )
    fields = (
        "within_common",
        "common_pair_reweighting",
        "common_support_mass",
        "exclusive_pair_contribution",
    )
    y_positions = (2.35, 1.65, 0.95, 0.25)
    for label, field, y in zip(labels, fields, y_positions, strict=True):
        value = float(decomposition[field])
        color = "#238B78" if value >= 0 else "#B33A53"
        detail.text(0.02, y + 0.24, label, fontsize=9.6, color=MUTED, alpha=reveal)
        detail.barh(
            y,
            abs(value) * reveal,
            left=0.02,
            height=0.19,
            color=color,
            alpha=0.88 * reveal,
        )
        detail.text(
            0.285,
            y,
            _percentage_point(value),
            fontsize=11,
            fontweight="bold",
            color=color,
            alpha=reveal,
            ha="right",
            va="center",
        )
    detail.text(
        0.02,
        -0.42,
        "Ultimate-pair turnover is the largest component.",
        fontsize=11.5,
        fontweight="bold",
        color=ACCENT,
        alpha=reveal,
        ha="left",
    )

    figure.text(
        0.055,
        0.105,
        "Exact two-atomic-trade routes. Monthly shares use all observed ordered ultimate pairs; smaller stablecoins remain in the denominator.",
        fontsize=9.4,
        color=MUTED,
        ha="left",
    )
    figure.text(
        0.055,
        0.072,
        "The closing decomposition compares the same 181 calendar days in January–June 2024 and 2026 and is descriptive.",
        fontsize=9.4,
        color=MUTED,
        ha="left",
    )
    figure.add_artist(
        plt.Line2D(
            [0.055, 0.055 + 0.89 * progress],
            [0.035, 0.035],
            transform=figure.transFigure,
            color=ACCENT,
            linewidth=3.0,
            solid_capstyle="round",
        )
    )
    figure.add_artist(
        plt.Line2D(
            [0.055, 0.945],
            [0.035, 0.035],
            transform=figure.transFigure,
            color=GRID,
            linewidth=1.0,
            zorder=0,
        )
    )


def render_outputs(
    monthly: pd.DataFrame,
    decomposition: pd.Series,
    *,
    video_output: Path = VIDEO_OUTPUT,
    poster_pdf_output: Path = POSTER_PDF_OUTPUT,
    poster_png_output: Path = POSTER_PNG_OUTPUT,
    seconds: float = 11.0,
    fps: int = 24,
    poster_only: bool = False,
) -> None:
    """Render a 16:9 H.264 film and a final-state PDF/PNG poster."""

    if seconds <= 0 or fps <= 0:
        raise ValueError("seconds and fps must be positive")
    frame_count = max(2, int(round(seconds * fps)))
    timeline = interpolated_timeline(monthly, frames=frame_count)
    for output in (video_output, poster_pdf_output, poster_png_output):
        output.parent.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "pdf.fonttype": 42,
            "axes.labelcolor": INK,
            "text.color": INK,
        }
    ):
        figure = plt.figure(figsize=(16, 9), dpi=120)
        try:
            _draw_frame(figure, timeline, decomposition, len(timeline) - 1)
            with tempfile.TemporaryDirectory(
                prefix="vehicle-timelapse-", dir=poster_pdf_output.parent
            ) as temporary:
                temporary_root = Path(temporary)
                pdf = temporary_root / poster_pdf_output.name
                png = temporary_root / poster_png_output.name
                figure.savefig(
                    pdf,
                    format="pdf",
                    facecolor=BACKGROUND,
                    metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None},
                )
                figure.savefig(
                    png,
                    format="png",
                    facecolor=BACKGROUND,
                    dpi=120,
                )
                pdf.replace(poster_pdf_output)
                png.replace(poster_png_output)
            if poster_only:
                return
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                raise FileNotFoundError("ffmpeg is required to render the MP4")
            movie = animation.FuncAnimation(
                figure,
                lambda index: _draw_frame(figure, timeline, decomposition, index),
                frames=len(timeline),
                interval=1000 / fps,
                repeat=False,
                cache_frame_data=False,
            )
            writer = animation.FFMpegWriter(
                fps=fps,
                codec="libx264",
                metadata={
                    "title": "Vehicle leadership shifts across DeFi ultimate pairs",
                    "artist": "ddvc",
                },
                extra_args=(
                    "-crf",
                    "21",
                    "-preset",
                    "medium",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                ),
            )
            with tempfile.TemporaryDirectory(
                prefix="vehicle-timelapse-", dir=video_output.parent
            ) as temporary:
                movie_path = Path(temporary) / video_output.name
                movie.save(movie_path, writer=writer, dpi=120)
                movie_path.replace(video_output)
        finally:
            plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--decomposition", type=Path, default=DECOMPOSITION_INPUT)
    parser.add_argument("--video", type=Path, default=VIDEO_OUTPUT)
    parser.add_argument("--poster-pdf", type=Path, default=POSTER_PDF_OUTPUT)
    parser.add_argument("--poster-png", type=Path, default=POSTER_PNG_OUTPUT)
    parser.add_argument("--seconds", type=float, default=11.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--poster-only", action="store_true")
    arguments = parser.parse_args()
    monthly, decomposition = load_inputs(arguments.choices, arguments.decomposition)
    render_outputs(
        monthly,
        decomposition,
        video_output=arguments.video,
        poster_pdf_output=arguments.poster_pdf,
        poster_png_output=arguments.poster_png,
        seconds=arguments.seconds,
        fps=arguments.fps,
        poster_only=arguments.poster_only,
    )
    outputs = [arguments.poster_pdf, arguments.poster_png]
    if not arguments.poster_only:
        outputs.insert(0, arguments.video)
    print("wrote " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render vehicle-currency leadership as a genuinely time-dependent film.

Each frame is a monthly cross-section rather than a partial line chart.  The
horizontal position is route-count share, the vertical position is supported-
value share, and bubble area records the breadth of active ordered ultimate
pairs.  Six-month fading trails reveal recent momentum without allowing the
last frame to reproduce the full history.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd
from matplotlib import animation
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgba
from matplotlib.ticker import PercentFormatter

from ddvc.paths import DATA_DIR, OUTPUT_DIR


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


CHOICES_INPUT = DATA_DIR / "processed/endpoint_candidate_choices.parquet"
VIDEO_OUTPUT = OUTPUT_DIR / "figures/vehicle_dominance_timelapse.mp4"
POSTER_PDF_OUTPUT = OUTPUT_DIR / "figures/vehicle_dominance_timelapse_poster.pdf"
POSTER_PNG_OUTPUT = OUTPUT_DIR / "figures/vehicle_dominance_timelapse_poster.png"

START = pd.Timestamp("2020-06-01")
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
TRAIL_DAYS = 183


def _monthly_state_from_aggregates(aggregates: pd.DataFrame) -> pd.DataFrame:
    """Convert candidate-month totals into a complete wide monthly state."""

    required = {
        "month",
        "candidate_symbol",
        "candidate_type",
        "route_count",
        "value_usd",
        "active_pairs",
    }
    missing = sorted(required - set(aggregates.columns))
    if missing:
        raise ValueError(f"monthly vehicle aggregates are missing {', '.join(missing)}")
    data = aggregates.loc[:, list(required)].copy()
    data["month"] = pd.to_datetime(data["month"], errors="raise").dt.to_period("M").dt.to_timestamp()
    for column in ("route_count", "value_usd", "active_pairs"):
        data[column] = pd.to_numeric(data[column], errors="raise").fillna(0.0)
        if data[column].lt(0).any():
            raise ValueError(f"monthly vehicle aggregates contain negative {column}")
    data = data.loc[
        data["month"].between(START, END)
        & data["candidate_type"].isin(("native", "stable"))
    ].copy()
    if data.empty:
        raise ValueError("vehicle choices lack native-or-stable observations")
    data = (
        data.groupby(
            ["month", "candidate_symbol", "candidate_type"],
            observed=True,
            dropna=False,
            as_index=False,
        )[["route_count", "value_usd", "active_pairs"]]
        .sum()
    )
    months = pd.date_range(START, END, freq="MS")
    observed_months = pd.DatetimeIndex(data["month"].drop_duplicates()).sort_values()
    if not observed_months.equals(months):
        missing_months = months.difference(observed_months)
        raise ValueError(
            "vehicle timeline has missing calendar months"
            + (f": {missing_months[0]:%Y-%m}" if len(missing_months) else "")
        )

    totals = data.groupby("month", observed=True)[["route_count", "value_usd"]].sum()
    if totals["route_count"].le(0).any() or totals["value_usd"].le(0).any():
        raise ValueError("a vehicle month has no count or supported-value mass")
    state = pd.DataFrame(index=months)
    state.index.name = "month"
    for symbol in SYMBOLS:
        rows = (
            data.loc[data["candidate_symbol"].eq(symbol)]
            .groupby("month", observed=True)[["route_count", "value_usd", "active_pairs"]]
            .sum()
            .reindex(months, fill_value=0.0)
        )
        state[f"{symbol}_count_share"] = rows["route_count"].div(totals["route_count"])
        state[f"{symbol}_value_share"] = rows["value_usd"].div(totals["value_usd"])
        state[f"{symbol}_active_pairs"] = rows["active_pairs"]
        state[f"{symbol}_route_count"] = rows["route_count"]

    stable = (
        data.loc[data["candidate_type"].eq("stable")]
        .groupby("month", observed=True)[["route_count", "value_usd"]]
        .sum()
        .reindex(months, fill_value=0.0)
    )
    state["stable_count_share"] = stable["route_count"].div(totals["route_count"])
    state["stable_value_share"] = stable["value_usd"].div(totals["value_usd"])
    state["total_route_count"] = totals["route_count"]
    share_columns = [column for column in state if column.endswith("_share")]
    if state[share_columns].lt(0).any().any() or state[share_columns].gt(1 + 1e-12).any().any():
        raise ValueError("vehicle timeline contains a share outside zero and one")
    return state


def monthly_vehicle_state(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate route observations into the state used by the film."""

    required = {
        "date",
        "src",
        "tgt",
        "candidate_symbol",
        "candidate_type",
        "route_count",
        "within_20pct_value_usd",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"vehicle choices are missing {', '.join(missing)}")
    data = frame.loc[:, list(required)].copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data["route_count"] = pd.to_numeric(data["route_count"], errors="raise")
    data["within_20pct_value_usd"] = pd.to_numeric(
        data["within_20pct_value_usd"], errors="raise"
    ).fillna(0.0)
    data = data.loc[
        data["date"].between(START, END)
        & data["candidate_type"].isin(("native", "stable"))
    ].copy()
    if data.empty:
        raise ValueError("vehicle choices lack native-or-stable observations")
    data["month"] = data["date"].dt.to_period("M").dt.to_timestamp()
    data["pair_key"] = list(zip(data["src"], data["tgt"], strict=True))
    aggregates = (
        data.groupby(
            ["month", "candidate_symbol", "candidate_type"],
            observed=True,
            dropna=False,
        )
        .agg(
            route_count=("route_count", "sum"),
            value_usd=("within_20pct_value_usd", "sum"),
            active_pairs=("pair_key", "nunique"),
        )
        .reset_index()
    )
    return _monthly_state_from_aggregates(aggregates)


def load_input(choices_path: Path = CHOICES_INPUT) -> pd.DataFrame:
    """Read candidate-month aggregates without materialising the 15m-row panel."""

    query = """
        SELECT
            CAST(date_trunc('month', date) AS DATE) AS month,
            candidate_symbol,
            candidate_type,
            SUM(route_count)::DOUBLE AS route_count,
            SUM(COALESCE(within_20pct_value_usd, 0))::DOUBLE AS value_usd,
            COUNT(DISTINCT (src, tgt))::DOUBLE AS active_pairs
        FROM read_parquet(?)
        WHERE date >= ?
          AND date <= ?
          AND candidate_type IN ('native', 'stable')
        GROUP BY 1, 2, 3
    """
    aggregates = duckdb.execute(
        query,
        [str(choices_path), START.date(), END.date()],
    ).fetchdf()
    return _monthly_state_from_aggregates(aggregates)


def interpolated_timeline(monthly: pd.DataFrame, *, frames: int) -> pd.DataFrame:
    """Interpolate monthly states onto a smooth, equally spaced film clock."""

    if frames < 2:
        raise ValueError("the timelapse requires at least two frames")
    monthly_days = (monthly.index - monthly.index[0]).days.to_numpy(dtype=float)
    film_days = np.linspace(monthly_days[0], monthly_days[-1], frames)
    timeline = pd.DataFrame(
        {
            column: np.interp(
                film_days,
                monthly_days,
                monthly[column].to_numpy(dtype=float),
            )
            for column in monthly.columns
        }
    )
    timeline["date"] = monthly.index[0] + pd.to_timedelta(film_days, unit="D")
    return timeline


def spread_label_positions(
    values: dict[str, float], *, minimum_gap: float = 0.055
) -> dict[str, float]:
    """Separate bubble labels while retaining their vertical ordering."""

    ordered = sorted(values, key=values.get)
    positions = {symbol: float(values[symbol]) for symbol in ordered}
    for index in range(1, len(ordered)):
        lower, symbol = ordered[index - 1], ordered[index]
        positions[symbol] = max(positions[symbol], positions[lower] + minimum_gap)
    if ordered and positions[ordered[-1]] > 0.86:
        shift = positions[ordered[-1]] - 0.86
        positions = {symbol: position - shift for symbol, position in positions.items()}
    if ordered and positions[ordered[0]] < 0.035:
        shift = 0.035 - positions[ordered[0]]
        positions = {symbol: position + shift for symbol, position in positions.items()}
    return positions


def bubble_area(active_pairs: float, *, maximum: float) -> float:
    """Map ultimate-pair breadth to a visible but bounded bubble area."""

    if active_pairs < 0 or maximum <= 0:
        raise ValueError("bubble breadth must be nonnegative with a positive maximum")
    scaled = np.log1p(active_pairs) / np.log1p(maximum)
    return float(160 + 1500 * scaled**2)


def _add_trail(
    axis: plt.Axes,
    history: pd.DataFrame,
    symbol: str,
) -> None:
    """Draw a fading recent path for one currency."""

    points = history[
        [f"{symbol}_count_share", f"{symbol}_value_share"]
    ].to_numpy(dtype=float)
    if len(points) < 2:
        return
    segments = np.stack([points[:-1], points[1:]], axis=1)
    alphas = np.linspace(0.04, 0.52, len(segments))
    colors = [to_rgba(COLORS[symbol], float(alpha)) for alpha in alphas]
    axis.add_collection(
        LineCollection(
            segments,
            colors=colors,
            linewidths=np.linspace(1.0, 2.7, len(segments)),
            capstyle="round",
            zorder=2,
        )
    )


def _draw_frame(
    figure: plt.Figure,
    timeline: pd.DataFrame,
    frame_index: int,
) -> None:
    """Draw one cross-sectional frame for the film or poster."""

    figure.clear()
    figure.patch.set_facecolor(BACKGROUND)
    grid = figure.add_gridspec(
        1,
        2,
        left=0.065,
        right=0.955,
        bottom=0.17,
        top=0.79,
        width_ratios=(1.62, 0.92),
        wspace=0.16,
    )
    axis = figure.add_subplot(grid[0, 0])
    detail = figure.add_subplot(grid[0, 1])
    current = timeline.iloc[frame_index]
    current_date = pd.Timestamp(current["date"])
    history = timeline.iloc[: frame_index + 1]
    history = history.loc[
        pd.to_datetime(history["date"]).ge(current_date - pd.Timedelta(days=TRAIL_DAYS))
    ]
    progress = frame_index / max(1, len(timeline) - 1)

    figure.text(
        0.065,
        0.925,
        "Vehicle currencies vie for frequency, value, and network reach",
        fontsize=25.5,
        fontweight="bold",
        color=INK,
        ha="left",
        va="top",
    )
    figure.text(
        0.065,
        0.858,
        "Each frame is one month; no frame contains the full path",
        fontsize=13.2,
        color=MUTED,
        ha="left",
        va="top",
    )
    figure.text(
        0.94,
        0.865,
        current_date.strftime("%B %Y"),
        fontsize=17,
        fontweight="bold",
        color=ACCENT,
        ha="right",
        va="center",
    )

    axis.set_xlim(0, 0.90)
    axis.set_ylim(0, 0.90)
    axis.plot([0, 0.90], [0, 0.90], color=GRID, linestyle=(0, (4, 5)), linewidth=1.2)
    axis.text(
        0.885,
        0.86,
        "dominant in both",
        fontsize=9.5,
        fontweight="bold",
        color=MUTED,
        ha="right",
    )
    axis.text(
        0.885,
        0.04,
        "frequent, lower dollar weight",
        fontsize=9.3,
        color=MUTED,
        ha="right",
    )
    axis.text(
        0.015,
        0.86,
        "dollar-heavy, less frequent",
        fontsize=9.3,
        color=MUTED,
        ha="left",
    )
    axis.grid(color=GRID, linewidth=0.75, alpha=0.82)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["bottom", "left"]].set_color(GRID)
    axis.tick_params(axis="both", length=0, labelcolor=MUTED, labelsize=9.5)
    axis.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    axis.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    axis.set_xlabel("Share of intermediary routes", fontsize=11.5, color=INK, labelpad=10)
    axis.set_ylabel(
        "Share of supported intermediary value",
        fontsize=11.5,
        color=INK,
        labelpad=10,
    )
    axis.set_title(
        "The current vehicle-currency field",
        loc="left",
        fontsize=15,
        fontweight="bold",
        color=INK,
        pad=13,
    )

    maximum_pairs = max(
        float(timeline[f"{symbol}_active_pairs"].max()) for symbol in SYMBOLS
    )
    y_values = {
        symbol: float(current[f"{symbol}_value_share"]) for symbol in SYMBOLS
    }
    label_positions = spread_label_positions(y_values)
    for symbol in SYMBOLS:
        _add_trail(axis, history, symbol)
        x_value = float(current[f"{symbol}_count_share"])
        y_value = float(current[f"{symbol}_value_share"])
        size = bubble_area(
            float(current[f"{symbol}_active_pairs"]), maximum=maximum_pairs
        )
        axis.scatter(
            [x_value],
            [y_value],
            s=size,
            facecolor=to_rgba(COLORS[symbol], 0.78),
            edgecolor=BACKGROUND,
            linewidth=2.2,
            zorder=4,
        )
        label_x = x_value + 0.025 if x_value < 0.72 else x_value - 0.025
        horizontal = "left" if x_value < 0.72 else "right"
        axis.annotate(
            symbol,
            (x_value, y_value),
            xytext=(label_x, label_positions[symbol]),
            textcoords="data",
            ha=horizontal,
            va="center",
            fontsize=11.5,
            fontweight="bold",
            color=COLORS[symbol],
            clip_on=False,
            arrowprops={
                "arrowstyle": "-",
                "color": COLORS[symbol],
                "linewidth": 0.85,
                "alpha": 0.62,
            },
        )

    detail.set_xlim(0, 1)
    detail.set_ylim(0, 1)
    detail.axis("off")
    detail.text(
        0.02,
        0.965,
        "Current standings",
        fontsize=15,
        fontweight="bold",
        color=INK,
        va="top",
    )
    detail.text(0.48, 0.895, "route share", fontsize=9.4, color=MUTED, ha="right")
    detail.text(0.74, 0.895, "value share", fontsize=9.4, color=MUTED, ha="right")
    detail.text(0.98, 0.895, "ultimate pairs", fontsize=9.4, color=MUTED, ha="right")
    count_leader = max(SYMBOLS, key=lambda symbol: float(current[f"{symbol}_count_share"]))
    value_leader = max(SYMBOLS, key=lambda symbol: float(current[f"{symbol}_value_share"]))
    row_y = (0.82, 0.70, 0.58, 0.46)
    for symbol, y in zip(SYMBOLS, row_y, strict=True):
        detail.add_patch(
            plt.Rectangle(
                (0.015, y - 0.048),
                0.97,
                0.096,
                transform=detail.transAxes,
                facecolor=to_rgba(COLORS[symbol], 0.075),
                edgecolor="none",
                zorder=0,
            )
        )
        detail.scatter(
            [0.055],
            [y],
            s=58,
            color=COLORS[symbol],
            transform=detail.transAxes,
            clip_on=False,
        )
        detail.text(0.095, y, symbol, fontsize=11.2, fontweight="bold", color=INK, va="center")
        count_color = COLORS[symbol] if symbol == count_leader else INK
        value_color = COLORS[symbol] if symbol == value_leader else INK
        detail.text(
            0.48,
            y,
            f"{float(current[f'{symbol}_count_share']):.1%}",
            fontsize=11.0,
            fontweight="bold" if symbol == count_leader else "normal",
            color=count_color,
            ha="right",
            va="center",
        )
        detail.text(
            0.74,
            y,
            f"{float(current[f'{symbol}_value_share']):.1%}",
            fontsize=11.0,
            fontweight="bold" if symbol == value_leader else "normal",
            color=value_color,
            ha="right",
            va="center",
        )
        detail.text(
            0.98,
            y,
            f"{int(round(float(current[f'{symbol}_active_pairs']))):,}",
            fontsize=10.3,
            color=INK,
            ha="right",
            va="center",
        )

    detail.text(
        0.02,
        0.355,
        "Stablecoin family",
        fontsize=12.3,
        fontweight="bold",
        color=INK,
    )
    for label, field, y, color in (
        ("Route count", "stable_count_share", 0.275, "#238B78"),
        ("Supported value", "stable_value_share", 0.185, "#4F8A3C"),
    ):
        value = float(current[field])
        detail.text(0.02, y + 0.027, label, fontsize=9.8, color=MUTED, va="bottom")
        detail.add_patch(
            plt.Rectangle(
                (0.31, y),
                0.56,
                0.032,
                transform=detail.transAxes,
                facecolor=GRID,
                edgecolor="none",
            )
        )
        detail.add_patch(
            plt.Rectangle(
                (0.31, y),
                0.56 * value,
                0.032,
                transform=detail.transAxes,
                facecolor=color,
                edgecolor="none",
            )
        )
        detail.text(0.98, y + 0.016, f"{value:.1%}", fontsize=11, fontweight="bold", color=color, ha="right", va="center")
    detail.text(
        0.02,
        0.075,
        "Bubble area: log active ordered ultimate pairs\nTrail: prior six months only",
        fontsize=9.8,
        color=MUTED,
        linespacing=1.4,
    )

    figure.text(
        0.065,
        0.105,
        "Exact two-atomic-trade routes. Value shares require source, intermediary, and destination values to agree within 20%.",
        fontsize=9.4,
        color=MUTED,
        ha="left",
    )
    figure.text(
        0.065,
        0.073,
        "Named bubbles remain inside the full native-plus-stable denominator; smaller stablecoins are included in the family bars.",
        fontsize=9.4,
        color=MUTED,
        ha="left",
    )
    figure.add_artist(
        plt.Line2D(
            [0.065, 0.065 + 0.87 * progress],
            [0.036, 0.036],
            transform=figure.transFigure,
            color=ACCENT,
            linewidth=3.0,
            solid_capstyle="round",
        )
    )
    figure.add_artist(
        plt.Line2D(
            [0.065, 0.935],
            [0.036, 0.036],
            transform=figure.transFigure,
            color=GRID,
            linewidth=1.0,
            zorder=0,
        )
    )


def _draw_poster(
    figure: plt.Figure,
    timeline: pd.DataFrame,
    frame_index: int,
) -> None:
    """Draw a sparse clickable poster while the film retains the full detail."""

    figure.clear()
    figure.patch.set_facecolor(BACKGROUND)
    axis = figure.add_axes((0.11, 0.17, 0.78, 0.68))
    current = timeline.iloc[frame_index]
    current_date = pd.Timestamp(current["date"])
    history = timeline.iloc[: frame_index + 1]
    history = history.loc[
        pd.to_datetime(history["date"]).ge(current_date - pd.Timedelta(days=TRAIL_DAYS))
    ]

    figure.text(
        0.89,
        0.91,
        current_date.strftime("%B %Y"),
        fontsize=19,
        fontweight="bold",
        color=ACCENT,
        ha="right",
        va="center",
    )
    axis.set_xlim(0, 0.90)
    axis.set_ylim(0, 0.90)
    axis.plot([0, 0.90], [0, 0.90], color=GRID, linestyle=(0, (4, 5)), linewidth=1.2)
    axis.grid(color=GRID, linewidth=0.75, alpha=0.82)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["bottom", "left"]].set_color(GRID)
    axis.tick_params(axis="both", length=0, labelcolor=MUTED, labelsize=10)
    axis.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    axis.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    axis.set_xlabel("Share of intermediary routes", fontsize=12, color=INK, labelpad=10)
    axis.set_ylabel(
        "Share of supported intermediary value",
        fontsize=12,
        color=INK,
        labelpad=10,
    )

    maximum_pairs = max(
        float(timeline[f"{symbol}_active_pairs"].max()) for symbol in SYMBOLS
    )
    label_positions = spread_label_positions(
        {
            symbol: float(current[f"{symbol}_value_share"])
            for symbol in SYMBOLS
        }
    )
    for symbol in SYMBOLS:
        _add_trail(axis, history, symbol)
        x_value = float(current[f"{symbol}_count_share"])
        y_value = float(current[f"{symbol}_value_share"])
        axis.scatter(
            [x_value],
            [y_value],
            s=bubble_area(
                float(current[f"{symbol}_active_pairs"]),
                maximum=maximum_pairs,
            ),
            facecolor=to_rgba(COLORS[symbol], 0.78),
            edgecolor=BACKGROUND,
            linewidth=2.2,
            zorder=4,
        )
        label_x = x_value + 0.025 if x_value < 0.72 else x_value - 0.025
        axis.annotate(
            symbol,
            (x_value, y_value),
            xytext=(label_x, label_positions[symbol]),
            textcoords="data",
            ha="left" if x_value < 0.72 else "right",
            va="center",
            fontsize=12,
            fontweight="bold",
            color=COLORS[symbol],
            clip_on=False,
            arrowprops={
                "arrowstyle": "-",
                "color": COLORS[symbol],
                "linewidth": 0.85,
                "alpha": 0.62,
            },
        )

    figure.text(
        0.11,
        0.075,
        "Bubble area: active ultimate pairs   |   Trail: prior six months",
        fontsize=11,
        color=MUTED,
        ha="left",
    )


def render_outputs(
    monthly: pd.DataFrame,
    *,
    video_output: Path = VIDEO_OUTPUT,
    poster_pdf_output: Path = POSTER_PDF_OUTPUT,
    poster_png_output: Path = POSTER_PNG_OUTPUT,
    seconds: float = 18.0,
    fps: int = 24,
    poster_only: bool = False,
) -> None:
    """Render a 16:9 H.264 film and a sparse final-month PDF/PNG poster."""

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
            _draw_poster(figure, timeline, len(timeline) - 1)
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
                figure.savefig(png, format="png", facecolor=BACKGROUND, dpi=120)
                pdf.replace(poster_pdf_output)
                png.replace(poster_png_output)
            if poster_only:
                return
            _draw_frame(figure, timeline, 0)
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                raise FileNotFoundError("ffmpeg is required to render the MP4")
            movie = animation.FuncAnimation(
                figure,
                lambda index: _draw_frame(figure, timeline, index),
                frames=len(timeline),
                interval=1000 / fps,
                repeat=False,
                cache_frame_data=False,
            )
            writer = animation.FFMpegWriter(
                fps=fps,
                codec="libx264",
                metadata={
                    "title": "Vehicle currencies vie for dominance over time",
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
    parser.add_argument("--video", type=Path, default=VIDEO_OUTPUT)
    parser.add_argument("--poster-pdf", type=Path, default=POSTER_PDF_OUTPUT)
    parser.add_argument("--poster-png", type=Path, default=POSTER_PNG_OUTPUT)
    parser.add_argument("--seconds", type=float, default=18.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--poster-only", action="store_true")
    arguments = parser.parse_args()
    monthly = load_input(arguments.choices)
    render_outputs(
        monthly,
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

"""Shared transforms and rendering used by current paper/deck figures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import matplotlib
import pandas as pd

from ddvc.runtime import serialized_output_install, staged_output
from ddvc.workflow import current_inputs, describe_file

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ASSET_TYPES = ("native", "staked_native", "stable", "imported", "other")
ASSET_LABELS = {
    "native": "Native",
    "staked_native": "Staked native",
    "stable": "Stable",
    "imported": "Imported",
    "other": "Other",
}
PALETTE = {
    "native": "#1F4E79",
    "staked_native": "#7C3AED",
    "stable": "#238B78",
    "imported": "#D97706",
    "other": "#6B7280",
}


def bridge_adoption_capital_path(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the balanced stablecoin and WETH adoption-capital paths."""

    required = {
        "record_type",
        "vehicle_class",
        "event_time_days",
        "coefficient",
        "standard_error",
        "events",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"bridge adoption path is missing {', '.join(missing)}")
    data = frame.loc[
        frame["record_type"].eq("bridge_adoption_capital_path"),
        list(required),
    ].copy()
    data["event_time_days"] = pd.to_numeric(
        data["event_time_days"], errors="raise"
    ).astype(int)
    for column in ("coefficient", "standard_error", "events"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    expected = {
        (vehicle_class, event_time)
        for vehicle_class in ("stablecoin", "WETH")
        for event_time in range(-7, 8)
    }
    observed = set(
        data[["vehicle_class", "event_time_days"]].itertuples(
            index=False, name=None
        )
    )
    if (
        data.duplicated(["vehicle_class", "event_time_days"]).any()
        or observed != expected
    ):
        raise ValueError("bridge adoption path lacks one unique row per class-day")
    if data["events"].nunique() != 1 or int(data["events"].iloc[0]) < 100:
        raise ValueError("bridge adoption path lacks common event support")
    if data["standard_error"].lt(0).any():
        raise ValueError("bridge adoption path has negative standard errors")
    order = {"stablecoin": 0, "WETH": 1}
    data["vehicle_order"] = data["vehicle_class"].map(order)
    return data.sort_values(
        ["vehicle_order", "event_time_days"], kind="stable"
    ).reset_index(drop=True)


def render_bridge_adoption_capital_path(frame: pd.DataFrame, output: Path) -> None:
    """Render bridge-capital changes around first use of the supported stablecoin."""

    data = bridge_adoption_capital_path(frame)
    colours = {"stablecoin": PALETTE["stable"], "WETH": PALETTE["native"]}
    labels = {"stablecoin": "Stablecoin bridge", "WETH": "WETH bridge"}
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "pdf.fonttype": 42,
            "axes.labelcolor": "#111827",
            "text.color": "#111827",
        }
    ):
        figure, axis = plt.subplots(figsize=(8.8, 4.2))
        try:
            for vehicle_class in ("stablecoin", "WETH"):
                group = data[data["vehicle_class"].eq(vehicle_class)]
                x = group["event_time_days"].to_numpy(dtype=float)
                y = group["coefficient"].to_numpy(dtype=float)
                se = group["standard_error"].to_numpy(dtype=float)
                colour = colours[vehicle_class]
                axis.fill_between(
                    x,
                    y - 1.96 * se,
                    y + 1.96 * se,
                    color=colour,
                    alpha=0.12,
                    linewidth=0,
                )
                axis.plot(
                    x,
                    y,
                    color=colour,
                    linewidth=2.4,
                    marker="o",
                    markersize=3.5,
                    label=labels[vehicle_class],
                )
            axis.axhline(0, color="#6B7280", linewidth=0.9)
            axis.axvline(0, color="#111827", linewidth=1.0, linestyle="--")
            axis.annotate(
                "first use of supported stablecoin",
                xy=(0, axis.get_ylim()[1]),
                xytext=(5, -5),
                textcoords="offset points",
                ha="left",
                va="top",
                fontsize=9,
                color="#374151",
            )
            axis.set_xlabel("Calendar days from first use of supported stablecoin")
            axis.set_ylabel("Change in log weak-leg deposited capital")
            axis.set_xticks(range(-7, 8, 2))
            axis.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.75)
            axis.spines[["top", "right"]].set_visible(False)
            axis.legend(frameon=False, loc="upper left")
            figure.tight_layout()
            figure.savefig(
                output,
                format="pdf",
                bbox_inches="tight",
                metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None},
            )
        finally:
            plt.close(figure)


def vehicle_excess_use_transition(
    frame: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    symbols: tuple[str, ...] = ("USDC", "USDT"),
) -> pd.DataFrame:
    """Select one supported count/value observation per candidate and year."""

    required = {
        "level",
        "year",
        "symbol",
        "vehicle_excess_use_count_ratio",
        "vehicle_excess_use_ratio_within_20pct",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"vehicle excess-use exhibit is missing {', '.join(missing)}")
    data = frame.loc[
        frame["level"].eq("token")
        & frame["symbol"].isin(symbols)
        & frame["year"].isin([baseline_year, comparison_year]),
        list(required),
    ].copy()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    ratio_columns = (
        "vehicle_excess_use_count_ratio",
        "vehicle_excess_use_ratio_within_20pct",
    )
    for column in ratio_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["symbol", *ratio_columns])
    expected = {
        (symbol, year)
        for symbol in symbols
        for year in (baseline_year, comparison_year)
    }
    observed = set(data[["symbol", "year"]].itertuples(index=False, name=None))
    if data.duplicated(["symbol", "year"]).any() or observed != expected:
        raise ValueError("vehicle excess-use exhibit lacks one unique cell per candidate-year")
    if data[list(ratio_columns)].lt(0).any().any():
        raise ValueError("vehicle excess-use exhibit has negative excess-use ratios")
    order = {symbol: index for index, symbol in enumerate(symbols)}
    data["symbol_order"] = data["symbol"].map(order)
    return data.sort_values(["symbol_order", "year"], kind="stable").reset_index(drop=True)


def render_vehicle_excess_use_transition(frame: pd.DataFrame, output: Path) -> None:
    """Render candidate movements with parity visible in both panels."""

    data = vehicle_excess_use_transition(frame)
    panels = (
        ("vehicle_excess_use_count_ratio", "Route count"),
        ("vehicle_excess_use_ratio_within_20pct", "Routed value"),
    )
    symbols = data.sort_values("symbol_order")["symbol"].drop_duplicates().tolist()
    years = sorted(data["year"].unique())
    colours = {years[0]: "#6B7280", years[-1]: PALETTE["stable"]}
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "pdf.fonttype": 42,
            "axes.labelcolor": "#111827",
            "text.color": "#111827",
        }
    ):
        figure, axes = plt.subplots(1, 2, figsize=(10.2, 3.9), sharey=True)
        try:
            for axis, (column, title) in zip(axes, panels, strict=True):
                for row, symbol in enumerate(symbols):
                    cells = data.loc[data["symbol"].eq(symbol)].set_index("year")
                    start = float(cells.loc[years[0], column])
                    end = float(cells.loc[years[-1], column])
                    axis.plot([start, end], [row, row], color="#9CA3AF", linewidth=2, zorder=1)
                    for year, value in ((years[0], start), (years[-1], end)):
                        axis.scatter(value, row, s=58, color=colours[year], zorder=2)
                        axis.annotate(
                            f"{value:.2f}",
                            (value, row),
                            xytext=(0, 9 if year == years[-1] else -13),
                            textcoords="offset points",
                            ha="center",
                            va="center",
                            fontsize=8,
                            color=colours[year],
                        )
                axis.axvline(1, color="#111827", linewidth=1, linestyle="--", alpha=0.8)
                axis.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=8)
                axis.set_xlabel("Intermediary use relative to endpoint use")
                axis.set_yticks(range(len(symbols)), symbols)
                axis.set_ylim(-0.55, len(symbols) - 0.45)
                axis.grid(axis="x", color="#D1D5DB", linewidth=0.6, alpha=0.75)
                axis.spines[["top", "right", "left"]].set_visible(False)
                axis.tick_params(axis="y", length=0)
            handles = [
                plt.Line2D([], [], marker="o", linestyle="", color=colours[year], label=str(year))
                for year in years
            ]
            figure.legend(handles=handles, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.01))
            figure.text(
                0.995,
                0.015,
                "Dashed line is parity. Routed value is shown only when all three dollar amounts agree within 20%.",
                ha="right",
                va="bottom",
                fontsize=8,
                color="#4B5563",
            )
            figure.tight_layout(rect=(0, 0.13, 1, 1))
            figure.savefig(
                output,
                format="pdf",
                bbox_inches="tight",
                metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None},
            )
        finally:
            plt.close(figure)


def load_current_jsonl(path: Path, *, consumer: str) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read one required JSONL exhibit and record diagnostic file facts."""

    with current_inputs([path], consumer=consumer):
        identity = describe_file(path)
        frame = pd.read_json(path, lines=True)
    return frame, identity


def publish_pdf(
    output: Path,
    *,
    renderer: Callable[[Path], None],
    input_path: Path,
    input_identity: dict[str, object],
    code_sources: list[str],
    notes: str,
    script: str,
) -> None:
    """Render and atomically install one PDF.

    The descriptive arguments keep each producer self-documenting; publication
    itself is the direct atomic replacement of the requested output.
    """

    del input_path, input_identity, code_sources, notes, script
    output.parent.mkdir(parents=True, exist_ok=True)
    with staged_output(output) as temporary:
        renderer(temporary)
        with serialized_output_install(output):
            temporary.replace(output)

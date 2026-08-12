"""Shared presentation-layer transforms and rendering for paper/deck figures."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from ddvc.provenance import (
    describe_input,
    install_stamped_artifact,
    prepare_stamp,
    require_current_artifacts,
)
from ddvc.runtime import staged_output

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402


ASSET_TYPES = ("native", "staked_native", "stable", "imported", "other")
DISPLAYED_ASSET_TYPES = ("native", "stable", "imported", "other")
ASSET_LABELS = {
    "native": "Native",
    "stable": "Stable",
    "imported": "Imported",
    "other": "Other",
}
PALETTE = {
    "native": "#1F4E79",
    "stable": "#238B78",
    "imported": "#D97706",
    "other": "#6B7280",
    "count": "#1F4E79",
    "value": "#B45309",
}
LINE_STYLES = {
    "native": "-",
    "stable": "--",
    "imported": "-.",
    "other": ":",
}
MARKERS = {
    "native": "o",
    "stable": "s",
    "imported": "^",
    "other": "D",
}


def _require_columns(frame: pd.DataFrame, columns: set[str], *, name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def validate_daily_calendar(frame: pd.DataFrame, *, name: str) -> pd.DataFrame:
    """Require one observation on every calendar day between the panel endpoints."""

    _require_columns(frame, {"date"}, name=name)
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    if out.empty:
        raise ValueError(f"{name} is empty")
    if out["date"].duplicated().any():
        duplicated = out.loc[out["date"].duplicated(), "date"].iloc[0].date()
        raise ValueError(f"{name} has more than one row for {duplicated}")
    out = out.sort_values("date", kind="stable").reset_index(drop=True)
    expected = pd.date_range(out["date"].iloc[0], out["date"].iloc[-1], freq="D")
    observed = pd.DatetimeIndex(out["date"])
    missing = expected.difference(observed)
    if len(missing):
        preview = ", ".join(str(day.date()) for day in missing[:3])
        raise ValueError(
            f"{name} is not full-calendar: {len(missing)} missing day(s), beginning {preview}"
        )
    return out


def quarterly_vehicle_type_shares(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily type totals into exhaustive calendar-quarter shares."""

    count_columns = [f"cnt_{asset_type}" for asset_type in ASSET_TYPES]
    value_columns = [f"usd_within_20pct_{asset_type}" for asset_type in ASSET_TYPES]
    data = validate_daily_calendar(frame, name="intermediation-by-type panel")
    _require_columns(data, set(count_columns + value_columns), name="intermediation-by-type panel")
    for column in count_columns + value_columns:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if data[column].lt(0).any():
            raise ValueError(f"intermediation-by-type panel has negative {column}")
    data["quarter"] = data["date"].dt.to_period("Q")
    quarterly = data.groupby("quarter", observed=True)[count_columns + value_columns].sum()
    count_total = quarterly[count_columns].sum(axis=1)
    value_total = quarterly[value_columns].sum(axis=1)
    valid = count_total.gt(0) & value_total.gt(0)
    if not valid.any():
        raise ValueError("intermediation-by-type panel has no quarter with count and value support")
    quarterly = quarterly.loc[valid].copy()
    count_total = count_total.loc[valid]
    value_total = value_total.loc[valid]
    result = pd.DataFrame({"date": quarterly.index.to_timestamp(how="end").normalize()})
    for asset_type in ASSET_TYPES:
        result[f"count_share_{asset_type}"] = quarterly[f"cnt_{asset_type}"].to_numpy() / count_total.to_numpy()
        result[f"value_share_{asset_type}"] = quarterly[f"usd_within_20pct_{asset_type}"].to_numpy() / value_total.to_numpy()
    return result.reset_index(drop=True)


def round_trip_daily_and_quarterly(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate the full daily route audit and compute quarterly median daily shares."""

    required = {
        "date",
        "multi_leg_routes",
        "round_trip_routes",
        "round_trip_share_of_multileg",
        "round_trip_usd_share_of_multileg",
    }
    data = validate_daily_calendar(frame, name="certified route audit panel")
    _require_columns(data, required, name="certified route audit panel")
    numeric = sorted(required - {"date"})
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="raise")
    if data[["multi_leg_routes", "round_trip_routes"]].lt(0).any().any():
        raise ValueError("certified route audit panel has negative route counts")
    if data["round_trip_routes"].gt(data["multi_leg_routes"]).any():
        raise ValueError("round-trip routes exceed multi-leg routes")
    positive = data["multi_leg_routes"].gt(0)
    implied = data.loc[positive, "round_trip_routes"] / data.loc[positive, "multi_leg_routes"]
    observed = data.loc[positive, "round_trip_share_of_multileg"]
    if not np.allclose(implied, observed, rtol=0, atol=1e-12, equal_nan=False):
        raise ValueError("round-trip count share disagrees with its route-count identity")
    for column in ("round_trip_share_of_multileg", "round_trip_usd_share_of_multileg"):
        supported = data.loc[positive, column]
        if supported.isna().any() or not supported.between(0, 1).all():
            raise ValueError(f"certified route audit panel has invalid {column}")
    data = data.loc[positive].copy()
    data["quarter"] = data["date"].dt.to_period("Q")
    quarterly = (
        data.groupby("quarter", observed=True)[
            ["round_trip_share_of_multileg", "round_trip_usd_share_of_multileg"]
        ]
        .median()
        .reset_index()
    )
    quarterly["date"] = quarterly.pop("quarter").dt.to_timestamp(how="end").dt.normalize()
    return data.reset_index(drop=True), quarterly


def _style_axis(axis, *, title: str, ylabel: str | None = None) -> None:
    axis.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=8)
    if ylabel:
        axis.set_ylabel(ylabel)
    axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    axis.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.75)
    axis.spines[["top", "right"]].set_visible(False)
    axis.tick_params(labelsize=9)
    axis.xaxis.set_major_locator(mdates.YearLocator(1))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def load_current_parquet(path: Path, *, consumer: str) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read a provenance-current panel and bind the exact bytes used by the figure."""

    require_current_artifacts([path], consumer=consumer)
    identity = describe_input(path)
    frame = pd.read_parquet(path)
    if describe_input(path) != identity:
        raise RuntimeError(f"{consumer} input changed while it was being read")
    return frame, identity


def render_vehicle_type_shares(frame: pd.DataFrame, output: Path) -> None:
    """Render quarterly count and strict common-support value shares as vector PDF."""

    data = quarterly_vehicle_type_shares(frame)
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "axes.labelcolor": "#111827", "text.color": "#111827"}):
        figure, axes = plt.subplots(1, 2, figsize=(11.2, 4.4), sharey=True)
        try:
            panels = (("count_share", "Route-count share"), ("value_share", "Common-support value share"))
            for axis, (prefix, title) in zip(axes, panels, strict=True):
                for asset_type in DISPLAYED_ASSET_TYPES:
                    axis.plot(
                        data["date"],
                        data[f"{prefix}_{asset_type}"],
                        color=PALETTE[asset_type],
                        linestyle=LINE_STYLES[asset_type],
                        linewidth=2.1,
                        marker=MARKERS[asset_type],
                        markersize=3.2,
                        markevery=4,
                        label=ASSET_LABELS[asset_type],
                    )
                _style_axis(axis, title=title, ylabel="Share of intermediation" if axis is axes[0] else None)
                axis.set_ylim(0, 0.9)
            handles, labels = axes[0].get_legend_handles_labels()
            figure.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.045))
            figure.suptitle("The intermediating asset changes over time", x=0.06, ha="left", fontsize=15, fontweight="bold")
            figure.text(0.995, 0.015, "Quarterly ratios of totals. Value requires source–intermediary–sink amounts within 20%. Staked-native remains in the denominator.", ha="right", va="bottom", fontsize=8, color="#4B5563")
            figure.tight_layout(rect=(0, 0.16, 1, 0.92))
            figure.savefig(output, format="pdf", bbox_inches="tight", metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None})
        finally:
            plt.close(figure)


def render_round_trip_shares(frame: pd.DataFrame, output: Path) -> None:
    """Render every certified day with quarterly median count and value paths."""

    daily, quarterly = round_trip_daily_and_quarterly(frame)
    series = (
        ("round_trip_share_of_multileg", "count", "By count"),
        ("round_trip_usd_share_of_multileg", "value", "By value"),
    )
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "axes.labelcolor": "#111827", "text.color": "#111827"}):
        figure, axis = plt.subplots(figsize=(10.5, 4.5))
        try:
            for column, palette_key, label in series:
                color = PALETTE[palette_key]
                axis.scatter(daily["date"], daily[column], s=3.5, alpha=0.10, color=color, linewidths=0, rasterized=False)
                axis.plot(quarterly["date"], quarterly[column], color=color, linewidth=2.3, label=label)
            _style_axis(axis, title="Round trips are common, and value incidence is more volatile", ylabel="Share of multi-leg routes")
            axis.set_ylim(0, 1)
            axis.legend(frameon=False, ncol=2, loc="upper left")
            figure.text(0.995, 0.015, "Dots are all certified daily observations; lines are quarterly medians of daily shares.", ha="right", va="bottom", fontsize=8, color="#4B5563")
            figure.tight_layout(rect=(0, 0.06, 1, 1))
            figure.savefig(output, format="pdf", bbox_inches="tight", metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None})
        finally:
            plt.close(figure)


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
    """Render and atomically install one PDF together with its provenance record."""

    output.parent.mkdir(parents=True, exist_ok=True)
    with staged_output(output) as temporary:
        renderer(temporary)
        prepared = prepare_stamp(
            output,
            content_path=temporary,
            code_sources=code_sources,
            inputs=[input_path],
            notes=notes,
            script=script,
        )
        recorded_inputs = json.loads(prepared).get("inputs")
        if recorded_inputs != [input_identity]:
            raise RuntimeError("figure input changed after it was read; refusing mixed-generation output")
        install_stamped_artifact(temporary, output, prepared)

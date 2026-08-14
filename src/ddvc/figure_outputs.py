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
    current_artifacts,
)
from ddvc.runtime import staged_output

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import TwoSlopeNorm  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402


ASSET_TYPES = ("native", "staked_native", "stable", "imported", "other")
DISPLAYED_ASSET_TYPES = ASSET_TYPES
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
    "count": "#1F4E79",
    "value": "#B45309",
    "composition": "#9CA3AF",
    "incomplete": "#D97706",
    "overlap": "#7C3AED",
    "usable": "#238B78",
}
LINE_STYLES = {
    "native": "-",
    "staked_native": (0, (5, 1)),
    "stable": "--",
    "imported": "-.",
    "other": ":",
}
MARKERS = {
    "native": "o",
    "staked_native": "P",
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


def integration_intermediation_bins(frame: pd.DataFrame, *, bins: int = 10) -> pd.DataFrame:
    """Summarise the daily association between venue reach and intermediation."""

    if bins < 2:
        raise ValueError("integration/intermediation figure needs at least two bins")
    data = validate_daily_calendar(frame, name="cross-venue routing panel")
    columns = {
        "cross_venue_share",
        "intermediated_share",
        "balanced_cross_venue_share",
        "balanced_intermediated_share",
    }
    _require_columns(data, columns, name="cross-venue routing panel")
    results: list[pd.DataFrame] = []
    for cohort, x_name, y_name in (
        ("Full sample", "cross_venue_share", "intermediated_share"),
        ("Balanced cohort", "balanced_cross_venue_share", "balanced_intermediated_share"),
    ):
        sample = data[["date", x_name, y_name]].copy()
        sample[x_name] = pd.to_numeric(sample[x_name], errors="coerce")
        sample[y_name] = pd.to_numeric(sample[y_name], errors="coerce")
        sample = sample.replace([np.inf, -np.inf], np.nan).dropna()
        if sample.empty or not sample[x_name].between(0, 1).all() or not sample[y_name].between(0, 1).all():
            raise ValueError(f"cross-venue routing panel has invalid {cohort.lower()} shares")
        if sample[x_name].nunique() < bins:
            raise ValueError(f"cross-venue routing panel has fewer than {bins} distinct integration states")
        sample["bin"] = pd.qcut(
            sample[x_name].rank(method="first"),
            q=bins,
            labels=False,
        )
        grouped = sample.groupby("bin", observed=True).agg(
            integration_share=(x_name, "mean"),
            intermediation_share=(y_name, "mean"),
            days=("date", "size"),
        )
        grouped["cohort"] = cohort
        results.append(grouped.reset_index(drop=True))
    return pd.concat(results, ignore_index=True)


def integration_rotation_slopes(
    frame: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
) -> pd.DataFrame:
    """Select stable-share levels for the integration-regime rotation comparison."""

    required = {
        "integration_scope",
        "weighting",
        "value_support",
        "transformation",
        "baseline_year",
        "comparison_year",
        "baseline_daily_mean",
        "comparison_daily_mean",
    }
    _require_columns(frame, required, name="integration rival exhibit")
    data = frame.loc[
        frame["integration_scope"].isin(["single_venue", "cross_venue"])
        & frame["transformation"].eq("share_level")
        & pd.to_numeric(frame["baseline_year"], errors="coerce").eq(baseline_year)
        & pd.to_numeric(frame["comparison_year"], errors="coerce").eq(comparison_year)
        & (
            (frame["weighting"].eq("episode") & frame["value_support"].eq("all_routes"))
            | (frame["weighting"].eq("value") & frame["value_support"].eq("within_20pct"))
        ),
        list(required),
    ].copy()
    for column in ("baseline_daily_mean", "comparison_daily_mean"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["baseline_daily_mean", "comparison_daily_mean"])
    expected = {
        ("single_venue", "episode", "all_routes"),
        ("cross_venue", "episode", "all_routes"),
        ("single_venue", "value", "within_20pct"),
        ("cross_venue", "value", "within_20pct"),
    }
    keys = set(data[["integration_scope", "weighting", "value_support"]].itertuples(index=False, name=None))
    if data.duplicated(["integration_scope", "weighting", "value_support"]).any() or keys != expected:
        raise ValueError("integration rival exhibit lacks one unique cell per regime and weighting")
    if not data[["baseline_daily_mean", "comparison_daily_mean"]].apply(
        lambda column: column.between(0, 1)
    ).all().all():
        raise ValueError("integration rival exhibit has invalid stable-share levels")
    return data.sort_values(["weighting", "integration_scope"], kind="stable").reset_index(drop=True)


def vehicle_excess_use_cross_section(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the latest candidate cross-section for a count/value heatmap."""

    required = {"lens", "year", "token", "count_excess_use", "value_excess_use", "is_vehicle"}
    _require_columns(frame, required, name="vehicle-rotation exhibit")
    data = frame.loc[frame["lens"].eq("cross_section"), list(required)].copy()
    data["year"] = pd.to_numeric(data["year"], errors="coerce")
    data = data.loc[data["year"].eq(data["year"].max())]
    for column in ("count_excess_use", "value_excess_use"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["token", "count_excess_use", "value_excess_use"])
    if data.empty or data["token"].duplicated().any():
        raise ValueError("vehicle-rotation exhibit lacks a unique latest candidate cross-section")
    if data[["count_excess_use", "value_excess_use"]].lt(0).any().any():
        raise ValueError("vehicle-rotation exhibit has negative excess-use ratios")
    data["mean_excess_use"] = data[["count_excess_use", "value_excess_use"]].mean(axis=1)
    return data.sort_values(
        ["mean_excess_use", "token"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)


def vehicle_excess_use_transition(
    frame: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    symbols: tuple[str, ...] = ("USDC", "USDT"),
) -> pd.DataFrame:
    """Select supported candidate-level count and value ratios for a paired-year plot."""

    required = {
        "level",
        "year",
        "symbol",
        "vehicle_excess_use_count_ratio",
        "vehicle_excess_use_ratio_within_20pct",
    }
    _require_columns(frame, required, name="vehicle excess-use exhibit")
    data = frame.loc[
        frame["level"].eq("token")
        & frame["symbol"].isin(symbols)
        & frame["year"].isin([baseline_year, comparison_year]),
        list(required),
    ].copy()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    for column in (
        "vehicle_excess_use_count_ratio",
        "vehicle_excess_use_ratio_within_20pct",
    ):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(
        subset=[
            "symbol",
            "vehicle_excess_use_count_ratio",
            "vehicle_excess_use_ratio_within_20pct",
        ]
    )
    expected = pd.MultiIndex.from_product(
        [symbols, (baseline_year, comparison_year)], names=["symbol", "year"]
    )
    observed = pd.MultiIndex.from_frame(data[["symbol", "year"]])
    if data.duplicated(["symbol", "year"]).any() or set(observed) != set(expected):
        raise ValueError("vehicle excess-use exhibit lacks one unique cell per candidate-year")
    if data[
        ["vehicle_excess_use_count_ratio", "vehicle_excess_use_ratio_within_20pct"]
    ].lt(0).any().any():
        raise ValueError("vehicle excess-use exhibit has negative excess-use ratios")
    order = {symbol: index for index, symbol in enumerate(symbols)}
    data["symbol_order"] = data["symbol"].map(order)
    return data.sort_values(["symbol_order", "year"], kind="stable").reset_index(drop=True)


def architecture_support_composition(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and order architecture-event support attrition."""

    required = {
        "kind",
        "threshold",
        "detected_events",
        "composition_shift_events",
        "incomplete_window_events",
        "overlapping_transition_events",
        "usable_events",
    }
    _require_columns(frame, required, name="architecture-transition support exhibit")
    data = frame.loc[frame["kind"].isin(["entry", "exit"]), list(required)].copy()
    data["threshold"] = pd.to_numeric(data["threshold"], errors="raise")
    count_columns = sorted(required - {"kind", "threshold"})
    for column in count_columns:
        data[column] = pd.to_numeric(data[column], errors="raise").astype(int)
    if data.empty or data.duplicated(["kind", "threshold"]).any():
        raise ValueError("architecture-transition support exhibit has duplicate or missing cells")
    accounted = data[
        [
            "composition_shift_events",
            "incomplete_window_events",
            "overlapping_transition_events",
            "usable_events",
        ]
    ].sum(axis=1)
    if not accounted.eq(data["detected_events"]).all():
        raise ValueError("architecture-transition exclusions do not reconcile to detected events")
    return data.sort_values(["kind", "threshold"], kind="stable").reset_index(drop=True)


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

    with current_artifacts([path], consumer=consumer):
        identity = describe_input(path)
        frame = pd.read_parquet(path)
    return frame, identity


def render_vehicle_type_shares(frame: pd.DataFrame, output: Path) -> None:
    """Render quarterly route-count and comparable routed-value shares as vector PDF."""

    data = quarterly_vehicle_type_shares(frame)
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "axes.labelcolor": "#111827", "text.color": "#111827"}):
        figure, axes = plt.subplots(1, 2, figsize=(11.2, 4.4), sharey=True)
        try:
            panels = (("count_share", "Route-count share"), ("value_share", "Routed-value share"))
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
            figure.legend(handles, labels, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 0.045))
            figure.suptitle("The intermediating asset changes over time", x=0.06, ha="left", fontsize=15, fontweight="bold")
            figure.text(0.995, 0.015, "Quarterly ratios of totals. Value requires source–intermediary–sink amounts within 20%.", ha="right", va="bottom", fontsize=8, color="#4B5563")
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


def render_integration_intermediation(frame: pd.DataFrame, output: Path) -> None:
    """Render binned daily associations without using calendar time as an axis."""

    data = integration_intermediation_bins(frame)
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "axes.labelcolor": "#111827", "text.color": "#111827"}):
        figure, axis = plt.subplots(figsize=(8.6, 4.8))
        try:
            for cohort, color, marker in (
                ("Full sample", PALETTE["count"], "o"),
                ("Balanced cohort", PALETTE["value"], "s"),
            ):
                rows = data.loc[data["cohort"].eq(cohort)]
                axis.plot(
                    rows["integration_share"],
                    rows["intermediation_share"],
                    color=color,
                    marker=marker,
                    linewidth=2.2,
                    markersize=6,
                    label=cohort,
                )
            axis.set_xlabel("Cross-venue share of multi-leg routes")
            axis.set_ylabel("Share of routes using an intermediary")
            axis.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
            axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
            axis.set_title(
                "More cross-venue routing does not mechanically imply more intermediation",
                loc="left",
                fontsize=13,
                fontweight="bold",
                pad=9,
            )
            axis.grid(color="#D1D5DB", linewidth=0.6, alpha=0.75)
            axis.spines[["top", "right"]].set_visible(False)
            axis.legend(frameon=False, loc="best")
            figure.text(
                0.995,
                0.015,
                "Points are equal-frequency bins of daily observations; the association is descriptive.",
                ha="right",
                va="bottom",
                fontsize=8,
                color="#4B5563",
            )
            figure.tight_layout(rect=(0, 0.06, 1, 1))
            figure.savefig(output, format="pdf", bbox_inches="tight", metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None})
        finally:
            plt.close(figure)


def render_integration_rotation_slopes(frame: pd.DataFrame, output: Path) -> None:
    """Render stable-share changes within single- and cross-venue route strata."""

    data = integration_rotation_slopes(frame)
    panels = (
        ("episode", "all_routes", "Route count"),
        ("value", "within_20pct", "Routed value"),
    )
    colours = {"single_venue": PALETTE["count"], "cross_venue": PALETTE["stable"]}
    labels = {"single_venue": "Single venue", "cross_venue": "Cross venue"}
    years = [int(data["baseline_year"].iloc[0]), int(data["comparison_year"].iloc[0])]
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "pdf.fonttype": 42,
            "axes.labelcolor": "#111827",
            "text.color": "#111827",
        }
    ):
        figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.1), sharey=True)
        try:
            for axis, (weighting, support, title) in zip(axes, panels, strict=True):
                sample = data.loc[
                    data["weighting"].eq(weighting) & data["value_support"].eq(support)
                ]
                changes: dict[str, float] = {}
                for scope in ("single_venue", "cross_venue"):
                    row = sample.loc[sample["integration_scope"].eq(scope)].iloc[0]
                    values = [float(row["baseline_daily_mean"]), float(row["comparison_daily_mean"])]
                    changes[scope] = values[1] - values[0]
                    axis.plot(
                        years,
                        values,
                        marker="o" if scope == "single_venue" else "s",
                        color=colours[scope],
                        linewidth=2.4,
                        markersize=6.5,
                        label=labels[scope],
                    )
                    for year, value in zip(years, values, strict=True):
                        axis.annotate(
                            f"{value:.0%}",
                            (year, value),
                            xytext=(0, 9 if scope == "cross_venue" else -14),
                            textcoords="offset points",
                            ha="center",
                            fontsize=8,
                            color=colours[scope],
                        )
                differential = changes["cross_venue"] - changes["single_venue"]
                axis.text(
                    0.02,
                    0.97,
                    f"Cross-venue minus single-venue change: {differential:+.1%}",
                    transform=axis.transAxes,
                    ha="left",
                    va="top",
                    fontsize=8.5,
                    color="#374151",
                )
                axis.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=8)
                axis.set_xticks(years, [str(year) for year in years])
                axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
                axis.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.75)
                axis.spines[["top", "right"]].set_visible(False)
            axes[0].set_ylabel("Stable share within native + stable")
            handles, legend_labels = axes[0].get_legend_handles_labels()
            figure.legend(
                handles,
                legend_labels,
                loc="lower center",
                ncol=2,
                frameon=False,
                bbox_to_anchor=(0.5, 0.015),
            )
            figure.text(
                0.995,
                0.015,
                "Routed value includes routes whose three dollar amounts agree within 20%. "
                "Paired calendar-day means; route strata are selected, so the interaction is descriptive.",
                ha="right",
                va="bottom",
                fontsize=8,
                color="#4B5563",
            )
            figure.tight_layout(rect=(0, 0.12, 1, 1))
            figure.savefig(
                output,
                format="pdf",
                bbox_inches="tight",
                metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None},
            )
        finally:
            plt.close(figure)


def render_vehicle_excess_use_heatmap(frame: pd.DataFrame, output: Path) -> None:
    """Render candidate-level count/value excess use around the neutral value one."""

    data = vehicle_excess_use_cross_section(frame)
    matrix = data[["count_excess_use", "value_excess_use"]].to_numpy(dtype=float)
    span = max(0.25, float(np.nanmax(np.abs(matrix - 1))))
    norm = TwoSlopeNorm(vmin=max(0, 1 - span), vcenter=1, vmax=1 + span)
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "text.color": "#111827"}):
        figure, axis = plt.subplots(figsize=(6.8, 5.2))
        try:
            colour_map = matplotlib.colormaps["PuOr"]
            for row in range(matrix.shape[0]):
                for column in range(matrix.shape[1]):
                    axis.add_patch(
                        Rectangle(
                            (column, row),
                            1,
                            1,
                            facecolor=colour_map(norm(matrix[row, column])),
                            edgecolor="white",
                            linewidth=1.5,
                        )
                    )
            axis.set_xlim(0, matrix.shape[1])
            axis.set_ylim(0, matrix.shape[0])
            axis.set_xticks([0.5, 1.5], ["Route count", "Routed value"])
            axis.set_yticks(
                np.arange(len(data)) + 0.5,
                data["token"].astype(str),
            )
            axis.invert_yaxis()
            for row in range(matrix.shape[0]):
                for column in range(matrix.shape[1]):
                    axis.text(
                        column + 0.5,
                        row + 0.5,
                        f"{matrix[row, column]:.2f}",
                        ha="center",
                        va="center",
                        fontsize=9,
                        color="#111827",
                        fontweight="bold" if bool(data.loc[row, "is_vehicle"]) else "normal",
                    )
            axis.set_title(
                "Excess use differs across currencies and weighting choices",
                loc="left",
                fontsize=13,
                fontweight="bold",
                pad=9,
            )
            axis.tick_params(length=0)
            for spine in axis.spines.values():
                spine.set_visible(False)
            figure.text(
                0.995,
                0.015,
                "Routed value includes routes whose three dollar amounts agree within 20%. "
                "Orange is below parity; purple is above parity.",
                ha="right",
                va="bottom",
                fontsize=8,
                color="#4B5563",
            )
            figure.tight_layout(rect=(0, 0.06, 1, 1))
            figure.savefig(output, format="pdf", bbox_inches="tight", metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None})
        finally:
            plt.close(figure)


def render_vehicle_excess_use_transition(frame: pd.DataFrame, output: Path) -> None:
    """Render 2024-to-2026 candidate movements with parity visible in both panels."""

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
                    axis.plot([start, end], [row, row], color="#9CA3AF", linewidth=2.0, zorder=1)
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
                axis.axvline(1, color="#111827", linewidth=1.0, linestyle="--", alpha=0.8)
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


def render_architecture_support(frame: pd.DataFrame, output: Path) -> None:
    """Render why detected architecture transitions do not yield clean comparisons."""

    data = architecture_support_composition(frame)
    categories = (
        ("composition_shift_events", "Changing comparison set", PALETTE["composition"]),
        ("incomplete_window_events", "Incomplete window", PALETTE["incomplete"]),
        ("overlapping_transition_events", "Overlapping transition", PALETTE["overlap"]),
        ("usable_events", "Usable comparison", PALETTE["usable"]),
    )
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "text.color": "#111827"}):
        figure, axes = plt.subplots(1, 2, figsize=(10.8, 4.5), sharey=True)
        try:
            for axis, kind in zip(axes, ("entry", "exit"), strict=True):
                rows = data.loc[data["kind"].eq(kind)].sort_values("threshold")
                left = np.zeros(len(rows))
                for column, label, color in categories:
                    share = rows[column].to_numpy() / rows["detected_events"].to_numpy()
                    axis.barh(
                        range(len(rows)),
                        share,
                        left=left,
                        color=color,
                        label=label,
                        height=0.58,
                    )
                    left += share
                axis.set_yticks(
                    range(len(rows)),
                    [f"{threshold:.0%} threshold" for threshold in rows["threshold"]],
                )
                axis.set_xlim(0, 1)
                axis.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
                axis.set_xlabel("Share of detected transitions")
                axis.set_title(
                    "Architecture-share entry" if kind == "entry" else "Architecture-share exit",
                    loc="left",
                    fontsize=12,
                    fontweight="bold",
                )
                axis.grid(axis="x", color="#D1D5DB", linewidth=0.6, alpha=0.75)
                axis.spines[["top", "right", "left"]].set_visible(False)
                axis.tick_params(axis="y", length=0)
                for y, detected in enumerate(rows["detected_events"]):
                    axis.text(1.01, y, f"N={detected}", va="center", fontsize=8, color="#4B5563")
            handles, labels = axes[0].get_legend_handles_labels()
            figure.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.01))
            figure.suptitle(
                "Detected architecture transitions do not isolate a stable comparison",
                x=0.055,
                ha="left",
                fontsize=14,
                fontweight="bold",
            )
            figure.tight_layout(rect=(0, 0.13, 0.98, 0.92))
            figure.savefig(output, format="pdf", bbox_inches="tight", metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None})
        finally:
            plt.close(figure)


def load_current_jsonl(path: Path, *, consumer: str) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read a provenance-current JSONL exhibit and bind the exact bytes used."""

    with current_artifacts([path], consumer=consumer):
        identity = describe_input(path)
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

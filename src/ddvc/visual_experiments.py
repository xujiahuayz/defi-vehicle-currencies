"""Low-cost presentation experiments on the current route-only release.

These renderers deliberately reuse admitted aggregate panels.  They test visual
grammar; they do not create a new estimand or promote a finding.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.ticker import PercentFormatter

from ddvc.figure_outputs import (
    ASSET_LABELS,
    ASSET_TYPES,
    PALETTE,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


WEIGHTINGS = (
    ("count", "Intermediary episodes"),
    ("value", "Routed value"),
)


def annual_vehicle_composition(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the current year-by-scope vehicle composition exhibit."""

    required = {
        "year",
        "integration_scope",
        "asset_type",
        "episodes",
        "episode_share",
        "usd_within_20pct",
        "usd_share_within_20pct",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"intermediation-by-type exhibit is missing {', '.join(missing)}")
    data = frame[list(required)].copy()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    data = data.loc[
        data["integration_scope"].isin(["all", "single_venue", "cross_venue"])
        & data["asset_type"].isin(ASSET_TYPES)
    ]
    for column in ("episodes", "episode_share", "usd_within_20pct", "usd_share_within_20pct"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    if data.empty or data.duplicated(["year", "integration_scope", "asset_type"]).any():
        raise ValueError("intermediation-by-type exhibit lacks unique year-scope-type cells")
    if data[["episodes", "episode_share", "usd_within_20pct", "usd_share_within_20pct"]].lt(0).any().any():
        raise ValueError("intermediation-by-type exhibit contains negative mass")
    expected = set(
        pd.MultiIndex.from_product(
            [
                sorted(data["year"].unique()),
                ("all", "single_venue", "cross_venue"),
                ASSET_TYPES,
            ]
        ).tolist()
    )
    observed = set(data[["year", "integration_scope", "asset_type"]].itertuples(index=False, name=None))
    if observed != expected:
        raise ValueError("intermediation-by-type exhibit has an incomplete year-scope-type grid")
    for scope in ("all", "single_venue", "cross_venue"):
        cells = data.loc[data["integration_scope"].eq(scope)]
        for share in ("episode_share", "usd_share_within_20pct"):
            totals = cells.groupby("year", observed=True)[share].sum()
            supported = cells.groupby("year", observed=True)[
                "episodes" if share == "episode_share" else "usd_within_20pct"
            ].sum().gt(0)
            if not np.allclose(totals.loc[supported], 1, atol=1e-9, rtol=0):
                raise ValueError(f"{scope} {share} does not exhaust its supported denominator")
    return data.sort_values(["year", "integration_scope", "asset_type"], kind="stable")


def halfyear_vehicle_composition(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the half-year-by-scope vehicle composition exhibit."""

    required = {
        "period",
        "period_order",
        "integration_scope",
        "asset_type",
        "episodes",
        "episode_share",
        "usd_within_20pct",
        "usd_share_within_20pct",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"half-year intermediation exhibit is missing {', '.join(missing)}")
    data = frame[list(required)].copy()
    data["period"] = data["period"].astype(str)
    data["period_order"] = pd.to_numeric(data["period_order"], errors="raise").astype(int)
    data = data.loc[
        data["integration_scope"].isin(["all", "single_venue", "cross_venue"])
        & data["asset_type"].isin(ASSET_TYPES)
    ]
    for column in ("episodes", "episode_share", "usd_within_20pct", "usd_share_within_20pct"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    keys = ["period_order", "integration_scope", "asset_type"]
    if data.empty or data.duplicated(keys).any():
        raise ValueError("half-year intermediation exhibit lacks unique period-scope-type cells")
    period_labels = data[["period_order", "period"]].drop_duplicates()
    if period_labels.duplicated("period_order").any() or period_labels.duplicated("period").any():
        raise ValueError("half-year intermediation exhibit has ambiguous period labels")
    expected = set(
        pd.MultiIndex.from_product(
            [
                sorted(data["period_order"].unique()),
                ("all", "single_venue", "cross_venue"),
                ASSET_TYPES,
            ]
        ).tolist()
    )
    observed = set(data[keys].itertuples(index=False, name=None))
    if observed != expected:
        raise ValueError("half-year intermediation exhibit has an incomplete period-scope-type grid")
    for scope in ("all", "single_venue", "cross_venue"):
        cells = data.loc[data["integration_scope"].eq(scope)]
        for share in ("episode_share", "usd_share_within_20pct"):
            totals = cells.groupby("period_order", observed=True)[share].sum()
            supported = cells.groupby("period_order", observed=True)[
                "episodes" if share == "episode_share" else "usd_within_20pct"
            ].sum().gt(0)
            if not np.allclose(totals.loc[supported], 1, atol=1e-9, rtol=0):
                raise ValueError(f"{scope} {share} does not exhaust its supported denominator")
    return data.sort_values(keys, kind="stable")


def annual_integration_flows(frame: pd.DataFrame, *, year: int | None = None) -> pd.DataFrame:
    """Return current annual scope-by-type shares for alluvial rendering."""

    data = annual_vehicle_composition(frame)
    selected_year = int(data["year"].max()) if year is None else year
    data = data.loc[
        data["year"].eq(selected_year)
        & data["integration_scope"].isin(["single_venue", "cross_venue"])
    ]
    rows: list[dict[str, object]] = []
    for weighting, mass_column in (("count", "episodes"), ("value", "usd_within_20pct")):
        total = float(data[mass_column].sum())
        if total <= 0:
            raise ValueError(f"annual integration flow has no {weighting} support")
        for row in data.itertuples(index=False):
            mass = float(getattr(row, mass_column))
            rows.append(
                {
                    "year": selected_year,
                    "weighting": weighting,
                    "scope": row.integration_scope,
                    "asset_type": row.asset_type,
                    "mass": mass,
                    "share": mass / total,
                }
            )
    return pd.DataFrame(rows)


def integration_change_cells(
    frame: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
) -> pd.DataFrame:
    """Select share-level changes by realised integration scope."""

    required = {
        "baseline_year",
        "comparison_year",
        "integration_scope",
        "weighting",
        "value_support",
        "transformation",
        "change",
        "hac_standard_error",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"integration-rival exhibit is missing {', '.join(missing)}")
    data = frame.loc[
        pd.to_numeric(frame["baseline_year"], errors="coerce").eq(baseline_year)
        & pd.to_numeric(frame["comparison_year"], errors="coerce").eq(comparison_year)
        & frame["transformation"].eq("share_level")
        & frame["integration_scope"].isin(["all", "single_venue", "cross_venue"])
        & (
            (frame["weighting"].eq("episode") & frame["value_support"].eq("all_routes"))
            | (frame["weighting"].eq("value") & frame["value_support"].eq("within_20pct"))
        ),
        list(required),
    ].copy()
    for column in ("change", "hac_standard_error"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    if len(data) != 6 or data.duplicated(["integration_scope", "weighting"]).any():
        raise ValueError("integration-rival exhibit lacks six unique 2024-to-2026 share cells")
    return data



def _save(figure: plt.Figure, output: Path) -> None:
    figure.savefig(
        output,
        format="pdf",
        bbox_inches="tight",
        metadata={"Creator": "ddvc", "CreationDate": None, "ModDate": None},
    )



def _ribbon(axis: plt.Axes, left: tuple[float, float], right: tuple[float, float], *, color: str) -> None:
    x0, x1 = 0.14, 0.86
    l0, l1 = left
    r0, r1 = right
    vertices = [
        (x0, l0),
        (0.44, l0),
        (0.56, r0),
        (x1, r0),
        (x1, r1),
        (0.56, r1),
        (0.44, l1),
        (x0, l1),
        (x0, l0),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.LINETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CLOSEPOLY,
    ]
    axis.add_patch(PathPatch(MplPath(vertices, codes), facecolor=color, edgecolor="none", alpha=0.72))



def render_annual_composition_bands(
    frame: pd.DataFrame,
    output: Path,
    *,
    deck: bool = False,
) -> None:
    """Render the annual or half-year native-versus-stable path."""

    halfyear = "period" in frame.columns
    data = halfyear_vehicle_composition(frame) if halfyear else annual_vehicle_composition(frame)
    data = data.loc[data["integration_scope"].eq("all")]
    index = "period_order" if halfyear else "year"
    points = sorted(data[index].unique())
    tick_labels = (
        data[[index, "period"]]
        .drop_duplicates()
        .set_index(index)["period"]
        .reindex(points)
        .tolist()
        if halfyear
        else [str(point) for point in points]
    )
    display_points = points
    display_tick_labels = tick_labels
    if halfyear:
        # Keep every half-year observation but label one point per year.  Labelling
        # the opening 2018 H2 point beside 2019 H1 made the two leftmost labels
        # collide in both the paper and deck versions.
        display_indices = [
            i for i, label in enumerate(tick_labels) if str(label).endswith("H1")
        ]
        display_points = [points[i] for i in display_indices]
        display_tick_labels = [
            str(tick_labels[i]).replace(" ", "\n") for i in display_indices
        ]
    panels = (
        ("episode_share", "Intermediary positions"),
        ("usd_share_within_20pct", "Routed value"),
    )

    def _leader_runs(pivot: pd.DataFrame) -> list[tuple[str, int, int]]:
        leaders = np.where(
            pivot["stable"].gt(pivot["native"]),
            "stable",
            np.where(pivot["native"].gt(pivot["stable"]), "native", "tie"),
        )
        runs: list[tuple[str, int, int]] = []
        for year, leader in zip(pivot.index.astype(int), leaders, strict=True):
            if runs and runs[-1][0] == leader and runs[-1][2] + 1 == year:
                runs[-1] = (leader, runs[-1][1], year)
            else:
                runs.append((leader, year, year))
        return runs

    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        figure, axes = plt.subplots(1, 2, figsize=(10.8, 4.4), sharey=True)
        try:
            for axis, (column, title) in zip(axes, panels, strict=True):
                pivot = (
                    data.pivot(index=index, columns="asset_type", values=column)
                    .reindex(index=points, columns=ASSET_TYPES)
                )
                other = pivot[
                    [item for item in ASSET_TYPES if item not in {"native", "stable"}]
                ].sum(axis=1)
                axis.plot(
                    points,
                    pivot["native"],
                    color=PALETTE["native"],
                    linewidth=3.0,
                    marker="o",
                    markersize=5.0,
                    label="Native",
                    zorder=3,
                )
                axis.plot(
                    points,
                    pivot["stable"],
                    color=PALETTE["stable"],
                    linewidth=3.0,
                    marker="o",
                    markersize=5.0,
                    label="Stable",
                    zorder=3,
                )
                axis.plot(
                    points,
                    other,
                    color="#9CA3AF",
                    linewidth=1.6,
                    linestyle="--",
                    marker="o",
                    markersize=3.5,
                    label="Other types combined",
                    zorder=2,
                )
                axis.fill_between(
                    points,
                    pivot["native"],
                    pivot["stable"],
                    where=pivot["stable"].gt(pivot["native"]),
                    color=PALETTE["stable"],
                    alpha=0.12,
                    interpolate=True,
                    zorder=1,
                )
                axis.fill_between(
                    points,
                    pivot["native"],
                    pivot["stable"],
                    where=pivot["native"].gt(pivot["stable"]),
                    color=PALETTE["native"],
                    alpha=0.08,
                    interpolate=True,
                    zorder=1,
                )
                axis.set_title(title, loc="left", fontsize=12, fontweight="bold")
                axis.set_xticks(
                    display_points,
                    display_tick_labels,
                    rotation=0,
                    ha="center",
                )
                axis.set_xlim(min(points) - 0.25, max(points) + 0.25)
                axis.set_ylim(0, 1.0)
                axis.set_yticks(np.linspace(0, 1.0, 6))
                axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
                axis.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.75)
                axis.spines[["top", "right"]].set_visible(False)

                if column == "episode_share":
                    latest_year = int(pivot.index.max())
                    latest_gap = abs(
                        float(
                            pivot.loc[latest_year, "native"]
                            - pivot.loc[latest_year, "stable"]
                        )
                    )
                    stable_runs = [
                        run for run in _leader_runs(pivot) if run[0] == "stable"
                    ]
                    sustained_stable_lead = any(
                        end - start >= 1 for _, start, end in stable_runs
                    )
                    if latest_gap <= 0.02 and not sustained_stable_lead:
                        label = f"Near parity by {tick_labels[-1]}"
                    elif sustained_stable_lead:
                        label = "Stable leads in consecutive periods"
                    else:
                        label = "Native remains the period leader"
                    axis.text(
                        0.98,
                        0.97,
                        label,
                        transform=axis.transAxes,
                        ha="right",
                        va="top",
                        fontsize=8.5,
                        color="#374151",
                    )
                else:
                    runs = [
                        run for run in _leader_runs(pivot) if run[0] != "tie"
                    ][-3:]
                    labels = (
                        "Earlier stable",
                        "Native retakes",
                        "Stable regains",
                    )
                    label_heights = (0.875, 0.815, 0.875)
                    if [leader for leader, _, _ in runs] == [
                        "stable",
                        "native",
                        "stable",
                    ]:
                        for (leader, start, end), label, label_height in zip(
                            runs, labels, label_heights, strict=True
                        ):
                            colour = PALETTE[leader]
                            axis.axvspan(
                                start - 0.35,
                                end + 0.35,
                                color=colour,
                                alpha=0.045,
                                zorder=0,
                            )
                            axis.text(
                                (start + end) / 2,
                                label_height,
                                label,
                                ha="center",
                                va="top",
                                fontsize=7.2,
                                fontweight="bold",
                                color=colour,
                            )
            axes[0].set_ylabel("Share of intermediation")
            axes[1].tick_params(axis="y", labelleft=False, labelright=True, right=True)
            if deck:
                figure.tight_layout(rect=(0, 0.02, 1, 0.99))
            else:
                handles, labels = axes[0].get_legend_handles_labels()
                figure.legend(
                    handles,
                    labels,
                    frameon=False,
                    ncol=3,
                    loc="lower center",
                    bbox_to_anchor=(0.5, 0.02),
                )
                figure.tight_layout(rect=(0, 0.10, 1, 0.99))
            _save(figure, output)
        finally:
            plt.close(figure)


def render_deck_annual_composition_bands(
    frame: pd.DataFrame,
    output: Path,
) -> None:
    """Render the half-year composition path with deck-scale annotations."""

    render_annual_composition_bands(frame, output, deck=True)

def render_annual_integration_alluvial(frame: pd.DataFrame, output: Path) -> None:
    """Render latest-year integration scope by intermediary type."""

    flows = annual_integration_flows(frame)
    year = int(flows["year"].iloc[0])
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        figure, axes = plt.subplots(1, 2, figsize=(11.2, 5.2))
        try:
            for axis, (weighting, title) in zip(axes, WEIGHTINGS, strict=True):
                sample = flows.loc[flows["weighting"].eq(weighting)]
                gap = 0.025
                left_cursor = right_cursor = 1.0
                left_segments: dict[tuple[str, str], tuple[float, float]] = {}
                right_segments: dict[tuple[str, str], tuple[float, float]] = {}
                for scope in ("single_venue", "cross_venue"):
                    rows = sample.loc[sample["scope"].eq(scope)]
                    height = float(rows["share"].sum())
                    top = left_cursor
                    for asset_type in ASSET_TYPES:
                        share = float(rows.loc[rows["asset_type"].eq(asset_type), "share"].iloc[0])
                        left_segments[(scope, asset_type)] = (top - share, top)
                        top -= share
                    axis.add_patch(Rectangle((0.06, left_cursor - height), 0.08, height, facecolor="#334155", edgecolor="white"))
                    axis.text(0.04, left_cursor - height / 2, "Single venue" if scope == "single_venue" else "Cross venue", ha="right", va="center", fontsize=8)
                    left_cursor -= height + gap
                for asset_type in ASSET_TYPES:
                    rows = sample.loc[sample["asset_type"].eq(asset_type)]
                    height = float(rows["share"].sum())
                    top = right_cursor
                    for scope in ("single_venue", "cross_venue"):
                        share = float(rows.loc[rows["scope"].eq(scope), "share"].iloc[0])
                        right_segments[(scope, asset_type)] = (top - share, top)
                        top -= share
                    axis.add_patch(Rectangle((0.86, right_cursor - height), 0.08, height, facecolor=PALETTE[asset_type], edgecolor="white"))
                    axis.text(0.96, right_cursor - height / 2, ASSET_LABELS[asset_type], ha="left", va="center", fontsize=8)
                    right_cursor -= height + gap
                for scope in ("single_venue", "cross_venue"):
                    for asset_type in ASSET_TYPES:
                        _ribbon(axis, left_segments[(scope, asset_type)], right_segments[(scope, asset_type)], color=PALETTE[asset_type])
                axis.set_xlim(0, 1)
                axis.set_ylim(min(left_cursor, right_cursor) - 0.02, 1.02)
                axis.set_title(title, loc="left", fontsize=12, fontweight="bold")
                axis.axis("off")
            figure.suptitle(f"Integration and vehicle composition are separate margins in {year}", x=0.06, ha="left", fontsize=14, fontweight="bold")
            figure.text(0.995, 0.012, f"Ribbon width is the share of {year} intermediation jointly classified by venue scope and intermediary type.", ha="right", fontsize=8, color="#4B5563")
            figure.tight_layout(rect=(0, 0.04, 1, 0.94))
            _save(figure, output)
        finally:
            plt.close(figure)



def render_integration_change_forest(frame: pd.DataFrame, output: Path) -> None:
    """Render 2024-to-2026 stable-share changes with uncertainty by scope."""

    data = integration_change_cells(frame)
    scopes = ("all", "single_venue", "cross_venue")
    labels = {"all": "All routes", "single_venue": "Single venue", "cross_venue": "Cross venue"}
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        figure, axes = plt.subplots(1, 2, figsize=(10.3, 4.0), sharex=True, sharey=True)
        try:
            for axis, (weighting, support, title) in zip(
                axes,
                (("episode", "all_routes", "Intermediary episodes"), ("value", "within_20pct", "Routed value")),
                strict=True,
            ):
                sample = data.loc[data["weighting"].eq(weighting) & data["value_support"].eq(support)].set_index("integration_scope")
                y = np.arange(len(scopes))
                changes = np.array([float(sample.loc[scope, "change"]) for scope in scopes])
                errors = np.array([1.96 * float(sample.loc[scope, "hac_standard_error"]) for scope in scopes])
                axis.errorbar(changes, y, xerr=errors, fmt="o", color=PALETTE["stable"], ecolor="#64748B", capsize=3, markersize=7)
                axis.axvline(0, color="#111827", linestyle="--", linewidth=1)
                axis.set_title(title, loc="left", fontsize=12, fontweight="bold")
                axis.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
                axis.grid(axis="x", color="#D1D5DB", linewidth=0.5)
                axis.spines[["top", "right", "left"]].set_visible(False)
                axis.tick_params(axis="y", length=0)
            axes[0].set_yticks(range(len(scopes)), [labels[scope] for scope in scopes])
            figure.suptitle("Stable share rises within realised route scopes", x=0.06, ha="left", fontsize=14, fontweight="bold")
            figure.text(0.995, 0.012, "Points are 2024-to-2026 changes; bars are 95% HAC intervals.", ha="right", fontsize=8, color="#4B5563")
            figure.tight_layout(rect=(0, 0.06, 1, 0.93))
            _save(figure, output)
        finally:
            plt.close(figure)

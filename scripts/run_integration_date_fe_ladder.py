#!/usr/bin/env python3
"""Does cross-venue routing use a different vehicle, holding the day fixed?

`build_intermediation_by_type.py` already asks whether the native-to-stable
transition is confined to the cross-venue integration margin. It answers with a
year-endpoint change: the stable share in one endpoint year against another, with
calendar-day HAC. That design puts the calendar in the identifying position. A
referee is entitled to reply that the whole contrast is a time-series comparison
of two years that differ in many things besides venue integration.

This owner answers that objection the same way the excess-use ladder does, on the
other half of the paper's composition evidence. It stacks the daily panel long by
integration regime, so a day contributes one observation for single-venue routing
and one for cross-venue routing, and it absorbs the date. Identification then comes
from the SAME day's cross-section: on a given day, does the cross-venue half of the
route universe intermediate through stablecoins more than the single-venue half?

The two designs answer different questions and neither replaces the other:

  existing rival exhibits   how much the stable share MOVED between two years,
                            estimated separately inside each integration regime
  this ladder               how large the integration GAP is at any point in the
                            calendar, and whether that gap widened, with the
                            calendar absorbed rather than doing the work

The rungs are shown as a ladder rather than as a preferred column:

  R1 pooled                 no calendar control at all; the raw gap
  R2 + date FE              the within-day paired gap over the whole calendar
  R3 + date FE, weighted    the same gap at economic weight (the day's episodes)
  R4 + date FE x half       the gap early, the gap late, and their difference
  R5 + date FE x year       the gap in every year, each identified within day

State one thing plainly before anyone reads R1 against R2. Every retained day
contributes exactly one observation per regime, so the stack is balanced by
construction, the date fixed effect is exactly a within-day pairing, and the R1 and
R2 point estimates are ALGEBRAICALLY IDENTICAL. That equality is arithmetic and is
not evidence about the world. What the rungs actually deliver is elsewhere: R2
supplies the inference that respects the pairing, R3 moves the estimate by
reweighting cells toward economic size, and R4 and R5 let the gap vary over the
calendar without letting the calendar identify it. Writing the R1-R2 equality up as
"the gap survives absorbing the calendar" would be a tautology sold as a result.

The genuinely new estimand against the rival exhibits is the LEVEL of the gap. The
rival design estimates how much the stable share moved between two endpoint years
inside each regime; it never states how far apart the regimes stand. R2 states
that over all 2,332 panel days, and R5 states it year by year, which replaces a
comparison of two hand-picked endpoint years with the whole annual path.

Calendar time is a CONTROL in R2 and R3 and a robustness SPLIT in R4 and R5. It is
never the treatment. Each row records which in `calendar_role`.

Inference clusters on the date with the family's standing thirty-day Bartlett lag.
The integration dimension has exactly TWO groups and is never a clustering
dimension: CR1 over two clusters is not inference, and the 2026-08-16 correction to
the few-currency cuts of the excess-use ladder is the same mistake in another
costume. After the date is absorbed each date contributes a single paired
difference, so the date is the repeated sampling unit and serial dependence across
days is the live threat.

The outcome, denominator and value-support bands are taken unchanged from
`STABLE_SHARE_ESTIMANDS` in the panel's own owner, so a coefficient here is
directly comparable to a change in the rival exhibits. Both the share level (in
percentage points) and the log odds are estimated, because a share bounded in the
unit interval can move for a floor or ceiling reason that the level hides.

Interpretation boundary, inherited from the rival exhibit and not weakened here:
integration regime is SELECTED. Routes are not assigned to cross-venue execution,
so the gap is a descriptive composition contrast, not the causal effect of venue
integration on vehicle choice.

Reads   data/processed/intermediation_by_type_daily.parquet
Writes  output/exhibits/integration_date_fe_ladder.jsonl
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    linear_contrast,
    ols_clustered,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit

PANEL = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUT_LADDER = OUTPUT_DIR / "exhibits" / "integration_date_fe_ladder.jsonl"
CODE_SOURCES = [
    "scripts/run_integration_date_fe_ladder.py",
    "src/ddvc/analysis/regression.py",
]

# The panel's own estimand perimeter, copied from build_intermediation_by_type.py
# so that a coefficient here sits on the same outcome as a change there.
STABLE_SHARE_ESTIMANDS = (
    ("episode", "all_routes", "cnt_"),
    ("value", "all_routes", "usd_"),
    ("value", "within_2x", "usd_within_2x_"),
    ("value", "within_20pct", "usd_within_20pct_"),
)
# Two routing bases. The locked decision reserves exact two-leg routes for
# one-intermediary dominance and treats longer routes as a separate network-reach
# object, so the two are never pooled into one headline.
ROUTING_BASES = {
    "all_leg_counts": ("single_venue", "cross_venue"),
    "exact_two_leg": ("single_venue_two_leg", "cross_venue_two_leg"),
}
HAC_LAG_DAYS = 30
CLUSTERING = f"CR1 on date with a {HAC_LAG_DAYS}-day Bartlett lag"
# Below this many supported days a Bartlett lag of thirty is longer than the
# series can carry, and the rung is skipped rather than reported thin.
MIN_SUPPORTED_DAYS = 4 * HAC_LAG_DAYS


def stacked(
    panel: pd.DataFrame,
    *,
    column_prefix: str,
    scopes: tuple[str, str],
    transformation: str,
) -> pd.DataFrame:
    """Long frame of (date, integration regime) with the stable share as outcome.

    A day enters only when BOTH regimes have a positive native-plus-stable
    denominator, because the estimand is a within-day paired difference and a day
    that supports only one regime carries no information about the gap. The count
    of days lost to that requirement travels with every row.
    """
    single_scope, cross_scope = scopes
    frame = pd.DataFrame({"date": pd.to_datetime(panel["date"])})
    for label, scope in (("single_venue", single_scope), ("cross_venue", cross_scope)):
        stable = pd.to_numeric(panel[f"{column_prefix}{scope}_stable"], errors="coerce")
        native = pd.to_numeric(panel[f"{column_prefix}{scope}_native"], errors="coerce")
        denominator = stable + native
        share = stable / denominator.where(denominator.gt(0))
        if transformation == "log_odds":
            # Evaluate the log only on the interior, so a boundary day is dropped
            # rather than producing an infinity that a later mask has to hide.
            interior = share.between(0, 1, inclusive="neither")
            odds = (share / (1 - share)).where(interior)
            share = pd.Series(np.nan, index=share.index)
            share[interior] = np.log(odds[interior])
        else:
            share = share * 100.0
        frame[label] = share
        # Episodes behind the cell, used only as the economic weight in R3.
        frame[f"{label}_units"] = denominator
    frame = frame.dropna(subset=["single_venue", "cross_venue"])
    long = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": frame["date"],
                    "regime": label,
                    "y": frame[label],
                    "units": frame[f"{label}_units"],
                }
            )
            for label in ("single_venue", "cross_venue")
        ],
        ignore_index=True,
    ).sort_values(["date", "regime"], kind="stable")
    long["cross_venue"] = long["regime"].eq("cross_venue").astype(float)
    return long.reset_index(drop=True)


def fit(
    frame: pd.DataFrame,
    regressors: list[str],
    *,
    date_fe: bool,
    weights: pd.Series | None = None,
):
    """One rung: absorb the date when asked, then cluster on date with HAC."""
    y = frame["y"]
    x = frame[regressors].copy()
    groups = (frame["date"],) if date_fe else ()
    if date_fe:
        stacked_design = pd.concat([y.rename("__outcome__"), x], axis=1)
        residual = absorb_fixed_effects(stacked_design, *groups, weights=weights)
        y = residual["__outcome__"]
        x = residual[regressors]
    return ols_clustered(
        y,
        x,
        frame["date"],
        add_constant=not date_fe,
        absorbed_groups=groups,
        cluster_hac_lag=HAC_LAG_DAYS,
        weights=weights,
    )


def identity(
    *,
    routing_basis: str,
    weighting: str,
    value_support: str,
    transformation: str,
) -> dict[str, object]:
    return {
        "routing_basis": routing_basis,
        "weighting": weighting,
        "value_support": value_support,
        "transformation": transformation,
        "outcome": (
            "stable_share_pp_within_native_plus_stable"
            if transformation == "share_level"
            else "log_odds_stable_share_within_native_plus_stable"
        ),
    }


def estimate_rows(
    result,
    regressors: list[str],
    *,
    spec: str,
    calendar_role: str,
    date_fe: bool,
    weighted: bool,
    frame: pd.DataFrame,
    supported_days: int,
    dropped_days: int,
    base: dict[str, object],
) -> list[dict[str, object]]:
    """Long-format rows, one per term, each carrying its own interval.

    Every term is reported whether or not it separates from zero. The standing rule
    is that a contrast the data cannot separate is stated as prominently as one it
    can, with its interval, and never written as a confirmed ordering.
    """
    offset = 0 if date_fe else 1
    statistics = result.named_statistics(regressors, offset=offset)
    # Same t reference as the p-values, so a row can never print an interval that
    # excludes zero beside a p-value above five percent.
    critical = float(stats.t.ppf(0.975, max(result.n_clusters - 1, 1)))
    rows: list[dict[str, object]] = []
    for name in regressors:
        beta = statistics[f"{name}_beta"]
        se = statistics[f"{name}_se"]
        rows.append(
            {
                **base,
                "spec": spec,
                "term": name,
                "fixed_effects": "date" if date_fe else "none",
                "calendar_role": calendar_role,
                "weighted": bool(weighted),
                "beta": beta,
                "se": se,
                "t": statistics[f"{name}_t"],
                "p": statistics[f"{name}_p"],
                "ci_lower": beta - critical * se,
                "ci_upper": beta + critical * se,
                "separable_at_5pct": bool(statistics[f"{name}_p"] < 0.05),
                "n": int(result.n_observations),
                "supported_days": supported_days,
                "days_without_both_regimes": dropped_days,
                "clustering": CLUSTERING,
                "inference_clusters": int(result.n_clusters),
                "absorbed_df": int(result.absorbed_degrees_of_freedom),
                "interpretation_boundary": (
                    "descriptive composition contrast; integration regime is "
                    "selected and the coefficient is not a causal effect of venue "
                    "integration on vehicle choice"
                ),
            }
        )
    return rows


def contrast_row(
    result,
    regressors: list[str],
    weights: dict[str, float],
    *,
    term: str,
    spec: str,
    calendar_role: str,
    date_fe: bool,
    frame: pd.DataFrame,
    supported_days: int,
    dropped_days: int,
    base: dict[str, object],
) -> dict[str, object]:
    """A linear combination of fitted coefficients through the repo's own owner."""
    offset = 0 if date_fe else 1
    vector = np.zeros(len(result.beta))
    for name, weight in weights.items():
        vector[regressors.index(name) + offset] = weight
    evaluated = linear_contrast(result, vector)
    return {
        **base,
        "spec": spec,
        "term": term,
        "fixed_effects": "date" if date_fe else "none",
        "calendar_role": calendar_role,
        "weighted": False,
        "beta": evaluated.estimate,
        "se": evaluated.standard_error,
        "t": evaluated.t_statistic,
        "p": evaluated.p_value,
        "ci_lower": evaluated.confidence_interval_lower,
        "ci_upper": evaluated.confidence_interval_upper,
        "separable_at_5pct": bool(evaluated.p_value < 0.05),
        "n": int(result.n_observations),
        "supported_days": supported_days,
        "days_without_both_regimes": dropped_days,
        "clustering": CLUSTERING,
        "inference_clusters": int(result.n_clusters),
        "absorbed_df": int(result.absorbed_degrees_of_freedom),
        "interpretation_boundary": (
            "descriptive composition contrast; integration regime is selected and "
            "the coefficient is not a causal effect of venue integration on vehicle "
            "choice"
        ),
    }


def ladder(panel: pd.DataFrame) -> list[dict[str, object]]:
    """Four rungs on every routing basis, weighting, support band and transform."""
    rows: list[dict[str, object]] = []
    total_days = int(pd.to_datetime(panel["date"]).nunique())
    for routing_basis, scopes in ROUTING_BASES.items():
        for weighting, value_support, column_prefix in STABLE_SHARE_ESTIMANDS:
            for transformation in ("share_level", "log_odds"):
                frame = stacked(
                    panel,
                    column_prefix=column_prefix,
                    scopes=scopes,
                    transformation=transformation,
                )
                supported_days = int(frame["date"].nunique())
                dropped_days = total_days - supported_days
                if supported_days < MIN_SUPPORTED_DAYS:
                    continue
                base = identity(
                    routing_basis=routing_basis,
                    weighting=weighting,
                    value_support=value_support,
                    transformation=transformation,
                )
                common = dict(
                    frame=frame,
                    supported_days=supported_days,
                    dropped_days=dropped_days,
                    base=base,
                )

                # Regime means, so the gap can be read against the levels it sits on.
                for regime in ("single_venue", "cross_venue"):
                    rows.append(
                        {
                            **base,
                            "spec": "R0 regime mean",
                            "term": f"mean_{regime}",
                            "fixed_effects": "none",
                            "calendar_role": "uncontrolled",
                            "weighted": False,
                            "beta": float(frame.loc[frame["regime"].eq(regime), "y"].mean()),
                            "se": None,
                            "t": None,
                            "p": None,
                            "ci_lower": None,
                            "ci_upper": None,
                            "separable_at_5pct": None,
                            "n": int(frame["regime"].eq(regime).sum()),
                            "supported_days": supported_days,
                            "days_without_both_regimes": dropped_days,
                            "clustering": "none; descriptive mean",
                            "inference_clusters": None,
                            "absorbed_df": 0,
                            "interpretation_boundary": "descriptive level",
                        }
                    )

                result = fit(frame, ["cross_venue"], date_fe=False)
                rows += estimate_rows(
                    result,
                    ["cross_venue"],
                    spec="R1 pooled",
                    calendar_role="uncontrolled",
                    date_fe=False,
                    weighted=False,
                    **common,
                )

                result = fit(frame, ["cross_venue"], date_fe=True)
                rows += estimate_rows(
                    result,
                    ["cross_venue"],
                    spec="R2 + date FE",
                    calendar_role="control",
                    date_fe=True,
                    weighted=False,
                    **common,
                )

                # Economic weight: the day-regime cell's own native-plus-stable
                # episodes (or dollars). Zero-unit cells cannot be weighted and are
                # already excluded by the positive-denominator requirement.
                weights = frame["units"].astype(float)
                if weights.gt(0).all() and np.isfinite(weights).all():
                    result = fit(frame, ["cross_venue"], date_fe=True, weights=weights)
                    rows += estimate_rows(
                        result,
                        ["cross_venue"],
                        spec="R3 + date FE, weighted by cell units",
                        calendar_role="control",
                        date_fe=True,
                        weighted=True,
                        **common,
                    )

                # R4 demotes the calendar to a sample split. The late-half main
                # effect is a function of the date and is absorbed with it, so only
                # the interaction is identified alongside the gap.
                split = frame.copy()
                median_date = split["date"].median()
                split["late"] = split["date"].gt(median_date).astype(float)
                split["cross_venue_x_late"] = split["cross_venue"] * split["late"]
                terms = ["cross_venue", "cross_venue_x_late"]
                result = fit(split, terms, date_fe=True)
                rows += estimate_rows(
                    result,
                    terms,
                    spec="R4 + date FE x calendar half",
                    calendar_role="robustness split",
                    date_fe=True,
                    weighted=False,
                    **common,
                )
                rows.append(
                    contrast_row(
                        result,
                        terms,
                        {"cross_venue": 1.0, "cross_venue_x_late": 1.0},
                        term="cross_venue in late half",
                        spec="R4 + date FE x calendar half",
                        calendar_role="robustness split",
                        date_fe=True,
                        **common,
                    )
                )

                # R5 replaces the rival design's two hand-picked endpoint years
                # with the whole annual path. Each year's gap is still a within-day
                # paired difference; the year enters only by letting the gap vary,
                # never as the outcome's own regressor, which the date absorbs.
                rows += annual_path(**common)
    return rows


# A year needs enough paired days for its own gap to be a measurement rather than
# a handful of days given a coefficient. Sixty is two months of paired support.
MIN_YEAR_DAYS = 60


def annual_path(
    frame: pd.DataFrame,
    *,
    supported_days: int,
    dropped_days: int,
    base: dict[str, object],
) -> list[dict[str, object]]:
    """The integration gap in every adequately supported year, within day."""
    split = frame.copy()
    split["year"] = split["date"].dt.year
    days_by_year = split.groupby("year")["date"].nunique()
    years = [int(year) for year in days_by_year[days_by_year >= MIN_YEAR_DAYS].index]
    if len(years) < 2:
        return []
    split = split[split["year"].isin(years)].copy()
    terms: list[str] = []
    for year in years:
        name = f"cross_venue_{year}"
        split[name] = split["cross_venue"] * split["year"].eq(year).astype(float)
        terms.append(name)
    # No omitted year and no `cross_venue` main effect: the year indicators
    # partition the cross-venue observations, so each coefficient IS that year's
    # gap rather than a difference from a base year.
    result = fit(split, terms, date_fe=True)
    return estimate_rows(
        result,
        terms,
        spec="R5 + date FE x year",
        calendar_role="robustness split",
        date_fe=True,
        weighted=False,
        frame=split,
        supported_days=int(split["date"].nunique()),
        dropped_days=dropped_days + (supported_days - int(split["date"].nunique())),
        base=base,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-dates", type=int, default=0, help="smoke-test subsample; writes nothing"
    )
    arguments = parser.parse_args()

    panel = pd.read_parquet(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])
    if arguments.max_dates:
        keep = sorted(panel["date"].unique())[: arguments.max_dates]
        panel = panel[panel["date"].isin(keep)].reset_index(drop=True)
    print(
        f"panel: {len(panel):,} days, {panel['date'].min():%Y-%m-%d} to "
        f"{panel['date'].max():%Y-%m-%d}",
        flush=True,
    )

    estimates = pd.DataFrame(ladder(panel))
    if estimates.empty:
        print("no routing basis carried enough supported days to estimate")
        return 1

    if arguments.max_dates:
        print(estimates.to_string())
        print("\nsmoke run: exhibit not written")
        return 0

    write_exhibit(
        estimates,
        OUT_LADDER,
        code_sources=CODE_SOURCES,
        inputs=[PANEL],
        notes=(
            "within-day cross-section of the daily stable share within native plus "
            "stable, stacked by venue-integration regime; date fixed effects absorb "
            "the calendar and the calendar half enters only as a robustness split; "
            "CR1 on date with a thirty-day Bartlett lag, never on the two-group "
            "integration dimension; descriptive because integration regime is "
            "selected"
        ),
    )

    headline = estimates[
        estimates["spec"].isin(("R1 pooled", "R2 + date FE"))
        & estimates["transformation"].eq("share_level")
    ]
    print(
        "\n"
        + headline[
            [
                "routing_basis",
                "weighting",
                "value_support",
                "spec",
                "beta",
                "se",
                "p",
                "ci_lower",
                "ci_upper",
                "supported_days",
            ]
        ].to_string(index=False, float_format=lambda v: f"{v:,.4f}")
    )
    print(f"\nwrote {OUT_LADDER.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

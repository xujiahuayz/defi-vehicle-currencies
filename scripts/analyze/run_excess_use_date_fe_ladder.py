#!/usr/bin/env python3
"""Who takes the intermediary role within a day, once the calendar is absorbed?

The paper's primary extent measure, vehicle excess use, is a ratio: a token's share
of the day's intermediary episodes divided by its share of the day's endpoint
episodes. Read across years it invites the objection that the whole result is a
time-series contrast, so the answer is whatever the calendar happens to do.

This owner answers that objection by re-specifying the same construct as a
regression coefficient and putting the calendar inside a date fixed effect. The
outcome is the token-day intermediary count share in percentage points; the
regressor of interest is the token's own endpoint (trade-demand) count share in the
same units; and every rung above the pooled baseline absorbs the date, so
identification comes from the cross-section of tokens observed on the SAME day.

This is a re-specification of the excess-use construct, not a redefinition of it.
The ratio estimand asks how far intermediary use exceeds trade demand at the level
of a token-day. The regression asks the same question with two extra degrees of
freedom the ratio cannot express: a slope, which says whether intermediary use
rises more or less than one-for-one with demand, and a type intercept, which says
how much of the role a class of asset takes beyond what its own demand implies.
Both are reported; neither replaces the ratio exhibits, which remain the primary
extent measure.

The ladder is deliberately shown as a ladder rather than as a preferred column:

  L1 pooled type dummies         no calendar control at all
  L2 + date FE                   the pure within-day cross-section
  L3 + date FE + own demand      excess use as a coefficient, within day
  L4 two-way token + date FE     within a token and within a day: pass-through
                                 stripped of between-token composition
  L5 demand x type, date FE      does the pass-through differ by asset class
  L6 L3 weighted by route units  the same question at economic weight

Calendar time is a CONTROL here, and in the two half-sample rows a robustness
SPLIT. It is never the identifying variation. That distinction is the point of the
exercise and is recorded per row in the `calendar_role` field.

Base categories matter and are the reason a naive version of this script returns
nothing. Once the date fixed effect is absorbed it spans the constant, so a full
set of type dummies is collinear with it. Every sample therefore drops one class
and reports which: the full sample uses the residual `other` bucket as its base,
and the classified and candidate samples use `stable`, because on those samples
`other` is empty by construction.

The five-candidate and all-classified magnitudes are both reported for every
contrast, and neither may be quoted alone: the samples put different amounts of
share mass behind the same dummy, so the coefficients are not comparable in size
even though they answer the same question.

Mechanicalness screens run in this file and are reported beside the estimates,
because intermediary share and endpoint share are drawn from the same day's route
universe. The three screens are documented at `screens()`.

Reads   data/processed/vehicle_excess_use_daily.parquet
Writes  output/exhibits/excess_use_date_fe_ladder.jsonl
        output/exhibits/excess_use_date_fe_screens.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    linear_contrast,
    ols_clustered,
)
from ddvc.asset_types import VEHICLE_CANDIDATE_SYMBOLS, backing
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit

PANEL = REPO_ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
OUT_LADDER = OUTPUT_DIR / "exhibits" / "excess_use_date_fe_ladder.jsonl"
OUT_SCREENS = OUTPUT_DIR / "exhibits" / "excess_use_date_fe_screens.jsonl"
CODE_SOURCES = [
    "scripts/analyze/run_excess_use_date_fe_ladder.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/vehicle_extent.py",
]

# A token-day enters only if the token is quoted as an endpoint that day and the
# day gives it enough route units for its two shares to be measured rather than
# rounded. Twenty is the panel's own thin-cell floor; the sensitivity at 5 and 100
# is reported in the screens exhibit rather than chosen silently.
MIN_ROUTE_UNITS = 20
TYPES = ("native", "stable", "staked_native", "imported")
COLUMNS = [
    "date",
    "token",
    "symbol",
    "asset_type",
    "intermediate_count_share",
    "endpoint_count_share",
    "intermediate_routes",
    "endpoint_routes",
    "endpoint_supported",
    "routes_clean",
]


def load(min_route_units: int = MIN_ROUTE_UNITS) -> pd.DataFrame:
    """Return the estimation frame plus the day totals its shares are built on.

    The day totals are summed over the WHOLE panel before the thin-cell filter,
    because that is the denominator the panel's shares actually use. Recomputing
    them from the filtered frame would silently renormalise the outcome.
    """
    raw = pd.read_parquet(PANEL, columns=COLUMNS)
    totals = raw.groupby("date", sort=False).agg(
        day_intermediary_episodes=("intermediate_routes", "sum"),
        day_endpoint_episodes=("endpoint_routes", "sum"),
    )
    units = raw["intermediate_routes"].fillna(0) + raw["endpoint_routes"].fillna(0)
    frame = raw[
        (units > min_route_units) & raw["endpoint_supported"].astype(bool)
    ].copy()
    frame["route_units"] = units.loc[frame.index].astype(float)
    frame = frame.join(totals, on="date")
    # Percentage points, so a coefficient reads as pp of the day's episodes.
    frame["y"] = frame["intermediate_count_share"].astype(float) * 100.0
    frame["demand"] = frame["endpoint_count_share"].astype(float) * 100.0
    frame = frame[np.isfinite(frame["y"]) & np.isfinite(frame["demand"])].copy()
    for asset_type in TYPES:
        frame[asset_type] = (frame["asset_type"] == asset_type).astype(float)
    return frame.reset_index(drop=True)


def design(frame: pd.DataFrame, base: str) -> list[str]:
    """Type dummies present in this sample, excluding the declared base class."""
    present = [t for t in TYPES if frame[t].sum() > 0]
    if base != "other" and base not in present:
        raise ValueError(f"base class {base!r} is absent from the sample")
    return [t for t in present if t != base]


# Below this many tokens the token dimension is not a cluster population. Two-way
# CR1 takes its reference distribution from the SMALLER dimension, so clustering a
# five-token cross-section on token leaves four degrees of freedom and an interval
# that is wide for a bookkeeping reason rather than an economic one. Thirty is the
# conventional floor at which cluster-robust asymptotics are treated as usable.
TOKEN_CLUSTER_FLOOR = 30
# For the few-token cuts the repeated sampling unit is the DAY, not the token, and
# the live dependence is serial: the same five assets are observed on 2,258
# consecutive days. So those rows cluster on date with the project's standing
# thirty-day Bartlett lag instead of pretending to a token cluster population.
HAC_LAG_DAYS = 30


def clustering_of(frame: pd.DataFrame) -> tuple[str, bool]:
    """Return the inference label and whether the token dimension is usable."""
    many_tokens = frame["token"].nunique() >= TOKEN_CLUSTER_FLOOR
    label = (
        "two-way CR1 on date and token"
        if many_tokens
        else f"CR1 on date with a {HAC_LAG_DAYS}-day Bartlett lag"
    )
    return label, many_tokens


def fit(
    frame: pd.DataFrame,
    regressors: list[str],
    *,
    fixed_effects: tuple[str, ...] = (),
    weights: pd.Series | None = None,
    outcome: str = "y",
):
    """One rung: absorb the declared fixed effects, then cluster by `clustering_of`."""
    y = frame[outcome]
    x = frame[regressors].copy()
    add_constant = not fixed_effects
    groups = tuple(frame[name] for name in fixed_effects)
    if fixed_effects:
        stacked = pd.concat([y.rename("__outcome__"), x], axis=1)
        residual = absorb_fixed_effects(stacked, *groups, weights=weights)
        y = residual["__outcome__"]
        x = residual[regressors]
    _, many_tokens = clustering_of(frame)
    return ols_clustered(
        y,
        x,
        frame["date"],
        add_constant=add_constant,
        absorbed_groups=groups,
        additional_clusters=(frame["token"],) if many_tokens else (),
        cluster_hac_lag=None if many_tokens else HAC_LAG_DAYS,
        weights=weights,
    )


def rows_from(
    result,
    regressors: list[str],
    *,
    family: str,
    spec: str,
    sample: str,
    base: str,
    fixed_effects: tuple[str, ...],
    calendar_role: str,
    frame: pd.DataFrame,
    weighted: bool = False,
    outcome: str = "intermediary_count_share_pp",
) -> list[dict[str, object]]:
    """Long-format estimate rows, one per term, each carrying its own interval."""
    offset = 0 if fixed_effects else 1
    statistics = result.named_statistics(regressors, offset=offset)
    # Intervals use the same t reference as the p-values, so a row can never report
    # an interval that excludes zero beside a p-value above five percent.
    critical = float(stats.t.ppf(0.975, max(result.n_clusters - 1, 1)))
    clustering, _ = clustering_of(frame)
    out: list[dict[str, object]] = []
    for name in regressors:
        beta = statistics[f"{name}_beta"]
        se = statistics[f"{name}_se"]
        out.append(
            {
                "family": family,
                "spec": spec,
                "sample": sample,
                "base_class": base,
                "fixed_effects": "+".join(fixed_effects) if fixed_effects else "none",
                "calendar_role": calendar_role,
                "weighted": bool(weighted),
                "outcome": outcome,
                "term": name,
                "beta": beta,
                "se": se,
                "t": statistics[f"{name}_t"],
                "p": statistics[f"{name}_p"],
                "ci_lower": beta - critical * se,
                "ci_upper": beta + critical * se,
                "n": int(result.n_observations),
                "dates": int(frame["date"].nunique()),
                "tokens": int(frame["token"].nunique()),
                "clustering": clustering,
                "inference_clusters": int(result.n_clusters),
                "absorbed_df": int(result.absorbed_degrees_of_freedom),
            }
        )
    return out


def contrast_row(
    result,
    regressors: list[str],
    left: str,
    right: str,
    *,
    family: str,
    spec: str,
    sample: str,
    base: str,
    fixed_effects: tuple[str, ...],
    calendar_role: str,
    frame: pd.DataFrame,
) -> dict[str, object]:
    """beta(left) - beta(right) through the repo's own clustered contrast owner.

    Reported whether or not it separates from zero. The project's standing rule is
    that a contrast the data cannot separate is stated as prominently as one it can,
    with its interval, and never written as a confirmed ordering.
    """
    offset = 0 if fixed_effects else 1
    weights = np.zeros(len(result.beta))
    weights[regressors.index(left) + offset] = 1.0
    weights[regressors.index(right) + offset] = -1.0
    evaluated = linear_contrast(result, weights)
    return {
        "family": family,
        "spec": spec,
        "sample": sample,
        "base_class": base,
        "fixed_effects": "+".join(fixed_effects) if fixed_effects else "none",
        "calendar_role": calendar_role,
        "weighted": False,
        "outcome": "intermediary_count_share_pp",
        "term": f"{left} - {right}",
        "beta": evaluated.estimate,
        "se": evaluated.standard_error,
        "t": evaluated.t_statistic,
        "p": evaluated.p_value,
        "ci_lower": evaluated.confidence_interval_lower,
        "ci_upper": evaluated.confidence_interval_upper,
        "n": int(result.n_observations),
        "dates": int(frame["date"].nunique()),
        "tokens": int(frame["token"].nunique()),
        "clustering": clustering_of(frame)[0],
        "inference_clusters": int(result.n_clusters),
        "absorbed_df": int(result.absorbed_degrees_of_freedom),
        "separable_at_5pct": bool(evaluated.p_value < 0.05),
    }


def ladder(frame: pd.DataFrame, *, heavy: bool = True) -> list[dict[str, object]]:
    """The six rungs on the full estimation sample, base class `other`."""
    base = "other"
    dummies = design(frame, base)
    rows: list[dict[str, object]] = []

    common = dict(family="ladder", sample="all_endpoint_supported", base=base, frame=frame)

    result = fit(frame, dummies)
    rows += rows_from(
        result, dummies, spec="L1 pooled type dummies", fixed_effects=(),
        calendar_role="uncontrolled", **common,
    )

    result = fit(frame, dummies, fixed_effects=("date",))
    rows += rows_from(
        result, dummies, spec="L2 + date FE", fixed_effects=("date",),
        calendar_role="control", **common,
    )

    conditional = dummies + ["demand"]
    result_l3 = fit(frame, conditional, fixed_effects=("date",))
    rows += rows_from(
        result_l3, conditional, spec="L3 + date FE + own demand share",
        fixed_effects=("date",), calendar_role="control", **common,
    )
    for left, right in (("stable", "native"), ("stable", "imported"), ("native", "imported")):
        if left in conditional and right in conditional:
            rows.append(
                contrast_row(
                    result_l3, conditional, left, right,
                    spec="L3 + date FE + own demand share", fixed_effects=("date",),
                    calendar_role="control", **common,
                )
            )

    if heavy:
        result = fit(frame, ["demand"], fixed_effects=("date", "token"))
        rows += rows_from(
            result, ["demand"], spec="L4 two-way token + date FE",
            fixed_effects=("date", "token"), calendar_role="control", **common,
        )

    interacted = frame.copy()
    slopes = ["demand"]
    for asset_type in design(frame, base):
        column = f"demand_x_{asset_type}"
        interacted[column] = interacted["demand"] * interacted[asset_type]
        slopes.append(column)
    terms = slopes + dummies
    result_l5 = fit(interacted, terms, fixed_effects=("date",))
    rows += rows_from(
        result_l5, terms, spec="L5 demand x type, date FE", fixed_effects=("date",),
        calendar_role="control", family="ladder", sample="all_endpoint_supported",
        base=base, frame=interacted,
    )
    for left, right in (
        ("demand_x_stable", "demand_x_native"),
        ("demand_x_stable", "demand_x_imported"),
        ("demand_x_native", "demand_x_imported"),
    ):
        if left in terms and right in terms:
            rows.append(
                contrast_row(
                    result_l5, terms, left, right, spec="L5 demand x type, date FE",
                    fixed_effects=("date",), calendar_role="control", family="ladder",
                    sample="all_endpoint_supported", base=base, frame=interacted,
                )
            )

    result = fit(frame, conditional, fixed_effects=("date",), weights=frame["route_units"])
    rows += rows_from(
        result, conditional, spec="L6 L3 weighted by route units",
        fixed_effects=("date",), calendar_role="control", weighted=True, **common,
    )
    return rows


def sample_cuts(frame: pd.DataFrame) -> list[dict[str, object]]:
    """The same within-day design on the samples a referee will ask for.

    Both magnitudes are produced together on purpose. The candidate sample carries
    almost all of the share mass in five tokens, so its dummies are large; the
    classified sample spreads the same question over 37 tokens and its dummies are
    small. Quoting one without the other would misstate the size of the effect.
    """
    rows: list[dict[str, object]] = []
    classified = frame[frame["asset_type"] != "other"].copy()
    candidates = frame[frame["symbol"].isin(VEHICLE_CANDIDATE_SYMBOLS)].copy()
    for sample, part in (
        ("classified_types_only", classified),
        ("five_named_candidates", candidates),
    ):
        base = "stable"
        dummies = design(part, base)
        terms = dummies + ["demand"]
        result = fit(part, terms, fixed_effects=("date",))
        rows += rows_from(
            result, terms, family="sample_cut",
            spec="date FE + own demand share, stable base", sample=sample, base=base,
            fixed_effects=("date",), calendar_role="control", frame=part,
        )
    return rows


def regime_cuts(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Which KIND of stable takes the role, within a day.

    Two crossings of the type axis. The backing regime separates a fiat-reserve
    claim from an on-chain-collateralised one, so the prose can stop treating "the
    stable numeraire" as one instrument. The token cut separates USDC from USDT,
    which the rotation results already distinguish. Both are estimated inside the
    stable class with a fiat-reserve base, so the coefficient reads as a difference
    against the fiat-reserve claim on the same day.
    """
    rows: list[dict[str, object]] = []
    stables = frame[frame["asset_type"] == "stable"].copy()
    if stables.empty:
        return rows
    regimes = {
        token: backing(token, when=None) for token in stables["token"].unique()
    }
    stables["backing"] = stables["token"].map(regimes)
    counts = stables["backing"].value_counts()
    keep = [r for r in counts.index if counts[r] >= 500 and r != "not_applicable"]
    if "fiat_reserve" in keep and len(keep) > 1:
        cut = stables[stables["backing"].isin(keep)].copy()
        terms = []
        for regime in keep:
            if regime == "fiat_reserve":
                continue
            column = f"backing_{regime}"
            cut[column] = (cut["backing"] == regime).astype(float)
            terms.append(column)
        terms.append("demand")
        result = fit(cut, terms, fixed_effects=("date",))
        rows += rows_from(
            result, terms, family="regime_cut",
            spec="backing regime, date FE + own demand share",
            sample="stable_class_only", base="fiat_reserve", fixed_effects=("date",),
            calendar_role="control", frame=cut,
        )

    pair = stables[stables["symbol"].isin(("USDC", "USDT"))].copy()
    if pair["symbol"].nunique() == 2:
        pair["usdt"] = (pair["symbol"] == "USDT").astype(float)
        terms = ["usdt", "demand"]
        result = fit(pair, terms, fixed_effects=("date",))
        rows += rows_from(
            result, terms, family="regime_cut",
            spec="USDT versus USDC, date FE + own demand share",
            sample="usdc_usdt_only", base="USDC", fixed_effects=("date",),
            calendar_role="control", frame=pair,
        )
    return rows


def calendar_split(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Refit L3 on each calendar half.

    Calendar time is a SAMPLE SPLIT in these two rows and nothing else. If the
    within-day cross-section is the same in both halves, the answer is not a period
    artefact; if it is not, the difference is reported rather than pooled away.
    """
    rows: list[dict[str, object]] = []
    median = frame["date"].median()
    halves = (
        ("first_calendar_half", frame[frame["date"] <= median]),
        ("second_calendar_half", frame[frame["date"] > median]),
    )
    for sample, part in halves:
        part = part.copy()
        base = "other"
        terms = design(part, base) + ["demand"]
        result = fit(part, terms, fixed_effects=("date",))
        produced = rows_from(
            result, terms, family="calendar_split",
            spec="L3 refit on calendar half", sample=sample, base=base,
            fixed_effects=("date",), calendar_role="sample_split", frame=part,
        )
        for row in produced:
            row["date_min"] = str(part["date"].min().date())
            row["date_max"] = str(part["date"].max().date())
        rows += produced
    return rows


def screens(frame: pd.DataFrame, *, heavy: bool = True) -> list[dict[str, object]]:
    """Is the conditional cross-section mechanically true by construction?

    Both variables are token-day shares of the SAME day's route universe, so three
    mechanical channels have to be bounded before the estimate can be read
    economically.

    CROWD-OUT CEILING. A token cannot be the intermediary on a route it is an
    endpoint of, so its intermediary count is capped at the day's clean routes minus
    the routes it terminates. If that cap bound often, the demand slope would be
    mechanically pushed NEGATIVE and the design would be measuring an accounting
    identity. The screen reports how close token-days sit to the cap.

    SHARED-DENOMINATOR SELF-INCLUSION. A token's own numerator sits inside the
    denominator of its own share on both sides, which alone induces a positive
    association. The screen refits the headline rung on leave-own-out shares, where
    each token's share is taken against the day's episodes EXCLUDING its own, so the
    self-inclusion channel is removed by construction.

    THIN-CELL SENSITIVITY. The twenty-route-unit floor is a choice. The screen refits
    the headline rung at 5 and 100 so the floor is reported rather than assumed.
    """
    rows: list[dict[str, object]] = []

    feasible = (frame["routes_clean"] - frame["endpoint_routes"]).clip(lower=1)
    utilisation = frame["intermediate_routes"] / feasible
    rows.append(
        {
            "screen": "crowd_out_ceiling",
            "question": (
                "how close does the day's intermediary count sit to the routes the "
                "token does not itself terminate"
            ),
            "n": int(len(frame)),
            "mean_ceiling_utilisation": float(utilisation.mean()),
            "median_ceiling_utilisation": float(utilisation.median()),
            "p99_ceiling_utilisation": float(utilisation.quantile(0.99)),
            "max_ceiling_utilisation": float(utilisation.max()),
            "share_above_half_ceiling": float((utilisation > 0.5).mean()),
            "share_above_nine_tenths_ceiling": float((utilisation > 0.9).mean()),
            "verdict_rule": (
                "the crowd-out channel can only push the demand slope negative; it "
                "cannot manufacture a positive one"
            ),
        }
    )

    leave_out = frame.copy()
    intermediary_rest = (
        leave_out["day_intermediary_episodes"] - leave_out["intermediate_routes"]
    )
    endpoint_rest = leave_out["day_endpoint_episodes"] - leave_out["endpoint_routes"]
    leave_out["y_loo"] = (
        leave_out["intermediate_routes"] / intermediary_rest.where(intermediary_rest > 0)
    ) * 100.0
    leave_out["demand_loo"] = (
        leave_out["endpoint_routes"] / endpoint_rest.where(endpoint_rest > 0)
    ) * 100.0
    leave_out = leave_out[
        np.isfinite(leave_out["y_loo"]) & np.isfinite(leave_out["demand_loo"])
    ].copy()
    leave_out["demand"] = leave_out["demand_loo"]
    terms = design(leave_out, "other") + ["demand"]
    result = fit(leave_out, terms, fixed_effects=("date",), outcome="y_loo")
    statistics = result.named_statistics(terms)
    rows.append(
        {
            "screen": "leave_own_out_denominator",
            "question": (
                "does the demand slope survive when neither share includes the "
                "token's own episodes in its denominator"
            ),
            "n": int(result.n_observations),
            "dates": int(leave_out["date"].nunique()),
            "demand_beta": statistics["demand_beta"],
            "demand_se": statistics["demand_se"],
            "demand_p": statistics["demand_p"],
            "native_beta": statistics.get("native_beta"),
            "native_se": statistics.get("native_se"),
            "stable_beta": statistics.get("stable_beta"),
            "stable_se": statistics.get("stable_se"),
            "verdict_rule": (
                "a slope that collapses to zero here would mean the association is "
                "the shared denominator and not the routing decision"
            ),
        }
    )

    if heavy:
        for floor in (5, 100):
            cut = load(min_route_units=floor)
            terms = design(cut, "other") + ["demand"]
            result = fit(cut, terms, fixed_effects=("date",))
            statistics = result.named_statistics(terms)
            rows.append(
                {
                    "screen": f"thin_cell_floor_{floor}",
                    "question": (
                        "does the headline rung move when the minimum route-unit "
                        "floor changes"
                    ),
                    "n": int(result.n_observations),
                    "dates": int(cut["date"].nunique()),
                    "demand_beta": statistics["demand_beta"],
                    "demand_se": statistics["demand_se"],
                    "demand_p": statistics["demand_p"],
                    "native_beta": statistics.get("native_beta"),
                    "native_se": statistics.get("native_se"),
                    "stable_beta": statistics.get("stable_beta"),
                    "stable_se": statistics.get("stable_se"),
                    "verdict_rule": (
                        "the floor is a reported choice, not a tuned one"
                    ),
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-heavy",
        action="store_true",
        help="omit the two-way token+date rung and the thin-cell refits (smoke runs)",
    )
    parser.add_argument("--max-dates", type=int, default=0, help="smoke-test subsample")
    arguments = parser.parse_args()

    frame = load()
    if arguments.max_dates:
        keep = sorted(frame["date"].unique())[: arguments.max_dates]
        frame = frame[frame["date"].isin(keep)].reset_index(drop=True)
    print(
        f"estimation sample: {len(frame):,} token-days, "
        f"{frame['token'].nunique():,} tokens, {frame['date'].nunique():,} dates, "
        f"minimum {MIN_ROUTE_UNITS} route units",
        flush=True,
    )
    print(frame["asset_type"].value_counts().to_dict(), flush=True)

    heavy = not arguments.skip_heavy
    rows = ladder(frame, heavy=heavy)
    rows += sample_cuts(frame)
    rows += regime_cuts(frame)
    rows += calendar_split(frame)
    estimates = pd.DataFrame(rows)

    screen_rows = screens(frame, heavy=heavy)

    if arguments.max_dates:
        print(estimates.to_string())
        print(pd.DataFrame(screen_rows).to_string())
        print("\nsmoke run: exhibits not written")
        return 0

    write_exhibit(
        estimates,
        OUT_LADDER,
        code_sources=CODE_SOURCES,
        inputs=[PANEL],
        notes=(
            "within-day cross-section of the token-day intermediary count share on "
            "the token's own endpoint count share, both in percentage points; date "
            "fixed effects absorb the calendar; two-way CR1 clustering on date and "
            "token; every contrast reported with its interval whether or not it "
            "separates from zero"
        ),
    )
    write_exhibit(
        pd.DataFrame(screen_rows),
        OUT_SCREENS,
        code_sources=CODE_SOURCES,
        inputs=[PANEL],
        notes=(
            "mechanicalness screens for the share-on-share specification: crowd-out "
            "ceiling incidence, leave-own-out denominators, thin-cell floor "
            "sensitivity"
        ),
    )

    shown = estimates[estimates["family"].isin(("ladder", "sample_cut"))]
    print("\n" + shown[
        ["spec", "sample", "term", "beta", "se", "p", "ci_lower", "ci_upper", "n"]
    ].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
    print(f"\nwrote {OUT_LADDER.relative_to(REPO_ROOT)}")
    print(f"wrote {OUT_SCREENS.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

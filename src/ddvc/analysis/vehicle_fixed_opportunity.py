"""Fixed-cohort conditioning of the vehicle-transition estimand.

The transition family measures one share, stable over stable-plus-native, on the
exact two-leg routing strata. An aggregate share of that kind moves for two very
different reasons, and the pooled number cannot tell them apart: the units that
were already there may route differently, or the set of units may have changed.
Amiti, Itskhoki and Konings face the identical problem with invoicing-currency
shares and answer it by re-estimating on continuing firm-product-destination
triplets, so that the currency composition of a fixed set of units is what moves.
This module applies that design here.

Three cohorts are defined on the released endpoint-candidate choice panel, each
inside its own routing stratum, and each by one estimand-independent rule: a cell
is in the cohort when it carries at least one observed route in the baseline year
*and* at least one in the comparison year. The second and third each refine the
first; they do not refine each other.

`persistent_pair`
    Ordered endpoint pairs active in both years. Holds the corridor set fixed, so
    corridors that appeared or disappeared cannot carry the measured rotation.
`persistent_pair_candidate`
    Ordered pair by intermediating candidate. Holds the observed candidate menu
    inside a corridor fixed as well, which is the closest analogue of the
    continuing-triplet restriction: a candidate that only ever appears in one
    endpoint year cannot contribute.
`persistent_pair_venue_sequence`
    Ordered pair by realised venue sequence. Reported, and deliberately flagged,
    as a bad control: the venue sequence is chosen jointly with the vehicle, so
    conditioning on it partials out part of the mechanism rather than isolating
    an opportunity set. Its estimate bounds how much of the rotation coincides
    with a change in realised routing architecture; it is not a causal control.

Three boundaries are deliberate.

First, the cohort is selected using both endpoints, so the conditional estimand
is "the change among units continuously active across the window" and is not an
unbiased estimate of the full-universe change. That is the design, not a defect,
and `cohort_mass_ledger` publishes exactly how much of each endpoint year's
denominator the cohort retains so a reader can weigh it.

Second, every series is measured on the *pooled* stratum's common month-and-day
calendar, so the conditional estimate answers the same calendar question as the
pooled one. Alongside the conditional share the module also publishes each
cohort's contribution to the pooled share, `M_cohort / D_pooled`, and its
complement. Those two sum to the pooled share on every day and the estimator is
linear in its outcome, so their fitted changes must sum to the fitted pooled
change; `assert_cohort_additivity` checks that identity rather than trusting it.

Third, the attack this module serves also asks for reach, notional and
search-regret conditioning. Those need the validated transaction-state frontier,
which is not released. `unsupported_dimension_ledger` records each of them as
unsupported with its exact blocker, in the open, so that the fitted cohort half
is never read as the whole attack.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    year_endpoint_change,
)
from ddvc.analysis.vehicle_backing_regimes import (
    ESTIMAND_MASS_COLUMNS,
    NATIVE_STRATUM,
    SCOPE_FILTERS,
    TRANSFORMATIONS,
)

ATTACK_ID = "fixed_opportunity_conditioning"
POOLED_COHORT = "all_routes"
# Cohort identity is the set of columns whose observed activity must span both
# endpoint years. The second and third each refine the first by construction, so
# neither can retain more mass than `persistent_pair`; they do not refine each
# other, and their two estimates are never ordered against one another.
COHORT_KEYS: dict[str, tuple[str, ...]] = {
    "persistent_pair": ("src", "tgt"),
    "persistent_pair_candidate": ("src", "tgt", "candidate_address"),
    "persistent_pair_venue_sequence": ("src", "tgt", "venue_sequence"),
}
# The venue-sequence cohort is published with this flag attached to every row it
# produces, because a reader who takes it for an opportunity control would draw
# the wrong conclusion from it.
BAD_CONTROL_COHORTS = frozenset({"persistent_pair_venue_sequence"})
CONDITIONAL_ROLE = "conditional"
AGGREGATE_ROLE = "aggregate"
CONTRIBUTION_IN_ROLE = "contribution_in"
CONTRIBUTION_OUT_ROLE = "contribution_out"
CONTRIBUTION_ROLES = (CONTRIBUTION_IN_ROLE, CONTRIBUTION_OUT_ROLE)
# Activity is counted in routes for every cohort and every estimand, so that the
# cohort is one fixed set of units rather than a different set per weighting.
ACTIVITY_COLUMN = "route_count"
# A cohort estimate that lands near zero has to be reported as an interval that
# either does or does not exclude the economically relevant magnitude, never as a
# bare failure to reject. The interval uses the estimator's own t reference, the
# same one `year_endpoint_change` builds its p-value from.
CONFIDENCE_LEVEL = 0.95
# The dimensions this attack asks for that the released panel cannot carry, with
# the exact blocker each waits on.
UNSUPPORTED_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "observed_reach",
        "blocked_transaction_state_frontier",
        "the set of pools and venues reachable at the moment of the route is not "
        "released, so a cohort cannot be held fixed on the opportunity set itself",
    ),
    (
        "trade_notional",
        "blocked_transaction_state_frontier",
        "the choice panel aggregates route count and value to the cell-day, so a "
        "fixed-notional cohort cannot be constructed from it",
    ),
    (
        "search_regret_cell",
        "blocked_transaction_state_frontier",
        "within-reach search regret needs exact pre-transaction state and the best "
        "reachable alternative, neither of which is released",
    ),
)
REQUIRED_CHOICE_COLUMNS = (
    "date",
    "src",
    "tgt",
    "candidate_address",
    "candidate_type",
    "integration_scope",
    "venue_sequence",
    *ESTIMAND_MASS_COLUMNS.values(),
)
IDENTITY_COLUMNS = (
    "routing_scope",
    "cohort",
    "stratum_role",
    "weighting",
    "value_support",
    "transformation",
    "baseline_year",
    "comparison_year",
)


def _validated_window(
    choices: pd.DataFrame, *, baseline_year: int, comparison_year: int
) -> pd.DataFrame:
    """Return the contrast-window rows after checking the panel's own identity."""

    missing = [column for column in REQUIRED_CHOICE_COLUMNS if column not in choices.columns]
    if missing:
        raise ValueError(f"fixed-opportunity panel lacks required columns: {missing}")
    if comparison_year <= baseline_year:
        raise ValueError("fixed-opportunity contrast needs an ordered endpoint-year pair")
    frame = choices.loc[:, list(REQUIRED_CHOICE_COLUMNS)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any():
        raise ValueError("fixed-opportunity panel carries undated choice rows")
    frame["year"] = frame["date"].dt.year
    frame = frame[frame["year"].between(baseline_year, comparison_year)]
    if frame.empty:
        raise ValueError("fixed-opportunity panel has no rows inside the contrast window")
    types = set(frame["candidate_type"].unique())
    unexpected = sorted(types - {NATIVE_STRATUM, "stable"})
    if unexpected:
        raise ValueError(
            f"fixed-opportunity denominator identity requires native and stable only: {unexpected}"
        )
    for column in ("src", "tgt", "candidate_address", "venue_sequence"):
        if frame[column].isna().any():
            raise ValueError(f"fixed-opportunity cohort identity is undefined: {column} is null")
    return frame.reset_index(drop=True)


def _persistent_mask(
    scoped: pd.DataFrame,
    keys: tuple[str, ...],
    *,
    baseline_year: int,
    comparison_year: int,
) -> tuple[np.ndarray, int, int]:
    """Flag rows whose cohort cell carries observed routes in both endpoint years."""

    endpoints = scoped[scoped["year"].isin((baseline_year, comparison_year))]
    if endpoints.empty:
        raise ValueError("fixed-opportunity cohort has no endpoint-year rows")
    activity = (
        endpoints.groupby([*keys, "year"], observed=True)[ACTIVITY_COLUMN]
        .sum()
        .unstack("year")
        .reindex(columns=[baseline_year, comparison_year])
        .fillna(0.0)
    )
    persistent = activity.index[
        activity[baseline_year].gt(0) & activity[comparison_year].gt(0)
    ]
    if len(keys) == 1:
        observed = pd.Index(scoped[keys[0]])
    else:
        observed = pd.MultiIndex.from_frame(scoped.loc[:, list(keys)])
    return observed.isin(persistent), int(len(persistent)), int(len(activity))


def cohort_cell_ledger(
    choices: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
) -> pd.DataFrame:
    """Report how many cells each cohort keeps out of its stratum's universe."""

    frame = _validated_window(
        choices, baseline_year=baseline_year, comparison_year=comparison_year
    )
    rows: list[dict[str, object]] = []
    for scope, venue in SCOPE_FILTERS.items():
        scoped = frame if venue is None else frame[frame["integration_scope"].eq(venue)]
        if scoped.empty:
            raise ValueError(f"fixed-opportunity panel has no rows on routing stratum {scope}")
        for cohort, keys in COHORT_KEYS.items():
            _, persistent, universe = _persistent_mask(
                scoped, keys, baseline_year=baseline_year, comparison_year=comparison_year
            )
            rows.append(
                {
                    "record_type": "cohort_cell_ledger",
                    "routing_scope": scope,
                    "cohort": cohort,
                    "cohort_identity": "+".join(keys),
                    "persistent_cells": persistent,
                    "endpoint_universe_cells": universe,
                    "persistent_cell_share": (
                        persistent / universe if universe else None
                    ),
                    "baseline_year": baseline_year,
                    "comparison_year": comparison_year,
                    "is_bad_control": cohort in BAD_CONTROL_COHORTS,
                }
            )
    return pd.DataFrame(rows)


def fixed_opportunity_daily_shares(
    choices: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
) -> pd.DataFrame:
    """Build the pooled, conditional and contribution daily series by stratum.

    One row per date, routing stratum, estimand, cohort and role. The pooled row
    carries the family's own share. Each cohort carries its conditional share on
    its own denominator, and its contribution to the pooled share together with
    the complement's; those two sum to the pooled share on every day.
    """

    frame = _validated_window(
        choices, baseline_year=baseline_year, comparison_year=comparison_year
    )
    rows: list[pd.DataFrame] = []
    for scope, venue in SCOPE_FILTERS.items():
        scoped = frame if venue is None else frame[frame["integration_scope"].eq(venue)]
        if scoped.empty:
            raise ValueError(f"fixed-opportunity panel has no rows on routing stratum {scope}")
        masks = {
            cohort: _persistent_mask(
                scoped, keys, baseline_year=baseline_year, comparison_year=comparison_year
            )[0]
            for cohort, keys in COHORT_KEYS.items()
        }
        stable = scoped["candidate_type"].eq("stable").to_numpy()
        for (weighting, value_support), column in ESTIMAND_MASS_COLUMNS.items():
            mass = scoped[column].to_numpy(dtype=float)
            wide = pd.DataFrame({"date": scoped["date"].to_numpy()})
            wide["denominator"] = mass
            wide["numerator"] = np.where(stable, mass, 0.0)
            for cohort, mask in masks.items():
                wide[f"denominator__{cohort}"] = np.where(mask, mass, 0.0)
                wide[f"numerator__{cohort}"] = np.where(
                    mask & stable, mass, 0.0
                )
            daily = wide.groupby("date", observed=True).sum().sort_index()
            daily = daily[daily["denominator"].gt(0)]
            if daily.empty:
                raise ValueError(f"fixed-opportunity stratum {scope} has no supported day")
            dates = pd.Series(daily.index, index=daily.index)
            years = dates.dt.year
            keep = common_calendar_day_mask(
                dates, years, baseline_year=baseline_year, comparison_year=comparison_year
            )
            daily, years = daily[keep], years[keep]
            observed_years = sorted(int(value) for value in years.unique())
            if baseline_year not in observed_years or comparison_year not in observed_years:
                raise ValueError(
                    f"fixed-opportunity stratum {scope} lacks one endpoint year "
                    "after calendar balance"
                )
            common = {
                "date": daily.index,
                "year": years.to_numpy(),
                "routing_scope": scope,
                "weighting": weighting,
                "value_support": value_support,
            }
            rows.append(
                pd.DataFrame(
                    {
                        **common,
                        "cohort": POOLED_COHORT,
                        "stratum_role": AGGREGATE_ROLE,
                        "is_bad_control": False,
                        "mass": daily["numerator"].to_numpy(),
                        "denominator": daily["denominator"].to_numpy(),
                        "pooled_denominator": daily["denominator"].to_numpy(),
                        "share": (
                            daily["numerator"] / daily["denominator"]
                        ).to_numpy(),
                    }
                )
            )
            for cohort in COHORT_KEYS:
                inside_mass = daily[f"numerator__{cohort}"]
                inside_denominator = daily[f"denominator__{cohort}"]
                supported = inside_denominator.gt(0)
                rows.append(
                    pd.DataFrame(
                        {
                            **{
                                key: (
                                    value[supported.to_numpy()]
                                    if isinstance(value, np.ndarray)
                                    else value
                                )
                                for key, value in common.items()
                                if key != "date"
                            },
                            "date": daily.index[supported.to_numpy()],
                            "cohort": cohort,
                            "stratum_role": CONDITIONAL_ROLE,
                            "is_bad_control": cohort in BAD_CONTROL_COHORTS,
                            "mass": inside_mass[supported].to_numpy(),
                            "denominator": inside_denominator[supported].to_numpy(),
                            "pooled_denominator": daily["denominator"][
                                supported
                            ].to_numpy(),
                            "share": (
                                inside_mass[supported] / inside_denominator[supported]
                            ).to_numpy(),
                        }
                    )
                )
                for role, numerator in (
                    (CONTRIBUTION_IN_ROLE, inside_mass),
                    (CONTRIBUTION_OUT_ROLE, daily["numerator"] - inside_mass),
                ):
                    rows.append(
                        pd.DataFrame(
                            {
                                **common,
                                "cohort": cohort,
                                "stratum_role": role,
                                "is_bad_control": cohort in BAD_CONTROL_COHORTS,
                                "mass": numerator.to_numpy(),
                                "denominator": daily["denominator"].to_numpy(),
                                "pooled_denominator": daily["denominator"].to_numpy(),
                                "share": (
                                    numerator / daily["denominator"]
                                ).to_numpy(),
                            }
                        )
                    )
    daily_panel = pd.concat(rows, ignore_index=True)
    if not daily_panel["share"].between(0, 1).all():
        raise ValueError("fixed-opportunity daily shares left the unit interval")
    return daily_panel.sort_values(
        ["routing_scope", "weighting", "value_support", "cohort", "stratum_role", "date"],
        kind="stable",
        ignore_index=True,
    )


def _transformed(sample: pd.DataFrame, transformation: str) -> pd.DataFrame:
    """Apply the family's own transformation rule to one daily share sample."""

    if transformation == "log_odds":
        inside = sample[sample["share"].between(0, 1, inclusive="neither")].copy()
        inside["estimand"] = np.log(inside["share"] / (1 - inside["share"]))
        return inside
    kept = sample.copy()
    kept["estimand"] = kept["share"]
    return kept


def fixed_opportunity_support(
    daily: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    minimum_endpoint_days: int,
) -> pd.DataFrame:
    """Gate every cohort specification on its own retained endpoint-year days.

    The row also carries the share of the stratum's denominator the cohort keeps
    in each endpoint year, because a conditional estimate on a cohort that holds
    a tenth of the economy means something different from one that holds most of
    it, and the reader should not have to guess which this is.
    """

    if minimum_endpoint_days < 2:
        raise ValueError("fixed-opportunity support minimum must be at least two days")
    rows: list[dict[str, object]] = []
    keys = ["routing_scope", "cohort", "stratum_role", "weighting", "value_support"]
    for identity, sample in daily.groupby(keys, observed=True, sort=False):
        fields = dict(zip(keys, identity, strict=True))
        endpoint = sample[sample["year"].isin((baseline_year, comparison_year))]
        retained = endpoint.groupby("year", observed=True)[
            ["denominator", "pooled_denominator"]
        ].sum()
        for transformation in TRANSFORMATIONS:
            kept = _transformed(sample, transformation)
            counts = kept.groupby("year", observed=True).size()
            baseline_days = int(counts.get(baseline_year, 0))
            comparison_days = int(counts.get(comparison_year, 0))
            supported = min(baseline_days, comparison_days) >= minimum_endpoint_days
            rows.append(
                {
                    "record_type": "support",
                    **fields,
                    "is_bad_control": bool(sample["is_bad_control"].iloc[0]),
                    "transformation": transformation,
                    "baseline_year": baseline_year,
                    "comparison_year": comparison_year,
                    "baseline_supported_days": baseline_days,
                    "comparison_supported_days": comparison_days,
                    "minimum_endpoint_days": minimum_endpoint_days,
                    "baseline_denominator_share": _retained_share(retained, baseline_year),
                    "comparison_denominator_share": _retained_share(retained, comparison_year),
                    "fit_supported": supported,
                    "support_reason": (
                        "pass"
                        if supported
                        else "retained endpoint-year days below the declared HAC horizon"
                    ),
                }
            )
    return pd.DataFrame(rows)


def _retained_share(retained: pd.DataFrame, year: int) -> float | None:
    if year not in retained.index:
        return None
    pooled = float(retained.loc[year, "pooled_denominator"])
    if pooled <= 0:
        return None
    return float(retained.loc[year, "denominator"]) / pooled


def cohort_mass_ledger(
    daily: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
) -> pd.DataFrame:
    """Publish each cohort's retained denominator mass in both endpoint years.

    This is the quantity that decides how far a conditional estimate travels. It
    is reported per stratum and estimand because episodes and value weight the
    same cohort very differently.
    """

    conditional = daily[daily["stratum_role"].eq(CONDITIONAL_ROLE)]
    if conditional.empty:
        raise ValueError("fixed-opportunity mass ledger has no conditional rows")
    keys = ["routing_scope", "cohort", "weighting", "value_support"]
    rows: list[dict[str, object]] = []
    for identity, sample in conditional.groupby(keys, observed=True, sort=False):
        fields = dict(zip(keys, identity, strict=True))
        endpoint = sample[sample["year"].isin((baseline_year, comparison_year))]
        retained = endpoint.groupby("year", observed=True)[
            ["denominator", "pooled_denominator", "mass"]
        ].sum()
        rows.append(
            {
                "record_type": "cohort_mass_ledger",
                **fields,
                "is_bad_control": bool(sample["is_bad_control"].iloc[0]),
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "baseline_denominator_share": _retained_share(retained, baseline_year),
                "comparison_denominator_share": _retained_share(retained, comparison_year),
                "baseline_cohort_share": _cohort_share(retained, baseline_year),
                "comparison_cohort_share": _cohort_share(retained, comparison_year),
                "selection_note": (
                    "cohort membership is decided using both endpoint years, so the "
                    "conditional estimand is the change among continuously active "
                    "cells and is not the full-universe change"
                ),
            }
        )
    return pd.DataFrame(rows)


def _cohort_share(retained: pd.DataFrame, year: int) -> float | None:
    if year not in retained.index:
        return None
    denominator = float(retained.loc[year, "denominator"])
    if denominator <= 0:
        return None
    return float(retained.loc[year, "mass"]) / denominator


def unsupported_dimension_ledger() -> pd.DataFrame:
    """Record the attack dimensions the released panel cannot carry, in the open.

    The rows deliberately omit `attack_id`: the runner stamps one attack id across
    every record it publishes, so carrying a second copy here would either
    duplicate the column or let the two disagree.
    """

    return pd.DataFrame(
        [
            {
                "record_type": "unsupported_dimension",
                "dimension": dimension,
                "blocker": blocker,
                "reason": reason,
                "fitted": False,
            }
            for dimension, blocker, reason in UNSUPPORTED_DIMENSIONS
        ]
    )


def fixed_opportunity_tests(
    daily: pd.DataFrame,
    support: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int,
) -> pd.DataFrame:
    """Fit every supported cohort specification with the family's own estimator."""

    supported = support[
        support["record_type"].eq("support") & support["fit_supported"].astype(bool)
    ]
    keys = ["routing_scope", "cohort", "stratum_role", "weighting", "value_support"]
    rows: list[dict[str, object]] = []
    for record in supported.itertuples(index=False):
        fields = {key: getattr(record, key) for key in keys}
        mask = np.ones(len(daily), dtype=bool)
        for key, value in fields.items():
            mask &= daily[key].to_numpy() == value
        sample = _transformed(daily[mask], record.transformation)
        estimate = year_endpoint_change(
            sample["estimand"],
            sample["year"],
            baseline_year=baseline_year,
            comparison_year=comparison_year,
            hac_lag=hac_lag,
            dates=sample["date"],
        )
        critical = float(
            stats.t.ppf(0.5 + CONFIDENCE_LEVEL / 2, estimate.degrees_freedom)
        )
        half_width = critical * estimate.standard_error
        rows.append(
            {
                **fields,
                "is_bad_control": bool(record.is_bad_control),
                "transformation": record.transformation,
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "baseline_daily_mean": estimate.baseline_mean,
                "comparison_daily_mean": estimate.comparison_mean,
                "change": estimate.change,
                "hac_standard_error": estimate.standard_error,
                "t_statistic": estimate.t_statistic,
                "p_value": estimate.p_value,
                "confidence_level": CONFIDENCE_LEVEL,
                "confidence_interval_lower": estimate.change - half_width,
                "confidence_interval_upper": estimate.change + half_width,
                "degrees_freedom": estimate.degrees_freedom,
                "days": estimate.n_observations,
                "hac_lag_days": hac_lag,
                "baseline_denominator_share": record.baseline_denominator_share,
                "comparison_denominator_share": record.comparison_denominator_share,
                "calendar_support": (
                    "daily observations at calendar month-and-day positions observed in both "
                    "endpoint years of the pooled stratum; calendar-day HAC excludes "
                    "unsupported gaps"
                ),
                "share_denominator": (
                    "native_plus_stable inside the cohort"
                    if fields["stratum_role"] == CONDITIONAL_ROLE
                    else "native_plus_stable on the full stratum"
                ),
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("fixed-opportunity family fitted no supported specification")
    # Multiplicity is controlled across the simultaneous conditional tests inside
    # one estimand and transformation. The pooled row is the comparison they are
    # judged against, and the two contribution rows are one identity rather than
    # two further hypotheses, so neither enters the family.
    conditional = result["stratum_role"].eq(CONDITIONAL_ROLE)
    family = ["baseline_year", "comparison_year", "weighting", "value_support", "transformation"]
    result["p_value_holm"] = np.nan
    result.loc[conditional, "p_value_holm"] = (
        result[conditional]
        .groupby(family, sort=False)["p_value"]
        .transform(holm_adjusted_pvalues)
    )
    return result.sort_values(
        ["weighting", "value_support", "transformation", "routing_scope", "cohort", "stratum_role"],
        kind="stable",
        ignore_index=True,
    )


def cohort_additivity_failures(checked: pd.DataFrame) -> pd.DataFrame:
    """Return the checked cells whose contribution terms miss the pooled change."""

    checkable = checked[checked["checked"].astype(bool)]
    return checkable[checkable["absolute_difference"].astype(float) > checkable["tolerance"]]


def assert_cohort_additivity(
    estimates: pd.DataFrame,
    *,
    tolerance: float = 1e-9,
    strict: bool = True,
) -> pd.DataFrame:
    """Check that each cohort's two contribution changes sum to the pooled change.

    The identity holds because the in-cohort and out-of-cohort contributions
    divide one denominator on one day set and the estimator is linear in its
    outcome. Where either contribution is gated out the cell is reported as
    unchecked rather than silently passing. Log odds is not additive and is never
    checked here.

    `strict=False` returns the same frame without raising, for a caller that must
    publish the failed check as support evidence before refusing to publish the
    estimates it failed on.
    """

    fitted = estimates[estimates["transformation"].eq("share_level")]
    rows: list[dict[str, object]] = []
    keys = ["routing_scope", "weighting", "value_support"]
    for identity, cell in fitted.groupby(keys, observed=True, sort=False):
        fields = dict(zip(keys, identity, strict=True))
        aggregate = cell[cell["stratum_role"].eq(AGGREGATE_ROLE)]
        pooled = float(aggregate["change"].iloc[0]) if len(aggregate) == 1 else float("nan")
        for cohort in sorted(set(cell["cohort"]) - {POOLED_COHORT}):
            terms = cell[
                cell["cohort"].eq(cohort) & cell["stratum_role"].isin(CONTRIBUTION_ROLES)
            ]
            missing = sorted(set(CONTRIBUTION_ROLES) - set(terms["stratum_role"]))
            checked = bool(len(aggregate) == 1 and not missing)
            summed = float(terms["change"].sum())
            rows.append(
                {
                    "record_type": "cohort_additive_decomposition",
                    **fields,
                    "cohort": cohort,
                    "transformation": "share_level",
                    "contribution_change_sum": summed,
                    "pooled_change": pooled,
                    "absolute_difference": abs(summed - pooled) if checked else None,
                    "tolerance": tolerance,
                    "checked": checked,
                    "gated_roles": ",".join(missing) if missing else "none",
                }
            )
    result = pd.DataFrame(rows)
    broken = cohort_additivity_failures(result)
    if strict and not broken.empty:
        raise ValueError(
            "cohort contributions do not sum to the pooled change: "
            f"{broken[[*keys, 'cohort', 'absolute_difference']].to_dict('records')}"
        )
    return result

"""Dated-backing-regime stratification of the vehicle-transition estimand.

The transition family measures one share, stable over stable-plus-native, on the
exact two-leg routing strata. `stable` is a class, not an instrument. Four papers
in this project's corpus exist because backing regimes behave differently, and
`ddvc.asset_types.backing` is dated for exactly that reason: DAI and FRAX cannot
carry one label across this sample. Reporting the pooled share alone therefore
leaves a rival standing — that the measured rotation is a re-composition inside
`stable`, or an artifact of a label that moved under a fixed candidate.

This module answers that rival with the same estimand, cut by dated regime. The
numerator becomes the mass of one regime and the denominator does not move, so
the regime shares sum to the pooled share on every day. `year_endpoint_change` is
linear in its outcome, so the fitted regime changes sum to the fitted pooled
change on the same universe; `assert_additive_decomposition` checks that identity
rather than trusting it, and the runner refuses to publish if it fails.

Two boundaries are deliberate. First, thin regimes are gated, not fitted and
footnoted: a specification whose retained endpoint-year day count falls below the
HAC horizon is written to the support ledger with its reason and never fitted.
Second, the panel is the released endpoint-candidate universe, which is not the
type-level route universe of `intermediation_by_type_daily`; `universe_reconciliation`
reports the pooled change on both so a reader can see how far the decomposition
travels, instead of a silent claim that it decomposes the headline number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    year_endpoint_change,
)
from ddvc.asset_types import BACKINGS

# The three exact two-leg strata of the transition family, expressed as filters on
# the released choice panel's realised integration scope. The runner asserts this
# key order equals `VEHICLE_TRANSITION_SCOPES`, so the perimeter cannot drift.
SCOPE_FILTERS: dict[str, str | None] = {
    "two_leg": None,
    "single_venue_two_leg": "single_venue",
    "cross_venue_two_leg": "cross_venue",
}
# The transition family's two estimands, mapped onto the choice panel's own mass
# columns. Episode weighting counts routes; value weighting uses the 20 percent
# coherence support, which is the family's strict-value denominator.
ESTIMAND_MASS_COLUMNS: dict[tuple[str, str], str] = {
    ("episode", "all_routes"): "route_count",
    ("value", "within_20pct"): "within_20pct_value_usd",
}
TRANSFORMATIONS = ("share_level", "log_odds")
AGGREGATE_STRATUM = "all_stable"
NATIVE_STRATUM = "native"
# A dated label is required. `backing()` returns `time_varying` only when it is
# called without a date, and `not_applicable` outside the stable type, so either
# value on a stable row means the panel lost its date and the regime cut is void.
UNDATED_REGIMES = ("time_varying", "not_applicable")
IDENTITY_COLUMNS = (
    "routing_scope",
    "backing_regime",
    "weighting",
    "value_support",
    "transformation",
    "baseline_year",
    "comparison_year",
)
REQUIRED_CHOICE_COLUMNS = (
    "date",
    "candidate_address",
    "candidate_symbol",
    "candidate_type",
    "backing_regime",
    "integration_scope",
    *ESTIMAND_MASS_COLUMNS.values(),
)


def _validated_window(
    choices: pd.DataFrame, *, baseline_year: int, comparison_year: int
) -> pd.DataFrame:
    """Return the contrast-window rows after checking the panel's own identity."""

    missing = [column for column in REQUIRED_CHOICE_COLUMNS if column not in choices.columns]
    if missing:
        raise ValueError(f"backing-regime panel lacks required columns: {missing}")
    if comparison_year <= baseline_year:
        raise ValueError("backing-regime contrast needs an ordered endpoint-year pair")
    frame = choices.loc[:, list(REQUIRED_CHOICE_COLUMNS)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any():
        raise ValueError("backing-regime panel carries undated choice rows")
    frame["year"] = frame["date"].dt.year
    frame = frame[frame["year"].between(baseline_year, comparison_year)]
    if frame.empty:
        raise ValueError("backing-regime panel has no rows inside the contrast window")
    types = set(frame["candidate_type"].unique())
    unexpected = sorted(types - {NATIVE_STRATUM, "stable"})
    if unexpected:
        raise ValueError(
            f"backing-regime denominator identity requires native and stable only: {unexpected}"
        )
    stable = frame["candidate_type"].eq("stable")
    labels = set(frame.loc[stable, "backing_regime"].unique())
    unknown = sorted(labels - set(BACKINGS))
    if unknown:
        raise ValueError(f"backing-regime panel carries labels outside the taxonomy: {unknown}")
    undated = sorted(labels & set(UNDATED_REGIMES))
    if undated:
        raise ValueError(f"backing-regime panel carries undated stable labels: {undated}")
    off_type = frame.loc[~stable, "backing_regime"].ne("not_applicable")
    if bool(off_type.any()):
        raise ValueError("backing-regime panel labels a non-stable candidate with a regime")
    return frame


def observed_regimes(frame: pd.DataFrame) -> list[str]:
    """Return the dated regimes present on stable rows, in taxonomy order."""

    present = set(frame.loc[frame["candidate_type"].eq("stable"), "backing_regime"].unique())
    ordered = [regime for regime in BACKINGS if regime in present]
    if not ordered:
        raise ValueError("backing-regime panel carries no stable mass in the contrast window")
    return ordered


def backing_regime_daily_shares(
    choices: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
) -> pd.DataFrame:
    """Build daily regime shares of the stable-plus-native denominator by stratum.

    One row per date, routing stratum, estimand and regime, plus the pooled
    `all_stable` row on the identical denominator. Days are restricted to the
    month-and-day positions observed in both endpoint years, exactly as the pooled
    transition sample is, so the two estimates answer the same calendar question.
    """

    frame = _validated_window(
        choices, baseline_year=baseline_year, comparison_year=comparison_year
    )
    regimes = observed_regimes(frame)
    frame["stratum"] = np.where(
        frame["candidate_type"].eq(NATIVE_STRATUM), NATIVE_STRATUM, frame["backing_regime"]
    )
    rows: list[pd.DataFrame] = []
    for scope, venue in SCOPE_FILTERS.items():
        scoped = frame if venue is None else frame[frame["integration_scope"].eq(venue)]
        if scoped.empty:
            raise ValueError(f"backing-regime panel has no rows on routing stratum {scope}")
        for (weighting, value_support), column in ESTIMAND_MASS_COLUMNS.items():
            mass = (
                scoped.groupby(["date", "stratum"], observed=True)[column]
                .sum()
                .unstack("stratum")
                .reindex(columns=[NATIVE_STRATUM, *regimes])
                .fillna(0.0)
                .sort_index()
            )
            stable_mass = mass[regimes].sum(axis=1)
            denominator = stable_mass + mass[NATIVE_STRATUM]
            supported = denominator.gt(0)
            mass, stable_mass, denominator = (
                mass[supported],
                stable_mass[supported],
                denominator[supported],
            )
            if mass.empty:
                raise ValueError(f"backing-regime stratum {scope} has no supported day")
            years = pd.Series(mass.index, index=mass.index).dt.year
            keep = common_calendar_day_mask(
                pd.Series(mass.index, index=mass.index),
                years,
                baseline_year=baseline_year,
                comparison_year=comparison_year,
            )
            mass, stable_mass, denominator, years = (
                mass[keep],
                stable_mass[keep],
                denominator[keep],
                years[keep],
            )
            observed_years = sorted(int(value) for value in years.unique())
            if baseline_year not in observed_years or comparison_year not in observed_years:
                raise ValueError(
                    f"backing-regime stratum {scope} lacks one endpoint year after calendar balance"
                )
            for stratum in (*regimes, AGGREGATE_STRATUM):
                numerator = stable_mass if stratum == AGGREGATE_STRATUM else mass[stratum]
                rows.append(
                    pd.DataFrame(
                        {
                            "date": mass.index,
                            "year": years.to_numpy(),
                            "routing_scope": scope,
                            "weighting": weighting,
                            "value_support": value_support,
                            "backing_regime": stratum,
                            "stratum_role": (
                                "aggregate" if stratum == AGGREGATE_STRATUM else "regime"
                            ),
                            "mass": numerator.to_numpy(dtype=float),
                            "stable_mass": stable_mass.to_numpy(dtype=float),
                            "denominator": denominator.to_numpy(dtype=float),
                            "share": (numerator / denominator).to_numpy(dtype=float),
                        }
                    )
                )
    daily = pd.concat(rows, ignore_index=True)
    return daily.sort_values(
        ["routing_scope", "weighting", "value_support", "backing_regime", "date"],
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


def backing_regime_support(
    daily: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    minimum_endpoint_days: int,
) -> pd.DataFrame:
    """Gate every regime specification on its own retained endpoint-year days.

    A thin regime is a support statement, not a missing result: the row records
    the retained days, the regime's share of stable mass in each endpoint year,
    and the exact reason the specification is not fitted.
    """

    if minimum_endpoint_days < 2:
        raise ValueError("backing-regime support minimum must be at least two days")
    rows: list[dict[str, object]] = []
    keys = ["routing_scope", "weighting", "value_support", "backing_regime", "stratum_role"]
    for identity, sample in daily.groupby(keys, observed=True, sort=False):
        fields = dict(zip(keys, identity, strict=True))
        endpoint = sample[sample["year"].isin((baseline_year, comparison_year))]
        mass = endpoint.groupby("year", observed=True)[["mass", "stable_mass"]].sum()
        for transformation in TRANSFORMATIONS:
            retained = _transformed(sample, transformation)
            counts = retained.groupby("year", observed=True).size()
            baseline_days = int(counts.get(baseline_year, 0))
            comparison_days = int(counts.get(comparison_year, 0))
            supported = min(baseline_days, comparison_days) >= minimum_endpoint_days
            rows.append(
                {
                    "record_type": "support",
                    **fields,
                    "transformation": transformation,
                    "baseline_year": baseline_year,
                    "comparison_year": comparison_year,
                    "baseline_supported_days": baseline_days,
                    "comparison_supported_days": comparison_days,
                    "minimum_endpoint_days": minimum_endpoint_days,
                    "baseline_share_of_stable_mass": _mass_share(mass, baseline_year),
                    "comparison_share_of_stable_mass": _mass_share(mass, comparison_year),
                    "fit_supported": supported,
                    "support_reason": (
                        "pass"
                        if supported
                        else "retained endpoint-year days below the declared HAC horizon"
                    ),
                }
            )
    return pd.DataFrame(rows)


def _mass_share(mass: pd.DataFrame, year: int) -> float | None:
    if year not in mass.index:
        return None
    stable = float(mass.loc[year, "stable_mass"])
    if stable <= 0:
        return None
    return float(mass.loc[year, "mass"]) / stable


def backing_regime_tests(
    daily: pd.DataFrame,
    support: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int,
) -> pd.DataFrame:
    """Fit every supported regime specification with the family's own estimator."""

    supported = support[
        support["record_type"].eq("support") & support["fit_supported"].astype(bool)
    ]
    keys = ["routing_scope", "weighting", "value_support", "backing_regime", "stratum_role"]
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
        rows.append(
            {
                **fields,
                "transformation": record.transformation,
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "baseline_daily_mean": estimate.baseline_mean,
                "comparison_daily_mean": estimate.comparison_mean,
                "change": estimate.change,
                "hac_standard_error": estimate.standard_error,
                "t_statistic": estimate.t_statistic,
                "p_value": estimate.p_value,
                "days": estimate.n_observations,
                "hac_lag_days": hac_lag,
                "calendar_support": (
                    "daily observations at calendar month-and-day positions observed in both "
                    "endpoint years; calendar-day HAC excludes unsupported gaps"
                ),
                "share_denominator": "native_plus_stable",
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("backing-regime family fitted no supported specification")
    # Multiplicity is controlled across the simultaneous regime tests inside one
    # estimand and transformation. The pooled `all_stable` row is their sum, not an
    # additional hypothesis, so it is excluded from the family it aggregates.
    regime = result["stratum_role"].eq("regime")
    family = ["baseline_year", "comparison_year", "weighting", "value_support", "transformation"]
    result["p_value_holm"] = np.nan
    result.loc[regime, "p_value_holm"] = (
        result[regime].groupby(family, sort=False)["p_value"].transform(holm_adjusted_pvalues)
    )
    return result.sort_values(
        ["weighting", "value_support", "transformation", "routing_scope", "backing_regime"],
        kind="stable",
        ignore_index=True,
    )


def additivity_failures(checked: pd.DataFrame) -> pd.DataFrame:
    """Return the checked cells whose regime terms miss the pooled change."""

    checkable = checked[checked["checked"].astype(bool)]
    return checkable[checkable["absolute_difference"].astype(float) > checkable["tolerance"]]


def assert_additive_decomposition(
    estimates: pd.DataFrame,
    support: pd.DataFrame,
    *,
    tolerance: float = 1e-9,
    strict: bool = True,
) -> pd.DataFrame:
    """Check that fitted regime changes sum to the fitted pooled change.

    The identity holds only where every regime in a cell is fitted at share level:
    the estimator is linear in the outcome and the regime shares sum to the pooled
    share on the same denominator and the same days. Where a regime is gated out,
    the cell is reported as unchecked with the missing regimes named, and the
    caller decides. Log odds is not additive and is never checked here.

    `strict=False` returns the same frame without raising, for a caller that must
    publish the failed check as support evidence before it refuses to publish the
    estimates it failed on.
    """

    fitted = estimates[estimates["transformation"].eq("share_level")]
    declared = support[
        support["record_type"].eq("support")
        & support["transformation"].eq("share_level")
        & support["stratum_role"].eq("regime")
    ]
    rows: list[dict[str, object]] = []
    keys = ["routing_scope", "weighting", "value_support"]
    for identity, cell in fitted.groupby(keys, observed=True, sort=False):
        fields = dict(zip(keys, identity, strict=True))
        aggregate = cell[cell["stratum_role"].eq("aggregate")]
        regimes = cell[cell["stratum_role"].eq("regime")]
        expected = declared
        for key, value in fields.items():
            expected = expected[expected[key].eq(value)]
        gated = sorted(
            set(expected["backing_regime"]) - set(regimes["backing_regime"])
        )
        checked = bool(len(aggregate) == 1 and not gated)
        summed = float(regimes["change"].sum())
        pooled = float(aggregate["change"].iloc[0]) if len(aggregate) == 1 else float("nan")
        rows.append(
            {
                "record_type": "additive_decomposition",
                **fields,
                "transformation": "share_level",
                "regime_change_sum": summed,
                "pooled_change": pooled,
                "absolute_difference": abs(summed - pooled) if checked else None,
                "tolerance": tolerance,
                "checked": checked,
                "gated_regimes": ",".join(gated) if gated else "none",
            }
        )
    result = pd.DataFrame(rows)
    broken = additivity_failures(result)
    if strict and not broken.empty:
        raise ValueError(
            "backing-regime changes do not sum to the pooled change: "
            f"{broken[[*keys, 'absolute_difference']].to_dict('records')}"
        )
    return result


def regime_change_ledger(
    choices: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
) -> pd.DataFrame:
    """Record every dated label move, and whether it can reach the contrast window.

    This is the rival the dated taxonomy exists for. If a candidate's regime label
    changes between the endpoint years, part of a regime's measured move is a
    relabelling of a fixed instrument rather than a change in use. The ledger dates
    every observed label per candidate over the full panel and reports which
    candidates change inside the window, so the rival is bounded by evidence.
    """

    missing = [column for column in REQUIRED_CHOICE_COLUMNS if column not in choices.columns]
    if missing:
        raise ValueError(f"regime-change ledger lacks required columns: {missing}")
    frame = choices.loc[:, list(REQUIRED_CHOICE_COLUMNS)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame[frame["candidate_type"].eq("stable") & frame["date"].notna()]
    if frame.empty:
        raise ValueError("regime-change ledger has no stable candidate rows")
    frame["year"] = frame["date"].dt.year
    in_window = frame["year"].between(baseline_year, comparison_year)
    rows: list[dict[str, object]] = []
    keys = ["candidate_address", "candidate_symbol", "backing_regime"]
    for identity, block in frame.groupby(keys, observed=True, sort=False):
        address, symbol, regime = identity
        window = block[in_window.loc[block.index]]
        rows.append(
            {
                "record_type": "regime_change_ledger",
                "candidate_address": address,
                "candidate_symbol": symbol,
                "backing_regime": regime,
                "first_labelled_date": block["date"].min().date().isoformat(),
                "last_labelled_date": block["date"].max().date().isoformat(),
                "panel_route_count": int(block["route_count"].sum()),
                "window_route_count": int(window["route_count"].sum()),
                "window_within_20pct_value_usd": float(
                    window["within_20pct_value_usd"].sum()
                ),
            }
        )
    ledger = pd.DataFrame(rows)
    labels = ledger.groupby("candidate_address", observed=True)["backing_regime"].transform(
        "nunique"
    )
    in_window_labels = (
        ledger[ledger["window_route_count"].gt(0)]
        .groupby("candidate_address", observed=True)["backing_regime"]
        .nunique()
    )
    ledger["panel_label_count"] = labels.astype(int)
    ledger["window_label_count"] = (
        ledger["candidate_address"].map(in_window_labels).fillna(0).astype(int)
    )
    ledger["label_moves_in_panel"] = ledger["panel_label_count"].gt(1)
    ledger["label_moves_in_window"] = ledger["window_label_count"].gt(1)
    ledger["baseline_year"] = baseline_year
    ledger["comparison_year"] = comparison_year
    return ledger.sort_values(
        ["candidate_symbol", "backing_regime"], kind="stable", ignore_index=True
    )


def universe_reconciliation(
    regime_estimates: pd.DataFrame, transition_estimates: pd.DataFrame
) -> pd.DataFrame:
    """Compare the pooled change on the choice universe with the type-level one.

    The regime cut is measured on the released endpoint-candidate choice panel,
    which is labelled at ordered-pair level and therefore is not the same route
    universe as `intermediation_by_type_daily`. Reporting both pooled changes side
    by side is what licenses reading the regime terms next to the headline; the
    difference is published rather than assumed away.
    """

    keys = ["routing_scope", "weighting", "value_support", "transformation"]
    pooled = regime_estimates[regime_estimates["stratum_role"].eq("aggregate")]
    merged = pooled.merge(
        transition_estimates,
        on=keys,
        how="inner",
        suffixes=("_choice_universe", "_type_panel"),
    )
    if len(merged) != len(pooled):
        raise ValueError("pooled regime rows do not match the type-level transition perimeter")
    return pd.DataFrame(
        {
            "record_type": "universe_reconciliation",
            **{key: merged[key] for key in keys},
            "choice_universe_change": merged["change_choice_universe"].astype(float),
            "type_panel_change": merged["change_type_panel"].astype(float),
            "absolute_difference": (
                merged["change_choice_universe"].astype(float)
                - merged["change_type_panel"].astype(float)
            ).abs(),
            "choice_universe_days": merged["days_choice_universe"].astype(int),
            "type_panel_days": merged["days_type_panel"].astype(int),
        }
    )

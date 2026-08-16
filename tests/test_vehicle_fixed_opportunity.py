from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ddvc.analysis.vehicle_fixed_opportunity import (
    POOLED_COHORT,
    assert_cohort_additivity,
    cohort_cell_ledger,
    cohort_mass_ledger,
    fixed_opportunity_daily_shares,
    fixed_opportunity_support,
    fixed_opportunity_tests,
    unsupported_dimension_ledger,
)

NATIVE = "0x0000000000000000000000000000000000000001"
STABLE = "0x0000000000000000000000000000000000000002"
NEWCOMER = "0x0000000000000000000000000000000000000003"


def _row(
    date: str,
    src: str,
    tgt: str,
    address: str,
    candidate_type: str,
    routes: float,
    *,
    scope: str = "single_venue",
    venue: str = "uniswap_v3|uniswap_v3",
    value: float | None = None,
) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "candidate_address": address,
        "candidate_type": candidate_type,
        "integration_scope": scope,
        "venue_sequence": venue,
        "route_count": routes,
        "within_20pct_value_usd": routes if value is None else value,
    }


def _choices(days: int = 12) -> pd.DataFrame:
    """Two endpoint years on identical month-day positions, three kinds of pair.

    `AAA->BBB` is active throughout and rotates toward the stable candidate.
    `CCC->DDD` appears only in the comparison year and is stable-only, so it is
    the entrant a fixed cohort must exclude. `EEE->FFF` runs throughout but its
    stable mass arrives on a candidate that is absent in the baseline year, which
    is what separates the pair cohort from the pair-candidate cohort.
    """

    rows: list[dict[str, object]] = []
    for year, stable_routes in ((2024, 20.0), (2026, 60.0)):
        for index, day in enumerate(pd.date_range(f"{year}-03-01", periods=days, freq="D")):
            stamp = day.date().isoformat()
            for scope in ("single_venue", "cross_venue"):
                rows.append(_row(stamp, "AAA", "BBB", NATIVE, "native", 100.0 + index, scope=scope))
                rows.append(
                    _row(stamp, "AAA", "BBB", STABLE, "stable", stable_routes, scope=scope)
                )
                rows.append(_row(stamp, "EEE", "FFF", NATIVE, "native", 40.0, scope=scope))
                if year == 2026:
                    rows.append(
                        _row(stamp, "CCC", "DDD", STABLE, "stable", 90.0, scope=scope)
                    )
                    rows.append(
                        _row(stamp, "EEE", "FFF", NEWCOMER, "stable", 50.0, scope=scope)
                    )
    return pd.DataFrame(rows)


def test_contributions_sum_to_the_pooled_share_on_every_day() -> None:
    daily = fixed_opportunity_daily_shares(_choices())
    assert set(daily["routing_scope"]) == {
        "two_leg",
        "single_venue_two_leg",
        "cross_venue_two_leg",
    }
    keys = ["date", "routing_scope", "weighting", "value_support", "cohort"]
    contributions = (
        daily[daily["stratum_role"].str.startswith("contribution")].groupby(keys)["share"].sum()
    )
    pooled = (
        daily[daily["cohort"].eq(POOLED_COHORT)]
        .set_index(["date", "routing_scope", "weighting", "value_support"])["share"]
    )
    expected = pooled.reindex(
        pd.MultiIndex.from_arrays(
            [contributions.index.get_level_values(level) for level in keys[:4]]
        )
    )
    assert np.allclose(contributions.to_numpy(), expected.to_numpy())
    assert daily["share"].between(0, 1).all()


def test_a_pair_that_appears_only_in_the_comparison_year_leaves_every_cohort() -> None:
    choices = _choices()
    daily = fixed_opportunity_daily_shares(choices)
    cells = cohort_cell_ledger(choices)
    # Three ordered pairs are observed, but only two carry routes in both years.
    pair = cells[cells["cohort"].eq("persistent_pair") & cells["routing_scope"].eq("two_leg")]
    assert int(pair["persistent_cells"].iloc[0]) == 2
    assert int(pair["endpoint_universe_cells"].iloc[0]) == 3
    # The entrant is stable-only and large, so dropping it must lower the cohort's
    # comparison-year share below the pooled one.
    comparison = daily[
        daily["routing_scope"].eq("two_leg")
        & daily["weighting"].eq("episode")
        & daily["date"].dt.year.eq(2026)
    ]
    pooled_share = comparison[comparison["cohort"].eq(POOLED_COHORT)]["share"].mean()
    cohort_share = comparison[
        comparison["cohort"].eq("persistent_pair")
        & comparison["stratum_role"].eq("conditional")
    ]["share"].mean()
    assert cohort_share < pooled_share


def test_the_candidate_cohort_is_strictly_tighter_than_the_pair_cohort() -> None:
    choices = _choices()
    daily = fixed_opportunity_daily_shares(choices)
    ledger = cohort_mass_ledger(daily)
    scoped = ledger[ledger["routing_scope"].eq("two_leg") & ledger["weighting"].eq("episode")]
    pair = scoped[scoped["cohort"].eq("persistent_pair")]
    candidate = scoped[scoped["cohort"].eq("persistent_pair_candidate")]
    # `EEE->FFF` survives the pair cohort but its 2026 stable candidate does not
    # survive the pair-candidate cohort, so retained mass can only fall.
    assert (
        float(candidate["comparison_denominator_share"].iloc[0])
        < float(pair["comparison_denominator_share"].iloc[0])
    )
    assert (
        float(candidate["comparison_cohort_share"].iloc[0])
        < float(pair["comparison_cohort_share"].iloc[0])
    )
    assert ledger["selection_note"].str.contains("continuously active").all()


def test_the_venue_sequence_cohort_is_published_as_a_bad_control() -> None:
    daily = fixed_opportunity_daily_shares(_choices())
    flagged = daily[daily["is_bad_control"].astype(bool)]
    assert set(flagged["cohort"]) == {"persistent_pair_venue_sequence"}
    support = fixed_opportunity_support(daily, minimum_endpoint_days=5)
    estimates = fixed_opportunity_tests(daily, support, hac_lag=2)
    assert estimates.loc[
        estimates["cohort"].eq("persistent_pair_venue_sequence"), "is_bad_control"
    ].all()
    assert not estimates.loc[
        estimates["cohort"].eq("persistent_pair"), "is_bad_control"
    ].any()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"candidate_type": "imported"}, "denominator identity"),
        ({"src": None}, "cohort identity is undefined"),
        ({"venue_sequence": None}, "cohort identity is undefined"),
    ],
)
def test_daily_shares_refuse_a_panel_whose_cohort_identity_is_broken(
    mutation: dict[str, object], message: str
) -> None:
    choices = _choices()
    target = choices["candidate_address"].eq(STABLE)
    for column, value in mutation.items():
        choices.loc[target, column] = value
    with pytest.raises(ValueError, match=message):
        fixed_opportunity_daily_shares(choices)


def test_support_gates_a_thin_specification_and_records_retained_mass() -> None:
    daily = fixed_opportunity_daily_shares(_choices())
    support = fixed_opportunity_support(daily, minimum_endpoint_days=5)
    assert support["record_type"].eq("support").all()
    # `baseline_denominator_share` is the share of the stratum's denominator this
    # specification's own denominator spans, so it is one for the pooled row and
    # for both contribution rows, which divide the pooled denominator, and below
    # one only where the cohort's own denominator is the estimand's.
    unit = support[support["stratum_role"].ne("conditional")]
    assert np.allclose(unit["baseline_denominator_share"].astype(float), 1.0)
    cohort = support[
        support["cohort"].eq("persistent_pair") & support["stratum_role"].eq("conditional")
    ]
    # Every baseline pair in the fixture is persistent, so the cohort spans the
    # whole 2024 denominator; the 2026 entrant is what it drops.
    assert np.allclose(cohort["baseline_denominator_share"].astype(float), 1.0)
    assert (cohort["comparison_denominator_share"].astype(float) < 1.0).all()
    # Every baseline stable route in the fixture sits inside a persistent pair, so
    # the out-of-cohort contribution is exactly zero in 2024 and its log odds is
    # undefined. That is a published support row with its reason, never a silently
    # dropped specification.
    gated = support[~support["fit_supported"].astype(bool)]
    assert set(gated["stratum_role"]) == {"contribution_out"}
    assert set(gated["transformation"]) == {"log_odds"}
    assert (gated["baseline_supported_days"] == 0).all()
    assert gated["support_reason"].str.contains("below the declared HAC horizon").all()
    thin = fixed_opportunity_support(daily, minimum_endpoint_days=50)
    assert not thin["fit_supported"].any()


def test_tests_fit_only_supported_rows_and_control_multiplicity_across_cohorts() -> None:
    daily = fixed_opportunity_daily_shares(_choices())
    support = fixed_opportunity_support(daily, minimum_endpoint_days=5)
    estimates = fixed_opportunity_tests(daily, support, hac_lag=2)
    assert len(estimates) == len(support[support["fit_supported"]])
    conditional = estimates[estimates["stratum_role"].eq("conditional")]
    other = estimates[~estimates["stratum_role"].eq("conditional")]
    assert conditional["p_value_holm"].notna().all()
    assert other["p_value_holm"].isna().all()
    assert (conditional["p_value_holm"] >= conditional["p_value"]).all()
    assert (estimates["hac_lag_days"] == 2).all()
    assert estimates["change"].notna().all()
    # Every estimate carries an interval on its own t reference, so a cohort that
    # lands near zero is reported as a bound rather than as a failure to reject.
    assert (estimates["confidence_interval_lower"] <= estimates["change"]).all()
    assert (estimates["change"] <= estimates["confidence_interval_upper"]).all()
    assert (estimates["confidence_level"] == 0.95).all()
    assert (estimates["degrees_freedom"] > 0).all()


def test_tests_refuse_a_family_with_no_supported_specification() -> None:
    daily = fixed_opportunity_daily_shares(_choices())
    support = fixed_opportunity_support(daily, minimum_endpoint_days=50)
    with pytest.raises(ValueError, match="fitted no supported specification"):
        fixed_opportunity_tests(daily, support, hac_lag=2)


def test_additivity_holds_on_the_fitted_estimates_and_fails_when_one_moves() -> None:
    daily = fixed_opportunity_daily_shares(_choices())
    support = fixed_opportunity_support(daily, minimum_endpoint_days=5)
    estimates = fixed_opportunity_tests(daily, support, hac_lag=2)
    checked = assert_cohort_additivity(estimates)
    assert checked["checked"].all()
    assert (checked["absolute_difference"].astype(float) < 1e-9).all()
    tampered = estimates.copy()
    target = (
        tampered["stratum_role"].eq("contribution_in")
        & tampered["transformation"].eq("share_level")
    )
    tampered.loc[tampered[target].index[0], "change"] += 0.01
    with pytest.raises(ValueError, match="do not sum to the pooled change"):
        assert_cohort_additivity(tampered)


def test_additivity_reports_a_cell_as_unchecked_when_a_contribution_is_gated_out() -> None:
    daily = fixed_opportunity_daily_shares(_choices())
    support = fixed_opportunity_support(daily, minimum_endpoint_days=5)
    estimates = fixed_opportunity_tests(daily, support, hac_lag=2)
    dropped = estimates[~estimates["stratum_role"].eq("contribution_out")]
    checked = assert_cohort_additivity(dropped)
    assert not checked["checked"].any()
    assert (checked["gated_roles"] == "contribution_out").all()


def test_unsupported_dimensions_are_named_with_their_blocker() -> None:
    ledger = unsupported_dimension_ledger()
    assert set(ledger["dimension"]) == {"observed_reach", "trade_notional", "search_regret_cell"}
    assert ledger["blocker"].eq("blocked_transaction_state_frontier").all()
    # A support row must never be readable as a passed attack.
    assert not ledger["fitted"].any()
    # The runner stamps one attack id across every record it publishes, so the
    # ledger must not carry a second copy that could drift from it.
    assert "attack_id" not in ledger.columns

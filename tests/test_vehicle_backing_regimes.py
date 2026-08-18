from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ddvc.analysis.vehicle_backing_regimes import (
    AGGREGATE_STRATUM,
    assert_additive_decomposition,
    backing_regime_daily_shares,
    backing_regime_support,
    backing_regime_tests,
    observed_regimes,
    regime_change_ledger,
    universe_reconciliation,
)


NATIVE = "0x0000000000000000000000000000000000000001"
FIAT = "0x0000000000000000000000000000000000000002"
SYNTHETIC = "0x0000000000000000000000000000000000000003"


def _row(
    date: str,
    address: str,
    symbol: str,
    candidate_type: str,
    regime: str,
    routes: float,
    *,
    scope: str = "single_venue",
    value: float | None = None,
) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date),
        "candidate_address": address,
        "candidate_symbol": symbol,
        "candidate_type": candidate_type,
        "backing_regime": regime,
        "integration_scope": scope,
        "route_count": routes,
        "within_20pct_value_usd": routes if value is None else value,
    }


def _choices(days: int = 12) -> pd.DataFrame:
    """Two endpoint years on identical month-day positions, three strata of mass."""

    rows: list[dict[str, object]] = []
    for year, stable_routes, synthetic_routes in ((2024, 20.0, 1.0), (2026, 40.0, 6.0)):
        for index, day in enumerate(pd.date_range(f"{year}-03-01", periods=days, freq="D")):
            stamp = day.date().isoformat()
            for scope in ("single_venue", "cross_venue"):
                rows.append(
                    _row(stamp, NATIVE, "WETH", "native", "not_applicable", 100.0 + index, scope=scope)
                )
                rows.append(
                    _row(
                        stamp,
                        FIAT,
                        "USDC",
                        "stable",
                        "fiat_reserve",
                        stable_routes + (index % 3),
                        scope=scope,
                    )
                )
                rows.append(
                    _row(stamp, SYNTHETIC, "USDe", "stable", "synthetic", synthetic_routes, scope=scope)
                )
    return pd.DataFrame(rows)


def test_daily_shares_sum_to_the_pooled_share_on_one_denominator() -> None:
    daily = backing_regime_daily_shares(_choices())
    assert set(daily["routing_scope"]) == {"two_leg", "single_venue_two_leg", "cross_venue_two_leg"}
    keys = ["date", "routing_scope", "weighting", "value_support"]
    regimes = daily[daily["stratum_role"].eq("regime")].groupby(keys)["share"].sum()
    pooled = daily[daily["backing_regime"].eq(AGGREGATE_STRATUM)].set_index(keys)["share"]
    assert np.allclose(regimes.to_numpy(), pooled.reindex(regimes.index).to_numpy())
    # The denominator is stable plus native, so a share is strictly inside the unit
    # interval whenever both sides carry mass.
    assert daily["share"].between(0, 1).all()


def test_daily_shares_keep_only_month_day_positions_seen_in_both_endpoint_years() -> None:
    choices = _choices()
    extra = choices[choices["date"].eq(pd.Timestamp("2026-03-01"))].copy()
    extra["date"] = pd.Timestamp("2026-07-04")
    daily = backing_regime_daily_shares(pd.concat([choices, extra], ignore_index=True))
    assert pd.Timestamp("2026-07-04") not in set(daily["date"])
    assert observed_regimes(choices.assign(date=pd.to_datetime(choices["date"]))) == [
        "fiat_reserve",
        "synthetic",
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"backing_regime": "reserve_fund"}, "outside the taxonomy"),
        ({"backing_regime": "time_varying"}, "undated stable labels"),
        ({"candidate_type": "imported"}, "denominator identity"),
    ],
)
def test_daily_shares_refuse_a_panel_whose_regime_identity_is_broken(
    mutation: dict[str, str], message: str
) -> None:
    choices = _choices()
    stable = choices["candidate_address"].eq(SYNTHETIC)
    for column, value in mutation.items():
        choices.loc[stable, column] = value
    with pytest.raises(ValueError, match=message):
        backing_regime_daily_shares(choices)


def test_daily_shares_refuse_a_regime_label_on_a_native_candidate() -> None:
    choices = _choices()
    choices.loc[choices["candidate_address"].eq(NATIVE), "backing_regime"] = "fiat_reserve"
    with pytest.raises(ValueError, match="labels a non-stable candidate"):
        backing_regime_daily_shares(choices)


def test_support_gates_a_thin_regime_and_records_its_economic_weight() -> None:
    daily = backing_regime_daily_shares(_choices())
    support = backing_regime_support(daily, minimum_endpoint_days=5)
    assert support["record_type"].eq("support").all()
    thin = backing_regime_support(daily, minimum_endpoint_days=50)
    assert not thin["fit_supported"].any()
    assert thin["support_reason"].str.contains("below the declared HAC horizon").all()
    synthetic = support[
        support["backing_regime"].eq("synthetic")
        & support["transformation"].eq("share_level")
        & support["routing_scope"].eq("two_leg")
        & support["weighting"].eq("episode")
    ]
    assert len(synthetic) == 1
    # The regime grows from a small share of stable mass to a larger one, and the
    # ledger reports that weight rather than leaving the reader to infer it.
    assert 0 < float(synthetic["baseline_share_of_stable_mass"].iloc[0]) < 0.1
    assert float(synthetic["comparison_share_of_stable_mass"].iloc[0]) > 0.1


def test_tests_fit_only_supported_rows_and_control_multiplicity_across_regimes() -> None:
    daily = backing_regime_daily_shares(_choices())
    support = backing_regime_support(daily, minimum_endpoint_days=5)
    estimates = backing_regime_tests(daily, support, hac_lag=2)
    assert len(estimates) == len(support[support["fit_supported"]])
    aggregate = estimates[estimates["stratum_role"].eq("aggregate")]
    regime = estimates[estimates["stratum_role"].eq("regime")]
    assert aggregate["p_value_holm"].isna().all()
    assert regime["p_value_holm"].notna().all()
    assert (regime["p_value_holm"] >= regime["p_value"]).all()
    assert (estimates["hac_lag_days"] == 2).all()
    assert estimates["change"].notna().all()


def test_tests_refuse_a_family_with_no_supported_specification() -> None:
    daily = backing_regime_daily_shares(_choices())
    support = backing_regime_support(daily, minimum_endpoint_days=50)
    with pytest.raises(ValueError, match="fitted no supported specification"):
        backing_regime_tests(daily, support, hac_lag=2)


def test_additivity_holds_on_the_fitted_estimates_and_fails_when_one_moves() -> None:
    daily = backing_regime_daily_shares(_choices())
    support = backing_regime_support(daily, minimum_endpoint_days=5)
    estimates = backing_regime_tests(daily, support, hac_lag=2)
    checked = assert_additive_decomposition(estimates, support)
    assert checked["checked"].all()
    assert (checked["absolute_difference"].astype(float) < 1e-9).all()
    tampered = estimates.copy()
    target = tampered["stratum_role"].eq("regime") & tampered["transformation"].eq("share_level")
    tampered.loc[tampered[target].index[0], "change"] += 0.01
    with pytest.raises(ValueError, match="do not sum to the pooled change"):
        assert_additive_decomposition(tampered, support)


def test_additivity_reports_a_cell_as_unchecked_when_a_regime_is_gated_out() -> None:
    daily = backing_regime_daily_shares(_choices())
    support = backing_regime_support(daily, minimum_endpoint_days=5)
    estimates = backing_regime_tests(daily, support, hac_lag=2)
    dropped = estimates[~estimates["backing_regime"].eq("synthetic")]
    checked = assert_additive_decomposition(dropped, support)
    assert not checked["checked"].any()
    assert (checked["gated_regimes"] == "synthetic").all()


def test_regime_change_ledger_separates_an_in_window_label_move_from_an_earlier_one() -> None:
    choices = _choices()
    early = choices[choices["candidate_address"].eq(FIAT)].copy()
    early["date"] = pd.Timestamp("2021-03-01")
    early["backing_regime"] = "mixed_with_fiat_stablecoin"
    moved = choices[
        choices["candidate_address"].eq(SYNTHETIC) & choices["date"].dt.year.eq(2026)
    ].copy()
    moved["backing_regime"] = "on_chain_collateralized"
    ledger = regime_change_ledger(pd.concat([choices, early, moved], ignore_index=True))
    fiat = ledger[ledger["candidate_address"].eq(FIAT)]
    synthetic = ledger[ledger["candidate_address"].eq(SYNTHETIC)]
    assert fiat["label_moves_in_panel"].all()
    assert not fiat["label_moves_in_window"].any()
    assert synthetic["label_moves_in_window"].all()
    assert int(fiat.loc[fiat["backing_regime"].eq("mixed_with_fiat_stablecoin"), "window_route_count"].iloc[0]) == 0


def test_universe_reconciliation_requires_the_exact_pooled_perimeter() -> None:
    daily = backing_regime_daily_shares(_choices())
    support = backing_regime_support(daily, minimum_endpoint_days=5)
    estimates = backing_regime_tests(daily, support, hac_lag=2)
    pooled = estimates[estimates["stratum_role"].eq("aggregate")]
    transition = pooled[
        ["routing_scope", "weighting", "value_support", "transformation", "change", "days"]
    ].copy()
    transition["change"] = transition["change"] + 0.5
    reconciliation = universe_reconciliation(estimates, transition)
    assert reconciliation["record_type"].eq("universe_reconciliation").all()
    assert np.allclose(reconciliation["absolute_difference"].to_numpy(), 0.5)
    with pytest.raises(ValueError, match="do not match the type-level transition perimeter"):
        universe_reconciliation(estimates, transition.iloc[1:])


def _deck_values_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_backing_regime_deck_values", "scripts/tabulate/build_backing_regime_deck_values.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _published_frames():
    """The two exhibits the macro builder consumes, from the module's own output."""

    choices = _choices()
    daily = backing_regime_daily_shares(choices)
    support = backing_regime_support(daily, minimum_endpoint_days=5)
    estimates = backing_regime_tests(daily, support, hac_lag=2)
    pooled = estimates[estimates["stratum_role"].eq("aggregate")][
        ["routing_scope", "weighting", "value_support", "transformation", "change", "days"]
    ]
    records = pd.concat(
        [
            support,
            regime_change_ledger(choices),
            assert_additive_decomposition(estimates, support),
            universe_reconciliation(estimates, pooled),
        ],
        ignore_index=True,
        sort=False,
    )
    return estimates, records


def test_deck_macros_carry_every_regime_term_and_the_label_ledger() -> None:
    module = _deck_values_module()
    estimates, support = _published_frames()
    # The fixture carries two of the taxonomy's regimes, so the builder's full regime
    # list cannot be rendered from it; the two present ones plus the pooled row are.
    module.REGIMES = (("Fiat", "fiat_reserve"), ("Synthetic", "synthetic"), ("Pooled", "all_stable"))
    rendered = module.render(estimates, support)
    for macro in (
        "\\BackingFiatCountChange",
        "\\BackingFiatCountSE",
        "\\BackingSyntheticValueChange",
        "\\BackingPooledCountChange",
        "\\BackingCountUniverseGap",
        "\\BackingLabelMovesInWindow",
        "\\BackingCandidates",
    ):
        assert f"\\newcommand{{{macro}}}" in rendered
    assert "pp}" in rendered and "\\%}" in rendered
    # A macro may never be emitted twice: the paper takes the last definition
    # silently, so a duplicate is a wrong number rather than an error.
    names = [line.split("}")[0] for line in rendered.splitlines() if line.startswith("\\newcommand")]
    assert len(names) == len(set(names))

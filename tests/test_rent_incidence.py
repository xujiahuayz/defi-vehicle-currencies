"""Checks on the rent-incidence accounting, on the pieces that can be wrong silently.

The three hazards are the tick-liquidity replay, whose bug would be a plausible
but wrong liquidity number rather than a crash; the multi-scale realised
variance, whose coarse arms are the bound on the microstructure threat and are
worthless if they are not actually coarser; and the loss-versus-rebalancing
closed form, which is asserted in prose everywhere and derived nowhere.
"""

from __future__ import annotations

import importlib.util
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_rent_incidence import (
    OUTPUT_PROVENANCE,
    REQUIRED_PANELS,
    by_role_over_time,
    pool_months,
    report,
)
from ddvc.fetch.pool_daily import pool_day_values, require_pool_daily_coverage
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.liquidity import (
    CAPITAL_COLUMN,
    LIQUIDITY_CONTRACTS,
    LOCAL_DEPTH_COLUMN,
    capital_interpretable,
    capital_reconciliation_mask,
    capital_scale_label,
    exact_calendar_lag,
    liquidity_contract,
    lvr_inference_ready,
    quantity_supported,
    require_contract_coverage,
    require_capital_denominator,
    require_quantity_support,
    return_inference_ready,
)

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_rent_incidence_panel", ROOT / "scripts" / "build_rent_incidence_panel.py")
brp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brp)

_capital_spec = importlib.util.spec_from_file_location(
    "build_pool_capital_panel", ROOT / "scripts" / "build_pool_capital_panel.py")
capital_builder = importlib.util.module_from_spec(_capital_spec)
_capital_spec.loader.exec_module(capital_builder)


def capital_contract_fields(venue: str) -> dict[str, object]:
    contract = liquidity_contract(venue)
    return {
        "pool_family": contract.pool_family,
        "invariant_family": contract.invariant_family,
        "state_generation": contract.capability("deposited_capital").state_generation,
    }


def test_every_estimator_output_uses_one_current_input_contract():
    source = (ROOT / "scripts" / "run_rent_incidence.py").read_text()
    assert OUTPUT_PROVENANCE["inputs"] == REQUIRED_PANELS
    assert source.count("**OUTPUT_PROVENANCE") == 7


def test_rent_report_uses_two_way_primary_and_keeps_one_way_sensitivities():
    x_value = np.arange(24, dtype=float)
    design = np.column_stack([np.ones(len(x_value)), x_value])
    pools = np.repeat(["a", "b", "c", "d", "e", "f"], 4)
    months = np.tile(["m1", "m2", "m3", "m4"], 6)
    pool_shock = np.repeat([0.5, -0.5, 0.25, -0.25, 0.75, -0.75], 4)
    month_shock = np.tile([0.2, -0.1, 0.3, -0.4], 6)
    outcome = (
        1.0
        + 0.2 * x_value
        + pool_shock
        + month_shock
        + np.random.default_rng(0).normal(0, 0.1, len(x_value))
    )

    _, _, fit, records = report(
        "test",
        outcome,
        design,
        ["const", "slope"],
        pools,
        additional_cluster=months,
        focus={"slope"},
    )

    assert fit.cluster_counts == (6, 4)
    assert len(records) == 1
    record = records[0]
    assert record["covariance"] == "two_way_pool_month_cr1"
    assert record["pool_clusters"] == 6
    assert record["month_clusters"] == 4
    assert record["p"] == pytest.approx(fit.p_values[1])
    assert np.isfinite(record["se_pool_only"])
    assert np.isfinite(record["p_pool_only"])
    assert np.isfinite(record["se_month_only"])
    assert np.isfinite(record["p_month_only"])


def test_role_exhibit_keeps_pooled_and_annual_bridge_rows():
    dates = pd.to_datetime(["2024-01-01"] * 500 + ["2025-01-01"] * 500)
    frame = pd.DataFrame(
        {
            "date": dates,
            "day": dates.strftime("%Y%m%d"),
            "pool_role": "native / other",
            "pool": [f"pool-{index % 2}" for index in range(1_000)],
            "token0": "native",
            "token1": "other",
            CAPITAL_COLUMN: 100_000.0,
            "fee_yield": 0.001,
            "lvr_rate": 0.002,
            "gas_rate": 0.0001,
            "n_mint": 1,
            "n_burn": 0,
            "net_yield": -0.0011,
            "net_pre_gas_yield": -0.001,
            "fees_usd": 100.0,
            "lvr_usd": 200.0,
            "gas_usd": 10.0,
            "net_usd": -110.0,
        }
    )

    result = by_role_over_time(frame, "uniswap_v2")

    assert set(result["scope"]) == {"pooled", "annual"}
    assert set(result.loc[result.scope.eq("annual"), "year"]) == {2024, 2025}
    pooled = result.loc[result.scope.eq("pooled")].iloc[0]
    assert pooled["pool_days"] == 1_000
    assert pooled["mean_daily_scale_usd_bn"] == pytest.approx(0.05)
    assert pooled["scale_share"] == pytest.approx(1.0)
    assert pooled["pool_day_share"] == pytest.approx(1.0)
    assert pooled["scale_basis"] == "lagged reported reserve capital"
    assert pooled["capital_interpretable"]


def test_v3_role_exhibit_labels_provider_scale_and_withholds_capital_inference():
    dates = pd.to_datetime(["2024-01-01"] * 500)
    frame = pd.DataFrame(
        {
            "date": dates,
            "day": dates.strftime("%Y%m%d"),
            "pool_role": "native / stable",
            "pool": [f"pool-{index % 2}" for index in range(500)],
            "token0": "native",
            "token1": "stable",
            CAPITAL_COLUMN: 1_000_000.0,
            "fee_yield": 0.001,
            "lvr_rate": 0.002,
            "gas_rate": 0.0001,
            "n_mint": 1,
            "n_burn": 0,
            "net_yield": -0.0011,
            "net_pre_gas_yield": -0.001,
            "fees_usd": 1_000.0,
            "lvr_usd": 2_000.0,
            "gas_usd": 100.0,
            "net_usd": -1_100.0,
        }
    )

    pooled = by_role_over_time(frame, "uniswap_v3").query("scope == 'pooled'").iloc[0]

    assert pooled["scale_basis"] == "unvalidated provider TVL diagnostic"
    assert not pooled["capital_interpretable"]
    assert not pooled["return_inference_ready"]
    assert np.isnan(pooled["med_net_yield_apr"])
    assert np.isnan(pooled["cw_net_yield_apr"])
    assert np.isnan(pooled["share_net_positive"])
    assert np.isnan(pooled["fee_over_lvr"])


def test_capital_and_return_model_gates_are_separate():
    assert capital_interpretable("uniswap_v2")
    assert not capital_interpretable("uniswap_v3")
    assert return_inference_ready("uniswap_v2")
    assert not return_inference_ready("uniswap_v3")
    assert capital_scale_label("uniswap_v3") == "unvalidated provider TVL diagnostic"


def test_every_canonical_venue_has_one_liquidity_contract():
    require_contract_coverage(set(DEX_SOURCES))
    assert {venue for venue, _family in LIQUIDITY_CONTRACTS} == set(DEX_SOURCES)


def test_non_cp_protocols_do_not_inherit_a_cp_return_model():
    venues = {"uniswap_v3", "sushiswap_v3", "uniswap_v4", "curve", "balancer", "fluid"}
    assert not any(return_inference_ready(venue) for venue in venues)
    assert not any(lvr_inference_ready(venue) for venue in venues)


def test_exact_capital_lag_never_uses_the_previous_observed_row():
    frame = pd.DataFrame(
        {
            "pool": ["a", "a", "a"],
            "day": ["20250101", "20250103", "20250104"],
            "reported_capital_usd": [100.0, 300.0, 400.0],
        }
    )
    lag = exact_calendar_lag(frame)
    assert np.isnan(lag.iloc[0])
    assert np.isnan(lag.iloc[1])
    assert lag.iloc[2] == 300.0


def test_streaming_capital_lag_requires_the_exact_previous_calendar_day():
    base = {
        "pool": "pool",
        "reported_capital_usd": 100.0,
        "reported_volume_usd": 1.0,
        "reported_fees_usd": 0.1,
        "capital_source": "uniswap_v2.reserveUSD",
    }
    first, state = capital_builder.with_exact_capital_lag(
        base,
        venue="uniswap_v2",
        day="20250101",
        ordinal=100,
        prior=None,
    )
    gap, _ = capital_builder.with_exact_capital_lag(
        {**base, "reported_capital_usd": 200.0},
        venue="uniswap_v2",
        day="20250103",
        ordinal=102,
        prior=state,
    )
    adjacent, _ = capital_builder.with_exact_capital_lag(
        {**base, "reported_capital_usd": 200.0},
        venue="uniswap_v2",
        day="20250102",
        ordinal=101,
        prior=state,
    )
    assert not first["exact_lag_valid"] and first[CAPITAL_COLUMN] is None
    assert not gap["exact_lag_valid"] and gap[CAPITAL_COLUMN] is None
    assert adjacent["exact_lag_valid"] and adjacent[CAPITAL_COLUMN] == 100.0
    assert adjacent["pool_family"] == "full_range_constant_product"
    assert adjacent["state_generation"] == "provider_pool_day_v1"


def test_provider_capital_must_reconcile_to_independently_priced_holdings():
    reported = pd.Series([100.0, 100.0, 100.0, 0.0])
    reconstructed = pd.Series([100.0, 299.0, 301.0, 100.0])
    mask = capital_reconciliation_mask(reported, reconstructed, tolerance=3.0)
    assert mask.tolist() == [True, True, False, False]


def test_return_denominator_rejects_virtual_or_local_depth_sources():
    frame = pd.DataFrame(
        {
            CAPITAL_COLUMN: [100.0],
            "capital_source": ["local_virtual_depth"],
            "quantity_kind": ["deposited_capital"],
            **{key: [value] for key, value in capital_contract_fields("uniswap_v2").items()},
            "capital_validation_status": ["reconciled_exact_lag"],
            "exact_lag_valid": [True],
        }
    )
    with pytest.raises(ValueError, match="cannot be a capital source"):
        require_capital_denominator(frame, venue="uniswap_v2")


def test_return_denominator_rejects_an_unapproved_tvl_source():
    frame = pd.DataFrame(
        {
            CAPITAL_COLUMN: [100.0],
            "capital_source": ["some_provider.tvlUSD"],
            "quantity_kind": ["deposited_capital"],
            **{key: [value] for key, value in capital_contract_fields("uniswap_v3").items()},
            "capital_validation_status": ["reported_plausible"],
            "exact_lag_valid": [True],
        }
    )
    with pytest.raises(ValueError, match="no validated capital measure"):
        require_capital_denominator(frame, venue="uniswap_v3", purpose="descriptive")


def test_return_denominator_rejects_a_protocol_without_validated_capital():
    frame = pd.DataFrame(
        {
            CAPITAL_COLUMN: [100.0],
            "capital_source": ["uniswap_v4.tvlUSD"],
            "quantity_kind": ["deposited_capital"],
            "pool_family": ["vanilla_concentrated"],
            "invariant_family": ["concentrated_liquidity_singleton"],
            "state_generation": ["provider_pool_day_v1"],
            "capital_validation_status": ["reported_plausible"],
            "exact_lag_valid": [True],
        }
    )
    with pytest.raises(ValueError, match="no validated capital measure"):
        require_capital_denominator(
            frame,
            venue="uniswap_v4",
            pool_family="vanilla_concentrated",
        )


def test_protocol_quantities_are_typed_and_fail_closed_independently():
    assert not quantity_supported("uniswap_v3", "deposited_capital")
    assert not quantity_supported(
        "uniswap_v3", "deposited_capital", use="descriptive"
    )
    assert not quantity_supported(
        "uniswap_v3", "deposited_capital", use="return_after_row_reconciliation"
    )
    assert quantity_supported(
        "uniswap_v2", "deposited_capital", use="return_after_row_reconciliation"
    )
    assert quantity_supported("uniswap_v3", "local_marginal_depth")
    assert quantity_supported("uniswap_v3", "executable_band_depth")
    assert not quantity_supported("uniswap_v3", "lvr")
    assert not quantity_supported("curve", "quote_quality")
    assert not quantity_supported("curve", "quote_quality", "stableswap")
    assert not quantity_supported("curve", "deposited_capital")
    assert not quantity_supported("balancer", "executable_band_depth")
    with pytest.raises(ValueError, match="does not support executable_band_depth"):
        require_quantity_support("balancer", "executable_band_depth")
    with pytest.raises(ValueError, match="unknown liquidity quantity kind"):
        quantity_supported("uniswap_v2", "liquidity")


def test_heterogeneous_protocol_needs_pool_family_and_never_spills_capability():
    with pytest.raises(ValueError, match="requires an explicit pool/invariant family"):
        liquidity_contract("curve")
    assert not quantity_supported("curve", "quote_quality", "cryptoswap")
    assert not quantity_supported("balancer", "quote_quality", "weighted")
    assert quantity_supported("uniswap_v4", "quote_quality", "vanilla_concentrated")
    assert not quantity_supported(
        "uniswap_v4", "quote_quality", "hooked_or_dynamic_fee"
    )


def test_uniswap_v3_daily_tvl_normalizes_as_reported_capital():
    record = {
        "pool": {
            "id": "0xPool",
            "token0": {"id": "0xToken0", "symbol": "TOKEN0"},
            "token1": {"id": "0xToken1", "symbol": "TOKEN1"},
        },
        "tvlUSD": "1234.5",
        "volumeUSD": "10",
    }
    normalized = pool_day_values("uniswap_v3", record)
    assert normalized is not None
    assert normalized["pool"] == "0xpool"
    assert normalized["reported_capital_usd"] == 1234.5
    assert normalized["capital_source"] == "uniswap_v3.tvlUSD"
    assert normalized["token0_address"] == "0xtoken0"
    assert normalized["token1_address"] == "0xtoken1"


def test_sushiswap_v2_reserve_value_normalizes_as_reported_capital():
    record = {
        "pairAddress": "0xPair",
        "token0": {"id": "0xToken0", "symbol": "TOKEN0"},
        "token1": {"id": "0xToken1", "symbol": "TOKEN1"},
        "reserveUSD": "987.5",
        "dailyVolumeUSD": "12",
    }
    normalized = pool_day_values("sushiswap_v2", record)
    assert normalized is not None
    assert normalized["pool"] == "0xpair"
    assert normalized["reported_capital_usd"] == 987.5
    assert normalized["capital_source"] == "sushiswap_v2.reserveUSD"
    assert normalized["token0_address"] == "0xtoken0"
    assert normalized["token1_address"] == "0xtoken1"


def test_legacy_pool_day_identity_is_filled_only_by_exact_pool_contract(tmp_path: Path):
    from ddvc.fetch.pool_daily import (
        apply_pool_identity,
        load_pool_identity_crosswalk,
    )

    source = tmp_path / "mints.jsonl.gz"
    record = {
        "pair": {
            "id": "0xPool",
            "token0": {"id": "0xToken0", "symbol": "TOKEN0"},
            "token1": {"id": "0xToken1", "symbol": "TOKEN1"},
        }
    }
    with gzip.open(source, "wt") as handle:
        handle.write(json.dumps(record) + "\n")
    identities = load_pool_identity_crosswalk([source])
    daily = {
        "pool": "0xpool",
        "token0_address": None,
        "token0_symbol": "spoofable-symbol",
        "token1_address": None,
        "token1_symbol": "TOKEN1",
    }

    resolved = apply_pool_identity(daily, identities)

    assert resolved["token0_address"] == "0xtoken0"
    assert resolved["token1_address"] == "0xtoken1"
    assert resolved["token0_symbol"] == "spoofable-symbol"


def test_pool_identity_crosswalk_rejects_address_conflicts(tmp_path: Path):
    from ddvc.fetch.pool_daily import load_pool_identity_crosswalk

    source = tmp_path / "mints.jsonl.gz"
    records = [
        {
            "pair": {
                "id": "0xPool",
                "token0": {"id": "0xToken0"},
                "token1": {"id": "0xToken1"},
            }
        },
        {
            "pair": {
                "id": "0xPool",
                "token0": {"id": "0xOther"},
                "token1": {"id": "0xToken1"},
            }
        },
    ]
    with gzip.open(source, "wt") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    with pytest.raises(ValueError, match="conflicting immutable token identities"):
        load_pool_identity_crosswalk([source])


def test_pool_identity_crosswalk_accepts_a_static_pool_entity(tmp_path: Path):
    from ddvc.fetch.pool_daily import load_pool_identity_crosswalk

    source = tmp_path / "pools.jsonl.gz"
    record = {
        "id": "0xPool",
        "token0": {"id": "0xToken0", "symbol": "TOKEN0"},
        "token1": {"id": "0xToken1", "symbol": "TOKEN1"},
    }
    with gzip.open(source, "wt") as handle:
        handle.write(json.dumps(record) + "\n")

    identities = load_pool_identity_crosswalk([source])

    assert identities["0xpool"].token0_address == "0xtoken0"


def test_candidate_capital_materializer_allocates_one_pool_once():
    from ddvc.asset_types import VEHICLE_CANDIDATES

    address_by_symbol = {
        symbol: address for address, symbol in VEHICLE_CANDIDATES.items()
    }
    row = {
        "venue": "uniswap_v2",
        "day": "20250102",
        "pool": "0xpool",
        "token0_address": address_by_symbol["WETH"],
        "token0_symbol": "WETH",
        "token1_address": address_by_symbol["USDC"],
        "token1_symbol": "USDC",
        "reported_capital_usd": 1_000.0,
        CAPITAL_COLUMN: 900.0,
        "capital_source": "uniswap_v2.reserveUSD",
        "capital_validation_status": "reported_plausible",
        "capital_valid": True,
        "exact_lag_valid": True,
        **capital_contract_fields("uniswap_v2"),
    }

    allocations = capital_builder.candidate_capital_rows(row)

    assert len(allocations) == 2
    assert sum(item["candidate_capital_usd"] for item in allocations) == 1_000.0
    assert sum(item["candidate_capital_usd_lagged"] for item in allocations) == 900.0
    assert {item["allocation_weight"] for item in allocations} == {0.5}
    assert {item["quantity_kind"] for item in allocations} == {"deposited_capital"}


def test_missing_exact_identity_is_quarantined_without_guessing_from_symbols():
    row = {
        "venue": "uniswap_v2",
        "day": "20250102",
        "pool": "0xpool",
        "token0_address": None,
        "token0_symbol": "WETH",
        "token1_address": None,
        "token1_symbol": "USDC",
        "reported_capital_usd": 10.0,
        "capital_source": "uniswap_v2.reserveUSD",
        "capital_valid": True,
        **capital_contract_fields("uniswap_v2"),
    }

    assert capital_builder.candidate_capital_rows(row) == []
    rejection = capital_builder.capital_identity_rejection(row)

    assert rejection is not None
    assert rejection["capital_validation_status"] == "quarantined_missing_exact_identity"
    assert rejection["reported_capital_usd"] == 10.0


def test_capital_materializer_streams_pool_and_candidate_panels_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ddvc.asset_types import VEHICLE_CANDIDATES

    address_by_symbol = {
        symbol: address for address, symbol in VEHICLE_CANDIDATES.items()
    }
    raw = tmp_path / "raw"
    venue_dir = raw / "uniswap_v2"
    venue_dir.mkdir(parents=True)
    for day, capital in (("20250101", "1000"), ("20250102", "1200")):
        record = {
            "pairAddress": "0xPool",
            "token0": {"id": address_by_symbol["WETH"], "symbol": "WETH"},
            "token1": {"id": address_by_symbol["USDC"], "symbol": "USDC"},
            "reserveUSD": capital,
            "dailyVolumeUSD": "10",
        }
        path = venue_dir / f"uniswap_v2_daily_{day}.jsonl.gz"
        with gzip.open(path, "wt") as handle:
            handle.write(json.dumps(record) + "\n")
    pool_output = tmp_path / "pool.parquet"
    candidate_output = tmp_path / "candidate.parquet"
    rejection_output = tmp_path / "rejections.parquet"
    monkeypatch.setattr(capital_builder, "RAW", raw)
    monkeypatch.setattr(capital_builder, "OUT", pool_output)
    monkeypatch.setattr(capital_builder, "CANDIDATE_OUT", candidate_output)
    monkeypatch.setattr(capital_builder, "REJECTIONS_OUT", rejection_output)
    monkeypatch.setattr(capital_builder, "VENUES", ("uniswap_v2",))
    monkeypatch.setattr(capital_builder, "pool_identity_files", lambda _venue, _raw: [])

    rows, candidate_rows, rejection_rows, summaries, sources = capital_builder.materialize()

    assert rows == 2
    assert candidate_rows == 4
    assert rejection_rows == 0
    assert len(sources) == 2
    assert summaries[0]["source_days"] == 2
    assert summaries[0]["days_with_rows"] == 2
    pool = pd.read_parquet(pool_output).sort_values("day")
    candidates = pd.read_parquet(candidate_output).sort_values(["day", "candidate"])
    assert pool["quantity_kind"].tolist() == ["deposited_capital"] * 2
    assert pool["pool_family"].tolist() == ["full_range_constant_product"] * 2
    assert pool["state_generation"].tolist() == ["provider_pool_day_v1"] * 2
    assert pool["exact_lag_valid"].tolist() == [False, True]
    assert pd.isna(pool[CAPITAL_COLUMN].iloc[0])
    assert pool[CAPITAL_COLUMN].iloc[1] == 1_000.0
    assert candidates.groupby("day")["candidate_capital_usd"].sum().to_dict() == {
        "20250101": 1_000.0,
        "20250102": 1_200.0,
    }
    assert candidates.groupby("day")["allocation_weight"].sum().eq(1.0).all()
    assert pd.read_parquet(rejection_output).empty


def test_pool_daily_coverage_gate_rejects_a_missing_calendar_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import ddvc.fetch.pool_daily as pool_daily

    files = [tmp_path / "uniswap_v2_daily_20250101.jsonl.gz"]
    files[0].touch()
    monkeypatch.setattr(
        pool_daily,
        "expected_pool_daily_days",
        lambda _venue: ("20250101", "20250102"),
    )

    with pytest.raises(RuntimeError, match="missing=1.*first_missing=20250102"):
        require_pool_daily_coverage("uniswap_v2", files)


def test_v3_pool_month_panel_cannot_leak_return_like_fields():
    dates = pd.date_range("2025-01-01", periods=16, freq="D")
    frame = pd.DataFrame(
        {
            "venue": "uniswap_v3",
            "pool": "pool",
            "month": dates.strftime("%Y-%m"),
            "day": dates.strftime("%Y%m%d"),
            "token0": "token0",
            "token1": "token1",
            "pool_role": "native / stable",
            "other_role": "stable",
            "gas_usd": 1.0,
            "fees_usd": 10.0,
            "lvr_usd": 5.0,
            "lvr_usd_4h": 4.0,
            "net_yield": 0.00004,
            "fee_yield": 0.0001,
            "lvr_rate": 0.00005,
            "gas_rate": 0.00001,
            "rv": 0.001,
            "turnover": 0.1,
            CAPITAL_COLUMN: 100_000.0,
            LOCAL_DEPTH_COLUMN: 1_000_000.0,
        }
    )
    centrality = pd.DataFrame(
        {
            "day": np.repeat(dates.strftime("%Y%m%d"), 2),
            "token": [token for _ in dates for token in ("token0", "token1")],
            "betweenness_volume": 0.1,
            "degree": 2.0,
        }
    )
    result = pool_months(frame, centrality, "uniswap_v3")
    assert len(result) == 1
    assert not result.iloc[0]["return_inference_ready"]
    for column in (
        "mean_net",
        "sd_net",
        "mean_fee",
        "mean_lvr",
        "mean_gas",
        "sharpe",
        "net_yield_apr",
        "fee_yield_apr",
        "net_positive",
        "log_fee_over_lvr",
    ):
        assert np.isnan(result.iloc[0][column])


def test_open_to_close_variance_is_the_total_move_squared():
    hours = np.arange(6, dtype=np.int64)
    prices = np.array([100.0, 101.0, 99.0, 103.0, 98.0, 102.0])
    rv1, rv4, rv_oc, mx = brp._rv_multiscale(hours, prices)
    assert rv_oc == pytest.approx(np.log(102.0 / 100.0) ** 2)
    assert rv1 == pytest.approx(float(np.sum(np.diff(np.log(prices)) ** 2)))
    assert mx == pytest.approx(float(np.max(np.abs(np.diff(np.log(prices))))))
    # Two four-hour buckets here, so the coarse estimate uses one return.
    assert rv4 < rv1


def test_coarse_sampling_strips_the_round_trip_that_fine_sampling_counts():
    """A price that bounces and comes back has variance at one scale and none at another."""
    hours = np.arange(8, dtype=np.int64)
    prices = np.array([100.0, 110.0, 100.0, 110.0, 100.0, 110.0, 100.0, 110.0])
    rv1, _rv4, rv_oc, _ = brp._rv_multiscale(hours, prices)
    assert rv1 > 0.05
    assert rv_oc == pytest.approx(np.log(1.1) ** 2)


def test_square_root_price_input_is_doubled_into_log_returns():
    hours = np.arange(3, dtype=np.int64)
    price = np.array([100.0, 121.0, 144.0])
    rv_price, _, _, _ = brp._rv_multiscale(hours, price)
    rv_sqrt, _, _, _ = brp._rv_multiscale(hours, np.sqrt(price), scale=2.0)
    assert rv_sqrt == pytest.approx(rv_price)


def test_lvr_closed_form_equals_the_numeric_delta_hedging_loss():
    """LVR rate is sigma^2/2 * P^2 * |dx/dP|, which for constant product is V * sigma^2/8.

    The pool holds x = L / sqrt(P) of the risky asset, so the derivative is taken
    numerically here rather than reusing the algebra the closed form came from.
    """
    liq, price = 1_234.0, 2_500.0
    h = price * 1e-6

    def x_of(p):
        return liq / np.sqrt(p)

    dxdp = (x_of(price + h) - x_of(price - h)) / (2 * h)
    sigma_sq = 0.04
    lvr_rate = 0.5 * sigma_sq * price ** 2 * abs(dxdp)
    pool_value = 2.0 * liq * np.sqrt(price)      # y + P*x with y = L*sqrt(P)
    assert lvr_rate == pytest.approx(sigma_sq / 8.0 * pool_value, rel=1e-6)


def test_virtual_reserves_reproduce_the_liquidity_invariant():
    liq, sqrt_price = 5e18, 3.0
    y = liq * sqrt_price
    x = liq / sqrt_price
    assert x * y == pytest.approx(liq ** 2)
    assert 2.0 * y == pytest.approx(y + (sqrt_price ** 2) * x)


def test_constant_product_pool_holds_equal_value_on_both_legs():
    """The identity the anchored valuation relies on, so a pool is worth twice one leg."""
    reserve0, reserve1 = 400.0, 1_000_000.0
    price0_in_1 = reserve1 / reserve0
    assert reserve0 * price0_in_1 == pytest.approx(reserve1)
    assert 2.0 * reserve1 == pytest.approx(reserve0 * price0_in_1 + reserve1)

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_v3_lp_provider_network_specialization import (
    PRIMARY_FAMILY_ID,
    USDC,
    WETH,
    build_specialization_choice_panel,
    event_level_summary,
    fit_choice_models,
    first_material_pool_events,
    summarize_events,
)


DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
ENDPOINT = "0x00000000000000000000000000000000000000aa"
OTHER = "0x00000000000000000000000000000000000000bb"


def _fee_panel(path: Path) -> None:
    rows = []
    for day, tvl in (("2025-01-05", 10_000.0), ("2025-01-08", 60_000.0)):
        rows.append(
            {
                "origin_date": pd.Timestamp(day),
                "pool": "0xfocal",
                "token0_address": USDC,
                "token0_symbol": "USDC",
                "token1_address": ENDPOINT,
                "token1_symbol": "TOKEN",
                "tvl_usd": tvl,
            }
        )
    # A two-candidate core pool must not become a spoke event.
    rows.append(
        {
            "origin_date": pd.Timestamp("2025-01-08"),
            "pool": "0xcore",
            "token0_address": USDC,
            "token0_symbol": "USDC",
            "token1_address": WETH,
            "token1_symbol": "WETH",
            "tvl_usd": 1_000_000.0,
        }
    )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _origin_panel(path: Path) -> None:
    rows = [
        # Focal supply during the first material week.
        ("2025-01-07", "0xfocal", "0xa", USDC, ENDPOINT, 100.0),
        ("2025-01-09", "0xfocal", "0xb", USDC, ENDPOINT, 300.0),
        # The following week's addition supplies the intensive-margin extension.
        ("2025-01-14", "0xfocal", "0xa", USDC, ENDPOINT, 80.0),
        # Valid outside-endpoint same-vehicle experience for origin A.
        ("2025-01-01", "0xusdc-other", "0xa", USDC, OTHER, 20.0),
        # A stable-core mint enters both token-specific vehicle histories.
        ("2025-01-01", "0xusdc-usdt-core", "0xa", USDC, USDT, 10.0),
        ("2025-01-01", "0xusdc-usdt-core", "0xa", USDT, USDC, 10.0),
        # Same endpoint and focal-pool histories are explicitly excluded.
        ("2025-01-02", "0xusdc-same-endpoint", "0xa", USDC, ENDPOINT, 30.0),
        ("2025-01-03", "0xfocal", "0xa", USDC, ENDPOINT, 40.0),
        # Alternative-vehicle experience is retained in the stacked comparison.
        ("2025-01-04", "0xweth-other", "0xa", WETH, OTHER, 50.0),
    ]
    pd.DataFrame(
        [
            {
                "origin_date": pd.Timestamp(day),
                "pool": pool,
                "origin": origin,
                "candidate_address": candidate,
                "candidate_symbol": {
                    USDC: "USDC",
                    WETH: "WETH",
                    DAI: "DAI",
                    USDT: "USDT",
                }[candidate],
                "paired_token_address": paired,
                "v3_add_action_events": 1,
                "v3_add_action_transactions": 1,
                "v3_add_flow_usd_screened": value,
            }
            for day, pool, origin, candidate, paired, value in rows
        ]
    ).to_parquet(path, index=False)


def test_provider_specialization_excludes_focal_endpoint_and_pool(
    tmp_path: Path,
) -> None:
    fees = tmp_path / "fees.parquet"
    origins = tmp_path / "origins.parquet"
    _fee_panel(fees)
    _origin_panel(origins)

    events = first_material_pool_events(fees, material_tvl_usd=50_000.0)
    assert len(events) == 1
    assert events.iloc[0]["event_week"] == pd.Timestamp("2025-01-06")
    panel, support = build_specialization_choice_panel(
        origins,
        events,
        lookback_days=30,
    )

    assert support["event_origin_observations"] == 2
    assert len(panel) == 8
    origin_a_usdc = panel.loc[
        panel["event_origin_id"].eq("0xfocal|0|0xa")
        & panel["history_candidate_address"].eq(USDC)
    ].iloc[0]
    assert origin_a_usdc["prior_distinct_pools"] == 2
    assert origin_a_usdc["prior_distinct_endpoints"] == 2
    assert origin_a_usdc["prior_add_actions"] == 2
    assert origin_a_usdc["prior_stable_core_distinct_pools"] == 1
    assert origin_a_usdc["prior_noncore_spoke_distinct_pools"] == 1

    origin_a_weth = panel.loc[
        panel["event_origin_id"].eq("0xfocal|0|0xa")
        & panel["history_candidate_address"].eq(WETH)
    ].iloc[0]
    assert origin_a_weth["prior_distinct_pools"] == 1

    summary = event_level_summary(panel).iloc[0]
    assert summary["experienced_origin_share"] == pytest.approx(0.5)
    assert summary["experienced_focal_flow_share"] == pytest.approx(0.25)
    assert summary["stable_core_experienced_origin_share"] == pytest.approx(0.5)
    assert summary["noncore_spoke_experienced_origin_share"] == pytest.approx(0.5)
    expected_margin = (np.log(3) - 2 * np.log(2) / 3) / 2
    assert summary[
        "mean_actual_minus_alternative_log1p_endpoints"
    ] == pytest.approx(expected_margin)
    table = summarize_events(pd.DataFrame([summary]))
    period = table.loc[
        table["record_type"].eq("v3_lp_provider_specialization_by_year")
    ].iloc[0]
    assert period["event_year"] == 2025
    assert period["events"] == 1
    assert period["mean_event_prior_stable_core_origin_share"] == pytest.approx(0.5)

    next_week, next_support = build_specialization_choice_panel(
        origins,
        events,
        lookback_days=30,
        supply_week_offset=1,
    )
    assert next_support["event_origin_observations"] == 1
    assert next_week["supply_week"].drop_duplicates().item() == pd.Timestamp(
        "2025-01-13"
    )
    assert set(next_week["event_origin_id"]) == {"0xfocal|1|0xa"}


def test_primary_family_uses_two_way_clustering_and_holm_adjustment() -> None:
    rng = np.random.default_rng(1977)
    candidates = [WETH, DAI, USDC, USDT]
    rows = []
    for event in range(80):
        pool = f"0xpool{event:04d}"
        actual_index = event % len(candidates)
        actual_candidate = candidates[actual_index]
        vehicle_type = "WETH" if actual_candidate == WETH else "stable"
        for provider_slot in range(2):
            origin = f"0xorigin{(event * 2 + provider_slot) % 50:04d}"
            event_origin = f"{pool}|0|{origin}"
            for candidate_index, candidate in enumerate(candidates):
                is_actual = int(candidate_index == actual_index)
                prior_any = int(
                    rng.random() < (0.68 if is_actual else 0.28)
                )
                prior_endpoints = rng.poisson(0.7 + 1.4 * is_actual)
                stable_core_any = int(
                    candidate != WETH
                    and rng.random() < (0.55 if is_actual else 0.20)
                )
                stable_core_pools = (
                    rng.poisson(0.4 + 1.0 * is_actual)
                    if candidate != WETH
                    else 0
                )
                rows.append(
                    {
                        "material_tvl_usd": 50_000.0,
                        "lookback_days": 90,
                        "supply_week_offset": 0,
                        "vehicle_type": vehicle_type,
                        "history_candidate_address": candidate,
                        "is_actual_vehicle": is_actual,
                        "prior_same_vehicle_any": prior_any,
                        "log1p_prior_distinct_endpoints": np.log1p(prior_endpoints),
                        "prior_stable_core_any": stable_core_any,
                        "log1p_prior_stable_core_pools": np.log1p(
                            stable_core_pools
                        ),
                        "event_origin_id": event_origin,
                        "candidate_quarter_id": f"{candidate}|2025Q1",
                        "pool": pool,
                        "origin": origin,
                    }
                )
    models = fit_choice_models(pd.DataFrame(rows))
    primary = models.loc[models["specification_role"].eq("primary")]
    assert len(primary) == 4
    assert set(primary["family_id"]) == {PRIMARY_FAMILY_ID}
    assert set(primary["family_size"]) == {4.0}
    broad = primary.loc[primary["model_id"].str.startswith(("m1_", "m2_"))]
    core = primary.loc[primary["model_id"].str.startswith(("m3_", "m4_"))]
    assert (broad["pool_clusters"] == 80).all()
    assert (core["pool_clusters"] == 60).all()
    assert (primary["transaction_origin_clusters"] == 50).all()
    assert primary["holm_adjusted_p_value"].notna().all()
    assert (
        primary["holm_adjusted_p_value"] + 1e-15 >= primary["p_value"]
    ).all()
    assert set(models["inference"]) == {
        "two_way_pool_and_transaction_origin_clustered"
    }

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_stablecoin_supply_lp import (
    aggregate_relationship_capital,
    add_declared_family_adjustment,
    assign_stable_roles,
    monthly_supply_panel,
    prepare_capital_growth_panel,
    prepare_formation_panel,
    prepare_stablecoin_scope_panel,
)
from scripts.fetch.fetch_defillama_stablecoin_supply import candidate_detail_ids
from scripts.process.build_stablecoin_supply import (
    load_detail_payloads,
    parse_detail_supply,
    select_canonical_details,
    source_ethereum_address,
    source_ethereum_addresses,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
ENDPOINT = "0x0000000000000000000000000000000000000001"
NEVER_ENDPOINT = "0x0000000000000000000000000000000000000002"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"


def _timestamp(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").timestamp())


def _detail(
    identifier: str,
    symbol: str,
    address: str,
    values: list[tuple[str, float]],
) -> dict[str, object]:
    records = [
        {"date": _timestamp(day), "circulating": {"peggedUSD": value}}
        for day, value in values
    ]
    return {
        "id": identifier,
        "name": symbol,
        "symbol": symbol,
        "address": address,
        "pegType": "peggedUSD",
        "pegMechanism": "fiat-backed",
        "tokens": records,
        "chainBalances": {"Ethereum": {"tokens": records}},
    }


def test_fetch_and_process_require_an_ethereum_specific_address() -> None:
    catalog = {
        "peggedAssets": [
            {"id": "2", "symbol": "USDC"},
            {"id": "999", "symbol": "USDC"},
            {"id": "1", "symbol": "USDT"},
        ]
    }
    assert candidate_detail_ids(catalog, symbols={"USDC"}) == ("2", "999")
    assert source_ethereum_address(f"ethereum:{USDC.upper()}") == USDC
    assert source_ethereum_address(f"bsc:{USDC}") is None

    right = _detail("2", "USDC", f"bsc:{USDC}", [("2025-01-31", 10.0)])
    right["chainConfig"] = {"chains": {"ethereum": {"issued": [USDC.upper()]}}}
    assert source_ethereum_addresses(right) == frozenset({USDC})
    wrong = _detail(
        "999",
        "USDC",
        f"bsc:{USDC}",
        [("2025-01-31", 10.0)],
    )
    usdt = _detail("1", "USDT", USDT, [("2025-01-31", 10.0)])
    dai = _detail(
        "5",
        "DAI",
        DAI,
        [("2025-01-31", 10.0)],
    )
    selected, support = select_canonical_details([right, wrong, usdt, dai])
    assert selected[USDC]["id"] == "2"
    mapping = pd.DataFrame(support)
    assert mapping.loc[mapping["token_symbol"].eq("USDC"), "source_id"].iloc[0] == "2"
    assert (
        mapping.loc[mapping["token_symbol"].eq("USDC"), "mapping_method"].iloc[0]
        == "ethereum_chain_config"
    )


def test_manifest_excludes_stale_detail_files(tmp_path: Path) -> None:
    detail_dir = tmp_path / "details"
    detail_dir.mkdir()
    catalog_path = tmp_path / "catalog.json"
    manifest_path = tmp_path / "manifest.json"
    catalog_path.write_text(
        json.dumps(
            {"peggedAssets": [{"id": "2", "symbol": "USDC"}, {"id": "9", "symbol": "USDC"}]}
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps({"detail_ids": ["2"]}), encoding="utf-8")
    (detail_dir / "2.json").write_text(
        json.dumps(_detail("2", "USDC", USDC, [("2025-01-31", 10.0)])),
        encoding="utf-8",
    )
    (detail_dir / "9.json").write_text(
        json.dumps(_detail("9", "USDC", USDC, [("2025-01-31", 20.0)])),
        encoding="utf-8",
    )
    details, paths = load_detail_payloads(
        detail_dir,
        catalog_path=catalog_path,
        manifest_path=manifest_path,
    )
    assert [detail["id"] for detail in details] == ["2"]
    assert [path.name for path in paths] == ["2.json"]


def test_manifest_requires_every_declared_detail(tmp_path: Path) -> None:
    detail_dir = tmp_path / "details"
    detail_dir.mkdir()
    catalog_path = tmp_path / "catalog.json"
    manifest_path = tmp_path / "manifest.json"
    catalog_path.write_text(
        json.dumps({"peggedAssets": [{"id": "2", "symbol": "USDC"}]}),
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps({"detail_ids": ["2"]}), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_detail_payloads(
            detail_dir,
            catalog_path=catalog_path,
            manifest_path=manifest_path,
        )


def test_parse_detail_supply_aligns_asset_wide_and_ethereum_dates() -> None:
    detail = _detail(
        "2",
        "USDC",
        USDC,
        [("2025-01-31", 100.0), ("2025-02-28", 110.0)],
    )
    detail["chainBalances"] = {
        "Ethereum": {
            "tokens": [
                {
                    "date": _timestamp("2025-01-31"),
                    "circulating": {"peggedUSD": 60.0},
                },
                {
                    "date": _timestamp("2025-02-28"),
                    "circulating": {"peggedUSD": 65.0},
                },
            ]
        }
    }
    panel = parse_detail_supply(detail, token_address=USDC, token_symbol="USDC")
    assert panel["asset_wide_circulating"].tolist() == [100.0, 110.0]
    assert panel["ethereum_circulating"].tolist() == [60.0, 65.0]


def test_stable_roles_duplicate_core_for_each_stablecoin_side() -> None:
    pools = pd.DataFrame(
        [
            {
                "origin_month": pd.Timestamp("2025-01-01"),
                "venue": "uniswap_v2",
                "pool": "0xcore",
                "token0_address": USDC,
                "token1_address": USDT,
                "capital_usd": 100_000.0,
                "observed_date": pd.Timestamp("2025-01-31"),
                "staleness_days": 0,
            },
            {
                "origin_month": pd.Timestamp("2025-01-01"),
                "venue": "uniswap_v3",
                "pool": "0xspoke",
                "token0_address": USDC,
                "token1_address": ENDPOINT,
                "capital_usd": 50_000.0,
                "observed_date": pd.Timestamp("2025-01-31"),
                "staleness_days": 0,
            },
        ]
    )
    roles = assign_stable_roles(pools)
    assert len(roles) == 3
    assert roles["scope"].value_counts().to_dict() == {
        "stable_core": 2,
        "stable_spoke": 1,
    }
    core = roles[roles["scope"].eq("stable_core")]
    assert set(core["stablecoin_address"]) == {USDC, USDT}
    relationships = aggregate_relationship_capital(roles)
    core_links = relationships[relationships["scope"].eq("stable_core")]
    assert core_links["pair_id"].nunique() == 2
    assert core_links["undirected_link_id"].nunique() == 1


def test_month_end_uses_last_nonmissing_value_for_each_measure() -> None:
    daily = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2025-01-31"),
                "token_address": USDC,
                "token_symbol": "USDC",
                "asset_wide_circulating": 100_000_000.0,
                "ethereum_circulating": 60_000_000.0,
            },
            {
                "date": pd.Timestamp("2025-02-20"),
                "token_address": USDC,
                "token_symbol": "USDC",
                "asset_wide_circulating": 110_000_000.0,
                "ethereum_circulating": 66_000_000.0,
            },
            {
                "date": pd.Timestamp("2025-02-28"),
                "token_address": USDC,
                "token_symbol": "USDC",
                "asset_wide_circulating": 120_000_000.0,
                "ethereum_circulating": np.nan,
            },
        ]
    )
    monthly = monthly_supply_panel(daily)
    february = monthly.loc[
        monthly["origin_month"].eq(pd.Timestamp("2025-02-01"))
    ].iloc[0]
    assert february["asset_wide_circulating"] == 120_000_000.0
    assert february["ethereum_circulating"] == 66_000_000.0
    assert february["asset_wide_circulating_observation_date"] == pd.Timestamp(
        "2025-02-28"
    )
    assert february["ethereum_circulating_observation_date"] == pd.Timestamp(
        "2025-02-20"
    )
    assert february["asset_wide_circulating_growth"] == pytest.approx(np.log(1.2))
    assert february["ethereum_circulating_growth"] == pytest.approx(np.log(1.1))


def test_supply_growth_precedes_capital_growth_and_formation() -> None:
    daily_rows: list[dict[str, object]] = []
    for address, symbol, values in (
        (USDC, "USDC", [100.0, 110.0, 121.0, 133.1]),
        (USDT, "USDT", [100.0, 100.0, 100.0, 100.0]),
    ):
        for day, value in zip(
            pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"]),
            values,
            strict=True,
        ):
            daily_rows.append(
                {
                    "date": day,
                    "token_address": address,
                    "token_symbol": symbol,
                    "asset_wide_circulating": value * 1_000_000.0,
                    "ethereum_circulating": value * 500_000.0,
                }
            )
    supply = monthly_supply_panel(pd.DataFrame(daily_rows))

    roles: list[dict[str, object]] = []
    for month, capital in (
        ("2025-02-01", 60_000.0),
        ("2025-03-01", 90_000.0),
        ("2025-04-01", 120_000.0),
    ):
        roles.append(
            {
                "origin_month": pd.Timestamp(month),
                "stablecoin_address": USDC,
                "stablecoin_symbol": "USDC",
                "endpoint_address": ENDPOINT,
                "scope": "stable_spoke",
                "capital_usd": capital,
                "pool": "0xpool",
                "venue": "uniswap_v2",
                "staleness_days": 0,
            }
        )
    # USDT creates the comparison endpoint-month cells and first crosses the
    # material threshold in April.
    for month, capital in (
        ("2025-02-01", 1_000.0),
        ("2025-03-01", 10_000.0),
        ("2025-04-01", 70_000.0),
    ):
        roles.append(
            {
                "origin_month": pd.Timestamp(month),
                "stablecoin_address": USDT,
                "stablecoin_symbol": "USDT",
                "endpoint_address": ENDPOINT,
                "scope": "stable_spoke",
                "capital_usd": capital,
                "pool": "0xpool2",
                "venue": "uniswap_v2",
                "staleness_days": 0,
            }
        )
    relationships = aggregate_relationship_capital(pd.DataFrame(roles))
    growth = prepare_capital_growth_panel(relationships, supply)
    usdc_february = growth[
        growth["stablecoin_address"].eq(USDC)
        & growth["origin_month"].eq(pd.Timestamp("2025-02-01"))
    ].iloc[0]
    assert usdc_february["asset_wide_circulating_growth"] == pytest.approx(
        np.log(1.1)
    )
    assert usdc_february["next_capital_usd"] == pytest.approx(90_000.0)
    assert usdc_february["next_pure_log_capital_change"] == pytest.approx(
        np.log(90_000.0 / 60_000.0)
    )
    assert np.isfinite(usdc_february["next_asinh_capital_change"])

    endpoint_eligibility = pd.DataFrame(
        {
            "endpoint_address": [ENDPOINT, NEVER_ENDPOINT],
            "endpoint_first_eligible_month": [
                pd.Timestamp("2025-02-01"),
                pd.Timestamp("2025-02-01"),
            ],
        }
    )
    formation = prepare_formation_panel(
        relationships,
        supply,
        endpoint_eligibility,
    )
    usdt_march = formation[
        formation["stablecoin_address"].eq(USDT)
        & formation["origin_month"].eq(pd.Timestamp("2025-03-01"))
    ].iloc[0]
    assert usdt_march["forms_next_month"] == 1.0
    never = formation[formation["endpoint_address"].eq(NEVER_ENDPOINT)]
    assert not never.empty
    assert never["first_material_month"].isna().all()
    assert never["forms_next_month"].eq(0.0).all()

    stablecoin_scope = prepare_stablecoin_scope_panel(relationships, supply)
    usdt_march_scope = stablecoin_scope[
        stablecoin_scope["stablecoin_address"].eq(USDT)
        & stablecoin_scope["scope"].eq("stable_spoke")
        & stablecoin_scope["origin_month"].eq(pd.Timestamp("2025-03-01"))
    ].iloc[0]
    assert usdt_march_scope["next_new_material_links"] == 1.0


def test_declared_asset_wide_core_spoke_family_uses_holm_adjustment() -> None:
    models = pd.DataFrame(
        [
            {
                "model_family": family,
                "scope": scope,
                "supply_measure": "asset_wide",
                "predictor": "supply_growth_per_10pct",
                "p_value": p_value,
            }
            for family, scope, p_value in (
                ("capital_growth", "stable_core", 0.01),
                ("capital_growth", "stable_spoke", 0.02),
                ("formation", "stable_core", 0.03),
                ("formation", "stable_spoke", 0.20),
            )
        ]
    )
    adjusted = add_declared_family_adjustment(models)
    assert adjusted["p_value_holm"].tolist() == pytest.approx(
        [0.04, 0.06, 0.06, 0.20]
    )
    assert adjusted["family_hypotheses"].eq(4).all()

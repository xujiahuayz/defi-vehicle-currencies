from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.tables import read_exhibit
from scripts.analyze.run_v3_lp_launch_supply import (
    COMPARISON_PERIOD,
    USDC,
    WETH,
    build_outputs,
    run,
)


ENDPOINT_A = "0x00000000000000000000000000000000000000aa"
ENDPOINT_B = "0x00000000000000000000000000000000000000bb"
ENDPOINT_C = "0x00000000000000000000000000000000000000cc"


def _write_pool_days(path: Path) -> None:
    rows = [
        # A surviving, material stable-facing launch pool in each endpoint period.
        ("2024-01-01", "0xstable24", 10_000.0),
        ("2024-01-31", "0xstable24", 60_000.0),
        ("2024-03-31", "0xstable24", 70_000.0),
        ("2026-01-01", "0xstable26", 10_000.0),
        ("2026-01-31", "0xstable26", 60_000.0),
        ("2026-04-01", "0xstable26", 70_000.0),
        # WETH-facing launch pools have no later observed pool-day.
        ("2024-01-01", "0xweth24", 10_000.0),
        ("2026-01-01", "0xweth26", 10_000.0),
        # The old pool supplies the >90-day age cell.
        ("2023-01-01", "0xoldstable", 100_000.0),
        ("2024-02-01", "0xoldstable", 100_000.0),
        # This core pool must not enter any retained spoke result.
        ("2024-01-01", "0xcore", 1_000_000.0),
    ]
    pd.DataFrame(rows, columns=["origin_date", "pool", "tvl_usd"]).assign(
        origin_date=lambda x: pd.to_datetime(x["origin_date"])
    ).to_parquet(path, index=False)


def _origin_row(
    day: str,
    pool: str,
    origin: str,
    candidate: str,
    endpoint: str,
    actions: float,
    flow: float,
) -> dict[str, object]:
    return {
        "origin_date": pd.Timestamp(day),
        "pool": pool,
        "origin": origin,
        "candidate_address": candidate,
        "paired_token_address": endpoint,
        "v3_add_action_events": actions,
        "v3_add_action_transactions": actions,
        "v3_add_flow_usd_screened": flow,
    }


def _write_origins(path: Path) -> None:
    rows = [
        # The three origin-history classes appear in the 2024 stable cell.
        _origin_row(
            "2024-01-01", "0xstable24", "0xsingle", USDC, ENDPOINT_A, 1, 10
        ),
        _origin_row(
            "2024-01-01", "0xstable24", "0xrepeat", USDC, ENDPOINT_A, 2, 20
        ),
        _origin_row(
            "2024-01-02", "0xstable24", "0xrepeat", USDC, ENDPOINT_A, 3, 30
        ),
        _origin_row(
            "2024-01-01", "0xstable24", "0xmulti", USDC, ENDPOINT_A, 4, 40
        ),
        _origin_row(
            "2024-02-01", "0xoldstable", "0xmulti", USDC, ENDPOINT_B, 5, 50
        ),
        _origin_row(
            "2024-01-01", "0xweth24", "0xwethsingle", WETH, ENDPOINT_C, 2, 20
        ),
        # Multi remains active in both endpoint periods and in multiple pools.
        _origin_row(
            "2026-01-01", "0xstable26", "0xmulti", USDC, ENDPOINT_A, 6, 60
        ),
        _origin_row(
            "2026-01-01", "0xstable26", "0xsingle26", USDC, ENDPOINT_A, 1, 10
        ),
        _origin_row(
            "2026-01-01", "0xweth26", "0xweth26", WETH, ENDPOINT_C, 2, 20
        ),
        # Stable--WETH is a two-candidate core and must be excluded.
        _origin_row("2024-01-01", "0xcore", "0xcore", USDC, WETH, 999, 999),
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)


def _flow_row(
    day: str,
    pool: str,
    candidate: str,
    endpoint: str,
    add: float,
    remove: float,
) -> dict[str, object]:
    return {
        "origin_date": pd.Timestamp(day),
        "pool": pool,
        "candidate_address": candidate,
        "paired_token_address": endpoint,
        "v3_add_only_lp_flow_usd_screened": add,
        "v3_remove_only_lp_flow_usd_screened": remove,
        "v3_net_add_remove_only_lp_flow_usd_screened": add - remove,
    }


def _write_flows(path: Path) -> None:
    rows = [
        # Pool day 5 is seeding and excluded; days 10/20 enter both horizons.
        _flow_row("2024-01-06", "0xstable24", USDC, ENDPOINT_A, 999, 0),
        _flow_row("2024-01-11", "0xstable24", USDC, ENDPOINT_A, 10, 0),
        _flow_row("2024-01-21", "0xstable24", USDC, ENDPOINT_A, 0, 3),
        # This removal enters 90-day but not 30-day post-launch flow.
        _flow_row("2024-02-10", "0xstable24", USDC, ENDPOINT_A, 0, 4),
        _flow_row("2026-01-11", "0xstable26", USDC, ENDPOINT_A, 5, 0),
        _flow_row("2026-01-21", "0xstable26", USDC, ENDPOINT_A, 0, 1),
        _flow_row("2024-01-11", "0xweth24", WETH, ENDPOINT_C, 1, 0),
        _flow_row("2026-01-11", "0xweth26", WETH, ENDPOINT_C, 1, 0),
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    origins = tmp_path / "origins.parquet"
    flows = tmp_path / "flows.parquet"
    pool_days = tmp_path / "pool_days.parquet"
    _write_origins(origins)
    _write_flows(flows)
    _write_pool_days(pool_days)
    return origins, flows, pool_days


def test_launch_supply_separates_age_origin_history_and_followup(
    tmp_path: Path,
) -> None:
    origins, flows, pool_days = _inputs(tmp_path)
    output, support = build_outputs(
        origin_path=origins,
        flow_path=flows,
        pool_day_path=pool_days,
    )
    assert support.iloc[0]["missing_pool_inception_rows"] == 0
    assert support.iloc[0]["negative_pool_age_rows"] == 0

    age = output.loc[output["record_type"].eq("v3_lp_supply_by_pool_age")]
    stable_2024 = age.loc[
        age["period"].eq("2024H1") & age["vehicle_type"].eq("stable")
    ].set_index("pool_age_bin")
    assert stable_2024.loc["0-7", "addition_action_events"] == 10
    assert stable_2024.loc[">90", "addition_action_events"] == 5
    assert stable_2024.loc["0-7", "pool_age_share_of_vehicle_actions"] == pytest.approx(
        2 / 3
    )

    history = output.loc[output["record_type"].eq("v3_lp_origin_history")]
    stable_2024_history = history.loc[
        history["period"].eq("2024H1")
        & history["vehicle_type"].eq("stable")
    ].set_index(["endpoint_period_membership", "origin_history_class"])
    assert stable_2024_history.loc[
        ("period-specific", "one-day/one-pool"), "transaction_origin_proxies"
    ] == 1
    assert stable_2024_history.loc[
        ("period-specific", "repeat-day/one-pool"), "addition_action_events"
    ] == 5
    assert stable_2024_history.loc[
        ("continuing", "multi-pool"), "transaction_origin_proxies"
    ] == 1

    followup = output.loc[output["record_type"].eq("v3_lp_launch_followup")]
    stable_30 = followup.loc[
        followup["period"].eq("2024H1")
        & followup["vehicle_type"].eq("stable")
        & followup["horizon_days"].eq(30)
    ].iloc[0]
    assert stable_30["launch_pools"] == 1
    assert stable_30["active_pool_share"] == 1
    assert stable_30["material_pool_share"] == 1
    assert stable_30["post_launch_add_only_flow_usd"] == 10
    assert stable_30["post_launch_remove_only_flow_usd"] == 3
    assert stable_30["post_launch_net_flow_usd"] == 7

    stable_90 = followup.loc[
        followup["period"].eq("2024H1")
        & followup["vehicle_type"].eq("stable")
        & followup["horizon_days"].eq(90)
    ].iloc[0]
    assert stable_90["post_launch_net_flow_usd"] == 3
    weth_30 = followup.loc[
        followup["period"].eq("2024H1")
        & followup["vehicle_type"].eq("WETH")
        & followup["horizon_days"].eq(30)
    ].iloc[0]
    assert weth_30["active_pool_share"] == 0
    assert weth_30["material_pool_share"] == 0


def test_launch_supply_run_writes_machine_readable_outputs(tmp_path: Path) -> None:
    origins, flows, pool_days = _inputs(tmp_path)
    output_path = tmp_path / "launch.jsonl"
    support_path = tmp_path / "support.jsonl"
    assert (
        run(
            origin_path=origins,
            flow_path=flows,
            pool_day_path=pool_days,
            output_path=output_path,
            support_path=support_path,
        )
        == 0
    )
    output = read_exhibit(output_path)
    assert set(output["record_type"]) == {
        "v3_lp_supply_by_pool_age",
        "v3_lp_origin_history",
        "v3_lp_launch_followup",
    }
    assert COMPARISON_PERIOD in set(output["period"].dropna())
    checked_support = read_exhibit(support_path)
    assert checked_support.iloc[0]["full_sample_spoke_pools"] == 5

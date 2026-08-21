from __future__ import annotations

import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.analyze.run_balancer_stable_core_lp_flows import (
    attach_trailing_relative_volatility,
    build_pool_concentration,
    summarize_flows,
)
from scripts.process.build_balancer_stable_core_lp_flow_weekly import (
    aggregate_balancer_stable_core_events,
    classify_stable_core_or_spoke_pool,
    complete_pool_week_calendar,
    load_balancer_stable_core_events,
    load_balancer_stable_core_lagged_state,
    validate_balancer_stable_core_panel,
)


DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
AGEUR = "0x1a7e4e63778b4f12a199c062f3efdd288afcbce8"
OTHER = "0x00000000000000000000000000000000000000cc"
POOL_CORE = "0x00000000000000000000000000000000000000aa000200000000000000000001"
POOL_SPOKE = "0x00000000000000000000000000000000000000bb000200000000000000000002"


def _timestamp(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").timestamp())


def _event(
    *,
    pool: str,
    tokens: list[str],
    amounts: list[str],
    event_type: str,
    event_id: str,
    day: str = "2025-06-02",
) -> dict[str, object]:
    return {
        "id": event_id,
        "type": event_type,
        "sender": "0x0000000000000000000000000000000000000abc",
        "user": "0x0000000000000000000000000000000000000def",
        "amounts": amounts,
        "valueUSD": str(sum(float(value) for value in amounts)),
        "timestamp": _timestamp(day),
        "block": "100",
        "tx": f"0x{event_id:0>64}",
        "pool": {"id": pool, "tokensList": tokens},
    }


def _write_gzip(path: Path, rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class BalancerStablePoolDefinitionTests(unittest.TestCase):
    def test_exact_core_spoke_and_exclusions(self) -> None:
        core, reason = classify_stable_core_or_spoke_pool(
            _event(
                pool=POOL_CORE,
                tokens=[DAI, USDC],
                amounts=["1", "1"],
                event_type="Join",
                event_id="1",
            )
        )
        self.assertIsNone(reason)
        self.assertEqual(core.pool_class, "stable_core")

        spoke, reason = classify_stable_core_or_spoke_pool(
            _event(
                pool=POOL_SPOKE,
                tokens=[USDC, WETH],
                amounts=["1", "1"],
                event_type="Join",
                event_id="2",
            )
        )
        self.assertIsNone(reason)
        self.assertEqual(spoke.pool_class, "stable_spoke")

        non_usd, reason = classify_stable_core_or_spoke_pool(
            _event(
                pool=POOL_CORE,
                tokens=[USDC, AGEUR],
                amounts=["1", "1"],
                event_type="Join",
                event_id="3",
            )
        )
        self.assertIsNone(non_usd)
        self.assertEqual(reason, "contains_non_usd_stablecoin")

        basket, reason = classify_stable_core_or_spoke_pool(
            _event(
                pool=POOL_CORE,
                tokens=[USDC, WETH, OTHER],
                amounts=["1", "1", "1"],
                event_type="Join",
                event_id="4",
            )
        )
        self.assertIsNone(basket)
        self.assertEqual(reason, "outside_exact_core_or_two_token_spoke")

        bpt_pool = "0x1111111111111111111111111111111111111111000200000000000000000001"
        bpt, reason = classify_stable_core_or_spoke_pool(
            _event(
                pool=bpt_pool,
                tokens=[USDC, bpt_pool[:42]],
                amounts=["1", "1"],
                event_type="Join",
                event_id="5",
            )
        )
        self.assertIsNone(bpt)
        self.assertEqual(reason, "contains_balancer_pool_token")


class BalancerStableFlowBuildTests(unittest.TestCase):
    def test_events_and_refreshed_daily_schema_build_exact_lagged_state(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_gzip(
                root / "balancer_joins_exits_20250602.jsonl.gz",
                [
                    _event(
                        pool=POOL_CORE,
                        tokens=[DAI, USDC],
                        amounts=["100", "200"],
                        event_type="Join",
                        event_id="11",
                    ),
                    _event(
                        pool=POOL_CORE,
                        tokens=[DAI, USDC],
                        amounts=["40", "10"],
                        event_type="Exit",
                        event_id="12",
                    ),
                    _event(
                        pool=POOL_SPOKE,
                        tokens=[USDC, WETH],
                        amounts=["100", "1"],
                        event_type="Join",
                        event_id="13",
                    ),
                ],
            )
            price_lookup = {
                ("20250602", DAI): 1.0,
                ("20250602", USDC): 1.0,
                ("20250602", WETH): 2_000.0,
            }
            events, registry, support = load_balancer_stable_core_events(
                raw_dir=root,
                price_lookup=price_lookup,
            )
            self.assertEqual(support["stable_core_events"], 2)
            self.assertEqual(support["stable_spoke_events"], 1)
            core_events = events[events["pool_class"].eq("stable_core")]
            self.assertEqual(core_events["priced_flow_usd"].sum(), 350.0)
            spoke_event = events[events["pool_class"].eq("stable_spoke")].iloc[0]
            self.assertEqual(spoke_event["priced_flow_usd"], 2_100.0)

            # The refreshed schema adds full pool statics and token metadata.
            # The state reader must continue to use the top-level cumulative
            # volume and liquidity fields without depending on the old sparse
            # shape of ``pool``.
            for day, core_volume, spoke_volume in (
                ("2025-05-25", 1_000.0, 500.0),
                ("2025-06-01", 1_700.0, 900.0),
            ):
                rows = []
                for pool, tokens, volume, tvl in (
                    (POOL_CORE, [DAI, USDC], core_volume, 10_000.0),
                    (POOL_SPOKE, [USDC, WETH], spoke_volume, 20_000.0),
                ):
                    rows.append(
                        {
                            "id": f"{pool}-{day}",
                            "timestamp": _timestamp(day),
                            "amounts": ["1", "1"],
                            "liquidity": str(tvl),
                            "swapVolume": str(volume),
                            "swapFees": "1",
                            "totalShares": "100",
                            "pool": {
                                "id": pool,
                                "poolType": "Stable" if pool == POOL_CORE else "Weighted",
                                "poolTypeVersion": 2,
                                "tokensList": tokens,
                                "tokens": [
                                    {
                                        "address": token,
                                        "symbol": "TOKEN",
                                        "decimals": 18,
                                        "balance": "1",
                                        "weight": "0.5",
                                    }
                                    for token in tokens
                                ],
                            },
                        }
                    )
                _write_gzip(
                    root / f"balancer_daily_{day.replace('-', '')}.jsonl.gz",
                    rows,
                )

            flow = aggregate_balancer_stable_core_events(events)
            state, state_support = load_balancer_stable_core_lagged_state(
                raw_dir=root,
                registry=registry,
            )
            self.assertEqual(state_support["lagged_state_complete_pool_weeks"], 2)
            complete = state[state["lagged_state_complete"]]
            self.assertEqual(
                complete.set_index("pool").loc[POOL_CORE, "lagged_volume_usd"],
                700.0,
            )
            panel = complete_pool_week_calendar(flow, state, registry)
            validate_balancer_stable_core_panel(panel)
            core_week = panel[
                panel["pool"].eq(POOL_CORE)
                & panel["week_start"].eq(pd.Timestamp("2025-06-02"))
            ].iloc[0]
            self.assertEqual(core_week["priced_join_flow_usd"], 300.0)
            self.assertEqual(core_week["priced_exit_flow_usd"], 50.0)
            self.assertEqual(core_week["priced_net_join_flow_usd"], 250.0)
            self.assertEqual(core_week["lagged_reported_tvl_usd"], 10_000.0)


class BalancerStableFlowAnalysisTests(unittest.TestCase):
    def _panel(self) -> pd.DataFrame:
        rows = []
        for pool, pool_class, gross, joins, exits in (
            ("core_a", "stable_core", 80.0, 60.0, 20.0),
            ("core_b", "stable_core", 20.0, 5.0, 15.0),
            ("spoke_a", "stable_spoke", 50.0, 30.0, 20.0),
            ("spoke_b", "stable_spoke", 50.0, 20.0, 30.0),
        ):
            rows.append(
                {
                    "week_start": pd.Timestamp("2025-06-02"),
                    "pool": pool,
                    "pool_class": pool_class,
                    "token_addresses": (
                        f"{DAI},{USDC}"
                        if pool_class == "stable_core"
                        else f"{USDC},{WETH}"
                    ),
                    "join_event_count": 2,
                    "exit_event_count": 1,
                    "event_count": 3,
                    "priced_event_count": 3,
                    "priced_join_flow_usd": joins,
                    "priced_exit_flow_usd": exits,
                    "priced_gross_flow_usd": gross,
                    "priced_net_join_flow_usd": joins - exits,
                    "flow_value_complete": True,
                }
            )
        return pd.DataFrame(rows)

    def test_concentration_and_leave_largest_pool_out(self) -> None:
        panel = self._panel()
        concentration, dominant = build_pool_concentration(panel)
        self.assertEqual(dominant["stable_core"], "core_a")
        core_a = concentration[
            concentration["pool"].eq("core_a")
        ].iloc[0]
        self.assertAlmostEqual(core_a["priced_gross_flow_share"], 0.8)
        self.assertAlmostEqual(core_a["priced_flow_hhi"], 0.68)
        summary = summarize_flows(panel, dominant)
        leave_out = summary[
            summary["pool_class"].eq("stable_core")
            & summary["sample"].eq("exclude_largest_pool")
        ].iloc[0]
        self.assertEqual(leave_out["excluded_pool"], "core_a")
        self.assertEqual(leave_out["priced_gross_flow_usd"], 20.0)
        self.assertEqual(leave_out["priced_net_join_flow_usd"], -10.0)

    def test_relative_price_risk_uses_all_pool_token_pairs(self) -> None:
        panel = self._panel().iloc[[0]].copy()
        panel["week_start"] = pd.Timestamp("2025-02-03")
        rows = []
        for index, day in enumerate(pd.date_range("2025-01-01", "2025-02-02")):
            rows.extend(
                [
                    {"day": day, "token": DAI, "price_usd": 1.0 + 0.0005 * index},
                    {"day": day, "token": USDC, "price_usd": 1.0},
                ]
            )
        result = attach_trailing_relative_volatility(panel, pd.DataFrame(rows))
        self.assertGreater(
            result.iloc[0]["trailing_relative_volatility_annualized"],
            0.0,
        )
        self.assertGreaterEqual(result.iloc[0]["trailing_relative_return_days"], 20)


if __name__ == "__main__":
    unittest.main()

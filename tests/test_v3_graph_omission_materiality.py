from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from argparse import Namespace
from unittest.mock import patch

import duckdb
import pandas as pd
import scripts.fetch_pool_identity_registry as static_producer
import scripts.audit_v3_graph_omission_materiality as omission_audit
from ddvc.runtime import exclusive_job

from ddvc.v3_graph_materiality import (
    GRAPH_STATIC_FIELDS,
    GRAPH_STATIC_VALIDATION,
    graph_daily_provider_bound,
    graph_event_coverage_materiality,
    event_coverage_clears_state_estimands,
    omitted_static_state_pool_perimeter,
    graph_pool_snapshot,
    register_installed_inventory_events,
    route_opportunity_exposure,
    route_estimand_perturbation_bounds,
)
from ddvc.v3_inventory import EVENT_TOPICS
from ddvc.pricing.v3pools import compute_pool_address
from ddvc.fetch.pool_daily import UNISWAP_V3_STATIC_QUERY_CONTRACT


def provider_row(
    pool: str,
    tx_hash: str,
    block: int,
    log_index: int,
    event_id: str,
) -> dict[str, object]:
    return {
        "id": event_id,
        "logIndex": str(log_index),
        "pool": {"id": pool},
        "transaction": {"id": tx_hash, "blockNumber": str(block)},
    }


class V3GraphOmissionMaterialityTests(unittest.TestCase):
    def test_audit_holds_raw_mutation_lease_through_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "raw.lock"
            entered = threading.Event()
            release = threading.Event()
            errors: list[BaseException] = []

            def paused_audit(_args):
                entered.set()
                self.assertTrue(release.wait(timeout=10))
                return 0

            def audit() -> None:
                try:
                    omission_audit.main()
                except BaseException as error:
                    errors.append(error)

            with (
                patch.object(omission_audit, "RAW_MARKET_DATA_LOCK", lock),
                patch.object(omission_audit, "_parse_args", return_value=Namespace()),
                patch.object(omission_audit, "_audit_and_publish", side_effect=paused_audit),
            ):
                auditor = threading.Thread(target=audit)
                auditor.start()
                self.assertTrue(entered.wait(timeout=10))
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with exclusive_job(lock, job="synthetic raw writer"):
                        self.fail("raw writer entered during omission-audit publication")
                release.set()
                auditor.join(timeout=10)
            self.assertFalse(auditor.is_alive())
            self.assertEqual(errors, [])

    def test_canonical_static_producer_recertifies_existing_bytes_with_bound_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / static_producer.OUTPUT.name
            metadata_path = root / static_producer.METADATA.name
            token0 = "0x" + "11" * 20
            token1 = "0x" + "22" * 20
            pool = compute_pool_address(token0, token1, 500)
            row = {"id": pool, "feeTier": "500", "token0": {"id": token0}, "token1": {"id": token1}}
            with gzip.open(output, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            metadata_path.write_text(
                json.dumps(
                    {
                        "source": static_producer.VENUE,
                        "entity": "pools",
                        "historical_block": static_producer.SAMPLE_BLOCK,
                        "sample_day": static_producer.SAMPLE_DAY,
                        "provider_head_at_fetch": static_producer.SAMPLE_BLOCK,
                        "fetched_at_utc": "2026-07-01T00:00:00+00:00",
                        "fields": static_producer.FIELDS,
                        "validation": GRAPH_STATIC_VALIDATION,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(static_producer, "OUTPUT", output),
                patch.object(static_producer, "METADATA", metadata_path),
            ):
                summary = static_producer._recertify_existing({pool}, {pool})
            certified = json.loads(metadata_path.read_text(encoding="utf-8"))
            output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
            admitted_pools, _binding = graph_pool_snapshot(
                output,
                metadata_path,
                certified_upper_block=static_producer.SAMPLE_BLOCK,
            )
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(admitted_pools, {pool})
        self.assertEqual(certified["container_sha256"], output_sha256)
        self.assertEqual(certified["query_contract"], static_producer.query_contract())
        self.assertIn("recertified_at_utc", certified)

    def test_installed_inventory_relation_uses_exact_bound_ordered_perimeter(self) -> None:
        from ddvc.quoter import canonical_json_sha256

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for index in range(2):
                path = root / f"blocks_{index:08d}_{index:08d}.parquet"
                pd.DataFrame([{"block_number": index}]).to_parquet(path, index=False)
                paths.append(path)
            binding = {
                "chunk_count": 2,
                "listed_raw_paths_sha256": canonical_json_sha256([path.name for path in paths]),
            }
            con = duckdb.connect()
            registered = register_installed_inventory_events(con, paths, binding)
            self.assertEqual(registered, tuple(paths))
            self.assertEqual(
                con.execute("SELECT block_number FROM installed_inventory_events ORDER BY block_number").fetchall(),
                [(0,), (1,)],
            )
            with self.assertRaisesRegex(ValueError, "perimeter disagrees"):
                register_installed_inventory_events(con, paths[:1], binding)
            con.close()

    def test_audit_uses_only_certified_current_generation_apis(self) -> None:
        script = Path("scripts/audit_v3_graph_omission_materiality.py").read_text(encoding="utf-8")
        library = Path("src/ddvc/v3_graph_materiality.py").read_text(encoding="utf-8")
        self.assertIn("load_certified_inventory_generation(", script)
        self.assertIn("load_certified_frozen_upper(", script)
        self.assertIn("validate_token_decimals_registry(", script)
        self.assertIn("TOKEN_PRICE_DAILY_PANEL.name", script)
        self.assertIn("select_transaction_frontier_audit_days(list(route_release.days))", script)
        self.assertIn("load_day_calendar()", script)
        self.assertIn("recertified_rows", script)
        self.assertNotIn('event_coverage = {"status": "not_requested"}', script)
        self.assertLess(
            script.index('if not claim_materiality["clears_paper_estimands"]'),
            script.index("write_json(args.output, result)"),
        )
        self.assertNotIn("blocks_*.parquet", script)
        self.assertNotIn("v2_token_decimals.parquet", script)
        self.assertNotIn("v2_token_price_daily.parquet", script)
        self.assertNotIn("def graph_pool_ids", library)

    def test_daily_bound_requires_certified_paths_and_labels_static_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "pool": {"id": "0xpresent"},
                            "volumeUSD": "100",
                            "tvlUSD": "50",
                        }
                    )
                    + "\n"
                )
                handle.write(
                    json.dumps(
                        {
                            "pool": {"id": "0xmissing"},
                            "volumeUSD": "10",
                            "tvlUSD": "5",
                        }
                    )
                    + "\n"
                )
            con = duckdb.connect()
            result = graph_daily_provider_bound(
                con,
                certified_paths={"20210101": path},
                days=["2021-01-01"],
                graph_pools={"0xpresent"},
            )
            with self.assertRaisesRegex(ValueError, "lacks 1 certified days"):
                graph_daily_provider_bound(
                    con,
                    certified_paths={},
                    days=["2021-01-01"],
                    graph_pools=set(),
                )
            con.close()
        self.assertEqual(result["pool_days"], 2)
        self.assertEqual(result["missing_static_pool_days"], 1)
        self.assertAlmostEqual(result["missing_static_volume_share"], 1 / 11)

    def test_static_snapshot_identity_is_bound_during_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "uniswap_v3_pool_statics_20250101.jsonl.gz"
            metadata_path = Path(directory) / "uniswap_v3_pool_statics_20250101.meta.json"
            token0 = "0x" + "11" * 20
            token1 = "0x" + "22" * 20
            token2 = "0x" + "33" * 20
            rows = [
                {"id": compute_pool_address(token0, token1, 500), "feeTier": "500", "token0": {"id": token0}, "token1": {"id": token1}},
                {"id": compute_pool_address(token0, token2, 3000), "feeTier": "3000", "token0": {"id": token0}, "token1": {"id": token2}},
            ]
            payload = b"".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                for row in rows
            )
            with path.open("wb") as raw_handle:
                with gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as handle:
                    handle.write(payload)
            metadata_path.write_text(
                json.dumps(
                    {
                        "source": "uniswap_v3",
                        "entity": "pools",
                        "sample_day": "20250101",
                        "historical_block": 10,
                        "rows": 2,
                        "sample_pools_needing_identity": 2,
                        "sample_identity_gaps_resolved": 2,
                        "container_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "logical_content_sha256": hashlib.sha256(payload).hexdigest(),
                        "fields": GRAPH_STATIC_FIELDS,
                        "validation": GRAPH_STATIC_VALIDATION,
                        "query_contract": {**UNISWAP_V3_STATIC_QUERY_CONTRACT, "historical_block": 10},
                    }
                ),
                encoding="utf-8",
            )
            pools, binding = graph_pool_snapshot(
                path,
                metadata_path,
                certified_upper_block=10,
            )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["historical_block"] = 11
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "certified factory perimeter"):
                graph_pool_snapshot(path, metadata_path, certified_upper_block=10)
        self.assertEqual(pools, {row["id"] for row in rows})
        self.assertEqual(binding["rows"], 2)
        self.assertEqual(binding["distinct_pool_ids"], 2)
        self.assertEqual(
            binding["logical_content_sha256"],
            hashlib.sha256(payload).hexdigest(),
        )
        self.assertEqual(binding["certified_factory_upper_block"], 10)

    def test_route_exposure_is_an_exact_venue_opportunity_bound(self) -> None:
        lusd = "0x5f98805a4e8be255a32880fdec7f6728c6568ba0"
        weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
        other = "0x" + "99" * 20
        routes = pd.DataFrame(
            [
                {"src": lusd, "tgt": other, "realised_hop1_source": "uniswap_v3", "realised_hop2_source": "uniswap_v2"},
                {"src": lusd, "tgt": weth, "realised_hop1_source": "uniswap_v3", "realised_hop2_source": "uniswap_v3"},
                {"src": other, "tgt": other, "realised_hop1_source": "uniswap_v2", "realised_hop2_source": "uniswap_v3"},
                {"src": weth, "tgt": other, "realised_hop1_source": "curve", "realised_hop2_source": "uniswap_v3"},
            ]
        )
        class RouteRelease:
            @staticmethod
            def read_day(day: str) -> pd.DataFrame:
                self.assertEqual(day, "20210101")
                return pd.DataFrame()

            @staticmethod
            def assert_current() -> None:
                return None

        with patch("ddvc.v3_graph_materiality.extract_linear_realised_routes", return_value=routes):
            result = route_opportunity_exposure(
                RouteRelease(),
                pool="0xpool",
                token0=lusd,
                token1=weth,
                first_exposure_day="20210101",
                audit_days=["20201231", "20210101"],
            )
        self.assertEqual(result["audit_dates"], 1)
        self.assertEqual(result["exact_venue_two_leg_routes"], 3)
        self.assertEqual(result["pool_leg_opportunity_routes"], 2)
        self.assertEqual(result["direct_pool_pair_routes"], 1)

    def test_all_pool_perturbation_bounds_vehicle_share_value_and_route_cost(self) -> None:
        endpoint = "0x" + "99" * 20
        other = "0x" + "88" * 20
        weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
        routes = pd.DataFrame(
            [
                {"src": endpoint, "vehicle": weth, "tgt": other, "realised_hop1_source": "uniswap_v3", "realised_hop2_source": "uniswap_v2", "input_usd": 100.0, "output_usd": 99.0},
                {"src": other, "vehicle": weth, "tgt": "0x" + "77" * 20, "realised_hop1_source": "uniswap_v2", "realised_hop2_source": "uniswap_v2", "input_usd": 300.0, "output_usd": 297.0},
            ]
        )

        class RouteRelease:
            current_checks = 0

            @staticmethod
            def read_day(day: str) -> pd.DataFrame:
                self.assertEqual(day, "20210101")
                return pd.DataFrame()

            @classmethod
            def assert_current(cls) -> None:
                cls.current_checks += 1

        with patch("ddvc.v3_graph_materiality.extract_linear_realised_routes", return_value=routes):
            result = route_estimand_perturbation_bounds(
                RouteRelease(),
                pool_perimeter=[{"pool": "0xpool", "token0": endpoint, "token1": weth, "first_exposure_day": "20210101"}],
                audit_days=["20210101"],
            )
        self.assertEqual(result["defective_state_pools"], 1)
        self.assertAlmostEqual(result["vehicle_count_share_abs_change_upper_bound"], 0.5)
        self.assertAlmostEqual(result["vehicle_value_share_abs_change_upper_bound"], 0.25)
        self.assertIsNone(result["value_weighted_route_cost_bps_reduction_upper_bound"])
        self.assertEqual(result["route_cost_bound_status"], "requires_corrected_direct_and_candidate_quotes")
        self.assertEqual(RouteRelease.current_checks, 1)

    def test_monthly_structural_coverage_and_pre_provider_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_root = root / "raw" / "thegraph" / "uniswap_v3"
            event_root.mkdir(parents=True)
            pool = "0xpool"
            mint_only_pool = "0xmint-only"
            provider = {
                "swaps": [provider_row(pool, "0xswap", 10, 3, "swap-1")],
                "mints": [provider_row(pool, "0xmint", 9, 99, "mint-1")],
                "burns": [
                    provider_row(pool, "0xburn", 12, 8, "burn-1"),
                    provider_row(pool, "0xburn", 12, 8, "burn-1"),
                ],
            }
            for stream, rows in provider.items():
                path = event_root / f"uniswap_v3_{stream}_20210101.jsonl.gz"
                with gzip.open(path, "wt", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")
            exact = pd.DataFrame(
                [
                    {
                        "pool": pool,
                        "topic": EVENT_TOPICS["mint"],
                        "block_number": 9,
                        "transaction_hash": "0xmint",
                        "log_index": 5,
                    },
                    {
                        "pool": pool,
                        "topic": EVENT_TOPICS["swap"],
                        "block_number": 10,
                        "transaction_hash": "0xswap",
                        "log_index": 3,
                    },
                    {
                        "pool": pool,
                        "topic": EVENT_TOPICS["swap"],
                        "block_number": 10,
                        "transaction_hash": "0xswap",
                        "log_index": 4,
                    },
                    {
                        "pool": pool,
                        "topic": EVENT_TOPICS["burn"],
                        "block_number": 12,
                        "transaction_hash": "0xburn",
                        "log_index": 8,
                    },
                    {
                        "pool": pool,
                        "topic": EVENT_TOPICS["burn"],
                        "block_number": 12,
                        "transaction_hash": "0xburn",
                        "log_index": 9,
                    },
                    *[
                        {
                            "pool": mint_only_pool,
                            "topic": EVENT_TOPICS["mint"],
                            "block_number": 11,
                            "transaction_hash": f"0xmint-only-{index}",
                            "log_index": index,
                        }
                        for index in range(3)
                    ],
                ]
            )
            registry = pd.DataFrame(
                [
                    {
                        "pool": pool,
                        "graph_present": True,
                        "vehicle_pair": True,
                        "stable_pair": False,
                    },
                    {
                        "pool": mint_only_pool,
                        "graph_present": True,
                        "vehicle_pair": False,
                        "stable_pair": False,
                    },
                ]
            )
            calendar = pd.DataFrame(
                [{"day": "20210101", "start_block": 1, "day_end_block": 20}]
            )
            topics = pd.DataFrame(
                [{"topic": topic, "kind": kind} for kind, topic in EVENT_TOPICS.items()]
            )
            con = duckdb.connect()
            con.register("exact_source", exact)
            con.execute("CREATE TEMP VIEW exact_events AS SELECT * FROM exact_source")
            con.register("topics", topics)
            result = graph_event_coverage_materiality(
                con,
                provider_paths={
                    stream: {
                        "20210101": event_root
                        / f"uniswap_v3_{stream}_20210101.jsonl.gz"
                    }
                    for stream in provider
                },
                registry=registry,
                calendar=calendar,
                audit_days=["20210101"],
            )
            con.close()
        self.assertEqual(result["by_kind"]["swap"]["exact_rows"], 2)
        self.assertEqual(result["by_kind"]["swap"]["structurally_matched_rows"], 1)
        self.assertEqual(result["by_kind"]["swap"]["exact_only_rows"], 1)
        self.assertEqual(result["by_kind"]["mint"]["exact_log_matches"], 0)
        self.assertEqual(result["by_kind"]["burn"]["duplicate_provider_entity_rows"], 1)
        self.assertEqual(result["by_kind"]["burn"]["exact_only_rows"], 1)
        state_defects = {
            row["pool"]: row
            for row in result["exact_only_state_pool_perimeter"]
        }
        self.assertEqual(state_defects[mint_only_pool]["exact_only_swap_rows"], 0)
        self.assertEqual(state_defects[mint_only_pool]["exact_only_mint_rows"], 3)
        self.assertEqual(state_defects[mint_only_pool]["exact_only_liquidity_rows"], 3)
        self.assertEqual(state_defects[mint_only_pool]["first_exposure_day"], "20210101")
        self.assertEqual(result["liquidity_event_defect_pools"], 2)
        self.assertFalse(event_coverage_clears_state_estimands(result))
        with self.assertRaisesRegex(ValueError, "lacks state-changing defect"):
            event_coverage_clears_state_estimands({})
        top = result["top_exact_only_swap_pools"][0]
        self.assertEqual(top["pool"], pool)
        self.assertEqual(top["first_exact_swap_day"], "20210101")
        self.assertEqual(top["last_exact_swap_day"], "20210101")
        self.assertEqual(top["exact_swap_days"], 1)
        self.assertEqual(top["exact_swaps"], 2)
        self.assertEqual(top["audit_dates_with_exact_swaps"], 1)
        self.assertEqual(top["exact_swaps_on_audit_dates"], 2)
        cells = result["pre_first_provider_swap"]["cells"]
        mint_cell = next(row for row in cells if row["kind"] == "mint")
        swap_cell = next(row for row in cells if row["kind"] == "swap")
        self.assertEqual(mint_cell["events_before_first_provider_swap"], 1)
        self.assertEqual(swap_cell["events_before_first_provider_swap"], 0)
        self.assertEqual(swap_cell["events_on_first_provider_block"], 2)

    def test_omitted_static_pool_enters_perimeter_at_mint_without_any_swap(self) -> None:
        pool = "0xminted-but-never-swapped"
        registry = pd.DataFrame(
            [
                {
                    "pool": pool,
                    "token0": "0x" + "11" * 20,
                    "token1": "0x" + "22" * 20,
                    "graph_present": False,
                }
            ]
        )
        exact = pd.DataFrame(
            [
                {
                    "pool": pool,
                    "topic": EVENT_TOPICS["mint"],
                    "block_number": 7,
                }
            ]
        )
        topics = pd.DataFrame(
            [{"topic": topic, "kind": kind} for kind, topic in EVENT_TOPICS.items()]
        )
        calendar = pd.DataFrame(
            [
                {"day": "20210101", "day_end_block": 5},
                {"day": "20210102", "day_end_block": 10},
            ]
        )
        con = duckdb.connect()
        con.register("exact_events", exact)
        con.register("topics", topics)
        result = omitted_static_state_pool_perimeter(
            con,
            registry=registry,
            calendar=calendar,
        )
        con.close()
        self.assertEqual(result["pool"].tolist(), [pool])
        self.assertEqual(result["first_exposure_day"].tolist(), ["20210102"])


if __name__ == "__main__":
    unittest.main()

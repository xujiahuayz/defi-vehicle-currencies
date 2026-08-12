from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from eth_abi import encode as abi_encode
import pandas as pd

from ddvc.pricing.tick_replay import TickReplayEvent
from ddvc.pricing.v2_replay import V2SwapEvent
from ddvc.realised import LINEAR_ROUTE_COLUMNS
from ddvc.transaction_targets import (
    ChainSwapEvent,
    ProviderSwapEvent,
    TargetRelease,
    TargetEvidenceError,
    build_provider_target_ledger,
    calendar_sha256,
    decode_v2_chain_swap,
    decode_v3_chain_swap,
    decode_v4_chain_swap,
    one_sided_zero_failure_upper_bound,
    provider_event_from_tick,
    provider_event_from_v2,
    publish_target_release,
    read_target_day,
    resolve_target_release,
    target_generation_root,
    validate_leg_provider_match,
    validate_provider_chain_match,
    validation_contract,
    write_target_day,
)
from ddvc.v2_event_completeness import V2_EVENT_TOPICS
from ddvc.v3_inventory import EVENT_TOPICS as V3_EVENT_TOPICS
from ddvc.v4_contract import UNISWAP_V4_POOL_MANAGER_ADDRESS, UNISWAP_V4_SWAP_TOPIC
from scripts.build_transaction_target_release import exclude_post_support_v4_routes, load_provider_day


A = "0x000000000000000000000000000000000000000a"
K = "0x000000000000000000000000000000000000000b"
B = "0x000000000000000000000000000000000000000c"
POOL1 = "0x0000000000000000000000000000000000000011"
POOL2 = "0x0000000000000000000000000000000000000012"
TX = "0x" + "ab" * 32
BLOCK_HASH = "0x" + "cd" * 32
GENERATION = "1" * 64
DAILY_GENERATION = "2" * 64


def route_leg(
    log_index: int,
    token_in: str,
    token_out: str,
    tin_role: str,
    tout_role: str,
    *,
    source: str,
    amount_in: int,
    amount_out: int,
    amount_usd: float,
) -> dict[str, object]:
    return {
        "tx_hash": TX,
        "component_id": 0,
        "source": source,
        "token_in": token_in,
        "token_out": token_out,
        "token_in_sym": token_in,
        "token_out_sym": token_out,
        "amount_in": amount_in,
        "amount_out": amount_out,
        "amount_usd": amount_usd,
        "log_index": log_index,
        "route_class": "coherent",
        "tin_role": tin_role,
        "tout_role": tout_role,
        "timestamp_utc": 1_700_000_000,
    }


def provider(
    venue: str,
    log_index: int,
    pool: str,
    token0: str,
    token1: str,
    amount0_raw: int,
    amount1_raw: int,
    *,
    supported: bool = True,
    reason: str | None = None,
) -> ProviderSwapEvent:
    return ProviderSwapEvent(
        venue,
        TX,
        100,
        log_index,
        1_700_000_000,
        pool,
        token0,
        token1,
        0,
        0,
        amount0_raw,
        amount1_raw,
        supported,
        reason,
    )


def chain(event: ProviderSwapEvent) -> ChainSwapEvent:
    return ChainSwapEvent(
        event.venue,
        event.tx_hash,
        event.block_number,
        event.log_index,
        event.pool,
        event.amount0_raw,
        event.amount1_raw,
        event.timestamp,
        BLOCK_HASH,
    )


def raw_log(
    *,
    address: str,
    topic: str,
    data: bytes,
    log_index: int = 7,
    topics: list[str] | None = None,
) -> dict[str, object]:
    return {
        "address": address,
        "block_number": 100,
        "block_hash": BLOCK_HASH,
        "transaction_hash": TX,
        "transaction_index": 1,
        "log_index": log_index,
        "topics": topics or [topic],
        "data": "0x" + data.hex(),
        "removed": False,
    }


class TransactionTargetTests(unittest.TestCase):
    def test_post_support_v4_routes_are_explicitly_excluded_and_certified(self) -> None:
        legs = pd.DataFrame([
            route_leg(7, A, K, "source", "intermediate", source="uniswap_v4", amount_in=100, amount_out=90, amount_usd=100.0),
            route_leg(8, K, B, "intermediate", "sink", source="uniswap_v3", amount_in=90, amount_out=80, amount_usd=90.0),
        ])
        filtered, support = exclude_post_support_v4_routes("20250101", legs, False)
        self.assertTrue(filtered.empty)
        self.assertEqual((support["v4_scientific_support_status"], support["post_support_v4_routes_excluded"]), ("excluded_post_prefix", 1))
        self.assertEqual(len(str(support["post_support_v4_route_ids_sha256"])), 64)
        admitted, admitted_support = exclude_post_support_v4_routes("20250101", legs, True)
        self.assertEqual(len(admitted), 2)
        self.assertEqual(admitted_support["post_support_v4_routes_excluded"], 0)
        with self.assertRaisesRegex(TargetEvidenceError, "without a certified scientific-support marker"):
            exclude_post_support_v4_routes("20250101", legs, None)

    def test_post_support_provider_day_never_loads_absent_v4_state(self) -> None:
        legs = pd.DataFrame([
            route_leg(7, A, K, "source", "intermediate", source="uniswap_v4", amount_in=100, amount_out=90, amount_usd=100.0),
            route_leg(8, K, B, "intermediate", "sink", source="uniswap_v3", amount_in=90, amount_out=80, amount_usd=90.0),
        ])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            support_paths = tuple(root / name for name in ("state.jsonl.gz", "state.meta.json", "certificate.json"))
            for path in support_paths:
                path.write_text("support", encoding="utf-8")
            with patch("scripts.build_transaction_target_release.pd.read_parquet", return_value=legs), patch("scripts.build_transaction_target_release.v4_state_day_inputs", return_value=support_paths), patch("scripts.build_transaction_target_release.validate_v4_state_day", return_value=support_paths), patch("scripts.build_transaction_target_release.tick_scientific_support", return_value=False), patch("scripts.build_transaction_target_release.state_partition_inputs", return_value=[]), patch("scripts.build_transaction_target_release.load_v2_replay_day", return_value=SimpleNamespace(swaps_by_identity={})), patch("scripts.build_transaction_target_release.load_tick_day_events", return_value=[]) as load_tick:
                filtered, v2_events, tick_events, inputs, support = load_provider_day("20250101", set())
        self.assertTrue(filtered.empty)
        self.assertEqual((v2_events, tick_events), ({}, {}))
        self.assertEqual(set(inputs), set(support_paths))
        self.assertEqual(support["post_support_v4_routes_excluded"], 1)
        self.assertEqual(load_tick.call_args.kwargs["venues"], ("uniswap_v3",))

    def test_exact_frontier_still_rejects_a_missing_certified_event(self) -> None:
        legs = pd.DataFrame([
            route_leg(7, A, K, "source", "intermediate", source="uniswap_v2", amount_in=100, amount_out=90, amount_usd=100.0),
            route_leg(8, K, B, "intermediate", "sink", source="uniswap_v2", amount_in=90, amount_out=80, amount_usd=90.0),
        ])
        support_paths = (Path(__file__), Path(__file__), Path(__file__))
        with patch("scripts.build_transaction_target_release.pd.read_parquet", return_value=legs), patch("scripts.build_transaction_target_release.tick_scientific_support", return_value=False), patch("scripts.build_transaction_target_release.v4_state_day_inputs", return_value=support_paths), patch("scripts.build_transaction_target_release.validate_v4_state_day", return_value=support_paths), patch("scripts.build_transaction_target_release.state_partition_inputs", return_value=[]), patch("scripts.build_transaction_target_release.load_v2_replay_day", return_value=SimpleNamespace(swaps_by_identity={})), patch("scripts.build_transaction_target_release.load_tick_day_events", return_value=[]):
            with self.assertRaisesRegex(TargetEvidenceError, "canonical V2 state lacks target swap identity"):
                load_provider_day("20250101", set())

    def test_v4_contract_identity_has_one_canonical_owner(self) -> None:
        self.assertEqual(len(UNISWAP_V4_POOL_MANAGER_ADDRESS), 42)
        self.assertEqual(len(UNISWAP_V4_SWAP_TOPIC), 66)

    def test_validation_calendar_counts_and_hashes_are_observed(self) -> None:
        audit = ["20250101", "20250103"]
        full = ["20250101", "20250102", "20250103"]
        contract = validation_contract(verified_legs=1_000, evidence_failures=0, audit_calendar=audit, full_calendar=full)
        self.assertEqual(contract["validation_dates"], 2)
        self.assertEqual(contract["full_daily_dates"], 3)
        self.assertEqual(contract["validation_calendar_sha256"], calendar_sha256(audit))
        self.assertEqual(contract["full_daily_calendar_sha256"], calendar_sha256(full))
        self.assertAlmostEqual(float(contract["day_coverage_share"]), 2 / 3)
        self.assertAlmostEqual(float(contract["per_leg_mismatch_upper_bound"]), 1 - 0.05 ** (1 / 1_000))
        self.assertFalse(contract["full_history_chain_log_anchored"])
        self.assertIn("exchangeability", str(contract["exchangeability_caveat"]))
        with self.assertRaisesRegex(ValueError, "subset"):
            validation_contract(verified_legs=1, evidence_failures=0, audit_calendar=["20240101"], full_calendar=full)

    def test_zero_failure_bound_rejects_empty_trial_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive trials"):
            one_sided_zero_failure_upper_bound(0)

    def test_provider_chain_match_includes_independent_block_timestamp(self) -> None:
        observed = provider("uniswap_v2", 7, POOL1, A, K, 100, -90)
        validate_provider_chain_match(observed, chain(observed))
        stale = ChainSwapEvent("uniswap_v2", TX, 100, 7, POOL1, 100, -90, observed.timestamp + 1, BLOCK_HASH)
        with self.assertRaisesRegex(TargetEvidenceError, "differs"):
            validate_provider_chain_match(observed, stale)

    def test_chain_decoders_require_certified_block_timestamp(self) -> None:
        v2 = raw_log(address=POOL1, topic=V2_EVENT_TOPICS["swap"], data=abi_encode(["uint256", "uint256", "uint256", "uint256"], [100, 0, 0, 90]))
        decoded_v2 = decode_v2_chain_swap("uniswap_v2", v2, block_timestamps={100: 1_700_000_000})
        self.assertEqual((decoded_v2.amount0_raw, decoded_v2.amount1_raw, decoded_v2.block_timestamp), (100, -90, 1_700_000_000))
        with self.assertRaisesRegex(TargetEvidenceError, "certified timestamp"):
            decode_v2_chain_swap("uniswap_v2", v2, block_timestamps={})

        v3 = raw_log(address=POOL1, topic=V3_EVENT_TOPICS["swap"], data=abi_encode(["int256", "int256", "uint160", "uint128", "int24"], [100, -90, 2**96, 10, 0]), topics=[V3_EVENT_TOPICS["swap"], "0x" + "00" * 32, "0x" + "00" * 32])
        decoded_v3 = decode_v3_chain_swap(v3, block_timestamps={100: 1_700_000_000})
        self.assertEqual((decoded_v3.amount0_raw, decoded_v3.amount1_raw), (100, -90))

        pool_id = "0x" + "12" * 32
        v4 = raw_log(address=UNISWAP_V4_POOL_MANAGER_ADDRESS, topic=UNISWAP_V4_SWAP_TOPIC, data=abi_encode(["int128", "int128", "uint160", "uint128", "int24", "uint24"], [100, -90, 2**96, 10, 0, 500]), topics=[UNISWAP_V4_SWAP_TOPIC, pool_id, "0x" + "00" * 32])
        decoded_v4 = decode_v4_chain_swap(v4, block_timestamps={100: 1_700_000_000})
        self.assertEqual((decoded_v4.pool, decoded_v4.amount0_raw, decoded_v4.amount1_raw), (pool_id, 100, -90))
        with self.assertRaisesRegex(ValueError, "canonical V4"):
            decode_v4_chain_swap({**v4, "address": POOL1}, block_timestamps={100: 1_700_000_000})

    def test_provider_constructors_preserve_exact_base_units(self) -> None:
        row = {
            "token0_raw": A,
            "token1_raw": K,
            "decimals0": 2,
            "decimals1": 1,
            "amount0_delta": "1.25",
            "amount1_delta": "-9.0",
        }
        event = V2SwapEvent("uniswap_v2", POOL1, TX, 1_700_000_000, 1_699_999_200, (100, 7), 7, row)
        observed = provider_event_from_v2(event)
        self.assertEqual((observed.amount0_raw, observed.amount1_raw), (125, -90))

    def test_v4_admission_uses_canonical_static_and_quarantine_contract(self) -> None:
        def tick(*, fee: int = 500, hooks: str = "0x0000000000000000000000000000000000000000") -> TickReplayEvent:
            row = {
                "transaction": {"id": TX, "blockNumber": 100, "timestamp": 1_700_000_000},
                "timestamp": 1_700_000_000,
                "logIndex": 7,
                "pool": {
                    "id": "0x" + "12" * 32,
                    "token0": {"id": A, "decimals": 0},
                    "token1": {"id": K, "decimals": 0},
                    "feeTier": fee,
                    "tickSpacing": 10,
                    "hooks": hooks,
                },
                "amount0": "100",
                "amount1": "-90",
            }
            return TickReplayEvent((100, 7), "uniswap_v4", "swap", row)

        with self.assertRaisesRegex(ValueError, "quarantine"):
            provider_event_from_tick(tick())
        vanilla = provider_event_from_tick(tick(), v4_quarantined_pools=set())
        self.assertTrue(vanilla.quote_supported)
        hooked = provider_event_from_tick(tick(hooks=POOL1), v4_quarantined_pools=set())
        self.assertFalse(hooked.quote_supported)
        self.assertEqual(hooked.quote_unsupported_reason, "v4_hooks")
        dynamic = provider_event_from_tick(tick(fee=1 << 23), v4_quarantined_pools=set())
        self.assertEqual(dynamic.quote_unsupported_reason, "v4_dynamic_fee")
        quarantined = provider_event_from_tick(tick(), v4_quarantined_pools={vanilla.pool})
        self.assertEqual(quarantined.quote_unsupported_reason, "v4_static_quarantine")

    def test_leg_matching_rejects_identity_direction_and_amount_drift(self) -> None:
        event = provider("uniswap_v2", 7, POOL1, A, K, 100, -90)
        good = type("Leg", (), {"tx_hash": TX, "source": "uniswap_v2", "log_index": 7, "token_in": A, "token_out": K, "amount_in": 100, "amount_out": 90})()
        validate_leg_provider_match(good, event)
        bad = SimpleNamespace(tx_hash=TX, source="uniswap_v2", log_index=7, token_in=A, token_out=K, amount_in=100, amount_out=89)
        with self.assertRaisesRegex(TargetEvidenceError, "amounts differ"):
            validate_leg_provider_match(bad, event)

    def test_target_ledger_maps_every_route_and_preserves_structural_rejection(self) -> None:
        legs = pd.DataFrame([
            route_leg(7, A, K, "source", "intermediate", source="uniswap_v2", amount_in=100, amount_out=90, amount_usd=100.0),
            route_leg(8, K, B, "intermediate", "sink", source="uniswap_v3", amount_in=90, amount_out=80, amount_usd=90.0),
        ])
        first = provider("uniswap_v2", 7, POOL1, A, K, 100, -90)
        second = provider("uniswap_v3", 8, POOL2, K, B, 90, -80)
        provider_maps = {
            (first.venue, TX, 7): first,
            (second.venue, TX, 8): second,
        }
        chains = {key: chain(value) for key, value in provider_maps.items()}
        frame, support = build_provider_target_ledger("20250101", legs, v2_events={(first.venue, TX, 7): first}, tick_events={(second.venue, TX, 8): second}, chain_events=chains)
        self.assertEqual(len(frame), 1)
        self.assertTrue(bool(frame.iloc[0]["target_admitted"]))
        self.assertEqual(support["verified_chain_log_legs"], 2)
        with self.assertRaisesRegex(TargetEvidenceError, "chain evidence lacks"):
            build_provider_target_ledger("20250101", legs, v2_events={(first.venue, TX, 7): first}, tick_events={(second.venue, TX, 8): second}, chain_events={(first.venue, TX, 7): chain(first)})

        unsupported = provider("uniswap_v3", 8, POOL2, K, B, 90, -80, supported=False, reason="v4_static_quarantine")
        rejected, rejected_support = build_provider_target_ledger("20250101", legs.assign(source=["uniswap_v2", "uniswap_v3"]), v2_events={(first.venue, TX, 7): first}, tick_events={(unsupported.venue, TX, 8): unsupported}, chain_events={(first.venue, TX, 7): chain(first)})
        self.assertFalse(bool(rejected.iloc[0]["target_admitted"]))
        self.assertEqual(rejected_support["verified_chain_log_legs"], 1)

    def test_zero_route_day_preserves_typed_empty_ledger(self) -> None:
        frame, support = build_provider_target_ledger("20250101", pd.DataFrame(columns=LINEAR_ROUTE_COLUMNS), v2_events={}, tick_events={}, chain_events={})
        self.assertTrue(frame.empty)
        self.assertIn("route_id", frame.columns)
        self.assertEqual(support["provider_mapped_routes"], 0)
        self.assertEqual(support["evidence_failures"], 0)

    def test_marker_last_release_rejects_mutated_shards_and_calendar_overclaim(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "target_release"
            directory = target_generation_root(GENERATION, root=root)
            frame = pd.DataFrame({"route_id": ["r1"], "target_admitted": [True]})
            support = {"day": "20250101", "provider_mapped_routes": 1, "verified_chain_log_legs": 2, "evidence_failures": 0}
            marker = write_target_day(directory, "20250101", frame, support, scope="audit", generation=GENERATION, lineage={})
            validation = validation_contract(verified_legs=2, evidence_failures=0, audit_calendar=["20250101"], full_calendar=["20250101", "20250102"])
            with patch("ddvc.provenance.ROOT", root), patch("ddvc.provenance.MANIFESTS", root / "provenance"):
                release = publish_target_release(directory, [marker], scope="audit", generation=GENERATION, validation=validation, full_calendar=["20250101", "20250102"], code_sources=["src/ddvc/transaction_targets.py"], inputs=[], root=root)
                reopened = resolve_target_release("audit", expected_days=["20250101"], root=root)
                reopened.assert_current()
                observed, _ = read_target_day(reopened, "20250101")
                self.assertEqual(observed["route_id"].tolist(), ["r1"])

                daily_directory = target_generation_root(DAILY_GENERATION, root=root)
                daily_support = {**support, "verified_chain_log_legs": 0, "evidence_scope": "provider_derived"}
                daily_marker = write_target_day(daily_directory, "20250101", frame, daily_support, scope="daily", generation=DAILY_GENERATION, lineage={})
                with self.assertRaisesRegex(TargetEvidenceError, "overclaims or misstates"):
                    publish_target_release(daily_directory, [daily_marker], scope="daily", generation=DAILY_GENERATION, validation={**validation, "full_history_chain_log_anchored": True, "full_daily_dates": 1, "full_daily_calendar_sha256": calendar_sha256(["20250101"])}, full_calendar=["20250101"], code_sources=["src/ddvc/transaction_targets.py"], inputs=[], root=root)

                shard = marker.parents[1] / json.loads(marker.read_text())["shard"]
                shard.write_bytes(b"mutated")
                with self.assertRaisesRegex(TargetEvidenceError, "mutated"):
                    read_target_day(release, "20250101")
                with self.assertRaises(TargetEvidenceError):
                    reopened.assert_current()

    def test_target_day_retry_proves_frame_support_and_lineage_identity(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "target"
            frame = pd.DataFrame({"route_id": ["r1"], "target_admitted": [True]})
            support = {"day": "20250101", "provider_mapped_routes": 1, "verified_chain_log_legs": 0, "evidence_failures": 0}
            write_target_day(directory, "20250101", frame, support, scope="daily", generation=GENERATION, lineage={})
            with self.assertRaisesRegex(TargetEvidenceError, "requested frame"):
                write_target_day(directory, "20250101", frame.assign(target_admitted=False), support, scope="daily", generation=GENERATION, lineage={})
            with self.assertRaisesRegex(TargetEvidenceError, "requested support"):
                write_target_day(directory, "20250101", frame, {**support, "new_field": 1}, scope="daily", generation=GENERATION, lineage={})
            lineage_source = Path(temporary) / "source.json"
            lineage_source.write_text("{}\n", encoding="utf-8")
            digest = hashlib.sha256(lineage_source.read_bytes()).hexdigest()
            with self.assertRaisesRegex(TargetEvidenceError, "requested lineage"):
                write_target_day(directory, "20250101", frame, support, scope="daily", generation=GENERATION, lineage={str(lineage_source): digest})

    def test_same_scope_concurrent_publishers_leave_one_complete_release(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "target_release"
            validation = validation_contract(verified_legs=2, evidence_failures=0, audit_calendar=["20250101"], full_calendar=["20250101"])
            generations = (GENERATION, DAILY_GENERATION)
            publications = []
            for index, generation in enumerate(generations, 1):
                directory = target_generation_root(generation, root=root)
                frame = pd.DataFrame({"route_id": [f"r{index}"], "target_admitted": [True]})
                support = {"day": "20250101", "provider_mapped_routes": 1, "verified_chain_log_legs": 2, "evidence_failures": 0}
                marker = write_target_day(directory, "20250101", frame, support, scope="audit", generation=generation, lineage={})
                publications.append((directory, marker, generation))
            barrier = Barrier(2)

            def publish(publication: tuple[Path, Path, str]) -> TargetRelease:
                directory, marker, generation = publication
                barrier.wait()
                return publish_target_release(directory, [marker], scope="audit", generation=generation, validation=validation, full_calendar=["20250101"], code_sources=["src/ddvc/transaction_targets.py"], inputs=[], root=root)

            with patch("ddvc.provenance.ROOT", root), patch("ddvc.provenance.MANIFESTS", root / "provenance"):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    completed = [future.result() for future in [executor.submit(publish, publication) for publication in publications]]
                selected = resolve_target_release("audit", expected_days=["20250101"], root=root)
            self.assertIn(selected.generation, generations)
            self.assertTrue(all(release.generation in generations for release in completed))
            observed, _support = read_target_day(selected, "20250101")
            self.assertEqual(len(observed), 1)


if __name__ == "__main__":
    unittest.main()

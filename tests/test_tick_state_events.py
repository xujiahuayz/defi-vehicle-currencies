from __future__ import annotations

from dataclasses import replace
from eth_abi import encode as abi_encode
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ddvc.ethereum_logs import fetch_exact_logs_with_capacity_bisection
from ddvc.quoter import RpcCapacityError, canonical_json_sha256
from ddvc.tick_state_events import (
    TickInitialization,
    V3_INITIALIZE_TOPIC,
    V4_INITIALIZE_TOPIC,
    certificate_identity_sha256,
    certify_materialization_support,
    certify_state_event_generation,
    certify_state_event_precedence,
    decode_initializations,
    decode_v3_initialize,
    decode_v4_initialize,
    daily_release_set_path,
    initialization_day_inputs,
    iter_v4_state_events,
    state_event_chunk_paths,
    load_state_event_chunk,
    state_event_generation,
    v4_pool_id,
    validate_initialization_day,
    validate_v4_state_day,
    write_daily_initializations,
    write_daily_v4_state_events,
    write_state_event_chunk,
)
from ddvc.v3_pool_registry import V3FactoryPool
from ddvc.v4_contract import (
    UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC,
    UNISWAP_V4_POOL_MANAGER_ADDRESS,
    UNISWAP_V4_SWAP_TOPIC,
    decode_v4_state_event_identity,
    validate_v4_provider_event_identity,
)
from scripts.fetch_tick_state_events import _v2_scoped_token_metadata, _v3_inputs
from day_cut_fixtures import certified_day_cuts


A = "0x" + "11" * 20
B = "0x" + "22" * 20
C = "0x" + "33" * 20
D = "0x" + "44" * 20
HOOK = "0x" + "33" * 20
TX = "0x" + "44" * 32
BLOCK_HASH = "0x" + "55" * 32


def raw(address: str, topics: list[str], data: bytes, *, block: int = 10, log_index: int = 2) -> dict[str, object]:
    return {
        "address": address,
        "block_number": block,
        "block_hash": BLOCK_HASH,
        "transaction_hash": TX,
        "transaction_index": 1,
        "log_index": log_index,
        "topics": topics,
        "data": "0x" + data.hex(),
        "removed": False,
    }


def topic_address(address: str) -> str:
    return "0x" + "0" * 24 + address[2:]


def certificate(venue: str) -> dict[str, object]:
    value = {"status": "pass", "generation": state_event_generation(venue), "venue": venue, "precedence_status": "pass"}
    value["certificate_identity_sha256"] = certificate_identity_sha256(value)
    return value


def frozen_upper(block: int = 20) -> dict[str, object]:
    endpoint = {"host": "injected", "endpoint_sha256": "0" * 64}
    response = {"jsonrpc": "2.0", "id": 1, "result": {"number": hex(block), "hash": "0x" + "9" * 64, "parentHash": "0x" + "8" * 64, "timestamp": hex(1_700_000_000)}}
    value = {
        "status": "complete", "schema_version": 1, "block_number": block,
        "block_hash": "0x" + "9" * 64, "parent_hash": "0x" + "8" * 64,
        "timestamp": 1_700_000_000,
        "rpc_request": {"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": [hex(block), False]},
        "rpc_response": response, "rpc_endpoint": endpoint,
        "rpc_attempts": [{"endpoint": endpoint, "attempt": 1, "classification": "success", "http_status": None, "rpc_code": None, "message": "success"}],
        "response_sha256": canonical_json_sha256(response),
    }
    value["header_identity_sha256"] = canonical_json_sha256({"block_number": block, "block_hash": value["block_hash"], "parent_hash": value["parent_hash"], "timestamp": value["timestamp"]})
    return value


def exact_evidence(records: dict[str, object] | list[dict[str, object]], frozen: dict[str, object]) -> list[dict[str, object]]:
    from ddvc.tick_state_events import VENUE_GENERATION_TOPICS
    rows = [records] if isinstance(records, dict) else records
    lower, upper = min(int(row["block_number"]) for row in rows), max(int(row["block_number"]) for row in rows)
    endpoint = {"host": "injected", "endpoint_sha256": "0" * 64}
    rpc_logs = [{
        "address": row["address"], "blockNumber": hex(int(row["block_number"])),
        "blockHash": row["block_hash"], "transactionHash": row["transaction_hash"],
        "transactionIndex": hex(int(row["transaction_index"])), "logIndex": hex(int(row["log_index"])),
        "topics": row["topics"], "data": row["data"], "removed": False,
    } for row in rows]
    header = dict(frozen["rpc_response"])
    header["id"] = 2
    log_request = {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [{"fromBlock": hex(lower), "toBlock": hex(upper), "topics": [list(VENUE_GENERATION_TOPICS["uniswap_v4"])], "address": UNISWAP_V4_POOL_MANAGER_ADDRESS}]}
    header_request = {"jsonrpc": "2.0", "id": 2, "method": "eth_getBlockByNumber", "params": [hex(int(frozen["block_number"])), False]}
    response = [{"jsonrpc": "2.0", "id": 1, "result": rpc_logs}, header]
    return [{
        "start_block": lower, "end_block": upper,
        "request": [log_request, header_request], "response": response, "endpoint": endpoint,
        "attempts": [{"endpoint": endpoint, "attempt": 1, "classification": "success", "http_status": None, "rpc_code": None, "message": "success"}],
        "response_sha256": canonical_json_sha256(response), "frozen_upper_request": header_request,
        "frozen_upper_response": header, "frozen_upper_response_sha256": canonical_json_sha256(header),
    }]


class TickStateEventTests(unittest.TestCase):
    def test_v4_preflight_stops_before_absent_certified_decimals_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("scripts.fetch_tick_state_events.V2_AUDITED_TOKEN_DECIMALS_REGISTRY", Path(directory) / "absent.parquet"):
            with self.assertRaisesRegex(FileNotFoundError, "certified V2-scoped token-decimals prerequisite is absent"):
                _v2_scoped_token_metadata()

    def test_v3_metadata_uses_exact_registry_not_provider_decimals(self) -> None:
        pool = "0x" + "66" * 20
        static = V3FactoryPool(pool, A, B, 500, 10, 9, BLOCK_HASH, TX, 1)
        with tempfile.TemporaryDirectory() as directory:
            provider_path = Path(directory) / "provider.jsonl.gz"
            with gzip.open(provider_path, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": pool, "token0": {"id": A, "symbol": "A", "decimals": "1"}, "token1": {"id": B, "symbol": "B", "decimals": "2"}}) + "\n")
            with patch("scripts.fetch_tick_state_events.load_registry", return_value=[static]), patch("scripts.fetch_tick_state_events._v2_scoped_token_metadata", return_value=({A: ("", 18), B: ("", 6)}, [Path("exact.parquet")])), patch("scripts.fetch_tick_state_events.v3_pool_static_path", return_value=provider_path):
                registry, metadata, _inputs = _v3_inputs()
        self.assertEqual(set(registry), {pool})
        self.assertEqual(metadata, {A: ("A", 18), B: ("B", 6)})

    def test_v3_factory_pool_missing_from_graph_remains_in_exact_registry(self) -> None:
        first_pool = "0x" + "66" * 20
        missing_pool = "0x" + "77" * 20
        statics = [
            V3FactoryPool(first_pool, A, B, 500, 10, 9, BLOCK_HASH, TX, 1),
            V3FactoryPool(missing_pool, C, D, 3000, 11, 10, BLOCK_HASH, TX, 2),
        ]
        with tempfile.TemporaryDirectory() as directory:
            provider_path = Path(directory) / "provider.jsonl.gz"
            with gzip.open(provider_path, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": first_pool, "token0": {"id": A, "symbol": "A", "decimals": "18"}, "token1": {"id": B, "symbol": "B", "decimals": "6"}}) + "\n")
            exact = {A: ("", 18), B: ("", 6), C: ("", 8), D: ("", 7)}
            with patch("scripts.fetch_tick_state_events.load_registry", return_value=statics), patch("scripts.fetch_tick_state_events._v2_scoped_token_metadata", return_value=(exact, [Path("exact.parquet")])), patch("scripts.fetch_tick_state_events.v3_pool_static_path", return_value=provider_path):
                registry, metadata, _inputs = _v3_inputs()
        self.assertEqual(set(registry), {first_pool, missing_pool})
        self.assertEqual(metadata[C], ("", 8))
        self.assertEqual(metadata[D], ("", 7))

    def test_v3_initialize_requires_factory_identity_and_precedes_state(self) -> None:
        pool = "0x" + "66" * 20
        static = V3FactoryPool(pool, A, B, 500, 10, 9, BLOCK_HASH, TX, 1)
        record = raw(pool, [V3_INITIALIZE_TOPIC], abi_encode(["uint160", "int24"], [2**96, 0]))
        decoded = decode_v3_initialize(record, {pool: static})
        self.assertEqual((decoded.pool, decoded.fee_pips, decoded.order), (pool, 500, (10, 2)))
        with self.assertRaisesRegex(ValueError, "outside the certified"):
            decode_v3_initialize(record, {})
        with self.assertRaisesRegex(ValueError, "does not follow"):
            decode_v3_initialize({**record, "block_number": 9, "log_index": 1}, {pool: static})

    def test_streaming_v3_certificate_rejects_duplicate_initialize(self) -> None:
        pool = "0x" + "66" * 20
        static = V3FactoryPool(pool, A, B, 500, 10, 9, BLOCK_HASH, TX, 1)
        first = raw(pool, [V3_INITIALIZE_TOPIC], abi_encode(["uint160", "int24"], [2**96, 0]), log_index=2)
        second = {**first, "log_index": 3}
        with patch("ddvc.tick_state_events.load_state_event_chunk", return_value=[first, second]):
            with self.assertRaisesRegex(ValueError, "duplicate V3 Initialize"):
                certify_state_event_generation("uniswap_v3", [(10, 10)], frozen_upper=frozen_upper(), raw_root=Path("unused"), v3_registry={pool: static})

    def test_v4_initialize_recomputes_pool_id_and_retains_hook_status(self) -> None:
        pool = v4_pool_id(A, B, 500, 10, HOOK)
        record = raw(
            UNISWAP_V4_POOL_MANAGER_ADDRESS,
            [V4_INITIALIZE_TOPIC, pool, topic_address(A), topic_address(B)],
            abi_encode(["uint24", "int24", "address", "uint160", "int24"], [500, 10, HOOK, 2**96, 0]),
        )
        decoded = decode_v4_initialize(record)
        self.assertFalse(decoded.quote_supported)
        self.assertEqual(decoded.quote_unsupported_reason, "hooks")
        with self.assertRaisesRegex(ValueError, "PoolId disagrees"):
            decode_v4_initialize({**record, "topics": [V4_INITIALIZE_TOPIC, "0x" + "77" * 32, topic_address(A), topic_address(B)]})

    def test_v4_native_dynamic_initialize_and_duplicate_identity_are_explicit(self) -> None:
        native = "0x" + "0" * 40
        dynamic_fee = 1 << 23
        pool = v4_pool_id(native, A, dynamic_fee, 10, native)
        record = raw(UNISWAP_V4_POOL_MANAGER_ADDRESS, [V4_INITIALIZE_TOPIC, pool, topic_address(native), topic_address(A)], abi_encode(["uint24", "int24", "address", "uint160", "int24"], [dynamic_fee, 10, native, 2**96, 0]))
        decoded = decode_v4_initialize(record)
        self.assertEqual((decoded.token0, decoded.quote_unsupported_reason), (native, "dynamic_fee"))
        with self.assertRaisesRegex(ValueError, "more than one Initialize"):
            decode_initializations("uniswap_v4", [record, {**record, "log_index": 3}])

    def test_precedence_certificate_rejects_missing_or_late_initialize(self) -> None:
        initialization = TickInitialization("uniswap_v4", "pool", A, B, 500, 10, "0x" + "0" * 40, 2**96, 0, 10, BLOCK_HASH, TX, 1, 2, True, None)
        base = certificate("uniswap_v4")
        passed = certify_state_event_precedence(base, [initialization], [{"pool": "pool", "block_number": 10, "log_index": 3, "kind": "swap"}], registry_pools=["pool", "never"])
        self.assertEqual(passed["registry_pools_zero_initialize"], 1)
        with self.assertRaisesRegex(ValueError, "missing"):
            certify_state_event_precedence(base, [], [{"pool": "pool", "block_number": 10, "log_index": 3, "kind": "swap"}])
        with self.assertRaisesRegex(ValueError, "nonpreceding"):
            certify_state_event_precedence(base, [replace(initialization, log_index=4)], [{"pool": "pool", "block_number": 10, "log_index": 3, "kind": "swap"}])

    def test_daily_release_is_deterministic_portable_and_keeps_unknown_metadata(self) -> None:
        initialization = TickInitialization("uniswap_v4", "pool", A, B, 500, 10, "0x" + "0" * 40, 2**96, 0, 10, BLOCK_HASH, TX, 1, 2, True, None)
        support = certify_materialization_support({**certificate("uniswap_v4"), "token_metadata_scope": "exact_anchor_v2_registry_plus_native_currency_only"}, [initialization], {A: ("A", 18)})
        self.assertEqual((support["protocol_static_quote_supported_pools"], support["metadata_supported_pools"], support["materialized_quote_supported_pools"]), (1, 0, 0))
        self.assertEqual((support["initialize_tokens_outside_metadata_scope"], support["initialize_pools_excluded_unknown_token_metadata"]), (1, 1))
        self.assertEqual((support["venue_initialization_tokens_outside_v2_audit_scope"], support["venue_initialization_pools_outside_v2_audit_scope"]), (1, 1))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thegraph"
            kwargs = dict(venue="uniswap_v4", rows=[initialization], day_cuts=certified_day_cuts({"20250101": (1, 20)}), token_metadata={A: ("A", 18)}, raw_root=root, generation_certificate=certificate("uniswap_v4"))
            first = write_daily_initializations(**kwargs)[0].read_bytes()
            second = write_daily_initializations(**kwargs)[0].read_bytes()
            self.assertEqual(first, second)
            data, marker, cert = validate_initialization_day(root, "uniswap_v4", "20250101")
            self.assertFalse(Path(json.loads(marker.read_text())["certificate_identity"]).is_absolute())
            with gzip.open(data, "rt") as handle:
                self.assertEqual(json.loads(handle.readline())["quoteUnsupportedReason"], "unknown_token_metadata")
            payload = json.loads(cert.read_text())
            payload["venue"] = "tampered"
            cert.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "stale or uncertified"):
                validate_initialization_day(root, "uniswap_v4", "20250101")

    def test_daily_release_binds_exact_cut_and_requires_complete_calendar_set(self) -> None:
        initialization = TickInitialization("uniswap_v4", "pool", A, B, 500, 10, "0x" + "0" * 40, 2**96, 0, 5, BLOCK_HASH, TX, 1, 1, True, None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thegraph"
            cuts = certified_day_cuts({"20250101": (1, 10), "20250102": (11, 20)})
            paths = write_daily_initializations("uniswap_v4", [initialization], day_cuts=cuts, token_metadata={A: ("A", 18), B: ("B", 6)}, raw_root=root, generation_certificate=certificate("uniswap_v4"))
            marker = json.loads(paths[0].with_suffix(".meta.json").read_text())
            self.assertEqual(marker["day_cut_sha256"], hashlib.sha256(json.dumps(cuts["20250101"], sort_keys=True, separators=(",", ":")).encode()).hexdigest())
            paths[1].with_suffix(".meta.json").unlink()
            with self.assertRaisesRegex(ValueError, "incomplete set"):
                validate_initialization_day(root, "uniswap_v4", "20250101")

    def test_daily_release_final_marker_is_absent_after_publication_failure(self) -> None:
        initialization = TickInitialization("uniswap_v4", "pool", A, B, 500, 10, "0x" + "0" * 40, 2**96, 0, 5, BLOCK_HASH, TX, 1, 1, True, None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thegraph"
            with patch("ddvc.tick_state_events._write_daily_release_set", side_effect=RuntimeError("injected release-set failure")), self.assertRaisesRegex(RuntimeError, "release-set failure"):
                write_daily_initializations("uniswap_v4", [initialization], day_cuts=certified_day_cuts({"20250101": (1, 20)}), token_metadata={A: ("A", 18), B: ("B", 6)}, raw_root=root, generation_certificate=certificate("uniswap_v4"))
            self.assertFalse(daily_release_set_path(root, "uniswap_v4", kind="initializations").exists())

    def test_v4_daily_materialization_consumes_ordered_stream_once(self) -> None:
        initialization = TickInitialization("uniswap_v4", "pool", A, B, 500, 10, "0x" + "0" * 40, 2**96, 0, 5, BLOCK_HASH, TX, 1, 1, True, None)
        events = [
            {"kind": "modify_liquidity", "pool": "pool", "block_number": 10, "block_hash": BLOCK_HASH, "transaction_hash": TX, "transaction_index": 0, "log_index": 1, "tick_lower": -10, "tick_upper": 10, "liquidity_delta": 7, "salt": "0x" + "0" * 64},
            {"kind": "swap", "pool": "pool", "block_number": 20, "block_hash": BLOCK_HASH, "transaction_hash": "0x" + "6" * 64, "transaction_index": 0, "log_index": 2, "amount0": 1, "amount1": -1, "sqrt_price_x96": 2**96, "liquidity": 7, "tick": 0, "fee": 500},
        ]
        visits = []
        def one_pass():
            for event in events:
                visits.append(event["block_number"])
                yield event
        release = certificate("uniswap_v4")
        release.update(exact_modify_liquidity_events=1, exact_swap_events=1)
        release["certificate_identity_sha256"] = certificate_identity_sha256(release)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thegraph"
            metadata = {A: ("A", 18), B: ("B", 6)}
            cuts = certified_day_cuts({"20250101": (1, 10), "20250102": (11, 20)})
            write_daily_initializations("uniswap_v4", [initialization], day_cuts=cuts, token_metadata=metadata, raw_root=root, generation_certificate=release)
            paths = write_daily_v4_state_events(one_pass(), [initialization], day_cuts=cuts, token_metadata=metadata, raw_root=root, generation_certificate=release)
            self.assertEqual([json.loads(path.with_suffix(".meta.json").read_text())["rows"] for path in paths], [1, 1])
        self.assertEqual(visits, [10, 20])

    def test_v4_modify_identity_covers_zero_log_index_and_signed_payload(self) -> None:
        pool = "0x" + "88" * 32
        record = raw(
            UNISWAP_V4_POOL_MANAGER_ADDRESS,
            [UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC, pool, topic_address(A)],
            abi_encode(["int24", "int24", "int256", "bytes32"], [-10, 10, -7, b"\0" * 32]),
            log_index=0,
        )
        exact = decode_v4_state_event_identity(record, "modify_liquidity")
        provider = {"transaction": {"id": TX, "blockNumber": 10}, "logIndex": 0, "pool": {"id": pool}, "tickLower": -10, "tickUpper": 10, "amount": -7}
        validate_v4_provider_event_identity(provider, exact)
        with self.assertRaisesRegex(ValueError, "state payload"):
            validate_v4_provider_event_identity({**provider, "amount": 7}, exact)
        with self.assertRaisesRegex(ValueError, "mapping pool"):
            validate_v4_provider_event_identity({**provider, "pool": pool}, exact)

    def test_chunk_evidence_reopens_and_tamper_fails_closed(self) -> None:
        pool = v4_pool_id(A, B, 500, 10, "0x" + "0" * 40)
        record = raw(UNISWAP_V4_POOL_MANAGER_ADDRESS, [V4_INITIALIZE_TOPIC, pool, topic_address(A), topic_address(B)], abi_encode(["uint24", "int24", "address", "uint160", "int24"], [500, 10, "0x" + "0" * 40, 2**96, 0]))
        frozen = frozen_upper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thegraph"
            write_state_event_chunk("uniswap_v4", 10, 10, [record], exact_evidence(record, frozen), frozen_upper=frozen, root=root)
            self.assertEqual(len(load_state_event_chunk("uniswap_v4", 10, 10, frozen_upper=frozen, root=root)), 1)
            _raw, _evidence, marker = state_event_chunk_paths("uniswap_v4", 10, 10, root=root)
            payload = json.loads(marker.read_text())
            payload["event_topics"] = [V4_INITIALIZE_TOPIC]
            marker.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "marker"):
                load_state_event_chunk("uniswap_v4", 10, 10, frozen_upper=frozen, root=root)

    def test_capacity_bisection_preserves_exact_partition(self) -> None:
        def fetch(**kwargs):
            if kwargs["start_block"] != kwargs["end_block"]:
                raise RpcCapacityError("wide", attempts=[])
            return [], {"request": [], "response": [], "endpoint": {}, "attempts": [], "response_sha256": "x", "frozen_upper_request": {}, "frozen_upper_response": {}, "frozen_upper_response_sha256": "y"}
        with patch("ddvc.ethereum_logs.fetch_exact_logs_with_evidence", side_effect=fetch):
            records, evidence = fetch_exact_logs_with_capacity_bisection(start_block=10, end_block=11, topics=[V4_INITIALIZE_TOPIC], frozen_upper={})
        self.assertEqual(records, [])
        self.assertEqual([(row["start_block"], row["end_block"]) for row in evidence], [(10, 10), (11, 11)])

    def test_v4_generation_certifies_modify_and_swap_payloads_after_initialize(self) -> None:
        zero = "0x" + "0" * 40
        pool = v4_pool_id(A, B, 500, 10, zero)
        initialize = raw(UNISWAP_V4_POOL_MANAGER_ADDRESS, [V4_INITIALIZE_TOPIC, pool, topic_address(A), topic_address(B)], abi_encode(["uint24", "int24", "address", "uint160", "int24"], [500, 10, zero, 2**96, 0]), log_index=0)
        modify = raw(UNISWAP_V4_POOL_MANAGER_ADDRESS, [UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC, pool, topic_address(A)], abi_encode(["int24", "int24", "int256", "bytes32"], [-10, 10, 7, b"\0" * 32]), log_index=1)
        swap = raw(UNISWAP_V4_POOL_MANAGER_ADDRESS, [UNISWAP_V4_SWAP_TOPIC, pool, topic_address(A)], abi_encode(["int128", "int128", "uint160", "uint128", "int24", "uint24"], [5, -4, 2**96, 7, 0, 500]), log_index=2)
        frozen = frozen_upper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thegraph"
            rows = [initialize, modify, swap]
            write_state_event_chunk("uniswap_v4", 10, 10, rows, exact_evidence(rows, frozen), frozen_upper=frozen, root=root)
            decoded, release = certify_state_event_generation("uniswap_v4", [(10, 10)], frozen_upper=frozen, raw_root=root)
            state_events = list(iter_v4_state_events([(10, 10)], frozen_upper=frozen, raw_root=root))
            release["metadata_source_manifest"] = []
            release["metadata_source_manifest_sha256"] = hashlib.sha256(b"[]").hexdigest()
            release["certificate_identity_sha256"] = certificate_identity_sha256(release)
            metadata = {A: ("A", 18), B: ("B", 6)}
            cuts = certified_day_cuts({"20250101": (10, 10)})
            write_daily_initializations("uniswap_v4", decoded, day_cuts=cuts, token_metadata=metadata, raw_root=root, generation_certificate=release)
            write_daily_v4_state_events(state_events, decoded, day_cuts=cuts, token_metadata=metadata, raw_root=root, generation_certificate=release)
            data, _marker, _certificate = validate_v4_state_day(root, "20250101")
            with gzip.open(data, "at", encoding="utf-8") as handle:
                handle.write("{}\n")
            with self.assertRaisesRegex(ValueError, "stale or uncertified"):
                validate_v4_state_day(root, "20250101")
        self.assertEqual(len(decoded), 1)
        self.assertEqual([row["kind"] for row in state_events], ["modify_liquidity", "swap"])
        self.assertEqual((release["exact_modify_liquidity_events"], release["exact_swap_events"]), (1, 1))
        self.assertEqual(release["precedence_status"], "pass")


if __name__ == "__main__":
    unittest.main()

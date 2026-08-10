from __future__ import annotations

import json
import unittest
from unittest.mock import patch
import urllib.error

from ddvc import quoter


class Response:
    def __init__(self, body: dict) -> None:
        self.body = body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.body).encode()


class RpcPostTests(unittest.TestCase):
    def setUp(self) -> None:
        quoter._rpc_idx = 0
        quoter._disabled_rpc_urls.clear()

    def test_receipt_mode_rotates_past_http_200_json_rpc_errors(self) -> None:
        rejected = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "authentication required"}}
        )
        accepted = Response({"jsonrpc": "2.0", "id": 1, "result": {"gasUsed": "0x1"}})
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=[rejected, accepted]) as request,
        ):
            response = quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": ["0x1"]},
                retries=1,
                retry_json_errors=True,
            )
        self.assertEqual(response["result"]["gasUsed"], "0x1")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(quoter._disabled_rpc_urls, {"https://first"})

        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
            patch.object(quoter.urllib.request, "urlopen", return_value=accepted) as next_request,
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 2, "method": "eth_getTransactionReceipt", "params": ["0x2"]},
                retries=1,
                retry_json_errors=True,
            )
        self.assertEqual(next_request.call_count, 1)
        self.assertEqual(next_request.call_args.args[0].full_url, "https://second")

    def test_default_mode_preserves_execution_error_responses(self) -> None:
        rejected = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}
        )
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
            patch.object(quoter.urllib.request, "urlopen", return_value=rejected) as request,
        ):
            response = quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": []},
                retries=1,
            )
        self.assertEqual(response["error"]["code"], 3)
        self.assertEqual(request.call_count, 1)

    def test_gateway_5xx_is_retryable_instead_of_a_terminal_fetch_error(self) -> None:
        gateway_failure = urllib.error.HTTPError(
            "https://first", 521, "gateway unavailable", {}, None
        )
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=gateway_failure),
            patch.object(quoter.time, "sleep"),
            self.assertRaises(quoter.Throttled),
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
            )

    def test_transport_exhaustion_is_a_retryable_queue_error(self) -> None:
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=TimeoutError("slow")),
            patch.object(quoter.time, "sleep"),
            self.assertRaises(quoter.Throttled),
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
            )

    def test_evidence_mode_returns_sanitized_attempts(self) -> None:
        accepted = Response({"jsonrpc": "2.0", "id": 1, "result": []})
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://user:secret@example.test/key?a=secret"]),
            patch.object(quoter.urllib.request, "urlopen", return_value=accepted),
        ):
            envelope = quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                return_evidence=True,
                classify_capacity=True,
            )
        self.assertIsInstance(envelope, quoter.RpcEnvelope)
        self.assertEqual(envelope.endpoint["host"], "example.test")
        self.assertNotIn("secret", json.dumps(envelope.attempts))
        self.assertEqual(envelope.attempts[-1]["classification"], "success")
        self.assertEqual(
            envelope.endpoint,
            quoter.sanitized_endpoint_identity("https://different:credential@example.test/other"),
        )
        quoter.validate_rpc_attempts(envelope.attempts, envelope.endpoint)

    def test_attempt_validator_rejects_success_unbound_from_winning_endpoint(self) -> None:
        endpoint = quoter.sanitized_endpoint_identity("https://winner.test")
        other = quoter.sanitized_endpoint_identity("https://other.test")
        attempts = ({
            "endpoint": other,
            "attempt": 1,
            "classification": "success",
            "http_status": 200,
            "rpc_code": None,
            "message": "success",
        },)
        with self.assertRaisesRegex(ValueError, "successful endpoint"):
            quoter.validate_rpc_attempts(attempts, endpoint)

    def test_evidence_redacts_credentials_echoed_by_provider_errors(self) -> None:
        rejected = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "api key secret-token is invalid"}}
        )
        accepted = Response({"jsonrpc": "2.0", "id": 1, "result": []})
        with (
            patch.object(
                quoter,
                "rpc_urls",
                return_value=["https://user:secret-token@first.test/private", "https://second.test"],
            ),
            patch.object(quoter.urllib.request, "urlopen", side_effect=[rejected, accepted]),
        ):
            envelope = quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                return_evidence=True,
                classify_capacity=True,
            )
        self.assertNotIn("secret-token", json.dumps(envelope.attempts))
        self.assertEqual(envelope.attempts[0]["message"], "api key")

    def test_archive_token_requirement_disables_endpoint_and_rotates(self) -> None:
        rejected = Response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "Archive requests require a personal token"},
            }
        )
        accepted = Response({"jsonrpc": "2.0", "id": 1, "result": []})
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=[rejected, accepted]),
        ):
            envelope = quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                return_evidence=True,
                classify_capacity=True,
            )
        self.assertEqual(envelope.attempts[0]["classification"], "transient")
        self.assertEqual(envelope.attempts[0]["message"], "personal token")
        self.assertEqual(quoter._disabled_rpc_urls, {"https://first"})

    def test_unroutable_gateway_is_retryable(self) -> None:
        rejected = Response(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": 12, "message": "Can't route your request to suitable provider"},
            }
        )
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first"]),
            patch.object(quoter.urllib.request, "urlopen", return_value=rejected),
            patch.object(quoter.time, "sleep"),
            self.assertRaises(quoter.Throttled),
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                classify_capacity=True,
            )

    def test_explicit_result_cap_licenses_bisection(self) -> None:
        rejected = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "too many results"}}
        )
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first"]),
            patch.object(quoter.urllib.request, "urlopen", return_value=rejected),
            self.assertRaises(quoter.RpcCapacityError) as raised,
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                classify_capacity=True,
            )
        self.assertEqual(raised.exception.attempts[-1]["classification"], "capacity")

    def test_ambiguous_minus_32005_is_transient_not_capacity(self) -> None:
        rejected = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "temporarily unavailable"}}
        )
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first"]),
            patch.object(quoter.urllib.request, "urlopen", return_value=rejected),
            self.assertRaises(quoter.Throttled),
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                classify_capacity=True,
            )

    def test_timeout_is_transient_not_capacity(self) -> None:
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=TimeoutError("slow")),
            self.assertRaises(quoter.Throttled),
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                classify_capacity=True,
            )

    def test_terminal_semantic_error_takes_precedence_over_capacity(self) -> None:
        terminal = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "invalid params"}}
        )
        capacity = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "too many results"}}
        )
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=[terminal, capacity]),
            self.assertRaises(quoter.RpcSemanticError),
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                classify_capacity=True,
            )

    def test_unavailable_authenticated_endpoint_does_not_block_capacity_classification(self) -> None:
        unavailable = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "authentication required"}}
        )
        capacity = Response(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "too many results"}}
        )
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=[unavailable, capacity]),
            self.assertRaises(quoter.RpcCapacityError),
        ):
            quoter.rpc_post(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                retries=1,
                retry_json_errors=True,
                classify_capacity=True,
            )

    def test_batch_error_rotates_before_accepting_two_item_evidence(self) -> None:
        rejected = Response(
            [
                {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "usage limit"}},
                {"jsonrpc": "2.0", "id": 2, "result": {"number": "0x1"}},
            ]
        )
        accepted_body = [
            {"jsonrpc": "2.0", "id": 1, "result": []},
            {"jsonrpc": "2.0", "id": 2, "result": {"number": "0x1"}},
        ]
        accepted = Response(accepted_body)
        with (
            patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
            patch.object(quoter.urllib.request, "urlopen", side_effect=[rejected, accepted]),
        ):
            envelope = quoter.rpc_post(
                [
                    {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
                    {"jsonrpc": "2.0", "id": 2, "method": "eth_getBlockByNumber", "params": ["0x1", False]},
                ],
                retries=1,
                retry_json_errors=True,
                return_evidence=True,
                classify_capacity=True,
            )
        self.assertEqual(envelope.response, accepted_body)
        self.assertEqual([attempt["classification"] for attempt in envelope.attempts], ["transient", "success"])


if __name__ == "__main__":
    unittest.main()

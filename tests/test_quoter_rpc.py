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


if __name__ == "__main__":
    unittest.main()

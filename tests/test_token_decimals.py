from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ddvc import quoter
from ddvc.quoter import RpcEnvelope, RpcSemanticError, Throttled
from ddvc.token_decimals import (
    ERC20_DECIMALS_SELECTOR,
    TokenDecimalsAnchor,
    build_token_decimals_registry,
    load_or_fetch_token_decimals_evidence,
    resolve_token_decimals_evidence,
    select_token_decimals_anchors,
    token_decimals_evidence_path,
    validate_token_decimals_evidence,
    validate_token_decimals_registry,
    write_token_decimals_registry,
)


TOKEN = "0x" + "1" * 40
POOL = "0x" + "2" * 40
BLOCK_HASH = "0x" + "3" * 64
TX_HASH = "0x" + "4" * 64
ENDPOINT = {"host": "injected", "endpoint_sha256": "5" * 64}


class HttpResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.body).encode()


def anchor(*, priority: int = 0, block_number: int = 100) -> TokenDecimalsAnchor:
    return TokenDecimalsAnchor(
        token=TOKEN,
        block_number=block_number,
        block_hash=BLOCK_HASH,
        priority=priority,
        proof_kind="matched_core_event",
        venue="uniswap_v2",
        pool=POOL,
        event_type="swap",
        transaction_hash=TX_HASH,
        transaction_index=1,
        log_index=2,
    )


def envelope(payload: dict[str, object], result: object) -> RpcEnvelope:
    return RpcEnvelope(
        {"jsonrpc": "2.0", "id": payload["id"], "result": result},
        ENDPOINT,
        (
            {
                "endpoint": ENDPOINT,
                "attempt": 1,
                "classification": "success",
                "http_status": 200,
                "rpc_code": None,
                "message": "success",
            },
        ),
    )


def test_exact_decimals_covers_a_token_outside_any_priced_panel_and_reuses_cache(tmp_path) -> None:
    calls = []

    def rpc(payload, **_kwargs):
        calls.append(payload)
        return envelope(payload, "0x" + f"{6:064x}")

    expected = anchor()
    record, path = load_or_fetch_token_decimals_evidence(
        expected,
        fetch=True,
        root=tmp_path / "raw",
        rpc_request=rpc,
    )
    assert record["decimals"] == 6
    assert calls == [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {"to": TOKEN, "data": ERC20_DECIMALS_SELECTOR},
                {"blockHash": BLOCK_HASH, "requireCanonical": True},
            ],
        }
    ]
    cached, cached_path = load_or_fetch_token_decimals_evidence(
        expected,
        fetch=False,
        root=tmp_path / "raw",
        rpc_request=lambda *_args, **_kwargs: pytest.fail("valid cache must be reopened"),
    )
    assert cached == record
    assert cached_path == path


@pytest.mark.parametrize("failure_token", [TOKEN, "0x" + "6" * 40])
def test_bounded_resolver_recovers_first_or_late_transient_token(tmp_path, failure_token) -> None:
    late_token = "0x" + "6" * 40
    anchors = {
        TOKEN: anchor(),
        late_token: TokenDecimalsAnchor(**{**anchor(block_number=101).__dict__, "token": late_token}),
    }
    calls = {token: 0 for token in anchors}

    def resolve_one(expected, **_kwargs):
        calls[expected.token] += 1
        if expected.token == failure_token and calls[expected.token] == 1:
            raise Throttled("temporary")
        return {"token": expected.token}, tmp_path / f"{expected.token}.json"

    with patch("ddvc.token_decimals.load_or_fetch_token_decimals_evidence", side_effect=resolve_one):
        records, paths = resolve_token_decimals_evidence(anchors, fetch=True, workers=2, max_attempts=2, retry_backoff=0)
    assert set(records) == set(anchors)
    assert set(paths) == set(anchors)
    assert calls[failure_token] == 2
    assert calls[next(token for token in anchors if token != failure_token)] == 1


def test_bounded_resolver_fails_closed_after_transient_cap(tmp_path) -> None:
    with (
        patch("ddvc.token_decimals.load_or_fetch_token_decimals_evidence", side_effect=Throttled("temporary")) as request,
        pytest.raises(RuntimeError, match="after 3 bounded attempts"),
    ):
        resolve_token_decimals_evidence({TOKEN: anchor()}, fetch=True, workers=4, root=tmp_path, max_attempts=3, retry_backoff=0)
    assert request.call_count == 3
    assert list(tmp_path.rglob("*")) == []


def test_tampered_exact_response_is_rejected_without_overwrite(tmp_path) -> None:
    expected = anchor()
    _record, path = load_or_fetch_token_decimals_evidence(
        expected,
        fetch=True,
        root=tmp_path,
        rpc_request=lambda payload, **_kwargs: envelope(payload, "0x" + f"{18:064x}"),
    )
    tampered = json.loads(path.read_text())
    tampered["rpc_response"]["result"] = "0x" + f"{6:064x}"
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="response digest"):
        load_or_fetch_token_decimals_evidence(expected, fetch=True, root=tmp_path)


def test_registry_reopens_raw_evidence_and_rejects_provider_time_variation(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    expected = anchor()
    record, evidence_path = load_or_fetch_token_decimals_evidence(
        expected,
        fetch=True,
        root=repo_root / "data" / "raw",
        rpc_request=lambda payload, **_kwargs: envelope(payload, "0x" + f"{6:064x}"),
    )
    registry = build_token_decimals_registry(
        {TOKEN: expected},
        {TOKEN: record},
        {TOKEN: evidence_path},
        {TOKEN: ["6", "18"]},
        repo_root=repo_root,
    )
    path = repo_root / "data" / "processed" / "registry.parquet"
    write_token_decimals_registry(registry, path)
    with pytest.raises(ValueError, match="invalid, varying, or disagreeing"):
        validate_token_decimals_registry(
            path,
            expected_anchors={TOKEN: expected},
            provider_observations={TOKEN: ["6", "18"]},
            repo_root=repo_root,
        )
    assert registry.loc[0, "provider_status"] == "time_varying"


def test_archive_error_rotates_to_valid_endpoint_and_retains_both_attempts(tmp_path) -> None:
    expected = anchor()
    archive_gap = HttpResponse(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "missing trie node for historical state"},
        }
    )
    valid = HttpResponse({"jsonrpc": "2.0", "id": 1, "result": "0x" + f"{6:064x}"})
    quoter._rpc_idx = 0
    quoter._disabled_rpc_urls.clear()
    with (
        patch.object(quoter, "rpc_urls", return_value=["https://archive-gap.example", "https://valid.example"]),
        patch.object(quoter.urllib.request, "urlopen", side_effect=[archive_gap, valid]),
    ):
        record, _path = load_or_fetch_token_decimals_evidence(
            expected,
            fetch=True,
            root=tmp_path,
        )
    assert record["status"] == "complete"
    assert record["decimals"] == 6
    assert [attempt["classification"] for attempt in record["rpc_attempts"]] == [
        "terminal",
        "success",
    ]
    assert [attempt["endpoint"]["host"] for attempt in record["rpc_attempts"]] == [
        "archive-gap.example",
        "valid.example",
    ]


def test_malformed_http_200_result_fails_acquisition_without_cache(tmp_path) -> None:
    expected = anchor()
    malformed = HttpResponse({"jsonrpc": "2.0", "id": 1, "result": "0x1234"})
    quoter._rpc_idx = 0
    quoter._disabled_rpc_urls.clear()
    with (
        patch.object(quoter, "rpc_urls", return_value=["https://first.example", "https://second.example"]),
        patch.object(quoter.urllib.request, "urlopen", side_effect=[malformed, malformed]),
        pytest.raises(Throttled),
    ):
        load_or_fetch_token_decimals_evidence(expected, fetch=True, root=tmp_path)
    assert not token_decimals_evidence_path(expected, root=tmp_path).exists()


def test_terminal_no_decimals_fails_explicitly_without_unsupported_evidence(tmp_path) -> None:
    expected = anchor()
    reverted = HttpResponse(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": 3, "message": "execution reverted"},
        }
    )
    quoter._rpc_idx = 0
    quoter._disabled_rpc_urls.clear()
    with (
        patch.object(quoter, "rpc_urls", return_value=["https://first.example", "https://second.example"]),
        patch.object(quoter.urllib.request, "urlopen", side_effect=[reverted, reverted]),
        pytest.raises(RpcSemanticError) as error,
    ):
        load_or_fetch_token_decimals_evidence(expected, fetch=True, root=tmp_path)
    assert [attempt["classification"] for attempt in error.value.attempts] == ["terminal", "terminal"]
    assert not token_decimals_evidence_path(expected, root=tmp_path).exists()


def test_anchor_selection_prefers_a_matched_event_before_earlier_fallback() -> None:
    earlier_fallback = TokenDecimalsAnchor(
        **{
            **anchor(priority=1, block_number=90).__dict__,
            "proof_kind": "exact_core_event",
        }
    )
    matched = anchor(priority=0, block_number=100)
    assert select_token_decimals_anchors([earlier_fallback, matched]) == {TOKEN: matched}


def test_registry_rejects_tampered_raw_evidence(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    expected = anchor()
    record, evidence_path = load_or_fetch_token_decimals_evidence(
        expected,
        fetch=True,
        root=repo_root / "data" / "raw",
        rpc_request=lambda payload, **_kwargs: envelope(payload, "0x" + f"{6:064x}"),
    )
    registry = build_token_decimals_registry(
        {TOKEN: expected},
        {TOKEN: record},
        {TOKEN: evidence_path},
        {TOKEN: ["6"]},
        repo_root=repo_root,
    )
    path = repo_root / "data" / "processed" / "registry.parquet"
    write_token_decimals_registry(registry, path)
    evidence_path.write_text(evidence_path.read_text() + " ")
    with pytest.raises(ValueError, match="evidence digest"):
        validate_token_decimals_registry(path, repo_root=repo_root)

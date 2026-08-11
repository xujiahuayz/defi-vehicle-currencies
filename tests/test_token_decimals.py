from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ddvc import quoter
from ddvc.quoter import RpcEnvelope, RpcSemanticError, Throttled
from ddvc.token_decimals import (
    ERC20_DECIMALS_SELECTOR,
    TokenDecimalsResolutionError,
    TokenDecimalsAnchor,
    build_token_decimals_anchor_manifest,
    build_token_decimals_registry,
    load_token_decimals_anchor_manifest,
    load_or_fetch_token_decimals_evidence,
    retain_token_decimals_anchor,
    resolve_token_decimals_evidence,
    select_token_decimals_anchors,
    token_decimals_evidence_path,
    validate_token_decimals_evidence,
    validate_token_decimals_registry,
    write_token_decimals_anchor_manifest,
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


def test_resolver_collects_distinct_terminal_failures_retains_success_and_installs_ledger_last(tmp_path) -> None:
    tokens = [TOKEN, "0x" + "6" * 40, "0x" + "7" * 40]
    anchors = {
        token: TokenDecimalsAnchor(
            **{
                **anchor(block_number=100 + index).__dict__,
                "token": token,
            }
        )
        for index, token in enumerate(tokens)
    }
    repo_root = tmp_path / "repo"
    ledger_path = repo_root / "data" / "raw" / "unresolved.json"
    manifest_path = repo_root / "data" / "raw" / "anchors.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}")
    calls = {token: 0 for token in anchors}

    def resolve_one(expected, **_kwargs):
        assert not ledger_path.exists()
        calls[expected.token] += 1
        if expected.token in tokens[:2]:
            raise Throttled(f"unavailable-{expected.token[-1]}")
        path = repo_root / "data" / "raw" / f"{expected.token}.json"
        path.write_text('{"complete":true}\n')
        return {"token": expected.token}, path

    with (
        patch("ddvc.token_decimals.load_or_fetch_token_decimals_evidence", side_effect=resolve_one),
        pytest.raises(TokenDecimalsResolutionError) as caught,
    ):
        resolve_token_decimals_evidence(
            anchors,
            fetch=True,
            workers=3,
            max_attempts=2,
            retry_backoff=0,
            unresolved_ledger_path=ledger_path,
            anchor_manifest_path=manifest_path,
            repo_root=repo_root,
        )
    assert set(caught.value.failures) == set(tokens[:2])
    assert set(caught.value.records) == {tokens[2]}
    assert calls == {tokens[0]: 2, tokens[1]: 2, tokens[2]: 1}
    ledger = json.loads(ledger_path.read_text())
    assert ledger["status"] == "complete"
    assert ledger["resolved_count"] == 1
    assert ledger["unresolved_count"] == 2
    assert [row["token"] for row in ledger["unresolved"]] == sorted(tokens[:2])


def test_resolver_drains_invalid_cache_semantic_rpc_and_transient_cap_before_one_raise(tmp_path) -> None:
    invalid_token, semantic_token, transient_token, success_token = [
        "0x" + digit * 40 for digit in ("6", "7", "8", "9")
    ]
    anchors = {
        token: TokenDecimalsAnchor(
            **{
                **anchor(block_number=100 + index).__dict__,
                "token": token,
            }
        )
        for index, token in enumerate(
            (invalid_token, semantic_token, transient_token, success_token)
        )
    }
    repo_root = tmp_path / "repo"
    evidence_root = repo_root / "data" / "raw" / "token_decimals"
    invalid_path = token_decimals_evidence_path(
        anchors[invalid_token],
        root=evidence_root,
    )
    invalid_path.parent.mkdir(parents=True)
    invalid_path.write_text('{"schema_version":null}\n', encoding="utf-8")
    ledger_path = repo_root / "data" / "raw" / "unresolved.json"
    manifest_path = repo_root / "data" / "raw" / "anchors.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    calls = {token: 0 for token in anchors}

    def rpc(payload, **_kwargs):
        assert not ledger_path.exists()
        token = payload["params"][0]["to"]
        calls[token] += 1
        if token == semantic_token:
            raise RpcSemanticError("historical state is terminal")
        if token == transient_token:
            raise Throttled("provider capacity")
        return envelope(payload, "0x" + f"{18:064x}")

    with pytest.raises(TokenDecimalsResolutionError) as caught:
        resolve_token_decimals_evidence(
            anchors,
            fetch=True,
            workers=4,
            root=evidence_root,
            rpc_request=rpc,
            max_attempts=2,
            retry_backoff=0,
            unresolved_ledger_path=ledger_path,
            anchor_manifest_path=manifest_path,
            repo_root=repo_root,
        )
    assert set(caught.value.records) == {success_token}
    assert {token: failure["classification"] for token, failure in caught.value.failures.items()} == {
        invalid_token: "invalid_cached_evidence",
        semantic_token: "terminal_rpc_semantics",
        transient_token: "transient_attempt_cap",
    }
    assert calls == {
        invalid_token: 0,
        semantic_token: 1,
        transient_token: 2,
        success_token: 1,
    }
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["status"] == "complete"
    assert ledger["resolved_count"] == 1
    assert ledger["unresolved_count"] == 3
    assert str(repo_root) not in ledger["unresolved"][0]["error_message"]
    assert [row["classification"] for row in ledger["unresolved"]] == [
        "invalid_cached_evidence",
        "terminal_rpc_semantics",
        "transient_attempt_cap",
    ]


def test_selected_anchor_manifest_reopens_without_reselection_and_revalidates_lineage(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    lineage_path = repo_root / "data" / "raw" / "exact.parquet"
    lineage_path.parent.mkdir(parents=True)
    lineage_path.write_bytes(b"exact-v1")
    manifest_path = repo_root / "data" / "raw" / "selected.json"
    context = {"audit_days": ["20250101"], "factory_registry_sha256": "a" * 64}
    expected = anchor()
    manifest = build_token_decimals_anchor_manifest(
        {TOKEN: expected},
        {TOKEN: ["6"]},
        context=context,
        lineage_inputs=[lineage_path],
        statistics={"raw_global_event_logs": 7},
        repo_root=repo_root,
    )
    write_token_decimals_anchor_manifest(manifest, manifest_path)
    with patch(
        "ddvc.token_decimals.select_token_decimals_anchors",
        side_effect=lambda *_args, **_kwargs: pytest.fail(
            "resume must not rerun anchor selection"
        ),
    ):
        anchors, observations, paths, statistics = load_token_decimals_anchor_manifest(
            manifest_path,
            expected_context=context,
            repo_root=repo_root,
        )
    assert anchors == {TOKEN: expected}
    assert observations == {TOKEN: ["6"]}
    assert paths == [lineage_path]
    assert statistics == {"raw_global_event_logs": 7}
    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered["statistics"]["raw_global_event_logs"] = 8
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="statistics digest"):
        load_token_decimals_anchor_manifest(
            manifest_path,
            expected_context=context,
            repo_root=repo_root,
        )
    write_token_decimals_anchor_manifest(manifest, manifest_path)
    lineage_path.write_bytes(b"exact-v2")
    with pytest.raises(ValueError, match="lineage changed"):
        load_token_decimals_anchor_manifest(
            manifest_path,
            expected_context=context,
            repo_root=repo_root,
        )


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


def test_online_anchor_selection_matches_batch_order_across_ties_and_fallbacks() -> None:
    fallback = TokenDecimalsAnchor(
        **{
            **anchor(priority=2, block_number=90).__dict__,
            "proof_kind": "factory_pair_created",
            "event_type": "pair_created",
        }
    )
    later_event = anchor(priority=0, block_number=101)
    winning_event = anchor(priority=0, block_number=100)
    tied_event = TokenDecimalsAnchor(**winning_event.__dict__)
    candidates = [fallback, later_event, winning_event, tied_event]
    selected: dict[str, TokenDecimalsAnchor] = {}
    for candidate in candidates:
        retain_token_decimals_anchor(selected, candidate)
    assert selected == select_token_decimals_anchors(candidates) == {TOKEN: winning_event}


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

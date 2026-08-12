from __future__ import annotations

import pytest

from ddvc.fetch.schema_admission import ROOT_POLICIES, adjudicate_entity_fields, adjudicate_new_stream_fields, adjudicate_query_roots, build_field_admission_manifest


def _entity() -> dict:
    return {
        "stream": "swaps",
        "entity": "swaps",
        "selected_paths": ["id", "pool.id", "badRelation"],
        "fields": [
            {"path": "id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
            {"path": "amountUSD", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
            {"path": "old", "kind": "SCALAR", "deprecated": True, "field_list_valued": False, "ancestor_list_valued": False},
            {"path": "pool.id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
            {"path": "pool.feeTier", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
            {"path": "pool.totalValueLockedUSD", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
            {"path": "pool.ticks.id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": True},
        ],
    }


def test_admission_adds_root_primitives_and_bounded_mechanics() -> None:
    result = adjudicate_entity_fields("example", _entity())
    assert result["added_paths"] == ["amountUSD"]
    assert result["removed_or_invalid_paths"] == ["badRelation"]
    assert "pool.totalValueLockedUSD" not in result["proposed_selected_paths"]
    assert "pool.ticks.id" not in result["proposed_selected_paths"]


def test_admission_removes_balancer_query_head_state() -> None:
    entity = _entity()
    entity["stream"] = "daily"
    entity["selected_paths"] = ["id", "pool.amp"]
    entity["fields"].append(
        {"path": "pool.amp", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False}
    )
    result = adjudicate_entity_fields("balancer", entity)
    assert result["removed_or_invalid_paths"] == ["pool.amp"]
    assert next(item for item in result["decisions"] if item["path"] == "pool.amp")["reason"] == "mutable_parent_state_can_leak_query_head_backward"


def test_manifest_detects_source_specific_schema_divergence() -> None:
    first = _entity()
    second = _entity()
    second["fields"] = [*second["fields"], {"path": "gasUsed", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False}]
    manifest = build_field_admission_manifest(
        {
            "captured_at_utc": "2026-08-11T00:00:00+00:00",
            "sources": [
                {"source": "a", "schema_family": "shared", "status": "available", "entities": [first], "query_roots": []},
                {"source": "b", "schema_family": "shared", "status": "available", "entities": [second], "query_roots": []},
            ],
        }
    )
    assert manifest["summary"]["source_specific_schema_splits_required"] == 1
    assert manifest["source_specific_schema_splits"][0]["sources"] == ["a", "b"]


def test_query_root_admission_fails_when_collection_is_unclassified() -> None:
    with pytest.raises(ValueError, match="mysteries"):
        adjudicate_query_roots(
            {
                "source": "uniswap_v3",
                "entities": [],
                "query_roots": [{"name": "mysteries", "type": "Mystery", "list_valued": True}],
            }
        )


def test_new_event_stream_admits_direct_arrays_and_bounded_token_identity() -> None:
    result = adjudicate_new_stream_fields(
        "curve",
        {
            "entity": "deposits",
            "entity_type": "Deposit",
            "mode": "historical_event_full",
            "fields": [
                {"path": "id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
                {"path": "inputTokenAmounts", "kind": "SCALAR", "deprecated": False, "field_list_valued": True, "ancestor_list_valued": False},
                {"path": "inputTokens.id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": True},
                {"path": "pool.swaps.id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": True},
            ],
        },
    )
    assert result["proposed_selected_paths"] == ["id", "inputTokenAmounts", "inputTokens.id"]


def test_unowned_list_valued_primitive_fails_closed() -> None:
    with pytest.raises(ValueError, match="unowned admitted Graph vectors"):
        adjudicate_new_stream_fields(
            "curve",
            {
                "entity": "deposits",
                "entity_type": "Deposit",
                "mode": "historical_event_full",
                "fields": [
                    {"path": "id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
                    {"path": "mysteryAmounts", "kind": "SCALAR", "deprecated": False, "field_list_valued": True, "ancestor_list_valued": False},
                ],
            },
        )


def test_nested_reverse_management_identity_is_not_admitted() -> None:
    result = adjudicate_new_stream_fields(
        "balancer",
        {
            "entity": "pools",
            "entity_type": "Pool",
            "mode": "block_pinned_configuration",
            "fields": [
                {"path": "id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False},
                {"path": "tokens.managements.id", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": True},
            ],
        },
    )
    assert result["proposed_selected_paths"] == ["id"]


def test_null_quarantine_is_source_and_stream_specific() -> None:
    mint = _entity()
    mint["stream"] = "mints"
    mint["selected_paths"] = ["id", "feeLiquidity"]
    mint["fields"].append(
        {"path": "feeLiquidity", "kind": "SCALAR", "deprecated": False, "field_list_valued": False, "ancestor_list_valued": False}
    )
    burn = {**mint, "stream": "burns"}
    assert "feeLiquidity" not in adjudicate_entity_fields("uniswap_v2", mint)["proposed_selected_paths"]
    assert "feeLiquidity" in adjudicate_entity_fields("uniswap_v2", burn)["proposed_selected_paths"]


def test_former_placeholder_roots_have_truthful_adjudications() -> None:
    assert ROOT_POLICIES["uniswap_v3"]["positionSnapshots"]["decision"] == "admit"
    assert ROOT_POLICIES["sushiswap_v3"]["tickHourlySnapshots"]["decision"] == "admit"
    assert ROOT_POLICIES["balancer"]["swapFeeUpdates"]["decision"] == "admit"
    assert ROOT_POLICIES["curve"]["liquidityGauges"]["decision"] == "admit"
    confirmed_empty = {
        (source, root)
        for source, policy in ROOT_POLICIES.items()
        for root, decision in policy.items()
        if decision["reason"] == "confirmed_empty_at_frozen_cutoff"
    }
    assert confirmed_empty == {
        ("balancer", "circuitBreakers"),
        ("sushiswap_v3", "rewardTokens"),
        ("uniswap_v3", "collects"),
        ("uniswap_v3", "flashes"),
        ("uniswap_v3", "tickHourDatas"),
        ("uniswap_v4", "subscribes"),
        ("uniswap_v4", "unsubscribes"),
    }

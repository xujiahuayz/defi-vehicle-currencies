from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import pandas as pd

from ddvc.asset_types import TYPES
from scripts import refresh_panel_dependents as refresher
from scripts.audit_findings_freeze import (
    card_source_evidence_text,
    cex_reference_support_checks,
    cited_bibliography_keys,
    companion_sources_closed,
    companion_source_keys,
    complete_literature_card,
    confirmatory_promotion_errors,
    expected_market_state_keys,
    expected_unified_route_venue_days,
    graph_status,
    literature_use_contract_violations,
    non_text_dispositions_closed,
    parse_literature_cards,
    parse_state_frontmatter,
    published_venue_version,
    registered_empirical_consumers,
    retired_route_gas_release_checks,
    route_measurement_invariants,
    route_cost_panel_checks,
    source_materialized,
    source_set_companion_disposition_resolved,
    source_set_main_artifact_closed,
    source_set_record_closed,
    transaction_frontier_artifact_checks,
    transaction_frontier_support_checks,
    v2_event_source_certificate_checks,
    v3_event_source_certificate_checks,
    validate_capital_contract_rows,
    validate_literature_audit,
    validate_literature_use_contracts,
    validate_liquidity_contracts,
    validate_quote_state_contract_rows,
    validate_canonical_consumer_boundary,
    validate_claim_input_layer,
    validate_model_ledger,
    validate_specification_lock,
    validate_unified_route_layer,
    v3_inventory_calendar_checks,
)
from ddvc.literature_admission import validate_source_admission
from ddvc.liquidity import LIQUIDITY_CONTRACTS
from ddvc.model_registry import canonical_hash, exploratory_plan_identity, model_run_id
from ddvc.provenance import portable_content_sha256, sidecar_path
from scripts.refresh_panel_dependents import (
    CLAIM_INPUT_STAGES,
    DAILY_FRONTIER_PREREQUISITES,
)


def _bind_exploratory_plan(run: dict) -> None:
    run.update(
        {
            "plan_path": "docs/test-exploration-plan.json",
            "runner": "scripts/test-exploration-runner.py",
            "arguments": [],
            "engine_sources": ["scripts/test-exploration-runner.py"],
            "question": "Which exploratory pattern merits confirmation?",
            "search_dimensions": ["mechanism"],
            "declared_artifacts": [
                {
                    "path": artifact["path"],
                    "role": artifact["role"],
                    "spec_ids": artifact["spec_ids"],
                }
                for artifact in run["artifacts"]
            ],
        }
    )
    run["plan_hash"] = canonical_hash(exploratory_plan_identity(run))
    run["run_id"] = model_run_id(run)


class FindingsFreezeAuditTest(unittest.TestCase):
    def test_retired_route_gas_gate_covers_code_refresh_publications_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "scripts/refresh_panel_dependents.py",
                "scripts/test_gap_arbitrage_bound.py",
                "scripts/measure_dominance_windows.py",
                "scripts/run_rent_incidence.py",
                "src/ddvc/cpquote.py",
                "paper/sections/01-introduction.tex",
                "deck/sections/01-introduction.tex",
                "docs/research-workflow.md",
                "docs/findings-freeze.md",
                "docs/specification-lock.json",
                "docs/paper-spine.md",
                "docs/deck-outline.md",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "raise RuntimeError('withdrawn')\n"
                    if path.name
                    in {
                        "test_gap_arbitrage_bound.py",
                        "measure_dominance_windows.py",
                        "run_rent_incidence.py",
                    }
                    else "registered exact-clock owner\n",
                    encoding="utf-8",
                )

            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertTrue(all(checks.values()), checks)

            (root / "scripts" / "refresh_panel_dependents.py").write_text(
                "measure_dominance_windows.py\n", encoding="utf-8"
            )
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(checks["retired route-gas executables fail closed"])

            (root / "scripts" / "refresh_panel_dependents.py").write_text("safe\n", encoding="utf-8")
            (root / "src" / "ddvc" / "cpquote.py").write_text(
                "GAS_BY_LEGS = {}\neth_usd = 2500\n", encoding="utf-8"
            )
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(checks["retired route-gas constants absent from code"])

            (root / "src" / "ddvc" / "cpquote.py").write_text("safe\n", encoding="utf-8")
            (root / "docs" / "new-current-note.md").write_text(
                "A separate sample contains 319,906 rows and a $2,500 notional.\n",
                encoding="utf-8",
            )
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertTrue(all(checks.values()), checks)

            (root / "paper" / "sections" / "01-introduction.tex").write_text(
                "output/exhibits/gap_arbitrage_bound.jsonl\n", encoding="utf-8"
            )
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(
                checks["withdrawn route-gas evidence absent from publication surfaces"]
            )

            (root / "paper" / "sections" / "01-introduction.tex").write_text("safe\n", encoding="utf-8")
            (root / "deck" / "sections" / "01-introduction.tex").write_text(
                "Three-hop gas at 319,906 units\n", encoding="utf-8"
            )
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(
                checks["withdrawn route-gas evidence absent from publication surfaces"]
            )

            (root / "deck" / "sections" / "01-introduction.tex").write_text("safe\n", encoding="utf-8")
            unregistered_doc = root / "docs" / "new-current-note.md"
            unregistered_doc.write_text("Gas per hop: 74,096\n", encoding="utf-8")
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(
                checks["withdrawn route-gas evidence absent from publication surfaces"]
            )

            unregistered_doc.write_text("safe\n", encoding="utf-8")
            artifact = root / "output" / "exhibits" / "dominance_windows_screened.jsonl"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(checks["withdrawn route-gas artifacts absent"])

            artifact.unlink()
            daily_artifact = root / "data" / "interim" / "gas_price_graph" / "20200211.json"
            daily_artifact.parent.mkdir(parents=True, exist_ok=True)
            daily_artifact.write_text("{}\n", encoding="utf-8")
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(checks["withdrawn route-gas artifacts absent"])

            daily_artifact.unlink()
            (root / "scripts" / "new_daily_gas.py").write_text(
                "path = 'data/interim/gas_days'\n", encoding="utf-8"
            )
            checks = {name: passed for name, passed, _detail in retired_route_gas_release_checks(root)}
            self.assertFalse(checks["retired route-gas constants absent from code"])

    def test_findings_gate_requires_current_exact_v2_event_certificate(self) -> None:
        import json

        from ddvc.fetch.sources import get_source
        from ddvc.graph_event_order import SCHEMA_VERSION as EVENT_ORDER_SCHEMA_VERSION
        from ddvc.v2_event_completeness import (
            V2_CORE_EVENTS,
            V2_COMPARISON_LEDGER,
            V2_EVENT_SOURCE_SCHEMA_VERSION,
            V2_EVENT_VENUES,
            V2_POOL_PERIMETER,
            V2_RECONCILIATION_COUNT_FIELDS,
            V2_RECONCILIATION_SCOPE,
            V2_TOKEN_DECIMALS_CONTRACT,
            V2_TOKEN_DECIMALS_SCOPE,
            audit_calendar_sha256,
            compare_event_maps,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            quality = root / "quality.parquet"
            summary_path = root / "summary.parquet"
            exceptions_path = root / "exceptions.parquet"
            certificate_path = root / "certificate.json"
            day = "20201015"
            pd.DataFrame({"day": [day], "output_rows": [1], "passed": [True]}).to_parquet(
                quality,
                index=False,
            )
            rows = []
            for venue in V2_EVENT_VENUES:
                genesis = get_source(venue).genesis.strftime("%Y%m%d")
                venue_rows, _ = compare_event_maps(
                    day,
                    venue,
                    {},
                    {},
                    set(),
                    launch_status="pre_genesis" if day < genesis else "audited",
                )
                rows.extend(venue_rows)
            zero_reconciliation = {field: 0 for field in V2_RECONCILIATION_COUNT_FIELDS}
            correction_generations = {
                f"{venue}/{day}": {
                    "generation_id": "1" * 64,
                    "pointer_sha256": "2" * 64,
                    "data_sha256": "3" * 64,
                    "metadata_sha256": "4" * 64,
                    "scope": V2_RECONCILIATION_SCOPE,
                    "start_block": 1,
                    "end_block": 2,
                    "reconciliation_pool_perimeter_count": 1,
                    "reconciliation_pool_perimeter_sha256": "5" * 64,
                    "audited_token_decimals_count": 2,
                    "audited_token_decimals_sha256": "6" * 64,
                    "exact_log_inputs_sha256": {"exact": "7" * 64},
                    "authority_inputs_sha256": {"authority": "8" * 64},
                    "reconciliation_counts": dict(zero_reconciliation),
                }
                for venue in V2_EVENT_VENUES
            }
            pd.DataFrame(rows).to_parquet(summary_path, index=False)
            pd.DataFrame(columns=["status"]).to_parquet(exceptions_path, index=False)
            certificate_path.write_text(
                json.dumps(
                    {
                        "schema_version": V2_EVENT_SOURCE_SCHEMA_VERSION,
                        "status": "pass",
                        "audit_calendar_sha256": audit_calendar_sha256([day]),
                        "audit_dates": 1,
                        "first_day": day,
                        "last_day": day,
                        "summary_rows": len(rows),
                        "exception_rows": 0,
                        "venues": list(V2_EVENT_VENUES),
                        "event_types": list(V2_CORE_EVENTS),
                        "pool_perimeter": V2_POOL_PERIMETER,
                        "reconciliation_scope": V2_RECONCILIATION_SCOPE,
                        "comparison_ledger": V2_COMPARISON_LEDGER,
                        "correction_generation_schema_version": EVENT_ORDER_SCHEMA_VERSION,
                        "correction_generations": correction_generations,
                        "reconciliation_totals": zero_reconciliation,
                        "registry_source": "complete_factory_PairCreated_histories",
                        "global_event_query": "topic_only_without_address_filter",
                        "identity_fields": [
                            "venue",
                            "event_type",
                            "block_number",
                            "transaction_hash",
                            "log_index",
                            "pool",
                        ],
                        "quantity_contract": "exact_raw_token_deltas_and_swap_in_out_fields",
                        "token_decimals_contract": V2_TOKEN_DECIMALS_CONTRACT,
                        "token_decimals_scope": V2_TOKEN_DECIMALS_SCOPE,
                        "raw_factory_chunks": 2,
                        "raw_event_chunks": 2,
                        "raw_global_event_logs": 0,
                        "exact_events": 0,
                        "canonical_events": 0,
                        "matched_identities": 0,
                        "missing_from_canonical": 0,
                        "canonical_only": 0,
                        "canonical_duplicate_identities": 0,
                        "amount_mismatches": 0,
                        "factory_pairs": 2,
                        "factory_pairs_by_venue": {
                            venue: 1 for venue in V2_EVENT_VENUES
                        },
                        "factory_registry_sha256": "a" * 64,
                        "token_decimals_registry_rows": 2,
                        "token_decimals_registry_sha256": "f" * 64,
                        "token_decimals_registry_file_sha256": "1" * 64,
                        "token_decimals_evidence_files": 2,
                        "factory_registry_upper_block": 109,
                        "factory_registry_upper_block_hash": "0x" + "9" * 64,
                        "factory_registry_upper_block_timestamp": 1_700_000_000,
                        "frozen_upper_block_sha256": "d" * 64,
                        "factory_deployment_proof_sha256_by_venue": {
                            venue: "e" * 64 for venue in V2_EVENT_VENUES
                        },
                        "factory_coverage_manifest_sha256_by_venue": {
                            venue: "b" * 64 for venue in V2_EVENT_VENUES
                        },
                        "factory_state_proof_sha256_by_venue": {
                            venue: "c" * 64 for venue in V2_EVENT_VENUES
                        },
                        "factory_state_sample_size_by_venue": {
                            venue: 1 for venue in V2_EVENT_VENUES
                        },
                    }
                )
            )
            with (
                patch("scripts.audit_findings_freeze.verify", return_value={"status": "ok"}),
                patch(
                    "scripts.audit_findings_freeze.validate_v2_event_source_evidence_bundle",
                    return_value=(2, 2),
                ),
            ):
                checks = v2_event_source_certificate_checks(
                    summary_path,
                    exceptions_path,
                    certificate_path,
                    quality,
                )
        self.assertTrue(all(passed for _name, passed, _detail in checks), checks)

    def test_findings_gate_requires_current_exact_v3_event_certificate(self) -> None:
        release = Mock(
            artifact_paths=(
                Path("summary.parquet"),
                Path("exceptions.parquet"),
                Path("quarantine.parquet"),
                Path("certificate.json"),
            )
        )
        summary = pd.DataFrame()
        quarantine = pd.DataFrame()
        certificate = {"pool_count": 12}
        with (
            patch(
                "scripts.audit_findings_freeze.resolve_v3_event_source_release",
                return_value=release,
            ),
            patch(
                "scripts.audit_findings_freeze.read_v3_event_source_release",
                return_value=(summary, pd.DataFrame(), quarantine, certificate),
            ),
            patch("scripts.audit_findings_freeze.Path.is_file", return_value=True),
            patch(
                "scripts.audit_findings_freeze.verify", return_value={"status": "ok"}
            ),
            patch(
                "scripts.audit_findings_freeze.v3_audit_days",
                return_value=["20250115"],
            ),
            patch(
                "scripts.audit_findings_freeze.validate_v3_event_source_certificate",
                return_value=(1, 34),
            ) as validate,
            patch(
                "scripts.audit_findings_freeze.validate_v3_event_source_evidence_bundle",
                return_value=(12, 34),
            ) as reopen,
        ):
            checks = v3_event_source_certificate_checks()
        self.assertTrue(all(passed for _name, passed, _detail in checks), checks)
        validate.assert_called_once()
        reopen.assert_called_once_with(
            certificate, summary=summary, quarantine=quarantine
        )

    def test_live_json_contracts_have_unique_keys_and_a_current_lock_hash(self) -> None:
        import copy
        import hashlib
        import json

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON contract key: {key}")
                result[key] = value
            return result

        root = Path(__file__).resolve().parents[1]
        payloads = {
            path.name: json.loads(path.read_text(), object_pairs_hook=unique_object)
            for path in (root / "docs" / "specification-lock.json", root / "docs" / "model-ledger.json")
        }
        passed, detail = validate_specification_lock(payloads["specification-lock.json"])
        self.assertTrue(passed, detail)
        passed, detail = validate_specification_lock(
            payloads["specification-lock.json"],
            require_confirmatory=True,
        )
        self.assertFalse(passed, detail)
        self.assertIn("stage=design_seed", detail)
        premature = copy.deepcopy(payloads["specification-lock.json"])
        premature["claims"][0]["status"] = "registered_primary"
        premature["lock_hash"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in premature.items() if key != "lock_hash"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        passed, detail = validate_specification_lock(premature)
        self.assertFalse(passed, detail)
        self.assertIn("invalid_stage_statuses=['vehicle_transition']", detail)
        passed, detail = validate_model_ledger(
            payloads["model-ledger.json"],
            claim_ids=set(),
            lock_payload=payloads["specification-lock.json"],
        )
        self.assertTrue(passed, detail)
        passed, detail = validate_model_ledger(
            payloads["model-ledger.json"],
            claim_ids=set(),
            lock_payload=payloads["specification-lock.json"],
            require_confirmatory=True,
        )
        self.assertFalse(passed, detail)
        self.assertIn("confirmatory_context=invalid", detail)

    def test_route_cost_gate_checks_cell_semantics_and_formula(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route-cost.parquet"
            src = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
            tgt = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            vehicle = "0x6b175474e89094c44da98b954eedeac495271d0f"
            rows = []
            for hour in range(24):
                for size in (1_000.0, 10_000.0, 100_000.0):
                    direct = size * 0.99
                    indirect = size * 0.98
                    rows.append(
                        {
                            "date": "2025-01-01",
                            "method": "v2_cp_plus_v3_exact_tick",
                            "reserve_hour_utc": hour,
                            "src": src,
                            "tgt": tgt,
                            "vehicle": vehicle,
                            "trade_size_usd": size,
                            "direct_available": True,
                            "vehicle_available": True,
                            "direct_output_usd": direct,
                            "vehicle_output_usd": indirect,
                            "direct_cost_advantage": (direct - indirect) / direct,
                            "direct_source": "uniswap_v2",
                            "direct_pool": "direct",
                            "hop1_source": "uniswap_v2",
                            "hop1_pool": "hop1",
                            "hop2_source": "uniswap_v2",
                            "hop2_pool": "hop2",
                            "realized_bridge_volume_usd": 1_000_000.0,
                            "n_realized_routes": 20,
                        }
                    )
            pd.DataFrame(rows).to_parquet(path, index=False)
            with patch("scripts.audit_findings_freeze.verify", return_value={"status": "ok"}):
                checks = route_cost_panel_checks(path)
            self.assertTrue(all(passed for _name, passed, _detail in checks), checks)

            frame = pd.read_parquet(path)
            frame.loc[0, "direct_cost_advantage"] = -0.5
            frame.to_parquet(path, index=False)
            with patch("scripts.audit_findings_freeze.verify", return_value={"status": "ok"}):
                checks = route_cost_panel_checks(path)
            cost_check = next(check for check in checks if check[0].endswith("row semantics"))
            self.assertFalse(cost_check[1], checks)

    def test_cex_reference_gate_is_positive_exact_address_support(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cex.parquet"
            pd.DataFrame(
                [
                    {
                        "token_address": "0x" + "1" * 40,
                        "token_symbol": "ONE",
                        "dex_pool": "0x" + "a" * 40,
                        "binance_symbol": "ONEETH",
                        "binance_base_asset": "ONE",
                        "binance_quote_asset": "ETH",
                        "source_dex_creation_at": pd.Timestamp("2020-01-01"),
                        "binance_sample_first_at": pd.Timestamp("2020-02-01"),
                        "binance_sample_last_at": pd.Timestamp("2020-03-01"),
                        "binance_sample_rows": 2,
                        "support_definition": "positive_observed_uniswap_binance_reference_support",
                        "source_publication": "published source",
                    }
                ]
            ).to_parquet(path, index=False)
            with patch("scripts.audit_findings_freeze.verify", return_value={"status": "ok"}):
                checks = cex_reference_support_checks(
                    path,
                    expected_rows=1,
                    expected_sample_rows=2,
                )
            self.assertTrue(all(passed for _name, passed, _detail in checks), checks)

            frame = pd.read_parquet(path)
            frame.loc[0, "support_definition"] = "unlisted_when_absent"
            frame.to_parquet(path, index=False)
            with patch("scripts.audit_findings_freeze.verify", return_value={"status": "ok"}):
                checks = cex_reference_support_checks(
                    path,
                    expected_rows=1,
                    expected_sample_rows=2,
                )
            self.assertFalse(checks[-1][1])

    def test_v3_inventory_calendar_requires_exact_raw_rpc_identity(self) -> None:
        import json
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_root = root / "cuts"
            raw_root.mkdir()
            calendar = root / "calendar.parquet"
            day = "20250101"
            target = 1_735_776_000
            record = {
                "status": "complete",
                "day": day,
                "target_timestamp": target,
                "day_end_block": 100,
                "day_end_block_timestamp": target - 5,
                "next_block": 101,
                "next_block_timestamp": target + 7,
                "initial_lower_bracket": 90,
                "resolved_upper_bracket": 110,
                "rpc_evidence": [
                    {
                        "request": {
                            "method": "eth_getBlockByNumber",
                            "params": [hex(block), False],
                        },
                        "response": {
                            "number": hex(block),
                            "hash": f"0x{block}",
                            "parentHash": f"0x{block - 1}",
                            "timestamp": hex(
                                {
                                    90: target - 100,
                                    100: target - 5,
                                    101: target + 7,
                                    110: target + 100,
                                }[block]
                            ),
                        },
                    }
                    for block in (90, 100, 101, 110)
                ],
            }
            (raw_root / f"{day}.json").write_text(json.dumps(record))
            pd.DataFrame(
                [
                    {
                        key: value
                        for key, value in record.items()
                        if key not in {"rpc_evidence", "status"}
                    }
                ]
            ).to_parquet(calendar, index=False)
            with patch("scripts.audit_findings_freeze.verify", return_value={"status": "ok"}):
                checks = dict(
                    (name, (passed, detail))
                    for name, passed, detail in v3_inventory_calendar_checks(
                        calendar,
                        raw_root,
                        expected_days=[day],
                    )
                )
            self.assertTrue(all(passed for passed, _detail in checks.values()), checks)
            record["next_block_timestamp"] = target - 1
            (raw_root / f"{day}.json").write_text(json.dumps(record))
            with patch("scripts.audit_findings_freeze.verify", return_value={"status": "ok"}):
                checks = dict(
                    (name, (passed, detail))
                    for name, passed, detail in v3_inventory_calendar_checks(
                        calendar,
                        raw_root,
                        expected_days=[day],
                    )
                )
            self.assertFalse(checks["node D V3 inventory raw-to-panel identity"][0])
            self.assertFalse(checks["node D V3 inventory RPC evidence"][0])

    def test_every_canonical_venue_has_a_coherent_liquidity_contract(self) -> None:
        passed, detail = validate_liquidity_contracts()
        self.assertTrue(passed, detail)

    def test_capital_rows_are_bound_to_family_generation_quantity_and_source(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "venue": contract.venue,
                    "pool_family": contract.pool_family,
                    "invariant_family": contract.invariant_family,
                    "state_generation": contract.capability(
                        "deposited_capital"
                    ).state_generation,
                    "quantity_kind": "deposited_capital",
                    "capital_source": source,
                }
                for contract in LIQUIDITY_CONTRACTS.values()
                if contract.capital_ready
                for source in contract.capital_sources
            ]
        )
        passed, detail = validate_capital_contract_rows(rows)
        self.assertTrue(passed, detail)
        rows.loc[0, "state_generation"] = "wrong_generation"
        passed, detail = validate_capital_contract_rows(rows)
        self.assertFalse(passed)
        self.assertIn("unsupported", detail)

    def test_quote_state_rows_are_bound_to_family_invariant_and_generation(self) -> None:
        rows = pd.DataFrame(
            [
                {
                    "venue": "uniswap_v3",
                    "pool_family": "concentrated_liquidity",
                    "invariant_family": "concentrated_liquidity",
                    "state_generation": "uniswap_v3_tick_state_v2",
                    "quote_supported": True,
                },
                {
                    "venue": "curve",
                    "pool_family": "ng_or_unclassified",
                    "invariant_family": "ng_or_unclassified",
                    "state_generation": "curve_multi_asset_state_v2",
                    "quote_supported": False,
                },
            ]
        )
        passed, detail = validate_quote_state_contract_rows(rows)
        self.assertTrue(passed, detail)
        rows.loc[1, "quote_supported"] = True
        passed, detail = validate_quote_state_contract_rows(rows)
        self.assertFalse(passed)
        self.assertIn("unsupported quote admitted", detail)

    def test_primary_technical_card_may_resolve_to_a_source_note(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "literature" / "source-notes" / "2021-Protocol.md"
            note.parent.mkdir(parents=True)
            note.write_text("Versioned protocol code and archive identity checked.")
            with patch("scripts.audit_findings_freeze.ROOT", root):
                self.assertEqual(
                    card_source_evidence_text(
                        {"source": "literature/source-notes/2021-Protocol.md"}
                    ),
                    "Versioned protocol code and archive identity checked.",
                )

    def test_source_admission_requires_complete_decision_for_every_source(self) -> None:
        record = {
            "key": "Technical",
            "title": "Protocol mechanics",
            "decision": "include_primary_technical",
            "publication_class": "primary_technical",
            "publication_status": "official protocol whitepaper",
            "author_field_credibility": "protocol authors",
            "scholarly_uptake": "widely used technical reference",
            "finance_relevance": "contract mechanics only",
            "evidence_role": "primary technical source",
            "boundary": "cannot support behaviour or economic mechanisms",
            "technical_integrity": "mechanics checked against deployed contract documentation",
            "rationale": "the contract specification is the primary source for its arithmetic",
            "supporting_source_version": "version 1.0 whitepaper",
            "finance_native": False,
            "reviewed_at": "2026-08-09",
        }
        passed, detail = validate_source_admission(
            {"Published", "Technical"},
            {
                "schema_version": "1.0.0",
                "admitted_records": [
                    {
                        **record,
                        "key": "Published",
                        "decision": "include_scholarly",
                        "publication_class": "peer_reviewed_finance_economics",
                    },
                    record,
                ],
                "rejected_or_retired_candidates": [],
            },
        )
        self.assertTrue(passed, detail)
        passed, detail = validate_source_admission(
            {"Published", "Technical", "Working"},
            {
                "schema_version": "1.0.0",
                "admitted_records": [
                    {
                        **record,
                        "key": "Published",
                        "decision": "include_scholarly",
                        "publication_class": "peer_reviewed_finance_economics",
                    },
                    record,
                ],
                "rejected_or_retired_candidates": [],
            },
        )
        self.assertFalse(passed)
        self.assertIn("Working", detail)
        rejected = {**record, "decision": "exclude"}
        passed, detail = validate_source_admission(
            {"Technical"},
            {
                "schema_version": "1.0.0",
                "admitted_records": [],
                "rejected_or_retired_candidates": [
                    {
                        **rejected,
                        "red_flags": ["claim mismatch"],
                        "reentry_condition": "a verified role emerges",
                    }
                ],
            },
        )
        self.assertFalse(passed)
        self.assertIn("rejected=['Technical']", detail)
        incompatible = {**record, "publication_class": "working_paper"}
        passed, detail = validate_source_admission(
            {"Technical"},
            {
                "schema_version": "1.0.0",
                "admitted_records": [incompatible],
                "rejected_or_retired_candidates": [],
            },
        )
        self.assertFalse(passed)
        self.assertIn("incompatible=['Technical']", detail)

    def test_refresh_log_path_flattens_script_subdirectories(self) -> None:
        self.assertEqual(
            refresher.stage_log_path("process/build_route_transaction_gas.py").name,
            "process__build_route_transaction_gas.py.log",
        )

    @patch("scripts.refresh_panel_dependents.os.killpg")
    def test_refresh_timeout_terminates_then_kills_worker_group(self, killpg) -> None:
        process = Mock(pid=123)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("stage", 10), 0]
        refresher.terminate_process_group(process)
        self.assertEqual(
            killpg.call_args_list,
            [
                call(123, refresher.signal.SIGTERM),
                call(123, refresher.signal.SIGKILL),
            ],
        )

    @patch("scripts.refresh_panel_dependents.terminate_process_group")
    @patch("scripts.refresh_panel_dependents.subprocess.Popen")
    def test_refresh_interrupt_cleans_up_worker_group(self, popen, terminate) -> None:
        process = popen.return_value
        process.wait.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            refresher.run_stage(["stage"], log=Mock(), env={}, timeout=10)
        terminate.assert_called_once_with(process)

    def test_d3_refresh_owns_every_stale_canonical_claim_input(self) -> None:
        outputs = {
            output
            for _script, _args, _why, stage_outputs in CLAIM_INPUT_STAGES
            for output in stage_outputs
        }
        self.assertEqual(
            outputs,
            {
                "data/processed/cex_reference_support.parquet",
                "data/processed/counterfactual_dominance.parquet",
                "data/processed/counterfactual_dominance_gross.parquet",
                "data/processed/cross_venue_routing_daily.parquet",
                "data/processed/ethereum_utc_day_calendar.parquet",
                "data/processed/intermediation_by_type_daily.parquet",
                "data/processed/lp_liquidity_flow_candidates_v3.parquet",
                "data/processed/lp_liquidity_flow_events_v3.parquet",
                "data/processed/lp_liquidity_flow_daily_v3.parquet",
                "data/processed/lp_liquidity_flow_rejections_v3.parquet",
                "data/processed/pool_candidate_capital_daily.parquet",
                "data/processed/pool_capital_daily.parquet",
                "data/processed/pool_capital_rejections.parquet",
                "data/processed/rent_incidence_v2_pool_day.parquet",
                "data/processed/routing_maturation_cell_day.parquet",
                "data/processed/routing_maturation_exact_horizons.parquet",
                "data/processed/routing_transition_cells.parquet",
                "data/processed/route_gas_units.parquet",
                "data/processed/route_transaction_gas.parquet",
                "data/processed/token_price_daily.parquet",
                "data/processed/vehicle_centrality_dense.parquet",
                "data/processed/vehicle_excess_use_daily.parquet",
            },
        )
        self.assertEqual(len(DAILY_FRONTIER_PREREQUISITES), 3)
        self.assertFalse(
            any("run_" in script for script, _args, _why, _outputs in CLAIM_INPUT_STAGES)
        )

    def test_claim_input_gate_rejects_raw_missing_and_stale_inputs(self) -> None:
        import tempfile
        from pathlib import Path

        payload = {
            "stage": "confirmatory",
            "claims": [
                {
                    "id": "live",
                    "status": "registered_primary",
                    "execution_gate": "open",
                    "inputs": ["data/processed/clean.parquet"],
                },
                {
                    "id": "blocked",
                    "status": "registered_companion",
                    "execution_gate": "blocked_external_reference_variance",
                    "inputs": ["data/processed/missing-blocked.parquet"],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clean = root / "data" / "processed" / "clean.parquet"
            clean.parent.mkdir(parents=True)
            clean.touch()
            passed, detail = validate_claim_input_layer(
                payload,
                root=root,
                verifier=lambda _path: {"status": "ok"},
            )
            self.assertTrue(passed, detail)
            payload["claims"][0].pop("execution_gate")
            passed, detail = validate_claim_input_layer(
                payload,
                root=root,
                verifier=lambda _path: {"status": "ok"},
            )
            self.assertFalse(passed, detail)
            self.assertIn("must explicitly declare", detail)
            payload["claims"][0]["execution_gate"] = "open"
            passed, _detail = validate_claim_input_layer(
                payload,
                root=root,
                verifier=lambda _path: {"status": "stale"},
            )
            self.assertFalse(passed)
            payload["claims"][0]["inputs"] = ["data/raw/provider.jsonl"]
            passed, _detail = validate_claim_input_layer(payload, root=root)
            self.assertFalse(passed)

    def test_registered_consumers_cover_active_claim_and_model_producers(self) -> None:
        consumers = set(registered_empirical_consumers())
        self.assertIn("scripts/build_intermediation_by_type.py", consumers)
        self.assertIn("scripts/run_rent_incidence.py", consumers)
        self.assertIn("scripts/test_block_vs_hour_verdict.py", consumers)

    def test_market_state_perimeter_is_the_full_genesis_clamped_calendar(self) -> None:
        keys = expected_market_state_keys()
        self.assertEqual(len(keys), 11_009)
        self.assertIn(("tick", "uniswap_v4", "20250124"), keys)
        self.assertNotIn(("tick", "uniswap_v4", "20250123"), keys)
        self.assertIn(("constant_product", "uniswap_v2", "20260630"), keys)

    def test_directed_route_perimeter_keeps_empty_days_and_all_eight_venues(self) -> None:
        self.assertEqual(expected_unified_route_venue_days(), 12_802)
        days = pd.date_range("2020-02-11", "2026-06-30", freq="D").strftime("%Y%m%d")
        expected_sources = []
        from ddvc.reconstruct import DEX_FAMILY, active_route_sources

        for day in days:
            expected_sources.append(len(active_route_sources(day, list(DEX_FAMILY))))
        quality = pd.DataFrame(
            {
                "day": days,
                "expected_sources": expected_sources,
                "missing_sources": 0,
                "conflicting_events": 0,
                "malformed_rows": 0,
                "passed": True,
            }
        )
        passed, detail = validate_unified_route_layer(quality, provenance_status="ok")
        self.assertTrue(passed, detail)
        quality = quality.iloc[1:].copy()
        passed, _detail = validate_unified_route_layer(quality, provenance_status="ok")
        self.assertFalse(passed)

    def test_active_empirical_consumers_cannot_parse_raw_provider_files(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            clean = Path(directory) / "clean.py"
            raw = Path(directory) / "raw.py"
            imported_raw = Path(directory) / "imported_raw.py"
            clean.write_text("from ddvc.state_data import read_tick_partition\n")
            raw.write_text('with gzip.open(ROOT / "data/raw/thegraph/x"):\n    pass\n')
            imported_raw.write_text("from ddvc.fetch.raw import raw_path\n")
            clean_relative = str(clean.relative_to(Path.cwd()))
            raw_relative = str(raw.relative_to(Path.cwd()))
            imported_raw_relative = str(imported_raw.relative_to(Path.cwd()))
            passed, detail = validate_canonical_consumer_boundary((clean_relative,))
            self.assertTrue(passed, detail)
            passed, detail = validate_canonical_consumer_boundary((raw_relative,))
            self.assertFalse(passed, detail)
            passed, detail = validate_canonical_consumer_boundary((imported_raw_relative,))
            self.assertFalse(passed, detail)

    def test_model_ledger_keeps_exploration_open_but_not_admissible(self) -> None:
        exploratory = {
            "family_id": "discovery",
            "run_id": "pending",
            "claim_id": "unregistered_discovery_question",
            "lane": "exploratory",
            "lifecycle": "executed",
            "disposition": "diagnostic",
            "selection_origin": None,
            "promoted_from_run_id": None,
            "decision_id": None,
            "d3_generation": "d3-generation",
            "exploration_generation": None,
            "lock_hash": None,
            "plan_hash": "exploratory-plan",
            "engine_hash": "engine",
            "estimator": "OLS",
            "fixed_effects": "open",
            "inference": "open",
            "artifacts": [
                {
                    "path": "output/discovery.jsonl",
                    "role": "result",
                    "sha256": "0" * 64,
                    "provenance_path": "output/discovery.jsonl.prov.json",
                    "spec_ids": ["explore-1"],
                }
            ],
            "note": "open-ended discovery",
        }
        _bind_exploratory_plan(exploratory)
        payload = {
            "schema_version": 2,
            "current_analysis_generation": "d3-generation",
            "exploration": {
                "status": "in_progress",
                "d3_generation": "d3-generation",
                "d3_certificate": "docs/d3-analysis-release.json",
                "generation": None,
                "certificate": None,
                "started_at": "2026-08-10T10:00:00Z",
                "completed_at": None,
            },
            "legacy_families": [
                {
                    "id": "legacy",
                    "claim_id": "legacy",
                    "estimator": "OLS",
                    "fixed_effects": "none",
                    "inference": "robust",
                    "substantive_specifications": 1,
                    "diagnostic_specifications": 0,
                    "resampling_refits": 0,
                    "status": "retired",
                    "artifacts": [],
                    "note": "historical",
                }
            ],
            "runs": [exploratory],
        }
        passed, detail = validate_model_ledger(
            payload,
            claim_ids=set(),
            verify_artifacts=False,
            verify_certificates=False,
        )
        self.assertTrue(passed, detail)
        payload["runs"][0]["disposition"] = "admissible"
        passed, detail = validate_model_ledger(
            payload,
            claim_ids=set(),
            verify_artifacts=False,
            verify_certificates=False,
        )
        self.assertFalse(passed, detail)
        self.assertIn("exploratory_admissible", detail)
        payload["runs"][0]["disposition"] = "diagnostic"
        payload["runs"][0]["lane"] = "confirmatory"
        passed, detail = validate_model_ledger(
            payload,
            claim_ids=set(),
            verify_artifacts=False,
            verify_certificates=False,
        )
        self.assertFalse(passed, detail)
        self.assertIn("run_id", detail)

    def test_model_run_identity_binds_claim_and_selection_history(self) -> None:
        run = {
            "family_id": "family",
            "claim_id": "claim",
            "lane": "confirmatory",
            "selection_origin": "exploratory_discovery",
            "promoted_from_run_id": "source",
            "decision_id": "decision",
            "d3_generation": "d3",
            "exploration_generation": "e0",
            "lock_hash": "lock",
            "plan_hash": "plan",
            "engine_hash": "engine",
        }
        original = model_run_id(run)
        for field in ("claim_id", "selection_origin", "promoted_from_run_id", "decision_id"):
            changed = dict(run)
            changed[field] = f"different-{field}"
            self.assertNotEqual(model_run_id(changed), original, field)

    def test_confirmatory_promotion_requires_exact_promote_decision_and_distinct_execution(self) -> None:
        import copy

        source = {
            "run_id": "exploratory-run",
            "lane": "exploratory",
            "lifecycle": "executed",
            "plan_hash": "exploratory-plan",
            "engine_hash": "shared-engine",
            "artifacts": [{"path": "output/exploratory.jsonl", "sha256": "1" * 64}],
        }
        confirmation = {
            "run_id": "confirmatory-run",
            "lane": "confirmatory",
            "claim_id": "promoted-claim",
            "selection_origin": "exploratory_discovery",
            "promoted_from_run_id": source["run_id"],
            "decision_id": "decision-promote",
            "plan_hash": "registered-e1-plan",
            "engine_hash": "shared-engine",
            "artifacts": [{"path": "output/confirmatory.jsonl", "sha256": "2" * 64}],
        }
        certificate = {
            "exploratory_run_ids": [source["run_id"]],
            "triage_decisions": [
                {
                    "decision_id": "decision-promote",
                    "run_id": source["run_id"],
                    "outcome": "promote",
                    "proposed_claim_id": confirmation["claim_id"],
                    "required_reopen_nodes": ["C", "E1"],
                }
            ],
        }
        errors, certificate_errors = confirmatory_promotion_errors([source, confirmation], certificate)
        self.assertEqual(errors, {})
        self.assertEqual(certificate_errors, [])

        for outcome in ("reject", "retain_auxiliary", "park_next_paper"):
            changed = copy.deepcopy(certificate)
            changed["triage_decisions"][0]["outcome"] = outcome
            errors, _certificate_errors = confirmatory_promotion_errors([source, confirmation], changed)
            self.assertIn("promotion_decision", errors[confirmation["run_id"]])

        for field, value in (
            ("decision_id", "different-decision"),
            ("proposed_claim_id", "different-claim"),
            ("required_reopen_nodes", ["C"]),
        ):
            changed_confirmation = copy.deepcopy(confirmation)
            changed_certificate = copy.deepcopy(certificate)
            if field == "decision_id":
                changed_confirmation[field] = value
            else:
                changed_certificate["triage_decisions"][0][field] = value
            errors, _certificate_errors = confirmatory_promotion_errors(
                [source, changed_confirmation], changed_certificate
            )
            self.assertIn("promotion_decision", errors[confirmation["run_id"]])

        same_plan = {**confirmation, "plan_hash": source["plan_hash"]}
        errors, _certificate_errors = confirmatory_promotion_errors([source, same_plan], certificate)
        self.assertIn("confirmation_plan_not_distinct", errors[confirmation["run_id"]])
        same_path = copy.deepcopy(confirmation)
        same_path["artifacts"][0]["path"] = source["artifacts"][0]["path"]
        errors, _certificate_errors = confirmatory_promotion_errors([source, same_path], certificate)
        self.assertIn("confirmation_artifact_path_not_distinct", errors[confirmation["run_id"]])
        same_content = copy.deepcopy(confirmation)
        same_content["artifacts"][0]["sha256"] = source["artifacts"][0]["sha256"]
        errors, _certificate_errors = confirmatory_promotion_errors([source, same_content], certificate)
        self.assertIn("confirmation_artifact_content_not_distinct", errors[confirmation["run_id"]])

    def test_model_ledger_requires_distinct_complete_confirmatory_rerun(self) -> None:
        registered_specifications = [
            {
                "spec_id": "primary-null",
                "kind": "primary",
                "parameters": {"outcome": "share"},
                "covers": ["mandatory_alternatives/weighting/0", "falsifier"],
            },
            {
                "spec_id": "weighting-alternative",
                "kind": "alternative",
                "parameters": {"weighting": "value"},
                "covers": ["mandatory_alternatives/weighting/1"],
            },
        ]
        plan_hash = canonical_hash(registered_specifications)
        lock = {
            "stage": "confirmatory",
            "lock_hash": "lock-hash",
            "d3_generation": "d3-generation",
            "d3_certificate": "data/manifests/analysis-release.json",
            "exploration_generation": "e0-generation",
            "exploration_certificate": "docs/e0-exploration-certificate.json",
            "claims": [
                {
                    "id": "lead",
                    "status": "registered_primary",
                    "execution_gate": "open",
                    "plan_hash": plan_hash,
                    "registered_specifications": registered_specifications,
                }
            ],
        }
        exploratory = {
            "family_id": "lead-discovery",
            "run_id": "pending",
            "claim_id": "lead-discovery",
            "lane": "exploratory",
            "lifecycle": "executed",
            "disposition": "diagnostic",
            "selection_origin": None,
            "promoted_from_run_id": None,
            "decision_id": None,
            "d3_generation": "d3-generation",
            "exploration_generation": None,
            "lock_hash": None,
            "plan_hash": "exploration-plan",
            "engine_hash": "engine",
            "estimator": "OLS",
            "fixed_effects": "candidate",
            "inference": "candidate",
            "artifacts": [
                {
                    "path": "output/exploratory.jsonl",
                    "role": "result",
                    "sha256": "1" * 64,
                    "provenance_path": "output/exploratory.jsonl.prov.json",
                    "spec_ids": ["discovery-fit"],
                }
            ],
            "note": "publication-worthy discovery",
        }
        _bind_exploratory_plan(exploratory)
        confirmatory = {
            "family_id": "lead",
            "run_id": "pending",
            "claim_id": "lead",
            "lane": "confirmatory",
            "lifecycle": "executed",
            "disposition": "admissible",
            "selection_origin": "exploratory_discovery",
            "promoted_from_run_id": exploratory["run_id"],
            "decision_id": "e1-decision-lead",
            "d3_generation": "d3-generation",
            "exploration_generation": "e0-generation",
            "lock_hash": "lock-hash",
            "plan_hash": plan_hash,
            "engine_hash": "engine",
            "estimator": "OLS",
            "fixed_effects": "pair and date",
            "inference": "pair clustered",
            "artifacts": [
                {
                    "path": "output/confirmatory.jsonl",
                    "role": "result",
                    "sha256": "2" * 64,
                    "provenance_path": "output/confirmatory.jsonl.prov.json",
                    "spec_ids": ["primary-null", "weighting-alternative"],
                }
            ],
            "note": "the registered result is null and remains admissible",
        }
        confirmatory["run_id"] = model_run_id(confirmatory)
        payload = {
            "schema_version": 2,
            "current_analysis_generation": "d3-generation",
            "exploration": {
                "status": "complete",
                "d3_generation": "d3-generation",
                "d3_certificate": "data/manifests/analysis-release.json",
                "generation": "e0-generation",
                "certificate": "docs/e0-exploration-certificate.json",
                "started_at": "2026-08-10T10:00:00Z",
                "completed_at": "2026-08-10T12:00:00Z",
            },
            "legacy_families": [
                {
                    "id": "legacy",
                    "claim_id": "legacy",
                    "estimator": "OLS",
                    "fixed_effects": "none",
                    "inference": "robust",
                    "substantive_specifications": 1,
                    "diagnostic_specifications": 0,
                    "resampling_refits": 0,
                    "status": "retired",
                    "artifacts": [],
                    "note": "historical",
                }
            ],
            "runs": [exploratory, confirmatory],
        }
        passed, detail = validate_model_ledger(
            payload,
            claim_ids={"lead"},
            lock_payload=lock,
            require_confirmatory=True,
            verify_artifacts=False,
            verify_certificates=False,
        )
        self.assertTrue(passed, detail)
        passed, detail = validate_model_ledger(
            payload,
            claim_ids={"lead"},
            lock_payload=lock,
            require_confirmatory=True,
            verify_artifacts=False,
        )
        self.assertFalse(passed, detail)
        self.assertIn("d3_analysis_release_missing", detail)

        confirmatory["artifacts"][0]["spec_ids"] = ["primary-null"]
        passed, detail = validate_model_ledger(
            payload,
            claim_ids={"lead"},
            lock_payload=lock,
            require_confirmatory=True,
            verify_artifacts=False,
            verify_certificates=False,
        )
        self.assertFalse(passed, detail)
        self.assertIn("specification_coverage", detail)
        confirmatory["artifacts"][0]["spec_ids"] = [
            "primary-null",
            "weighting-alternative",
        ]

        confirmatory["promoted_from_run_id"] = None
        passed, detail = validate_model_ledger(
            payload,
            claim_ids={"lead"},
            lock_payload=lock,
            require_confirmatory=True,
            verify_artifacts=False,
            verify_certificates=False,
        )
        self.assertFalse(passed, detail)
        self.assertIn("promotion_source", detail)

    def test_model_ledger_verifies_current_artifact_content_and_provenance(self) -> None:
        with tempfile.NamedTemporaryFile(dir=Path.cwd(), suffix=".jsonl", delete=False) as handle:
            handle.write(b'{"spec_id":"explore-1","estimate":0.0}\n')
            artifact_path = Path(handle.name)
        provenance_path = sidecar_path(artifact_path)
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        provenance_path.write_text("{}\n")
        try:
            relative_artifact = str(artifact_path.relative_to(Path.cwd()))
            relative_provenance = str(provenance_path.relative_to(Path.cwd()))
            run = {
                "family_id": "discovery",
                "run_id": "pending",
                "claim_id": "discovery",
                "lane": "exploratory",
                "lifecycle": "executed",
                "disposition": "diagnostic",
                "selection_origin": None,
                "promoted_from_run_id": None,
                "decision_id": None,
                "d3_generation": "d3-generation",
                "exploration_generation": None,
                "lock_hash": None,
                "plan_hash": "exploratory-plan",
                "engine_hash": "engine",
                "estimator": "OLS",
                "fixed_effects": "open",
                "inference": "open",
                "artifacts": [
                    {
                        "path": relative_artifact,
                        "role": "result",
                        "sha256": portable_content_sha256(artifact_path),
                        "provenance_path": relative_provenance,
                        "spec_ids": ["explore-1"],
                    }
                ],
                "note": "artifact verification",
            }
            _bind_exploratory_plan(run)
            payload = {
                "schema_version": 2,
                "current_analysis_generation": "d3-generation",
                "exploration": {
                    "status": "in_progress",
                    "d3_generation": "d3-generation",
                    "d3_certificate": "docs/d3-analysis-release.json",
                    "generation": None,
                    "certificate": None,
                    "started_at": "2026-08-10T10:00:00Z",
                    "completed_at": None,
                },
                "legacy_families": [
                    {
                        "id": "legacy",
                        "claim_id": "legacy",
                        "estimator": "OLS",
                        "fixed_effects": "none",
                        "inference": "robust",
                        "substantive_specifications": 1,
                        "diagnostic_specifications": 0,
                        "resampling_refits": 0,
                        "status": "retired",
                        "artifacts": [],
                        "note": "historical",
                    }
                ],
                "runs": [run],
            }
            passed, detail = validate_model_ledger(
                payload,
                claim_ids=set(),
                verifier=lambda _path: {"status": "ok"},
                verify_certificates=False,
            )
            self.assertTrue(passed, detail)
            run["artifacts"][0]["sha256"] = "f" * 64
            passed, detail = validate_model_ledger(
                payload,
                claim_ids=set(),
                verifier=lambda _path: {"status": "ok"},
                verify_certificates=False,
            )
            self.assertFalse(passed, detail)
            self.assertIn("artifact_hash", detail)
        finally:
            artifact_path.unlink(missing_ok=True)
            provenance_path.unlink(missing_ok=True)

    def test_transaction_frontier_gate_separates_validation_from_calendar(self) -> None:
        support = pd.DataFrame(
            {
                "day": ["20250615"],
                "scored_routes": [100],
                "rejected_routes": [1],
                "exact_venue_two_leg_routes": [101],
                "invalid_realised_input": [0],
                "invalid_realised_output": [0],
                "invalid_chosen_output": [0],
                "within_20pct_chosen_quote_eligible_routes": [101],
                "within_20pct_chosen_quote_available": [101],
                "within_20pct_chosen_output_mismatch": [1],
                "chosen_validation_tolerance_bps": [1.0],
            }
        )
        checks = {
            name: (passed, detail)
            for name, passed, detail in transaction_frontier_support_checks(
                support,
                panel_rows=100,
                rejection_rows=1,
            )
        }
        self.assertTrue(checks["transaction frontier row contract"][0])
        self.assertTrue(checks["transaction frontier chosen-state support"][0])
        self.assertTrue(checks["transaction frontier chosen-output validation"][0])
        self.assertFalse(checks["transaction frontier audit-day coverage"][0])
        support["chosen_validation_tolerance_bps"] = 100.0
        checks = {
            name: (passed, detail)
            for name, passed, detail in transaction_frontier_support_checks(
                support,
                panel_rows=100,
                rejection_rows=1,
            )
        }
        self.assertFalse(checks["transaction frontier chosen-output validation"][0])

    def test_daily_frontier_gate_requires_all_artifacts_and_full_calendar(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            panel = root / "daily.parquet"
            rejections = root / "daily_rejections.parquet"
            support = root / "daily_support.parquet"
            pd.DataFrame({"day": ["20200211"], "route_id": ["accepted"]}).to_parquet(
                panel, index=False
            )
            pd.DataFrame({"day": ["20200211"], "route_id": ["rejected"]}).to_parquet(
                rejections, index=False
            )
            pd.DataFrame(
                {
                    "day": ["20200211"],
                    "scored_routes": [1],
                    "rejected_routes": [1],
                    "exact_venue_two_leg_routes": [2],
                    "invalid_realised_input": [0],
                    "invalid_realised_output": [0],
                    "invalid_chosen_output": [0],
                    "within_20pct_chosen_quote_eligible_routes": [1],
                    "within_20pct_chosen_quote_available": [1],
                    "within_20pct_chosen_output_mismatch": [0],
                    "chosen_validation_tolerance_bps": [1.0],
                }
            ).to_parquet(support, index=False)
            with patch(
                "scripts.audit_findings_freeze.verify",
                return_value={"status": "ok"},
            ):
                checks = {
                    name: (passed, detail)
                    for name, passed, detail in transaction_frontier_artifact_checks(
                        panel,
                        rejections,
                        support,
                        prefix="transaction frontier daily",
                        coverage_label="calendar",
                        expected_days=1,
                        first_day="20200211",
                        last_day="20200211",
                    )
                }
            self.assertTrue(checks["transaction frontier daily provenance current"][0])
            self.assertTrue(checks["transaction frontier daily row contract"][0])
            self.assertTrue(checks["transaction frontier daily chosen-state support"][0])
            self.assertTrue(checks["transaction frontier daily calendar coverage"][0])
            support.unlink()
            missing = transaction_frontier_artifact_checks(
                panel,
                rejections,
                support,
                prefix="transaction frontier daily",
                coverage_label="calendar",
                expected_days=1,
                first_day="20200211",
                last_day="20200211",
            )
            self.assertEqual(missing[0][0], "transaction frontier daily exists")
            self.assertFalse(missing[0][1])

    def test_literature_gate_requires_individual_verified_cards(self) -> None:
        text = """---
status: complete
---

### PaperA
- Status: claim-verified
- Roles: central, mechanism
- Source: literature/papers/paper-a.pdf
- Source key: PaperA
- Version: Journal version, 2020
- Companions: Complete: Internet Appendix saved and read with the main article
- Uses: Contribution and mechanism claims in sections 1 and 3
- Scientific: Identifies the mechanism with a panel design and states its limits
- Structure: Motivation, model, design, results, mechanisms, and robustness
- Depth: Concentrates detail in identification and mechanism validation
- Breadth: Covers two mechanisms and rules out the leading alternative
- Optics: Calibrated title, early result preview, and a compact exhibit hierarchy
- Locations: Sections 1 and 4, pages 2 and 18, Table 3
- Implication: Lead with the priced counterfactual and keep descriptive breadth subordinate
- First reader: Reader A
- Independent: complete

### venue:one
- Status: full-text-read
- Roles: venue
- Source: literature/venue/paper-one.pdf
- Source key: PaperOne
- Version: Published JFE version, 2021
- Companions: None: no appendix, supplement, correction, or data appendix found in the article, DOI page, or author page
- Uses: Venue structure and presentation benchmark
- Scientific: Uses a focused finance question and a design matched to the claim
- Structure: Introduction, setting, design, results, channels, and conclusion
- Depth: Gives the main design and two robustness families most of the space
- Breadth: Addresses the principal rival while keeping external scope bounded
- Optics: Short title, two-page opening, early main table, and restrained claims
- Locations: Pages 1 to 5 and 18 to 24, Tables 2 and 5
- Implication: Put the lead estimate early and move diagnostics behind the main table
- First reader: Reader B
- Independent: pending
"""
        cards = parse_literature_cards(text)
        self.assertEqual(cards["PaperA"]["status"], "claim-verified")
        passed, detail = validate_literature_audit(
            text, {"PaperA"}, {"venue:one"}
        )
        self.assertTrue(passed, detail)
        self.assertTrue(complete_literature_card(cards["PaperA"]))
        self.assertTrue(companion_sources_closed(cards["PaperA"]))
        self.assertTrue(published_venue_version(cards["venue:one"]))
        working_only = text.replace(
            "Version: Published JFE version, 2021",
            "Version: Revised working paper, 2021; later published in JFE",
        )
        passed, detail = validate_literature_audit(
            working_only, {"PaperA"}, {"venue:one"}
        )
        self.assertFalse(passed, detail)
        missing_optics = text.replace(
            "- Optics: Calibrated title, early result preview, and a compact exhibit hierarchy\n",
            "",
            1,
        )
        passed, detail = validate_literature_audit(
            missing_optics, {"PaperA"}, {"venue:one"}
        )
        self.assertFalse(passed, detail)
        missing_companion = text.replace(
            "- Companions: Complete: Internet Appendix saved and read with the main article\n",
            "",
            1,
        )
        passed, detail = validate_literature_audit(
            missing_companion, {"PaperA"}, {"venue:one"}
        )
        self.assertFalse(passed, detail)
        unresolved_companion = text.replace(
            "Companions: Complete: Internet Appendix saved and read with the main article",
            "Companions: Missing: Internet Appendix cited but not retrieved",
            1,
        )
        passed, detail = validate_literature_audit(
            unresolved_companion, {"PaperA"}, {"venue:one"}
        )
        self.assertFalse(passed, detail)
        passed, _detail = validate_literature_audit(
            text.replace("Independent: complete", "Independent: pending"),
            {"PaperA"},
            {"venue:one"},
        )
        self.assertFalse(passed)

    def test_companion_gate_requires_registered_materialized_keys(self) -> None:
        fields = {
            "companions": "Complete: appendix `PaperAAppendix` saved and read",
        }
        self.assertEqual(companion_source_keys(fields), {"PaperAAppendix"})
        self.assertTrue(
            companion_sources_closed(
                fields,
                materialized={"PaperAAppendix": True},
                source_text="Main article text",
            )
        )
        self.assertFalse(
            companion_sources_closed(
                fields,
                materialized={"PaperAAppendix": False},
                source_text="Main article text",
            )
        )
        self.assertFalse(
            companion_sources_closed(
                {"companions": "Complete: appendix saved and read"},
                materialized={},
                source_text="Main article text",
            )
        )
        self.assertFalse(
            companion_sources_closed(
                fields,
                materialized={"PaperAAppendix": True},
            )
        )
        self.assertFalse(
            companion_sources_closed(
                {"companions": "None: DOI and author pages checked"},
                source_text="Results are reported in the Online Appendix.",
            )
        )
        self.assertFalse(
            companion_sources_closed(
                {"companions": "None: DOI and author pages checked"},
                source_text="Supplementary material associated with this article can be found online.",
            )
        )
        self.assertTrue(
            companion_sources_closed(
                {"companions": "None: DOI and author pages checked"},
                source_text="The exchange rule refers to Supplementary Material .05 of Rule 104.",
            )
        )

    def test_literature_use_policy_catches_claim_conflicts_and_vocabulary_absence(self) -> None:
        import tempfile

        policy = {
            "schema_version": 1,
            "method_absence_rule": "absence_never_prohibits_without_explicit_source_prohibition",
            "vocabulary_absence_rule": "configured_absence_prohibits",
            "claim_use_contracts": [
                {
                    "id": "paper-a-boundary",
                    "source_key": "PaperA",
                    "evidence_field": "uses",
                    "evidence_pattern": "does not license the estimator",
                    "prohibited_pattern": "licenses the estimator",
                    "reason": "The card expressly withholds that use.",
                }
            ],
            "vocabulary_contracts": [
                {
                    "id": "succession-usage",
                    "term": "succession",
                    "publication_classes": ["peer_reviewed_finance_economics"],
                    "minimum_documents": 2,
                    "reason": "The configured corpus does not use the term.",
                }
            ],
        }
        passed, detail = validate_literature_use_contracts(policy)
        self.assertTrue(passed, detail)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manuscript = root / "paper.tex"
            manuscript.write_text(
                "This source licenses the estimator \\citep{PaperA}. "
                "The method is novel, and the episode is a succession."
            )
            text_root = root / "text"
            text_root.mkdir()
            (text_root / "2020-PaperA-main.txt").write_text("transition and estimator")
            (text_root / "2021-PaperB-main.txt").write_text("currency displacement")
            admission = {
                "admitted_records": [
                    {"key": "PaperA", "publication_class": "peer_reviewed_finance_economics"},
                    {"key": "PaperB", "publication_class": "peer_reviewed_finance_economics"},
                ]
            }
            claim, vocabulary = literature_use_contract_violations(
                policy,
                cards={"PaperA": {"uses": "This source does not license the estimator."}},
                manuscript_paths=[manuscript],
                admission_ledger=admission,
                text_root=text_root,
            )
            self.assertEqual(claim, ["paper-a-boundary:paper.tex"])
            self.assertEqual(vocabulary, ["succession-usage:paper=1,corpus=0/2"])
            self.assertNotIn("method", " ".join(claim + vocabulary))

        weakened = {
            **policy,
            "method_absence_rule": "absence_prohibits",
        }
        passed, _detail = validate_literature_use_contracts(weakened)
        self.assertFalse(passed)

    def test_live_companion_gate_requires_auditable_discovery_record(self) -> None:
        fields = {
            "source key": "PaperA",
            "companions": "Complete: appendix `PaperAAppendix` saved and read",
        }
        complete = {
            "status": "complete",
            "main": "PaperA",
            "checks": {
                "article": "tracked full text checked",
                "publisher_or_doi": "DOI landing page checked",
                "author_or_repository": "author publication page checked",
            },
            "companions": ["PaperAAppendix"],
        }
        materialized = {"PaperA": True, "PaperAAppendix": True}
        self.assertTrue(source_set_record_closed(complete, materialized))
        self.assertTrue(
            companion_sources_closed(
                fields,
                materialized=materialized,
                source_text="Main article text",
                source_set=complete,
            )
        )
        for missing_check in complete["checks"]:
            incomplete = {**complete, "checks": {**complete["checks"], missing_check: ""}}
            self.assertFalse(
                companion_sources_closed(
                    fields,
                    materialized=materialized,
                    source_text="Main article text",
                    source_set=incomplete,
                )
            )
        self.assertFalse(
            companion_sources_closed(
                fields,
                materialized=materialized,
                source_text="Main article text",
                source_set={**complete, "companions": []},
            )
        )
        self.assertFalse(
            source_set_record_closed(
                {
                    **complete,
                    "non_text_companions": ["https://publisher.test/package.zip"],
                },
                materialized,
            )
        )
        self.assertFalse(
            companion_sources_closed(
                fields,
                materialized={"PaperAAppendix": True},
                source_text="Main article text",
                source_set=complete,
            )
        )

    def test_non_text_companions_require_inspected_durable_dispositions(self) -> None:
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "literature" / "papers"
            notes = root / "literature" / "source-notes"
            papers.mkdir(parents=True)
            notes.mkdir(parents=True)
            artifact = papers / "package.zip"
            artifact.write_bytes(b"PK\x03\x04test")
            note = notes / "PaperAReplication.md"
            note.write_text("inspected package")
            source_set = {
                "non_text_companions": ["https://publisher.test/package.zip"],
            }
            self.assertFalse(non_text_dispositions_closed(source_set, root=root))
            materialized = {
                **source_set,
                "non_text_dispositions": [
                    {
                        "sources": source_set["non_text_companions"],
                        "status": "materialized",
                        "artifact": "literature/papers/package.zip",
                        "note": "literature/source-notes/PaperAReplication.md",
                        "bytes": artifact.stat().st_size,
                        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    }
                ],
            }
            self.assertTrue(non_text_dispositions_closed(materialized, root=root))
            artifact.write_bytes(b"PK\x03\x04fail")
            self.assertFalse(non_text_dispositions_closed(materialized, root=root))
            artifact.write_bytes(b"PK\x03\x04test")
            materialized["non_text_dispositions"][0]["bytes"] += 1
            self.assertFalse(non_text_dispositions_closed(materialized, root=root))
            unavailable = {
                **source_set,
                "non_text_dispositions": [
                    {
                        "sources": source_set["non_text_companions"],
                        "status": "unavailable",
                        "note": "literature/source-notes/PaperAReplication.md",
                        "reason": "publisher endpoint no longer serves the declared artifact",
                    }
                ],
            }
            self.assertTrue(non_text_dispositions_closed(unavailable, root=root))
    def test_materialization_does_not_confuse_main_and_companion_prefixes(self) -> None:
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text_root = root / "text"
            note_root = root / "notes"
            paper_root = root / "papers"
            text_root.mkdir()
            note_root.mkdir()
            paper_root.mkdir()
            stem = "2021-PaperAAppendix-supplement"
            (text_root / f"{stem}.txt").write_text("appendix")
            keys = {"PaperA", "PaperAAppendix"}
            self.assertFalse(
                source_materialized(
                    "PaperA",
                    bib_keys=keys,
                    source_keys=keys,
                    text_root=text_root,
                    note_root=note_root,
                    paper_root=paper_root,
                    index={},
                )
            )
            self.assertFalse(
                source_materialized(
                    "PaperAAppendix",
                    bib_keys=keys,
                    source_keys=keys,
                    text_root=text_root,
                    note_root=note_root,
                    paper_root=paper_root,
                    index={},
                )
            )
            pdf = paper_root / f"{stem}.pdf"
            pdf.write_bytes(b"%PDF synthetic")
            self.assertTrue(
                source_materialized(
                    "PaperAAppendix",
                    bib_keys=keys,
                    source_keys=keys,
                    text_root=text_root,
                    note_root=note_root,
                    paper_root=paper_root,
                    index={
                        stem: {
                            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                        }
                    },
                )
            )

    def test_source_set_main_requires_the_indexed_pdf_not_only_its_extract(self) -> None:
        import hashlib
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text_root = root / "literature" / "text"
            paper_root = root / "literature" / "papers"
            text_root.mkdir(parents=True)
            paper_root.mkdir(parents=True)
            stem = "2020-PaperA-published"
            article = text_root / f"{stem}.txt"
            article.write_text("full article")
            pdf = paper_root / f"{stem}.pdf"
            pdf_bytes = b"%PDF synthetic"
            index_record = {
                "stem": stem,
                "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            }
            (text_root / "_index.jsonl").write_text(json.dumps(index_record) + "\n")
            source_set = {
                "main": "PaperA",
                "checks": {"article": f"literature/text/{stem}.txt"},
            }
            self.assertFalse(source_set_main_artifact_closed(source_set, {"PaperA": True}, root=root))
            pdf.write_bytes(pdf_bytes)
            self.assertTrue(source_set_main_artifact_closed(source_set, {"PaperA": False}, root=root))
            pdf.write_bytes(b"%PDF changed")
            self.assertFalse(source_set_main_artifact_closed(source_set, {"PaperA": True}, root=root))

    def test_inaccessible_companion_note_cannot_close_a_complete_card(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / "literature" / "source-notes"
            notes.mkdir(parents=True)
            (notes / "2026-PaperAAppendix.md").write_text(
                "# Appendix disposition\n\nThe accepted appendix remains access-restricted."
            )
            source_set = {
                "status": "complete",
                "main": "PaperA",
                "checks": {
                    "article": "synthetic full text",
                    "publisher_or_doi": "publisher checked",
                    "author_or_repository": "author checked",
                },
                "companions": ["PaperAAppendix"],
            }
            self.assertFalse(
                source_set_companion_disposition_resolved(
                    "PaperAAppendix",
                    {"PaperAAppendix": False},
                    root=root,
                )
            )
            self.assertFalse(
                source_set_record_closed(
                    source_set,
                    {"PaperA": True, "PaperAAppendix": False},
                    root=root,
                )
            )
            (notes / "2026-PaperAAppendix.md").write_text(
                "---\nsource_type: embedded-in-main\n---\n\nThe appendix occupies pages 30 to 40."
            )
            self.assertTrue(
                source_set_companion_disposition_resolved(
                    "PaperAAppendix",
                    {"PaperAAppendix": False},
                    root=root,
                )
            )
            self.assertTrue(
                source_set_record_closed(
                    source_set,
                    {"PaperA": True, "PaperAAppendix": False},
                    root=root,
                )
            )
    def test_citation_inventory_reads_every_key_in_a_group(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "section.tex"
            path.write_text(r"\\citet{PaperA,PaperB} and \\citep{PaperC}")
            self.assertEqual(
                cited_bibliography_keys([path]),
                {"PaperA", "PaperB", "PaperC"},
            )

    def test_specification_lock_requires_hash_and_complete_registered_claims(self) -> None:
        import copy
        import hashlib
        import json

        claim = {
            "id": "lead",
            "status": "registered_primary",
            "execution_gate": "open",
            "role": "lead",
            "estimand": "change",
            "sample": "sample",
            "unit": "day",
            "dependent_variable": "share",
            "transformation": "level",
            "outlier_treatment": "none",
            "inference": "HAC",
            "mandatory_alternatives": {"weighting": ["count", "value"]},
            "falsifier": "zero",
            "admissible_interpretation": "change",
            "forbidden_interpretation": "cause",
            "inputs": ["input"],
            "outputs": ["output"],
        }
        registered_specifications = [
            {
                "spec_id": "primary",
                "kind": "primary",
                "parameters": {"weighting": "count"},
                "covers": [
                    "mandatory_alternatives/weighting/0",
                    "mandatory_alternatives/weighting/1",
                    "falsifier",
                ],
            }
        ]
        claim["registered_specifications"] = registered_specifications
        claim["plan_hash"] = hashlib.sha256(
            json.dumps(
                registered_specifications,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        payload = {
            "schema_version": 1,
            "locked_at": "2026-08-07",
            "stage": "confirmatory",
            "analytical_choices_status": "registered_after_exploration",
            "d3_generation": "test-d3-generation",
            "d3_certificate": "data/manifests/analysis-release.json",
            "exploration_generation": "test-d3-e0-generation",
            "exploration_certificate": "docs/e0-exploration-certificate.json",
            "global_rules": {
                "audit_sampling": "monthly snapshots are validation only and do not define a monthly estimand",
                "vehicle_status": "binary intermediary-use indicator",
                "vehicle_dominance": "continuous degree of intermediary use",
                "cost_domination": "route loses to an available alternative",
                "abstract_question": "what makes a vehicle currency dominant",
                "dynamic_horizons": "exact calendar dates at 1, 7, 30, and 120 days; row shifts are not substitutes",
            },
            "claims": [
                claim,
                {**claim, "id": "foundation", "status": "registered_foundation"},
                {**claim, "id": "mechanism", "status": "registered_mechanism"},
                {**claim, "id": "companion", "status": "registered_companion"},
            ],
        }
        payload["lock_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        passed, detail = validate_specification_lock(payload)
        self.assertTrue(passed, detail)
        missing_gate = copy.deepcopy(payload)
        missing_gate["claims"][0].pop("execution_gate")
        missing_gate["lock_hash"] = canonical_hash(
            {key: value for key, value in missing_gate.items() if key != "lock_hash"}
        )
        passed, detail = validate_specification_lock(missing_gate)
        self.assertFalse(passed, detail)
        self.assertIn("must explicitly declare", detail)
        blocked_incomplete = copy.deepcopy(payload)
        blocked_claim = blocked_incomplete["claims"][-1]
        blocked_claim["execution_gate"] = "blocked_external_reference_variance"
        blocked_claim.pop("inputs")
        blocked_claim.pop("registered_specifications")
        blocked_claim.pop("plan_hash")
        blocked_incomplete["lock_hash"] = canonical_hash(
            {key: value for key, value in blocked_incomplete.items() if key != "lock_hash"}
        )
        passed, detail = validate_specification_lock(blocked_incomplete)
        self.assertTrue(passed, detail)
        incomplete_attack = copy.deepcopy(payload)
        registered_claim = incomplete_attack["claims"][0]
        registered_claim["registered_specifications"][0]["covers"].remove(
            "mandatory_alternatives/weighting/1"
        )
        registered_claim["plan_hash"] = canonical_hash(
            registered_claim["registered_specifications"]
        )
        incomplete_attack["lock_hash"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in incomplete_attack.items()
                    if key != "lock_hash"
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        passed, detail = validate_specification_lock(incomplete_attack)
        self.assertFalse(passed, detail)
        self.assertIn("mandatory_alternatives/weighting/1", detail)
        payload["claims"][0].pop("falsifier")
        passed, detail = validate_specification_lock(payload)
        self.assertFalse(passed, detail)

    def test_specification_lock_requires_semantic_distinctions(self) -> None:
        import hashlib
        import json

        claim = {
            "id": "lead",
            "status": "registered_primary",
            "execution_gate": "open",
            "role": "lead",
            "estimand": "change",
            "sample": "sample",
            "unit": "day",
            "dependent_variable": "share",
            "transformation": "level",
            "outlier_treatment": "none",
            "inference": "HAC",
            "mandatory_alternatives": {"weighting": ["count", "value"]},
            "falsifier": "zero",
            "admissible_interpretation": "change",
            "forbidden_interpretation": "cause",
            "inputs": ["input"],
            "outputs": ["output"],
        }
        payload = {
            "schema_version": 1,
            "global_rules": {
                "vehicle_status": "binary intermediary-use indicator",
                "vehicle_dominance": "continuous degree of intermediary use",
                "cost_domination": "route loses to an available alternative",
            },
            "claims": [
                claim,
                {**claim, "id": "foundation", "status": "registered_foundation"},
                {**claim, "id": "mechanism", "status": "registered_mechanism"},
            ],
        }
        payload["lock_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        passed, detail = validate_specification_lock(payload)
        self.assertFalse(passed)
        self.assertIn("abstract_question", detail)

    def test_specification_lock_rejects_noncanonical_dynamic_horizons(self) -> None:
        import hashlib
        import json

        claim = {
            "id": "lead",
            "status": "registered_primary",
            "execution_gate": "open",
            "role": "lead",
            "estimand": "change",
            "sample": "sample",
            "unit": "day",
            "dependent_variable": "share",
            "transformation": "level",
            "outlier_treatment": "none",
            "inference": "HAC",
            "mandatory_alternatives": {"weighting": ["count", "value"]},
            "falsifier": "zero",
            "admissible_interpretation": "change",
            "forbidden_interpretation": "cause",
            "inputs": ["input"],
            "outputs": ["output"],
            "response_horizon_days": [1, 7, 14, 30],
        }
        payload = {
            "schema_version": 1,
            "locked_at": "2026-08-10",
            "stage": "confirmatory",
            "analytical_choices_status": "registered_after_exploration",
            "d3_generation": "test-d3-generation",
            "d3_certificate": "data/manifests/analysis-release.json",
            "exploration_generation": "test-d3-e0-generation",
            "exploration_certificate": "docs/e0-exploration-certificate.json",
            "global_rules": {
                "audit_sampling": "monthly snapshots are validation only and do not define a monthly estimand",
                "vehicle_status": "binary intermediary-use indicator",
                "vehicle_dominance": "continuous degree of intermediary use",
                "cost_domination": "route loses to an available alternative",
                "abstract_question": "what makes a vehicle currency dominant",
                "dynamic_horizons": "exact calendar dates at 1, 7, 30, and 120 days; row shifts are not substitutes",
            },
            "claims": [
                claim,
                {**claim, "id": "foundation", "status": "registered_foundation", "response_horizon_days": [1, 7, 30, 120]},
                {**claim, "id": "mechanism", "status": "registered_mechanism", "response_horizon_days": [1, 7, 30, 120]},
            ],
        }
        payload["lock_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        passed, detail = validate_specification_lock(payload)
        self.assertFalse(passed)
        self.assertIn("lead", detail)

    def test_route_measurement_invariants_reconcile_all_families(self) -> None:
        intermediation = {
            "date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")],
            "routes_intermediated": [2, 0],
            "episodes": [3, 0],
        }
        for asset_type in TYPES:
            intermediation[f"cnt_{asset_type}"] = [
                3 if asset_type == "stable" else 0,
                0,
            ]
            intermediation[f"usd_{asset_type}"] = [
                30.0 if asset_type == "stable" else 0.0,
                0.0,
            ]
            intermediation[f"usd_within_2x_{asset_type}"] = [
                24.0 if asset_type == "stable" else 0.0,
                0.0,
            ]
            intermediation[f"usd_within_20pct_{asset_type}"] = [
                20.0 if asset_type == "stable" else 0.0,
                0.0,
            ]
        cross_venue = pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")],
                "economic_multileg_routes": [3, 1],
                "intermediated_routes": [2, 0],
                "direct_split_routes": [1, 1],
                "pure_sequential_routes": [1, 0],
                "mixed_indirect_routes": [1, 0],
                "intermediated_usd": [40.0, 0.0],
                "intermediated_usd_within_2x": [32.0, 0.0],
                "intermediated_usd_within_20pct": [28.0, 0.0],
            }
        )
        vehicle = pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-01-01")],
                "vehicle_intermediate_routes": [3],
                "vehicle_intermediate_usd": [30.0],
                "vehicle_intermediate_usd_within_2x": [24.0],
                "vehicle_intermediate_usd_within_20pct": [20.0],
            }
        )
        checks = route_measurement_invariants(
            pd.DataFrame(intermediation), cross_venue, vehicle
        )
        self.assertTrue(all(passed for _name, passed, _detail in checks))
        missing_nonempty = route_measurement_invariants(
            pd.DataFrame(intermediation).iloc[:1],
            cross_venue.iloc[:1],
            vehicle.iloc[:0],
        )
        self.assertFalse(
            {
                name: passed for name, passed, _detail in missing_nonempty
            }["route measurement calendars reconcile"]
        )
        vehicle.loc[0, "vehicle_intermediate_routes"] = 2
        checks = route_measurement_invariants(
            pd.DataFrame(intermediation), cross_venue, vehicle
        )
        self.assertFalse(
            {
                name: passed for name, passed, _detail in checks
            }["intermediary episode counts reconcile"]
        )

    def test_graph_status_is_read_only_from_leading_frontmatter(self) -> None:
        state = parse_state_frontmatter(
            """---
freeze_status: red
stable_passes: 0
active_node: D
parent_loop: C <-> K
next_edge: D -> C -> E -> I
prose_node: closed
---

active_node: P
"""
        )

        self.assertEqual(state["active_node"], "D")
        self.assertEqual(
            graph_status(state),
            "active=D; parent=C <-> K; next=D -> C -> E -> I; prose=closed",
        )

    def test_missing_graph_fields_remain_visible(self) -> None:
        self.assertEqual(
            graph_status({"active_node": "D"}),
            "active=D; parent=missing; next=missing; prose=missing",
        )


if __name__ == "__main__":
    unittest.main()

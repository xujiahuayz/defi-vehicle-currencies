from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock, call, patch

import pandas as pd

from ddvc.asset_types import TYPES
from scripts import refresh_panel_dependents as refresher
from scripts.audit_findings_freeze import (
    card_source_evidence_text,
    cited_bibliography_keys,
    companion_sources_closed,
    companion_source_keys,
    complete_literature_card,
    expected_market_state_keys,
    expected_unified_route_venue_days,
    graph_status,
    non_text_dispositions_closed,
    parse_literature_cards,
    parse_state_frontmatter,
    published_venue_version,
    registered_empirical_consumers,
    route_measurement_invariants,
    source_materialized,
    source_set_record_closed,
    transaction_frontier_artifact_checks,
    transaction_frontier_support_checks,
    validate_capital_contract_rows,
    validate_literature_audit,
    validate_liquidity_contracts,
    validate_quote_state_contract_rows,
    validate_canonical_consumer_boundary,
    validate_claim_input_layer,
    validate_model_ledger,
    validate_specification_lock,
    validate_unified_route_layer,
)
from ddvc.literature_admission import validate_source_admission
from ddvc.liquidity import LIQUIDITY_CONTRACTS
from scripts.refresh_panel_dependents import (
    CLAIM_INPUT_STAGES,
    DAILY_FRONTIER_PREREQUISITES,
)


class FindingsFreezeAuditTest(unittest.TestCase):
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
            refresher.stage_log_path("process/fetch_daily_gas_price_graph.py").name,
            "process__fetch_daily_gas_price_graph.py.log",
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
                "data/processed/counterfactual_dominance.parquet",
                "data/processed/cross_venue_routing_daily.parquet",
                "data/processed/daily_gas_price_graph.parquet",
                "data/processed/intermediation_by_type_daily.parquet",
                "data/processed/lp_liquidity_flow_candidates_v3.parquet",
                "data/processed/lp_liquidity_flow_events_v3.parquet",
                "data/processed/lp_liquidity_flow_daily_v3.parquet",
                "data/processed/lp_liquidity_flow_rejections_v3.parquet",
                "data/processed/pool_candidate_capital_daily.parquet",
                "data/processed/pool_capital_daily.parquet",
                "data/processed/pool_capital_rejections.parquet",
                "data/processed/rent_incidence_v2_pool_day.parquet",
                "data/processed/route_gas_units.parquet",
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
            "claims": [
                {
                    "id": "live",
                    "status": "enter_fgh_primary",
                    "inputs": ["data/processed/clean.parquet"],
                }
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

    def test_model_ledger_counts_families_once_and_binds_live_claims(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(dir=Path.cwd(), delete=False) as handle:
            artifact = Path(handle.name)
        try:
            relative = str(artifact.relative_to(Path.cwd()))
            payload = {
                "schema_version": 1,
                "families": [
                    {
                        "id": "live",
                        "claim_id": "lead",
                        "estimator": "OLS",
                        "fixed_effects": "pair and date",
                        "inference": "pair clustered",
                        "substantive_specifications": 2,
                        "diagnostic_specifications": 3,
                        "resampling_refits": 100,
                        "status": "admissible",
                        "artifacts": [relative],
                        "note": "one family",
                    }
                ],
            }
            passed, detail = validate_model_ledger(payload, claim_ids={"lead"})
            self.assertTrue(passed, detail)
            self.assertIn("reported=5", detail)
            payload["families"][0]["claim_id"] = "unknown"
            passed, detail = validate_model_ledger(payload, claim_ids={"lead"})
            self.assertFalse(passed, detail)
        finally:
            artifact.unlink(missing_ok=True)

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
                "within_20pct_chosen_quote_available": [101],
                "within_20pct_chosen_output_mismatch": [1],
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
        self.assertTrue(checks["transaction frontier chosen-output validation"][0])
        self.assertFalse(checks["transaction frontier audit-day coverage"][0])

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
                    "within_20pct_chosen_quote_available": [1],
                    "within_20pct_chosen_output_mismatch": [0],
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
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text_root = root / "text"
            note_root = root / "notes"
            text_root.mkdir()
            note_root.mkdir()
            (text_root / "2021-PaperAAppendix-supplement.txt").write_text("appendix")
            keys = {"PaperA", "PaperAAppendix"}
            self.assertFalse(
                source_materialized(
                    "PaperA",
                    bib_keys=keys,
                    source_keys=keys,
                    text_root=text_root,
                    note_root=note_root,
                )
            )
            self.assertTrue(
                source_materialized(
                    "PaperAAppendix",
                    bib_keys=keys,
                    source_keys=keys,
                    text_root=text_root,
                    note_root=note_root,
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

    def test_specification_lock_requires_hash_and_complete_entered_claims(self) -> None:
        import hashlib
        import json

        claim = {
            "id": "lead",
            "status": "enter_fgh_primary",
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
            "locked_at": "2026-08-07",
            "global_rules": {
                "vehicle_status": "binary intermediary-use indicator",
                "vehicle_dominance": "continuous degree of intermediary use",
                "cost_domination": "route loses to an available alternative",
                "abstract_question": "what makes a vehicle currency dominant",
            },
            "claims": [
                claim,
                {**claim, "id": "foundation", "status": "enter_fgh_foundation"},
                {**claim, "id": "mechanism", "status": "enter_fgh_mechanism"},
                {**claim, "id": "companion", "status": "enter_fgh_companion"},
            ],
        }
        payload["lock_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        passed, detail = validate_specification_lock(payload)
        self.assertTrue(passed, detail)
        payload["claims"][0].pop("falsifier")
        passed, detail = validate_specification_lock(payload)
        self.assertFalse(passed, detail)

    def test_specification_lock_requires_semantic_distinctions(self) -> None:
        import hashlib
        import json

        claim = {
            "id": "lead",
            "status": "enter_fgh_primary",
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
                {**claim, "id": "foundation", "status": "enter_fgh_foundation"},
                {**claim, "id": "mechanism", "status": "enter_fgh_mechanism"},
            ],
        }
        payload["lock_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        passed, detail = validate_specification_lock(payload)
        self.assertFalse(passed)
        self.assertIn("abstract_question", detail)

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

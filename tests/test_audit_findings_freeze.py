from __future__ import annotations

import unittest

import pandas as pd

from ddvc.asset_types import TYPES
from scripts.audit_findings_freeze import (
    cited_bibliography_keys,
    complete_literature_card,
    graph_status,
    parse_literature_cards,
    parse_state_frontmatter,
    route_measurement_invariants,
    validate_literature_audit,
    validate_specification_lock,
)


class FindingsFreezeAuditTest(unittest.TestCase):
    def test_literature_gate_requires_individual_verified_cards(self) -> None:
        text = """---
status: complete
---

### PaperA
- Status: claim-verified
- Roles: central, mechanism
- Source: literature/papers/paper-a.pdf
- Version: Journal version, 2020
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
- Version: Published JFE version, 2021
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
        missing_optics = text.replace(
            "- Optics: Calibrated title, early result preview, and a compact exhibit hierarchy\n",
            "",
            1,
        )
        passed, detail = validate_literature_audit(
            missing_optics, {"PaperA"}, {"venue:one"}
        )
        self.assertFalse(passed, detail)
        passed, _detail = validate_literature_audit(
            text.replace("Independent: complete", "Independent: pending"),
            {"PaperA"},
            {"venue:one"},
        )
        self.assertFalse(passed)

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
            "global_rules": {},
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

    def test_route_measurement_invariants_reconcile_all_families(self) -> None:
        intermediation = {
            "date": [pd.Timestamp("2026-01-01")],
            "routes_intermediated": [2],
            "episodes": [3],
        }
        for asset_type in TYPES:
            intermediation[f"cnt_{asset_type}"] = [
                3 if asset_type == "stable" else 0
            ]
            intermediation[f"usd_{asset_type}"] = [
                30.0 if asset_type == "stable" else 0.0
            ]
            intermediation[f"usd_within_2x_{asset_type}"] = [
                24.0 if asset_type == "stable" else 0.0
            ]
            intermediation[f"usd_within_20pct_{asset_type}"] = [
                20.0 if asset_type == "stable" else 0.0
            ]
        cross_venue = pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-01-01")],
                "economic_multileg_routes": [3],
                "intermediated_routes": [2],
                "direct_split_routes": [1],
                "pure_sequential_routes": [1],
                "mixed_indirect_routes": [1],
                "intermediated_usd": [40.0],
                "intermediated_usd_within_2x": [32.0],
                "intermediated_usd_within_20pct": [28.0],
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

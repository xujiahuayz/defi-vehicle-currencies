from __future__ import annotations

import unittest

from scripts.audit_findings_freeze import graph_status, parse_state_frontmatter


class FindingsFreezeAuditTest(unittest.TestCase):
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

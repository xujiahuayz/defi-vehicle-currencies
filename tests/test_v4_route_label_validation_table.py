from __future__ import annotations

import pandas as pd

from scripts.tabulate.render_v4_route_label_validation import (
    EVENT_LABELS,
    ROUTE_LABELS,
    render_table,
)


def test_renderer_uses_pooled_counts() -> None:
    rows = []
    for dimension in EVENT_LABELS:
        rows.append(
            {
                "record_type": "pooled_event_label",
                "dimension": dimension,
                "provider_assignments": 100,
                "exact_assignments": 101,
                "precision": 1.0,
                "recall": 100 / 101,
            }
        )
    for dimension in ROUTE_LABELS:
        rows.append(
            {
                "record_type": "pooled_route_label",
                "dimension": dimension,
                "provider_assignments": 50,
                "exact_assignments": 50,
                "precision": 1.0,
                "recall": 1.0,
                "scope_transactions": 100,
                "provider_label_transactions": 80,
                "exact_label_transactions": 81,
                "union_label_transactions": 82,
                "exact_match_transactions": 79,
                "unconditional_exact_match_share": 0.79,
                "conditional_exact_match_share": 79 / 82,
            }
        )
    rows.append(
        {
            "record_type": "support",
            "covered_days": 181,
            "v4_only_observed_transactions": 8_352_524,
        }
    )
    rendered = render_table(pd.DataFrame(rows))
    assert "PoolManager Swap labels" in rendered
    assert "Route-label assignment agreement" in rendered
    assert "Transaction coverage" in rendered
    assert "observed v4-only transactions" in rendered
    assert "8,352,524 observed v4-only transactions" in rendered
    assert "Signed raw amounts (covered)" in rendered
    assert "Ordered legs" in rendered
    assert "Exact two-leg inclusion" in rendered
    assert "Scope $N$" in rendered
    assert "$M/N$" in rendered
    assert "$M/U$" in rendered
    assert "79.0000" in rendered
    assert "96.3415" in rendered
    assert "181" in rendered
    assert rendered.count(r"Xrrrrr@{}}") == 3
    assert "Xrrrrrrr" not in rendered
    assert "\\parbox" not in rendered
    assert "\\exhibitnote" not in rendered

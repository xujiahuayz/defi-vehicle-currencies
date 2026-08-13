from __future__ import annotations

from scripts.audit_v2_token_anchor_materiality import decimals_scale_record


def test_decimals_scale_bound_uses_fail_closed_project_policy() -> None:
    observed = decimals_scale_record([None, "18", "18"])
    assert observed == {
        "provider_decimals": [18],
        "exact_decimals_min": 0,
        "exact_decimals_max": 36,
        "max_upward_scale_exponent": 18,
        "max_downward_scale_exponent": 18,
        "unreported_raw_quantity_exponent_width": None,
    }
    absent = decimals_scale_record([None])
    assert absent["provider_decimals"] == []
    assert absent["max_upward_scale_exponent"] is None
    assert absent["max_downward_scale_exponent"] is None
    assert absent["unreported_raw_quantity_exponent_width"] == 36


def test_materiality_owner_is_read_only_and_publishes_deletion_bound() -> None:
    source = __import__(
        "pathlib"
    ).Path("scripts/audit_v2_token_anchor_materiality.py").read_text(encoding="utf-8")
    assert "require_route_release()" in source
    assert "candidate_intermediary_usd_deleted_worst_case" in source
    assert "v4_fixed_cell_architecture_rows" in source
    assert "write_exhibit(" in source
    assert "rpc_post" not in source
    assert "--fetch" not in source

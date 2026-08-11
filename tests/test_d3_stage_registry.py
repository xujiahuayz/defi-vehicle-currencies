from __future__ import annotations

import json
import sys

import pytest

from ddvc.d3_stage_registry import (
    D3_BUILD_STAGES,
    D3BuildStage,
    d3_input_ownership,
    executable_claim_inputs,
)
from ddvc.paths import REPO_ROOT
from scripts import refresh_panel_dependents


def _specification() -> dict[str, object]:
    return json.loads(
        (REPO_ROOT / "docs" / "specification-lock.json").read_text(
            encoding="utf-8"
        )
    )


def test_real_d3_registry_equals_the_executable_specification_perimeter() -> None:
    specification = _specification()
    ownership = d3_input_ownership(specification)
    assert tuple(record.path for record in ownership) == executable_claim_inputs(
        specification
    )
    by_path = {record.path: record for record in ownership}
    route_cost = by_path["data/empirical/route_cost_panel_v2.parquet"]
    assert route_cost.status == "external_prerequisite"
    assert route_cost.owner == "scripts/run_route_cost_panel.py"
    for path in (
        "data/processed/liquidity_capital_flow_candidate_day.parquet",
        "data/processed/liquidity_capital_flow_exact_horizons.parquet",
    ):
        assert by_path[path].status == "built"
        assert by_path[path].owner == "build_liquidity_capital_flow_panels.py"


def test_refresh_consumes_typed_registry_without_a_compatibility_view(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert not hasattr(refresh_panel_dependents, "CLAIM_INPUT_STAGES")
    monkeypatch.setattr(
        sys,
        "argv",
        ["refresh_panel_dependents.py", "--dry-run", "--scope", "claim-inputs"],
    )
    assert refresh_panel_dependents.main() == 0
    output = capsys.readouterr().out
    assert f"{len(D3_BUILD_STAGES)} stages" in output
    assert "build_liquidity_capital_flow_panels.py" in output


def test_registry_rejects_an_unowned_executable_input() -> None:
    specification = _specification()
    claim = next(
        claim
        for claim in specification["claims"]
        if claim["execution_gate"] == "open"
    )
    claim["inputs"].append("data/processed/unowned.parquet")
    with pytest.raises(ValueError, match="missing=.*unowned"):
        d3_input_ownership(specification)


def test_registry_rejects_duplicate_ownership() -> None:
    specification = _specification()
    path = executable_claim_inputs(specification)[0]
    duplicate = D3BuildStage("duplicate.py", (), "invalid duplicate", (path,))
    with pytest.raises(ValueError, match="duplicate=.*"):
        d3_input_ownership(specification, stages=(*D3_BUILD_STAGES, duplicate))

from __future__ import annotations

import json
import sys

import pytest

from ddvc.capital_release import (
    CAPITAL_RELEASE_POINTER_RELATIVE,
    resolve_capital_release,
)
from ddvc.d3_stage_registry import (
    D3_BUILD_STAGES,
    D3ReleasePostcondition,
    D3BuildStage,
    d3_input_ownership,
    executable_claim_inputs,
)
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE,
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
    assert set(by_path) == {
        "data/processed/cross_venue_routing_daily.parquet",
        "data/processed/endpoint_candidate_composition_release/current.json",
        "data/processed/intermediation_by_type_daily.parquet",
        "data/processed/liquidity_capital_v2_candidate_day.parquet",
        "data/processed/liquidity_capital_v2_exact_horizons.parquet",
        "data/processed/pool_capital_release/current.json",
        "data/processed/vehicle_excess_use_daily.parquet",
    }
    capital = by_path["data/processed/pool_capital_release/current.json"]
    assert capital.status == "built"
    assert capital.owner == "build_pool_capital_panel.py"
    endpoint = by_path[
        "data/processed/endpoint_candidate_composition_release/current.json"
    ]
    assert endpoint.status == "built"
    assert endpoint.owner == "build_endpoint_candidate_composition.py"


def test_blocked_external_owner_remains_registered_but_not_executable() -> None:
    specification = _specification()
    ownership = d3_input_ownership(specification)
    assert "data/empirical/route_cost_panel_v2.parquet" not in {
        record.path for record in ownership
    }


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


def test_refresh_uses_typed_release_resolver_instead_of_flat_pointer_provenance(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = "data/processed/example-release/current.json"
    observed: list[object] = []

    def resolve(path):
        observed.append(path)
        return object()

    stage = D3BuildStage(
        "build_example.py",
        (),
        "typed release test",
        (pointer,),
        D3ReleasePostcondition(pointer, resolve),
    )
    monkeypatch.setattr(refresh_panel_dependents, "ROOT", tmp_path)
    monkeypatch.setattr(
        refresh_panel_dependents,
        "verify",
        lambda _path: (_ for _ in ()).throw(AssertionError("flat pointer verified")),
    )
    current, bad = refresh_panel_dependents.current_stage_artifacts(stage)
    assert current
    assert bad == []
    assert observed == [tmp_path / pointer]


def test_release_postcondition_must_name_an_owned_pointer() -> None:
    with pytest.raises(ValueError, match="owned output"):
        D3BuildStage(
            "invalid.py",
            (),
            "invalid release",
            ("data/processed/other.parquet",),
            D3ReleasePostcondition(
                "data/processed/release/current.json", lambda _path: object()
            ),
        )


def test_every_owned_current_pointer_has_one_typed_resolver() -> None:
    current_pointer_stages = [
        stage
        for stage in D3_BUILD_STAGES
        if any(output.endswith("/current.json") for output in stage.outputs)
    ]
    assert current_pointer_stages
    for stage in current_pointer_stages:
        assert stage.release_postcondition is not None
        assert stage.release_postcondition.pointer in stage.outputs
        assert callable(stage.release_postcondition.resolver)
    capital = next(
        stage
        for stage in current_pointer_stages
        if CAPITAL_RELEASE_POINTER_RELATIVE in stage.outputs
    )
    assert capital.release_postcondition == D3ReleasePostcondition(
        CAPITAL_RELEASE_POINTER_RELATIVE,
        resolve_capital_release,
    )
    endpoint = next(
        stage
        for stage in current_pointer_stages
        if ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE in stage.outputs
    )
    assert endpoint.release_postcondition is not None
    assert endpoint.release_postcondition.receipt_backed_lease is not None
    assert capital.release_postcondition.receipt_backed_lease is None


def test_current_pointer_without_typed_resolver_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires a typed resolver"):
        D3BuildStage(
            "invalid.py",
            (),
            "invalid unresolved pointer",
            ("data/processed/invalid/current.json",),
        )


def test_liquidity_sequence_runs_v2_before_v3_and_keeps_rent_out() -> None:
    scripts = [stage.script for stage in D3_BUILD_STAGES]
    assert "build_rent_incidence_panel.py" not in scripts
    assert "process/build_cex_reference_support.py" not in scripts
    liquidity = [
        (index, stage.arguments)
        for index, stage in enumerate(D3_BUILD_STAGES)
        if stage.script == "build_liquidity_capital_flow_panels.py"
    ]
    assert len(liquidity) == 2
    v2_index = next(index for index, arguments in liquidity if ("--family", "v2") == arguments[:2])
    joint_index = next(index for index, arguments in liquidity if ("--family", "joint") == arguments[:2])
    flow_index = scripts.index("build_lp_liquidity_flow_panel.py")
    assert v2_index < flow_index < joint_index

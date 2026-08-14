from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import ddvc.analysis.vehicle_role_risk as role_risk
from ddvc.asset_types import NATIVE as NATIVE_ASSETS, STABLE as STABLE_ASSETS
from ddvc.analysis.vehicle_role_risk import (
    assert_complete_endpoint_release,
    build_vehicle_role_risk_panel,
)
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
    ENDPOINT_CANDIDATE_COMPOSITION_VALIDATOR_SOURCES,
)
from ddvc.provenance import sidecar_path
from scripts.build_architecture_role_risk_panel import CODE_SOURCES


PAIR = {"src": "source", "tgt": "destination"}
NATIVE = next(address for address, symbol in NATIVE_ASSETS.items() if symbol == "WETH")
STABLE = next(address for address, symbol in STABLE_ASSETS.items() if symbol == "USDC")


def _choice(date: str, candidate: str, symbol: str, candidate_type: str) -> dict[str, object]:
    return {
        "date": date,
        **PAIR,
        "candidate_address": candidate,
        "integration_scope": "single_venue",
        "venue_sequence": "uniswap_v3>uniswap_v3",
        "candidate_symbol": symbol,
        "candidate_type": candidate_type,
        "route_count": 1,
    }


def _support(date: str, primary_choice_routes: int) -> dict[str, object]:
    return {
        "date": date,
        **PAIR,
        "market_route_count": 10,
        "primary_choice_route_count": primary_choice_routes,
    }


def synthetic_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = ["2025-01-06", "2025-01-13", "2025-01-20", "2025-01-27"]
    choices = pd.DataFrame(
        [
            _choice(dates[0], NATIVE, "WETH", "native"),
            _choice(dates[1], NATIVE, "WETH", "native"),
            _choice(dates[2], STABLE, "USDC", "stable"),
        ]
    )
    support = pd.DataFrame(
        [_support(date, primary) for date, primary in zip(dates, [1, 1, 1, 0], strict=True)]
    )
    return choices, support


def test_builds_genuine_zero_rows_and_separates_transition_taxonomy() -> None:
    choices, support = synthetic_inputs()
    panel = build_vehicle_role_risk_panel(choices, support)
    assert len(panel) == 6
    assert panel["total_routes"].eq(0).sum() == 3
    assert panel["candidate_set_definition"].str.contains("first_realised_week").all()
    assert {"candidate_type", "pair_observed_days", "candidate_first_observed_week"}.issubset(
        panel.columns
    )
    assert panel["opportunity_set_status"].eq(
        "economic_route_feasibility_not_observed_or_imputed"
    ).all()
    observed = panel[panel["transition_observed"]]
    assert observed["reentry_event"].sum() == 0
    assert observed["continuing_use_event"].sum() == 1
    assert observed["substitution_exit_event"].sum() == 1
    assert observed[
        "selected_stable_native_primary_route_cessation_event"
    ].sum() == 1
    assert set(observed["transition_kind"]) == {
        "continuing_use",
        "substitution_exit",
        "selected_stable_native_primary_route_cessation",
        "continuing_nonuse",
    }


def test_builder_code_perimeter_contains_endpoint_validator_dependencies() -> None:
    assert set(ENDPOINT_CANDIDATE_COMPOSITION_VALIDATOR_SOURCES).issubset(CODE_SOURCES)


def test_candidate_has_no_rows_before_first_observed_week() -> None:
    choices, support = synthetic_inputs()
    panel = build_vehicle_role_risk_panel(choices, support)
    stable = panel[panel["vehicle_id"].eq(STABLE)]
    assert stable["week"].min() == pd.Timestamp("2025-01-20")
    assert stable.iloc[0]["total_routes"] == 1


def test_candidate_type_metadata_mismatch_fails_closed() -> None:
    choices, support = synthetic_inputs()
    choices.loc[choices["candidate_address"].eq(STABLE), "candidate_type"] = "native"
    with pytest.raises(ValueError, match="canonical classification"):
        build_vehicle_role_risk_panel(choices, support)


def test_calendar_gap_does_not_create_a_transition() -> None:
    choices, support = synthetic_inputs()
    choices = choices[choices["date"] != "2025-01-20"].copy()
    support = support[support["date"] != "2025-01-20"].copy()
    panel = build_vehicle_role_risk_panel(choices, support)
    before_gap = panel[panel["week"].eq(pd.Timestamp("2025-01-13"))]
    assert not before_gap["transition_observed"].any()
    assert before_gap["reentry_event"].isna().all()
    assert before_gap["transition_kind"].eq(
        "not_observed_across_consecutive_calendar_weeks"
    ).all()


@pytest.mark.parametrize("which", ["choices", "support"])
def test_duplicate_registered_keys_fail_closed(which: str) -> None:
    choices, support = synthetic_inputs()
    if which == "choices":
        choices = pd.concat([choices, choices.iloc[[0]]], ignore_index=True)
    else:
        support = pd.concat([support, support.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="repeat"):
        build_vehicle_role_risk_panel(choices, support)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8192):
            digest.update(chunk)
    return digest.hexdigest()


def _synthetic_release(root: Path, *, partial_name: str | None = None) -> tuple[Path, set[Path]]:
    generation = "a" * 64
    pointer = root / "release" / "current.json"
    generation_dir = pointer.parent / "generations" / generation
    generation_dir.mkdir(parents=True)
    artifacts: dict[str, dict[str, str]] = {}
    member_paths: set[Path] = set()
    for name, filename in ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES.items():
        member = generation_dir / filename
        final_content = f"complete-{name}".encode()
        member.write_bytes(final_content[:-1] if name == partial_name else final_content)
        member_paths.add(member)
        provenance = {
            "artefact": str(member),
            "artefact_bytes": len(final_content),
            "artefact_sha256": hashlib.sha256(final_content).hexdigest(),
        }
        provenance_path = sidecar_path(member)
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        artifacts[name] = {
            "filename": filename,
            "sha256": hashlib.sha256(final_content).hexdigest(),
            "provenance_sha256": _sha(provenance_path),
        }
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "kind": ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
                "schema_version": ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
                "generation_id": generation,
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return pointer, member_paths


def test_partial_member_identity_fails_before_any_member_hash_or_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer, members = _synthetic_release(tmp_path, partial_name="choice_audit")
    real_hash = role_risk.file_sha256
    hashed_members: list[Path] = []

    def observed_hash(path: Path) -> str:
        if Path(path) in members:
            hashed_members.append(Path(path))
        return real_hash(path)

    monkeypatch.setattr(role_risk, "file_sha256", observed_hash)
    with pytest.raises(RuntimeError, match="no member was read"):
        assert_complete_endpoint_release(pointer)
    assert hashed_members == []


def test_complete_synthetic_release_passes_size_then_hash(tmp_path: Path) -> None:
    pointer, members = _synthetic_release(tmp_path)
    admitted = assert_complete_endpoint_release(pointer)
    assert set(admitted.artifacts.values()) == members

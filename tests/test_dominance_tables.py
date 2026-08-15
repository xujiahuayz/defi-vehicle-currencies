from __future__ import annotations

import json
from pathlib import Path

import pytest

from ddvc.dominance_tables import (
    parse_newcommands,
    render_dominance_rotation,
    render_pair_composition,
    render_usdt_transition,
)
from ddvc.provenance import sidecar_path, verify


ROOT = Path(__file__).resolve().parents[1]
EXHIBITS = ROOT / "output" / "exhibits"
TABLES = ROOT / "output" / "tables"


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_checked_in_fragments_equal_their_named_renderers() -> None:
    rotation = render_dominance_rotation(
        _jsonl(EXHIBITS / "intermediation_complexity_rival.jsonl")
    )
    pair = render_pair_composition(
        parse_newcommands(
            (EXHIBITS / "vehicle_transition_pair_decomposition_deck_values.tex").read_text(
                encoding="utf-8"
            )
        ),
        _jsonl(EXHIBITS / "vehicle_transition_pair_fixed_effects.jsonl"),
    )
    usdt = render_usdt_transition(
        parse_newcommands(
            (EXHIBITS / "provisional_results_deck_values.tex").read_text(
                encoding="utf-8"
            )
        )
    )

    assert (TABLES / "dominance_rotation.tex").read_text(encoding="utf-8") == rotation
    assert (TABLES / "pair_composition.tex").read_text(encoding="utf-8") == pair
    assert (TABLES / "usdt_transition.tex").read_text(encoding="utf-8") == usdt


def test_rotation_and_usdt_values_are_exact() -> None:
    rotation = (TABLES / "dominance_rotation.tex").read_text(encoding="utf-8")
    assert "Dollar-weighted routes (20\\% agreement)" in rotation
    assert "16.9\\% & 42.3\\% & $+25.4$ pp ($1.05$ pp)" in rotation
    assert "32.7\\% & 76.5\\% & $+43.9$ pp ($2.02$ pp)" in rotation

    usdt = (TABLES / "usdt_transition.tex").read_text(encoding="utf-8")
    assert (
        "Count excess-use ratio (2024 full year; 2026 January--June) & 1.06 & 1.23"
        in usdt
    )
    assert (
        "Value-weighted excess-use ratio (2024 full year; 2026 January--June) & 0.59 & 1.42"
        in usdt
    )
    assert "Paired January--June intermediary minus route-endpoint share" in usdt
    assert "$-7.13$ pp & $+8.14$ pp" in usdt


def test_pair_panel_c_contains_all_three_fixed_effect_rows() -> None:
    pair = (TABLES / "pair_composition.tex").read_text(encoding="utf-8")
    assert (
        "All two-leg routes, count share & $+0.22\\ (0.76)$ & 188,520"
        in pair
    )
    assert "Margin or estimate & Estimate in pp & Obs." in pair
    assert (
        "20\\% agreement sample, count share & $+0.32\\ (0.75)$ & 182,834"
        in pair
    )
    assert (
        "20\\% agreement sample, dollar-weighted share & $-1.35\\ (2.19)$ & 182,834"
        in pair
    )
    assert "95\\% CI" not in pair
    assert "0.770" not in pair

    rows = _jsonl(EXHIBITS / "vehicle_transition_pair_fixed_effects.jsonl")
    assert {str(row["metric"]) for row in rows} >= {
        "count_share",
        "matched_strict_count_share",
        "strict_intermediation_value_share",
    }
    for row in rows:
        for field in (
            "confidence_interval_lower",
            "confidence_interval_upper",
            "p_value",
            "p_value_holm",
            "estimator_id",
            "covariance_id",
            "estimand_scope",
            "mechanism_status",
        ):
            assert row[field] is not None


def test_paper_has_one_consumer_and_no_duplicate_inline_body() -> None:
    section = (ROOT / "paper" / "sections" / "03-dominance.tex").read_text(
        encoding="utf-8"
    )
    for stem in ("dominance_rotation", "pair_composition", "usdt_transition"):
        assert section.count(rf"\input{{../output/tables/{stem}.tex}}") == 1
    assert r"\begin{tabular}" not in section
    assert r"\begin{tabularx}" not in section
    assert r"s^{(m)}_{c,y}=\alpha^{(m)}_{c}+\beta^{(m)}\mathbf{1}\{y=2026\}" in section
    assert "2024 is the omitted year" in section
    assert "pair--calendar-date--route-type combination" in section
    assert "number or dollar value of native-plus-stable routes as weights" in section
    assert "clustered by ordered pair and calendar date" in section
    assert "comparison remains descriptive" in section


@pytest.mark.parametrize(
    ("stem", "expected_inputs"),
    [
        (
            "dominance_rotation",
            {
                "output/exhibits/intermediation_complexity_rival.jsonl",
                "data/manifests/output/exhibits/intermediation_complexity_rival.jsonl.prov.json",
            },
        ),
        (
            "pair_composition",
            {
                "output/exhibits/vehicle_transition_pair_decomposition_deck_values.tex",
                "data/manifests/output/exhibits/vehicle_transition_pair_decomposition_deck_values.tex.prov.json",
                "output/exhibits/vehicle_transition_pair_fixed_effects.jsonl",
                "data/manifests/output/exhibits/vehicle_transition_pair_fixed_effects.jsonl.prov.json",
            },
        ),
        (
            "usdt_transition",
            {
                "output/exhibits/provisional_results_deck_values.tex",
                "data/manifests/output/exhibits/provisional_results_deck_values.tex.prov.json",
            },
        ),
    ],
)
def test_generated_table_lineage_is_current(
    stem: str, expected_inputs: set[str]
) -> None:
    for suffix in ("tex", "pdf"):
        artifact = TABLES / f"{stem}.{suffix}"
        assert verify(artifact)["status"] == "ok"
        record = json.loads(sidecar_path(artifact).read_text(encoding="utf-8"))
        assert {str(item["path"]) for item in record["inputs"]} == expected_inputs
        assert record["payload_identity"]["sha256"]
        if stem == "usdt_transition":
            assert "provisional" in record["notes"]
            assert "lineage" in record["notes"]


def test_renderers_reject_missing_or_ambiguous_cells() -> None:
    with pytest.raises(ValueError, match="missing"):
        render_usdt_transition({})
    rows = _jsonl(EXHIBITS / "intermediation_complexity_rival.jsonl")
    with pytest.raises(ValueError, match="exactly one row"):
        render_dominance_rotation(rows + rows)

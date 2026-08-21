from pathlib import Path
import json
import re

import pytest

from ddvc.deck_evidence import (
    audit_audience_text,
    audit_deck_density,
    audit_deck_sources,
    rendered_page_density,
)
from ddvc.latex_text import strip_latex_comments
from scripts.utils.embed_deck_video import inspect_deck_video


ROOT = Path(__file__).resolve().parents[1]
DENSITY_LEDGER = ROOT / "deck" / "density-ledger.json"
DECK_PDF = ROOT / "deck" / "main.pdf"


def write_section(root: Path, source: str) -> None:
    sections = root / "sections"
    sections.mkdir(parents=True)
    (sections / "result.tex").write_text(source, encoding="utf-8")


def test_allows_layout_coordinates_years_and_generated_values(tmp_path: Path) -> None:
    write_section(
        tmp_path,
        r"""
\begin{frame}{Result in 2024}
\input{../output/exhibits/deck_values.tex}
\begin{tikzpicture}
\node at (2.5, 1.0) {\RouteShare};
\end{tikzpicture}
\includegraphics{../output/figures/route_share.pdf}
\end{frame}
""",
    )
    assert audit_deck_sources(tmp_path) == []


def test_rejects_manual_empirical_coordinates(tmp_path: Path) -> None:
    write_section(
        tmp_path,
        r"\addplot[draw=blue] coordinates {(2024,16.9) (2026,42.3)};",
    )
    defects = audit_deck_sources(tmp_path)
    assert [defect.kind for defect in defects] == ["manual_plot_data"]


def test_rejects_literal_measured_values_but_not_comments(tmp_path: Path) -> None:
    write_section(
        tmp_path,
        "% source audit observed 87.4\\%\nVisible estimate: 25.4 pp and 217,003 routes.\n",
    )
    defects = audit_deck_sources(tmp_path)
    assert [defect.kind for defect in defects] == [
        "literal_measurement",
        "literal_measurement",
    ]


def test_plot_table_must_come_from_output(tmp_path: Path) -> None:
    write_section(tmp_path, r"\addplot table {../data/processed/result.csv};")
    defects = audit_deck_sources(tmp_path)
    assert [defect.kind for defect in defects] == ["unowned_plot_table"]


def test_plot_table_under_output_is_allowed(tmp_path: Path) -> None:
    write_section(tmp_path, r"\addplot table {../output/figures/result.csv};")
    assert audit_deck_sources(tmp_path) == []


def test_evidence_managed_frames_require_status_and_sources(tmp_path: Path) -> None:
    write_section(
        tmp_path,
        r"""% EVIDENCE-MANAGED-FILE
% EVIDENCE-STATUS: evolving route result
% EVIDENCE-SOURCES: output/exhibits/result.tex; docs/findings/README.md
\begin{frame}{Result}
\end{frame}

\begin{frame}{Unbound result}
\end{frame}
""",
    )
    defects = audit_deck_sources(tmp_path)
    assert {defect.kind for defect in defects} == {
        "missing_evidence_status",
        "missing_evidence_sources",
    }


def test_field_language_gate_rejects_visible_workflow_jargon_but_allows_comments(
    tmp_path: Path,
) -> None:
    write_section(
        tmp_path,
        "% EVIDENCE-STATUS: internal scientific verdict\n"
        r"\begin{frame}{Result}\evidencekicker{Scientific verdict}\end{frame}",
    )
    defects = audit_deck_sources(tmp_path)
    assert [defect.kind for defect in defects] == ["audience_workflow_jargon"]
    assert "verdict" in defects[0].detail


def test_common_support_value_is_not_an_audience_measure_name(tmp_path: Path) -> None:
    defects = audit_audience_text(
        "The right panel reports common-support value.",
        path=tmp_path / "main.pdf",
    )
    assert [defect.kind for defect in defects] == ["audience_workflow_jargon"]
    assert "sample construction" in defects[0].detail


def test_field_language_gate_rejects_candidate_and_screen_language(tmp_path: Path) -> None:
    defects = audit_audience_text(
        "The candidate survives the mechanism screen.",
        path=tmp_path / "main.pdf",
    )
    assert [defect.kind for defect in defects] == [
        "audience_workflow_jargon",
        "audience_workflow_jargon",
    ]


def test_frame_titles_state_results_affirmatively(tmp_path: Path) -> None:
    write_section(tmp_path, r"\begin{frame}{Capital does not lead vehicle use}\end{frame}")
    defects = audit_deck_sources(tmp_path)
    assert [defect.kind for defect in defects] == ["negated_frame_title"]


def test_visual_managed_frames_require_object_form_and_job(tmp_path: Path) -> None:
    write_section(
        tmp_path,
        r"""% VISUAL-MANAGED-FILE
% VISUAL-FUNCTION: vehicle path | transaction trace | reveal observable mechanics
\begin{frame}{Real route}
\end{frame}

\begin{frame}{Unspecified visual}
\end{frame}
""",
    )
    defects = audit_deck_sources(tmp_path)
    assert [defect.kind for defect in defects] == ["missing_visual_function"]


def write_density_ledger(tmp_path: Path, allowances: list[dict[str, object]], **overrides: object) -> Path:
    ledger = {
        "schema_version": 1,
        "budget_words": 55,
        "hard_ceiling_words": 70,
        "core_frame_limit": 13,
        "core_frame_allowance": 2,
        "appendix_first_page": 3,
        "appendix_title": "Appendix map",
        "page_allowances": allowances,
    }
    ledger.update(overrides)
    path = tmp_path / "deck-density-ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    return path


def stub_pages(monkeypatch: pytest.MonkeyPatch, pages: list[tuple[str, int, int]]) -> None:
    monkeypatch.setattr("ddvc.deck_evidence.rendered_page_density", lambda _path: pages)


def test_density_gate_holds_an_unlisted_page_to_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_pages(
        monkeypatch,
        [("Title", 40, 20), ("Dense result", 68, 20), ("Appendix map", 40, 0)],
    )
    defects = audit_deck_density(DECK_PDF, write_density_ledger(tmp_path, []))
    assert [defect.kind for defect in defects] == ["deck_density_over_budget"]
    assert "68 visible words" in defects[0].detail


def test_density_gate_counts_the_exhibit_note_under_its_own_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = write_density_ledger(tmp_path, [])
    stub_pages(monkeypatch, [("Title", 40, 54), ("Result", 40, 12), ("Appendix map", 9, 0)])
    assert audit_deck_density(DECK_PDF, ledger) == []

    stub_pages(monkeypatch, [("Title", 40, 82), ("Result", 40, 12), ("Appendix map", 9, 0)])
    defects = audit_deck_density(DECK_PDF, ledger)
    assert [defect.kind for defect in defects] == ["deck_density_hard_ceiling"]
    assert "82 note words" in defects[0].detail


def test_core_density_cannot_be_grandfathered_above_the_hard_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = write_density_ledger(
        tmp_path,
        [{"page": 2, "title": "Dense result", "words": 96, "note_words": 20}],
    )
    stub_pages(monkeypatch, [("Title", 40, 0), ("Dense result", 96, 20), ("Appendix map", 9, 0)])
    defects = audit_deck_density(DECK_PDF, ledger)
    assert [defect.kind for defect in defects] == ["deck_density_hard_ceiling"]


def test_density_gate_fails_when_a_recorded_page_moves_in_either_direction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = write_density_ledger(
        tmp_path,
        [{"page": 2, "title": "Dense result", "words": 68, "note_words": 20}],
    )
    stub_pages(monkeypatch, [("Title", 40, 0), ("Dense result", 68, 20), ("Appendix map", 9, 0)])
    assert audit_deck_density(DECK_PDF, ledger) == []

    stub_pages(monkeypatch, [("Title", 40, 0), ("Dense result", 69, 20), ("Appendix map", 9, 0)])
    grew = audit_deck_density(DECK_PDF, ledger)
    assert [defect.kind for defect in grew] == ["deck_density_ledger_stale"]
    assert "grew to 69" in grew[0].detail

    stub_pages(monkeypatch, [("Title", 40, 0), ("Dense result", 67, 20), ("Appendix map", 9, 0)])
    fell = audit_deck_density(DECK_PDF, ledger)
    assert [defect.kind for defect in fell] == ["deck_density_ledger_stale"]
    assert "fell to 67" in fell[0].detail


def test_density_gate_requires_a_paid_down_page_to_leave_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = write_density_ledger(
        tmp_path,
        [{"page": 2, "title": "Dense result", "words": 50, "note_words": 20}],
    )
    stub_pages(monkeypatch, [("Title", 40, 0), ("Dense result", 50, 20), ("Appendix map", 9, 0)])
    defects = audit_deck_density(DECK_PDF, ledger)
    assert [defect.kind for defect in defects] == ["deck_density_ledger"]
    assert "delete the row" in defects[0].detail


def test_density_gate_catches_a_renamed_page_and_a_moved_appendix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = write_density_ledger(
        tmp_path,
        [{"page": 2, "title": "Dense result", "words": 68, "note_words": 20}],
    )
    stub_pages(monkeypatch, [("Title", 40, 0), ("Renamed result", 68, 20), ("Appendix map", 9, 0)])
    renamed = audit_deck_density(DECK_PDF, ledger)
    assert [defect.kind for defect in renamed] == ["deck_density_ledger"]
    assert "'Renamed result'" in renamed[0].detail

    stub_pages(
        monkeypatch,
        [("Title", 40, 0), ("Dense result", 68, 20), ("A new core frame", 9, 0), ("Appendix map", 9, 0)],
    )
    moved = audit_deck_density(DECK_PDF, ledger)
    assert [defect.kind for defect in moved] == ["deck_density_ledger"]
    assert "appendix boundary moved" in moved[0].detail


def test_live_deck_density_matches_its_recorded_debt_exactly() -> None:
    assert audit_deck_density(DECK_PDF, DENSITY_LEDGER) == []
    ledger = json.loads(DENSITY_LEDGER.read_text(encoding="utf-8"))
    pages = rendered_page_density(DECK_PDF)
    recorded = {int(row["page"]) for row in ledger["page_allowances"]}
    over = {
        number
        for number, (_title, slide, note) in enumerate(pages, start=1)
        if slide > ledger["budget_words"] or note > ledger["budget_words"]
    }
    assert recorded == over


def test_v1_architecture_deck_values_match_the_admitted_source_tables() -> None:
    from scripts.tabulate.build_v1_architecture_deck_values import (
        load_inputs,
        render_v1_architecture_deck_values,
    )

    binding = (
        ROOT / "output" / "exhibits" / "v1_architecture_deck_values.tex"
    ).read_text(encoding="utf-8")
    assert binding == render_v1_architecture_deck_values(*load_inputs())


def test_deck_states_units_scopes_and_primary_protocol_sources() -> None:
    results = (ROOT / "deck" / "sections" / "04-results.tex").read_text(
        encoding="utf-8"
    )
    objects = (ROOT / "deck" / "sections" / "02-objects.tex").read_text(
        encoding="utf-8"
    )
    identification = (ROOT / "deck" / "sections" / "01-identification.tex").read_text(
        encoding="utf-8"
    )
    appendix = (ROOT / "deck" / "sections" / "90-appendix.tex").read_text(
        encoding="utf-8"
    )
    secondary = (ROOT / "deck" / "sections" / "91-secondary-results.tex").read_text(
        encoding="utf-8"
    )
    decomposition = (
        ROOT / "deck" / "assets" / "vehicle-transition-pair-decomposition.tex"
    ).read_text(encoding="utf-8")

    assert "Routed value requires source, intermediary, and destination values to agree" in results
    assert "Endpoint demand predicts intermediary use" in secondary
    assert "native-WETH-versus-stablecoin routes" in secondary
    assert "common month-days" in secondary
    assert "Matched markets" not in decomposition
    assert "Within-pair change" in decomposition

    visible_identification = strip_latex_comments(identification)
    assert "\\RoutePanelRawSwaps" in visible_identification
    assert "\\RoutePanelCalendarDates" in visible_identification
    assert "\\RoutePanelDeploymentCount" in visible_identification
    assert "Uniswap v1, v2, v3, and v4" in visible_identification
    assert "SushiSwap v2 and v3" in visible_identification
    assert "Curve; Balancer; and Fluid" in visible_identification
    assert "maps every observed Uniswap v1 exchange to its token" in visible_identification
    assert "separate protocol-architecture analysis" not in visible_identification
    assert "Main route sample" in objects
    assert "Uniswap v1/v2/v3/v4" in objects
    assert "SushiSwap v2/v3" in objects
    assert "Fluid" in objects

    assert "https://app.uniswap.org/whitepaper-v4.pdf" in appendix
    assert "add-usdc-as-a-collateral-type-2020-03-17" in appendix
    assert "activate-rwa001-a" in appendix
    assert "fip-188-increase-cr-to-100" in appendix


def test_deck_mechanism_sequence_separates_route_settlement_and_capital() -> None:
    results = (ROOT / "deck" / "sections" / "04-results.tex").read_text(
        encoding="utf-8"
    )
    identification = (ROOT / "deck" / "sections" / "01-identification.tex").read_text(
        encoding="utf-8"
    )
    design = (ROOT / "deck" / "sections" / "03-design.tex").read_text(
        encoding="utf-8"
    )
    secondary = (ROOT / "deck" / "sections" / "91-secondary-results.tex").read_text(
        encoding="utf-8"
    )
    liquidity_asset = (
        ROOT / "deck" / "assets" / "liquidity-quantity-cross-section.tex"
    ).read_text(encoding="utf-8")

    visible_results = strip_latex_comments(results)
    assert "Higher capital predicts lower vehicle use at longer horizons" not in visible_results
    assert "Vehicle use barely changes subsequent capital" not in visible_results
    assert "Deposited capital at" not in visible_results
    assert "\\LiqPredCapRouteDayCoef" not in visible_results
    assert "\\LiqPredRouteCapDayCoef" not in visible_results
    assert "\\LiqPredLongCapRouteCoef" not in visible_results
    visible_secondary = strip_latex_comments(secondary)
    assert "\\BridgeLiquidityHorseRaceDepthCoef" in visible_secondary
    assert "per log point of weak-leg capital" in visible_secondary
    assert "candidate-day" not in visible_secondary

    assert "inventory: exact token holdings" in liquidity_asset
    assert "deposited capital: independently valued holdings" in liquidity_asset
    assert "executable depth: quantity available" in liquidity_asset
    assert "quote quality" in liquidity_asset

    appendix = (ROOT / "deck" / "sections" / "90-appendix.tex").read_text(
        encoding="utf-8"
    )
    assert "https://app.uniswap.org/whitepaper-v4.pdf" in appendix
    assert "V4: shared accounting" in design
    assert "one PoolManager" in design
    assert "the singleton changes where balances settle" in design
    assert "vehicle_dominance_timelapse.mp4" in results
    assert "vehicle_dominance_timelapse_poster.pdf" in results
    assert "run:../output/figures/vehicle_dominance_timelapse.mp4" in results
    assert "Click the film to play in Adobe Acrobat" in results
    assert "\\movie" not in results


def test_deck_pdf_contains_the_film_and_no_external_video_action() -> None:
    mp4 = ROOT / "output" / "figures" / "vehicle_dominance_timelapse.mp4"
    report = inspect_deck_video(DECK_PDF, mp4)
    assert report.richmedia_annotations == 1
    assert report.launch_actions == 0
    assert report.uri_actions == 0
    assert report.embedded_file_size == mp4.stat().st_size
    assert len(report.pages) == 1

    from pypdf import PdfReader

    video_page = PdfReader(DECK_PDF).pages[report.pages[0] - 1]
    assert "Vehicle leadership turns over through time" in video_page.extract_text()


def test_deck_separates_weth_eligibility_from_value_composition() -> None:
    secondary = (ROOT / "deck" / "sections" / "91-secondary-results.tex").read_text(
        encoding="utf-8"
    )
    asset = (
        ROOT / "deck" / "assets" / "vehicle-transition-pair-decomposition.tex"
    ).read_text(encoding="utf-8")
    value_asset = (
        ROOT / "deck" / "assets" / "non-weth-value-composition.tex"
    ).read_text(encoding="utf-8")

    title = "A16. Pair composition contains a mechanical component"
    assert title in secondary
    assert "output/exhibits/route_methodology_heterogeneity.jsonl" in secondary
    assert "grouped-binomial" not in secondary
    assert "endpoint pairs" not in secondary.lower()
    assert "corridors" not in secondary.lower()

    frame_start = secondary.index(rf"\begin{{frame}}{{{title}}}")
    frame_end = secondary.index(r"\end{frame}", frame_start)
    rendered_frame = secondary[frame_start:frame_end]
    assert "provisional" not in rendered_frame.lower()

    assert r"Eligible intermediaries:\\stablecoins" in asset
    assert "All matched pairs" in asset
    assert r"Pairs without\\WETH endpoints" in asset
    assert "cells" not in asset.lower()
    assert r"\WethCountFullChange" in asset
    assert r"\WethCountNoEndpointChange" in asset
    assert r"\WethValueNoEndpointChange" in value_asset
    assert r"\WethValueActivityChange" in value_asset
    assert r"\WethValueWithinChange" in value_asset


def test_weth_frame_evidence_boundary_does_not_drift() -> None:
    secondary = (ROOT / "deck" / "sections" / "91-secondary-results.tex").read_text(
        encoding="utf-8"
    )
    title = "A16. Pair composition contains a mechanical component"
    frame_start = secondary.index(rf"\begin{{frame}}{{{title}}}")
    metadata = secondary[secondary.rfind("% EVIDENCE-STATUS:", 0, frame_start):frame_start]

    status = re.search(r"^% EVIDENCE-STATUS: (.+)$", metadata, flags=re.MULTILINE)
    sources = re.search(r"^% EVIDENCE-SOURCES: (.+)$", metadata, flags=re.MULTILINE)
    assert status
    assert status.group(1).startswith("supporting deterministic")
    assert "validated" not in status.group(1).lower()
    assert sources
    assert "output/exhibits/route_methodology_heterogeneity.jsonl" in sources.group(1)

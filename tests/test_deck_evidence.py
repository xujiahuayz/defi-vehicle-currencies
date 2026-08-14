from pathlib import Path
import re
import subprocess

from ddvc.deck_evidence import audit_audience_text, audit_deck_sources


ROOT = Path(__file__).resolve().parents[1]


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


def test_evidence_managed_frames_require_source_only_status_commit_and_sources(tmp_path: Path) -> None:
    write_section(
        tmp_path,
        r"""% EVIDENCE-MANAGED-FILE
% EVIDENCE-STATUS: evolving route result
% EVIDENCE-COMMIT: 3873fca
% EVIDENCE-SOURCES: output/exhibits/result.tex; docs/findings-freeze.md
\begin{frame}{Result}
\end{frame}

\begin{frame}{Unbound result}
\end{frame}
""",
    )
    defects = audit_deck_sources(tmp_path)
    assert {defect.kind for defect in defects} == {
        "missing_evidence_status",
        "missing_evidence_commit",
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


def test_rendered_text_language_gate_catches_generated_backstage_labels(tmp_path: Path) -> None:
    defects = audit_audience_text(
        "Economic result\nProvenance status: current",
        path=tmp_path / "main.pdf",
    )
    assert [defect.kind for defect in defects] == ["audience_workflow_jargon"]
    assert defects[0].line == 2


def test_common_support_value_is_not_an_audience_measure_name(tmp_path: Path) -> None:
    defects = audit_audience_text(
        "The right panel reports common-support value.",
        path=tmp_path / "main.pdf",
    )
    assert [defect.kind for defect in defects] == ["audience_workflow_jargon"]
    assert "common_support_value" in defects[0].detail


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


def test_v1_architecture_deck_values_match_the_admitted_source_tables() -> None:
    source = (ROOT / "docs" / "finding-v1-forced-vehicle.md").read_text(encoding="utf-8")
    binding = (
        ROOT / "output" / "exhibits" / "v1_architecture_deck_values.tex"
    ).read_text(encoding="utf-8")

    forced = re.search(
        r"\| \*\*token to token, forced via ETH\*\* \| \*\*([\d,]+)\*\*",
        source,
    )
    trade_share = re.search(
        r"\| 2026 \| 13,862,895 \| ([\d.]+)% \| 84\.6% \|",
        source,
    )
    pair_share = re.search(r"\| 2026 \| 34,700 \| ([\d.]+)% \|", source)
    assert forced and trade_share and pair_share
    assert rf"\newcommand{{\VOneForcedRoutes}}{{{forced.group(1)}}}" in binding
    assert rf"\newcommand{{\VTwoWethTradeShare}}{{{trade_share.group(1)}\%}}" in binding
    assert rf"\newcommand{{\VTwoWethNewPairShare}}{{{pair_share.group(1)}\%}}" in binding


def test_deck_states_units_scopes_and_primary_protocol_sources() -> None:
    results = (ROOT / "deck" / "sections" / "04-results.tex").read_text(
        encoding="utf-8"
    )
    objects = (ROOT / "deck" / "sections" / "02-objects.tex").read_text(
        encoding="utf-8"
    )
    appendix = (ROOT / "deck" / "sections" / "90-appendix.tex").read_text(
        encoding="utf-8"
    )
    decomposition = (
        ROOT / "deck" / "assets" / "vehicle-transition-pair-decomposition.tex"
    ).read_text(encoding="utf-8")

    assert "one intermediary episode per route" in results
    assert "total routed value among routes whose source" in results
    assert "Descriptive accounting:" in results
    assert "carries no sampling interval" in results
    assert "native-WETH-versus-stablecoin routes" in results
    assert "on 181 common month-days" in results
    assert "Matched markets" not in decomposition
    assert "Within the same trading pair" in decomposition

    assert "Main route sample" in objects
    assert "V1/V2 architecture supplement" in objects
    assert "multi-asset Curve or Balancer pool" in objects

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
    liquidity_asset = (
        ROOT / "deck" / "assets" / "liquidity-quantity-cross-section.tex"
    ).read_text(encoding="utf-8")

    assert "Does liquidity lead vehicle use---or follow it?" in results
    assert "Capital or provider inflow" in results
    assert "Liquidity supply may attract later routes" in results
    assert "Providers may follow routed demand" in results
    assert "candidate-day" not in results
    assert "exact 1-, 7-, 30-, and 120-day horizons" not in results

    assert "inventory: exact token holdings" in liquidity_asset
    assert "deposited capital: independently valued holdings" in liquidity_asset
    assert "executable depth: quantity available" in liquidity_asset
    assert "quote quality" in liquidity_asset

    assert "V4 can net settlement without removing the vehicle route" not in results
    assert "https://app.uniswap.org/whitepaper-v4.pdf" in identification
    assert "calendar date alone is not treatment" in identification
    assert "V4: shared accounting" in design
    assert "one PoolManager" in design
    assert "the singleton changes the settlement boundary" in design
    assert ".mp4" not in results


def test_deck_separates_weth_eligibility_from_value_composition() -> None:
    results = (ROOT / "deck" / "sections" / "04-results.tex").read_text(
        encoding="utf-8"
    )
    asset = (
        ROOT / "deck" / "assets" / "vehicle-transition-pair-decomposition.tex"
    ).read_text(encoding="utf-8")
    value_asset = (
        ROOT / "deck" / "assets" / "non-weth-value-composition.tex"
    ).read_text(encoding="utf-8")

    title = "WETH-linked trading pairs account for most of the count rotation"
    assert title in results
    assert "output/provisional/route_methodology_heterogeneity.jsonl" in results
    assert "internal_generation=9aa4e1d3" in results
    assert "grouped-binomial" not in results
    assert "Challenger cost advantage predicts subsequent vehicle share" not in results
    assert "The routed-value rotation extends beyond WETH-linked trading pairs" in results

    frame_start = results.index(rf"\begin{{frame}}{{{title}}}")
    frame_end = results.index(r"\end{frame}", frame_start)
    rendered_frame = results[frame_start:frame_end]
    assert "provisional" not in rendered_frame.lower()

    assert "WETH cannot also be the intermediary" in asset
    assert "All matched trading-pair groups" in asset
    assert "Trading-pair groups without WETH endpoints" in asset
    assert "cells" not in asset.lower()
    assert r"\WethCountFullChange" in asset
    assert r"\WethCountNoEndpointChange" in asset
    assert "Exact midpoint identity" in value_asset
    assert r"\WethValueNoEndpointChange" in value_asset
    assert r"\WethValueActivityChange" in value_asset
    assert r"\WethValueWithinChange" in value_asset


def test_page_13_evidence_status_and_binding_commit_do_not_drift() -> None:
    results = (ROOT / "deck" / "sections" / "04-results.tex").read_text(
        encoding="utf-8"
    )
    title = "WETH-linked trading pairs account for most of the count rotation"
    frame_start = results.index(rf"\begin{{frame}}{{{title}}}")
    metadata = results[results.rfind("% EVIDENCE-STATUS:", 0, frame_start):frame_start]

    status = re.search(r"^% EVIDENCE-STATUS: (.+)$", metadata, flags=re.MULTILINE)
    evidence_commit = re.search(
        r"^% EVIDENCE-COMMIT: ([0-9a-f]{40})$",
        metadata,
        flags=re.MULTILINE,
    )
    assert status and status.group(1).startswith("E0 pending clean J0")
    assert "certified" not in status.group(1).lower()
    assert "b21ed0a" not in metadata
    assert evidence_commit
    subprocess.run(
        ["git", "cat-file", "-e", f"{evidence_commit.group(1)}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

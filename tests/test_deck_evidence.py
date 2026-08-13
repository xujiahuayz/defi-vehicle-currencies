from pathlib import Path

from ddvc.deck_evidence import audit_deck_sources


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

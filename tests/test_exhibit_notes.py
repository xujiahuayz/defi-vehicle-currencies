from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PAPER_SECTIONS = ROOT / "paper" / "sections"
DECK_SECTIONS = ROOT / "deck" / "sections"


def _environment_blocks(text: str, environment: str) -> list[str]:
    return re.findall(
        rf"\\begin\{{{environment}\}}(?:\[[^]]*\])?(.*?)\\end\{{{environment}\}}",
        text,
        flags=re.DOTALL,
    )


def _frame_blocks(text: str) -> list[str]:
    return _environment_blocks(text, "frame")


def test_paper_uses_one_shared_note_for_every_empirical_exhibit() -> None:
    main = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    assert r"\noindent\begin{minipage}{\linewidth}" in main
    assert r"\footnotesize\emph{Note:}" in main
    assert r"\makebox[\linewidth][c]" not in main
    assert r"\begin{minipage}{0.90\linewidth}" not in main
    assert r"\raggedright\emph{Note:}" not in main
    assert r"\setlength{\belowcaptionskip}{8pt}" in main

    sections = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PAPER_SECTIONS.glob("*.tex"))
    )
    blocks = _environment_blocks(sections, "table") + _environment_blocks(sections, "figure")
    assert blocks
    for block in blocks:
        assert block.count(r"\exhibitnote{") == 1
        assert block.index(r"\caption{") < min(
            position
            for marker in (
                r"\begin{tabular}",
                r"\input{../output/tables/",
                r"\includegraphics",
                r"\begin{tikzpicture}",
            )
            if (position := block.find(marker)) >= 0
        )

    assert r"\emph{Notes.}" not in sections
    assert not re.search(r"\\footnotesize\s+(?!\\raggedright\\emph\{Note\.\})", sections)


def test_deck_empirical_exhibits_use_the_shared_note_block() -> None:
    main = (ROOT / "deck" / "main.tex").read_text(encoding="utf-8")
    assert r"\noindent\begin{minipage}{\linewidth}" in main
    assert r"\fontsize{6.6}{7.3}\selectfont\color{muted}\emph{Note:}" in main
    assert r"\begin{minipage}{0.94\linewidth}" not in main
    assert r"\makebox[\linewidth][c]" not in main

    sections = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(DECK_SECTIONS.glob("*.tex"))
    )
    empirical_markers = (
        "observed_route_blockscout.png",
        "vehicle_excess_use_transition.pdf",
        "vehicle-transition-pair-decomposition.tex",
        "annual_vehicle_composition_bands.pdf",
        "integration_change_forest.pdf",
        "integration_vehicle_alluvial.pdf",
        r"\DiagnosticN",
        r"\ArchEntrySupportFive",
        "v1_architecture_deck_values.tex",
        "backing-regime-heatmap.tex",
        "count-value-route-widths.tex",
    )
    empirical_frames = [
        frame for frame in _frame_blocks(sections)
        if any(marker in frame for marker in empirical_markers)
    ]
    assert empirical_frames
    for frame in empirical_frames:
        assert frame.count(r"\decknote{") == 1

    assert r"\emph{Notes.}" not in sections

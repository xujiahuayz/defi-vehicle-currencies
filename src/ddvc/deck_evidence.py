"""Evidence-boundary checks for scientific presentation sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


MANUAL_PLOT_DATA = re.compile(
    r"\\addplot(?:\s*\[[^\]]*\])?\s*coordinates\s*\{",
    flags=re.DOTALL,
)
MEASURED_LITERAL = re.compile(
    r"(?<![\w.])(?:"
    r"\d{1,3}(?:,\d{3})+"
    r"|(?:\d+\.\d+|\$?-\d+\.\d+)\s*(?:\\%|%|pp\b|m\b|bn\b|bps?\b)"
    r"|\\\$[\d,]+(?:\.\d+)?"
    r")",
    flags=re.IGNORECASE,
)
OUTPUT_REFERENCE = re.compile(
    r"(?:\\input|\\includegraphics(?:\[[^\]]*\])?|\\addplot\s+table(?:\[[^\]]*\])?)"
    r"\s*\{?\.\./output/",
)
EVIDENCE_MANAGED_FILE = "EVIDENCE-MANAGED-FILE"
EVIDENCE_STATUS = re.compile(r"(?m)^% EVIDENCE-STATUS:\s*\S.+$")
EVIDENCE_COMMIT = re.compile(r"(?m)^% EVIDENCE-COMMIT:\s*[0-9a-f]{7,40}\s*$")
EVIDENCE_SOURCES = re.compile(r"(?m)^% EVIDENCE-SOURCES:\s*\S.+$")
VISUAL_MANAGED_FILE = "VISUAL-MANAGED-FILE"
VISUAL_FUNCTION = re.compile(r"(?m)^% VISUAL-FUNCTION:\s*\S.+\|\s*\S.+\|\s*\S.+$")

# Audience language is checked separately from scientific validity.  These are
# research-management or software expressions that are absent from, or used in
# a different sense by, the saved finance/economics presentation and paper
# corpus.  The internal evidence metadata is deliberately stripped before this
# check, so the workflow can stay precise without making the audience listen to
# its machinery.
AUDIENCE_JARGON = {
    "verdict": re.compile(r"\bverdicts?\b", flags=re.IGNORECASE),
    "findings_freeze": re.compile(r"\bfindings?[- ]freeze\b", flags=re.IGNORECASE),
    "evidence_gate": re.compile(r"\bevidence[- ]gate\b", flags=re.IGNORECASE),
    "data_pipeline": re.compile(r"\bdata[- ]pipeline\b", flags=re.IGNORECASE),
    "workflow_status": re.compile(r"\bworkflow[- ]status\b", flags=re.IGNORECASE),
    "provenance_status": re.compile(r"\bprovenance[- ]status\b", flags=re.IGNORECASE),
    "scientific_certificate": re.compile(r"\bscientific[- ]certificate\b", flags=re.IGNORECASE),
}


@dataclass(frozen=True)
class DeckEvidenceDefect:
    path: Path
    line: int
    kind: str
    detail: str


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _without_comments(text: str) -> str:
    visible: list[str] = []
    for line in text.splitlines():
        end = len(line)
        for offset, character in enumerate(line):
            if character == "%" and (offset == 0 or line[offset - 1] != "\\"):
                end = offset
                break
        visible.append(line[:end])
    return "\n".join(visible)


def audit_audience_text(text: str, *, path: Path, unit: int = 1) -> list[DeckEvidenceDefect]:
    """Find backstage vocabulary in one audience-visible source or PDF unit."""

    defects: list[DeckEvidenceDefect] = []
    for label, pattern in AUDIENCE_JARGON.items():
        for match in pattern.finditer(text):
            defects.append(
                DeckEvidenceDefect(
                    path=path,
                    line=_line_number(text, match.start()) if "\n" in text else unit,
                    kind="audience_workflow_jargon",
                    detail=(
                        f"{match.group(0)!r} is internal workflow language "
                        f"({label}); use the field-facing scientific statement"
                    ),
                )
            )
    return defects


def audit_rendered_deck(pdf_path: Path) -> list[DeckEvidenceDefect]:
    """Repeat the field-language check on extracted PDF text, page by page."""

    if not pdf_path.is_file():
        return []
    from pypdf import PdfReader

    defects: list[DeckEvidenceDefect] = []
    for page_number, page in enumerate(PdfReader(pdf_path).pages, start=1):
        text = page.extract_text() or ""
        for defect in audit_audience_text(text, path=pdf_path, unit=page_number):
            defects.append(
                DeckEvidenceDefect(
                    path=defect.path,
                    line=page_number,
                    kind=defect.kind,
                    detail=f"rendered page {page_number}: {defect.detail}",
                )
            )
    return defects


def audit_paper_sources(paper_root: Path) -> list[DeckEvidenceDefect]:
    """Find backstage vocabulary in audience-visible manuscript source."""

    defects: list[DeckEvidenceDefect] = []
    paths = [paper_root / "main.tex", *sorted((paper_root / "sections").glob("*.tex"))]
    for path in paths:
        if path.is_file():
            defects.extend(
                audit_audience_text(_without_comments(path.read_text(encoding="utf-8")), path=path)
            )
    return defects


def audit_deck_sources(deck_root: Path) -> list[DeckEvidenceDefect]:
    """Reject scientific values typed into authored slide source."""

    defects: list[DeckEvidenceDefect] = []
    sections = deck_root / "sections"
    paths = sorted(sections.glob("*.tex")) if sections.is_dir() else []
    if (deck_root / "main.tex").is_file():
        paths.insert(0, deck_root / "main.tex")
    for path in paths:
        authored = path.read_text(encoding="utf-8")
        source = _without_comments(authored)
        scientific_section = path.parent == sections
        for match in MANUAL_PLOT_DATA.finditer(source) if scientific_section else ():
            defects.append(
                DeckEvidenceDefect(
                    path=path,
                    line=_line_number(source, match.start()),
                    kind="manual_plot_data",
                    detail="empirical plot coordinates must be generated under output/",
                )
            )
        for match in MEASURED_LITERAL.finditer(source) if scientific_section else ():
            defects.append(
                DeckEvidenceDefect(
                    path=path,
                    line=_line_number(source, match.start()),
                    kind="literal_measurement",
                    detail=f"measured value is typed into slide source: {match.group(0)!r}",
                )
            )
        defects.extend(audit_audience_text(source, path=path))
        for match in re.finditer(r"\\addplot\s+table[^\n]*", source) if scientific_section else ():
            if not OUTPUT_REFERENCE.search(match.group(0)):
                defects.append(
                    DeckEvidenceDefect(
                        path=path,
                        line=_line_number(source, match.start()),
                        kind="unowned_plot_table",
                        detail="plot tables must be read from ../output/",
                    )
                    )
        if VISUAL_MANAGED_FILE in authored:
            frame_starts = list(re.finditer(r"(?m)^\\begin\{frame\}", authored))
            for index, frame in enumerate(frame_starts):
                prior = frame_starts[index - 1].end() if index else 0
                metadata = authored[prior:frame.start()]
                if not VISUAL_FUNCTION.search(metadata):
                    defects.append(
                        DeckEvidenceDefect(
                            path=path,
                            line=_line_number(authored, frame.start()),
                            kind="missing_visual_function",
                            detail=(
                                "frame needs a VISUAL-FUNCTION source comment with "
                                "economic object | visual form | presentation job"
                            ),
                        )
                    )
        if EVIDENCE_MANAGED_FILE in authored:
            frame_starts = list(re.finditer(r"(?m)^\\begin\{frame\}", authored))
            for index, frame in enumerate(frame_starts):
                prior = frame_starts[index - 1].end() if index else 0
                metadata = authored[prior:frame.start()]
                for pattern, kind, detail in (
                    (EVIDENCE_STATUS, "missing_evidence_status", "frame needs an EVIDENCE-STATUS source comment"),
                    (EVIDENCE_COMMIT, "missing_evidence_commit", "frame needs an EVIDENCE-COMMIT source comment"),
                    (EVIDENCE_SOURCES, "missing_evidence_sources", "frame needs an EVIDENCE-SOURCES source comment"),
                ):
                    if not pattern.search(metadata):
                        defects.append(
                            DeckEvidenceDefect(
                                path=path,
                                line=_line_number(authored, frame.start()),
                                kind=kind,
                                detail=detail,
                            )
                        )
    return defects

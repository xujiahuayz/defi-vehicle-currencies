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


def audit_deck_sources(deck_root: Path) -> list[DeckEvidenceDefect]:
    """Reject scientific values typed into authored slide source."""

    defects: list[DeckEvidenceDefect] = []
    sections = deck_root / "sections"
    for path in sorted(sections.glob("*.tex")) if sections.is_dir() else ():
        source = _without_comments(path.read_text(encoding="utf-8"))
        for match in MANUAL_PLOT_DATA.finditer(source):
            defects.append(
                DeckEvidenceDefect(
                    path=path,
                    line=_line_number(source, match.start()),
                    kind="manual_plot_data",
                    detail="empirical plot coordinates must be generated under output/",
                )
            )
        for match in MEASURED_LITERAL.finditer(source):
            defects.append(
                DeckEvidenceDefect(
                    path=path,
                    line=_line_number(source, match.start()),
                    kind="literal_measurement",
                    detail=f"measured value is typed into slide source: {match.group(0)!r}",
                )
            )
        for match in re.finditer(r"\\addplot\s+table[^\n]*", source):
            if not OUTPUT_REFERENCE.search(match.group(0)):
                defects.append(
                    DeckEvidenceDefect(
                        path=path,
                        line=_line_number(source, match.start()),
                        kind="unowned_plot_table",
                        detail="plot tables must be read from ../output/",
                    )
                )
    return defects

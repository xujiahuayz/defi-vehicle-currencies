"""Evidence-boundary and density checks for scientific presentation sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
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
    "common_support_value": re.compile(
        r"\bcommon(?:[-\s]+)support(?:[-\s]+)value\b",
        flags=re.IGNORECASE,
    ),
}


# Slide density is measured on the rendered page, not on the authored source.
# The rendered page is what a listener actually reads, it cannot be gamed by
# moving prose into a TikZ node or a coloured box, and it excludes Beamer
# `\note{}` presenter notes for free because those are not typeset in the
# delivered deck.  Numerals are deliberately not words: axis ticks, cell values
# and estimates are exhibit apparatus, and a chart is not made denser by having
# a longer y axis.  The repeated footline is subtracted before counting.
DECK_FOOTER = "Making Dominant Vehicle Currencies"
DENSITY_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
DENSITY_LEDGER_FIELDS = (
    "schema_version",
    "budget_words",
    "hard_ceiling_words",
    "core_frame_limit",
    "appendix_first_page",
    "appendix_title",
    "page_allowances",
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


LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}


def _normalize_rendered(text: str) -> str:
    for ligature, expansion in LIGATURES.items():
        text = text.replace(ligature, expansion)
    return text


def rendered_page_density(pdf_path: Path) -> list[tuple[str, int, int]]:
    """Return the title, spoken-prose words, and exhibit-note words of every page.

    The exhibit note set by `\\decknote` is measured apart from the rest of the
    page.  It is the exhibit's own apparatus -- unit, construction, encoding,
    sample, weighting, inference -- which the deck workflow requires on every
    empirical frame, so counting it against the slide-prose budget would make the
    budget unreachable for exactly the frames that carry evidence.  It is still
    counted, under its own cap, so that prose cannot be hidden there.
    """

    from pypdf import PdfReader

    pages: list[tuple[str, int, int]] = []
    for page in PdfReader(pdf_path).pages:
        text = _normalize_rendered(page.extract_text() or "").replace(DECK_FOOTER, " ")
        title = next((line.strip() for line in text.splitlines() if line.strip()), "")
        marker = text.rfind("\nNote:")
        body, note = (text, "") if marker < 0 else (text[:marker], text[marker:])
        pages.append((title, len(DENSITY_WORD.findall(body)), len(DENSITY_WORD.findall(note))))
    return pages


def _density_ledger_defect(path: Path, detail: str, *, line: int = 1) -> DeckEvidenceDefect:
    return DeckEvidenceDefect(path=path, line=line, kind="deck_density_ledger", detail=detail)


def audit_deck_density(pdf_path: Path, ledger_path: Path) -> list[DeckEvidenceDefect]:
    """Hold the delivered deck to its recorded word budget and its recorded debt.

    The venue benchmark in `deck/README.md` is 40-55 visible words a page.
    Pages already above that budget when the check was introduced are carried in
    `deck/density-ledger.json` as an exact, tight allowance: the recorded
    number must equal the measured number, so paying a page down and letting one
    grow are both edits a reader can see in the diff.  Any page not carried in
    the ledger must sit inside the budget, which is what stops the always-ready
    loop from drifting back into density on the next update.
    """

    if not pdf_path.is_file():
        return []
    if not ledger_path.is_file():
        return [_density_ledger_defect(ledger_path, "deck density ledger is absent")]
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [_density_ledger_defect(ledger_path, f"deck density ledger is unreadable: {error}")]
    if not isinstance(ledger, dict) or any(field not in ledger for field in DENSITY_LEDGER_FIELDS):
        missing = [field for field in DENSITY_LEDGER_FIELDS if not isinstance(ledger, dict) or field not in ledger]
        return [_density_ledger_defect(ledger_path, f"deck density ledger lacks required fields: {missing}")]
    if ledger["schema_version"] != 1:
        return [_density_ledger_defect(ledger_path, "deck density ledger schema is not current")]
    budget = int(ledger["budget_words"])
    ceiling = int(ledger["hard_ceiling_words"])
    core_limit = int(ledger["core_frame_limit"])
    core_allowance = int(ledger.get("core_frame_allowance", core_limit))
    if not 0 < budget <= ceiling or core_limit <= 0 or core_allowance <= 0:
        return [_density_ledger_defect(ledger_path, "deck density ledger states an incoherent budget")]

    defects: list[DeckEvidenceDefect] = []
    pages = rendered_page_density(pdf_path)
    allowances: dict[int, dict[str, object]] = {}
    for row in ledger["page_allowances"]:
        if not isinstance(row, dict) or not {"page", "title", "words", "note_words"} <= set(row):
            defects.append(_density_ledger_defect(ledger_path, "deck density allowance row is malformed"))
            continue
        number = int(row["page"])
        if number in allowances:
            defects.append(_density_ledger_defect(ledger_path, f"deck density ledger repeats page {number}"))
            continue
        if not 1 <= number <= len(pages):
            defects.append(_density_ledger_defect(ledger_path, f"deck density ledger names absent page {number}"))
            continue
        allowances[number] = row

    appendix_first = int(ledger["appendix_first_page"])
    if not 1 < appendix_first <= len(pages):
        defects.append(_density_ledger_defect(ledger_path, f"deck density ledger names an absent appendix page {appendix_first}"))
    elif pages[appendix_first - 1][0] != str(ledger["appendix_title"]):
        defects.append(
            _density_ledger_defect(
                ledger_path,
                "deck density ledger appendix boundary moved: page "
                f"{appendix_first} is {pages[appendix_first - 1][0]!r}, not {str(ledger['appendix_title'])!r}",
            )
        )
    else:
        core_frames = appendix_first - 1
        if core_frames != core_allowance:
            defects.append(
                _density_ledger_defect(
                    ledger_path,
                    f"core deck has {core_frames} frames against a recorded allowance of {core_allowance}"
                    f" (venue limit {core_limit})",
                )
            )

    for number, (title, slide, note) in enumerate(pages, start=1):
        row = allowances.get(number)
        if row is None:
            for measured, label in ((slide, "visible words"), (note, "words of exhibit note")):
                if measured > budget:
                    defects.append(
                        DeckEvidenceDefect(
                            path=pdf_path,
                            line=number,
                            kind="deck_density_over_budget",
                            detail=(
                                f"page {number} ({title!r}) carries {measured} {label} against a "
                                f"budget of {budget}; move the explanation into a Beamer note or "
                                f"record the page in {ledger_path.name}"
                            ),
                        )
                    )
            continue
        if str(row["title"]) != title:
            defects.append(
                _density_ledger_defect(
                    ledger_path,
                    f"page {number} is {title!r}, but the ledger carries {str(row['title'])!r}",
                    line=number,
                )
            )
        recorded_slide = int(row["words"])
        recorded_note = int(row["note_words"])
        if recorded_slide <= budget and recorded_note <= budget:
            defects.append(
                _density_ledger_defect(
                    ledger_path,
                    f"page {number} is recorded at {recorded_slide} visible and {recorded_note} note"
                    f" words, both inside the budget of {budget}; delete the row so the page can"
                    " never grow again",
                    line=number,
                )
            )
            continue
        for measured, recorded, label in (
            (slide, recorded_slide, "visible words"),
            (note, recorded_note, "words of exhibit note"),
        ):
            if measured != recorded:
                direction = "grew to" if measured > recorded else "fell to"
                defects.append(
                    DeckEvidenceDefect(
                        path=pdf_path,
                        line=number,
                        kind="deck_density_ledger_stale",
                        detail=(
                            f"page {number} ({title!r}) {direction} {measured} {label} against a "
                            f"recorded allowance of {recorded}; the ledger must state the measured"
                            " debt exactly"
                        ),
                    )
                )
    return defects


def write_deck_density_ledger(pdf_path: Path, ledger_path: Path) -> int:
    """Rewrite the recorded debt from the rendered deck and return its page count.

    Every number in the ledger is measured here, so the recorded debt can never
    be a hand-typed allowance that quietly licenses a denser slide.  The budget,
    the ceiling, the venue frame limit and the appendix boundary are carried
    across from the existing ledger; only the measurements are rewritten.
    """

    existing = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
    budget = int(existing.get("budget_words", 55))
    appendix_title = str(existing.get("appendix_title", "Appendix map"))
    pages = rendered_page_density(pdf_path)
    appendix_first = next(
        (number for number, (title, _slide, _note) in enumerate(pages, start=1) if title == appendix_title),
        int(existing.get("appendix_first_page", len(pages))),
    )
    allowances = [
        {"page": number, "title": title, "words": slide, "note_words": note}
        for number, (title, slide, note) in enumerate(pages, start=1)
        if slide > budget or note > budget
    ]
    ledger = {
        "schema_version": 1,
        "purpose": (
            "Recorded slide-density debt for the always-ready deck. A page absent from "
            "page_allowances must sit inside budget_words; a page present here must measure "
            "exactly its recorded words. Both halves are checked by "
            "scripts/verify/audit_deck_evidence.py against the rendered PDF, so density can only "
            "change through a visible edit to this file. Written by "
            "`scripts/verify/audit_deck_evidence.py --record-density`; never hand-typed."
        ),
        "budget_words": budget,
        "hard_ceiling_words": int(existing.get("hard_ceiling_words", 70)),
        "core_frame_limit": int(existing.get("core_frame_limit", 13)),
        "core_frame_allowance": appendix_first - 1,
        "appendix_first_page": appendix_first,
        "appendix_title": appendix_title,
        "page_allowances": allowances,
    }
    ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(allowances)


def deck_density_summary(pdf_path: Path, ledger_path: Path) -> str:
    """Return the one-line debt statement printed beside the density verdict."""

    if not pdf_path.is_file() or not ledger_path.is_file():
        return "deck density: not measured"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    budget = int(ledger["budget_words"])
    ceiling = int(ledger["hard_ceiling_words"])
    pages = rendered_page_density(pdf_path)
    appendix_first = int(ledger["appendix_first_page"])
    core = sorted(slide for _title, slide, _note in pages[: appendix_first - 1])
    counts = sorted(slide for _title, slide, _note in pages)
    over_budget = [count for count in counts if count > budget]
    return (
        f"deck density: {len(counts)} pages, {appendix_first - 1} core against a limit of "
        f"{int(ledger['core_frame_limit'])}; median {counts[len(counts) // 2]} visible words "
        f"({core[len(core) // 2]} core); {len(over_budget)} over the {budget}-word budget; "
        f"{sum(1 for count in counts if count > ceiling)} over the {ceiling}-word ceiling; "
        f"{sum(count - budget for count in over_budget)} words of recorded debt"
    )

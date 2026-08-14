import re
from pathlib import Path

from ddvc.latex_text import included_section_files


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "paper/main.tex"


def reader_text(path: Path) -> str:
    return "\n".join(
        "" if line.lstrip().startswith("%") else line
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def test_paper_uses_acro_for_automated_market_maker() -> None:
    main = MAIN.read_text(encoding="utf-8")
    assert r"\usepackage{acro}" in main
    assert r"\DeclareAcronym{amm}{short=AMM,long=automated market maker}" in main
    introduction = (ROOT / "paper/sections/01-introduction.tex").read_text(encoding="utf-8")
    assert r"\ac{amm}" in introduction

    for path in included_section_files(MAIN, fallback_dir=ROOT / "paper/sections"):
        visible_source = reader_text(path)
        assert not re.search(r"\bAMM\b", visible_source), path
        assert not re.search(r"automated[- ]market[- ]maker", visible_source, re.IGNORECASE), path

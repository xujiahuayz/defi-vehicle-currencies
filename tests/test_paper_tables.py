from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ddvc import paper_tables


def test_write_table_artifacts_writes_tex_and_pdf(
    tmp_path: Path,
) -> None:
    def render(_latex: str, output: Path, *, preview_width: str | None = None) -> Path:
        assert preview_width == "8in"
        output.write_bytes(b"pdf")
        return output

    with (
        patch.object(paper_tables, "TABLES_DIR", tmp_path / "tables"),
        patch.object(paper_tables, "render_standalone_pdf", side_effect=render),
        patch.object(paper_tables, "LOGGER"),
    ):
        tex, pdf = paper_tables.write_table_artifacts(
            "lineage_example",
            "table body\n",
            preview_width="8in",
        )

    assert tex.read_text(encoding="utf-8") == "table body\n"
    assert pdf.read_bytes() == b"pdf"

def test_table_lineage_readme_covers_every_active_manuscript_table() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "scripts" / "tabulate" / "README.md").read_text(
        encoding="utf-8"
    )
    sections = (
        root / "paper" / "sections" / "02-setting.tex",
        root / "paper" / "sections" / "03-dominance.tex",
        root / "paper" / "sections" / "05-rivals.tex",
        root / "paper" / "sections" / "08-appendix.tex",
    )
    labels = []
    for path in sections:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(r"\label{tab:"):
                labels.append(line.removeprefix(r"\label{").removesuffix("}"))
    assert len(labels) == 19
    assert all(f"`{label}`" in readme for label in labels)


def test_table_artifact_rerender_replaces_both_outputs(tmp_path: Path) -> None:
    def render(_latex: str, output: Path, *, preview_width: str | None = None) -> Path:
        output.write_bytes(b"pdf")
        return output

    with (
        patch.object(paper_tables, "TABLES_DIR", tmp_path / "tables"),
        patch.object(paper_tables, "render_standalone_pdf", side_effect=render),
        patch.object(paper_tables, "LOGGER"),
    ):
        tex, pdf = paper_tables.write_table_artifacts(
            "rendered_example",
            "table body\n",
        )

    assert tex.read_text(encoding="utf-8") == "table body\n"
    assert pdf.read_bytes() == b"pdf"

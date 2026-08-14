from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import call, patch

from ddvc import paper_tables
from ddvc.provenance import sidecar_path


def test_write_table_artifacts_stamps_tex_and_pdf_with_declared_lineage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.parquet"
    source.write_bytes(b"input")

    def render(_latex: str, output: Path, *, preview_width: str | None = None) -> Path:
        assert preview_width == "8in"
        output.write_bytes(b"pdf")
        return output

    with (
        patch.object(paper_tables, "TABLES_DIR", tmp_path / "tables"),
        patch.object(paper_tables, "render_standalone_pdf", side_effect=render),
        patch.object(paper_tables, "stamp") as stamped,
        patch.object(paper_tables, "LOGGER"),
    ):
        tex, pdf = paper_tables.write_table_artifacts(
            "lineage_example",
            "table body\n",
            preview_width="8in",
            inputs=[source],
            code_sources=["src/ddvc/variable_registry.py"],
            notes="inspection only",
        )

    assert tex.read_text(encoding="utf-8") == "table body\n"
    assert pdf.read_bytes() == b"pdf"
    expected_sources = [
        "src/ddvc/paper_tables.py",
        "src/ddvc/variable_registry.py",
        "tests/test_paper_tables.py",
    ]
    assert stamped.call_args_list == [
        call(
            tex,
            code_sources=expected_sources,
            inputs=[source],
            notes="inspection only",
        ),
        call(
            pdf,
            code_sources=expected_sources,
            inputs=[source],
            notes="inspection only",
        ),
    ]


def test_table_lineage_readme_covers_every_active_manuscript_table() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "scripts" / "tabulate" / "README.md").read_text(
        encoding="utf-8"
    )
    sections = (
        root / "paper" / "sections" / "02-setting.tex",
        root / "paper" / "sections" / "03-dominance.tex",
        root / "paper" / "sections" / "08-appendix.tex",
    )
    labels = []
    for path in sections:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(r"\label{tab:"):
                labels.append(line.removeprefix(r"\label{").removesuffix("}"))
    assert len(labels) == 11
    assert all(f"`{label}`" in readme for label in labels)


def test_table_artifact_provenance_binds_payload_and_input(tmp_path: Path) -> None:
    source = tmp_path / "input.jsonl"
    source.write_text('{"value": 1}\n', encoding="utf-8")

    def render(_latex: str, output: Path, *, preview_width: str | None = None) -> Path:
        output.write_bytes(b"pdf")
        return output

    with (
        patch.object(paper_tables, "TABLES_DIR", tmp_path / "tables"),
        patch.object(paper_tables, "render_standalone_pdf", side_effect=render),
        patch.object(paper_tables, "LOGGER"),
    ):
        tex, pdf = paper_tables.write_table_artifacts(
            "stamped_example",
            "table body\n",
            inputs=[source],
        )

    for artifact in (tex, pdf):
        record = json.loads(sidecar_path(artifact).read_text(encoding="utf-8"))
        assert record["artefact"] == str(artifact)
        assert record["payload_identity"]["sha256"]
        assert record["inputs"][0]["sha256"]
        assert "src/ddvc/paper_tables.py" in record["code_sources"]
        assert "tests/test_paper_tables.py" in record["code_sources"]


def test_tabulate_readme_does_not_advertise_withdrawn_sample_as_current() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "scripts" / "tabulate" / "README.md").read_text(
        encoding="utf-8"
    )
    sample_row = next(
        line for line in readme.splitlines() if "`render_sample_coverage.py`" in line
    )
    assert "Blocked" in sample_row
    assert "withdrawn" in sample_row

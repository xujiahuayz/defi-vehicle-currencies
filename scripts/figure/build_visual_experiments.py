#!/usr/bin/env python3
"""Render alternative visual grammars from current route-only exhibits."""

from __future__ import annotations

from pathlib import Path

from ddvc.figure_outputs import load_current_jsonl, publish_pdf
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.visual_experiments import (
    render_annual_composition_bands,
    render_annual_integration_alluvial,
    render_annual_rank_bump,
    render_annual_share_heatmap,
    render_integration_change_forest,
)


TYPE_INPUT = OUTPUT_DIR / "exhibits" / "intermediation_by_type.jsonl"
RIVAL_INPUT = OUTPUT_DIR / "exhibits" / "intermediation_integration_rival.jsonl"
OUTPUTS = OUTPUT_DIR / "figures" / "experiments"
SCRIPT = str(Path(__file__).resolve().relative_to(REPO_ROOT))
CODE_SOURCES = [
    "scripts/figure/build_visual_experiments.py",
    "src/ddvc/visual_experiments.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    by_type, type_identity = load_current_jsonl(TYPE_INPUT, consumer="visual experiment lane")
    rival, rival_identity = load_current_jsonl(RIVAL_INPUT, consumer="visual experiment lane")
    type_outputs = (
        ("annual_vehicle_share_heatmap.pdf", render_annual_share_heatmap, "annual type-by-weighting share matrix; calendar year is descriptive rather than a treatment"),
        ("annual_vehicle_composition_bands.pdf", render_annual_composition_bands, "exhaustive annual count and strict-value vehicle composition; descriptive calendar path"),
        ("integration_vehicle_alluvial.pdf", render_annual_integration_alluvial, "latest-year joint composition by integration scope and intermediary type; selected realised routes, not an integration effect"),
        ("annual_vehicle_rank_bump.pdf", render_annual_rank_bump, "annual vehicle-type rank diagnostic; rank intentionally suppresses share magnitudes and is not a headline result"),
    )
    for filename, renderer, notes in type_outputs:
        output = OUTPUTS / filename
        publish_pdf(
            output,
            renderer=lambda path, render=renderer: render(by_type, path),
            input_path=TYPE_INPUT,
            input_identity=type_identity,
            code_sources=CODE_SOURCES,
            notes=notes,
            script=SCRIPT,
        )
        print(f"wrote {output}")
    forest = OUTPUTS / "integration_change_forest.pdf"
    publish_pdf(
        forest,
        renderer=lambda path: render_integration_change_forest(rival, path),
        input_path=RIVAL_INPUT,
        input_identity=rival_identity,
        code_sources=CODE_SOURCES,
        notes="2024-to-2026 stable-share changes across realised integration scopes with HAC intervals; descriptive because scope is selected",
        script=SCRIPT,
    )
    print(f"wrote {forest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

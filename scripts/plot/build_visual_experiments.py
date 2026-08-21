#!/usr/bin/env python3
"""Render alternative visual grammars from current route-only exhibits."""

from __future__ import annotations

from pathlib import Path

from ddvc.figure_outputs import load_current_jsonl, publish_pdf
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.visual_experiments import (
    render_annual_composition_bands,
    render_annual_integration_alluvial,
    render_deck_annual_composition_bands,
    render_integration_change_forest,
)


TYPE_INPUT = OUTPUT_DIR / "exhibits" / "intermediation_by_type.jsonl"
HALFYEAR_INPUT = OUTPUT_DIR / "exhibits" / "intermediation_by_halfyear.jsonl"
RIVAL_INPUT = OUTPUT_DIR / "exhibits" / "intermediation_integration_rival.jsonl"
OUTPUTS = OUTPUT_DIR / "figures" / "experiments"
SCRIPT = str(Path(__file__).resolve().relative_to(REPO_ROOT))
CODE_SOURCES = [
    "scripts/plot/build_visual_experiments.py",
    "src/ddvc/visual_experiments.py",
    "src/ddvc/figure_outputs.py",
]


def main() -> int:
    by_type, type_identity = load_current_jsonl(TYPE_INPUT, consumer="visual experiment lane")
    by_halfyear, halfyear_identity = load_current_jsonl(
        HALFYEAR_INPUT, consumer="half-year visual experiment lane"
    )
    rival, rival_identity = load_current_jsonl(RIVAL_INPUT, consumer="visual experiment lane")
    type_outputs = (
        ("annual_vehicle_composition_bands.pdf", render_annual_composition_bands, by_halfyear, HALFYEAR_INPUT, halfyear_identity, "half-year native-versus-stable leadership path separated by intermediary episodes and routed value; routed value requires source, intermediary, and destination dollar amounts to agree within 20 percent; other intermediary types remain visible as one exhaustive residual"),
        ("annual_vehicle_composition_bands_deck.pdf", render_deck_annual_composition_bands, by_halfyear, HALFYEAR_INPUT, halfyear_identity, "deck-scale half-year native-versus-stable leadership path with annual tick labels; values and scope match the paper figure, while its legend and value-support note are supplied by the slide"),
        ("integration_vehicle_alluvial.pdf", render_annual_integration_alluvial, by_type, TYPE_INPUT, type_identity, "latest-year joint composition by integration scope and intermediary type; selected realised routes, not an integration effect"),
    )
    for filename, renderer, frame, input_path, input_identity, notes in type_outputs:
        output = OUTPUTS / filename
        publish_pdf(
            output,
            renderer=lambda path, render=renderer, data=frame: render(data, path),
            input_path=input_path,
            input_identity=input_identity,
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

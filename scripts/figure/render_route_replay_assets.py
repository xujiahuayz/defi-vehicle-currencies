#!/usr/bin/env python3
"""Render static PDF and native-browser companions from one admitted route manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import describe_input, install_stamped_artifact, prepare_stamp
from ddvc.route_replay import (
    render_route_replay_html,
    render_route_replay_pdf,
)
from ddvc.runtime import staged_output


DEFAULT_INPUT = OUTPUT_DIR / "exhibits" / "route_replay.json"
DEFAULT_PDF = OUTPUT_DIR / "figures" / "route_replay.pdf"
DEFAULT_HTML = OUTPUT_DIR / "live" / "route_replay.html"
DEFAULT_TEX = OUTPUT_DIR / "exhibits" / "route_replay_deck_values.tex"
CODE_SOURCES = [
    "scripts/figure/render_route_replay_assets.py",
    "src/ddvc/route_replay.py",
]


def _publish(
    output: Path,
    *,
    input_path: Path,
    input_identity: dict[str, object],
    renderer: object,
    notes: str,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with staged_output(output) as temporary:
        rendered = temporary.with_suffix(output.suffix)
        try:
            renderer(rendered)
            prepared = prepare_stamp(
                output,
                content_path=rendered,
                code_sources=CODE_SOURCES,
                described_inputs=[input_identity],
                notes=notes,
                script=str(Path(__file__).resolve().relative_to(REPO_ROOT)),
            )
            install_stamped_artifact(rendered, output, prepared)
        finally:
            rendered.unlink(missing_ok=True)


def _deck_values_tex(manifest: dict[str, object]) -> str:
    """Bind slide labels to the same admitted route used by both renderers."""

    route = manifest.get("route")
    if not isinstance(route, dict):
        raise ValueError("route replay manifest has no route object")
    legs = route.get("legs")
    if not isinstance(legs, list) or len(legs) != 2 or not all(isinstance(leg, dict) for leg in legs):
        raise ValueError("route replay deck values require exactly two legs")

    def amount(value: object) -> str:
        return f"{float(value):,.0f}"

    first, second = legs
    return "\n".join(
        [
            "% Generated from output/exhibits/route_replay.json; do not edit by hand.",
            f"\\newcommand{{\\RouteReplayInputAmount}}{{{amount(first['amount_in'])}}}",
            f"\\newcommand{{\\RouteReplayVehicleAmount}}{{{amount(first['amount_out'])}}}",
            f"\\newcommand{{\\RouteReplayOutputAmount}}{{{amount(second['amount_out'])}}}",
            f"\\newcommand{{\\RouteReplayValue}}{{{amount(route['value_usd'])}}}",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--tex", type=Path, default=DEFAULT_TEX)
    args = parser.parse_args()

    manifest_bytes = args.input.read_bytes()
    manifest = json.loads(manifest_bytes)
    input_identity = describe_input(args.input)
    if args.input.read_bytes() != manifest_bytes:
        raise RuntimeError("route replay manifest changed while rendering")
    _publish(
        args.pdf,
        input_path=args.input,
        input_identity=input_identity,
        renderer=lambda path: render_route_replay_pdf(manifest, path),
        notes="Complete static frame for one admitted two-leg cross-venue transaction trace",
    )
    _publish(
        args.html,
        input_path=args.input,
        input_identity=input_identity,
        renderer=lambda path: path.write_text(
            render_route_replay_html(manifest), encoding="utf-8"
        ),
        notes="Selectable progressive local replay of the same admitted route used by the static frame",
    )
    _publish(
        args.tex,
        input_path=args.input,
        input_identity=input_identity,
        renderer=lambda path: path.write_text(_deck_values_tex(manifest), encoding="utf-8"),
        notes="Presentation labels for the same admitted route used by the static and live traces",
    )
    print(f"wrote {args.pdf}, {args.html}, and {args.tex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

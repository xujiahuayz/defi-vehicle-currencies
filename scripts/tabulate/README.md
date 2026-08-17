# Table renderers

Each renderer reads a named processed panel or exhibit and writes one TeX fragment
under `output/tables/`. Captions, labels, notes, placement and numbering stay in
the manuscript. Edit the renderer or its input, never the generated fragment.

## Current manuscript owners

| Renderer | Paper consumer |
|---|---|
| `render_dominance_rotation.py` | `tab:rotation` |
| `render_pair_composition.py` | `tab:pair-composition` |
| `render_usdt_transition.py` | `tab:usdt-transition` |
| `render_within_day_ladder.py` | `tab:within-day-ladder` |
| `render_routing_technology_windows.py` | `tab:router-windows` |
| `render_venue_technology_rival.py` | `tab:venue-technology` |
| `render_venue_coverage.py` | `tab:app:venues` |

Inline manuscript-owned tables: `tab:panel`, `tab:app:cl`, `tab:app:curve`,
`tab:app:weighted`, `tab:app:support`, `tab:app:curveleg`, and
`tab:app:roundtrip`.

`render_provisional_results_deck_values.py` produces shared macros used by the
paper/deck transition material. It is generated support, not a separate research
claim.

## Inspection-only or blocked

- `render_data_coverage.py`, `render_variable_notation.py`, and
  `render_summary_statistics.py` are inspection utilities without a live
  deliverable consumer.
- `render_sample_coverage.py` is Blocked because its route-cost input is withdrawn.

Some appendix tables remain inline in the manuscript. When touched, give each
empirical table one renderer and replace the inline body in the same change. See
the root [`README.md`](../../README.md) for the project-wide contract.

# Tabulate

Tabulators read processed panels or analysis exhibits and write generated TeX.
Captions, labels, placement, and interpretation stay in the paper/deck source.

## Paper tables

| Owner | Output | Manuscript label |
|---|---|---|
| `render_dominance_rotation.py` | `dominance_rotation.tex/.pdf` | `tab:rotation` |
| `render_pair_composition.py` | `pair_composition.tex/.pdf` | `tab:pair-composition` |
| `render_usdt_transition.py` | `usdt_transition.tex/.pdf` | `tab:usdt-transition` |
| `render_within_day_ladder.py` | `within_day_ladder.tex/.pdf` | `tab:within-day-ladder` |
| `render_routing_technology_windows.py` | `routing_technology_windows.tex/.pdf` | deck/supporting output |
| `render_venue_technology_rival.py` | `venue_technology_rival.tex/.pdf` | deck/supporting output |
| `render_venue_coverage.py` | `venue_coverage.tex/.pdf` | `tab:app:venues` |

The remaining active manuscript tables are intentionally inline because each is
a short validation or sample-description display: `tab:panel`, `tab:app:cl`,
`tab:app:curve`, `tab:app:weighted`, `tab:app:support`, `tab:app:curveleg`, and
`tab:app:roundtrip`. Their evidence-source comments name the machine-readable
analysis exhibit that supplies each value.

## Shared paper/deck values

| Owner | Output family |
|---|---|
| `render_presentation_values.py` | shared current route-result macros |
| `build_vehicle_transition_pair_deck_values.py` | pair decomposition and support macros |
| `build_excess_use_date_fe_deck_values.py` | date-FE result macros |
| `build_backing_regime_deck_values.py` | backing-regime macros |
| `build_fixed_opportunity_deck_values.py` | fixed-opportunity macros |
| `build_liquidity_capital_v2_deck_values.py` | V2 mechanism macros |
| `build_v1_architecture_deck_values.py` | V1 mandate and V2 routing facts |

Each generated file has one owner. Inline empirical tables should be moved to a
renderer when next edited.

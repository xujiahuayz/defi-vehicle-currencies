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
| `render_vehicle_dominance_determinants.py` | `vehicle_dominance_determinants.tex/.pdf` | `tab:vehicle-dominance-determinants` |
| `render_routing_technology_windows.py` | `routing_technology_windows.tex/.pdf` | `tab:router-windows` |
| `render_venue_technology_rival.py` | `venue_technology_rival.tex/.pdf` | `tab:venue-technology` |
| `render_vehicle_formation_regressions.py` | `vehicle_formation_regressions.tex/.pdf` | `tab:formation-regressions` |
| `render_vehicle_mechanism_regressions.py` | `vehicle_mechanism_regressions.tex/.pdf` | `tab:vehicle-mechanism-regressions` |
| `build_bridge_liquidity_deck_values.py` | `bridge_establishment_regressions.tex` | `tab:bridge-establishment` |
| `render_bridge_liquidity_feedback.py` | `bridge_liquidity_feedback.tex/.pdf` | `tab:bridge-feedback` |
| `render_liquidity_provision_regressions.py` | `liquidity_provision_regressions.tex/.pdf` | `tab:lp-behavior-regressions` |
| `render_v4_flash_lp_mechanism.py` | `v4_flash_lp_mechanism.tex/.pdf` | `tab:v4-flash-lp` |
| `render_v4_flash_gap_interactions.py` | `v4_flash_gap_interactions.tex/.pdf` | `tab:v4-flash-gap` |
| `render_v4_flash_gap_flow_interactions.py` | `v4_flash_gap_flow_interactions.tex/.pdf` | `tab:v4-flash-gap-flow` |
| `render_v3_v4_lp_protocol_contrast.py` | `v3_v4_lp_protocol_contrast.tex/.pdf` | `tab:v3-v4-lp-protocol` |
| `render_v3_v4_lp_flow_protocol_contrast.py` | `v3_v4_lp_flow_protocol_contrast.tex/.pdf` | `tab:v3-v4-lp-flow-protocol` |
| `render_v3_v4_tvl_protocol_contrast.py` | `v3_v4_tvl_protocol_contrast.tex/.pdf` | `tab:v3-v4-tvl-protocol` |
| `render_v3_v4_lp_summary.py` | `v3_v4_lp_summary.tex/.pdf` | `tab:v3-v4-lp-summary` |
| `build_endpoint_direction_deck_values.py` | `endpoint_direction_deck_values.tex` | endpoint-direction paper/deck values |
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
| `build_liquidity_provision_behavior_deck_values.py` | exploratory liquidity behavior macros |
| `build_v4_flash_lp_deck_values.py` | V4 flash-accounting LP-position macros |
| `build_v4_flash_gap_deck_values.py` | V4 stable-shortfall flash-accounting interaction macros |
| `build_v3_v4_lp_protocol_deck_values.py` | V3/V4 same-candidate-date LP protocol-contrast macros |
| `build_v3_v4_lp_flow_protocol_deck_values.py` | V3/V4 same-candidate-date LP-flow protocol-contrast macros |
| `build_v3_v4_tvl_protocol_deck_values.py` | V3/V4 same-candidate-date reported-TVL protocol-contrast macros |
| `build_bridge_liquidity_feedback_deck_values.py` | local bridge-depth feedback macros |
| `build_stable_stress_event_deck_values.py` | USDC/SVB stable-identity stress-screen macros |
| `build_vehicle_formation_deck_values.py` | exploratory market-formation macros |
| `build_vehicle_market_size_deck_values.py` | exploratory market-size vehicle-use macros |
| `build_v1_architecture_deck_values.py` | V1 mandate and V2 routing facts |

Each generated file has one owner. Inline empirical tables should be moved to a
renderer when next edited.

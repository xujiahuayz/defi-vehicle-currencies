# Tabulate

Tabulators read processed panels or analysis exhibits and write generated TeX.
Captions, labels, placement, and interpretation stay in the paper/deck source.

## Paper tables

| Owner | Output | Manuscript label |
|---|---|---|
| `render_dominance_rotation.py` | `dominance_rotation.tex/.pdf` | `tab:app:rotation` |
| `render_disconnected_component_boundary.py` | `disconnected_component_boundary.tex/.pdf` and generated values | `tab:app:disconnected` |
| `render_pair_composition.py` | `pair_composition.tex/.pdf`, `pair_market_accounting.tex/.pdf` | `tab:pair-composition`, `tab:app:pair-market-accounting` |
| `render_route_reconstruction_validation.py` | `route_reconstruction_exact_chain_validation.tex/.pdf` | `tab:app:route-validation` |
| `render_entry_vehicle_persistence.py` | `entry_vehicle_persistence.tex/.pdf`, `entry_vehicle_persistence_robustness.tex/.pdf` | `tab:entry-persistence`, `tab:app:entry-persistence-robustness` |
| `render_contestable_vehicle_choice.py` | `contestable_vehicle_choice.tex/.pdf` | `tab:contestable-vehicle-choice` |
| `render_contestable_vehicle_consequences.py` | `contestable_vehicle_consequences.tex/.pdf` | `tab:contestable-vehicle-consequences` |
| `render_usdt_transition.py` | `usdt_transition.tex/.pdf` | `tab:usdt-transition` |
| `render_within_day_ladder.py` | `within_day_ladder.tex/.pdf` | `tab:within-day-ladder` |
| `render_venue_technology_rival.py` | `venue_technology_rival.tex/.pdf` | `tab:venue-technology` |
| `render_vehicle_mechanism_regressions.py` | `vehicle_mechanism_regressions.tex/.pdf` | `tab:vehicle-mechanism-regressions` |
| `render_network_position.py` | `network_position.tex/.pdf` and generated deck values | `tab:network-position` |
| `render_endpoint_direction.py` | `endpoint_direction.tex/.pdf` | `tab:app:endpoint-direction` |
| `build_bridge_liquidity_deck_values.py` | `bridge_establishment_regressions.tex`, `bridge_adoption_pool_margins.tex` | `tab:bridge-establishment`, `tab:bridge-pool-margins` |
| `render_bridge_exante.py` | `bridge_exante.tex/.pdf` | lagged-capital bridge formation table |
| `render_bridge_liquidity_feedback.py` | `bridge_liquidity_feedback.tex/.pdf` | `tab:bridge-feedback` |
| `render_bridge_lp_divergence_risk.py` | `bridge_lp_divergence_risk.tex/.pdf` | `tab:app:bridge-lp-risk` |
| `render_exact_vehicle_frontier.py` | `exact_vehicle_frontier.tex/.pdf` and generated values | `tab:app:exact-vehicle-frontier` |
| `render_result_resolution_checks.py` | adjacent-year, nonvehicle-endpoint, and priced-challenger tables plus generated values | `tab:app:rotation-boundaries`, `tab:app:entry-price-alignment` |
| `build_endpoint_direction_deck_values.py` | `endpoint_direction_deck_values.tex` | endpoint-direction paper/deck values |
| `build_stable_stable_vehicle_values.py` | `stable_stable_vehicle_values.tex` | stable-to-stable intermediary-identity values |
| `render_venue_coverage.py` | `venue_coverage.tex/.pdf` | `tab:app:venues` |
| `build_v1_architecture_deck_values.py` | `v1_architecture.tex/.pdf` and generated deck values | `tab:app:v1-architecture` |

The remaining active manuscript tables are intentionally inline because each is
a short validation or sample-description display: `tab:panel`, `tab:app:cl`,
`tab:app:curve`, `tab:app:weighted`, `tab:app:support`, `tab:app:curveleg`, and
`tab:app:roundtrip`. Their evidence-source comments name the machine-readable
analysis exhibit that supplies each value.

Renderers for router windows, exploratory formation models, liquidity-provider
comparisons, and V3/V4 results remain available for later work but do not feed
the current manuscript. They should return only when they answer the paper's
economic question more directly than an exhibit already in the main sequence.

## Shared paper/deck values

| Owner | Output family |
|---|---|
| `render_presentation_values.py` | shared current route-result macros |
| `build_vehicle_transition_pair_deck_values.py` | pair decomposition and support macros |
| `build_pair_turnover_lifecycle_values.py` | pair-entry, reactivation, vehicle-role turnover, and exit macros |
| `build_excess_use_date_fe_deck_values.py` | date-FE result macros |
| `build_backing_regime_deck_values.py` | backing-regime macros |
| `build_fixed_opportunity_deck_values.py` | fixed-opportunity macros |
| `build_liquidity_capital_v2_deck_values.py` | V2 mechanism macros |
| `build_liquidity_provision_behavior_deck_values.py` | exploratory liquidity behavior macros |
| `build_v4_flash_lp_deck_values.py` | V4 flash-accounting LP-position macros |
| `build_v4_lp_origin_timing_deck_values.py` | V4 transaction-origin timing macros |
| `build_v4_lp_volatility_state_deck_values.py` | V4 persistent-volatility participation macros |
| `build_v4_flash_gap_deck_values.py` | V4 stable-shortfall flash-accounting interaction macros |
| `build_v3_v4_lp_protocol_deck_values.py` | V3/V4 same-candidate-date LP protocol-contrast macros |
| `build_v3_v4_lp_flow_protocol_deck_values.py` | V3/V4 same-candidate-date LP-flow protocol-contrast macros |
| `build_v3_v4_tvl_protocol_deck_values.py` | V3/V4 same-candidate-date reported-TVL protocol-contrast macros |
| `build_stable_stress_event_deck_values.py` | USDC/SVB stable-identity stress-screen macros |
| `build_vehicle_formation_deck_values.py` | exploratory market-formation macros |
| `build_vehicle_market_size_deck_values.py` | exploratory market-size vehicle-use macros |
| `build_v1_architecture_deck_values.py` | V1 mandate and V2 routing facts; also owns the appendix table above |
| `render_exact_vehicle_frontier.py` | exact pre-transaction vehicle and venue frontier macros |
| `build_entry_vehicle_persistence_values.py` | post-entry persistence and retrading macros |
| `build_contestable_vehicle_choice_values.py` | exact-price, capital, retention, and output-shortfall macros |
| `build_bridge_lp_divergence_risk_deck_values.py` | deck macros for the divergence-risk boundary test |

Each generated file has one owner. Inline empirical tables should be moved to a
renderer when next edited.

# Tabulate

Tabulators read processed panels or analysis exhibits and write generated TeX.
Captions, labels, placement, and interpretation stay in the paper/deck source.

## Paper tables

| Owner | Output | Manuscript label |
|---|---|---|
| `render_dominance_rotation.py` | `dominance_rotation.tex/.pdf` | `tab:app:rotation` |
| `render_disconnected_component_boundary.py` | `disconnected_component_boundary.tex/.pdf` and generated values | `tab:app:disconnected` |
| `render_pair_composition.py` | `pair_composition.tex/.pdf`, `pair_market_accounting.tex/.pdf` | `tab:pair-composition`, `tab:app:pair-market-accounting` |
| `render_pair_composition_materiality.py` | `pair_composition_materiality.tex/.pdf` | `tab:app:pair-materiality` |
| `render_vehicle_rotation_venue_exclusion.py` | `vehicle_rotation_venue_exclusion.tex/.pdf` | `tab:app:venue-exclusion` |
| `render_route_reconstruction_validation.py` | `route_reconstruction_exact_chain_validation.tex/.pdf` | `tab:app:route-validation` |
| `render_v4_route_label_validation.py` | `v4_route_label_validation.tex/.pdf` | `tab:app:v4-route-label-validation` |
| `render_entry_vehicle_persistence.py` | `entry_vehicle_persistence.tex/.pdf`, `entry_vehicle_persistence_robustness.tex/.pdf` | `tab:entry-persistence`, `tab:app:entry-persistence-robustness` |
| `render_contestable_vehicle_choice.py` | `contestable_vehicle_choice.tex/.pdf` | `tab:contestable-vehicle-choice`, `tab:app:contestable-vehicle-choice` |
| `render_capital_price_transmission.py` | `capital_price_transmission.tex/.pdf` | `tab:capital-price-transmission`; common-support capital-to-exact-output, established-pair retention, and price-crossing evidence |
| `render_first_contestable_vehicle_choice.py` | `first_contestable_vehicle_choice.tex/.pdf` and generated values | `tab:first-contestable-choice`, `tab:app:first-contestable-choice` |
| `render_price_rank_crossing.py` | `price_rank_crossing.tex/.pdf` and generated values | `tab:price-rank-crossing`, `tab:app:price-rank-crossing` |
| `render_contestable_vehicle_consequences.py` | `contestable_vehicle_consequences.tex/.pdf` | `tab:contestable-vehicle-consequences`, `tab:app:contestable-vehicle-consequences` |
| `render_gas_adjusted_vehicle_consequences.py` | `gas_adjusted_vehicle_consequences.tex`, `gas_adjusted_vehicle_consequences_appendix.tex`, and generated values | panel D of `tab:contestable-vehicle-consequences`; appendix validation and bounds in `tab:app:gas-adjusted-validation` |
| `render_usdt_transition.py` | `usdt_transition.tex/.pdf` | `tab:usdt-transition`, `tab:app:usdt-excess-use` |
| `render_within_day_ladder.py` | `within_day_ladder.tex/.pdf` | `tab:within-day-ladder` |
| `render_vehicle_mechanism_regressions.py` | `vehicle_mechanism_regressions.tex/.pdf` | `tab:vehicle-mechanism-regressions` |
| `render_network_position.py` | `network_position.tex/.pdf` and generated deck values | `tab:network-position` |
| `render_network_centrality_robustness.py` | `network_centrality_robustness.tex/.pdf` | `tab:app:network-centrality-robustness` |
| `render_endpoint_direction.py` | `endpoint_direction.tex/.pdf` | `tab:app:endpoint-direction` |
| `build_bridge_liquidity_deck_values.py` | `bridge_establishment_regressions.tex`, `bridge_adoption_pool_margins.tex` | `tab:app:bridge-persistent-support`, `tab:bridge-pool-margins` |
| `render_bridge_adoption_risk_set.py` | `bridge_adoption_risk_set.tex/.pdf` and generated values | `tab:bridge-adoption-risk` |
| `render_bridge_exante.py` | `bridge_exante.tex/.pdf` | `tab:app:bridge-establishment` |
| `render_stablecoin_supply_lp.py` | `stablecoin_supply_lp.tex/.pdf` | `tab:app:stablecoin-supply-lp` |
| `render_bridge_lp_divergence_risk.py` | `bridge_lp_divergence_risk.tex/.pdf` | `tab:app:bridge-lp-risk` |
| `render_bridge_lp_flow_before_use.py` | `bridge_lp_flow_before_use.tex/.pdf` | `tab:app:bridge-lp-flow-before-use` |
| `render_eth_stress_supply_transmission.py` | `eth_stress_supply_transmission.tex/.pdf` and generated values | `tab:app:eth-stress-supply-transmission`; weekly LP flows, monthly capital--price--choice links, and six-hour ETH-decline exact-route estimates |
| `render_eth_decline_v2_accounting.py` | `eth_decline_v2_accounting.tex/.pdf` and generated values | `tab:app:eth-decline-v2-accounting` |
| `render_v3_lp_provider_formation.py` | `v3_lp_provider_formation.tex/.pdf` and generated values | `tab:v3-provider-formation` |
| `render_v3_lp_launch_supply.py` | `v3_lp_launch_supply.tex/.pdf` and generated values | `tab:app:v3-lp-launch-supply` |
| `render_exact_vehicle_frontier.py` | `exact_vehicle_frontier.tex/.pdf` and generated values | `tab:app:exact-vehicle-frontier` |
| `render_result_resolution_checks.py` | adjacent-year and nonvehicle-endpoint tables plus generated values | `tab:app:rotation-boundaries` |
| `build_endpoint_direction_deck_values.py` | `endpoint_direction_deck_values.tex` | endpoint-direction paper/deck values |
| `build_stable_stable_vehicle_values.py` | `stable_stable_vehicle_values.tex` | stable-to-stable intermediary-identity values |
| `render_venue_coverage.py` | `venue_coverage.tex/.pdf` | `tab:app:venues` |
| `build_v1_architecture_deck_values.py` | `v1_architecture.tex/.pdf` and generated deck values | `tab:app:v1-architecture` |

The remaining active manuscript tables are intentionally inline because each is
a short validation or sample-description display: `tab:panel`, `tab:app:cl`,
`tab:app:curve`, `tab:app:weighted`, `tab:app:support`, `tab:app:curveleg`, and
`tab:app:roundtrip`. Their evidence-source comments name the machine-readable
analysis exhibit that supplies each value.

Renderers for the superseded entry-price alignment, venue-family comparison,
route-depth feedback, router windows, exploratory formation models,
liquidity-provider comparisons, and V3/V4 results remain available for later
work but do not feed the current manuscript. They should return only when they
answer the economic question more directly than an exhibit already in the main
sequence.

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

# Analyze

Analysis programs read only `data/processed/`, `data/unified/`, or another named
exhibit and write machine-readable results under `output/exhibits/`. Rendering
belongs in `../plot/` or `../tabulate/`.

| Owner | Output family and current consumer |
|---|---|
| `measure_round_trip_share.py` | `round_trip_share_by_day.jsonl`; paper appendix |
| `run_excess_use_date_fe_ladder.py` | date-FE ladder and screens; paper/deck and figure inputs |
| `run_integration_date_fe_ladder.py` | integration ladder; paper/deck values |
| `run_liquidity_capital_v2_predictability.py` | V2 predictability results, support, and table; paper/deck |
| `run_bridge_liquidity_dominance.py` | local two-leg bridge depth plus first stable-bridge establishment, adoption, and displacement; paper/deck |
| `run_disconnected_component_boundary.py` | connected-component prevalence and component-as-route rotation sensitivity; paper/deck |
| `run_exact_vehicle_frontier.py` | monthly exact pre-transaction route frontier across V2, Sushi V2, and V3; route-cost evidence |
| `run_liquidity_provision_behavior_exploration.py` | exploratory V2 capital-allocation and vehicle-use behavior |
| `run_bridge_liquidity_feedback.py` | exploratory dynamic feedback between local bridge depth and vehicle use |
| `run_mechanism_expansion_exploration.py` | provisional JFE-expansion mechanism regressions and formation summaries |
| `run_route_gas_economics.py` | exploratory receipt-gas hurdle for direct and extra-hop vehicle routes |
| `run_v3_v4_internal_routing_participation.py` | same-candidate-day V3/V4 internal-routing, origin-participation, and persistent-volatility contrasts |
| `run_stable_stress_event.py` | exploratory USDC/SVB stable-vehicle identity stress screen |
| `run_route_heterogeneity.py` | WETH-eligibility and route-scope results plus deck values |
| `run_usdt_integration_decomposition_e0.py` | USDT transition decomposition; pair-decomposition values |
| `run_v1_forced_vehicle_tests.py` | aggregate V1 mandate-removal exhibits and research report |
| `run_v1_forced_vehicle_token_level.py` | token-level V1 checks and findings report |
| `run_vehicle_rotation_composition_e0.py` | pair panel, contribution ledger, decomposition, support, and fixed effects |
| `run_vehicle_transition_e0.py` | backing-regime and fixed-opportunity result/support families |
| `run_vehicle_transition_exploration.py` | umbrella command for the two vehicle-transition owners above |
| `run_vehicle_dominance_mechanism_sweep.py` | provisional driver screen for stable-vehicle gains, turn-ons, and leader switches |
| `run_vehicle_market_size_exploration.py` | exploratory realised-market-size screen for stable vehicle use |
| `run_endpoint_direction_decomposition.py` | exploratory endpoint-direction decomposition of stable vehicle rotation |
| `run_stable_stable_vehicle_decomposition.py` | exploratory issuer decomposition and concentration checks within stable-to-stable endpoint routes |
| `run_venue_coverage_bounds.py` | venue-coverage and excluded-source bounds; appendix and findings |
| `run_venue_technology_rival.py` | venue-technology comparison; paper/deck and generated table |

The historical `e0` suffix denotes an analysis family, not a second output
layer: all retained current results live directly under `output/exhibits/`.

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
| `run_bridge_exante.py` | stable-bridge formation dated only from prior-calendar weak-leg capital, followed by adoption, later use, and relative-depth estimates |
| `run_disconnected_component_boundary.py` | connected-component prevalence and component-as-route rotation sensitivity; paper/deck |
| `run_route_reconstruction_validation.py` | full-day Ethereum-log correction consequences for route assignments, stable shares, and the sampled pair decomposition; technical appendix |
| `run_exact_vehicle_frontier.py` | monthly exact pre-transaction route frontier across V2, Sushi V2, and V3; route-cost evidence |
| `run_contestable_vehicle_choice.py` | exact stable-versus-native route choice with prior incumbent identity and lagged V2 bridge depth |
| `run_price_rank_crossing.py` | event-time incumbent response when the median exact-output ranking reverses, with event-eve weak-leg capital and reverse-crossing checks |
| `run_entry_day_vehicle_choice.py` | exact stable-versus-WETH selection on materially active endpoint-pair entry days, with prior-day weak-leg capital |
| `run_first_contestable_vehicle_choice.py` | first sampled exact two-family opportunity after material pair entry; the retained monthly mode reads the fifteenth-of-month frontier, while `--four-per-month` replays the fixed 1/8/15/22 grid into separate `*_four_per_month` panel, result, and support files |
| `run_entry_vehicle_price_alignment.py` | incumbent vehicle use conditional on the exact pretrade price leader at the observed notional; appendix persistence evidence |
| `run_entry_vehicle_persistence.py` | disjoint days 1--30 and 31--120 post-entry vehicle persistence, retrading-incidence models, and equal-pair/activity-weighted persistence columns |
| `run_liquidity_provision_behavior_exploration.py` | exploratory V2 capital-allocation and vehicle-use behavior |
| `run_bridge_liquidity_feedback.py` | conditional future levels and time-reversed benchmarks for continuing positive-depth bridges |
| `run_bridge_lp_divergence_risk.py` | prior endpoint--vehicle relative-price risk and exact V2/Sushi V2 bridge depth; appendix evidence on LP risk |
| `run_uni_liquidity_mining_expiry.py` | exploratory LP-liquidity response around the fixed 2020 UNI reward start and expiry, including the WBTC-WETH pool-specific first stage; no trade-routing response and no paper or deck consumer unless the stated pool support, balance, and timing checks pass |
| `run_mechanism_expansion_exploration.py` | provisional JFE-expansion mechanism regressions and formation summaries |
| `run_route_gas_economics.py` | exploratory receipt-gas hurdle for direct and extra-hop vehicle routes |
| `run_gas_adjusted_vehicle_consequences.py` | gross and receipt-gas-adjusted output comparison for exact stablecoin-versus-WETH paths |
| `run_network_betweenness.py` | all-route intermediary participation and approximate betweenness in annual atomic-pair graphs; paper/deck |
| `run_v3_v4_internal_routing_participation.py` | same-candidate-day V3/V4 internal-routing, origin-participation, and persistent-volatility contrasts |
| `run_stable_stress_event.py` | exploratory USDC/SVB stable-vehicle identity stress screen |
| `run_route_heterogeneity.py` | WETH-eligibility and route-scope results plus deck values |
| `run_usdt_integration_decomposition_e0.py` | USDT transition decomposition; pair-decomposition values |
| `run_v1_forced_vehicle_tests.py` | aggregate V1 mandate-removal exhibits and research report |
| `run_v1_forced_vehicle_token_level.py` | token-level V1 checks and findings report |
| `run_vehicle_rotation_composition_e0.py` | pair panel, contribution ledger, decomposition, support, and fixed effects |
| `run_pair_turnover_lifecycle.py` | full-history endpoint-pair entry, reactivation, observed exit, and primary vehicle-role turnover split of the one-window contribution |
| `run_vehicle_rotation_adjacent_years.py` | the same decomposition for every adjacent January--June year pair and for the 2024--2026 sample with neither WETH nor a stablecoin at an endpoint; appendix time-window and economic-unit evidence |
| `run_vehicle_transition_e0.py` | backing-regime and fixed-opportunity result/support families |
| `run_vehicle_transition_exploration.py` | umbrella command for the three vehicle-transition analyses above |
| `run_vehicle_dominance_mechanism_sweep.py` | provisional driver screen for stable-vehicle gains, turn-ons, and leader switches |
| `run_vehicle_market_size_exploration.py` | exploratory realised-market-size screen for stable vehicle use |
| `run_endpoint_direction_decomposition.py` | exploratory endpoint-direction decomposition of stable vehicle rotation |
| `run_stable_stable_vehicle_decomposition.py` | exploratory issuer decomposition and concentration checks within stable-to-stable endpoint routes |
| `run_venue_coverage_bounds.py` | venue-coverage and excluded-source bounds; appendix and findings |
| `run_venue_technology_rival.py` | venue-technology comparison; paper/deck and generated table |

The historical `e0` suffix denotes an analysis family, not a second output
layer: all retained current results live directly under `output/exhibits/`.

`run_gas_adjusted_vehicle_consequences.py` subtracts predicted total transaction
gas from both exact two-leg paths on symmetric common support. It holds the
observed transaction-callee class and effective gas price fixed, values gas at
the same-day WETH price, and uses the common endpoint-token price for both
paths. The central comparison uses cell medians; path-specific interquartile
bounds and deterministic held-out prediction accuracy feed only the appendix.
Gross and net-of-gas columns use the same routes, requiring positive predicted
net output for both paths under the central gas estimate.

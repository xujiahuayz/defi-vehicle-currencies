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
| `run_route_heterogeneity.py` | WETH-eligibility and route-scope results plus deck values |
| `run_usdt_integration_decomposition_e0.py` | USDT transition decomposition; pair-decomposition values |
| `run_v1_forced_vehicle_tests.py` | aggregate V1 mandate-removal exhibits and research report |
| `run_v1_forced_vehicle_token_level.py` | token-level V1 checks and findings report |
| `run_vehicle_rotation_composition_e0.py` | pair panel, contribution ledger, decomposition, support, and fixed effects |
| `run_vehicle_transition_e0.py` | backing-regime and fixed-opportunity result/support families |
| `run_vehicle_transition_exploration.py` | umbrella command for the two vehicle-transition owners above |
| `run_venue_coverage_bounds.py` | venue-coverage and excluded-source bounds; appendix and findings |
| `run_venue_technology_rival.py` | venue-technology comparison; paper/deck and generated table |

The historical `e0` suffix denotes an analysis family, not a second output
layer: all retained current results live directly under `output/exhibits/`.

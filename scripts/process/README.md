# Process

These programs transform retained raw or unified records into reusable route
data and analysis-ready panels. Each current panel has one owner.

| Owner | Main output |
|---|---|
| `run_reconstruct.py` | daily routed-swap components under `data/unified/` |
| `build_v1_forced_vehicle.py` | V1 trade classes and exchange-day panels |
| `build_v1_exchange_class_panel.py` | V1 exchange classes and token-to-token pair days |
| `build_v1_exchange_token_crosswalk.py` | exact V1 exchange-to-token map from the retained registry |
| `build_v1_route_case.py` | authenticated V1 case manifest and deck values |
| `build_v2_token_panel.py` | V2 token prices, decimals, and pair-first-trade dates |
| `build_market_state.py` | reusable market-state quality panel |
| `build_token_price_panel.py` | daily route-token prices |
| `build_pool_capital_panel.py` | pool and candidate deposited-capital panels, rejection ledger, and coverage summary |
| `build_liquidity_capital_flow_panels.py` | V2 candidate-day and exact-horizon mechanism panels |
| `build_v3_pool_day_fees.py` | processed Uniswap v3 pool-day fee and volume panel for bounded LP rent-incidence screens |
| `build_v3_internal_routing_candidate_daily.py` | V3 candidate-day internal same-asset routing measured like the V4 routing proxy |
| `build_v3_v4_lp_origin_candidate_daily.py` | comparable nonzero V3/V4 LP actions by vehicle, day, and transaction origin |
| `build_endpoint_candidate_composition.py` | choice, audit, exclusion, and pair-support panels |
| `build_intermediation_by_type.py` | daily intermediary-type panel and its descriptive exhibits |
| `build_intermediation_halfyear.py` | half-year composition from the admitted daily intermediary panel |
| `build_defillama_market_coverage.py` | annual selected-family share of total Ethereum DEX volume from the retained DeFiLlama breakdown |
| `build_vehicle_excess_use.py` | daily excess-use panel and transition exhibits |
| `build_cross_venue_routing_series.py` | daily cross-venue panel, inference, and router windows |
| `measure_quoter_support.py` | V2/V4 quote-support bounds used by validation and the appendix |
| `reconcile_graph_event_order.py` | raw RPC order corrections for ambiguous indexed events |

Raw records remain under `data/raw/`; disposable worker shards belong under
`data/interim/` or a temporary directory and are not downstream inputs.

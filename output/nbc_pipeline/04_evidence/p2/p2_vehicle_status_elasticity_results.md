# P2 (revised): V2->V3 concentrated-liquidity event study, reframed around vehicle-status elasticity

Run at trade-size $10,000 notional, candidate set ['WETH', 'USDC', 'USDT', 'DAI', 'WBTC'], launch date 2021-05-05.

## Sample
| Window | Balanced pairs | Pair-candidate cells | Candidate-level rows | Pair-day rows | First date | Last date |
| --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | 396 | 1,305 | 65,022 | 32,557 | 2020-05-19 | 2022-05-05 |
| +/-24 months | 507 | 1,675 | 97,484 | 48,319 | 2020-05-19 | 2023-05-05 |

## Level difference-in-differences (extends run_v3_architecture_pair_design.py to all 5 candidates)
| Window | Outcome | Units | N | Pairs | Effect | SE | t | p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | Vehicle-candidate route share | pp | 65,022 | 396 | 0.9448 | 0.6402 | 1.48 | 0.141 |
| +/-12 months | Vehicle HHI | HHI (0-1) | 32,557 | 396 | 0.0143 | 0.0123 | 1.16 | 0.246 |
| +/-12 months | Direct-pool depth | ratio | 32,557 | 396 | 0.1203 | 0.0257 | 4.68 | <0.001 |
| +/-24 months | Vehicle-candidate route share | pp | 97,484 | 507 | 1.1276 | 0.7298 | 1.55 | 0.123 |
| +/-24 months | Vehicle HHI | HHI (0-1) | 48,319 | 507 | 0.0226 | 0.0150 | 1.51 | 0.131 |
| +/-24 months | Direct-pool depth | ratio | 48,319 | 507 | 0.1201 | 0.0275 | 4.36 | <0.001 |

## Elasticity test (headline P2 test: |day-to-day change| pre- vs post-V3)
| Window | Outcome | Units | N | Pairs | Effect | SE | t | p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | |day-to-day change| in route share | pp | 63,717 | 394 | -0.6810 | 1.3774 | -0.49 | 0.621 |
| +/-12 months | |day-to-day change| in vehicle HHI | HHI points | 32,161 | 396 | -0.0039 | 0.0063 | -0.62 | 0.535 |
| +/-12 months | |day-to-day change| in direct-pool depth | ratio points | 32,161 | 396 | -0.0023 | 0.0041 | -0.55 | 0.581 |
| +/-24 months | |day-to-day change| in route share | pp | 95,809 | 504 | -0.1241 | 1.5816 | -0.08 | 0.937 |
| +/-24 months | |day-to-day change| in vehicle HHI | HHI points | 47,812 | 507 | -0.0032 | 0.0062 | -0.51 | 0.611 |
| +/-24 months | |day-to-day change| in direct-pool depth | ratio points | 47,812 | 507 | 0.0056 | 0.0048 | 1.15 | 0.250 |

## Elasticity test split by pre-V3 pair volatility proxy (robustness battery item ii)
| Window | Subsample | Outcome | Units | N | Pairs | Effect | SE | t | p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | High pre-V3 volatility | |day-to-day change| in route share | pp | 24,338 | 252 | 0.4028 | 1.7994 | 0.22 | 0.823 |
| +/-12 months | Low pre-V3 volatility | |day-to-day change| in route share | pp | 39,379 | 142 | -1.1501 | 1.7912 | -0.64 | 0.522 |
| +/-12 months | High pre-V3 volatility | |day-to-day change| in vehicle HHI | HHI points | 13,122 | 254 | -0.0030 | 0.0106 | -0.28 | 0.778 |
| +/-12 months | Low pre-V3 volatility | |day-to-day change| in vehicle HHI | HHI points | 19,039 | 142 | -0.0044 | 0.0079 | -0.56 | 0.579 |


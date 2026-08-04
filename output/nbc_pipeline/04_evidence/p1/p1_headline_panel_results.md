# P1 headline panel: L_{k,t}, DirectCostAdvantage_{k,t,q}, VehicleShare_{k,t}

Lead-lag/local-projection system (RQ2 Experiment A operationalization), NOT an IV/event-study causal design -- the one clean exogenous shock found (UNI liquidity-mining launch, 2020-09-18) predates this repo's V3-only L_{k,t} construction and would require new V2-equivalent build work out of scope for this pass. This establishes temporal precedence, not a break in the contemporaneous simultaneity the referee flagged; the common-demand-shock confound is not resolved.

## Sample
| Sample | N rows | Tokens | First date | Last date |
| --- | --- | --- | --- | --- |
| Core (L, D, S all observed) | 9415 | 5 | 2021-05-05 | 2026-06-30 |
|   token=DAI | 1883 | 1 | 2021-05-05 | 2026-06-30 |
|   token=USDC | 1883 | 1 | 2021-05-05 | 2026-06-30 |
|   token=USDT | 1883 | 1 | 2021-05-05 | 2026-06-30 |
|   token=WBTC | 1883 | 1 | 2021-05-05 | 2026-06-30 |
|   token=WETH | 1883 | 1 | 2021-05-05 | 2026-06-30 |

## Results (all 3 equations x 4 horizons x 3 regressors)
| Equation | Outcome (full) | Horizon (days) | Regressor | N | Date clusters | Beta | SE (cluster-by-date) | p (cluster-by-date) | SE (Driscoll-Kraay) | p (Driscoll-Kraay) | SE (month block bootstrap) | Predicted sign (P1) | Sign check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 1 | L | 9,410 | 1,882 | 0.0223 | 0.0015 | <0.001 | 0.0015 | <0.001 | 0.0024 | + | MATCH (p<.05, DK) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 1 | D | 9,410 | 1,882 | -0.0060 | 0.0035 | 0.085 | 0.0036 | 0.095 | 0.0051 | - | sign matches but not sig. (DK p=0.095) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 1 | S | 9,410 | 1,882 | -0.3908 | 0.0180 | <0.001 | 0.0191 | <0.001 | 0.0253 | (no prior) | n/a (no P1 prior) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 7 | L | 9,380 | 1,876 | 0.0261 | 0.0016 | <0.001 | 0.0023 | <0.001 | 0.0030 | + | MATCH (p<.05, DK) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 7 | D | 9,380 | 1,876 | -0.0057 | 0.0036 | 0.117 | 0.0049 | 0.239 | 0.0067 | - | sign matches but not sig. (DK p=0.239) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 7 | S | 9,380 | 1,876 | -0.5120 | 0.0180 | <0.001 | 0.0213 | <0.001 | 0.0272 | (no prior) | n/a (no P1 prior) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 14 | L | 9,345 | 1,869 | 0.0270 | 0.0017 | <0.001 | 0.0030 | <0.001 | 0.0032 | + | MATCH (p<.05, DK) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 14 | D | 9,345 | 1,869 | -0.0122 | 0.0037 | 0.001 | 0.0065 | 0.060 | 0.0084 | - | sign matches but not sig. (DK p=0.060) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 14 | S | 9,345 | 1,869 | -0.5697 | 0.0176 | <0.001 | 0.0280 | <0.001 | 0.0341 | (no prior) | n/a (no P1 prior) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 30 | L | 9,265 | 1,853 | 0.0270 | 0.0016 | <0.001 | 0.0036 | <0.001 | 0.0040 | + | MATCH (p<.05, DK) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 30 | D | 9,265 | 1,853 | -0.0129 | 0.0041 | 0.002 | 0.0084 | 0.123 | 0.0086 | - | sign matches but not sig. (DK p=0.123) |
| outcome=S | Delta VehicleShare_{k,t+tau} (indirect-route volume share through k) | 30 | S | 9,265 | 1,853 | -0.6407 | 0.0157 | <0.001 | 0.0287 | <0.001 | 0.0291 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 1 | S | 9,410 | 1,882 | 0.0189 | 0.0091 | 0.039 | 0.0095 | 0.046 | 0.0094 | + | MATCH (p<.05, DK) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 1 | D | 9,410 | 1,882 | -0.0011 | 0.0029 | 0.709 | 0.0025 | 0.667 | 0.0023 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 1 | L | 9,410 | 1,882 | -0.0090 | 0.0029 | 0.002 | 0.0031 | 0.004 | 0.0033 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 7 | S | 9,380 | 1,876 | 0.0377 | 0.0114 | <0.001 | 0.0146 | 0.010 | 0.0130 | + | MATCH (p<.05, DK) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 7 | D | 9,380 | 1,876 | -0.0121 | 0.0050 | 0.016 | 0.0069 | 0.081 | 0.0076 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 7 | L | 9,380 | 1,876 | -0.0185 | 0.0042 | <0.001 | 0.0077 | 0.016 | 0.0092 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 14 | S | 9,345 | 1,869 | 0.0483 | 0.0148 | 0.001 | 0.0247 | 0.051 | 0.0276 | + | sign matches but not sig. (DK p=0.051) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 14 | D | 9,345 | 1,869 | -0.0198 | 0.0066 | 0.003 | 0.0124 | 0.111 | 0.0138 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 14 | L | 9,345 | 1,869 | -0.0268 | 0.0054 | <0.001 | 0.0144 | 0.064 | 0.0150 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 30 | S | 9,265 | 1,853 | 0.0842 | 0.0154 | <0.001 | 0.0344 | 0.014 | 0.0350 | + | MATCH (p<.05, DK) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 30 | D | 9,265 | 1,853 | -0.0401 | 0.0090 | <0.001 | 0.0247 | 0.104 | 0.0233 | (no prior) | n/a (no P1 prior) |
| outcome=L | Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t}) | 30 | L | 9,265 | 1,853 | -0.0422 | 0.0065 | <0.001 | 0.0269 | 0.116 | 0.0258 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 1 | L | 9,410 | 1,882 | 0.0111 | 0.0058 | 0.054 | 0.0054 | 0.039 | 0.0080 | - | WRONG SIGN (predicted -, got +) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 1 | S | 9,410 | 1,882 | -0.0396 | 0.0157 | 0.012 | 0.0158 | 0.012 | 0.0216 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 1 | D | 9,410 | 1,882 | -0.4923 | 0.0162 | <0.001 | 0.0209 | <0.001 | 0.0322 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 7 | L | 9,380 | 1,876 | 0.0162 | 0.0060 | 0.007 | 0.0085 | 0.057 | 0.0104 | - | WRONG SIGN (predicted -, got +) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 7 | S | 9,380 | 1,876 | -0.0537 | 0.0176 | 0.002 | 0.0241 | 0.026 | 0.0311 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 7 | D | 9,380 | 1,876 | -0.6002 | 0.0164 | <0.001 | 0.0250 | <0.001 | 0.0390 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 14 | L | 9,345 | 1,869 | 0.0168 | 0.0064 | 0.008 | 0.0113 | 0.139 | 0.0131 | - | WRONG SIGN (predicted -, got +) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 14 | S | 9,345 | 1,869 | -0.0287 | 0.0174 | 0.099 | 0.0315 | 0.363 | 0.0375 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 14 | D | 9,345 | 1,869 | -0.6815 | 0.0162 | <0.001 | 0.0307 | <0.001 | 0.0381 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 30 | L | 9,265 | 1,853 | 0.0244 | 0.0062 | <0.001 | 0.0154 | 0.113 | 0.0156 | - | WRONG SIGN (predicted -, got +) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 30 | S | 9,265 | 1,853 | -0.0534 | 0.0197 | 0.007 | 0.0472 | 0.258 | 0.0451 | (no prior) | n/a (no P1 prior) |
| outcome=D | Delta DirectCostAdvantage_{k,t+tau} | 30 | D | 9,265 | 1,853 | -0.7123 | 0.0157 | <0.001 | 0.0359 | <0.001 | 0.0366 | (no prior) | n/a (no P1 prior) |


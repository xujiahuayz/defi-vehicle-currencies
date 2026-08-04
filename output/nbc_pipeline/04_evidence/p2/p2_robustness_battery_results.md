# P2 robustness battery -- placebo/pretrend, volatility split, version construction, fixed windows

Runs the four robustness-battery items named in `output/nbc_pipeline/02_framings/framing_1.md` Section 2 and `docs/research-questions-and-empirical-design.md` RQ4 Experiment A's diagnostics section, against the P2 headline result in `p2_vehicle_status_elasticity_results.md`.

## (i) Placebo launch dates -- sample
| Placebo date | Regime | Balanced pairs | First date | Last date |
| --- | --- | --- | --- | --- |
| 2020-10-01 | pre-period placebo (true regime: pre-V3) | 216 | 2020-06-03 | 2021-01-29 |
| 2020-11-15 | pre-period placebo (true regime: pre-V3) | 232 | 2020-07-18 | 2021-03-15 |
| 2021-01-01 | pre-period placebo (true regime: pre-V3) | 283 | 2020-09-03 | 2021-05-01 |
| 2022-05-05 | post-period placebo (true regime: post-V3, +1yr) | 312 | 2022-01-05 | 2022-09-02 |
| 2023-05-05 | post-period placebo (true regime: post-V3, +2yr) | 246 | 2023-01-05 | 2023-09-02 |

## (i) Placebo launch dates -- level DiD and elasticity test at each fake break date

Real launch is 2021-05-05; every placebo date below uses a +/-120-day window entirely inside one regime (either all pre-launch, or well after launch), so no placebo window straddles the true break. A null result at every placebo date is the falsification check.
| Placebo date | Regime | Outcome | Units | N | Pairs | Effect | SE | t | p | Test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020-10-01 | pre-period placebo (true regime: pre-V3) | Vehicle-candidate route share | pp | 22,064 | 216 | -1.7776 | 0.8978 | -1.98 | 0.049 | Level DiD |
| 2020-10-01 | pre-period placebo (true regime: pre-V3) | Vehicle HHI | HHI (0-1) | 11,031 | 216 | -0.0224 | 0.0113 | -1.98 | 0.049 | Level DiD |
| 2020-10-01 | pre-period placebo (true regime: pre-V3) | Direct-pool depth | ratio | 11,031 | 216 | 0.0554 | 0.0185 | 2.99 | 0.003 | Level DiD |
| 2020-11-15 | pre-period placebo (true regime: pre-V3) | Vehicle-candidate route share | pp | 23,120 | 232 | -0.0901 | 0.5654 | -0.16 | 0.873 | Level DiD |
| 2020-11-15 | pre-period placebo (true regime: pre-V3) | Vehicle HHI | HHI (0-1) | 11,425 | 232 | -0.0261 | 0.0082 | -3.19 | 0.002 | Level DiD |
| 2020-11-15 | pre-period placebo (true regime: pre-V3) | Direct-pool depth | ratio | 11,425 | 232 | 0.0211 | 0.0106 | 1.99 | 0.048 | Level DiD |
| 2021-01-01 | pre-period placebo (true regime: pre-V3) | Vehicle-candidate route share | pp | 24,135 | 283 | 2.0903 | 0.4931 | 4.24 | <0.001 | Level DiD |
| 2021-01-01 | pre-period placebo (true regime: pre-V3) | Vehicle HHI | HHI (0-1) | 11,905 | 283 | 0.0018 | 0.0061 | 0.29 | 0.768 | Level DiD |
| 2021-01-01 | pre-period placebo (true regime: pre-V3) | Direct-pool depth | ratio | 11,905 | 283 | 0.0125 | 0.0070 | 1.77 | 0.077 | Level DiD |
| 2022-05-05 | post-period placebo (true regime: post-V3, +1yr) | Vehicle-candidate route share | pp | 25,258 | 312 | -2.4767 | 0.5117 | -4.84 | <0.001 | Level DiD |
| 2022-05-05 | post-period placebo (true regime: post-V3, +1yr) | Vehicle HHI | HHI (0-1) | 12,857 | 312 | -0.0287 | 0.0067 | -4.27 | <0.001 | Level DiD |
| 2022-05-05 | post-period placebo (true regime: post-V3, +1yr) | Direct-pool depth | ratio | 12,857 | 312 | -0.0255 | 0.0125 | -2.04 | 0.043 | Level DiD |
| 2023-05-05 | post-period placebo (true regime: post-V3, +2yr) | Vehicle-candidate route share | pp | 18,943 | 246 | 2.9108 | 0.6825 | 4.27 | <0.001 | Level DiD |
| 2023-05-05 | post-period placebo (true regime: post-V3, +2yr) | Vehicle HHI | HHI (0-1) | 9,852 | 246 | 0.0150 | 0.0080 | 1.88 | 0.061 | Level DiD |
| 2023-05-05 | post-period placebo (true regime: post-V3, +2yr) | Direct-pool depth | ratio | 9,852 | 246 | -0.0067 | 0.0064 | -1.04 | 0.301 | Level DiD |
| 2020-10-01 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in route share | pp | 21,392 | 215 | 3.4318 | 0.7831 | 4.38 | <0.001 | Elasticity |
| 2020-10-01 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in vehicle HHI | HHI points | 10,815 | 216 | 0.0148 | 0.0051 | 2.88 | 0.004 | Elasticity |
| 2020-10-01 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in direct-pool depth | ratio points | 10,815 | 216 | -0.0192 | 0.0042 | -4.52 | <0.001 | Elasticity |
| 2020-11-15 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in route share | pp | 22,383 | 229 | 4.0151 | 0.8285 | 4.85 | <0.001 | Elasticity |
| 2020-11-15 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in vehicle HHI | HHI points | 11,193 | 232 | 0.0207 | 0.0056 | 3.68 | <0.001 | Elasticity |
| 2020-11-15 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in direct-pool depth | ratio points | 11,193 | 232 | -0.0140 | 0.0043 | -3.28 | 0.001 | Elasticity |
| 2021-01-01 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in route share | pp | 23,227 | 279 | 5.9643 | 0.7606 | 7.84 | <0.001 | Elasticity |
| 2021-01-01 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in vehicle HHI | HHI points | 11,622 | 283 | 0.0187 | 0.0050 | 3.75 | <0.001 | Elasticity |
| 2021-01-01 | pre-period placebo (true regime: pre-V3) | |day-to-day change| in direct-pool depth | ratio points | 11,622 | 283 | -0.0098 | 0.0033 | -2.98 | 0.003 | Elasticity |
| 2022-05-05 | post-period placebo (true regime: post-V3, +1yr) | |day-to-day change| in route share | pp | 24,283 | 308 | -0.6550 | 0.8235 | -0.80 | 0.427 | Elasticity |
| 2022-05-05 | post-period placebo (true regime: post-V3, +1yr) | |day-to-day change| in vehicle HHI | HHI points | 12,545 | 312 | 0.0024 | 0.0066 | 0.37 | 0.711 | Elasticity |
| 2022-05-05 | post-period placebo (true regime: post-V3, +1yr) | |day-to-day change| in direct-pool depth | ratio points | 12,545 | 312 | 0.0219 | 0.0056 | 3.92 | <0.001 | Elasticity |
| 2023-05-05 | post-period placebo (true regime: post-V3, +2yr) | |day-to-day change| in route share | pp | 18,180 | 235 | 1.1534 | 0.7694 | 1.50 | 0.135 | Elasticity |
| 2023-05-05 | post-period placebo (true regime: post-V3, +2yr) | |day-to-day change| in vehicle HHI | HHI points | 9,606 | 246 | 0.0047 | 0.0064 | 0.73 | 0.468 | Elasticity |
| 2023-05-05 | post-period placebo (true regime: post-V3, +2yr) | |day-to-day change| in direct-pool depth | ratio points | 9,606 | 246 | -0.0101 | 0.0048 | -2.11 | 0.036 | Elasticity |

## (i) Joint pretrend tests

Pre-launch portion only. "Pretrend slope" is the linear month trend (mirrors `scripts/run_jfe_identification_extensions.py`'s `v3_event_time_pretrends`); "Joint chi2"/"Joint p" is the omnibus cluster-robust Wald test that ALL pre-period month dummies (relative to the launch-month reference) are jointly zero -- this is what "joint pretrend tests" in the RQ4 diagnostics list calls for and the existing script does not itself compute.
| Window | Outcome | Units | Pretrend N | Pretrend pairs | Pretrend slope | Pretrend slope SE | Pretrend slope t | Pretrend slope p | Joint pretrend months (k) | Joint chi2 | Joint p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | Vehicle-candidate route share | pp | 3,938 | 396 | 0.0012 | 0.1664 | 0.01 | 0.994 | 12 | 64.24 | <0.001 |
| +/-12 months | Vehicle HHI | HHI (0-1) | 1,625 | 396 | -0.0024 | 0.0016 | -1.46 | 0.144 | 12 | 50.52 | <0.001 |
| +/-12 months | Direct-pool depth | ratio | 1,625 | 396 | 0.0176 | 0.0030 | 5.79 | <0.001 | 12 | 60.33 | <0.001 |
| +/-24 months | Vehicle-candidate route share | pp | 4,392 | 507 | 0.0344 | 0.1663 | 0.21 | 0.836 | 12 | 67.48 | <0.001 |
| +/-24 months | Vehicle HHI | HHI (0-1) | 1,837 | 507 | -0.0020 | 0.0016 | -1.28 | 0.202 | 12 | 49.35 | <0.001 |
| +/-24 months | Direct-pool depth | ratio | 1,837 | 507 | 0.0184 | 0.0030 | 6.21 | <0.001 | 12 | 67.51 | <0.001 |

## (ii) Elasticity test split by pre-V3 pair volatility -- extended to both windows and all three outcomes

Extends the headline script's volatility split, which only ran +/-12mo and two of the three outcomes.
| Window | Subsample | Outcome | Units | N | Pairs | Effect | SE | t | p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | High pre-V3 volatility | |day-to-day change| in route share | pp | 24,338 | 252 | 0.4028 | 1.7994 | 0.22 | 0.823 |
| +/-12 months | Low pre-V3 volatility | |day-to-day change| in route share | pp | 39,379 | 142 | -1.1501 | 1.7912 | -0.64 | 0.522 |
| +/-12 months | High pre-V3 volatility | |day-to-day change| in vehicle HHI | HHI points | 13,122 | 254 | -0.0030 | 0.0106 | -0.28 | 0.778 |
| +/-12 months | High pre-V3 volatility | |day-to-day change| in direct-pool depth | ratio points | 13,122 | 254 | -0.0163 | 0.0099 | -1.64 | 0.102 |
| +/-12 months | Low pre-V3 volatility | |day-to-day change| in vehicle HHI | HHI points | 19,039 | 142 | -0.0044 | 0.0079 | -0.56 | 0.579 |
| +/-12 months | Low pre-V3 volatility | |day-to-day change| in direct-pool depth | ratio points | 19,039 | 142 | 0.0047 | 0.0032 | 1.49 | 0.137 |
| +/-24 months | High pre-V3 volatility | |day-to-day change| in route share | pp | 40,232 | 337 | 1.6682 | 1.5891 | 1.05 | 0.295 |
| +/-24 months | Low pre-V3 volatility | |day-to-day change| in route share | pp | 55,577 | 167 | -0.9029 | 2.1139 | -0.43 | 0.670 |
| +/-24 months | High pre-V3 volatility | |day-to-day change| in vehicle HHI | HHI points | 21,403 | 340 | 0.0010 | 0.0083 | 0.12 | 0.906 |
| +/-24 months | High pre-V3 volatility | |day-to-day change| in direct-pool depth | ratio points | 21,403 | 340 | -0.0120 | 0.0111 | -1.09 | 0.278 |
| +/-24 months | Low pre-V3 volatility | |day-to-day change| in vehicle HHI | HHI points | 26,409 | 167 | -0.0052 | 0.0083 | -0.63 | 0.530 |
| +/-24 months | Low pre-V3 volatility | |day-to-day change| in direct-pool depth | ratio points | 26,409 | 167 | 0.0143 | 0.0047 | 3.07 | 0.002 |

## (iii) V2-only / V3-only / best-across-versions route construction

Level DiD on the quote-based route_cost_panel_v2.parquet outcomes (the design `scripts/run_v3_architecture_pair_design.py` uses, generalized here from WETH-only to all five vehicle candidates). "Best-across-versions" is the existing unfiltered panel (whichever AMM version gave the best realized quote per leg); "V2-only"/"V3-only" restrict availability to legs whose realized best source was actually that version -- see module docstring for why this is a disclosed proxy, not a forced re-quote.
| Window | Version construction | Outcome | Units | N | Pairs | Effect | SE | t | p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | Best-across-versions (existing default) | Direct-route availability | pp | 516,240 | 598 | 11.1259 | 2.5658 | 4.34 | <0.001 |
| +/-12 months | Best-across-versions (existing default) | Vehicle-route availability | pp | 516,240 | 598 | 25.9944 | 1.9650 | 13.23 | <0.001 |
| +/-12 months | Best-across-versions (existing default) | No-direct vehicle-route availability | pp | 516,240 | 598 | -2.1639 | 0.8656 | -2.50 | 0.013 |
| +/-12 months | Best-across-versions (existing default) | Direct-route quality | ratio | 516,240 | 598 | 0.1394 | 0.0333 | 4.19 | <0.001 |
| +/-12 months | Best-across-versions (existing default) | Direct cost advantage vs vehicle route | fraction | 193,311 | 414 | -0.0124 | 0.0284 | -0.44 | 0.663 |
| +/-12 months | V2-only route construction | Direct-route availability | pp | 516,240 | 598 | -39.6643 | 2.9616 | -13.39 | <0.001 |
| +/-12 months | V2-only route construction | Vehicle-route availability | pp | 516,240 | 598 | -28.1843 | 3.1402 | -8.98 | <0.001 |
| +/-12 months | V2-only route construction | No-direct vehicle-route availability | pp | 516,240 | 598 | -2.2873 | 0.6321 | -3.62 | <0.001 |
| +/-12 months | V2-only route construction | Direct-route quality | ratio | 322,410 | 517 | 0.0237 | 0.0030 | 7.87 | <0.001 |
| +/-12 months | V2-only route construction | Direct cost advantage vs vehicle route | fraction | 58,049 | 297 | -0.0051 | 0.0224 | -0.23 | 0.821 |
| +/-12 months | V3-only route construction | Direct-route availability | pp | 516,240 | 598 | 50.7902 | 2.9230 | 17.38 | <0.001 |
| +/-12 months | V3-only route construction | Vehicle-route availability | pp | 516,240 | 598 | 28.7681 | 1.9185 | 15.00 | <0.001 |
| +/-12 months | V3-only route construction | No-direct vehicle-route availability | pp | 516,240 | 598 | 8.5205 | 1.0193 | 8.36 | <0.001 |
| +/-12 months | V3-only route construction | Direct-route quality | ratio | 137,670 | 364 | -0.0002 | 0.0002 | -0.99 | 0.321 |
| +/-12 months | V3-only route construction | Direct cost advantage vs vehicle route | fraction | 50,276 | 243 | 0.0000 | 0.0000 | 0.56 | 0.574 |
| +/-24 months | Best-across-versions (existing default) | Direct-route availability | pp | 768,969 | 844 | 11.5096 | 2.6721 | 4.31 | <0.001 |
| +/-24 months | Best-across-versions (existing default) | Vehicle-route availability | pp | 768,969 | 844 | 26.0733 | 2.0775 | 12.55 | <0.001 |
| +/-24 months | Best-across-versions (existing default) | No-direct vehicle-route availability | pp | 768,969 | 844 | -2.3110 | 0.9189 | -2.51 | 0.012 |
| +/-24 months | Best-across-versions (existing default) | Direct-route quality | ratio | 768,969 | 844 | 0.1290 | 0.0330 | 3.91 | <0.001 |
| +/-24 months | Best-across-versions (existing default) | Direct cost advantage vs vehicle route | fraction | 335,103 | 527 | -0.0023 | 0.0270 | -0.09 | 0.932 |
| +/-24 months | V2-only route construction | Direct-route availability | pp | 768,969 | 844 | -43.8880 | 2.9108 | -15.08 | <0.001 |
| +/-24 months | V2-only route construction | Vehicle-route availability | pp | 768,969 | 844 | -29.1629 | 3.1526 | -9.25 | <0.001 |
| +/-24 months | V2-only route construction | No-direct vehicle-route availability | pp | 768,969 | 844 | -2.9050 | 0.6427 | -4.52 | <0.001 |
| +/-24 months | V2-only route construction | Direct-route quality | ratio | 408,407 | 733 | 0.0173 | 0.0057 | 3.01 | 0.003 |
| +/-24 months | V2-only route construction | Direct cost advantage vs vehicle route | fraction | 61,707 | 377 | 0.0007 | 0.0185 | 0.04 | 0.970 |
| +/-24 months | V3-only route construction | Direct-route availability | pp | 768,969 | 844 | 55.3977 | 2.8040 | 19.76 | <0.001 |
| +/-24 months | V3-only route construction | Vehicle-route availability | pp | 768,969 | 844 | 32.2204 | 2.1450 | 15.02 | <0.001 |
| +/-24 months | V3-only route construction | No-direct vehicle-route availability | pp | 768,969 | 844 | 7.9494 | 0.9529 | 8.34 | <0.001 |
| +/-24 months | V3-only route construction | Direct-route quality | ratio | 291,376 | 502 | -0.0002 | 0.0002 | -1.00 | 0.320 |
| +/-24 months | V3-only route construction | Direct cost advantage vs vehicle route | fraction | 122,665 | 306 | 0.0000 | 0.0000 | 0.16 | 0.873 |

## (iv) Fixed 12- and 24-month event windows -- level DiD (reproduction of headline)
| Window | Outcome | Units | N | Pairs | Effect | SE | t | p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | Vehicle-candidate route share | pp | 65,022 | 396 | 0.9448 | 0.6402 | 1.48 | 0.141 |
| +/-12 months | Vehicle HHI | HHI (0-1) | 32,557 | 396 | 0.0143 | 0.0123 | 1.16 | 0.246 |
| +/-12 months | Direct-pool depth | ratio | 32,557 | 396 | 0.1203 | 0.0257 | 4.68 | <0.001 |
| +/-24 months | Vehicle-candidate route share | pp | 97,484 | 507 | 1.1276 | 0.7298 | 1.55 | 0.123 |
| +/-24 months | Vehicle HHI | HHI (0-1) | 48,319 | 507 | 0.0226 | 0.0150 | 1.51 | 0.131 |
| +/-24 months | Direct-pool depth | ratio | 48,319 | 507 | 0.1201 | 0.0275 | 4.36 | <0.001 |

## (iv) Fixed 12- and 24-month event windows -- elasticity test (reproduction of headline)
| Window | Outcome | Units | N | Pairs | Effect | SE | t | p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +/-12 months | |day-to-day change| in route share | pp | 63,717 | 394 | -0.6810 | 1.3774 | -0.49 | 0.621 |
| +/-12 months | |day-to-day change| in vehicle HHI | HHI points | 32,161 | 396 | -0.0039 | 0.0063 | -0.62 | 0.535 |
| +/-12 months | |day-to-day change| in direct-pool depth | ratio points | 32,161 | 396 | -0.0023 | 0.0041 | -0.55 | 0.581 |
| +/-24 months | |day-to-day change| in route share | pp | 95,809 | 504 | -0.1241 | 1.5816 | -0.08 | 0.937 |
| +/-24 months | |day-to-day change| in vehicle HHI | HHI points | 47,812 | 507 | -0.0032 | 0.0062 | -0.51 | 0.611 |
| +/-24 months | |day-to-day change| in direct-pool depth | ratio points | 47,812 | 507 | 0.0056 | 0.0048 | 1.15 | 0.250 |


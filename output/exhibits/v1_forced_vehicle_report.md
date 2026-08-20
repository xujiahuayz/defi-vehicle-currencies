## Test 1. Forced routing left V1 faster than ETH-paired flow
| window_days | swap_tx | eth_paired_tx | t2t_tx | t2t_strict_tx | t2t_share_count | t2t_share_strict | t2t_share_eth_vol | eth_paired_vs_pre | t2t_vs_pre | differential |
|---|---|---|---|---|---|---|---|---|---|---|
| -365 to -183 | 283,590 | 254,321 | 28,298 | 27,428 | 0.0998 | 0.0967 | 0.0655 | 0.3110 | 0.2504 | 1.2420 |
| -182 to -1 | 943,067 | 817,859 | 113,022 | 108,544 | 0.1198 | 0.1151 | 0.1011 | 1.0000 | 1.0000 | 1.0000 |
| 0 to +181 | 653,705 | 589,523 | 60,038 | 54,081 | 0.0918 | 0.0827 | 0.0795 | 0.7208 | 0.5312 | 1.3569 |
| +182 to +364 | 151,773 | 147,010 | 4,434 | 3,217 | 0.0292 | 0.0212 | 0.0219 | 0.1797 | 0.0392 | 4.5818 |
| +365 to +729 | 43,956 | 42,396 | 1,431 | 1,112 | 0.0326 | 0.0253 | 0.0095 | 0.0518 | 0.0127 | 4.0942 |

Monthly, V2 launched 2020-05-05:
| month | n_swap_tx | n_pair | n_token_to_token | t2t_share | t2t_share_strict |
|---|---|---|---|---|---|
| 2019-11 | 69,670 | 58,968 | 10,240 | 0.1470 | 0.1419 |
| 2019-12 | 78,424 | 68,204 | 9,988 | 0.1274 | 0.1240 |
| 2020-01 | 160,209 | 144,143 | 14,869 | 0.0928 | 0.0905 |
| 2020-02 | 198,234 | 174,261 | 21,200 | 0.1069 | 0.1030 |
| 2020-03 | 228,871 | 196,852 | 28,573 | 0.1248 | 0.1177 |
| 2020-04 | 181,215 | 153,441 | 24,147 | 0.1333 | 0.1283 |
| 2020-05 | 279,634 | 243,823 | 34,025 | 0.1217 | 0.1155 |
| 2020-06 | 160,426 | 144,138 | 15,484 | 0.0965 | 0.0842 |
| 2020-07 | 111,154 | 102,704 | 7,713 | 0.0694 | 0.0578 |
| 2020-08 | 80,661 | 75,356 | 4,336 | 0.0538 | 0.0452 |
| 2020-09 | 30,259 | 28,490 | 1,704 | 0.0563 | 0.0487 |
| 2020-10 | 21,952 | 20,513 | 1,242 | 0.0566 | 0.0480 |
| 2020-11 | 23,483 | 22,056 | 1,317 | 0.0561 | 0.0463 |
| 2020-12 | 45,299 | 44,124 | 1,078 | 0.0238 | 0.0183 |
| 2021-01 | 39,306 | 38,100 | 1,139 | 0.0290 | 0.0195 |
| 2021-02 | 23,792 | 23,296 | 443 | 0.0186 | 0.0122 |
| 2021-03 | 12,344 | 12,034 | 282 | 0.0228 | 0.0140 |
| 2021-04 | 7,639 | 7,411 | 216 | 0.0283 | 0.0137 |
| 2021-05 | 9,025 | 8,732 | 264 | 0.0293 | 0.0174 |
| 2021-06 | 7,192 | 6,943 | 234 | 0.0325 | 0.0225 |

### Test 1's confound: the V1 exchange network was thinning
| month | exchanges_traded | exchanges_over_10_trades | t2t_per_eth_paired | ratio_vs_2020_05 | N_vs_2020_05 | excess_over_thinning |
|---|---|---|---|---|---|---|
| 2020-01 | 549 | 243 | 0.1032 | 0.7392 | 0.7764 | 0.9521 |
| 2020-02 | 1,037 | 297 | 0.1217 | 0.8718 | 0.9489 | 0.9188 |
| 2020-03 | 669 | 304 | 0.1451 | 1.0401 | 0.9712 | 1.0709 |
| 2020-04 | 689 | 305 | 0.1574 | 1.1277 | 0.9744 | 1.1573 |
| 2020-05 | 765 | 313 | 0.1395 | 1.0000 | 1.0000 | 1.0000 |
| 2020-06 | 937 | 242 | 0.1074 | 0.7698 | 0.7732 | 0.9957 |
| 2020-07 | 383 | 190 | 0.0751 | 0.5382 | 0.6070 | 0.8866 |
| 2020-08 | 339 | 155 | 0.0575 | 0.4123 | 0.4952 | 0.8326 |
| 2020-09 | 332 | 135 | 0.0598 | 0.4286 | 0.4313 | 0.9937 |
| 2020-10 | 367 | 142 | 0.0605 | 0.4339 | 0.4537 | 0.9564 |
| 2020-11 | 354 | 133 | 0.0597 | 0.4279 | 0.4249 | 1.0070 |
| 2020-12 | 330 | 127 | 0.0244 | 0.1751 | 0.4058 | 0.4315 |
| 2021-03 | 218 | 75 | 0.0234 | 0.1679 | 0.2396 | 0.7008 |
| 2021-06 | 248 | 71 | 0.0337 | 0.2415 | 0.2268 | 1.0647 |
| 2021-12 | 130 | 24 | 0.0365 | 0.2612 | 0.0767 | 3.4068 |

Excess near 1.0 means the fall in token-to-token relative to ETH-paired trade is what the shrinking exchange network predicts on its own, with nothing left for the removal of the mandate to explain.

### Exact V1 exchange-to-token map
The retained V1 exchange registry resolves all 1,744 exchange addresses in the daily panel. It contains 3,086 distinct tokens, including 1,629 whose exchanges traded before V2 launched. Token identities come directly from the V1 subgraph; no price-series matching is used.

(pair-routing panel reused from disk)

### The mandate was withdrawn and native-asset pairing did not retreat
| year | single_leg_trades | weth_pool_share_count | weth_pool_share_value |
|---|---|---|---|
| 2020 | 14,422,786 | 0.9510 | 0.8120 |
| 2021 | 29,430,033 | 0.9522 | 0.9020 |
| 2022 | 17,001,637 | 0.9339 | 0.8507 |
| 2023 | 44,342,924 | 0.9790 | 0.9407 |
| 2024 | 48,367,432 | 0.9773 | 0.8517 |
| 2025 | 36,249,166 | 0.9542 | 0.9409 |
| 2026 | 13,862,895 | 0.9554 | 0.8456 |

Of 477,633 pairs that ever traded on V2, 463,548 (97.1%) include WETH. New pairs by the year they first traded:
| year | new_pairs_first_traded | share_including_weth |
|---|---|---|
| 2020 | 25,400 | 0.8406 |
| 2021 | 30,948 | 0.9292 |
| 2022 | 66,170 | 0.9652 |
| 2023 | 153,967 | 0.9900 |
| 2024 | 90,679 | 0.9798 |
| 2025 | 75,769 | 0.9809 |
| 2026 | 34,700 | 0.9792 |

### Test 2 sample construction
| filter | pair-days remaining | share kept |
|---|---|---|
| pair-days with any V2 trade | 12,713,685 | 1.000 |
| both tokens in the V2 decimals map | 12,613,176 | 0.992 |
| median trade notional in $100-$50,000,000 | 8,520,498 | 0.670 |
| pairs with a direct pool and >= 20 trades and any ETH-routed trade | 2,265 pairs | |

### Pre-V2 V1 tokens and later ETH-route persistence
The outcome is the ETH-routed share of pair-week trades, conditional on a direct V2 pool trading within the trailing 28 days. The reported coefficient is the difference for pairs whose two endpoint tokens both traded on V1 before V2 launched.
| model | weighting | coefficient_pp | standard_error_pp | p_value | observations | pairs | v1_pairs | fixed_effects | controls | clustering |
|---|---|---|---|---|---|---|---|---|---|---|
| calendar_week_and_cohort_fe | equal_pair_week | 14.8772 | 3.9791 | 0.0002 | 90,634 | 2,265 | 228 | calendar week; direct-pool cohort year | route count; weeks since direct pool first traded | pair and calendar week |
| calendar_week_and_cohort_fe | route_count | 12.2705 | 4.2634 | 0.0043 | 90,634 | 2,265 | 228 | calendar week; direct-pool cohort year | route count; weeks since direct pool first traded | pair and calendar week |
| endpoint_fe | equal_pair_week | -2.0864 | 6.0548 | 0.7306 | 90,634 | 2,265 | 228 | both endpoint tokens | calendar month; direct-pool cohort year; route count; weeks since direct pool first traded | pair and calendar week |
| endpoint_fe | route_count | -14.5235 | 7.1539 | 0.0432 | 90,634 | 2,265 | 228 | both endpoint tokens | calendar month; direct-pool cohort year; route count; weeks since direct pool first traded | pair and calendar week |

**A. All V2 pairs**, weeks since a direct pool first traded, with no condition on the direct pool still being usable:
| bucket | pairs | trades | eth_trades | usd_direct | usd_eth | eth_share_count | eth_share_value | eth_share_median_pair | eth_share_mean_pair |
|---|---|---|---|---|---|---|---|---|---|
| wk 0 | 2,265 | 355,017 | 175,701 | 3,178,576,508 | 938,333,151 | 0.3311 | 0.2279 | 0.4444 | 0.4442 |
| wk 1 | 1,897 | 143,042 | 81,141 | 947,695,177 | 438,806,074 | 0.3619 | 0.3165 | 0.6296 | 0.5504 |
| wk 2-3 | 1,911 | 198,147 | 123,521 | 1,521,921,622 | 765,819,751 | 0.3840 | 0.3347 | 0.7400 | 0.5661 |
| wk 4-7 | 1,861 | 306,503 | 177,958 | 3,035,392,421 | 1,171,743,355 | 0.3673 | 0.2785 | 0.8000 | 0.5915 |
| wk 8-12 | 1,746 | 272,257 | 166,206 | 2,613,282,618 | 1,419,041,165 | 0.3791 | 0.3519 | 0.9091 | 0.6224 |
| wk 13-25 | 1,733 | 566,209 | 313,823 | 4,518,309,615 | 2,701,003,011 | 0.3566 | 0.3741 | 0.9310 | 0.6375 |
| wk 26-51 | 1,594 | 824,470 | 281,288 | 6,571,667,173 | 3,715,730,604 | 0.2544 | 0.3612 | 0.9782 | 0.6604 |
| wk 52+ | 1,421 | 2,300,082 | 287,086 | 17,429,755,535 | 1,344,834,023 | 0.1110 | 0.0716 | 0.9910 | 0.6599 |

**B. The same, restricted to pair-days on which the direct pool traded within the trailing 28 days.** This is the specification to read:
| bucket | pairs | trades | eth_trades | usd_direct | usd_eth | eth_share_count | eth_share_value | eth_share_median_pair | eth_share_mean_pair |
|---|---|---|---|---|---|---|---|---|---|
| wk 0 | 2,265 | 355,017 | 175,701 | 3,178,576,508 | 938,333,151 | 0.3311 | 0.2279 | 0.4444 | 0.4442 |
| wk 1 | 1,897 | 143,042 | 81,141 | 947,695,177 | 438,806,074 | 0.3619 | 0.3165 | 0.6296 | 0.5504 |
| wk 2-3 | 1,911 | 198,147 | 123,521 | 1,521,921,622 | 765,819,751 | 0.3840 | 0.3347 | 0.7400 | 0.5661 |
| wk 4-7 | 1,664 | 306,503 | 135,658 | 3,035,392,421 | 955,729,447 | 0.3068 | 0.2395 | 0.6000 | 0.5406 |
| wk 8-12 | 1,190 | 272,257 | 110,459 | 2,613,282,618 | 1,143,304,695 | 0.2886 | 0.3043 | 0.3333 | 0.4374 |
| wk 13-25 | 1,133 | 566,209 | 204,160 | 4,518,309,615 | 2,062,741,570 | 0.2650 | 0.3134 | 0.3182 | 0.4276 |
| wk 26-51 | 935 | 824,470 | 172,007 | 6,571,667,173 | 3,002,301,703 | 0.1726 | 0.3136 | 0.2000 | 0.3806 |
| wk 52+ | 765 | 2,300,082 | 137,287 | 17,429,755,535 | 915,564,111 | 0.0563 | 0.0499 | 0.0772 | 0.2890 |

Of 463,327 pair-days after a direct pool first traded, 325,271 (70.2%) have a live direct pool. Per pair, the median share of days with a live direct pool is 0.89.

Median per-pair ETH-routed share of trade count, by the year the direct pool arrived (rows) and weeks since availability (columns):
| cohort | wk 0 | wk 1-3 | wk 4-12 | wk 13-25 | wk 26-51 | wk 52+ |
|---|---|---|---|---|---|---|
| 2020 | 0.5000 | 0.7778 | 0.8003 | 0.6301 | 0.5000 | 0.1667 |
| 2021 | 0.4762 | 0.6500 | 0.5200 | 0.2255 | 0.0921 | 0.0556 |
| 2022 | 0.0714 | 0.1043 | 0.0551 | 0.0212 | 0.0194 | 0.0101 |
| 2023 | 0.0851 | 0.1250 | 0.1378 | 0.0000 | 0.0000 | 0.0282 |
| 2024 | 0.1429 | 0.4526 | 0.2963 | 0.0486 | 0.0127 | 0.0078 |
| 2025 | 0.0668 | 0.1765 | 0.1702 | 0.0037 | 0.0662 | 0.0002 |
| 2026 | 0.5976 | 0.8931 | 0.9885 | 0.4000 |  |  |

Median per-pair ETH-routed share of trade count, by the calendar year of observation (rows) and weeks since availability (columns):
| cal_year | wk 0 | wk 1-3 | wk 4-12 | wk 13-25 | wk 26-51 | wk 52+ |
|---|---|---|---|---|---|---|
| 2020 | 0.5000 | 0.7647 | 0.8333 | 0.8261 | 0.9074 |  |
| 2021 | 0.4909 | 0.6667 | 0.5333 | 0.4000 | 0.3594 | 0.2890 |
| 2022 | 0.0693 | 0.0833 | 0.0278 | 0.0050 | 0.0286 | 0.0711 |
| 2023 | 0.0851 | 0.1125 | 0.1198 | 0.0121 | 0.0101 | 0.0286 |
| 2024 | 0.1548 | 0.4000 | 0.1667 | 0.0161 | 0.0000 | 0.0253 |
| 2025 | 0.1123 | 0.2308 | 0.1284 | 0.0229 | 0.0086 | 0.0837 |
| 2026 | 0.5976 | 0.8696 | 0.9828 | 0.0667 | 0.0673 | 0.0800 |

Tokens traded on V1 before V2 launched: 1,629. Pairs in the test with both tokens in that pre-V2 set and an active direct alternative: 228.

**Pre-V2 V1-token pairs with an active direct alternative**, weeks since a direct pool first traded:
| bucket | pairs | trades | eth_trades | usd_direct | usd_eth | eth_share_count | eth_share_value | eth_share_median_pair | eth_share_mean_pair |
|---|---|---|---|---|---|---|---|---|---|
| wk 0 | 228 | 1,683 | 4,668 | 2,073,845 | 14,204,190 | 0.7350 | 0.8726 | 0.6667 | 0.5477 |
| wk 1 | 190 | 826.0000 | 4,749 | 847,867 | 15,254,235 | 0.8518 | 0.9473 | 1.0000 | 0.7182 |
| wk 2-3 | 195 | 1,620 | 9,214 | 1,709,925 | 33,081,037 | 0.8505 | 0.9509 | 0.9787 | 0.7240 |
| wk 4-7 | 171 | 3,202 | 10,558 | 3,529,975 | 43,931,789 | 0.7673 | 0.9256 | 0.9615 | 0.7082 |
| wk 8-12 | 124 | 4,757 | 15,214 | 9,229,471 | 96,734,627 | 0.7618 | 0.9129 | 0.9274 | 0.6903 |
| wk 13-25 | 128 | 22,510 | 53,304 | 70,796,265 | 500,638,413 | 0.7031 | 0.8761 | 0.8738 | 0.6804 |
| wk 26-51 | 109 | 62,729 | 63,343 | 570,615,407 | 1,457,195,123 | 0.5024 | 0.7186 | 0.9091 | 0.6420 |
| wk 52+ | 79 | 366,659 | 35,440 | 3,518,414,302 | 402,707,698 | 0.0881 | 0.1027 | 0.5714 | 0.4843 |

Per-pair time from the direct pool's first trade to the ETH-routed share falling below a level:
| threshold | pairs_reaching_it | of_pairs | median_weeks | p75_weeks |
|---|---|---|---|---|
| ETH-routed share < 50% | 1,532 | 2,265 | 0.0000 | 0.0000 |
| ETH-routed share < 25% | 1,382 | 2,265 | 0.0000 | 2.0000 |
| ETH-routed share < 10% | 1,322 | 2,265 | 0.0000 | 4.0000 |

Before the direct pool existed, these pairs traded 444,690 times through ETH and 0 times directly (the latter must be zero by construction and is a check on the window logic).

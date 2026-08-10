# The native-intermediation level comparison: retired as a result, kept as a validation exhibit

> **RETIRED AS A HEADLINE, 2026-08-06, on adversarial review that I then verified myself.** Node I withheld approval and rejected the ESTIMAND, not only its execution, and it was right on every point I checked.
>
> **Three of my own errors, verified.** First, the trade-size gradient I used as the central evidence that this result is not mechanical does not exist: -0.4113 at a $10,000 trade against -0.3218 at $100,000 is a difference of 0.0895 against a standard error of difference of 0.0586, so t is 1.53 and p is 0.127, the full range gives t 1.64, and the $1,000-to-$10,000 leg moves 0.0002. I read a non-significant difference as a finding and then made it load-bearing in four places. Second, the headline triple mixed two specifications: -0.3834 and 11,248,255 rows come from the 7-day window while 177,106 identifying fixed effects comes from the 1-day window, where the coefficient is -0.3837, so the number I quoted belongs to no single specification. Third, my only direct defence against quote collapse, restricting to routes where the direct advantage is within 5% either way, conditions on the magnitude of a monotone function of the outcome, which is selection on the dependent variable, so the project had no answer to its own collapse diagnostic.
>
> **The objection I had not considered, which is the deepest one.** The measured gaps are not yet established as executable costs. A direct pool and a two-leg route on the same chain can be joined in one atomic transaction whose legs revert together, which removes unmatched-leg risk but not financing, gas, competition, reversion, state latency or builder costs. This repository's round-trip statistic, 12.7% of multi-leg routes by count and 21.7% by value on the median of 79 sampled days, establishes a large self-returning population but does not identify every such route as arbitrage or prove continuous capture capacity. Makarov and Schoar devote a full section of a JFE paper to explaining why their 15-to-40% Korean premium survived, naming settlement latency, short-sale unavailability and capital controls. Those exact frictions differ here, but the on-chain alternatives still have to be measured. A median same-state gap of -2,459 basis points is therefore more likely off-support quoter error than economics unless it survives transaction-state, gas, latency and execution bounds; the quoter is validated on swaps that happened and applied to 123.8 million that did not. Adding Curve alone does not address this.
>
> **Why the estimand still cannot lead, corrected 2026-08-09.** The earlier claim that native status is defined by the thickest pairing network was wrong; native status is the platform identity, so the level comparison is not tautological. It still cannot lead because the design failures above invalidate the estimate, and because a static level ranking does not identify persistence or a transition mechanism. What the project must establish is the state in which an asset holds the vehicle role while being strictly cost-dominated, then measure how long that role survives in economic units and time. The 17.9% gross and 30.0% all-in values below are superseded bounded-panel figures and are not publication estimates.
>
> **What survives from this document.** The level comparison becomes a validation exhibit in section 2, demonstrating that the counterfactual machinery reproduces sensible relative costs, and stops being a result. The quoter validations stand on their own: v2 at 0.0000% median error, v3 and v4 at 0.0000% in all four direction-by-tick-crossing cells, Curve at 0.022%, and the R fixest cross-check agreeing to 3.55e-07. Those are infrastructure and they are sound. The reading below is not.

Supersedes the conclusion of `docs/finding-cost-dominance-measured.md`, which said the native advantage was a composition effect, and supersedes the later reading that its point estimate leaned toward the incumbent being the *worse* intermediary. Both were artefacts of a design that identified from 703 pair-day fixed effects out of 22,991, with 96.2% of the panel contributing nothing and a minimum detectable effect near 24 percentage points against an estimate of +0.094. Neither claim should be cited.

## The estimate

Holding the token pair, the time window and the trade size fixed, a direct pool is **38.3 percentage points less likely to beat a native-intermediated route** than to beat a route through another candidate vehicle.

Coefficient **-0.3834**, cluster-robust standard error 0.0372 (0.000), on **177,106 identifying fixed effects** and **11,248,255 routes** across 944 pair clusters. The minimum detectable effect at conventional power is 0.104, so the estimate is nearly four times the smallest effect the design could have found. This is a detected effect and not a bounded null, which is the distinction the earlier version of this analysis could not make.

Built by `scripts/run_vehicle_dominance_hdfe.py` on the multi-venue route-cost panel: 123,765,615 quoted routes over 2,238 days at 24 hours a day, spanning Uniswap v2, SushiSwap v2, Uniswap v3 and Uniswap v4, of which 30,044,831 have both a direct and a vehicle route priced at the same reconstructed state.

## Why identification holds here and did not before

The realised-route panel could only compare intermediaries that *happened to be used* on the same pair the same day, which within a single venue is a coincidence: 703 fixed effects qualified. The counterfactual panel prices the route through **every** vehicle candidate for every pair-window, so a group contains all candidates by construction. That is a 252-fold increase in identifying fixed effects and is the whole reason the sign resolves.

## Robustness of the control window

The absorbed group is the control, so its width is a trade between conditioning and power and is reported rather than chosen. Window widths are integers in days, because a calendar month drifts between 28 and 31 days.

| window | groups | identifying | rows | coefficient | se | p | MDE(80%) |
|---|---|---|---|---|---|---|---|
| 1 day | 636,371 | 177,106 | 11,045,551 | -0.3837 | 0.0373 | 0.000 | 0.104 |
| 3 days | 299,276 | 82,600 | 11,151,003 | -0.3836 | 0.0372 | 0.000 | 0.104 |
| 7 days | 170,047 | 45,630 | 11,248,255 | -0.3834 | 0.0372 | 0.000 | 0.104 |
| 14 days | 108,988 | 28,137 | 11,336,722 | -0.3833 | 0.0371 | 0.000 | 0.104 |
| 30 days | 68,647 | 16,914 | 11,475,401 | -0.3830 | 0.0370 | 0.000 | 0.104 |
| 60 days | 46,497 | 10,922 | 11,626,478 | -0.3826 | 0.0369 | 0.000 | 0.103 |
| 120 days | 32,616 | 7,345 | 11,767,096 | -0.3816 | 0.0367 | 0.000 | 0.103 |

The coefficient moves 0.0022 across a 120-fold change in window width, against a median standard error of 0.0371. That is six hundredths of a standard error, so the window choice does not drive the answer.

## Independent verification in the reference implementation

`pyfixest` is a port of `fixest`'s alternating-projections algorithm, and a port is where a subtle disagreement would hide. The headline specification was re-estimated in R's `fixest` 0.12.1, which is also the output an empirical finance referee recognises.

| engine | coefficient | standard error |
|---|---|---|
| pyfixest 0.60.0 | -0.383388 | 0.037196 |
| R fixest 0.12.1 | -0.383388 | 0.037196 |

Absolute difference 3.55e-07 on identical samples: 11,248,255 observations, 45,630 absorbed fixed effects, 944 clusters. Reproduce with `scripts/verify/run_dominance_crosscheck.py`, which exports a transient sample, shells out to `Rscript`, parses the estimate back, compares against a stated tolerance and deletes the transient. R is a verifier and never part of the pipeline, so nothing in `output/` depends on it being installed.

## The non-mechanicalness screen, which the result passes

A result that is mechanically true by construction is exposition rather than a finding. The specific threat is that the panel quotes every candidate including some sitting in pools no router would touch, so the coefficient could partly measure having enumerated alternatives that do not exist.

| screen | rows | identifying fixed effects | coefficient | se | p |
|---|---|---|---|---|---|
| baseline, all candidates | 11,248,255 | 45,630 | -0.3834 | 0.0372 | 0.000 |
| trade size $1,000 | 3,950,991 | 16,938 | -0.4115 | 0.0328 | 0.000 |
| trade size $10,000 | 3,776,322 | 15,248 | -0.4113 | 0.0390 | 0.000 |
| trade size $100,000 | 3,520,942 | 13,444 | -0.3218 | 0.0437 | 0.000 |
| native against the stable numéraire only | 9,805,608 | 44,601 | -0.3683 | 0.0376 | 0.000 |
| native against the imported asset only | 2,975,383 | 14,408 | -0.5704 | 0.0394 | 0.000 |
| routes with abs(advantage) at most 50% | 8,072,791 | 32,352 | -0.4068 | 0.0353 | 0.000 |
| routes with abs(advantage) at most 20% | 7,316,874 | 28,446 | -0.4037 | 0.0358 | 0.000 |
| routes with abs(advantage) at most 5% | 6,015,748 | 23,215 | -0.3986 | 0.0351 | 0.000 |

**Not an enumeration artefact.** Dropping the imported asset entirely, which is the most likely thin candidate, leaves the native asset beating the stable numéraire head to head by 36.8 percentage points on 9.8 million rows and 44,601 fixed effects. Both legs of that comparison are deep and widely paired. Restricting to economically live routes, where the direct route's advantage is within 5% either way, moves the estimate only to -0.3986.

**Not pure depth, which was not the expected outcome.** A depth mechanism has to strengthen with notional, because thin pools fail worse as size grows. The profile does the reverse: -0.4115 at a $1,000 trade, -0.4113 at $10,000, and -0.3218 at $100,000. The incumbent's routing advantage is therefore largest for retail-sized trades and smallest where price impact dominates. That is a statement about who benefits from incumbency rather than a nuisance to be controlled away, and it is the reason this result is not mechanically true.

**The depth channel is present but partial.** Native against imported is -0.5704 while native against stable is -0.3683, consistent with the imported asset genuinely being thinner. The thick-market externality is the mechanism of the vehicle-currency literature, so a depth component is the expected shape of the claim; what matters is that the native-versus-stable estimate stands without it.

## The collapse diagnostic, which is why this is provisional

Quote collapse is not evenly distributed across candidate vehicles, and the pattern is close enough to the headline to account for most of it.

| vehicle type | quotes | collapsed below half notional | collapsed below 1% of notional | direct route dominates |
|---|---|---|---|---|
| native | 975 | 9.6% | 4.7% | 58.1% |
| stable | 5,253 | 37.6% | 13.2% | 86.7% |
| imported | 924 | 35.5% | 18.6% | 92.4% |

The dominance gap between native and stable is 28.6 percentage points and the collapse gap is 28.0, which is nearly one for one. Because the outcome is defined as the direct route returning more than the vehicle route, a collapsed VEHICLE quote scores as the direct route dominating, so a vehicle whose pools are missing from the panel is recorded as a vehicle that is expensive to route through. That is precisely what a missing venue produces, and Curve was missing.

The indirect reassurance is that restricting to routes where the direct advantage is within 5% either way excludes collapsed quotes by construction and left the coefficient at -0.3986. The direct test is the five-venue rebuild.

## Limits, stated

**The outcome is a binary on quoted output.** `dominated` is one when the best available direct pool returns more than the best two-leg route through the candidate. That is a statement about the quote at reconstructed state, not about what a router chose, so this measures the cost surface a router faced and not its revealed preference.

**Gas is not in this specification.** The gas term is what makes route choice size-dependent, and the estimates above are gross of it. The retired daily clock cannot price transaction-level swaps. The replacement joins each admitted transaction to its exact receipt and same-block header, uses the receipt's `effectiveGasPrice` for the two route alternatives, and converts the resulting wei costs with a strictly prior independent intraday WETH/USD mark. Until that release closes, the size profile mixes the pure depth channel with a fixed-cost channel that has not yet been separated.

**Two legs only.** Longer routes are not in this panel.

**Uniswap v4 is thin in absolute terms.** It contributes 536,696 direct legs because it exists for 546 of the 2,238 days, so the late-sample venue mix is dominated by v3.

**Contaminated pool-hours are excluded** for the v2 family, at a rate ranging from 3.2% to 11.8% depending on era. Mints and burns are now held for 2,279 days and explain 88.0% of flagged hours overall, so most of that exclusion is recoverable; the residual concentrates late in the sample and is most likely direct transfers and fee-on-transfer tokens.

## What this needs from the paper spine

The size profile is the most publishable feature here and it is not yet framed. An incumbency advantage that is strongest for small trades and weakest for large ones speaks to distributional incidence, which is candidate result 5 in the workflow rather than the routing result this specification was built for. The spine should decide whether the size heterogeneity leads or supports.

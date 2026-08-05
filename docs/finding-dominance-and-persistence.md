# Cost-dominance windows are common on realised routing, and the role persists through them

This supersedes `docs/finding-native-intermediation-advantage.md`, which is retired as a headline, and corrects the frequency reported in `docs/finding-cost-dominance-measured.md`. It states the two facts the paper now rests on and marks precisely where each stops.

## The fact FX data cannot contain

The FX inertia literature's stated limit is that an incumbent's cost advantage is a consequence of its incumbency, so the data never contain the state in which a currency holds the vehicle role while being strictly cost-dominated. Holding the role means being used, so the measurement joins realised routing to counterfactual cost: for each multi-leg swap that actually executed, would the best available direct pool have returned more at that same reconstructed state.

**27.2% of realised multi-leg routing was strictly dominated at the state it executed in**, population-weighted, covering 79.0% of realised routing.

By candidate type, from the matched sample:

| candidate | dominated | share of realised routing |
|---|---|---|
| native | 23.7% | 66.9% |
| stable | 45.4% | 11.4% |
| imported | 61.4% | 0.7% |

Two earlier figures answered different questions and should not be cited. Enumerating every candidate a router could have chosen gives 70.1%, which is easy to achieve because most enumerated two-hop routes are ones nobody took. The raw matched mean is 41.3%, which is a statement about large trades on busy pairs through stablecoins: the matched sample is 64.5% stable-intermediated where the population is 66.9% native-intermediated, carries a median trade of $11,594 against $866, and covers 71 pairs against 17,851.

The reweighted 27.2% lands close to the 30.0% all-in figure the original v2-only analysis reported. That is a convergence by a disjoint route and not a confirmation, since a shared error in the underlying quoting would move both.

## The role persists through dominance — WITHDRAWN 2026-08-06

> **Every number in this section is withdrawn pending block-level pricing.** `output/exhibits/repricing_at_block.jsonl` measures the timing threat that node E's screen named as open, and it is live: comparing each swap's own immediately-prior state against the hour-boundary state this panel used, the median deviation across the busiest pools is 1.166% and the median share of routes mispriced by more than 25 basis points is 86.2%, against route-cost differences of tens of basis points. A retention ratio computed on hour-boundary classification cannot be separated from staleness. The numbers are kept below for comparison against the block-level rebuild and must not be cited.
>
> Note the shape of why this hid. The deep stable pairs are fine, at 0.085% and 0.012% median deviation, while volatile pools run 1.8% to 4.9%. Validation concentrated on the deep pairs, so the error lived exactly where nobody was looking, and that pattern is worth checking elsewhere in the panel.
>
> The dominance FREQUENCY above is affected in magnitude but not in kind, because a frequency is a statement about a state and does not require the router to have had a choice.

A vehicle's share of its pair's multi-leg volume falls when it is dominated and does not collapse.

| candidate | share when not dominated | share when dominated | retained |
|---|---|---|---|
| native | 68.6% | 39.4% | 57% |
| stable | 43.4% | 28.2% | 65% |
| imported | 6.1% | 2.8% | 46% |

Across four priced days, **$83.1m was still routed through dominated vehicles**, $69.7m of it through stables. That is the foregone amount the persistence question prices, and it is the unit a referee can hold.

## What is deliberately not claimed

**Neither hysteresis nor inertia.** Persistence on its own is equally consistent with slow information or with switching frictions that apply symmetrically, and either would produce this cross-section with no incumbency advantage existing. Hysteresis is a claim about asymmetry, that the incumbent keeps the role while dominated for longer than a challenger takes to gain it when the edge runs the other way. `scripts/run_displacement_asymmetry.py` measures both arms and currently refuses to report a duration, because four priced days would censor every unswitched pair at four days and the estimate would be a function of the sample window.

**No duration and no survival curve**, for the same reason. The full rebuild covers 2,277 days and the script runs against it unchanged.

**Nothing conditional on trade size.** The panel prices three fixed notionals and matched trades are an order of magnitude larger than the population's. The earlier claim of a size gradient in the native advantage is dead on a formal test: the interaction of native with log size is +0.0023 (0.914).

**The level comparison is a validation exhibit, not a result.** On the continuous gap with the support screen applied it is about -25 basis points (0.037), against a retired -0.383 on a binary indicator that was measuring quote collapse.

## What the numbers rest on

Six venues priced, each validated against realised swaps before entering the panel: Uniswap v2 at 0.0000% median error, v3 and v4 at 0.0000% across all four direction-by-tick-crossing cells, Curve at 0.033% under a 90th-percentile calibration gate, Balancer at 0.0000% on backward-walked balances. Cross-implementation checks: Balancer against v2 on shared pairs at a median output ratio of 0.9979, and the regression engine against R `fixest` at 3.55e-07.

Legs are refused when their own price impact exceeds 5%, a bound derived from where the quoters were validated: over 932,270 realised swaps, trade size as a fraction of the input reserve is 0.0034 at the median and 0.0541 at the 95th percentile. Without it, between 44.5% and 82.0% of measured gaps implied an arbitrage cycle that pays after fees and gas, which cannot persist in one block.

`docs/venue-coverage-bounds.md` signs the remaining venue gaps and finds they understate the native comparison rather than manufacture it, because the Curve pools the gate rejects are the tricrypto pools where Curve's ETH-leg depth lived.

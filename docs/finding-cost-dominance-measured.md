# Cost-dominance windows exist, and the native vehicle is rarely in them

Supersedes the negative result in `docs/finding-cost-dominance-not-yet-established.md`, which failed because it compared realised trades across a day and intraday price movement swamped execution cost by 34 to 1. This prices both routes at identical reconstructed state, so price movement cannot enter.

Built by `scripts/build_counterfactual_dominance.py` on `src/ddvc/cpquote.py`. **103,857 intermediated two-leg routes with an available direct alternative, across 186 days sampled from 2020-05-29 to 2026-06-27.**

## The question, and the answer

The FX inertia literature's stated limit is that an incumbent's cost advantage is a consequence of its incumbency, so the data never contain the state where a currency holds the vehicle role while strictly cost-dominated. On-chain, that state is observable and common: **17.9% of intermediated routes were dominated gross of gas, 30.0% all-in.** So the windows exist.

## The result that matters

Dominance by intermediary type, all-in, every year of the sample:

| year | native n | native dominated | other n | other dominated |
|---|---|---|---|---|
| 2020 | 2,309 | 17.1% | 11,959 | 35.2% |
| 2021 | 7,723 | 15.5% | 31,620 | 29.1% |
| 2022 | 4,201 | 19.5% | 16,195 | 25.5% |
| 2023 | 2,611 | 22.2% | 7,179 | 29.5% |
| 2024 | 1,757 | 19.4% | 8,647 | 29.6% |
| 2025 | 689 | 15.4% | 7,261 | 55.5% |
| 2026 | 118 | 32.2% | 1,588 | 86.7% |

The native asset is dominated less often than every alternative, in all seven years, and its median all-in gap is **-2,352 bps**, meaning the typical native-intermediated route returns far more than the best direct pool would have.

**This is evidence against naive inertia.** An asset carried by habit should be dominated *more* often than alternatives, since habit would keep sending flow through it after it stopped being the best choice. The opposite holds. What the data support instead is incumbency operating through a state variable: the native asset's pools are deepest, so routing through it is genuinely optimal today, and the reason they are deepest may still be historical. That distinction is the defensible one, and it is the position Java argued for against a reviewer who wanted the incumbency reading dropped altogether.

## Gas behaves exactly as a fixed cost should

Adding the receipt-measured gas of the extra hop (74,096 units, from median gasUsed of 154,604 for one leg against 228,701 for two) raises overall dominance from 17.9% to 30.0%, and the change concentrates where a fixed cost must bite hardest:

| trade size | n | dominated gross | dominated all-in |
|---|---|---|---|
| $100-1k | 50,283 | 17.0% | 39.1% |
| $1k-10k | 42,051 | 18.9% | 22.2% |
| $10k-100k | 10,674 | 17.0% | 17.3% |
| >$100k | 847 | 33.5% | 33.5% |

Small trades flip in large numbers; trades above $100k do not move at all, because one extra hop is 0.5 bp of a $100,000 notional and 478 bp of a $100 notional.

The >$100k row is the anomaly worth chasing: those routes have the highest gross dominance at 33.5%, meaning large trades were intermediated when a direct pool would have paid more, and gas cannot explain it away at that size. Candidate explanations to test: split routing across venues our v2-only counterfactual cannot see, MEV protection, or a genuinely suboptimal router. It is a small cell at 847 routes.

## Limits, stated

**Flat gas and ETH price.** The all-in figures use 25.8 gwei and ETH at $2,500 across the whole 2020-2026 span, which is wrong in both directions at different times: gas ran far higher in 2021 and far lower after EIP-4844, and ETH ranged from a few hundred dollars to several thousand. Per-day gas price is recoverable from receipts and per-day ETH price from the pools themselves. This is the next refinement and it will move the all-in numbers, though not the ordering across intermediary types, which is measured gross of gas too.

**v2-family venues only.** Concentrated liquidity needs the tick map. Omitting venues understates the best alternative route, so dominance incidence is a lower bound. The v2 sample also thins badly late as volume migrated to v3 and v4, which is why native n falls to 118 in 2026; the 2025 and 2026 rows should be read with that in mind rather than as a trend.

**Contaminated pool-hours excluded.** Hours failing the reserve-continuity check are dropped, roughly 3.2%, and their exclusion is not random since liquidity events concentrate in actively managed pools.

**Two legs only.** Longer routes are excluded from this panel.

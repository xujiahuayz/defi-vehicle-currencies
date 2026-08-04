# The intermediation transition, measured

Built 2026-08-05 by `scripts/build_intermediation_by_type.py` over `data/unified/` (2,240 days with intermediated routing, 2020-05-06 to 2026-06-30). Asset types from `src/ddvc/asset_types.py`. Round-trip routes are excluded as atomic arbitrage or wash trading, matching the cross-venue series.

This asks the FX literature's dominance-transition question where the answer is observable. When a trade passes through an intermediary, which *type* of asset does it pass through, and has the role moved from the native platform asset to the stable numeraire?

## Result

Share of intermediation episodes, count-weighted:

| year | native | staked native | stable | imported | other |
|---|---|---|---|---|---|
| 2020 | 68.7% | 0.0% | 26.8% | 0.2% | 4.3% |
| 2021 | 72.4% | 0.0% | 21.3% | 2.0% | 4.3% |
| 2022 | 62.9% | 0.2% | 25.6% | 1.3% | 10.1% |
| 2023 | 71.3% | 0.3% | 13.9% | 0.9% | 13.7% |
| 2024 | 66.0% | 0.9% | 14.1% | 1.3% | 17.7% |
| 2025 | 45.1% | 1.1% | 28.9% | 4.1% | 20.7% |
| 2026 | 32.9% | 0.8% | 36.4% | 5.8% | 24.2% |

Value-weighted (secondary, per the round-trip caveat):

| year | native | staked native | stable | imported | other |
|---|---|---|---|---|---|
| 2020 | 73.0% | 0.0% | 21.2% | 1.3% | 4.5% |
| 2022 | 24.3% | 0.3% | 46.2% | 4.3% | 24.9% |
| 2024 | 36.0% | 6.7% | 29.5% | 3.6% | 24.2% |
| 2026 | 14.8% | 1.5% | 50.1% | 9.9% | 23.7% |

## What can and cannot be claimed

**Strong, value-weighted.** The stable numeraire first exceeds the native asset as intermediary in 2022-Q1 and the lead is sustained from 2022-Q4 onward, so roughly four years of the sample have the stable type dominant by value. Native falls from 73.0% to 14.8% across the sample.

**Tentative, count-weighted.** The crossover appears only in the final two quarters (2026-H1) and therefore cannot be called sustained: the sample ends 2026-06-30, so no four-quarter run is even possible. State it as a crossover occurring at the very end of the sample, with the caveat attached, and avoid describing the count-weighted series as having transitioned.

**Robust to the registered specification alternative.** Folding staked-native derivatives into native (the `staked_native_in_native` alternative in `asset_types.py`) leaves the 2026 count-weighted crossover intact (native plus staked 33.7% against stable 36.4%). Report this, since the alternative is defensible and a referee will ask.

**Not monotone.** Native rises in 2021 and again in 2023 before falling, so a smooth decline would misdescribe it.

## The count-value divergence is itself a finding

Large trades moved to the stable numeraire roughly four years before small trades did. That is economically sensible: an intermediary asset is held for the duration of the hop, so the cost of the intermediary's own volatility scales with notional, and large trades have more reason to route through a low-volatility unit. The mechanism also predicts the observed ordering, with the value crossover arriving early and the count crossover late, so it was not fitted after the fact.

## Two things this exhibit needs before it is presentable

**The residual is large and so far unexplained.** `other` runs 24.2% of episodes by 2026, across 9,283 distinct intermediary tokens over the stratified sample. Part of that is genuine diversification and part may be further classifiable assets. The taxonomy was built by measuring the top intermediaries, so coverage is good at the head and weak in the tail; the tail needs either a documented cutoff rule or an explicit statement that beyond the classified set no type claim is made.

**Imported store of value is rising and currently unremarked.** The imported type (wrapped bitcoin plus tokenised gold) grows from 0.2% to 5.8% of episodes and 1.3% to 9.9% of value. Tokenised gold serving as a route intermediary is a clean traditional-finance analogue and worth its own sentence, since a metallic reserve asset intermediating exchange is the pre-fiat arrangement reappearing.

## A correction worth recording

The first version of this exhibit carried only the five original candidate tokens and therefore filed **native ETH at the zero address** as `other`. That single omission was 19.8% of the `other` bucket in 2026 samples and understated the native share by roughly 6 percentage points, which flattered the transition. Newer stables (crvUSD, USDe, USD1, FRAX), staked-ETH derivatives, and tokenised gold were also misfiled. The taxonomy now rests on measured intermediation over 57 stratified days, replacing the candidate set inherited from earlier work.

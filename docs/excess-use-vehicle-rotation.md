# The making of a dominant vehicle currency, dated: the excess-use rotation

PROVISIONAL (workflow §41). Read from released route-only D3 exhibits; not a finding until rerun on the released D generation. Source exhibits: `output/exhibits/vehicle_excess_use.jsonl` (annual, token and asset-type levels), `output/exhibits/vehicle_excess_use_quarterly.jsonl` (quarterly, asset-type level).

## The measure, and why it pre-empts the composition rival

The vehicle role is intermediary use net of endpoint demand. For an asset the excess-use ratio is its share of intermediary (routed-through) legs divided by its share of endpoint (start or finish) legs. A ratio above one means the asset is routed through more than holding demand alone would put it, which is the operational signature of a vehicle. A ratio below one means it is mostly a destination, not a conduit.

The ratio is a quotient of a routing share over an endpoint share, so a common growth in both, which is what market maturation, rising stablecoin volume, or venue migration would produce, cancels. The rival that the transition is mere composition therefore has to survive a measure that already differences composition out. This is identification by construction, before any control is added.

## The value rotation changes hands, and the date is 2025Q1

Native platform asset (ETH), value excess-use by quarter: 1.52 (2020Q2), easing to 1.01 (2021Q4), a transient dip to 0.89 (2022Q2) during the Terra collapse, recovery to 1.22 (2023Q1), a plateau near 1.2 through 2024, then 0.95 (2025Q1), 0.67, 0.48, 0.61, 0.61, 0.55 (2026Q2). ETH crosses below one and stays there from 2025Q1.

USDT, value excess-use by year: 0.29 (2020), 0.66, 0.73, 0.48, 0.64 (2024), then 1.60 (2025) and 1.54 (2026). USDT crosses above one in 2025. A vehicle is born.

USDC, value excess-use by year: 0.50 (2020), then 1.06, 1.22, 1.25, 1.03, 1.06, 1.15. USDC has been a vehicle since 2021 and stays one. It is the incumbent stable vehicle, not the margin.

So the handover is precise. By value the vehicle role leaves ETH definitively at 2025Q1 and is taken up by USDT crossing into vehicle status in the same window, on top of USDC which already held it. The paper's title event is observable and datable.

## The transient of 2022 is the control that makes 2025 a succession

ETH's excess-use fell below one in 2022Q2 and returned above one by 2023Q1. The role dipped under stress and came back. In 2025 it falls below one and does not come back through 2026Q2. The same measure, on the same asset, separates a stress wobble from a regime change without any auxiliary model. A referee who suspects the 2025 fall is another transient has the 2022 recovery as the reference for what a transient looks like, and 2025 does not match it.

## Count leads nothing; value leads count

By count the ordering barely moves and it points the other way from value. Native asset-type excess-use by count sits near 0.8 to 0.95 across the whole sample, below one throughout, so per route the native asset was never the excess-vehicle. Stable excess-use by count sits near 1.2 to 1.5 throughout, above one throughout, so per route the stable class was always the excess-vehicle. The switch is a value event alone. Small routes favoured the stable vehicle from the start, and it was the large-value flow that relocated last, crossing to stables only in 2025. The vehicle role by number of trades was stable-tilted years before the vehicle role by dollars followed, so the large trades were the laggards, not the leaders. The lag between the count tilt, present from the start, and the value crossing in 2025Q1 is itself an estimand and reads as a vehicle adopted first on many small trades and only later on the large flow that dominates value.

## The vehicle role is a fiat-reserve phenomenon, and that is the mechanism

Being a stablecoin is not sufficient to become a vehicle. Decomposing stable excess-use by collateral backing, weighted by intermediary dollars so that tiny categories do not mislead, the vehicle role concentrates entirely in fiat-reserve stables and is absent from the alternatives. Source `output/exhibits/vehicle_excess_use.jsonl`, `level = stable_backing`.

Fiat-reserve backing (USDT, USDC) carries the intermediary volume, 30.6 billion dollars in 2021 rising to 36.4 billion in 2025, at a value excess-use ratio moving from 0.93 in 2020 to 1.09 in 2025. On-chain-collateralized backing (DAI) sits at 0.08 to 0.29 and falls to 0.02 to 0.04 by 2025 and 2026, so it is held and not routed through. Synthetic backing stays below one throughout. Fractional-algorithmic backing shows high ratios of 2.1 to 3.4 in 2021 to 2023 but only on 0.1 to 1.1 billion dollars, a niche conduit that then disappears after the 2022 algorithmic-stablecoin collapse. The extreme non-USD ratios, reaching 13.1 in 2024, sit on effectively zero dollars and are category noise, not a vehicle.

The token level sharpens it. Within fiat-reserve, USDC was already a vehicle and is the incumbent, while USDT is the entrant crossing into vehicle status in 2025. So the rotation is not native-to-stables in general. It is native-to-fiat-reserve-stables, and specifically the recruitment of USDT alongside USDC.

The economics is exactly the vehicle-currency theory made visible. A vehicle needs two things at once, a credible unit of account so a route can denominate through it without price risk, and a thick market so routing through it is cheap. A credible peg without depth, which is DAI, does not qualify. Depth without a reliable peg, which is the algorithmic stables before they broke, qualifies only briefly and at trivial scale. Only fiat-reserve stables hold both, and only they capture the role. The data does what the FX literature cannot, which is to show the full field of candidate media and which of them the thick-market and numéraire-stability conditions actually select.

## Above and beyond, three angles this measure opens

1. Excess-use as a continuous vehicle-status state variable, with the unit threshold as the operational definition of becoming or ceasing to be dominant. The paper can report the crossing as an event and characterise the speed of the crossing, not only the endpoint shares. Estimand: the hazard of an asset's excess-use crossing one, and the persistence of the post-crossing state.

2. The 2022-transient against the 2025-sustained crossing as a within-asset natural contrast for succession versus stress. Estimand: the mean-reversion half-life of excess-use after a sub-unit excursion, estimated separately for the recovered 2022 episode and the 2025 episode, testing whether 2025 is drawn from the same reverting process.

3. The count-leads-value diffusion. A vehicle appears on many small trades before it appears on the large flow that dominates dollars, so the stable role is above one by count for years before it crosses one by value in 2025. Estimand: the lag between the count tilt and the value crossing, as a measure of how a vehicle role propagates from small trades up to large trades. This is not answerable in FX, where trade-size-resolved vehicle use at daily frequency is unobservable.

## The maturation rival is rejected for the core, and the residual is the mechanism

The strongest rival, that market maturation and aggregator routing manufacture the apparent rotation by composition, is tested in the reproducible E0 rotation snapshot (`docs/finding-vehicle-rotation.md`, `scripts/run_vehicle_rotation_e0.py`, and `output/exhibits/e0_vehicle_rotation_analysis.jsonl`) and does not hold for the core of the effect. Three results.

First, the rebound survives inside a fixed opportunity set. Within the single-venue cell the stable share still rises by 22.97 points on episodes and 35.03 points on strict-support value from 2024 to 2026, with Holm p from about 1e-41 to 1e-73, which is roughly four fifths of the marginal magnitude. Holding both margins the rival names fixed, in the single-venue two-leg cell, it is still 20.67 and 38.09 points. Composition inside one venue cannot be the whole story when the effect is nearly intact inside one venue.

Second, the rival predicts the wrong sign on the aggregate. If integration created the rotation by letting routers reach stable paths they could not reach before, intermediation would rise as venues integrated. It does the opposite. As cross-venue incidence goes from 1.7 percent to 57 percent, true intermediation is flat to falling, minus 2.03 to minus 5.35 points. The vehicle composition rotated inside a roughly constant, even shrinking, intermediation layer, so the rotation is a reallocation of the vehicle role and not an expansion of intermediation.

Third, the endpoint-netted excess-use reversal, which differences out volume by construction, moves anyway, and USDT's endpoint-netted gap change of 15.27 points on strict value at Holm 5e-22 is not producible by proportional volume or venue growth.

The residual the rival keeps is a cross-venue amplification, about a quarter of the effect, where the rotation is faster across venues than within one venue by 7.45 to 8.17 points. This is not yet resolved into mechanism against artifact. It is either the opportunity-set channel the rival names, or the thick-market externality itself operating through integration, where a stable vehicle becomes more attractive as its route can be assembled across venues. The forced-versus-chosen and routing-search-efficiency test named in the registry is what distinguishes the two, and it is what the state-dependent D layer is being built to support. The honest current statement is that three quarters of the rotation is venue-invariant and outside the rival's reach, and the remaining quarter is an integration channel whose interpretation is open.

## The role leaves the native asset and does not land on a single successor

The rotation is not a clean handover from one dominant vehicle to the next. On direct value intermediation share, `output/exhibits/vehicle_concentration.jsonl` basis `share_volume`, the leader's share of the vehicle role falls from 83.7 percent in 2020 to 25.5 percent in 2026, and the effective number of vehicles, one over the Herfindahl, rises from 1.42 to 8.43. On value the regime moves from one asset carrying almost all of the vehicle role to a field where the leader carries a quarter of it. The native asset's dominance is unmade, and what replaces it is a fragmented multi-vehicle regime in which fiat stables are the leading but non-dominant vehicles, with USDT and USDC coexisting as genuine vehicles by the excess-use test above.

This reframes the paper's object. The making of a dominant vehicle currency here is inseparable from the unmaking of one, and the endpoint is not succession to a new hegemon but fragmentation with a stable-currency plurality at the top. That is the exact question the international-currency literature debates for the dollar against the euro and the renminbi, and it is observable here where it is not observable there.

One caveat is load-bearing and is stated so no later claim over-reaches. A falling aggregate Herfindahl is consistent with genuine fragmentation, where each pair now routes through many vehicles, and it is also consistent with a patchwork of pair-level monopolies, where many pairs each keep a single vehicle but different pairs use different ones. The direct-share measure used here removes the circularity of the retired betweenness measure, where the network centrality was close to a restatement of how the native asset was defined, but it does not by itself separate those two aggregation stories. Distinguishing them needs a per-pair regime and switching-order analysis on the state-dependent layer. So the honest statement is that the value concentration of the vehicle role collapses and the native asset's single dominance ends, while whether the successor regime is genuinely fragmented or a mosaic of local monopolies is a re-opened question and not a settled finding.

## What this still needs before promotion

The routing-search-efficiency and forced-versus-chosen conditioning named in the freeze registry, so that the residual rival, that the router only now finds stable routes it could not reach before, is closed and not only differenced. That test is provisional-in-progress separately. The excess-use construction answers the composition margin; it does not by itself answer the opportunity-set margin.

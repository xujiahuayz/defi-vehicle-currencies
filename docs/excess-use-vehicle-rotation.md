# The making of a dominant vehicle currency, dated: the excess-use rotation

PROVISIONAL (workflow §41). Read from released route-only D3 exhibits; not a finding until rerun on the released D generation. Source exhibits: `output/exhibits/vehicle_excess_use.jsonl` (annual, token and asset-type levels), `output/exhibits/vehicle_excess_use_quarterly.jsonl` (quarterly, asset-type level).

## The measure, and what endpoint netting does and does not remove

The vehicle role is intermediary use relative to endpoint demand. For an asset, let the excess-use gap be its share of intermediary legs minus its share of endpoint legs. The corresponding ratio divides the first share by the second when endpoint support is positive. A positive gap and a ratio above one make the same classification on supported observations, but the gap is the primary inferential outcome because it is measured in share points and does not become unstable near a small denominator. The ratio remains useful for describing relative intensity.

Endpoint netting removes proportional growth in intermediary and endpoint use. It does not remove arbitrary changes in endpoint-pair composition, trade size, venue identity, route design, token support, or the technology that maps a given opportunity set into a route. Those margins still require fixed-support decompositions and explicit rival tests. The 59,647 token-days with intermediary use but zero measured endpoint demand remain unsupported diagnostics; an undefined ratio is not promoted as evidence of extreme vehicle use.

## The annual and quarterly aggregates place the sustained value crossing in 2025

Native platform asset (ETH), value excess-use by quarter: 1.52 (2020Q2), easing to 1.01 (2021Q4), a transient dip to 0.89 (2022Q2) during the Terra collapse, recovery to 1.22 (2023Q1), a plateau near 1.2 through 2024, then 0.95 (2025Q1), 0.67, 0.48, 0.61, 0.61, 0.55 (2026Q2). ETH crosses below one and stays there from 2025Q1.

USDT, value excess-use by year: 0.29 (2020), 0.66, 0.73, 0.48, 0.64 (2024), then 1.60 (2025) and 1.54 (2026). USDT crosses above one in the 2025 annual aggregate.

USDC, value excess-use by year: 0.50 (2020), then 1.06, 1.22, 1.25, 1.03, 1.06, 1.15. USDC has been a vehicle since 2021 and stays one. It is the incumbent stable vehicle, not the margin.

Taken together, the aggregates show a sustained value reallocation in the 2025 window: WETH falls below one while USDT rises above one, on top of USDC's earlier vehicle use. They do not identify an event date or prove that one design change caused the crossing. Until the daily fixed-support analysis separates calendar change from architecture, opportunity, and composition, the admissible description is a 2025 rotation window rather than a dated handover.

## The 2022 recovery is a descriptive contrast, not a control group

WETH's excess-use fell below one in 2022Q2 and returned above one by 2023Q1. It falls below one again in 2025 and does not return through 2026Q2. This within-asset history shows that a sub-unit observation need not be permanent and therefore makes post-crossing persistence a required measurement. One earlier episode cannot serve as a control group: market design, venue reach, pair composition, and stress differ between 2022 and 2025. The contrast motivates a reversal analysis; it does not by itself classify one episode as stress and the other as structural succession.

## The count and value margins move by different magnitudes

At the asset-type level, stable excess use is above one by count throughout the sample while native excess use is below one; the value ordering changes later. At the token level, however, USDT's count ratio moves above and below one across years, so the class result cannot be read as a token-level adoption clock. On the seasonally balanced daily comparison, USDT's intermediary-minus-endpoint gap rises by 2.39 share points from 2024 to 2026 by episode count (Holm-adjusted $p=0.0147$) and by 15.27 share points on strict value support (Holm-adjusted $p=5.03\times10^{-22}$). The value movement is much larger. Whether this reflects large trades moving later, changing notional composition, or different route designs must be tested in joint token-by-notional-by-opportunity cells; the aggregates do not establish a diffusion order.

## Fiat-reserve concentration is a mechanism candidate, not its identification

Being a stablecoin is not sufficient to become a vehicle. Decomposing stable excess-use by collateral backing, weighted by intermediary dollars so that tiny categories do not mislead, the vehicle role concentrates entirely in fiat-reserve stables and is absent from the alternatives. Source `output/exhibits/vehicle_excess_use.jsonl`, `level = stable_backing`.

Fiat-reserve backing (USDT, USDC) carries the intermediary volume, 30.6 billion dollars in 2021 rising to 36.4 billion in 2025, at a value excess-use ratio moving from 0.93 in 2020 to 1.09 in 2025. On-chain-collateralized backing (DAI) sits at 0.08 to 0.29 and falls to 0.02 to 0.04 by 2025 and 2026, so it is held and not routed through. Synthetic backing stays below one throughout. Fractional-algorithmic backing shows high ratios of 2.1 to 3.4 in 2021 to 2023 but only on 0.1 to 1.1 billion dollars, a niche conduit that then disappears after the 2022 algorithmic-stablecoin collapse. The extreme non-USD ratios, reaching 13.1 in 2024, sit on effectively zero dollars and are category noise, not a vehicle.

The token level sharpens it. Within fiat-reserve, USDC was already a vehicle and is the incumbent, while USDT is the entrant crossing into vehicle status in 2025. So the rotation is not native-to-stables in general. It is native-to-fiat-reserve-stables, and specifically the recruitment of USDT alongside USDC.

The cross-section is consistent with the joint importance of value stability and thick markets, but it does not identify that mechanism. Fiat-reserve stables differ from crypto-collateralized and synthetic stables in liquidity, age, venue reach, pair coverage, issuer design, and user base as well as backing. The backing split therefore defines a mechanism horse race: stability and depth must explain the same token-level and fixed-opportunity comparisons, and an aggregate category ordering is motivating evidence rather than a mechanism result.

## Above and beyond, three angles this measure opens

1. Excess use as a continuous vehicle-dominance measure. The supported share gap is the inferential outcome; the ratio and its unit threshold are descriptive translations. A crossing becomes an event only after daily support shows that it is not a denominator or composition discontinuity.

2. The recovered 2022 excursion and the sustained 2025–2026 observations motivate a reversal comparison on common support. With one episode of each kind, the analysis can describe persistence and sensitivity to states; it cannot treat the pair as a natural experiment.

3. The count/value wedge motivates a notional-distribution decomposition. The test asks whether the USDT gap changes within stable token, endpoint pair, venue reach, route design, and notional bins, and whether reweighting the 2024 distribution to 2026 can reproduce the value change. Only then can the wedge be interpreted as propagation across trade sizes.

## Current tests narrow venue-entry and route-topology explanations; they do not identify time or design

The strongest rival is that market maturation and aggregator routing manufacture the apparent rotation through changing route composition. The reproducible E0 snapshot (`docs/finding-vehicle-rotation.md`, `scripts/run_vehicle_rotation_e0.py`, and `output/exhibits/e0_vehicle_rotation_analysis.jsonl`) currently narrows that rival in three ways without eliminating it.

First, the rotation survives within the single-venue and single-venue two-leg route-topology cells. This rules out migration from single- to cross-venue or from two- to many-leg execution as the whole arithmetic explanation. These cells do not hold endpoint pair, exact venue, notional, token support, or protocol design fixed, so they are not yet fixed opportunity sets and do not distinguish calendar time from the designs prevalent in each year.

Second, cross-venue integration and true intermediation are empirically distinct margins. From 2022 to 2026, true intermediation falls by 2.03 daily share points market-wide and by 5.35 points on the balanced five-venue perimeter even as cross-venue incidence rises. The vehicle rotation therefore occurs within a shrinking intermediation layer rather than through a mechanical expansion of all indirect routing. This does not reject routing maturation: the same technology could discover more direct routes while reallocating the remaining intermediary routes toward stablecoins.

Third, USDT's endpoint-netted strict-value gap rises by 15.27 points. Proportional growth in endpoint and intermediary use cannot produce that gap change. Non-proportional pair, venue, notional, design, and support changes still can, which is why the joint fixed-cell decomposition remains required.

The cross-venue cell shows additional amplification, but its interpretation is open. It may reflect opportunity-set expansion, the thick-market externality operating through integration, a different mix of pairs and sizes, or the designs and routers that happen to populate later years. The present evidence supports “not solely a route-topology composition shift.” It does not support a fraction of the rotation that is invariant to venue or a causal integration channel.

## The role leaves the native asset and does not land on a single successor

The rotation is not a clean handover from one dominant vehicle to the next. On direct value intermediation share, `output/exhibits/vehicle_concentration.jsonl` basis `share_volume`, the leader's share of the vehicle role falls from 83.7 percent in 2020 to 25.5 percent in 2026, and the effective number of vehicles, one over the Herfindahl, rises from 1.42 to 8.43. On value the regime moves from one asset carrying almost all of the vehicle role to a field where the leader carries a quarter of it. The native asset's dominance is unmade, and what replaces it is a fragmented multi-vehicle regime in which fiat stables are the leading but non-dominant vehicles, with USDT and USDC coexisting as genuine vehicles by the excess-use test above.

This reframes the paper's object. The making of a dominant vehicle currency here is inseparable from the unmaking of one, and the endpoint is not succession to a new hegemon but fragmentation with a stable-currency plurality at the top. That is the exact question the international-currency literature debates for the dollar against the euro and the renminbi, and it is observable here where it is not observable there.

One caveat is load-bearing and is stated so no later claim over-reaches. A falling aggregate Herfindahl is consistent with genuine fragmentation, where each pair now routes through many vehicles, and it is also consistent with a patchwork of pair-level monopolies, where many pairs each keep a single vehicle but different pairs use different ones. The direct-share measure used here removes the circularity of the retired betweenness measure, where the network centrality was close to a restatement of how the native asset was defined, but it does not by itself separate those two aggregation stories. Distinguishing them needs a per-pair regime and switching-order analysis on the state-dependent layer. So the honest statement is that the value concentration of the vehicle role collapses and the native asset's single dominance ends, while whether the successor regime is genuinely fragmented or a mosaic of local monopolies is a re-opened question and not a settled finding.

## What this still needs before promotion

The routing-search-efficiency and forced-versus-chosen conditioning named in the freeze registry, so that the residual rival, that the router only now finds stable routes it could not reach before, is closed and not only differenced. That test is provisional-in-progress separately. The excess-use construction answers the composition margin; it does not by itself answer the opportunity-set margin.

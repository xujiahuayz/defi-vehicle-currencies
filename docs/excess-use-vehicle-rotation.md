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

By count the ordering barely moves: native asset-type excess-use sits near 0.8 to 0.95 across the whole sample and stable near 1.2 to 1.5 throughout, so on a per-route basis stables were already the more excess-used class early. The crossing is a value event. Large trades relocate the vehicle role first and the count of routes follows later, which reads as diffusion of a new vehicle from large flow to small flow. The gap between the value crossing (2025Q1) and any count crossing is the diffusion lag and is itself an estimand.

## Above and beyond, three angles this measure opens

1. Excess-use as a continuous vehicle-status state variable, with the unit threshold as the operational definition of becoming or ceasing to be dominant. The paper can report the crossing as an event and characterise the speed of the crossing, not only the endpoint shares. Estimand: the hazard of an asset's excess-use crossing one, and the persistence of the post-crossing state.

2. The 2022-transient against the 2025-sustained crossing as a within-asset natural contrast for succession versus stress. Estimand: the mean-reversion half-life of excess-use after a sub-unit excursion, estimated separately for the recovered 2022 episode and the 2025 episode, testing whether 2025 is drawn from the same reverting process.

3. The value-leads-count diffusion. Estimand: the lag between an asset's value excess-use crossing one and its count excess-use crossing one, as a measure of how a vehicle role propagates from large to small trades. This is not answerable in FX, where trade-size-resolved vehicle use at daily frequency is unobservable.

## What this still needs before promotion

The routing-search-efficiency and forced-versus-chosen conditioning named in the freeze registry, so that the residual rival, that the router only now finds stable routes it could not reach before, is closed and not only differenced. That test is provisional-in-progress separately. The excess-use construction answers the composition margin; it does not by itself answer the opportunity-set margin.

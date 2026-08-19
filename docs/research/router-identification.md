# Router identification and routing-technology bounds

This note records the narrow identification result used by the routing rival in
the paper. The current outputs are
`output/exhibits/routing_technology_windows.jsonl` and
`output/exhibits/cross_venue_routing_{series,inference}.jsonl`, produced by
`scripts/process/build_cross_venue_routing_series.py`.

## What the transaction fields identify

Uniswap V3 swap records distinguish:

- `sender`: the contract or address that calls the pool;
- `origin`: the transaction-signing externally owned account;
- `recipient`: the destination of the pool output.

The sender can identify an execution contract. It does not generally identify
the system that selected the route. A wallet, frontend, meta-aggregator, or solver
can construct calldata and submit it through the same executor. Consequently,
executor shares are descriptive heterogeneity, not market shares of routing
algorithms.

Private quotes, losing RFQ responses, market-maker inventory, unselected solver
solutions, and private-inclusion values are not recoverable from the executed
transaction. A public-chain optimum is therefore a declared benchmark, not the
trader's complete ex-ante opportunity set.

## What is measured now

The route reconstruction distinguishes:

- direct single-pool exchange;
- direct splitting across pools with no intermediary;
- sequential intermediation through one or more assets;
- routes that combine intermediation with a split or join.

Counts use topology-valid, non-round-trip ultimate routes. Values are reported
raw and at the two declared route-flow coherence bands. Cross-venue incidence,
leg count, venue count, and intermediary composition are descriptive routing
objects; none is a welfare or efficiency measure by itself.

Three public Uniswap routing releases are evaluated in symmetric 60-day windows.
The windows show changing route composition but are not treated-versus-control
estimates. The release dates overlap other market events, the integrated venue
set evolves, and executor contracts do not reveal route authorship. The paper
therefore uses them as a bounded rival: no window is followed by a material
market-wide increase in true intermediation, and the stablecoin rotation appears
within both simple and complex, single-venue and cross-venue routes.

## Design required for a stronger routing claim

A future routing-efficiency study would need exact pre-transaction pool state and
three separately reported quantities:

1. chosen execution versus the best route within the executor's declared reach;
2. that reach-constrained optimum versus the public-pool optimum;
3. intermediary choice versus a direct route and alternative intermediaries.

Those comparisons must hold fixed the ultimate endpoints, input amount, block
state, reachable venues, and route complexity. Integration events require dated
venue additions and unaffected comparison markets. Until that design is complete,
the present paper makes no aggregator-causality or market-efficiency claim.

## Reporting rules

- Say **executor**, not route author, unless authorship is separately established.
- Say **ordered ultimate pair** for the direction-specific input-to-output
  endpoints, **route** for the realised execution sequence (or **path** when
  discussing the graph), and **atomic trade/pair** for each pool leg.
- Keep route complexity, market integration, search performance, and
  vehicle-currency economics separate.
- Count-weighted routing is primary; value-weighted routing always reports its
  support and round-trip screen.

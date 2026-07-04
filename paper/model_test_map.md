# Model-to-Test Map

This note records the current small-model structure. The Mathematica sources are
`paper/vehicle_currency_model.wl` and `paper/vehicle_currency_numerics.wl`.

On the Studio machine, Wolfram 14.3 works with UCL's MathLM server. Wolfram 15.0
installs but the server does not grant licenses to that version. Run the model
with:

```bash
'/Applications/Wolfram 14.3.app/Contents/MacOS/WolframKernel' -script paper/vehicle_currency_numerics.wl
```

The script writes symbolic derivations and numerical figures to `output/model/`.

## Model

A trader swaps source token `i` into destination token `j`. The trader can use a
direct route `i -> j` or a vehicle route `i -> k -> j`. Route costs are the sum of
fees, settlement or credibility costs, and a reduced-form price-impact term that
falls with executable liquidity.

Liquidity providers allocate liquidity toward pools that attract expected route
flow. This creates a feedback channel from vehicle-linked liquidity to future
vehicle use.

## Propositions and Empirical Tests

**Proposition 1. Vehicle use.** A token is used as a vehicle when the indirect
route through it is cheaper than the direct route.

Empirical test: compare direct-route and vehicle-route costs by endpoint pair and
trade-size bucket.

**Proposition 2. Liquidity feedback and stickiness.** Vehicle-linked executable
liquidity raises future bridge share, and liquidity responding to route flow makes
vehicle status persistent.

Empirical test: lag near-price liquidity and LP repositioning in vehicle-linked
pools; test whether they predict future bridge share, route betweenness, or
vehicle-route costs.

**Proposition 3. Stress rotation.** A risk or credibility shock to the incumbent
vehicle lowers its route advantage and shifts bridge use toward substitute
vehicles.

Empirical test: WETH bridge share falls with ETH downside stress; stablecoin bridge
share rises. Post-event recovery and half-life measure stickiness versus tipping.
USDC depeg is a reserve-credibility application of this proposition, not a separate
main pillar.

**Proposition 4a. Concentrated liquidity.** Increasing direct-pool executable
liquidity lowers the relative advantage of vehicle routes for affected endpoint
pairs.

Empirical test: around V3 concentrated-liquidity adoption, measure direct-route
feasibility, direct-route cost, and vehicle-route reliance.

**Proposition 4b. Flash accounting.** V4-style netting separates route
intermediation from physical settlement: gross vehicle exposure can remain positive
while physical vehicle movement falls.

Empirical test: matched V3-V4 route units. Hold endpoint pair and intermediate
token fixed; compare ERC-20 transfer incidence, physical movement, and compression.

# Model-Driven Empirical Design

This note pins the empirical design to the small vehicle-currency model in
`paper/vehicle_currency_model.wl`. The purpose is to avoid running empirical
tests because they are available; each test below corresponds to a model
comparative static.

## Measurement Spine

Reporting convention: empirical tables should report coefficient/effect size,
\(t\)-statistic, and \(p\)-value together. In text, always include the \(p\)-value
when giving a \(t\)-statistic so the significance level is immediately visible.

### Main vehicle-use outcome

Use `BridgeShare`, not raw token volume share.

\[
BridgeShare_{k,t} =
\frac{\sum_{r \in indirect(t)} 1[k \in intermediate(r)] \cdot USD(r)}
{\sum_{r \in indirect(t)} USD(r)}.
\]

Interpretation: among trades that use an intermediate token, how much intermediation
is performed by token \(k\). This is the on-chain analogue of a vehicle currency.

Do not use plain `VShare` as the main outcome. `VShare` mixes bridge use, endpoint
demand, and ordinary token turnover. It is useful as a control or diagnostic only.

Other bridge outcomes:

- `BridgeCountShare`: count-weighted version of `BridgeShare`.
- `PairCoverage`: fraction of source-destination pairs for which \(k\) appears as
  an intermediate.
- `PairMainVehicleShare`: fraction of source-destination pairs for which \(k\) is
  the largest intermediate by volume.
- `BetwCent_V`: volume-weighted route betweenness, reported as a network-theory
  cross-check.

Current implementation:

```bash
python3 scripts/run_empirical_proposition_tests.py
```

Outputs:

- `data/empirical/bridge_daily.parquet`
- `output/empirical/bridge_measure_summary_by_year.csv`
- `output/empirical/empirical_first_pass.md`

## Independent Review and Incorporation

An independent clean-room review of this design agreed with the measurement spine
but was stricter about identification. I incorporated the review as follows.

- `BridgeShare` remains the main vehicle-use outcome. Plain `VShare` is retained
  only as a diagnostic because it mixes intermediation with endpoint demand.
- Proposition 1 is still the load-bearing missing test. The paper cannot claim
  full model validation until the DVC-native route-cost panel is built.
- Proposition 2 is currently supportive association, not causal identification.
  I fixed the LP measure so it only counts pools with a known vehicle candidate
  on one side, and I drop absurd pool-level `tvlUSD` outliers from bad subgraph
  token pricing. The final table still needs date fixed effects, near-price
  executable liquidity, and mint/burn repositioning.
- Proposition 3 now has a DVC-native daily common-support event check. This
  should replace the naive aggregate daily stress regression as the first
  paper-facing stress result until the high-frequency event panel is ported.
- Proposition 4a remains only aggregate suggestive evidence until the route-cost
  panel supports pair-level direct-route feasibility.
- Proposition 4b remains conceptually clean but secondary until receipts and
  ERC-20 transfer incidence are rebuilt in DVC.

## Proposition 1. Route-Cost Advantage Creates Vehicle Use

### Model object

\[
\Delta_{ij,k,t}(q)
= C^{direct}_{ij,t}(q) - C^{vehicle}_{i k j,t}(q).
\]

The model predicts:

\[
\frac{\partial BridgeShare_{k,t}}{\partial \Delta_{ij,k,t}(q)} > 0.
\]

### Empirical proxy

For endpoint pair \(i,j\), vehicle candidate \(k\), day/hour \(t\), and trade-size
bucket \(q\):

\[
VehicleRouteAdvantage_{ij,k,t,q}
=
\frac{Output^{vehicle}_{i k j,t,q} - Output^{direct}_{ij,t,q}}
{Output^{direct}_{ij,t,q}}.
\]

Positive values mean the vehicle route gives more output than the direct route.

### Required construction

Build `data/empirical/route_cost_panel.parquet` with:

- endpoint pair \(i,j\)
- vehicle \(k\)
- timestamp day/hour
- trade-size bucket
- direct-route availability
- direct-route output
- best vehicle-route output
- fee component
- price-impact component
- source and destination symbols/addresses
- route venue(s)

Use exact AMM math where local state is available:

- Uniswap V2/Sushi V2: constant-product reserves.
- Uniswap V3: tick-level active liquidity and fee tier.
- Curve/Balancer/Fluid: initially exclude from the quoter panel unless a reliable
  pool-specific quoting module is available; keep them in realized route measures.

### Main tests

1. Route-cost validation:

\[
BridgeShare_{ij,k,t+1}
= \alpha_{ij} + \alpha_t
  + \beta VehicleRouteAdvantage_{ij,k,t,q}
  + \epsilon_{ij,k,t}.
\]

Prediction: \(\beta > 0\).

2. Foundational value-of-role exhibit:

For thin/no-direct-pool endpoint pairs, compare best direct route with best vehicle
route by trade-size bucket. This is the exhibit that shows why vehicle currencies
exist at all.

3. Trade-size heterogeneity:

Estimate the same advantage by \(q\). Small trades may favor concentrated direct
liquidity; large trades may still require deep vehicle routes.

### Exhibit

**Table. Direct routes, vehicle routes, and trade-size heterogeneity.**

Panels:

- Panel A. Direct-route availability.
- Panel B. Vehicle-route output advantage.
- Panel C. Fee versus price-impact decomposition.
- Panel D. Thin-pair value of vehicle routing.

### Current status

DVC now has a first route-cost counterfactual panel:

```bash
python3 scripts/run_route_cost_panel.py \
  --start 2020-05-11 --end 2026-06-30 \
  --top-pairs 100 --trade-sizes 1000,10000,100000
```

Outputs:

- `data/empirical/route_cost_panel_v2.parquet`
- `output/empirical/route_cost_panel_v2_summary.csv`

Scope: Uniswap V2 and SushiSwap V2 constant-product pools, using the noon UTC
hourly reserve snapshot for each day. This is a real counterfactual direct-vs-
vehicle route-cost panel, but it is not the final all-venue P1 table because it
does not yet include exact V3 tick-level quoting or Curve/Balancer/Fluid.

First-pass result: WETH is the only vehicle with a clear positive large-trade
route-cost advantage in this V2-style panel. For $10k trades, WETH beats the
direct route in 51.3% of common-support rows, median advantage 2.1 bp, winsorized
mean \(t=32.75\), \(p<0.001\). For $100k trades, WETH beats direct in 67.7% of
rows, median advantage 186.0 bp, winsorized mean \(t=53.74\), \(p<0.001\). At
$1k, the median advantage is slightly negative (-13.7 bp), consistent with the
model's trade-size heterogeneity.

DDC has reusable ingredients for the final upgrade:

- `src/ddc/v2quote.py`
- `src/ddc/v3quote.py`
- `scripts/run_crossvenue_panel_broad.py`
- `scripts/run_v3_counterfactual_quote_opportunity.py`

Data sufficiency for the V3 upgrade: no new Graph refetch is needed. DVC already
has the required Uniswap V3 swaps, mints, burns, fee tiers, ticks, and
sqrtPriceX96 fields. What is missing is not data acquisition; it is the derived
liquidity-index layer and the DVC path adapter for the old DDC exact V3 quoter.
Porting task: build those indexes from existing raw files, adapt the DDC exact
V3 quoter to DVC raw paths, and merge the resulting exact V3 quotes with the V2
panel above.

## Proposition 2. Liquidity Feedback and Stickiness

### Model object

Vehicle-linked liquidity lowers route costs and attracts future order flow:

\[
\frac{\partial BridgeShare_{k,t}}{\partial L_{ik,t}} > 0,
\quad
L_{k,t+1} = \bar L + \phi BridgeShare_{k,t}.
\]

### Empirical proxy

Primary:

- `lp_concentration_share_{k,t}`: share of Uniswap V3 LP liquidity whose base
  asset is token \(k\).

Better final version:

- near-price liquidity within 10/50/100/200 bps of current price;
- mint/burn repositioning intensity;
- net active liquidity added around the current tick.

### Current test

\[
BridgeShare_{k,t+7}
= \alpha_k + \beta LPConcentration_{k,t} + \epsilon_{k,t}.
\]

Current first-pass result is consistent with the proposition, but should be
described as association rather than causal evidence:

- raw slope: 0.5542;
- within-token slope: 0.2817;
- within-token \(t = 32.77\);
- \(p < 0.001\).

Stickiness:

\[
BridgeShare_{k,t} = \alpha_k + \rho BridgeShare_{k,t-1} + \epsilon_{k,t}.
\]

Current AR(1) estimates are 0.72-0.80 across candidate vehicles.

### Final test upgrade

Replace broad `lp_concentration_share` with near-price executable liquidity and
LP repositioning:

\[
BridgeShare_{k,t+h}
= \alpha_k + \alpha_t
  + \beta NearPriceLiquidity_{k,t}
  + \gamma Repositioning_{k,t}
  + \epsilon_{k,t}.
\]

Prediction: \(\beta > 0\), \(\gamma > 0\).

### Exhibit

**Table. LP liquidity and future vehicle share.**

Panels:

- Panel A. LP concentration.
- Panel B. Near-price executable liquidity.
- Panel C. Mint/burn repositioning.
- Panel D. Persistence and half-life.

### Current status

First pass implemented in:

```bash
python3 scripts/run_empirical_proposition_tests.py
```

Implementation note: the LP concentration input is restricted to pools with a
known vehicle candidate on one side (`WETH`, `USDC`, `USDT`, `DAI`, `WBTC`,
`FRAX`) and filters impossible single-pool TVL observations above $10bn.

Porting task: add near-price tick-liquidity measures and date-fixed-effect
specifications to DVC from the DDC V3 liquidity tooling.

## Proposition 3. Risk or Credibility Shocks Rotate Vehicle Use

### Model object

The model has a vehicle-risk or credibility wedge \(\rho_k\):

\[
\frac{\partial BridgeShare_k}{\partial \rho_k} < 0.
\]

For WETH, \(\rho_k\) is ETH downside risk. For stablecoins, \(\rho_k\) is reserve
credibility or peg risk.

### Why the naive daily test is not sufficient

A daily regression of aggregate `BridgeShare` on ETH downside returns is too blunt:
it mixes changes in the opportunity set with changes in route choice. The first
pass finds no meaningful effect in the naive daily aggregate specification. That
should not be a main result.

### Main stress design

Use common-support route opportunities:

- event-hour or event-day panel;
- endpoint pair fixed effects;
- event-time fixed effects;
- candidate vehicle fixed effects;
- compare WETH against stable vehicles inside the same source-destination
  opportunity set.

Core specification:

\[
Share_{ij,k,e,h}
= \alpha_{ij,e} + \alpha_h + \alpha_k
  + \beta (WETH_k \times Stress_{e,h})
  + \epsilon_{ij,k,e,h}.
\]

Prediction: \(\beta < 0\). WETH loses vehicle share under ETH downside stress
relative to stable vehicles within the same endpoint-pair opportunity set.

### Recovery and stickiness

For each event, estimate the event-time path:

\[
BridgeShare_{WETH,e,\tau} - BridgeShare_{stable,e,\tau}.
\]

Report:

- trough effect;
- recovery fraction by 24/48/72 hours;
- half-life if reached;
- persistent shift if not reached.

### Stablecoin credibility event

USDC/SVB depeg:

- \(k = USDC\);
- shock is peg widening / depeg severity;
- outcome is route-endpoint flight and substitute stablecoin bridge use;
- distinguish route-intermediation from endpoint demand.

### Exhibit

**Table. Common-support WETH route rotation under stress.**

**Figure. Event-time vehicle share around downside-stress episodes.**

### Current status

DVC now has a daily common-support event check. For each large WETH downside
day, it compares WETH-minus-stable bridge share against the same endpoint
pairs' prior 14-day baseline.

Current DVC first-pass result:

- events: 27;
- mean WETH-minus-stable effect: -5.41 percentage points;
- \(t = -4.50\);
- \(p = 0.0001\).

This is model-consistent evidence that WETH loses bridge role relative to stable
vehicles inside common route opportunities during downside stress. It is still
daily rather than hourly, so the final paper should port the high-frequency
design before freezing the table.

DDC has reusable high-frequency design and code:

- `scripts/run_hfpanel.py`
- `scripts/run_hfpanel_doseresponse.py`
- `scripts/run_v3_route_cost_opportunity.py`
- `scripts/run_vehicle_recovery.py`
- `src/ddc/hfpanel.py`

Porting task: create DVC-native high-frequency route panel from
`data/unified/YYYYMMDD.parquet` and run the common-support stress design.

## Proposition 4a. Concentrated Liquidity Changes Route Feasibility

### Model object

V3-style concentrated liquidity raises direct-route executable liquidity:

\[
\frac{\partial BridgeShare}{\partial a} < 0
\]

where \(a\) scales direct-pool liquidity.

### First-pass result

The one-year window around V3 launch shows:

- WETH `BridgeShare`: -29.6 pp;
- USDC `BridgeShare`: +22.1 pp;
- USDT `BridgeShare`: +5.4 pp.

This is directionally consistent with architecture changing the vehicle
equilibrium, but it is not yet the final design because it is an aggregate
mean-shift.

### Final design

Pair-level direct-route feasibility:

\[
DirectFeasible_{ij,t,q}
= 1[Output^{direct}_{ij,t,q} > 0].
\]

Direct-liquidity treatment:

\[
Treatment_{ij,t}
= 1[\text{pair } ij \text{ gets a deep V3 direct pool near launch}].
\]

Event-study:

\[
VehicleReliance_{ij,t}
= \alpha_{ij} + \alpha_t
  + \sum_{\tau \ne -1} \beta_\tau
    1[eventtime_{ij,t}=\tau] \times Treated_{ij}
  + \epsilon_{ij,t}.
\]

Prediction: treated pairs whose direct-route liquidity improves should rely less
on vehicle routes.

### Exhibit

**Figure. Vehicle routes around concentrated-liquidity adoption.**

Panels:

- Panel A. Direct-route feasibility.
- Panel B. Direct-route executable depth.
- Panel C. Vehicle-route reliance.
- Panel D. Direct versus vehicle route cost.

### Current status

Aggregate first pass implemented in `scripts/run_empirical_proposition_tests.py`.
Final pair-level design requires the route-cost panel from Proposition 1.

## Proposition 4b. Flash Accounting Virtualizes Settlement

### Model object

V4 flash accounting keeps gross route exposure but reduces physical movement:

\[
PhysicalMovement = (1-n) GrossVehicleExposure,
\quad
\frac{\partial PhysicalMovement}{\partial n} < 0.
\]

### Empirical proxy

For matched V3/V4 route units:

\[
TransferIncidence_{r,k}
= 1[\text{receipt contains ERC-20 Transfer of intermediate token } k].
\]

Virtual vehicle share:

\[
VirtualVehicleShare_{k}
=
\frac{RouteVolume(k \text{ intermediate, no } k \text{ Transfer})}
{RouteVolume(k \text{ intermediate})}.
\]

### Identification

Match on:

- endpoint pair \(i,j\);
- week;
- intermediate token \(k\);
- route class;
- route-size bucket where possible.

Specification:

\[
TransferIncidence_{r}
= \alpha_{ij,k,w} + \beta V4_r + \epsilon_r.
\]

Prediction: \(\beta < 0\). V4 lowers physical intermediary-token movement
conditional on the route still using the same vehicle.

### Exhibit

**Table. V4 matched settlement-implementation first stage.**

Panels:

- Panel A. Matched route-cell construction.
- Panel B. Transfer incidence by protocol.
- Panel C. No-transfer vehicle volume by token.
- Panel D. Compression ratio / virtual-vehicle share.

### Current status

Not yet rebuilt in DVC, but DDC already has the empirical logic:

- `scripts/run_v4_virtual_vehicle_tests.py`
- `scripts/run_v4_settlement_identification.py`
- `docs/v4_settlement_identification.md`

Porting task: adapt receipt fetching to DVC raw/unified layout and cache receipts
under `data/empirical/v4_receipts/`.

## Final Main-Paper Validation Sequence

The main paper should validate the model in this order:

1. **Measurement:** show `BridgeShare`, `BetwCent_V`, and pair coverage. Establish
   that the paper measures bridge use, not endpoint demand.
2. **P1 route-cost advantage:** show that vehicle routes are economically valuable
   where direct routes are unavailable or expensive.
3. **P2 liquidity feedback:** show LP liquidity predicts future bridge use and
   bridge use is persistent.
4. **P3 stress rotation:** show WETH loses bridge role under downside stress within
   common route opportunities, with recovery/half-life.
5. **P4 architecture:** show V3 changes direct-route feasibility and V4 separates
   route intermediation from physical settlement.

This sequence mirrors the model: route cost creates vehicle use; liquidity makes
it sticky; shocks perturb it; architecture changes the mapping between route use,
liquidity, and settlement.

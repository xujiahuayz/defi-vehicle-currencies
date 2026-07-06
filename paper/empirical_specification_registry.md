# Empirical Specification Registry

This registry is the pre-write contract for the empirical section. It separates
what the estimates identify from what they do not identify.

## P1. Route Availability and Thin-Direct-Market Value

- Unit: endpoint-pair, vehicle, date, trade-size bucket.
- Main sample: route-cost panel for WETH using V2/Sushi V2 constant-product
  state plus DVC-native exact-crossing V3 tick-net quotes.
- Main outcomes: direct-route availability, WETH-route availability,
  no-direct/WETH-available indicator, common-support route-cost advantage.
- Main estimand: availability and execution-cost value of the vehicle route
  relative to direct routing, especially when direct liquidity is missing or thin.
- Inference: endpoint-pair-day aggregation for central t-tests; report p-values.
- Weights: report equal-weighted, realized-bridge-volume-weighted, and
  endpoint-pair-day estimates.
- Identification claim: descriptive counterfactual quote evidence, not causal
  proof that WETH always lowers costs.

## P2. Liquidity Concentration and Stickiness

- Unit: token-day.
- Main sample: candidate vehicle tokens WETH, USDC, USDT, DAI, WBTC.
- Main outcomes: future BridgeShare and BridgeShare persistence.
- Main regressor: vehicle-linked LP concentration.
- Fixed effects: token and date fixed effects in robustness.
- Inference: date-clustered or block-bootstrap inference.
- Identification claim: predictive association and persistence. Do not claim
  causal LP feedback unless a separate shock design is added.
- Repositioning diagnostic: currently not positive-clean; use as a limitation
  or referee-proofing diagnostic, not as mechanism evidence.

## P3. Stress Rotation

- Unit: stress event by endpoint-pair opportunity set.
- Main treatment: large WETH downside events, defined from WETH returns.
- Main outcome: WETH-minus-stable BridgeShare within common-support endpoint
  pairs.
- Required decomposition: WETH share change, stable share change, aggregate
  direct-route share change, and indirect-route volume change.
- Baseline: prior 28 days unless stated otherwise.
- Inference: event-level t-tests and placebo/randomization distributions.
- Identification claim: short-window event association, not persistent stress
  regime rotation.

## P4a. V3 Architecture

- Unit: endpoint-pair/date/trade-size bucket around the V3 launch.
- Main outcomes: direct-route availability, WETH-route availability,
  no-direct/WETH-available cases, and direct-route quality.
- Fixed effects: endpoint-pair fixed effects; event-time/pre-trend checks still
  required before causal launch language.
- Identification claim: route-opportunity expansion evidence, not a clean causal
  estimate unless a control group/pre-trend design is added.

## P4b. V4 Settlement Virtualization

- Unit: matched V3/V4 route unit or matched route cell.
- Main outcome: ERC-20 transfer incidence of the intermediary token.
- Matching: week, endpoint pair, intermediate vehicle token, and route-size
  cells where available.
- Required validation: receipt-parser checks against known V4 flash-accounting
  examples and matched-cell balance diagnostics.
- Identification claim: settlement-mechanics evidence conditional on matched
  route use; not a claim that V4 eliminates vehicle currencies.

## Cross-Chain Scope

Cross-chain native-asset replication is an external-validity extension, not a
prerequisite for the Ethereum vehicle-currency paper. It becomes necessary only
if the paper claims a universal native-currency mechanism rather than an
Ethereum/AMM vehicle-currency mechanism. If added, the clean design is to use
chain-level replications for WETH-on-Ethereum, WBNB-on-BNB, WMATIC-on-Polygon,
WAVAX-on-Avalanche, and WETH/ETH-on-Base/Arbitrum/Optimism, using the same
BridgeShare, route-cost availability, and direct-route-substitution definitions.

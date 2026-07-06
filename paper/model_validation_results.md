# Model Validation Results

Generated after the DVC rebuild through 2026-06-30.

## Measurement

The paper-facing vehicle-use proxy is `BridgeShare`: USD route volume of
indirect routes in which a token is an intermediate, divided by total USD volume
of indirect routes. In 2026, WETH remains the largest route intermediary
(`BridgeShare` 44.5%), followed by USDT (23.6%) and USDC (20.7%). This differs
from raw volume share because raw volume mixes endpoint demand with bridge use.

## Proposition 1. Route-Cost Advantage

The DVC route-cost panel now uses Uniswap V2 and SushiSwap V2 constant-product
reserves plus exact-crossing Uniswap V3 tick-net quotes reconstructed from raw
mints, burns, and swap-state cutoffs.

WETH results:

| Trade size | Common-support rows | Beats direct | Median advantage | t | p |
|---:|---:|---:|---:|---:|---:|
| $1k | 48,840 | 59.6% | 27.7 bp | 33.04 | <0.001 |
| $10k | 48,840 | 56.6% | 21.5 bp | 45.06 | <0.001 |
| $100k | 48,840 | 49.9% | -0.4 bp | 63.95 | <0.001 |

Interpretation: the evidence is not that WETH is always cheaper. WETH is valuable
because it supplies availability and upper-tail execution-cost protection when
direct liquidity is missing or thin. There are 9,584 rows where the WETH vehicle
route is available and no direct route is available.

Robustness: direct-route quality filters sharpen this interpretation. When the
direct route itself has high output quality, the median WETH advantage shrinks or
turns negative. The main P1 claim should therefore be written as a route
availability / thin-direct-liquidity result, not as a universal cost-saving
claim on already deep direct markets.

## Proposition 2. Liquidity Feedback and Stickiness

Vehicle-linked LP concentration predicts future bridge use. The within-token
association is 0.2817 with \(t=32.77\), \(p<0.001\). Bridge use is persistent:
daily AR(1) coefficients range from 0.720 for USDT to 0.798 for WETH, all with
\(p<0.001\).

Interpretation: this supports the liquidity-feedback channel, but the main-paper
version should still strengthen the specification with date fixed effects,
near-price executable liquidity, and LP repositioning.

Robustness: the liquidity-feedback slope remains positive for 1-, 7-, 14-, and
30-day forward BridgeShare, and survives token and date fixed effects.

## Proposition 3. Stress Rotation

The naive aggregate stress regression is not informative. The paper-facing result
is the common-support event design: in large WETH downside events, WETH-minus-stable
bridge share falls by 5.4 percentage points within the same endpoint-pair
opportunity sets (\(t=-4.50\), \(p=0.0001\)).

Interpretation: stress rotates vehicle use away from the risky incumbent within
route opportunities that already support both WETH and stablecoin intermediaries.

Robustness: the effect remains negative under unweighted event averaging, when
the largest event is dropped, and when the sample is restricted to events with
at least 2,000 endpoint pairs. The top-10-stress-only slice is negative but not
statistically significant, so the paper should not overstate concentration in
the single largest events.

## Proposition 4a. Concentrated-Liquidity Architecture

The current aggregate V3-launch screen shows a large fall in WETH bridge share
and increases in USDC/USDT bridge share after V3 launch. This is directionally
consistent with architecture changing route feasibility, but it remains a screen
until connected directly to pair-level direct-route feasibility and the route-cost
panel.

## Proposition 4b. V4 Settlement Virtualization

The DVC receipt-level design matches coherent multi-hop V3 and V4 route units by
week, endpoint pair, and intermediate vehicle token. V4 reduces intermediary-token
ERC-20 transfer incidence from 100.0% to 81.4%, a -18.6 percentage-point
difference (\(t=-10.68\), \(p<0.001\)).

Interpretation: V4 does not eliminate vehicle routing. It partially virtualizes
settlement by weakening the mapping between route intermediation and physical
token movement.

Robustness: the V4 transfer-incidence gap is strongest for small routes, remains
negative for medium routes, and is small for large routes. That pattern is useful
for interpretation: flash accounting mainly virtualizes the settlement mechanics
of smaller route units rather than uniformly eliminating physical transfers.

## Current Paper Claim

The model now has first-pass DVC-native evidence on all four dimensions, but the
JFE-safe claim is narrower than "all propositions are established." The current
evidence supports the following cautious claims:

1. route-cost and availability advantages are consistent with vehicle usefulness,
   especially when direct routes are missing or thin;
2. vehicle-linked liquidity is strongly associated with future bridge use and
   bridge-use persistence;
3. stress rotates vehicle use away from a risky incumbent in daily common-support
   event designs;
4. V4 partially separates route intermediation from physical intermediary-token
   transfer settlement.

Before a JFE-style write-up, the remaining pre-write upgrades are inference at
the correct dependence unit, route-cost tables centered on availability and
thin-direct-route value, high-frequency/common-support stress evidence or
explicitly narrower daily-event wording, and a tighter pair-level V3 architecture
design. The conservative remaining caveats are executable-depth quotes for
Curve/Balancer/Fluid, transaction-time rather than daily cutoff state for quote
panels, and expanded V4 matched-cell balance diagnostics.

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

High-frequency robustness: the hourly common-support event panel is directionally
consistent but weaker. Across the top 20 WETH downside events, hourly
WETH-minus-stable BridgeShare falls by 1.71 percentage points relative to the
same endpoint pair and hour-of-day baseline, with \(t=-1.46\), \(p=0.161\).
This disciplines the write-up: the daily common-support event design remains the
main P3 evidence; the hourly result should be presented as a weaker
high-frequency check, not as an independent headline result.

Weekly robustness: aggregating over the event week does not restore statistical
power. WETH-minus-stable BridgeShare falls by 1.15 percentage points relative to
the same endpoint pairs over the prior four weeks, with \(t=-0.98\), \(p=0.340\).
The interpretation is that the stress rotation is a short-window event response,
not a week-long persistent shift in the full common-support set.

Event-window and placebo checks sharpen this interpretation. Using a 28-day
pre-event baseline, the same-day stress effect is -3.09 pp (\(t=-2.48\),
\(p=0.024\)); the two-day window is -2.18 pp (\(t=-2.02\), \(p=0.059\)); three-
and seven-day windows are not significant. The simple shifted-date placebo does
not mimic the same pattern: the one-day placebo effect has the opposite sign.
The write-up should therefore emphasize immediate stress rotation, not
multi-day persistence.

## Proposition 4a. Concentrated-Liquidity Architecture

The current aggregate V3-launch screen shows a large fall in WETH bridge share
and increases in USDC/USDT bridge share after V3 launch. This is directionally
consistent with architecture changing route feasibility, but it remains a screen
until connected directly to pair-level direct-route feasibility and the route-cost
panel.

The pair-level route-feasibility design now connects this architecture channel
to endpoint-pair opportunities around the May 5, 2021 Uniswap V3 launch. In a
balanced endpoint-pair sample with pair fixed effects, direct-route availability
increases by 27.58 pp (\(t=4.80\), \(p<0.001\)), WETH-route availability also
increases by 7.50 pp (\(t=4.64\), \(p<0.001\)), and no-direct-but-WETH-available
cases fall by 22.72 pp (\(t=-4.70\), \(p<0.001\)). The common-support WETH
advantage itself falls by 647 bp but is not statistically significant
(\(p=0.310\)). Interpretation: V3 primarily changes the route-opportunity set by
making direct routes feasible, rather than delivering a clean common-support WETH
price improvement.

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

Additional pre-write robustness now covers two construct-validity gaps:
Curve/Balancer/Fluid executable-depth coverage and transaction-time quote-state
robustness. Balancer weighted-pool quotes are feasible from the rebuilt raw
state, but Curve and Fluid are defensibly excluded from exact executable-depth
quotes because the current raw layer lacks the necessary amplification/ramp or
reserve/depth state. For V2/Sushi V2 hourly reserves, route-hour and daily-state
WETH route-cost advantages have median differences of 0 bp across the $1k, $10k,
and $100k trade-size buckets, with same-sign shares of 76.4%, 80.4%, and 93.3%.
The Balancer weighted-pool quote extension is now executed: Balancer contributes
some WETH-route quote availability in the matched route-cost universe, but it
adds no direct-route or WETH-route rows beyond the existing V2/Sushi V2/V3 panel
in this test. Thus Balancer does not overturn the P1 route-availability result.

Two further pre-write checks are now available. First, the WETH route-cost value
decomposition shows that the strongest economic role is availability and
thin-direct-market protection: WETH is available when no direct route exists in
9,584 rows, and the median thin-direct advantage is 142.65, 190.21, and 349.28
bp for $1k, $10k, and $100k trades. High-quality direct routes show much smaller
or negative medians, so the paper should not claim universal WETH cheapness.
Second, V3 mint/burn repositioning is not a clean positive mechanism result in
the current specification. Near-price gross repositioning is negative at 7- and
14-day horizons, and near net repositioning is negative at 14 days. This table
should be used as a referee-proofing diagnostic, not as a main P2 claim.

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

Before a JFE-style write-up, the remaining caveat is not an empty empirical
spine but scope discipline: write the stress result primarily as a daily
common-support event result, keep V3 architecture appendix/suggestive unless a
tighter pair-level design is added, and state clearly that transaction-time quote
robustness is hourly V2/Sushi V2 rather than exact V3 tick replay.

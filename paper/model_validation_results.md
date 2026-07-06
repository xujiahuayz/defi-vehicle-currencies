# Model Validation Results

Generated after the DVC rebuild through 2026-06-30.

## Measurement

The paper-facing vehicle-use proxy is `BridgeShare`: USD route volume of
indirect routes in which a token is an intermediate, divided by total USD volume
of indirect routes. In 2026, WETH remains the largest route intermediary
(`BridgeShare` 44.5%), followed by USDT (23.6%) and USDC (20.7%). This differs
from raw volume share because raw volume mixes endpoint demand with bridge use.

## Proposition 1. Availability and Thin-Direct-Market Protection

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

## Proposition 2. Liquidity Concentration and Bridge-Use Persistence

Vehicle-linked LP concentration predicts future bridge use. The within-token
association is 0.2817 with \(t=32.77\), \(p<0.001\). Bridge use is persistent:
daily AR(1) coefficients range from 0.720 for USDT to 0.798 for WETH, all with
\(p<0.001\).

Interpretation: this is predictive association and persistence, not identified
causal liquidity feedback. Reverse causality, common demand shocks, token
popularity, volatility, and router behavior are not ruled out.

Robustness: the predictive slope remains positive for 1-, 7-, 14-, and 30-day
forward BridgeShare, and survives token and date fixed effects.

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

## JFE Construct-Validity Round

After the second independent review, I added a dedicated construct-validity and
identification pass:

```bash
python scripts/run_jfe_construct_validity_checks.py
```

Outputs:

- `paper/empirical_specification_registry.md`
- `output/tables/table_r16_bridge_denominator_robustness.{csv,tex}`
- `output/tables/table_r17_route_cost_distribution_weighting.{csv,tex}`
- `output/tables/table_r18_stress_rotation_decomposition.{csv,tex}`

### BridgeShare denominator robustness

The indirect-route denominator is still the right paper-facing object if the
question is "conditional on routing through an intermediate, which token is the
vehicle?" But the all-route denominator is now reported because it makes direct
route substitution explicit. In 2026:

| Token | Indirect BridgeShare | All-route bridge share | PairCoverage |
|---|---:|---:|---:|
| WETH | 44.5% | 5.3% | 50.0% |
| USDC | 20.6% | 2.5% | 25.3% |
| USDT | 23.6% | 3.0% | 20.7% |

Interpretation: WETH remains the leading intermediary conditional on indirect
routing, but direct routing dominates total volume in 2026. The paper should
state both facts rather than letting BridgeShare sound like a share of all DEX
volume.

### Route-cost distribution and economic weighting

The new route-cost table reports mean, median, p10/p90, volume-weighted mean,
and dollar savings. This resolves the earlier concern that a positive t-statistic
could be read as positive median cost dominance. The result is highly skewed:
the median WETH advantage is small or negative at larger trade sizes, while the
upper tail and no-direct-route cases are economically large. This reinforces the
proper P1 wording: WETH is an availability and thin-direct-market protection
technology, not universally the cheapest route.

### Stress-rotation decomposition

The stress result is now decomposed into WETH loss, stablecoin gain, direct-route
substitution, and indirect-route volume. Across the top 20 WETH downside events:

- WETH share falls by 1.48 pp, \(t=-2.59\), \(p=0.018\).
- Stablecoin share rises by 1.48 pp, \(t=2.59\), \(p=0.018\).
- WETH-minus-stable falls by 2.96 pp, \(t=-2.59\), \(p=0.018\).
- Aggregate direct-route share changes by only -0.25 pp, \(p=0.679\).
- Log indirect-route volume rises by 0.51, \(p=0.005\).

Interpretation: the daily event result is not just direct-route substitution; it
is a within-indirect-route rotation from WETH to stable vehicles during stress.
The claim should still be short-window, not persistent.

### Cross-chain scope

Cross-chain native-asset replication is not required for the Ethereum paper
unless the manuscript claims a universal native-currency mechanism. It is an
external-validity extension. If added, it should be designed as a replication
across WETH/ETH on Ethereum and L2s plus WBNB, WMATIC, and WAVAX, using the same
BridgeShare, all-route denominator, route availability, and direct-route
substitution definitions.

## Identification Extensions

I then added two architecture-specific checks:

```bash
python scripts/run_jfe_identification_extensions.py
```

Outputs:

- `output/tables/table_r19_v3_event_time_pretrends.{csv,tex}`
- `output/tables/table_r20_v4_receipt_parser_validation.{csv,tex}`
- `output/empirical/v4_no_transfer_manual_audit_sample.csv`

### V3 event-time and pre-trends

The event-time version confirms the post-V3 route-opportunity result, but it also
shows why V3 should still be written carefully:

- Direct-route availability rises 31.78 pp after V3, \(p<0.001\), but the
  pretrend is already positive, \(p=0.002\).
- WETH-route availability rises 7.99 pp after V3, \(p<0.001\), but also has a
  positive pretrend, \(p<0.001\).
- No-direct/WETH-available cases fall 25.81 pp after V3, \(p<0.001\), and this
  outcome has no detectable pretrend, \(p=0.922\).
- Common-support WETH advantage is not statistically changed after V3,
  \(p=0.935\), and the pretrend is non-flat.

Interpretation: the usable V3 result is the collapse in no-direct/WETH-available
cases. It supports the architecture story that V3 expands direct-route
feasibility, but we should avoid a strong causal launch claim for every V3
outcome because several route-opportunity measures were already trending.

### V4 receipt-parser validation

The parser validation strengthens the V4 settlement result:

- V3 receipt coverage is 100%, and V3 intermediary transfer incidence is 100%.
  This is the positive-control check: the parser detects standard intermediary
  token transfers when they should be present.
- V4 receipt coverage is also 100%.
- V4 transfer incidence is 81.4%.
- The 93 V4 no-transfer receipts are still populated: 100% have nonempty logs,
  with mean total logs of 12.47 and zero matching intermediary-token transfers.

Interpretation: the V4 no-transfer result is not caused by missing receipts or
empty receipt parsing. The remaining paper defense is to manually inspect the
exported no-transfer sample against known V4 flash-accounting behavior if the
result becomes a main-table claim.

## Remaining Blocker Fixes

I added a final pre-write blocker pass:

```bash
python scripts/run_jfe_remaining_blocker_fixes.py
```

Outputs:

- `output/tables/table_r21_stress_event_definition.{csv,tex}`
- `output/tables/table_r22_stress_design_summary.{csv,tex}`
- `output/tables/table_r23_curve_fluid_materiality.{csv,tex}`
- `output/tables/table_r24_v4_manual_audit.{csv,tex}`
- `output/tables/table_r25_main_test_registry.{csv,tex}`

### Stress event specification

The main stress design is now explicit. Candidate events are WETH downside log
returns of at least 8%, after dropping absolute daily WETH returns above 50% as
price-construction outliers. There are 52 candidate days and the main design
uses the top 20 downside days. Four of the selected events have another selected
event within 14 days, so overlap is visible rather than hidden. The baseline
window is the prior 28 calendar days.

Stress threshold and overlap sensitivity now supports the same sign and
significance:

- all events with 6% threshold: -3.12 pp, \(p<0.001\);
- all events with 8% threshold: -2.95 pp, \(p=0.001\);
- all events with 10% threshold: -3.74 pp, \(p=0.001\);
- all events with 12% threshold: -3.18 pp, \(p=0.015\);
- non-overlapping 8% events: -3.01 pp, \(p=0.020\).

### Curve and Fluid materiality

Curve and Fluid remain material exclusions from the exact executable-depth route
cost panel:

- Curve is 11.5% of unified leg volume, with 71.5% stablecoin-leg share.
- Fluid is 4.7% of unified leg volume, with 84.5% stablecoin-leg share.
- Together they are 16.2% of leg volume and heavily stablecoin-oriented.

Interpretation: the route-cost panel must be described as exact executable-depth
evidence for the covered quoteable venues, not the whole DEX universe. The
realized BridgeShare and stress measures still include Curve and Fluid; the
limitation is specifically executable-depth counterfactual quoting.

### V4 manual no-transfer audit

The manual audit now checks all 93 sampled V4 route units with no
intermediary-token transfer. All 93 have populated receipts, all 93 have source
or sink token transfers in the receipt, and all 93 have zero ERC-20 Transfer
logs for the sampled route intermediary. This materially strengthens the V4
virtual-settlement interpretation: the route exists, endpoint tokens move, but
the intermediary token need not move externally.

### Latest independent review status

After these fixes, the independent-review verdict moved from **reject** to
**major revisions**. The remaining issues are now mainly framing and scope
control rather than missing core results:

- P2 must be titled and written as predictability/stickiness, not causal
  liquidity feedback.
- P1 must be titled and written as availability/thin-direct protection in
  covered quoteable venues, not universal route-cost advantage.
- Curve/Fluid exact-quote exclusion must be explicit because the excluded venues
  are material and stablecoin-heavy.
- Main text must always pair indirect BridgeShare with all-route bridge share
  when introducing WETH's vehicle role.

I added two further diagnostics to close the remaining empirical parts of those
comments:

- Curve/Fluid scope bound: exact-quote covered venues are 78.9% of unified leg
  volume; excluded Curve+Fluid are 16.2%, equal to 20.5% of covered quoteable
  volume, and 75.3% stablecoin-leg. This does not remove the limitation, but it
  quantifies its maximum scope and forces the P1 claim to covered quoteable
  venues.
- Curve/Fluid exclusion sensitivity: rebuilding 2026 realized BridgeShare after
  dropping Curve and Fluid does not overturn the main vehicle-use ranking. WETH
  BridgeShare changes from 44.5% to 44.9%; USDC rises from 20.6% to 21.7%;
  USDT falls from 23.6% to 17.5%. PairCoverage moves by less than 1 pp for the
  major vehicles. This closes the realized-measure concern, while exact
  executable-depth quotes remain scoped to quoteable venues.
- V4 balance diagnostics: V3 and V4 matched samples have identical ETH/WETH and
  stable-vehicle composition by construction, but V4 route units are smaller
  within matched cells (log route-size difference -0.692, \(p<0.001\)). The V4
  settlement result should therefore report size-bin robustness and state this
  balance fact directly.

### Frozen main-test registry

The paper now has one pre-specified main test per proposition:

1. P1: WETH availability/thin-direct-market protection.
2. P2: LP concentration predicts future BridgeShare, explicitly downgraded to
   predictive association.
3. P3: same-day WETH downside event decomposition.
4. P4a: V3 no-direct/WETH-available decline.
5. P4b: V4 intermediary transfer incidence plus no-transfer audit.

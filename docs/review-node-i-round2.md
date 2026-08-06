# Node I, round 2: adversarial review of the findings lock

Node I output, 2026-08-07. Scope: the corrected route topology and value panels, `docs/findings-freeze.md`, `docs/specification-lock.json`, `docs/finding-intermediation-transition.md`, `docs/finding-cost-dominance-measured.md`, `docs/finding-rent-incidence.md`, and the routing-maturation rival. The standard is whether the locked claim family could survive a *Journal of Financial Economics* desk review, not whether the code is cleaner than round 1.

## Verdict

**The round-1 measurement objection is substantially resolved. The paper would still be desk-rejected today because its three strongest facts do not yet form one identified economic argument. Approval to enter the F–G–H cluster is conditional on the reroutes below.**

The improved case is real. The vehicle rotation is measured on 47.6 million intermediary episodes with full topology coverage and survives single-venue, cross-venue, two-leg and longer routes. The exact-state branch no longer prices realised routes at hour end and no longer uses pooled gas: 45,720 routes have strict pre-transaction direct alternatives, 11.7% are dominated gross and 31.1% under median matched gas. The rent result survives an open-to-close LVR bound. These repairs retire the round-1 claim that the headline was mainly off-support quote error.

The remaining editorial problem is connection. Stable vehicles gain share; direct routes are sometimes cheaper on a shrinking legacy perimeter; native-long-tail LP trading revenue does not cover measured LVR and gas. None of those facts currently identifies why the stable share rose. Calling rent incidence the mechanism would overstate what is estimated, and calling routing maturation a control would overstate an hour-end frontier that the lock itself withholds.

## Ranked objections

| rank | objection | severity | current disposition |
|---:|---|---|---|
| 1 | The primary vehicle unit gives longer routes more votes | fatal to the lead estimand as locked | return to C/E; no data rebuild needed |
| 2 | The transition has no completed within-opportunity mechanism test | fatal to the paper's current causal narrative | F must estimate it or the paper must remain explicitly descriptive |
| 3 | Direct-cost dominance lacks durable statistical and dollar magnitudes | major | F can repair from the existing exact-state panel |
| 4 | Receipt gas is matched route cost, not a clean marginal-hop experiment | major | retain IQR and same-executor bounds; narrow the interpretation |
| 5 | Rent incidence is not yet linked to vehicle succession | major | estimate role-by-time capital and return reallocation; do not call it the transition mechanism before that |
| 6 | The prose evidence maps still carry retired headline numbers | major downstream contamination risk | G/H must rebuild from the lock before any prose pass |

## 1. The primary unit is wrong for the lead claim

The lock defines one observation as one non-endpoint asset occurrence. A route with three intermediary assets therefore contributes three votes while an ordinary two-leg route contributes one. This matters because routes longer than two legs rise sharply over the sample, from 9.8% of economic multi-leg routes in 2020 to 28.5% in 2026. A change in route length can change the episode-weighted vehicle mix even if the distribution of one-vehicle route choices is fixed.

The existing result contains its own clean repair. On two-leg routes, one route has exactly one vehicle and therefore one vote. The stable share within native plus stable rises 25.4 percentage points between 2024 and 2026 on common calendar support, with a 30-day HAC standard error of 1.05 points. The strict-value increase is 43.9 points. The transition therefore survives the stricter definition.

**Reroute:** make two-leg, one-vehicle routes the primary vehicle-choice unit. Report all intermediary episodes as the extensive network measure and longer routes as a prespecified extension. This is a C/E definition correction, not a robustness footnote.

## 2. The paper still lacks the test that separates succession from routing maturation

Integration and complexity are not sufficient controls for search efficiency. The stable shift survives both, which rejects two simple composition stories. A modern router can still search more pools, access private flow, split differently, or use a better direct path inside the same integration and hop-count cell. The V2-family exact-state branch cannot supply the missing trend because its support falls from 21,907 routes in 2021 to 109 in 2026.

The specification lock correctly withholds the full claim, but the paper architecture still calls rent incidence the mechanism and routing maturation the rival. A rival that has no admissible test cannot lose the horse race. A mechanism estimated in a separate pool-role panel cannot win it.

**Reroute:** F must either build a strict transaction-state, fixed-reach candidate-choice design or state in the first two pages that the paper establishes formation facts and bounds mechanisms without identifying the cause of the transition. The latter can be publishable only if the measurement contribution and economic magnitudes are exceptional. Do not fill the gap with router release windows or executor labels; both are descriptive and the release signs are mixed.

## 3. The dominance incidence needs uncertainty, weighting sensitivity, and dollars

The pooled 31.1% all-in incidence is route weighted across 73 nonempty monthly dates. Its date-clustered standard error is 2.18 percentage points, giving a 95% interval of 26.9% to 35.4%. Equal-date weighting gives 23.5%, well below the pooled estimate because 2020 and 2021 supply most routes. Gross incidence is 11.7% with a date-clustered interval of 8.8% to 14.6%; the equal-date mean is 13.2%.

This does not overturn the level condition. It changes how it must be presented. A JFE reader needs both weighting schemes because the fixed monthly sampling calendar and the number of surviving comparable routes are distinct design choices. The reader also needs the economic amount: median and aggregate dollars saved by switching to direct, split by size and strict valuation support. Basis-point incidence alone cannot say whether this is a retail fixed-cost nuisance or economically important foregone surplus.

**Reroute:** store pooled, equal-date, date-clustered interval, median dollars and aggregate sampled-date dollars in the canonical exhibit. The console transcript is not an evidence artifact.

## 4. The gas result is much stronger than a constant and weaker than a marginal-hop experiment

The new panel is a material advance: 31,128 receipts, 2,655 matched cells, exact year-by-venue-by-vehicle support on every direct route, and no topology fallback in the dominance application. The repeated-venue same-executor comparison finds a 67,172-unit median second-leg increment, positive in 90.1% of 162 cells.

The limitation is that total transaction gas includes calldata, transfers, approvals, router bookkeeping and any bundled action. The dominance application matches year, venue sequence and vehicle, but it does not hold executor and transaction purpose fixed. The IQR sensitivity partially bounds this; it does not turn total receipt gas into the causal cost of adding a hop.

**Disposition:** retain the all-in result as matched historical route cost. Describe the 67,172-unit comparison as the marginal-hop validation. Do not say the whole 31.1% shift is caused by the second pool leg.

## 5. Rent incidence is a separate finding until a transition link is estimated

The v2 result is economically sharp: native-other pools are 80% of pool-days, only 21.6% pay under the hourly LVR measure, and the median net yield remains negative under the open-to-close bound. The role tests cluster by pool and reject equality. The paper can say trading revenue is insufficient to compensate measured LVR and gas in the long tail.

It cannot yet say these losses sustain native incumbency or cause stable succession. Token incentives are unmeasured, the CEX-reference confound remains, and the stable takeover is carried by USDT and USDC while the rent grouping is a pair-role partition. The missing bridge is whether capital and net returns migrate from native-long-tail spokes toward fiat-reserve stable spokes before the routing share moves.

**Reroute:** estimate capital, fee/LVR ratio, net return and entry/exit by vehicle role over event time around the observed 2024 to 2026 rotation. Treat it as descriptive temporal ordering unless a predetermined shock supplies identification. If no migration appears, rent incidence remains a companion distributional result and leaves the mechanism slot.

## 6. What round 1 got wrong after the rebuild

Round 1's strongest objection was that hour-level counterfactual gaps of hundreds or thousands of basis points could be off-support quoter error. That objection does not carry over mechanically. The replacement compares an executed two-leg route with a one-leg direct pool at strict pre-transaction block-log state, uses the exact realised input, replays liquidity events, and reports a strict valuation screen. The median gross advantage among dominated routes is 76.7 basis points, not the retired 2,459-basis-point native median. Reserve-support classes agree in sign. The old four-day matched and enumerated estimates remain inadmissible, but the exact-state level condition survives.

Round 1 was right that the paper needed an executability section, candidate-specific gas, continuous economic magnitudes, a time dimension, and a question beyond “is the thickest network cheapest.” The current work resolves the first two, partly resolves the third, and leaves the mechanism time dimension open.

## Requirements before approval to the F–G–H cluster

1. Redefine the lead vehicle-choice unit to two-leg routes and regenerate the headline table without changing the all-episode extension.
2. Add date-clustered and equal-date incidence plus dollar magnitudes to the exact-state dominance exhibit.
3. Run the locked log-odds and weighting alternatives for the transition; apply Holm adjustment within the primary family.
4. Build the role-by-time LP capital and return bridge, or demote rent incidence from mechanism to companion finding.
5. Decide the routing-maturation branch by its measurement contract. No hour-end route regret enters the paper.
6. Rebuild G and H from the lock and delete every retired 27.2%, 41.3%, 70.1%, 17.9% and 30.0% headline outside explicit correction histories.

If these pass, the paper has a credible empirical contribution: the directly observed vehicle unit changes, the transition survives the clean one-vehicle unit and measured routing strata, exact transaction-state counterfactuals establish economically relevant cost-dominance states, and LP incidence shows who does not recover the cost of supplying the long-tail network. Whether that reaches JFE then turns on the within-opportunity transition test, not on prose polish.

# JFE Outline - The Making of Vehicle Currencies

Target title: **The Making of Vehicle Currencies: Evidence from DeFi**

This version keeps the paper close to JFE style: few visible section headings,
subsections only where they are likely to appear in the submitted paper, and
paragraph-level instructions recorded as comments rather than fake headings.

## Abstract

**Comment:** One paragraph, about 100-150 words. State the question, the DeFi
identification advantage, the three findings, and the finance implication. Avoid
a numbered tour of tables.

## 1. Introduction

**Comment:** Long JFE-style introduction, not subdivided in the paper. Paragraph
plan: vehicle-currency puzzle; why fiat evidence is opaque; why DeFi reveals the
route; core mechanism of liquidity and network externalities; main findings in
order; contribution; related literature; roadmap.

**Paragraph plan, not headings:**

1. Vehicle currencies are liquidity institutions: traders route through a token
   because it is the cheapest and deepest bridge.
2. Fiat markets make this hard to study: routes are hidden, transitions are rare,
   and architecture changes slowly.
3. DeFi is the laboratory: routes, intermediaries, endpoint tokens, liquidity, and
   settlement implementation are observed inside transactions.
4. Main finding 1: vehicle use is concentrated and persistent.
5. Main finding 2: stress rotates routes away from the inherited risky vehicle,
   WETH, toward safer stablecoin routes within common route opportunities.
6. Main finding 3: architecture changes route feasibility and settlement
   implementation.
7. Contribution: identify how vehicle currencies are made, why they stick, and
   what changes them.
8. Literature: vehicle/dominant currencies; liquidity and flight to safety; DeFi,
   AMMs, and stablecoins.
9. Roadmap.

## 2. Institutional Setting, Data, and Measurement

**Comment:** This section should have only a few visible subsections. It explains
the route object and data reliability, then moves detailed diagnostics to the
appendix.

### 2.1 Routed exchange in AMM markets

**Comment:** Define direct routes, indirect routes, split routes, loop routes, and
the vehicle role. Use Krugman/Somogyi language but make the DeFi object concrete.

**Figure 1 placed here.**

**Figure 1. Routed exchange and monetary roles in AMM markets.**
Panel A shows a direct route from source token \(A\) to destination token \(C\).
Panel B shows an indirect route in which token \(B\) is used as a vehicle currency
because the trade clears through \(A \rightarrow B \rightarrow C\). Panel C shows
a split route in which execution is divided across parallel paths. Panel D shows
a loop route that returns to the initial token inside the same atomic transaction.
A token is counted as a vehicle only when it is neither the source nor the
destination of the reconstructed route.

Subcaptions: **Panel A. Direct route**; **Panel B. Vehicle route**; **Panel C.
Split route**; **Panel D. Loop route**.

### 2.2 Route data, sample construction, and summary statistics

**Comment:** Combine raw swap records, transaction-hash grouping, log-index
ordering, route reconstruction, repricing, filters, summary statistics, and
estimation-sample definitions. Table 1 should do the normal JFE "summary
statistics" job; do not bury the basic sample facts in an appendix.

**Table 1 placed here.**

**Table 1. Sample coverage and summary statistics.**
The table reports sample coverage and summary statistics for the reconstructed
route network. Panel A reports the sample period, venues, swap legs, reconstructed
routes, source-destination pairs, tokens, and repriced USD route volume. Panel B
reports route composition, including direct, indirect, split, loop, and pure
vehicle routes. Panel C reports summary statistics for the main route-role
variables: vehicle share, route betweenness, endpoint share, route cost, and
gross-transfer incidence. Panel D reports the coefficient-bearing samples used in
the stress-rotation, depeg, architecture, and return tests. Separating the
measurement network from the estimation samples makes clear which observations
define the route network and which observations identify regression estimates.

### 2.3 Measuring vehicle use and settlement roles

**Comment:** Define vehicle share, route betweenness, endpoint share,
route-endpoint flow, and gross-transfer incidence in prose. Do not make each one a
subsection.

**Figure 2 placed here.**

**Figure 2. Vehicle-currency shares in routed exchange.**
The figure plots weekly shares of reconstructed route intermediation for WETH,
USDC, USDT, and other major route tokens. Vehicle share is the fraction of indirect
routes in which the token appears as a pure intermediate. The figure shows the
inherited WETH vehicle role, the growth of stablecoin intermediation, and the
distinction between gradual changes in route liquidity and sharp movements around
stress episodes.

Subcaptions: **Panel A. WETH and stablecoin vehicle shares**; **Panel B. Vehicle
share by token group**; **Panel C. Route betweenness by token group**; **Panel D.
Vehicle concentration over time**.

## 3. Framework

**Comment:** Visible section should be short and mechanism-led. If the formal
model is kept, this is where it belongs. Otherwise write it as a disciplined
conceptual framework with propositions. Do not create many subsections.

### 3.1 Liquidity, network externalities, and route choice

**Comment:** One visible subsection can cover the route-cost logic, thick-market
externalities, switching costs, and why vehicle use is persistent.

### 3.2 Predictions

**Comment:** Use propositions, not H1/H1a/H2 labels.

**Comment:** No table is necessary here unless the propositions are formal enough
that a compact proposition-to-test map helps. JFE papers usually let the model or
framework carry this in text rather than using a mechanical "hypothesis table."

## 4. Formation and Stickiness of the Vehicle Role

**Comment:** This is the first empirical section. It should establish "making" and
"stickiness" before stress events. Keep only two visible subsections if possible.

### 4.1 Vehicle concentration and persistence

**Comment:** Show that WETH is the inherited Ethereum vehicle and that vehicle
use is persistent.

**Table 2 placed here.**

**Table 2. Concentration and persistence of vehicle-currency use.**
The table reports concentration and persistence statistics for token vehicle shares
in the reconstructed route network. Vehicle share is measured from pure-intermediate
route use. Concentration statistics compare vehicle intermediation with endpoint
use, and persistence statistics measure how strongly a token's vehicle role carries
forward across weeks. The estimates show whether vehicle dominance is a sticky
route-liquidity object rather than a transient volume ranking.

### 4.2 Liquidity supplied against vehicle assets

**Comment:** This is the key foundation Kathy's liquidity-provision framing needs:
liquidity is organized around the vehicle.

**Figure 3 placed here.**

**Figure 3. Pair liquidity supplied against vehicle assets.**
The figure reports liquidity depth by base asset for major route tokens. Liquidity
is assigned to the asset against which other tokens are paired. The figure shows
whether WETH and major stablecoins attract disproportionate paired liquidity, the
liquidity foundation that makes indirect vehicle routes cheaper than thin direct
routes.

Subcaptions: **Panel A. Pair liquidity by base asset**; **Panel B. Share of token
pairs linked to WETH or stablecoins**; **Panel C. Direct-route depth versus
vehicle-route depth**; **Panel D. Change in paired liquidity over time**.

**Table 3 placed here.**

**Table 3. Direct routes and vehicle-route execution advantage.**
The table compares direct execution with the best available vehicle route for
source-destination pairs in the reconstructed network. For each pair, the table
reports direct-route availability, direct-route depth, vehicle-route depth, and the
output advantage of routing through WETH or a stablecoin vehicle. The estimates
quantify the economic value of the vehicle role before turning to stress-driven
rotation.

## 5. Stress-State Vehicle Rotation

**Comment:** This is the central identification section. Keep the structure tight:
dose response, common support, route costs/counterfactual, recovery. The hourly
event anatomy can be a figure or appendix material unless it is crucial.

### 5.1 Stress severity and WETH rotation

**Table 4 placed here.**

**Table 4. Daily vehicle-rotation dose response.**
The table reports daily fixed-effects estimates of vehicle rotation as downside
stress increases. The outcome is WETH's route-betweenness or vehicle-share gap
relative to the stablecoin layer. Stress is measured by downside ETH returns, with
days grouped by crash severity and with a continuous severity specification. WBTC
is included as a placebo vehicle. The estimates test whether the risky inherited
vehicle loses route share when market stress rises.

**Figure 4 placed here.**

**Figure 4. Event-time WETH vehicle share around stress episodes.**
The figure plots WETH vehicle share around pre-specified downside stress episodes.
Vehicle share is normalized to the pre-event window within each episode. The
event-time path shows when route rotation occurs, whether it reverses after stress
subsides, and whether the incumbent vehicle returns to its baseline role.

Subcaptions: **Panel A. Average event-time path**; **Panel B. Episode-specific
paths**; **Panel C. Recovery after stress trough**; **Panel D. Risk-on placebo
episodes**.

### 5.2 Common-support route opportunities

**Table 5 placed here.**

**Table 5. Common-support WETH route rotation.**
The table estimates WETH route-share changes within source-destination
pair-episodes that used both WETH and at least one non-WETH intermediary before
the stress anchor. The outcome is WETH's hourly intermediary share minus the
pair-episode's pre-anchor WETH share. Pair-by-episode and relative-hour fixed
effects absorb baseline route composition and common event timing. The coefficient
measures whether WETH loses share relative to observed substitute intermediaries
inside the same route opportunity set.

### 5.3 Route costs and the road not taken

**Table 6 placed here.**

**Table 6. Executed route costs and WETH route choice.**
The table compares WETH and non-WETH intermediaries in source-destination-hour
cells where both route categories are executed on Uniswap V3. Route cost includes
pool fees and realized within-swap price impact across the executed legs. The
estimates test whether WETH loses route share under stress after controlling for
observed route costs, route length, source-destination pair, and time.

**Table 7 placed here.**

**Table 7. Road-not-taken route costs under stress.**
The table prices the executed route against the best observed alternative route
for the same source-destination pair, using validated V3 quote reconstruction and
filters for mechanical pricing pathologies. The premium is the output lost or
gained by the route used relative to the route not taken. The table reports route
examples, quoter validation, fee and price-impact components, and
episode-minus-calm premiums. It quantifies the execution-cost consequence of
vehicle rotation under stress.

### 5.4 Recovery after stress

**Table 8 placed here.**

**Table 8. Recovery of the inherited vehicle role after stress.**
The table estimates the persistence and recovery of WETH vehicle share after
downside stress episodes. Recovery is measured as the share of the pre-event WETH
vehicle role regained by fixed post-event horizons and as the estimated half-life
of the stress-induced displacement. The estimates distinguish temporary stress
rotation from permanent tipping away from the incumbent vehicle.

## 6. Reserve Credibility and Settlement Endpoint Flight

**Comment:** Keep this as one compact section. It supports the safe-settlement
side of the story but should not crowd out the vehicle-currency spine.

### 6.1 USDC depeg and endpoint flow

**Figure 5 placed here.**

**Figure 5. The USDC depeg and route-endpoint flight.**
The figure plots the March 2023 USDC depeg and hourly route-endpoint flow into or
out of USDC. The price of USDC is recovered from Uniswap V3 USDC/USDT pool ticks,
with USDT as the numeraire. Bars show net route-endpoint flow into USDC from other
major stablecoins. Negative bars indicate flight from the impaired settlement token
during the widening phase; positive bars indicate reflow as the peg recovers.

Subcaptions: **Panel A. USDC price around the SVB shock**; **Panel B. Hourly net
endpoint flow into USDC**; **Panel C. Cumulative route-endpoint pressure**; **Panel
D. Placebo-window comparison**.

### 6.2 Persistence and substitution

**Table 9 placed here.**

**Table 9. Persistence of route-endpoint pressure during the USDC depeg.**
The table reports cumulative route-endpoint outflow from USDC during the March
2023 depeg. Cumulative pressure is the signed net stable-to-stable route flow out
of USDC and into substitute stablecoins. The measure records endpoint pressure
generated by observed routes, not wallet-level holdings or redemptions. Share of
peak reports the remaining pressure at each checkpoint relative to the maximum
cumulative outflow in the event window.

**Table 10 placed here.**

**Table 10. Settlement substitution during stablecoin depegs.**
The table reports positive net route-endpoint outflow from impaired stablecoins
during depeg widening phases. For each episode, it reports the total outflow, the
largest recipient's share, and the effective number of substitute stablecoins. The
table tests whether settlement flight tips mechanically to a single surviving
stablecoin or disperses across several substitutes with immediate clearing capacity.

## 7. Architecture and Settlement Implementation

**Comment:** Architecture is part of the vehicle-currency story, but causal claims
must stay tight. V3 route-feasibility evidence belongs here if built; V4 receipt
evidence is already a strong first stage.

### 7.1 Architecture and route feasibility

**Figure 6 placed here if the V3 analysis is built.**

**Figure 6. Vehicle routes around the introduction of concentrated liquidity.**
The figure plots route shares, direct-route availability, and paired liquidity
around the introduction of Uniswap V3 concentrated liquidity. The event window is
centered on V3 launch. The figure tests whether a change in market architecture
alters reliance on vehicle routes by changing pairwise depth and the cost of direct
exchange.

Subcaptions: **Panel A. Vehicle share around V3 launch**; **Panel B. Direct-route
availability**; **Panel C. Pair liquidity concentration**; **Panel D. Direct-route
versus vehicle-route cost**.

### 7.2 V4 settlement implementation

**Table 11 placed here.**

**Table 11. V4 matched settlement-implementation first stage.**
The table matches coherent multi-hop Uniswap V3 and V4 routes by endpoint pair,
week, and intermediate token. It reports the gross-exposure nettable share and
whether the intermediate token emits a matching ERC-20 transfer in the transaction
receipt. Holding the route unit fixed, V4 sharply lowers gross intermediate-token
movement, showing that protocol architecture can separate route use from physical
settlement.

**Table 12 placed here.**

**Table 12. Settlement netting on Uniswap V4.**
The table reports gross-transfer and netted-settlement shares for clean coherent V4
routes in which the named token is a pure intermediate. A route is physically
settled when the intermediate token emits an ERC-20 transfer in the transaction
receipt and internally netted when no such transfer appears. The table reports
token-level netted shares, adoption-time patterns, and stress diagnostics. The
stress estimates are descriptive; the identified architecture result is the
matched V3/V4 receipt wedge.

## 8. Pricing Implications and Conclusion

**Comment:** JFE needs the finance payoff, but this should be a payoff, not a
second asset-pricing paper.

### 8.1 Convenience-yield implication

**Table 13 placed here.**

**Table 13. Vehicle dominance and state-dependent convenience yields.**
The table sorts tokens by vehicle and route-dominance measures and reports
subsequent returns by market state. High-dominance tokens are expected to earn
lower subsequent returns when their route-liquidity services are most valuable.
The table reports conditional long-short spreads across boom and bust states.
Unconditional factor-pricing tests are reported in the appendix as diagnostics.

### 8.2 Conclusion

**Comment:** Short. No new results. Return to the title: how a vehicle currency is
made, why it sticks, and what changes it.

## References

**Comment:** References after the conclusion and before the appendix. Keep the
JFE-style integrated literature in the introduction, but include the full reference
list here.

## Appendix

**Comment:** This appendix is part of the paper file. Formal proofs, essential
derivations, and compact robustness that a reader needs to trust the paper belong
here. JFE submissions can also include an online appendix, but for initial
submission the journal says it should be attached to the end of the main manuscript
file; after acceptance, internet appendices are submitted separately and included
with the article in ScienceDirect.

### Appendix A. Proofs and framework details

**Comment:** Put formal proofs here if they are not short enough for Section 3.
If the framework is mostly conceptual, this appendix can contain derivations of
route-choice comparative statics and settlement-netting identities.

### Appendix B. Data construction and route reconstruction

**Table B1. Raw swap coverage by venue and protocol version.**
The table reports raw swap coverage by DEX, protocol version, sample start, sample
end, number of transactions, number of swap legs, and repriced USD volume. Coverage
is reported before and after artifact filters.

**Table B2. Route reconstruction validation.**
The table reports transaction-level conservation checks, route-component recovery
rates, and validation against known Uniswap V3 router paths. Validation statistics
are reported separately for direct, indirect, split, and loop routes.

**Table B3. Stablecoin repricing and artifact-filter sensitivity.**
The table reports route-volume and route-count coverage under alternative repricing
and artifact-filter rules. The main estimates use the baseline stablecoin-anchored
repricing and artifact filters.

### Appendix C. Additional measurement diagnostics

**Figure C1. Venue composition of the reconstructed route network.**
The figure plots weekly reconstructed route volume by DEX and protocol version.
Shares sum to one inside the reconstructed sample and do not represent total DEX
market size.

**Figure C2. Concentration of vehicle, endpoint, and volume-share measures.**
The figure plots inverse Herfindahl indexes and top-token shares for route vehicle
use, endpoint use, and total volume share.

**Figure C3. Lead-lag cross-autocorrelation of route-role measures.**
The figure reports cross-autocorrelations among vehicle share, endpoint share,
volume share, and route betweenness over alternative lag windows.

### Appendix D. Stress-rotation robustness

**Table D1. WETH route rotation under alternative crash thresholds.**
The table estimates WETH vehicle-rotation regressions using alternative daily ETH
drawdown thresholds. Each row reports the WETH interaction coefficient under the
same fixed-effects structure as the main dose-response design.

**Table D2. Episode-level vehicle-rotation estimates.**
The table reports the WETH route-rotation coefficient separately for each stress
episode, with event anchors, observation counts, and inference.

**Table D3. Vehicle-rotation placebo tests.**
The table reports placebo estimates for WBTC, non-vehicle risky tokens, risk-on
volatility episodes, and shuffled event windows.

**Table D4. Vehicle rotation under external stress measures.**
The table replaces ETH downside returns with broad crypto-market downside returns,
the S&P cryptocurrency index, and equity-market stress measures.

### Appendix E. Counterfactual route and quoter validation

**Table E1. Quoter validation against executed swaps.**
The table compares reconstructed V3 quote output with realized executed swaps for
the pools used in the counterfactual analysis. It reports the fraction of swaps
reproduced within tolerance, median absolute error, and tail errors.

**Table E2. Road-not-taken counterfactual under pricing filters.**
The table re-estimates road-not-taken premiums under route-mid parity,
direct-route price-impact, and raw-premium filters.

**Table E3. Representative road-not-taken route examples.**
The table reports selected source-destination pairs, executed routes, alternative
routes, notional sizes, fee components, price-impact components, and output
premiums.

### Appendix F. USDC depeg and stablecoin substitution

**Table F1. Placebo-window distribution for USDC endpoint flow.**
The table compares depeg-window route-endpoint flow with contiguous placebo windows
from normal periods, preserving autocorrelation in hourly flows.

**Table F2. USDC supply changes around the SVB depeg.**
The table reports changes in USDC supply around the depeg window and subsequent
recovery period. Supply changes are used as external corroboration, not as the
identified route-flow outcome.

**Table F3. Stablecoin endpoint substitution in the Terra/UST depeg.**
The table repeats the settlement-substitution analysis for the Terra/UST depeg and
compares the dispersion of substitute flows with the USDC/SVB episode.

### Appendix G. Architecture and V4 diagnostics

**Table G1. Construction of matched V3 and V4 route-unit cells.**
The table reports the number of eligible endpoint-pair-week-intermediate cells,
minimum route-count requirements, and matched-cell attrition.

**Table G2. V4 route-composition diagnostics.**
The table reports route-length, intermediary-token, stablecoin-use, and WETH-use
diagnostics in matched V3 and V4 cells.

**Table G3. Receipt-level settlement audit.**
The table reports ERC-20 transfer incidence by intermediate token, protocol
version, and route type, based on transaction receipt parsing.

### Supplementary Material / Internet Appendix

**Comment:** This is for bulky material that supports the paper but should not be
needed to understand it: long alternative-filter batteries, route-level audit
lists, extra venue-by-day plots, all placebo variants, code/data manifests, and
large tables that would distract from the main paper. For initial submission, this
can still be appended to the manuscript PDF if submitted as an online appendix;
the conceptual distinction is that it is not part of the journal article text.

### Supplement S1. Determinants and return diagnostics

**Table S1. Cross-sectional determinants of route dominance.**
The table reports weekly token-level regressions of route-dominance measures on
token characteristics, liquidity, safety proxies, and market-state interactions.

**Table S2. Return sorts by alternative dominance measures.**
The table reports long-short return spreads using volume share, route betweenness,
vehicle share, endpoint share, and eigenvector centrality.

**Table S3. Unconditional factor-pricing diagnostics.**
The table reports two-pass factor-pricing estimates for dominance-spread factors.
These diagnostics test whether the conditional convenience-yield result appears as
an unconditional priced factor.

## Potential Coauthor Note: Olga Klein

**Comment:** Kathy's "Olga from Warwick" is almost certainly Dr Olga Klein at
Warwick Business School. She is an Associate Professor of Finance and a Gillmore
Centre for Financial Technology research fellow. Her work is directly relevant:
market microstructure, liquidity, high-frequency trading, fintech, decentralized
finance, DEX liquidity, and automated market making.

Relevant publications and working papers to read/cite:

- Caparros, Chaudhary, and Klein, "Blockchain scaling and liquidity concentration
  on decentralized exchanges." This is very relevant to our architecture/liquidity
  section because it uses scaling solutions as instruments for lower LP
  repositioning costs and shows effects on liquidity concentration and slippage.
- Klein, Kozhan, Viswanath-Natraj, and Wang, "Informed Liquidity Provision on
  Decentralized Exchanges." Very relevant to LP behavior, price discovery, and
  liquidity updates around ETH-USDC.
- Klein and Shiyun (2021), "Commonality in intraday liquidity and multilateral
  trading facilities." Relevant to our commonality/liquidity-network framing.
- Klein (2020), "Trading aggressiveness and market efficiency." Relevant to
  crowding, price efficiency, and trading intensity.
- Klein, Maug, and Schneider (2017), "Trading strategies of corporate insiders."
  Less directly DeFi-related, but relevant to liquidity-sensitive trading behavior.

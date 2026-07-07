# JFE Outline - The Making of Vehicle Currencies

Target title: **The Making of Vehicle Currencies: Evidence from DeFi**

This version incorporates the independent JFE-lens review: the paper should use
Olga Klein's work to sharpen one LP mechanism block, not to add a second
microstructure paper. The main text should have roughly 8-10 core displays. USDC,
pricing, long validations, wallet-sophistication splits, cross-chain scaling, and
full commonality batteries move to the appendix or supplementary material unless
one becomes essential.

## Abstract

**Comment:** One paragraph, 100-150 words. State the question, the DeFi
identification advantage, the liquidity-provision mechanism, the stress-rotation
result, the architecture result, and the broader lesson. No table-number tour.

## 1. Introduction

**Comment:** No visible subsections. Paragraph plan only:

1. Vehicle currencies are liquidity institutions: traders route through the asset
   that gives the cheapest and deepest bridge.
2. Fiat markets hide the route and rarely reveal clean changes in vehicle status.
3. DeFi records routes, liquidity, endpoint tokens, and settlement implementation.
4. Vehicle status is made by liquidity provision: liquidity is supplied against
   candidate vehicle assets, and active LP repositioning makes some routes cheap.
5. Main result 1: vehicle use is concentrated and persistent.
6. Main result 2: liquidity-route feedback is bidirectional: LP liquidity predicts future vehicle use, and vehicle use predicts future LP liquidity.
7. Main result 3: vehicle risk and credibility shocks rotate routing within common route opportunities.
8. Main result 4: market- and settlement-architecture changes alter vehicle feasibility and LP incentives.
9. Contribution and literature: vehicle/dominant currencies, liquidity provision
   and commonality, DeFi/AMMs/stablecoins.
10. Roadmap.

## 2. Institutional Setting, Data, and Measurement

**Comment:** Explain the route object and data reliability, then move the reader
quickly to the economic mechanism.

### 2.1 Routed exchange in AMM markets

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

### 2.2 Route data and summary statistics

**Table 1 placed here.**

**Table 1. Sample coverage and summary statistics.**
The table reports sample coverage and summary statistics for the reconstructed
route network. Panel A reports the sample period, venues, swap legs, reconstructed
routes, source-destination pairs, tokens, and repriced USD route volume. Panel B
reports route composition, including direct, indirect, split, loop, and pure
vehicle routes. Panel C reports summary statistics for the main route-role and
liquidity-provision variables: vehicle share, route betweenness, endpoint share,
active liquidity near the current price, LP repositioning intensity, route cost,
and gross-transfer incidence. Panel D reports the coefficient-bearing samples used
in the liquidity-provision, stress-rotation, architecture, and return tests.

### 2.3 Measuring vehicle use and liquidity provision

**Comment:** Define vehicle share, route betweenness, active liquidity near the
current price, LP repositioning intensity, direct-route cost, vehicle-route cost,
endpoint flow, and gross-transfer incidence in prose. Do not make each measure a
subsection.

## 3. Framework

**Comment:** Short mechanism section before tests. No long hypothesis apparatus.

### 3.1 Liquidity, network externalities, and route choice

**Comment:** A router chooses the path with the highest output net of fees and
price impact. LPs choose where and how tightly to provide liquidity. A vehicle
currency emerges when liquidity supplied against it lowers future route costs,
which attracts more route demand and reinforces the liquidity base.

### 3.2 Predictions

**Comment:** State in prose or compact propositions:

1. Vehicle use and vehicle-linked liquidity are mutually persistent.
2. Vehicle-linked liquidity predicts future vehicle use, and vehicle use predicts future vehicle-linked liquidity.
3. Downside stress reduces use of a risky incumbent vehicle relative to safer
   substitutes within common route opportunities.
4. Architecture changes can alter route feasibility and LP supply incentives.

## 4. Liquidity Provision and Vehicle-Currency Formation

**Comment:** This is the Olga/Kathy mechanism block. Keep it to one figure and two
tables in the main text. Move informed-LP decompositions, wallet sophistication,
cross-chain scaling, and full commonality batteries to appendix/supplement.

### 4.1 Vehicle concentration and paired liquidity

**Figure 2 placed here.**

**Figure 2. Vehicle-currency shares and paired liquidity.**
Panel A plots weekly shares of reconstructed route intermediation for WETH, USDC,
USDT, and other major route tokens. Panel B plots active liquidity supplied in
pools linked to the same vehicle assets. Panel C reports liquidity concentration
near the current price, scaled by total value locked. Panel D reports the
concentration of vehicle use relative to endpoint use. The figure shows whether
vehicle status is matched by liquidity supplied against the candidate vehicle
asset.

Subcaptions: **Panel A. Vehicle shares**; **Panel B. Paired liquidity by vehicle
asset**; **Panel C. Near-price liquidity concentration**; **Panel D. Vehicle-use
concentration**.

### 4.2 LP repositioning and future vehicle use

**Table 2 placed here.**

**Table 2. LP repositioning and future vehicle share.**
The table relates liquidity supplied near the current price to future vehicle use.
The unit is pool-hour, pool-day, or vehicle-day depending on data availability.
Vehicle-linked pools are pairs in which one side is WETH, USDC, USDT, or another
major route vehicle. Repositioning intensity is measured from mint and burn events,
and near-price liquidity is measured within fixed bands around the current price.
The outcome is future vehicle share, route betweenness, or vehicle-route cost. The
table tests whether vehicle liquidity is actively made by LP allocation rather than
only observed ex post in trader routing.

**Table 3 placed here.**

**Table 3. Direct routes, vehicle routes, and trade-size heterogeneity.**
The table compares direct execution with the best available vehicle route for
source-destination pairs in the reconstructed network. For each pair and trade-size
bucket, it reports direct-route availability, direct-route depth, vehicle-route
depth, and the output advantage of routing through WETH or a stablecoin vehicle.
Uniswap V2 and SushiSwap V2 routes are quoted from constant-product reserves, and
Uniswap V3 routes are quoted from exact tick-net liquidity reconstructed from raw
mints, burns, and swap-state cutoffs. The estimates quantify when the vehicle
route is economically valuable and whether that value comes from lower common-support
costs, availability when no direct route exists, or upper-tail protection when
direct liquidity is thin.

## 5. Stress-State Vehicle Rotation

**Comment:** This is the central identification section and should arrive quickly.
Keep the strongest stress/common-support/road-not-taken evidence in main text.

### 5.1 Stress severity and WETH rotation

**Table 4 placed here.**

**Table 4. Daily vehicle-rotation dose response.**
The table reports daily fixed-effects estimates of vehicle rotation as downside
stress increases. The outcome is WETH's route-betweenness or vehicle-share gap
relative to the stablecoin layer. Stress is measured by downside ETH returns, with
days grouped by crash severity and with a continuous severity specification. WBTC
is included as a placebo vehicle. The estimates test whether the risky inherited
vehicle loses route share when market stress rises.

**Figure 3 placed here.**

**Figure 3. Event-time WETH vehicle share around stress episodes.**
The figure plots WETH vehicle share around pre-specified downside stress episodes.
Vehicle share is normalized to the pre-event window within each episode. The
event-time path shows when route rotation occurs and whether the inherited vehicle
returns to its baseline role after stress subsides.

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

**Table 6. Route costs and road-not-taken validation.**
The table compares executed WETH and non-WETH routes with the best observed or
quoted alternative route for the same source-destination pair. It reports route
fees, price-impact components, quoter validation, trade-size buckets, and
episode-minus-calm route-cost premiums. The table tests whether the stress-state
route rotation is an economically meaningful change in execution costs rather than
a composition artifact.

## 6. Architecture and Vehicle Feasibility

**Comment:** Architecture is kept because it is central to "what changes vehicle
currency." USDC depeg and broad pricing implications move to appendix/supplement
unless they become necessary for the paper's final contribution.

### 6.1 Direct-market deepening and route feasibility

**Figure 4 placed here if built.**

**Figure 4. Vehicle routes around a direct-market-deepening architecture change.**
The figure plots route shares, direct-route availability, and paired liquidity around an architecture change that deepens pairwise direct markets. The empirical event window uses the concentrated-liquidity launch as the test bed. The figure tests whether market architecture alters reliance on vehicle routes by changing pairwise depth and the cost of direct exchange.

Subcaptions: **Panel A. Vehicle share around architecture change**; **Panel B. Direct-route availability**; **Panel C. Pair liquidity concentration**; **Panel D. Direct-route versus vehicle-route cost**.

### 6.2 Settlement netting and LP supply

**Table 7 placed here.**

**Table 7. Settlement netting, transfer incidence, and LP response.**
The table first matches coherent multi-hop routes across settlement architectures by endpoint pair, week, and intermediate token, then reports whether the transaction receipt contains a physical transfer log for the intermediate token. The transfer-log result is a measurement step supporting the behavioral proposition. The behavioral test asks whether vehicles with greater netting exposure receive stronger post-launch LP liquidity supply. The current evidence is suggestive: netting exposure predicts higher log LP liquidity, while LP concentration share moves in the opposite direction.

## 7. Discussion and Conclusion

**Comment:** Short. State what DeFi teaches about vehicle currencies: they are
liquidity institutions, they persist through LP-supplied route depth and network
externalities, they rotate under stress, and architecture can change the mapping
from route use to settlement movement. Pricing can be mentioned only if the result
is clean enough for a one-paragraph payoff.

## References

**Comment:** References after the conclusion and before the appendix.

## Appendix

**Comment:** Part of the paper file. Formal proofs, essential derivations, compact
robustness, and trust-critical construction details belong here.

### Appendix A. Proofs and framework details

### Appendix B. Data construction and route reconstruction

**Table B1. Raw swap coverage by venue and protocol version.**
The table reports raw swap coverage by DEX, protocol version, sample start, sample
end, number of transactions, number of swap legs, and repriced USD volume.

**Table B2. Route reconstruction validation.**
The table reports transaction-level conservation checks, route-component recovery
rates, and validation against known Uniswap V3 router paths.

### Appendix C. Liquidity-provision mechanism details

**Table C1. LP repositioning and liquidity concentration.**
The table reports the relation between mint/burn intensity, range width,
near-price liquidity concentration, and vehicle-linked pool status.

**Table C2. Liquidity commonality across vehicle-linked pools.**
The table estimates whether pools linked by the same vehicle token share a common
liquidity factor, and whether that commonality strengthens in down markets.

### Appendix D. Stress-rotation robustness

**Table D1. WETH route rotation under alternative crash thresholds.**

**Table D2. Episode-level vehicle-rotation estimates.**

**Table D3. Vehicle-rotation placebo tests.**

**Table D4. Vehicle rotation under external stress measures.**

### Appendix E. Counterfactual route and quoter validation

**Table E1. Quoter validation against executed swaps.**

**Table E2. Road-not-taken counterfactual under pricing filters.**

**Table E3. Representative road-not-taken route examples.**

### Appendix F. Stablecoin endpoint shocks

**Figure F1. The USDC depeg and route-endpoint flight.**
The figure plots the March 2023 USDC depeg and hourly route-endpoint flow into or
out of USDC.

**Table F1. Persistence and substitution during stablecoin depegs.**
The table reports cumulative route-endpoint pressure and substitute dispersion for
stablecoin depeg episodes.

### Appendix G. V4 diagnostics

**Table G1. Construction of matched V3 and V4 route-unit cells.**

**Table G2. Receipt-level settlement audit.**

## Supplementary Material / Internet Appendix

**Comment:** Bulky supporting material that should not be needed to understand the
paper: large alternative-filter batteries, all route-level examples, venue-by-day
plots, wallet-sophistication splits, public-versus-private LP information splits,
cross-chain scaling quasi-experiment variants, full determinant batteries, and
unconditional factor-pricing diagnostics.

## Potential Coauthor Note: Olga Klein

**Comment:** Kathy's "Olga from Warwick" is almost certainly Dr Olga Klein at
Warwick Business School. Her relevant work points to one main addition: show that
vehicle currencies are made by LP-side liquidity allocation and by architecture that changes the payoff to supporting routed demand.

Relevant checked papers:

- Caparros, Chaudhary, and Klein, "Blockchain Scaling and Liquidity Concentration
  on Decentralized Exchanges."
- Klein, Kozhan, Viswanath-Natraj, and Wang, "Informed Liquidity Provision on
  Decentralized Exchanges."
- Klein and Song, "Commonality in Intraday Liquidity and Multilateral Trading
  Facilities: Evidence from Chi-X Europe."

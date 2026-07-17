# JFE Outline - The Making of Vehicle Currencies

Target title: **The Making of Vehicle Currencies: Evidence from DeFi**

This outline is aligned to the current model-evidence packet rather than the build
order of the experiments. The paper should lead with the economic question, then
use DeFi routes as the measurement laboratory. The main text should have roughly
8-10 core displays. The table order should follow the evidence map: measurement
and scope first, then route availability/thin-direct protection, liquidity-route
persistence, stress rotation, architecture, settlement netting, and common
liquidity. WETH, stablecoins, V3, and V4 are empirical test beds, not the
propositions themselves.

## Evidence Spine

**Comment:** This is the paper logic before prose. Each research question has one
paper-facing answer and one main display. Robustness tables can be selected later.

| Research question | Paper-facing mechanism | Main evidence | Placement |
| --- | --- | --- | --- |
| RQ1. When does an asset become a vehicle? | Direct-market incompleteness and thin-direct-route protection. | DirectCostAdvantage, vehicle-route availability, and vehicle-route depth predict actual and future vehicle share. | Section 4, Table 3 |
| RQ2. How does liquidity provision make a vehicle? | Vehicle-linked liquidity and vehicle use are mutually persistent. | LP concentration predicts future vehicle share; lagged vehicle share predicts future LP concentration and linked liquidity. | Section 5, Table 4 |
| RQ3. Why does vehicle status persist or get displaced? | Persistence is strong, but sufficiently large challenger cost edges displace incumbents. | Lagged vehicle share and challenger-edge bins predict incumbent share losses. | Section 5, Table 4 plus appendix |
| RQ4. When does vehicle status switch under stress? | Risk or credibility shocks rotate route intermediation on impact inside common route opportunities. | WETH-minus-stable vehicle share falls on stress event days, with threshold and overlap sensitivity. | Section 6, Table 5 |
| RQ5. How does market architecture change vehicle formation? | Direct-market-deepening architecture expands pairwise route opportunity and reduces no-direct dependence on vehicles. | Post-V3 no-direct WETH-available cases fall in balanced endpoint-pair panels. | Section 7, Table 6 |
| RQ6. How does settlement architecture change vehicle use? | Settlement netting separates route vehicle use from physical intermediary-token movement. | V4 lowers intermediary-token transfer incidence while matched V4 route use persists. | Section 8, Table 7 |
| RQ7. Does vehicle status create common liquidity? | Pools linked to the same vehicle share a vehicle-specific liquidity factor beyond market liquidity. | Leave-one-out vehicle liquidity factor predicts pool liquidity changes. | Section 9 or Appendix C, Table 8 |

## Abstract

**Comment:** One paragraph, 100-150 words. State the question, the transparent
DeFi route laboratory, the main measurement distinction, and the four results:
route feasibility/thin-direct protection, liquidity-route persistence, stress
rotation, and architecture/settlement design. Do not tour table numbers.

## 1. Introduction

**Comment:** No visible subsections. Paragraph plan only.

1. Vehicle currencies are routing infrastructure, not merely popular assets or
   endpoints.
2. Traditional markets hide route-level intermediation; DeFi records input,
   output, intermediate tokens, liquidity, and settlement implementation.
3. Define the empirical object: vehicle use means intermediate-token use in
   indirect routes; all-route shares and quote coverage are scope diagnostics.
4. State P1: candidate vehicles expand the feasible execution set when direct
   markets are missing or thin; conditional cost advantage is a separate margin.
5. State P2: vehicle-linked liquidity and vehicle use are persistent together.
6. State P3: risk/credibility stress rotates route intermediation on impact
   within common route opportunities.
7. State P4a/P4b: architecture changes both route feasibility and the mapping
   between route intermediation and physical settlement movement.
8. Explain contribution to vehicle-currency, liquidity/intermediation, and market
   design literatures.
9. Roadmap.

## 2. Institutional Setting, Data, and Measurement

**Comment:** The reader must understand what a route is, what counts as a
vehicle, and what the empirical scope is before seeing regressions.

### 2.1 Routed exchange in AMM markets

**Figure 1 placed here.**

**Figure 1. Routed exchange and vehicle-currency measurement.**
Panel A shows a direct route from input token \(A\) to output token \(C\).
Panel B shows an indirect route in which token \(B\) is used as the vehicle
because execution clears through \(A \rightarrow B \rightarrow C\). Panel C shows
a split route in which execution is divided across multiple paths. Panel D shows
a loop route that returns to the initial token inside the same atomic transaction.
A token is counted as a vehicle only when it is an intermediate token, not the
input or output endpoint.

Subcaptions: **Panel A. Direct route**; **Panel B. Vehicle route**; **Panel C.
Split route**; **Panel D. Loop route**.

### 2.2 Sample construction and coverage

**Table 1 placed here.**

**Table 1. Sample construction and measurement scope.**
The table reports the reconstructed route sample, venue coverage, exact-quote
coverage, and the distinction between conditional vehicle share and all-route
bridge share. Panel A reports route, token, pair, and volume coverage. Panel B
reports the leading vehicle tokens under conditional BridgeShare and their
all-route scope. Panel C reports exact executable-depth quote coverage and the
materiality of venues excluded from exact quote tests. The table defines the
sample over which each empirical claim is made.

### 2.3 Vehicle-use and liquidity variables

**Table 2 placed here.**

**Table 2. Variables and empirical proxies.**
The table defines vehicle share, DirectCostAdvantage, direct-route availability,
vehicle-route availability, vehicle-linked liquidity, LP concentration, settlement
transfer incidence, and the vehicle liquidity factor. It states the unit of
observation, construction, and research question using each variable.

## 3. Framework and Testable Implications

**Comment:** Keep the model atomic. The model should discipline what the signs
mean, not become a separate theory paper.

### 3.1 Route choice and liquidity allocation

**Comment:** A trader with input token \(i\) and output token \(o\) compares a direct route
\(i\to o\) with vehicle routes \(i\to k\to o\). Costs combine fees, price impact, route
availability, and implementation/settlement cost. LPs allocate liquidity toward
pools with expected route flow and net-of-cost returns.

### 3.2 Propositions

**Proposition 1. Direct-market incompleteness and vehicle-route feasibility.**
For an endpoint pair, a candidate vehicle expands the feasible execution set when
the direct route is unavailable or thin. Conditional on both routes being
feasible, the vehicle route improves execution only when the vehicle-route cost is
below the direct-route cost.

**Empirical counterpart:** no-direct/vehicle-available cases, thin-direct cells,
vehicle-route availability, vehicle-route depth, and common-support route-cost
advantage.

**Proposition 2. Liquidity-route persistence.**
Vehicle-linked liquidity and vehicle use are jointly persistent: liquidity around
a candidate vehicle predicts future vehicle use, and current vehicle use predicts
future vehicle-linked liquidity.

**Empirical counterpart:** token-day dynamic panels with LP concentration, lagged
vehicle share, token fixed effects, date fixed effects, and date-clustered
standard errors.

**Proposition 3. Impact stress rotation.**
A risk or credibility shock to an incumbent vehicle reduces its route-intermediation
share on impact relative to safer substitutes, conditional on common route
opportunities.

**Empirical counterpart:** WETH-minus-stable vehicle share around downside stress
events, threshold/overlap sensitivity, and event-time windows.

**Proposition 4a. Direct-market-deepening architecture.**
An architecture that increases direct pairwise depth reduces reliance on vehicle
routes that exist only because the direct route is absent or thin.

**Empirical counterpart:** V3 launch-window endpoint-pair panels for direct-route
availability and no-direct WETH-available cases.

**Proposition 4b. Settlement netting.**
Settlement netting can preserve the route-pricing role of a vehicle while reducing
physical transfers of the intermediary token.

**Empirical counterpart:** matched V3/V4 route units, receipt-level intermediary
Transfer incidence, manual receipt audit, and matched-cell route-use persistence.

## 4. Direct-Market Incompleteness and Vehicle Formation

**Comment:** This section answers RQ1. The headline is not "vehicle routes are
always cheaper." The headline is feasibility and thin-direct protection, with
common-support cost advantage as one margin.

**Table 3 placed here.**

**Table 3. Vehicle formation: route economics, availability, and realized route choice.**
The dependent variables are actual vehicle share and future vehicle share. The
main regressors are DirectCostAdvantage, vehicle-route availability,
vehicle-route depth, LP concentration, and lagged vehicle share. Cells report
coefficients with p-values beneath them. The table shows whether route economics
and executable vehicle-route opportunity are associated with realized and future
vehicle use.

**Appendix companion:** route-cost decomposition into no-direct, thin-direct, and
common-support price-improvement cells; Balancer weighted-pool extension;
Curve/Fluid scope and exclusion sensitivity.

## 5. Liquidity Provision, Persistence, and Displacement

**Comment:** This section answers RQ2 and RQ3. It should be written as persistent
liquidity-route co-movement, not causal LP feedback unless an exogenous liquidity
shock is later added.

**Figure 2 placed here if included.**

**Figure 2. Vehicle shares and vehicle-linked liquidity.**
Panel A plots weekly vehicle shares for major candidate vehicle tokens. Panel B
plots vehicle-linked liquidity concentration. Panel C compares vehicle use with
endpoint use. Panel D plots the concentration of liquidity around vehicle-linked
pools. The figure motivates the dynamic panel by showing that vehicle use and
liquidity concentration move together over time.

**Table 4 placed here.**

**Table 4. Liquidity provision, persistence, and challenger displacement.**
The dependent variables are future vehicle share, future LP concentration, future
log vehicle-linked liquidity, and 30-day changes in LP concentration and linked
liquidity. The table also reports challenger route-cost edge bins and incumbent
share losses. The table tests whether vehicle use and vehicle-linked liquidity are
mutually persistent and whether sufficiently large challenger cost edges predict
incumbent displacement.

## 6. Stress-State Vehicle Rotation

**Comment:** This section answers RQ4. Use the same-day/common-support result as
the headline. Treat hourly/weekly attenuation and pre-movement honestly as
robustness and duration diagnostics.

**Table 5 placed here.**

**Table 5. Stress rotation inside common route opportunities.**
The table reports changes in WETH vehicle share, stable-vehicle share, their gap,
direct-route share, and indirect-route volume on downside stress event days. The
sample is restricted to common route opportunities where substitutes are observed.
Panel B reports event-time WETH-minus-stable gap changes, and Panel C reports
threshold and overlap sensitivity. The table tests whether stress rotates route
intermediation away from the incumbent risky vehicle and toward stable substitutes.

**Appendix companions:** hourly common-support panel, weekly common-support panel,
placebo windows, threshold definitions, and event-overlap handling.

## 7. Market Architecture and Direct-Route Opportunity

**Comment:** This section answers P4a/RQ5 narrowly. It should not overclaim a
clean causal launch effect across all V3 outcomes. The defensible result is the
decline in no-direct WETH dependence where direct-route opportunity expands.

**Table 6 placed here.**

**Table 6. Architecture and direct-route opportunity.**
The dependent variables are no-direct WETH availability and direct-route
availability by pre-V3 direct-route quartile. The regressor is the post-V3 period,
with endpoint-pair fixed effects and pair-clustered standard errors. The table
shows whether a direct-market-deepening architecture reduces dependence on vehicle
routes for endpoint pairs that previously lacked direct-route opportunity.

## 8. Settlement Architecture and Vehicle Virtualization

**Comment:** This section answers P4b/RQ6. The result is not that V4 eliminates
vehicle currencies. The result is that V4 separates route vehicle use from
physical intermediary-token movement.

**Table 7 placed here.**

**Table 7. Settlement design, physical transfer incidence, and matched-cell route use.**
Columns 1-4 compare matched V3 and V4 route units by route-size bin and report
intermediary-token transfer incidence. Columns 5-6 regress V4 route use on V3
route use in matched endpoint-vehicle-week cells. The table tests whether V4
settlement design lowers physical movement of the vehicle token while preserving
vehicle-route demand.

**Appendix companions:** receipt-parser validation, manual no-transfer audit,
route-size balance, vehicle heterogeneity, and netting-exposure LP response.

## 9. Vehicle-Linked Common Liquidity

**Comment:** This can be main text if the paper wants a stronger LP mechanism, or
appendix if the main text is already overloaded. It is useful because it makes the
liquidity institution claim more than a token-level correlation.

**Table 8 placed here or moved to Appendix C.**

**Table 8. Common liquidity across pools linked to the same vehicle.**
The dependent variable is daily pool-level log liquidity change. The regressors
are a market liquidity factor and a leave-one-out vehicle liquidity factor. The
specifications include pool-vehicle fixed effects and date-clustered standard
errors. The table tests whether pools linked to the same vehicle share a common
liquidity component beyond market-wide liquidity.

## 10. Discussion and Conclusion

**Comment:** Short. Do not add new evidence. State what the route-level DeFi
laboratory teaches about vehicle currencies generally: vehicle status is a
liquidity and routing institution; it arises from direct-market incompleteness and
thin-direct protection; it persists with liquidity concentration; it rotates under
risk/credibility stress; and architecture changes the mapping from route use to
settlement movement.

## References

**Comment:** References after the conclusion and before appendices.

## Appendix

**Comment:** Part of the manuscript file. Put formal derivations, construction
details, robustness tables, and evidence that is important but not main-spine here.

### Appendix A. Model derivations and proof details

**Table A1. Model predictions and empirical counterparts.**
This table maps each proposition to the primitive, empirical proxy, main table,
identification assumption, and bounded wording.

### Appendix B. Data construction and route reconstruction

**Table B1. Raw swap coverage by venue and protocol version.**
The table reports venue, protocol version, sample start, sample end, transactions,
swap legs, reconstructed routes, and repriced USD volume.

**Table B2. Route reconstruction validation.**
The table reports transaction-level conservation checks, route-component recovery
rates, and validation against known router paths.

### Appendix C. Liquidity-provision mechanism details

**Table C1. LP repositioning and liquidity concentration.**
The table reports the relation between mint/burn intensity, range width,
near-price liquidity concentration, and vehicle-linked pool status.

**Table C2. Vehicle-linked liquidity commonality.**
The table reports common liquidity estimates and heterogeneity across high- and
low-vehicle-use samples.

### Appendix D. Stress-rotation robustness

**Table D1. Stress event definitions and threshold sensitivity.**

**Table D2. Hourly and weekly common-support stress panels.**

**Table D3. Placebo event windows and non-overlap checks.**

### Appendix E. Route-cost and exact-quote robustness

**Table E1. Route-cost decomposition.**

**Table E2. Transaction-time quote-state robustness.**

**Table E3. Non-Uni quote coverage and exclusion sensitivity.**

### Appendix F. Architecture and settlement diagnostics

**Table F1. V3 event-time pretrends.**

**Table F2. V4 receipt-parser validation and manual no-transfer audit.**

**Table F3. V4 route-size balance and vehicle heterogeneity.**

## Supplementary Material / Internet Appendix

**Comment:** Use only for bulky machine-readable audits, full event lists, very
large robustness batteries, and code/data documentation not needed inside the
paper file.

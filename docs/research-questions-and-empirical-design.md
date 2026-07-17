# Research questions and empirical design (review draft)

**Status:** proposed design for Java's review, 17 July 2026. No empirical experiment has been run for this draft. Existing result files are not treated as evidence for these specifications.

The canonical symbols, formulas, units, and constructions are maintained in `src/ddvc/variable_registry.py` and rendered in `output/tables/variable_notation.tex` and `output/tables/variable_notation.pdf`. Any measurement approved here must be implemented through that registry before it enters an estimation script.

## RQs rather than duplicate hypotheses

Use research questions as the paper's organizing labels. Do not add a parallel set of numbered hypotheses at this stage. Each RQ below already contains:

- an empirical prediction or, where mechanisms compete, the coefficients that distinguish them;
- a primary experiment and pre-specified sample;
- the evidence required to answer the question;
- a failure condition; and
- a limit on the interpretation.

Separately numbered hypotheses would duplicate these objects and would imply a theory-first structure that the paper does not currently need. If a journal later requires hypotheses, each empirical prediction can be relabelled without changing the experiments.

## Proposed RQ set

1. **RQ1. When is an indirect route used, and which candidate is selected as the vehicle?**
2. **RQ2. How does liquidity provision support and reinforce vehicle status?**
3. **RQ3. How persistent is vehicle status, and what displaces an incumbent?**
4. **RQ4. How does execution architecture change reliance on vehicle routes?**
5. **RQ5. Does settlement netting separate economic vehicle use from physical vehicle-token transfer?**

This consolidates the previous seven-question draft. Stress rotation is a source of incumbent displacement under RQ3. Commonality in liquidity is a mechanism test under RQ2. Execution architecture and settlement architecture remain separate because they change different economic objects.

## Cross-RQ design rules

- The primary quote notional is proposed as \(q=\$10{,}000\). The exact same specifications are repeated at \(q\in\{\$1{,}000,\$100{,}000\}\); results are not pooled across notionals.
- Quote and liquidity measurements dated \(t\) predict realized route outcomes at an exact future calendar date wherever the question permits. A missing \(t+\tau\) date is not replaced by the next observed row.
- RQ2 uses \(\tau\in\{1,7,30\}\), with 90 days as a persistence check. RQ3 uses \(\tau\in\{7,30,90\}\). These choices remain review items and are not hard-coded in the notation for \(\tau\).
- USD volume shares are primary. Route-count shares, pair coverage, and all-route denominators are robustness outcomes, not interchangeable definitions.
- Every output reports the coefficient, standard error, 95% confidence interval, \(p\)-value, sample size, fixed effects, and clustering method.
- A primary prediction is supported only when the coefficient has the proposed sign, its two-sided 95% confidence interval excludes zero, and its magnitude is economically interpretable. Holm-adjusted \(p\)-values are also reported within each RQ's primary coefficient family.
- Predictive panel evidence is described as predictive. Causal wording is used only for a design that passes its stated identifying assumptions and diagnostics.
- Result artifacts have descriptive filenames, no hard-coded table or figure numbers, and no notes embedded inside tables. Paper discussion is written separately after the evidence is approved.

## Compact design crosswalk

| RQ | Primary experiment | Unit and sample | Outcome | Primary evidence |
|---|---|---|---|---|
| RQ1 | Direct-market availability and conditional candidate choice | Pair-day, then pair-candidate-day | \(\mathrm{IndirectRouteShare}_{i,o,t+1}\); \(\mathrm{VehicleShare}_{i,o,k,t+1}\) | Direct availability and depth reduce indirect reliance; candidate indirect depth raises selection; \(\Delta C^D\) lowers selection because positive values favor direct execution |
| RQ2 | Bidirectional local projections plus pool commonality | Candidate-day; pool-candidate-day | Future changes in \(\mathrm{VehicleShare}_{k,t}\), \(\mathrm{LogVehicleLiquidity}_{k,t}\), and pool TVL | \(\mathrm{LPConc}_{k,t}\) predicts future vehicle share; vehicle share predicts future liquidity; the leave-one-out vehicle factor explains pool liquidity beyond the market factor |
| RQ3 | Incumbent persistence, challenger edge, and candidate-specific stress | Pair-candidate-day; incumbent-challenger pair-day | Future vehicle share and \(\mathrm{VehicleSwitch}_{i,o,q,t,\tau}\) | Current share persists; challenger cost edge and incumbent stress raise displacement; challenger stress lowers displacement |
| RQ4 | Continuous-treatment V3 event study | Fixed pre-V3 pair-day panel | \(D_{i,o,q,t}\), \(\mathrm{DirectDepth}_{i,o,q,t}\), \(\mathrm{AnyIndirectAvailable}_{i,o,q,t}\), and \(\mathrm{IndirectRouteShare}_{i,o,t}\) | More pre-constrained pairs experience larger post-V3 route-opportunity changes; the sign of vehicle reliance identifies whether direct-market or indirect-leg deepening dominates |
| RQ5 | Receipt-audited matched V3/V4 route comparison | Route unit within settlement comparison cell | \(\mathrm{Transfer}_{r,k}\) | \(\mathrm{V4}_r\) materially lowers transfer incidence while economically classified V4 vehicle routes remain present |

## RQ1. Route reliance and vehicle selection

### Question

When does an ordered pair use any indirect route, and conditional on indirect routing, which candidate \(k\) captures the route volume? These are two different margins and must not be collapsed into a candidate-day aggregate regression.

### Experiment A: pair-level reliance on indirect routing

The unit is ordered pair-day \((i,o,t)\). The quote is measured on day \(t\), and the outcome is realized route use on day \(t+1\). The primary sample requires \(\mathrm{AnyIndirectAvailable}_{i,o,q,t}=1\) and \(\mathrm{Vol}_{i,o,t+1}>0\).

The extensive-margin specification is

\[
\mathrm{IndirectRouteShare}_{i,o,t+1}
=\alpha_{i,o}+\delta_t
+\beta_D D_{i,o,q,t}+\varepsilon_{i,o,t+1}.
\]

The direct-depth specification is estimated only where \(D_{i,o,q,t}=1\):

\[
\mathrm{IndirectRouteShare}_{i,o,t+1}
=\alpha_{i,o}+\delta_t
+\beta_Q\mathrm{DirectDepth}_{i,o,q,t}
+\varepsilon_{i,o,t+1}.
\]

\(T_{i,o,q,t}\) enters a separate nonlinear specification because it is a thresholded version of direct quote quality. It is not included as though it were an independent measure of pool liquidity.

**Empirical prediction:** \(\beta_D<0\) and \(\beta_Q<0\). Direct availability and better direct execution should reduce the realized indirect-route share. In the threshold specification, the coefficient on \(T_{i,o,q,t}\) should be positive.

Pair fixed effects absorb persistent pair characteristics. Calendar-date fixed effects absorb market-wide conditions. Standard errors are two-way clustered by ordered pair and date.

### Experiment B: candidate selection conditional on indirect routing

The unit is pair-candidate-day \((i,o,k,t)\). The sample requires \(I_{i,o,k,q,t}=1\) and \(\mathrm{IVol}_{i,o,t+1}>0\). Candidate quote depth is tested with

\[
\mathrm{VehicleShare}_{i,o,k,t+1}
=\alpha_{i,o,k}+\lambda_{i,o,t}
+\beta_I\mathrm{IndirectDepth}_{i,o,k,q,t}
+\beta_L\mathrm{LPConc}_{k,t}
+\varepsilon_{i,o,k,t+1}.
\]

On common support, \((i,o)\in\mathcal C_{k,t,q}\), relative route cost is tested in a separate specification:

\[
\mathrm{VehicleShare}_{i,o,k,t+1}
=\alpha_{i,o,k}+\lambda_{i,o,t}
+\beta_C\Delta C^D_{i,o,k,q,t}
+\beta_L\mathrm{LPConc}_{k,t}
+\varepsilon_{i,o,k,t+1}.
\]

Do not put \(\mathrm{IndirectDepth}_{i,o,k,q,t}\) and \(\Delta C^D_{i,o,k,q,t}\) in the same common-support regression with pair-date fixed effects. At fixed \((i,o,q,t)\), both are algebraic transformations of \(O^I_{i,o,k,q,t}\), so their separate coefficients are not identified.

**Empirical prediction:** \(\beta_I>0\), \(\beta_C<0\), and \(\beta_L>0\). More indirect output and more candidate-linked liquidity should raise candidate share; a positive direct cost advantage should lower it. Pair-candidate fixed effects and pair-date fixed effects make this a within-pair choice among candidates. Standard errors are two-way clustered by pair-candidate and date.

### Evidence that answers RQ1

RQ1 is answered by the joint pattern, not one omnibus coefficient:

- \(\beta_D<0\) shows that a missing direct route shifts realized volume toward indirect execution.
- \(\beta_Q<0\), or a positive coefficient on \(T_{i,o,q,t}\), shows that weak direct execution also matters on the intensive margin.
- \(\beta_I>0\) and \(\beta_C<0\) show that candidate selection responds to the candidate's executable route quality.
- \(\beta_L>0\) connects candidate selection to liquidity and is carried forward as a mechanism coefficient in RQ2.

The RQ is not supported if direct availability and quality do not predict indirect reliance, or if candidate route quality does not predict conditional candidate share after the fixed effects. This evidence is predictive route-choice evidence, not an exogenous shock to route availability.

Planned outputs: `formation_route_reliance.tex` and `formation_candidate_selection.tex`.

## RQ2. Liquidity provision and reinforcement

### Question

Does vehicle-linked liquidity predict later vehicle use, does vehicle use predict later liquidity allocation, and do pools linked to the same vehicle share a liquidity component beyond market-wide liquidity?

### Experiment A: bidirectional candidate-day local projections

The first direction is

\[
\Delta_\tau\mathrm{VehicleShare}_{k,t+\tau}
=\alpha_k+\delta_t
+\beta_\tau\mathrm{LPConc}_{k,t}
+\rho_\tau\mathrm{VehicleShare}_{k,t}
+\varepsilon_{k,t+\tau}.
\]

The reverse direction is

\[
\Delta_\tau\mathrm{LogVehicleLiquidity}_{k,t+\tau}
=\alpha_k+\delta_t
+\gamma_\tau\mathrm{VehicleShare}_{k,t}
+\phi_\tau\mathrm{LogVehicleLiquidity}_{k,t}
+\eta_{k,t+\tau}.
\]

Nested columns add, by name, \(\mathrm{DirectAvailable}_{k,t,q}\), \(\mathrm{IndirectAvailable}_{k,t,q}\), \(\mathrm{DirectDepth}_{k,t,q}\), and \(\mathrm{DirectCostAdvantage}_{k,t,q}\). Common-support controls are only added where they are defined; missing values are not coded as zero. Candidate fixed effects and date fixed effects are used. Inference uses Driscoll-Kraay standard errors with a 30-day bandwidth and a calendar-month block bootstrap as a robustness check because \(|\mathcal K|=5\) is too small for ordinary candidate clustering.

**Empirical prediction:** \(\beta_\tau>0\) and \(\gamma_\tau>0\). The first coefficient tests whether liquidity concentration precedes gains in vehicle use; the second tests whether vehicle use precedes growth in vehicle-linked liquidity. The current level of each outcome is included, so these are changes beyond simple level persistence.

The pair-candidate coefficient \(\beta_L\) from RQ1 Experiment B is the route-level allocation counterpart: it asks whether the same candidate liquidity measure predicts choice while holding pair-date conditions fixed.

### Experiment B: commonality in vehicle-linked pool liquidity

The unit is pool-candidate-day \((p,k,t)\) for \(p\in\mathcal L_{k,t}\). Observations are weighted by \(1/m_p\), so a pool containing two candidates is not counted twice at full weight. The specification is

\[
\Delta_1\ln(\mathrm{TVL}_{p,t})
=\alpha_{p,k}+\delta_{\mathrm{month}(t)}
+\theta\mathrm{VehicleLiquidityFactor}_{p,k,t}
+\psi\mathrm{MarketLiquidityFactor}_{p,t}
+\omega\bigl(
\mathrm{VehicleLiquidityFactor}_{p,k,t}
\times\mathrm{VehicleShare}_{k,t-1}
\bigr)+\varepsilon_{p,k,t}.
\]

The vehicle and market factors are leave-one-out by construction. Full date fixed effects are not included because they would absorb the market factor; calendar- month fixed effects are used instead. Standard errors are two-way clustered by pool and date. Excluding two-candidate pools is a pre-specified robustness check.

**Empirical prediction:** \(\theta>0\) and \(\omega>0\). Pools linked to the same candidate should comove beyond the leave-one-out market factor, and that commonality should be stronger when the candidate is used more heavily as a vehicle.

### Evidence that answers RQ2

RQ2 receives coherent support only if liquidity predicts future use \((\beta_\tau>0)\), use predicts future liquidity \((\gamma_\tau>0)\), and at least one within-route or commonality mechanism is present \((\beta_L>0)\), \((\theta>0)\), or \((\omega>0)\). A one-way association is reported as one-way predictability, not feedback.

These panels do not by themselves identify a causal liquidity-supply effect. A causal extension would require a separately approved, candidate-specific LP shock such as a scheduled incentive start or termination, with treatment assignment, event notation, balance, and pretrends registered before estimation. No such shock is smuggled into the current design.

Planned outputs: `liquidity_feedback.tex` and `liquidity_commonality.tex`.

## RQ3. Persistence and displacement

### Question

Does vehicle status persist after current route economics are controlled for, and when does a challenger replace the trailing incumbent? Candidate-specific adverse shocks are treated as one displacement channel, not a separate RQ.

The incumbent \(k^\star_{i,o,t}\) is selected using only the 30 calendar days ending at \(t-1\). The challenger \(h^\star_{i,o,q,t}\) is the best executable nonincumbent on day \(t\). These definitions prevent future information from entering the rankings.

### Experiment A: persistence of pair-level candidate share

On common support, estimate

\[
\mathrm{VehicleShare}_{i,o,k,t+\tau}
=\alpha_{i,o,k}+\lambda_{i,o,t}
+\rho_\tau\mathrm{VehicleShare}_{i,o,k,t}
+\beta_\tau\Delta C^D_{i,o,k,q,t}
+\gamma_\tau\mathrm{LPConc}_{k,t}
+\varepsilon_{i,o,k,t+\tau}.
\]

**Empirical prediction:** \(\rho_\tau>0\) at 7, 30, and 90 days. Persistence is stronger when \(\rho_\tau\) decays slowly and remains economically large after route cost and liquidity are controlled for. Pair-candidate and pair-date fixed effects are used, with two-way clustering by pair-candidate and date.

This is state dependence, not proof of structural switching costs. The paper must use the word persistence unless an exogenous source of historical status is added.

### Experiment B: challenger advantage and candidate stress

For cells in which both the incumbent and challenger routes execute at \(q\), estimate a linear-probability model:

\[
\begin{aligned}
\mathrm{VehicleSwitch}_{i,o,q,t,\tau}
=\;&\alpha_{i,o}+\delta_t
+\kappa_{E,\tau}\mathrm{ChallengerCostEdge}_{i,o,q,t}\\
&+\kappa_{I,\tau}\mathrm{CandidateStress}_{k^\star,t}
+\kappa_{H,\tau}\mathrm{CandidateStress}_{h^\star,t}\\
&+\kappa_{L,\tau}\bigl(
\mathrm{LPConc}_{h^\star,t}-\mathrm{LPConc}_{k^\star,t}
\bigr)
+\kappa_{V,\tau}\mathrm{VehicleShare}_{i,o,k^\star,t}
+\varepsilon_{i,o,t+\tau}.
\end{aligned}
\]

**Empirical prediction:** \(\kappa_{E,\tau}>0\), \(\kappa_{I,\tau}>0\), \(\kappa_{H,\tau}<0\), \(\kappa_{L,\tau}>0\), and \(\kappa_{V,\tau}<0\). A challenger with better quoted execution or relatively more linked liquidity should be more likely to displace the incumbent. Stress to the incumbent should raise switching; stress to the challenger should lower it. A larger current incumbent share should protect the incumbent.

The companion continuous-outcome regression replaces \(\mathrm{VehicleSwitch}_{i,o,q,t,\tau}\) with \(\Delta_\tau\mathrm{VehicleShare}_{i,o,k^\star,t+\tau}\). Its expected signs for challenger edge and incumbent stress are negative. Pair and date fixed effects are used, with two-way clustering by ordered pair and date.

The challenger edge is continuous in the primary table. A secondary piecewise- linear specification uses fixed knots at 0, 25, 50, 100, and 200 basis points. The knots are approved before estimation and are not selected from observed switching results. A placebo regresses the share change ending at \(t-1\) on day-\(t\) candidate stress; its coefficient should be zero.

### Evidence that answers RQ3

Persistence is supported by positive, slowly decaying \(\rho_\tau\). Displacement is supported by a positive challenger-edge coefficient, a positive incumbent- stress coefficient, and corresponding incumbent share losses. If lagged share does not survive current route controls, status is not empirically sticky. If challenger advantage or incumbent stress does not predict future switching, the proposed displacement channel is not supported. A nonzero placebo coefficient invalidates event-style interpretation until the pre-movement is resolved.

Planned outputs: `vehicle_persistence.tex`, `challenger_displacement.tex`, and `candidate_stress_rotation.tex`.

## RQ4. Execution architecture

### Question

Did the introduction of Uniswap V3 change route opportunity and therefore vehicle reliance, especially for pairs whose direct markets were constrained before V3?

### Experiment: continuous-treatment V3 event study

The fixed pair universe is \(\mathcal P^{\mathrm{V3}}_q\), selected only from the 180-day pre-period. Every pair is quoted each day through the event window, independent of post-V3 activity. A missing route after a successful data fetch is an unavailable route; a failed or incomplete fetch is missing data, not zero.

The continuous treatment is \(\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}\). For each outcome listed below, estimate

\[
Y_{i,o,t}
=\alpha_{i,o}+\delta_t
+\sum_{\mu\ne-1}\beta_\mu
\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}
\mathbf{1}_{\{t\text{ is in event month }\mu\}}
+\varepsilon_{i,o,t},
\]

over event months \(-12\) through \(+12\), omitting month \(-1\). Here \(Y\) is estimated separately as:

- \(D_{i,o,q,t}\), for direct-route availability;
- \(\mathrm{DirectDepth}_{i,o,q,t}\), conditional on direct availability;
- \(\mathrm{AnyIndirectAvailable}_{i,o,q,t}\), for indirect route opportunity;
- \(\mathrm{IndirectRouteShare}_{i,o,t}\), conditional on positive realized pair volume.

The compact difference-in-differences summary replaces the event-month terms with \(\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}\times \mathrm{PostV3}_t\). Pair and calendar-date fixed effects are used. Standard errors are two-way clustered by ordered pair and calendar week.

**Empirical prediction:** the post-V3 coefficients for \(D_{i,o,q,t}\) and \(\mathrm{DirectDepth}_{i,o,q,t}\) should be more positive for pairs with larger pre-V3 direct constraints if V3 deepens direct markets. The sign for \(\mathrm{IndirectRouteShare}_{i,o,t}\) is deliberately not imposed:

- a negative effect, accompanied by stronger direct availability or depth, means direct-market deepening reduces vehicle reliance;
- a positive effect, accompanied by stronger indirect availability, means V3 deepens vehicle-linked legs enough to increase vehicle reliance;
- route-share movement without either opportunity-set mechanism is not interpreted as an architecture result.

The pre-V3 \(\beta_\mu\) coefficients must be individually small and jointly indistinguishable from zero. Diagnostics also include placebo launch dates, alternative 12- and 24-month windows, the three \(q\) values, and a balanced quote coverage audit.

### Evidence that answers RQ4

RQ4 is answered by the event-time difference between weak and strong pre-V3 direct markets and by the accompanying route-opportunity channel. It is not answered by a simple before-after mean. Detectable differential pretrends, missing-data imbalance, or a route-share shift without a direct or indirect opportunity change blocks causal language. Even with clean pretrends, the interpretation is a differential V3 architecture effect, not a claim that all market changes at the launch date were caused by V3.

Planned outputs: `v3_execution_architecture.tex` and `v3_execution_architecture_event_study.pdf`.

## RQ5. Settlement netting

### Question

Can a token retain its economic role as the intermediate in an \(i\to k\to o\) route while settlement architecture reduces observable physical transfer of that token?

### Experiment: receipt-audited matched V3/V4 route comparison

Route classification is constructed from swap execution before the transfer outcome is measured. The full comparison universe reports \(|\mathcal R^3_g|\), \(|\mathcal R^4_g|\), and \(\mathrm{V4RouteShare}_g\) for cells \(g\) defined by ordered pair, vehicle, UTC week, and a pre-specified route-size bin. This establishes the coverage and economic presence of V4 vehicle routes without requiring both versions to appear in every cell.

The regression sample then restricts to matched cells with \(|\mathcal R^3_g|>0\) and \(|\mathcal R^4_g|>0\):

\[
\mathrm{Transfer}_{r,k}
=\alpha_g+\beta_{\mathrm{V4}}\mathrm{V4}_r
+\varepsilon_{r,k}.
\]

Cell fixed effects compare V3 and V4 route units with the same pair, vehicle, week, and size bin. Standard errors are two-way clustered by comparison cell and week. The table reports both the regression coefficient and raw version-specific transfer incidence.

**Empirical prediction:** \(\beta_{\mathrm{V4}}<0\), with a material percentage- point reduction relative to V3 transfer incidence. The route counts and \(\mathrm{V4RouteShare}_g\) must also show that the result is not driven by a negligible set of V4 routes.

Receipt validity gates are part of the experiment:

- the ordered endpoints and intermediate contract must agree across route reconstruction, swap logs, and the transfer parser;
- proxy and wrapped-token contracts must be resolved to exact contract addresses, not ticker strings;
- every parser disagreement and a stratified sample of transfer and no-transfer receipts must be manually audited; and
- conclusions must survive alternative pre-specified size bins and a one-route- per-transaction restriction.

### Evidence that answers RQ5

RQ5 is supported when economically classified V4 \(i\to k\to o\) routes have substantially lower intermediate-token transfer incidence within matched cells, while the full comparison universe shows nontrivial V4 route use. The claim fails if the difference disappears after receipt validation or matching, if route and transfer classification are not independent, or if V4 route coverage is too thin to support the comparison.

This experiment identifies a settlement-implementation difference conditional on vehicle routing. It does not show that V4 caused a token to become a vehicle or increased vehicle adoption.

Planned output: `v4_settlement_decoupling.tex`.

## Notation added for this review

The notation registry now includes, but does not yet materialize, the following proposed measurements:

- pair route outcomes: \(\mathrm{IndirectRouteShare}_{i,o,t}\) and \(\mathrm{VehicleShare}_{i,o,k,t}\);
- pair quote measures: \(\mathrm{AnyIndirectAvailable}_{i,o,q,t}\), \(\mathrm{DirectDepth}_{i,o,q,t}\), and \(\mathrm{IndirectDepth}_{i,o,k,q,t}\);
- liquidity factors: \(\mathrm{VehicleLiquidityFactor}_{p,k,t}\) and \(\mathrm{MarketLiquidityFactor}_{p,t}\);
- displacement objects: \(k^\star_{i,o,t}\), \(h^\star_{i,o,q,t}\), \(\mathrm{CandidateStress}_{k,t}\), \(\mathrm{Incumbent}_{i,o,k,t}\), \(\mathrm{ChallengerCostEdge}_{i,o,q,t}\), and \(\mathrm{VehicleSwitch}_{i,o,q,t,\tau}\);
- architecture objects: \(t^{\mathrm{V3}}_0\), \(\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}\), \(\mathcal P^{\mathrm{V3}}_q\), \(\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}\), and \(\mathrm{PostV3}_t\); and
- settlement objects: \(\mathcal R^3_g\), \(\mathcal R^4_g\), \(\mathrm{Transfer}_{r,k}\), \(\mathrm{V4}_r\), and \(\mathrm{V4RouteShare}_g\).

They are flagged outside the current wide observations table so this review does not silently trigger data construction.

## Review decisions before execution

- [ ] Approve the five RQs and the use of empirical predictions instead of separately numbered hypotheses.
- [ ] Approve \(q=\$10{,}000\) as primary and \(\$1{,}000/\$100{,}000\) as robustness notionals.
- [ ] Approve the RQ2 horizons \(1/7/30\) and RQ3 horizons \(7/30/90\).
- [ ] Approve candidate-specific standardized stress as primary, with WETH-only stress retained as a special-case robustness test.
- [ ] Approve the fixed challenger-edge knots \(0/25/50/100/200\) basis points.
- [ ] Approve the fixed V3 pre-period pair rule, event window, and bounded causal language.
- [ ] Decide whether RQ5 belongs in the main paper or is retained as an empirical architecture extension.

## Execution hold

Do not run or modify the empirical experiment scripts, rebuild result tables, or rewrite result prose until the RQs, primary specifications, and review decisions above are approved. After approval, each panel is constructed by a durable script, intermediate data use language-native binary formats, and paper outputs are TeX and PDF only. No CSV output is generated.

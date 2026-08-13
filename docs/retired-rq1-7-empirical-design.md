# Retired RQ1–7 empirical-design memo

**Status:** Retired design record. This July RQ1–7 experiment menu is preserved for history, but it is not a current agent route, estimator specification, findings record, or deliverable source. Current execution follows `docs/specification-lock.json`, `docs/findings-freeze.md`, and `docs/research-workflow.md`.

Generated 2026-07-08. Purpose: redesign the DVC workflow around empirical experiments first. A theory section is optional and should be added only after the empirical design is coherent.

## Flow Decision

The paper should be empirical-first.

Start with research questions, empirical variation, outcomes, and regression designs. Do not require a formal model before the empirical work. Theoretical content can remain atomic: a short intuition paragraph in the introduction, a compact conceptual framework, or an appendix model only if it clarifies why the empirical tests answer the RQs.

Do not use `LiWangYe2021WhoProvides` as an empirical-only style template. The NBER version explicitly says "We model competition for liquidity provision", so it is useful background for liquidity-provider competition, not the template for this paper's empirical architecture.

Do not use CS-style DeFi LP papers as writing or identification templates. They may help with variable construction, wallet-level mechanics, and sanity checks, but the style target is empirical finance.

## Empirical-Finance Templates

Use these papers for style, identification architecture, and table design:

1. **Bessembinder, Hao, and Zheng (2020), RFS, "Liquidity Provision Contracts and Market Quality"**
   - Template role: clean empirical market-quality paper using institutional contract variation.
   - Design feature to copy: one institutional feature generates variation; several market-quality outcomes are tested with tight tables; mechanism is argued through empirical outcomes, not a standalone formal model.
   - DOI: https://doi.org/10.1093/rfs/hhz040

2. **Clark-Joseph, Ye, and Zi (2017), JFE, "Designated Market Makers Still Matter"**
   - Template role: layered event and exposure evidence on a designated supplier's marginal spread contribution.
   - Design feature to copy: pair a focal venue outage with adjacent-time placebos, a second-venue falsification and supplier-exposure decomposition; do not infer provider indispensability or an obligation mechanism from the source.
   - DOI: https://doi.org/10.1016/j.jfineco.2017.09.001

3. **Hendershott, Jones, and Menkveld (2011), JF, "Does Algorithmic Trading Improve Liquidity?"**
   - Template role: market-structure/technology change as plausibly exogenous variation.
   - Design feature to copy: use an institutional technology shock or instrument to link trading technology to liquidity and price-discovery outcomes.
   - DOI: https://doi.org/10.1111/j.1540-6261.2010.01624.x

4. **O'Hara and Ye (2011), JFE, "Is Market Fragmentation Harming Market Quality?"**
   - Template role: broad panel evidence on market architecture and market quality.
   - Design feature to copy: connect fragmentation/architecture measures to multiple market-quality outcomes in a consistent panel.
   - DOI: https://doi.org/10.1016/j.jfineco.2011.02.006

5. **Anand and Venkataraman (2016), JFE, "Market Conditions, Fragility, and the Economics of Market Making"**
   - Template role: market-maker participation under separately measured volume, order-flow and volatility states.
   - Design feature to copy: condition liquidity-supply tests on low activity and one-sided order flow while preserving the opposite positive association with volatility; use this as a heterogeneity template, not identification.
   - DOI: https://doi.org/10.1016/j.jfineco.2016.03.006

6. **Comerton-Forde, Hendershott, Jones, Moulton, and Seasholes (2010), JF, "Time Variation in Liquidity"**
   - Template role: liquidity supply responds to intermediary balance-sheet/inventory states.
   - Design feature to copy: supplier-state variables explain liquidity, with nonlinear effects when constraints bind.
   - DOI: https://doi.org/10.1111/j.1540-6261.2009.01530.x

7. **Coughenour and Saad (2004), JFE, "Common Market Makers and Commonality in Liquidity"**
   - Template role: common liquidity from shared intermediaries.
   - Design feature to copy: commonality regressions that tie cross-market liquidity co-movement to common liquidity suppliers.
   - DOI: https://doi.org/10.1016/j.jfineco.2003.05.006

8. **Chordia, Roll, and Subrahmanyam (2000), JFE, "Commonality in Liquidity"**
   - Template role: canonical empirical common-liquidity table structure.
   - Design feature to copy: estimate whether liquidity changes co-move with market-wide or group-specific liquidity factors.
   - DOI: https://doi.org/10.1016/S0304-405X(99)00057-4

## Empirical Objects

Core panel:

- Unit: endpoint pair \(i=(a,c)\), candidate vehicle \(v\), time \(t\) at day or hour frequency.
- Route opportunity set: observations where both direct and at least one vehicle route are feasible or where direct infeasibility is itself part of the treatment.
- Main outcomes:
  - `vehicle_share_{k,t}`: share of routed volume or route count through candidate vehicle \(k\).
  - `vehicle_indicator_{route}`: transaction-level or route-level indicator that \(v\) intermediates.
  - `direct_cost_advantage_{i,v,t}`: direct-route output minus indirect-route output, divided by direct-route output, for a standard trade-size grid; positive values favor the direct route.
  - `vehicle_linked_liquidity_{i,v,t}`: active liquidity near price in pools linking endpoints to \(v\).
  - `direct_depth_{i,t}` and `direct_available_{i,t}`.
  - `settlement_transfer_incidence_{route}` for physical transfer of the intermediate token.
  - `common_vehicle_liquidity_factor_{v,t}`.

Design principle: build a small family of regressions on the same panel. A large regression can answer multiple RQs, but the paper should present it as a coordinated empirical system, not as one unreadable table.

## Experiments by RQ

### RQ1. Under what market conditions does one asset become the vehicle?

Empirical experiment: route-cost dominance and direct-market incompleteness.

Main test:

\[
VehicleShare_{k,t} =
\beta_1 DirectCostAdvantage_{k,t-\tau}
+ \beta_2 DirectUnavailable_{k,t-\tau}
+ \beta_3 VehicleDepth_{k,t-\tau}
+ \beta_4 DirectDepth_{k,t-\tau}
+ FE + \epsilon_{k,t}.
\]

Here and below, \(\tau\) is the prediction horizon in calendar days; the main
specifications report \(\tau=7\) and \(\tau=30\).

Interpretation: a vehicle emerges when DirectCostAdvantage is lower, the vehicle route is deeper, or the vehicle route is available when the direct market is thin or absent.

Template: Bessembinder-Hao-Zheng for market-quality outcomes from institutional variation; Hendershott-Jones-Menkveld for market-structure variation.

### RQ2. How does liquidity provision make a vehicle?

Empirical experiment: liquidity-route feedback.

Main tests:

\[
VehicleShare_{k,t} =
\beta_1 VehicleLinkedLiquidity_{k,t-\tau}
+ \beta_2 LPRepositioning_{k,t-\tau}
+ \beta_3 DirectCostAdvantage_{k,t-\tau}
+ FE + \epsilon_{k,t}.
\]

\[
VehicleLinkedLiquidity_{k,t} =
\gamma_1 VehicleShare_{k,t-\tau}
+ \gamma_2 VehicleRouteVolume_{k,t-\tau}
+ \gamma_3 FeesEarned_{k,t-\tau}
+ FE + \eta_{k,t}.
\]

Interpretation: liquidity provision makes the vehicle if vehicle-linked liquidity predicts future vehicle use and vehicle use predicts future LP liquidity.

Template: Bessembinder-Hao-Zheng for liquidity-provision contracts; Comerton-Forde et al. for liquidity-supplier state and nonlinear constraint effects.

### RQ3. Why does vehicle status persist?

Empirical experiment: persistence and switching thresholds.

Main test:

\[
VehicleShare_{k,t} =
\rho VehicleShare_{k,t-\tau}
+ \beta DirectCostAdvantage_{k,t-\tau}
+ \theta ChallengerAdvantage_{k,t-\tau}
+ FE + \epsilon_{k,t}.
\]

Add bins for challenger cost advantage to estimate the threshold needed to displace an incumbent vehicle.

Interpretation: status is sticky if lagged vehicle share remains large after controlling for contemporaneous DirectCostAdvantage, and displacement occurs only after large challenger cost or safety edges.

Template: empirical persistence/event-study tables, not a theory model.

### RQ4. When does vehicle status switch?

Empirical experiment: stress-state rotation inside common route opportunities.

Main test:

\[
WETHShareGap_{i,t} =
\beta_1 Stress_t
+ \beta_2 Stress_t \times CommonSupport_i
+ FE_{i} + FE_{event\ time} + \epsilon_{i,t}.
\]

Alternative vehicle-level specification:

\[
VehicleShare_{i,v,t} =
\beta_1 Stress_t \times RiskyVehicle_v
+ \beta_2 Stress_t \times StableVehicle_v
+ FE_{i,v} + FE_t + \epsilon_{i,v,t}.
\]

Interpretation: vehicle status switches when a shock to the incumbent's risk or credibility causes route share to move toward safer substitutes within the same opportunity set.

Template: Anand-Venkataraman for state-decomposed liquidity-provider participation; Clark-Joseph-Ye-Zi for natural-experiment/event logic.

### RQ5. How does market architecture change vehicle formation?

Empirical experiment: architecture-change event studies.

Main tests:

- V3 concentrated liquidity: direct-market-deepening treatment.
- Fee-tier design: route-cost and LP allocation response.
- Fragmentation/specialization: whether liquidity moves into vehicle-linked or direct pools.

Specification:

\[
Outcome_{i,v,t} =
\beta PostArchitecture_t \times TreatedPair_i
+ FE_i + FE_t + Controls_{i,t} + \epsilon_{i,t}.
\]

Outcomes: direct-route availability, direct depth, DirectCostAdvantage, vehicle share, vehicle-linked liquidity.

Interpretation: architecture matters if design changes alter route feasibility, direct-market depth, or LP incentives enough to change vehicle reliance.

Template: O'Hara-Ye for architecture/fragmentation panels; Hendershott-Jones-Menkveld for technology-induced market-quality changes.

### RQ6. How does settlement design change vehicle use?

Empirical experiment: route role versus physical settlement movement.

Main tests:

1. Match coherent multi-hop route units across settlement architectures.
2. Estimate whether netting lowers intermediate-token transfer incidence.
3. Test whether lower settlement movement predicts stronger vehicle-linked liquidity or route use.

Specification:

\[
TransferIncidence_{route} =
\beta NettingArchitecture_{route}
+ FE_{endpoint,vehicle,time}
+ Controls + \epsilon.
\]

\[
VehicleLinkedLiquidity_{i,v,t+h} =
\gamma NettingExposure_{i,v,t}
+ FE + \eta.
\]

Interpretation: settlement design changes vehicle use if the vehicle can remain economically central while physical token movement falls, or if netting exposure changes LP supply.

Template: market-design/event-study papers above; no need for a formal settlement model unless the empirical result is ambiguous.

### RQ7. Does a vehicle create common liquidity across markets?

Empirical experiment: common vehicle-linked liquidity factor.

Main test:

\[
\Delta Liquidity_{pool,t} =
\beta_1 \Delta MarketLiquidity_t
+ \beta_2 \Delta VehicleLiquidityFactor_{v,t}
+ \beta_3 Stress_t \times \Delta VehicleLiquidityFactor_{v,t}
+ FE_{pool} + \epsilon_{pool,t}.
\]

Interpretation: the vehicle creates common liquidity if pools linked to the same vehicle co-move after controlling for market-wide liquidity, especially during stress or after architecture changes.

Template: Chordia-Roll-Subrahmanyam for commonality structure; Coughenour-Saad for common intermediary channel.

## Main Table Architecture

Use fewer, stronger tables:

1. **Table 1: Sample, route reconstruction, and variables.**
2. **Table 2: Route-cost dominance and direct-market incompleteness.** Answers RQ1.
3. **Table 3: Liquidity-route feedback.** Answers RQ2 and RQ3.
4. **Table 4: Stress-state rotation in common route opportunities.** Answers RQ4 and persistence after shocks.
5. **Table 5: Architecture changes and vehicle reliance.** Answers RQ5 and contributes to RQ1.
6. **Table 6: Settlement netting and vehicle use.** Answers RQ6.
7. **Table 7 or appendix: Common liquidity.** Answers RQ7 if strong; otherwise appendix.

Figures:

1. Route object and vehicle definition.
2. Vehicle shares and paired liquidity over time.
3. Event-time stress rotation.
4. Architecture event study.

## Theory Gate

Add theory only if at least one of these conditions holds:

- The same coefficient has multiple plausible interpretations and a minimal model separates them.
- The empirical system needs a clear threshold/comparative-static object.
- Referees are likely to ask why liquidity-route feedback is not just mechanical simultaneity.

If theory is added, it should be atomic:

- no broad monetary model;
- no separate theory contribution claim;
- one small setup with trader route choice and LP liquidity choice;
- propositions only where they map directly to a table.

The default paper should read as an empirical market-design and market-quality paper.

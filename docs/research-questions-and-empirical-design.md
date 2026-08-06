# Research questions and empirical design (review draft)

**Status:** exploratory design menu, superseded for execution on 2026-08-07 by the hashed machine-readable lock in `docs/specification-lock.json`. This file preserves the wider candidate set and its reasoning; it is not authority to run a withheld estimator or promote an unapproved claim.

**Organizing question:** how do trading technology, liquidity-provider capital, and settlement technology create or break increasing returns to a vehicle asset?

The canonical symbols, formulas, units, and constructions are maintained in `src/ddvc/variable_registry.py` and rendered in `output/tables/variable_notation.tex` and `output/tables/variable_notation.pdf`. Every quantity used below is already registered there; proposed fields remain outside the current observations table until this design is approved.

## RQs, not duplicate hypotheses

Use research questions as the paper's organizing labels. Do not maintain a parallel numbered hypothesis list: each RQ below states competing mechanisms, coefficient-level decision rules, evidence that would refute the proposed mechanism, and the permitted interpretation. This preserves an empirical-first paper and leaves theory as an optional, atomic extension after the evidence is known.

## Literature classification

The anchor audit below is based on the local PDF corpus and the keys in [`literature/vehicle-currencies.bib`](../literature/vehicle-currencies.bib). Classification matters because only genuinely empirical papers should serve as design and presentation templates.

| Literature | Classification | Use in this design |
|---|---|---|
| Chordia, Roll, and Subrahmanyam (2000), `ChordiaRollSubrahmanyam2000Commonality` | Pure empirical | Commonality benchmark and control structure for RQ2 |
| Coughenour and Saad (2004), `CoughenourSaad2004CommonMarketMakers` | Pure empirical | Shared-intermediary capital channel for RQ2 |
| Comerton-Forde et al. (2010), `ComertonFordeEtAl2010Inventories` | Pure empirical | Market-maker wealth/inventory shock template for RQ2 and RQ5 |
| Hendershott, Jones, and Menkveld (2011), `HendershottJonesMenkveld2011Algorithmic` | Pure empirical | Trading-technology event design and provider-rent benchmark for RQ4 |
| Anand and Venkataraman (2016), `AnandVenkataraman2016MarketMaking` | Pure empirical | Participation, synchronous withdrawal, and fragility benchmark for RQ2 |
| Clark-Joseph, Ye, and Zi (2017), `ClarkJosephYeZi2017DMM` | Pure empirical; local corpus includes the published version | Natural-experiment standard for identifying indispensable versus redundant liquidity providers |
| Bessembinder, Hao, and Zheng (2020), `BessembinderHaoZheng2020Contracts` | Pure empirical | Regression-discontinuity standard and strategic-complementarity spillover benchmark for RQ2 |
| Krugman (1980), `Krugman1980VehicleCurrencies`; Dowd and Greenaway (1993), `DowdGreenaway1993CurrencyCompetition` | Theory | Increasing returns, network externalities, inertia, and abrupt displacement mechanisms for RQ1 and RQ3 |
| Grossman and Miller (1988), `GrossmanMiller1988Liquidity`; Ho and Stoll (1981), `HoStoll1981OptimalDealer`; Brunnermeier and Pedersen (2009), `BrunnermeierPedersen2009Liquidity` | Theory | Finite risk-bearing and intermediary-capital mechanisms for RQ2 and RQ5 |
| Gopinath and Stein (2021), `GopinathStein2021Making` | Primarily theory with preliminary correlations | Boundary-condition anchor for whether medium-of-exchange use remains tied to settlement and stores of value in RQ5 |
| Chen and Duffie (2021), `ChenDuffie2021Fragmentation` | Theory | Competing prediction that fragmentation can reduce venue depth yet improve allocation through order splitting in RQ4 |
| Somogyi (2026), `Somogyi2026DollarDominanceFX` | Model plus empirical evidence, not pure empirical | Substantive FX benchmark for price-impact-driven vehicle routing; not a design-style template |
| Lehar and Parlour (2024), `LeharParlour2024Uniswap` | Equilibrium model plus empirical evidence, not pure empirical | AMM pool-size, price-impact, and adverse-selection benchmark for RQ1, RQ2, and RQ4 |
| Caparros, Chaudhary, and Klein (2024), `CaparrosChaudharyKlein2024BlockchainScaling` | Empirical working paper | DEX benchmark for gas costs, repositioning, liquidity concentration, and slippage in RQ4 |
| Li, Wang, and Ye (2021), `LiWangYe2021WhoProvides` | Theory/model paper, not pure empirical | Theory comparator only; not used as an empirical template |
| Heimbach, Pahari, and Schertenleib (2024), `HeimbachPahariSchertenleib2024NonAtomic` | Computer-science paper | Not used as the finance/economics design or writing template |

## Proposed RQ set

1. **RQ1. When and why does indirect intermediation dominate direct exchange?**
2. **RQ2. Does vehicle use create a liquidity multiplier, and who captures the rents?**
3. **RQ3. Does vehicle dominance exhibit hysteresis and abrupt displacement?**
4. **RQ4. Does liquidity-enhancing execution technology decentralize exchange or entrench the vehicle?**
5. **RQ5. Does net settlement sever transactional intermediation from physical settlement and market-making capital?**

The questions are deliberately mechanism-based rather than protocol-feature-based. Hooks are not a headline RQ; any hook-level analysis is a heterogeneity test only if it maps to execution cost, LP risk, or settlement netting.

## Cross-RQ design rules

- The primary quote notional remains \(q=\$10{,}000\), with \(\$1{,}000\) and \(\$100{,}000\) as fixed robustness notionals; RQ1 additionally evaluates the observed route notional and a wider fixed size grid where historical state replay is executable.
- All direct and indirect alternatives in a comparison use the same block state, input token, output token, input USD notional, token prices, and gas-price convention.
- Quote-output cost and all-in cost are not interchangeable: \(C^D\), \(C^I\), and \(\Delta C^{D,\mathrm{all}}\) include gas, while \(\Delta C^D\) remains the quote-output-only measure.
- Each all-in route cost retains the registered fee, price-impact, and gas components \(C^{D,\mathrm{fee}}\), \(C^{D,\mathrm{impact}}\), \(C^{D,\mathrm{gas}}\), \(C^{I,\mathrm{fee}}\), \(C^{I,\mathrm{impact}}\), and \(C^{I,\mathrm{gas}}\) even when the regression uses their sum.
- Episode counts are primary for the vehicle transition because topology coverage is complete while price support is type-dependent. Strict 20% valuation-coherent USD shares are secondary; raw value, pair coverage, and all-route denominators remain diagnostics.
- \(\mathrm{VehicleHHI}_{i,o,t}\) is concentration conditional on the fixed candidate set; every HHI result must be accompanied by \(\mathrm{Coverage}^{\mathcal K}_{i,o,t}\) and repeated with an expanded candidate set so changing out-of-set routing cannot masquerade as concentration.
- Every result table must report the coefficient, standard error, 95% confidence interval, \(p\)-value, sample size, fixed effects, clustering method, and an economically scaled effect.
- A predicted sign is supported only when its two-sided 95% confidence interval excludes zero; Holm-adjusted \(p\)-values are reported within each RQ's primary coefficient family.
- Predictive panel evidence is called predictive. Causal language requires the stated treatment timing, pretrend, balance, exclusion, and placebo tests to pass.
- Missing data trigger durable acquisition or reconstruction work; they never justify silently dropping an experiment or substituting a weaker proxy.
- After approval, every data build and estimator is a committed script, intermediate data use a language-native binary format, and paper outputs are TeX/PDF with descriptive filenames, no hard-coded numbering, no CSV, and no notes embedded in tables.

## Compact crosswalk

| RQ | Core empirical tension | Primary design | Decisive evidence |
|---|---|---|---|
| RQ1 | Two pool legs charge twice, but a deep vehicle path can have lower convex price impact than one thin direct pool | Same-state direct-versus-indirect cost frontier plus pair and candidate route-choice panels | \(\Delta C^{D,\mathrm{all}}<0\) for economically important cells and a significantly negative route-choice coefficient on \(\Delta C^{D,\mathrm{all}}\) |
| RQ2 | Vehicle demand can attract liquidity, but shared LP balance sheets can also create fragile commonality; gross fees need not be net rents | Bidirectional use/liquidity projections, LP shift-share wealth shocks, provider-overlap decomposition, and fee/LVR/net-return panels | Vehicle use predicts future liquidity; outside LP losses cause withdrawals; low-overlap spoke commonality survives; fee and net-return incidence identify who gains |
| RQ3 | Near-zero algorithmic user switching costs should weaken inertia, but liquidity coordination can still protect an incumbent until a threshold is crossed | Persistence conditional on current all-in economics plus challenger-edge crossing and candidate-stress event studies | Lagged incumbent status remains significant after current economics, and switching responds nonlinearly or abruptly when the challenger edge becomes large |
| RQ4 | Concentrated liquidity can improve execution while either deepening direct markets or concentrating routes around a few vehicle spokes | Fixed-universe heterogeneous V3 event study using pre-V3 direct constraint and pair volatility | Better depth together with falling indirect share/vehicle HHI means decentralization; better depth together with rising indirect share/vehicle HHI means entrenchment |
| RQ5 | V4 can net physical movements without eliminating the two economic swaps or their LP fees | Receipt-audited V3/V4 comparison plus pre-exposure pair and LP-capital event studies | Physical settlement intensity falls; route use, gas, LP flow, fee yield, net return, and turnover reveal whether netting expands, contracts, or merely virtualizes vehicle intermediation |

## RQ1. When and why does indirect intermediation dominate direct exchange?

### Literature anchors

| Anchor | Existing result or mechanism | Relationship to RQ1 |
|---|---|---|
| Krugman (1980) | Transaction cost falls with market volume, so routing through a large third currency can dominate bilateral exchange and reinforce that currency's scale | **Direct test and possible support:** replace the unobserved FX cost schedule with exact same-state AMM route counterfactuals; **refute in this setting** if scale and liquidity add no explanatory power after all-in cost |
| Somogyi (2026) | The direct FX spread can be lower while the vehicle route is cheaper after price impact; holiday variation is used because FX data do not reveal motive | **Expand and sharpen:** observe the intermediate directly, compare every executable route, and separate fee, price impact, and gas rather than infer vehicle demand from holidays |
| Lehar and Parlour (2024) | AMM pool size reflects fee revenue, adverse selection, and price impact | **Expand:** move from isolated pool quality to the economic choice between one direct pool and a two-pool network path |

### Experiment A: same-state route-cost frontier

- **Unit:** ordered pair-candidate-state-notional \((i,o,k,t,q)\), with block-level state preferred and day snapshots used only where exact historical state is unavailable.
- **Sample:** a fixed or predetermined rolling universe of economically active ordered pairs; \(k\in\mathcal K\setminus\{i,o\}\); retain unavailable direct and indirect alternatives as availability outcomes rather than deleting them.
- **Construction:** replay the direct route and every via-\(k\) route from the identical pre-trade state; compute \(C^D_{i,o,q,t}\), \(C^I_{i,o,k,q,t}\), and \(\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}=C^I-C^D\).
- **Decomposition:** rerun each route holding the marginal reference price fixed to isolate pool fees, then attribute residual quote loss to price impact and add route-specific historical gas; the three contributions must sum back to all-in cost within a numerical tolerance.
- **Outputs after approval:** availability by \(q\); the fraction and USD-weighted fraction of common-support cells with \(\Delta C^{D,\mathrm{all}}<0\); distributions of the direct-minus-indirect fee, impact, and gas components; and cost-difference curves over \(q\).
- **Nonlinearity rule:** do not force one crossing-size statistic, because concentrated-liquidity routes can cross more than once; report all sign-changing intervals on the fixed size grid and validate them with denser local replay.

### Experiment B: realized indirect-route reliance

The unit is pair-day. First estimate the extensive margin using \(D_{i,o,q,t}\), \(\mathrm{AnyIndirectAvailable}_{i,o,q,t}\), and next-day \(\mathrm{IndirectRouteShare}_{i,o,t+1}\). On common support, estimate the all-in economic specification separately at each \(q\):

\[\mathrm{IndirectRouteShare}_{i,o,t+1}=\alpha_{i,o}+\delta_t+\beta_C\min_{k:I_{i,o,k,q,t}=1}\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}+\beta_Q\mathrm{DirectDepth}_{i,o,q,t}+\varepsilon_{i,o,t+1}.\]

- **Fixed effects and inference:** ordered-pair and date fixed effects; two-way clustering by ordered pair and date.
- **Primary signs:** \(\beta_C<0\), because a larger direct cost advantage should reduce indirect reliance; \(\beta_Q<0\), because better direct execution should reduce indirect reliance.
- **Size test:** estimate the same specification separately by \(q\); a more negative indirect-versus-direct cost difference at large \(q\) together with greater large-trade indirect reliance isolates convex price impact from fixed gas cost.

### Experiment C: candidate choice within indirect routes

The unit is pair-candidate-day, restricted to executable via-\(k\) alternatives and positive next-day indirect volume. Pair-date fixed effects compare candidates facing the same endpoints and market state:

\[\mathrm{VehicleShare}_{i,o,k,t+1}=\alpha_{i,o,k}+\lambda_{i,o,t}+\beta_K\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}+\beta_L\mathrm{LPConc}_{k,t}+\varepsilon_{i,o,k,t+1}.\]

- **Primary signs:** \(\beta_K<0\), because a candidate with a cheaper indirect route has a smaller direct cost advantage and should capture more share; \(\beta_L>0\) is evidence that candidate-linked scale predicts selection beyond measured contemporaneous route cost.
- **Algebra rule:** do not place \(\mathrm{IndirectDepth}_{i,o,k,q,t}\) and a cost measure built from the same \(O^I\) in one pair-date specification and interpret both structurally.

### Experiment D: routing-search efficiency and market integration

The 2020 to 2026 transition also spans the diffusion of aggregators, universal routers, cross-venue execution, and faster arbitrage. The routing layer has two opposing implications for vehicle use. It can find direct liquidity across previously siloed pools and reduce indirect routing, or it can combine fragmented spoke liquidity and make a stable intermediary more usable. It can also make observed routes more efficient without changing the underlying vehicle-cost frontier. This is a competing mechanism for the time-series vehicle transition, not a one-sign explanation for whichever transition the data show.

- **Opportunity-set efficiency:** by month, measure the dispersion of same-state triangular residuals, direct-versus-best-route cost gaps, within-block correction, and the share of transactions executing across multiple pools or venues. Keep cost-surface efficiency separate from realised router choice.
- **Disintermediation versus activation:** report true intermediary-route incidence among economic routes separately from direct pool splitting and from the intermediary composition of the remaining indirect routes, on both the full and balanced venue perimeters. Canonical endpoint round trips enter neither numerator nor denominator. A fall in incidence supports direct-liquidity discovery; stable-share growth conditional on remaining indirect supports activation of fragmented stable liquidity. Report balanced-perimeter coverage and incidence among entrant-touching routes, because chosen-route support exit can make incumbent-only incidence fall even without better search. None of these mechanisms can be inferred from cross-venue growth alone.
- **Behaviour-first router proxy:** use transaction-level direct splitting, sequential intermediation, route complexity, and cross-venue execution as separate search-sophistication measures. `sender` identifies an executor, not the originating aggregator; labelled-address results remain a partial-coverage sensitivity using the versioned registry and never define the primary sample.
- **Transition test:** re-estimate vehicle extent and candidate choice within date-pair-size opportunity sets, stratified by search sophistication, and interact candidate type with the monthly efficiency measures. Report whether the stable-vehicle transition occurs inside comparable search regimes or is concentrated in the adoption of more integrated routing.
- **Interpretation bound:** if stable dominance disappears after conditioning on these measures, the result is a routing-technology transition. If it survives within comparable opportunity and search sets, liquidity composition remains the live mechanism. If sophisticated routing disproportionately selects stable vehicles from a dispersed pool set, routing technology is a mechanism that activates stable liquidity, not a nuisance control.

### Decision rule for RQ1

| Finding | Answer |
|---|---|
| Economically important common-support cells have \(\Delta C^{D,\mathrm{all}}<0\), especially at larger \(q\), and \(\beta_C,\beta_K<0\) significantly | Indirect intermediation dominates when deeper vehicle spokes save more price impact than the added fees and route gas; this supports Krugman's scale mechanism and expands Somogyi with observed route choice |
| Indirect routes win only before gas is added | Vehicle routing is a quote-quality phenomenon but not an all-in economic advantage for users |
| Indirect routes remain common when \(\Delta C^{D,\mathrm{all}}>0\), and lagged scale/liquidity remains significant | Current cost is incomplete; persistence, reliability, private order flow, or coordination moves to RQ3 rather than being labelled irrationality |
| All-in cost does not predict realized route choice | Refute the proposed cost mechanism or revisit route reconstruction, unobserved router objectives, and quote timing before making a formation claim |
| The stable-vehicle transition is confined to high-search or late-efficiency regimes | Attribute the transition to routing integration, or to routing integration activating fragmented stable liquidity; do not describe it as unconditional currency succession |

**Potentially surprising result:** two swaps can be cheaper than one only above a trade-size region because direct-pool price impact is convex, even though the indirect route pays two fee legs and more gas.

## RQ2. Does vehicle use create a liquidity multiplier, and who captures the rents?

### Literature anchors

| Anchor | Existing result or mechanism | Relationship to RQ2 |
|---|---|---|
| Chordia, Roll, and Subrahmanyam (2000) | Liquidity has market and industry common components after standard controls, but the source is not identified | **Corroborate and narrow:** test commonality on economically linked vehicle spokes, then separate common demand from shared-provider capital |
| Coughenour and Saad (2004) | Common specialist firms transmit capital and information across the stocks they manage | **Direct expansion:** on-chain positions reveal provider overlap and permit explicit exclusion of shared LP addresses |
| Comerton-Forde et al. (2010) | Market-maker inventory and income shocks predict future liquidity, with stronger nonlinear effects after losses | **Design anchor:** use predetermined outside-pool LP exposures and token-return shocks to test balance-sheet transmission |
| Anand and Venkataraman (2016) | Voluntary market makers enter and withdraw synchronously as profits and risk change; designated providers mitigate fragility | **Expand:** test synchronous LP withdrawal and whether vehicle-spoke demand offsets or amplifies it without a designated provider |
| Clark-Joseph, Ye, and Zi (2017) | Removing NYSE designated market makers impairs marketwide liquidity, while removing a voluntary venue does not | **Expand:** use provider-level shocks and pool capital shares to distinguish economically indispensable LP capital from redundant liquidity supply |
| Bessembinder, Hao, and Zheng (2020) | Stronger designated-market-maker obligations improve liquidity, including positive spillovers away from the treated venue | **Expand:** test whether vehicle liquidity is strategically complementary across pools rather than merely reallocated between them |
| Hendershott, Jones, and Menkveld (2011) | Automation improves liquidity and can initially raise liquidity-supplier realized spreads before the rent dissipates | **Expand:** separate LP gross fee yield from LVR, gas, and net return rather than equating volume or fees with rents |
| Grossman and Miller (1988); Brunnermeier and Pedersen (2009) | Market liquidity depends on finite intermediary risk-bearing and funding capacity | **Mechanism support or refutation:** outside LP wealth shocks should move supply if AMM liquidity remains balance-sheet constrained |

### Experiment A: use-to-liquidity multiplier and reverse feedback

Estimate candidate-day local projections in both directions for \(\tau\in\{1,7,30\}\), with candidate and date fixed effects and the current outcome level included:

\[\Delta_\tau\mathrm{LogVehicleLiquidity}_{k,t+\tau}=\alpha_k+\delta_t+\gamma_\tau\mathrm{VehicleShare}_{k,t}+\phi_\tau\mathrm{LogVehicleLiquidity}_{k,t}+\beta_\tau\mathrm{AllInDirectCostAdvantage}_{k,t,q}+\varepsilon_{k,t+\tau}.\]

\[\Delta_\tau\mathrm{VehicleShare}_{k,t+\tau}=\alpha_k+\delta_t+\eta_\tau\mathrm{LPConc}_{k,t}+\rho_\tau\mathrm{VehicleShare}_{k,t}+\beta_\tau\mathrm{AllInDirectCostAdvantage}_{k,t,q}+\nu_{k,t+\tau}.\]

- **Primary evidence:** \(\gamma_\tau>0\) means vehicle use precedes capital growth; \(\eta_\tau>0\) means capital concentration precedes vehicle-share growth; both are required before describing feedback.
- **Inference:** Driscoll-Kraay errors and calendar-month block bootstrap because five candidates are insufficient for ordinary candidate-cluster asymptotics.
- **Interpretation:** this is predictive feedback, not a causal supply elasticity; causal mechanism evidence comes from Experiment B.

### Experiment B: LP balance-sheet transmission

The unit is provider-address-pool-day. The shift-share shock \(Z^{\mathrm{other}}_{a,-p,t}\) uses lagged token exposures outside focal pool \(p\), excludes both focal-pool tokens, and multiplies those exposures by independently sourced token returns. Pool-date fixed effects compare providers facing the same pool demand, price path, and fee opportunity:

\[F^{\mathrm{LP}}_{a,p,t+1}=\alpha_{a,p}+\lambda_{p,t}+\beta_Z Z^{\mathrm{other}}_{a,-p,t}+\beta_L L_{a,p,t-1}+\varepsilon_{a,p,t+1}.\]

- **Primary sign:** \(\beta_Z>0\); an adverse outside-portfolio shock should induce relative withdrawal or smaller deposits from the affected provider.
- **First stage and falsification:** \(Z^{\mathrm{other}}\) must predict \(R^{\mathrm{other}}\); future \(Z^{\mathrm{other}}_{a,-p,t+1}\) must not predict day-\(t\) flow; results must survive excluding contract-managed positions without reliable controller look-through.
- **Dynamics:** replace next-day flow with cumulative \(F^{\mathrm{LP}}\) over 7 and 30 days and test whether losses have a larger absolute effect than gains using a prespecified zero split.
- **Inference:** two-way clustering by provider and date; address-pool fixed effects and pool-date fixed effects are mandatory.
- **Pool propagation:** estimate \(\Delta_1\ln(\mathrm{TVL}_{p,t+1})=\alpha_p+\delta_t+\beta_W\mathrm{LPWealthShock}_{p,t}+\varepsilon_{p,t+1}\); \(\beta_W>0\) shows that shocks to the incumbent provider portfolio reach aggregate pool liquidity, linking the address-level result to the Clark-Joseph and Comerton-Forde market-quality channel.

### Experiment C: vehicle commonality after removing shared providers

Estimate the pool-candidate-day commonality regression with leave-one-out factors:

\[\Delta_1\ln(\mathrm{TVL}_{p,t})=\alpha_{p,k}+\delta_{\mathrm{month}(t)}+\theta_V\mathrm{VehicleLiquidityFactor}_{p,k,t}+\theta_M\mathrm{MarketLiquidityFactor}_{p,t}+\omega\bigl(\mathrm{VehicleLiquidityFactor}_{p,k,t}\times\mathrm{VehicleShare}_{k,t-1}\bigr)+\varepsilon_{p,k,t}.\]

- **Shared-provider decomposition:** estimate once on all linked pools, once after excluding pool pairs with material \(\mathrm{LPOverlap}_{p,p',t}\), and once after constructing the vehicle factor only from capital supplied by addresses absent from the focal pool.
- **Demand-network evidence:** \(\theta_V>0\) and \(\omega>0\) after the shared-provider exclusions imply vehicle-linked commonality beyond market liquidity and common LP balance sheets.
- **Supply-network evidence:** coefficients that disappear when shared providers are removed attribute commonality to intermediary balance sheets rather than a vehicle-demand multiplier.

### Experiment D: gross and net LP rents

In the provider-pool panel, estimate \(\mathrm{LPFeeYield}_{a,p,t}\), \(\mathrm{LVR}_{a,p,t}\), and \(\mathrm{LPNetReturn}_{a,p,t}\) as separate outcomes against lagged \(\mathrm{VehicleRouteShare}_{p,k,t-1}\), with address-pool and date fixed effects, lagged active capital, pair volatility, and fee tier held fixed.

- **Rent capture:** a positive vehicle-route-share coefficient for fee yield shows gross LP revenue; a positive coefficient for net return shows LPs retain the rent after adverse selection and gas.
- **User capture:** RQ1's lower \(C^I\) measures trader benefit; lower user cost together with higher LP net return is a positive-sum liquidity multiplier.
- **Centrality curse:** higher vehicle-route share raises fee yield and LVR but lowers or fails to raise net return; the vehicle attracts volume while competition or adverse selection dissipates LP rents.

### Decision rule for RQ2

Use the phrase **liquidity multiplier** only if vehicle use predicts future capital \((\gamma_\tau>0)\), the vehicle commonality factor survives market and shared-provider controls \((\theta_V,\omega>0)\), and LP supply responds in the predicted direction to outside wealth shocks \((\beta_Z>0)\). If only the reverse projection is significant, report liquidity selection rather than feedback. If commonality vanishes after provider-overlap removal, report a shared-intermediary capital channel rather than a vehicle-demand externality. Gross fee yield never answers who benefits without LVR and net return.

**Potentially surprising result:** vehicle centrality can increase trader liquidity and gross LP fees while reducing LP net return, so the network grows even though the marginal provider does not capture the apparent rent.

## RQ3. Does vehicle dominance exhibit hysteresis and abrupt displacement?

### Literature anchors

| Anchor | Existing result or mechanism | Relationship to RQ3 |
|---|---|---|
| Krugman (1980) | Vehicle use is self-reinforcing, may persist after the original commercial advantage disappears, and can switch abruptly when declining volume raises cost | **Direct test:** condition on current all-in cost and liquidity, then test persistence and nonlinear displacement; **refute** abrupt-transition content if responses are smooth and reversible |
| Dowd and Greenaway (1993) | Network externalities interact with direct switching costs such as learning, accounting, and requoting | **Narrow the mechanism:** algorithmic routing largely removes user learning and requoting costs, so residual persistence points toward liquidity-capital coordination, integration, or router constraints rather than household-style switching cost |
| Gopinath and Stein (2021) | Complementarities between invoicing and safe-asset/banking demand can entrench a dominant currency; medium-of-exchange use is not the modeled margin | **Expand and delimit:** provide direct medium-of-exchange evidence without claiming to test their invoicing/banking model |
| Somogyi (2026) | Current spread and price impact can make vehicle execution optimal | **Control benchmark:** hysteresis requires persistence after exact current route economics, not merely continued cost superiority |

### Experiment A: persistence conditional on current economics

For common-support pair-candidate-days, estimate exact future horizons \(\tau\in\{7,30,90\}\):

\[\mathrm{VehicleShare}_{i,o,k,t+\tau}=\alpha_{i,o,k}+\lambda_{i,o,t}+\rho_\tau\mathrm{VehicleShare}_{i,o,k,t}+\beta_\tau\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}+\gamma_\tau\mathrm{LPConc}_{k,t}+\chi_\tau\mathrm{CandidateStress}_{k,t}+\varepsilon_{i,o,k,t+\tau}.\]

- **Primary evidence:** \(\rho_\tau>0\) and economically material after all-in cost, liquidity, availability, and stress controls; pair-date fixed effects compare candidates for the same endpoints and date.
- **Hysteresis bar:** persistence alone is not called hysteresis. Hysteresis additionally requires incumbent status to predict future choice among observations matched tightly on current \(\Delta C^{D,\mathrm{all}}\), \(\mathrm{LPConc}\), availability, and stress, plus asymmetric displacement in Experiment B.
- **Inference:** two-way clustering by pair-candidate and date; exact calendar horizons only.

### Experiment B: challenger-edge crossings and switching thresholds

The incumbent \(k^\star\) uses only the 30 days ending at \(t-1\); the challenger \(h^\star\) is the nonincumbent with the lowest current all-in indirect cost. The primary outcome is \(\mathrm{VehicleSwitch}_{i,o,q,t,\tau}\), and the continuous companion outcome is the incumbent's future share change.

\[\mathrm{VehicleSwitch}_{i,o,q,t,\tau}=\alpha_{i,o}+\delta_t+f\bigl(\mathrm{ChallengerCostEdge}_{i,o,q,t}\bigr)+\kappa_L\bigl(\mathrm{LPConc}_{h^\star,t}-\mathrm{LPConc}_{k^\star,t}\bigr)+\kappa_S\mathrm{CandidateStress}_{k^\star,t}+\varepsilon_{i,o,t+\tau}.\]

- **Functional form:** report a continuous linear term, fixed bins with knots at 0, 25, 50, 100, and 200 basis points, and a local event study around the first crossing above zero that remains positive for three consecutive days; knots are fixed before estimation.
- **Abrupt displacement evidence:** switching probability or incumbent share loss is flat near zero but rises sharply beyond an economically material challenger edge; event leads must be flat.
- **Asymmetry evidence:** estimate the mirror sample after a switch; if the former incumbent requires a larger cost edge to regain share than the challenger required to win it, the path matters.
- **Stress channel:** incumbent stress should raise switching and challenger stress should lower it; a placebo assigning the shock after the outcome window must be null.

### Decision rule for RQ3

| Finding | Answer |
|---|---|
| \(\rho_\tau>0\), matched incumbency remains predictive, and switching is threshold-like/asymmetric | Vehicle dominance exhibits hysteresis consistent with liquidity coordination and Krugman-style increasing returns despite low user-side switching cost |
| \(\rho_\tau>0\) but switching responds smoothly and symmetrically | Vehicle status is persistent but the evidence does not establish hysteresis or catastrophic displacement |
| Lagged status loses significance after current all-in cost and liquidity | Apparent persistence is explained by continuing economic superiority, supporting the current-cost channel rather than path dependence |
| Candidate stress moves share before the event or only contemporaneously | Do not interpret stress as displacement; resolve anticipation, timestamping, or common-shock confounding |

**Potentially surprising result:** an incumbent can retain most route share while being measurably more expensive, then lose dominance abruptly after a small additional challenger advantage even though routers can switch without human learning or accounting costs.

## RQ4. Does liquidity-enhancing execution technology decentralize exchange or entrench the vehicle?

### Literature anchors

| Anchor | Existing result or mechanism | Relationship to RQ4 |
|---|---|---|
| Hendershott, Jones, and Menkveld (2011) | Staggered NYSE autoquote provides an instrument for algorithmic trading; automation narrows spreads and reduces adverse selection for large stocks | **Empirical template and corroboration target:** test whether a trading technology improves execution, but add network topology as an outcome; acknowledge that the global V3 launch is weaker than their staggered instrument |
| Chen and Duffie (2021) | Fragmentation lowers per-venue depth, while order splitting can improve allocation and information aggregation | **Competing theory:** improved aggregate execution need not imply less concentration or deeper bilateral markets |
| Caparros, Chaudhary, and Klein (2024) | Lower gas costs instrument for more precise LP repositioning; concentration rises and small-trade slippage falls | **Expand:** move from within-pool concentration and slippage to direct-versus-vehicle route structure and candidate concentration |
| Lehar and Parlour (2024) | Pool size and execution reflect fee revenue, volatility, liquidity-trader demand, and adverse selection | **Narrow:** use pre-V3 pair volatility to distinguish where concentrated liquidity should be most effective, then observe whether gains accrue to direct pools or vehicle spokes |
| Bessembinder, Hao, and Zheng (2020) | A targeted liquidity-provision contract improves market quality beyond the treated venue | **Corroborate or refute strategic complementarity:** test whether technology-induced depth propagates across vehicle-linked pools rather than only reallocating liquidity |

### Experiment A: fixed-universe heterogeneous V3 event study

- **Universe:** \(\mathcal P^{\mathrm{V3}}_q\) is selected only from the fixed 180-day pre-period and quoted throughout event months \(-12\) to \(+12\), independent of post-V3 activity.
- **Treatments fixed before launch:** \(\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}\) measures missing pre-V3 direct execution; \(\sigma^{\mathrm{pre}}_{i,o}\) measures pair volatility and therefore suitability for narrow concentrated-liquidity ranges.
- **Outcomes:** estimate separately for \(D_{i,o,q,t}\), \(\mathrm{DirectDepth}_{i,o,q,t}\), \(\mathrm{AnyIndirectAvailable}_{i,o,q,t}\), \(\mathrm{IndirectRouteShare}_{i,o,t}\), and \(\mathrm{VehicleHHI}_{i,o,t}\); at pool level, estimate \(\mathrm{LiquidityConcentration}_{p,t,b}\).

\[Y_{i,o,t}=\alpha_{i,o}+\delta_t+\sum_{\mu\ne-1}\beta_\mu\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}\mathbf{1}_{\{t\in\mu\}}+\sum_{\mu\ne-1}\gamma_\mu\sigma^{\mathrm{pre}}_{i,o}\mathbf{1}_{\{t\in\mu\}}+\sum_{\mu\ne-1}\theta_\mu\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}\sigma^{\mathrm{pre}}_{i,o}\mathbf{1}_{\{t\in\mu\}}+\varepsilon_{i,o,t}.\]

- **Inference:** pair and date fixed effects; two-way clustering by ordered pair and calendar week; event month \(-1\) omitted.
- **Diagnostics:** joint pretrend tests; placebo launch dates; fixed 12- and 24-month windows; balanced quote-coverage audit; V2-only, V3-only, and best-across-versions route construction shown separately; no failed fetch is coded as route unavailability.
- **Capital-efficiency mechanism:** V3 should raise \(\mathrm{LiquidityConcentration}_{p,t,b}\) and executable depth most for lower-\(\sigma^{\mathrm{pre}}\) pairs if narrow ranges are the operative channel.

### Experiment B: where the execution gain goes

Decompose each pair's post-V3 depth gain into its direct pool and the two pools on its best indirect route, using the same \(q\) and historical state. Then estimate the event design separately for direct depth, first vehicle-spoke depth, second vehicle-spoke depth, pair indirect share, and pair vehicle HHI.

- **Decentralization pattern:** direct depth and availability rise, \(\mathrm{IndirectRouteShare}\) falls, and \(\mathrm{VehicleHHI}\) falls or remains unchanged.
- **Entrenchment pattern:** vehicle-spoke depth rises more than direct depth, and both \(\mathrm{IndirectRouteShare}\) and \(\mathrm{VehicleHHI}\) rise.
- **Strategic-complementarity pattern:** both vehicle spokes deepen together and the gain survives excluding pools with shared LP addresses; this parallels off-venue spillovers in Bessembinder, Hao, and Zheng rather than simple capital migration.
- **Reallocation pattern:** one spoke gains exactly as another loses and aggregate all-in cost does not improve; do not call this a liquidity expansion.

### Decision rule for RQ4

RQ4 is answered by the joint execution-quality and topology response, not by a post-V3 slippage coefficient alone. Better execution with lower indirect share and lower vehicle HHI is decentralization. Better execution with higher indirect share and higher vehicle HHI is technological entrenchment. Better execution with unchanged topology is a capital-efficiency result without a vehicle-currency result. Differential pretrends, quote-coverage imbalance, or sensitivity to placebo dates block causal language; in that case the evidence is reported as heterogeneous event-time association.

**Potentially surprising result:** V3 can improve aggregate execution and direct-pool depth while simultaneously increasing vehicle concentration because the same technology is even more productive on low-volatility vehicle spokes.

## RQ5. Does net settlement sever transactional intermediation from physical settlement and market-making capital?

### Literature anchors

| Anchor | Existing result or mechanism | Relationship to RQ5 |
|---|---|---|
| Gopinath and Stein (2021) | Dominant-currency invoicing and safe-asset/banking demand reinforce each other; medium-of-exchange use is not explicitly modeled | **Expand and set a boundary condition:** test whether an asset remains the economic route intermediate when physical settlement demand collapses; this is not a refutation of their invoicing model |
| Grossman and Miller (1988); Ho and Stoll (1981) | Intermediation requires finite risk-bearing and inventory capacity | **Support or refute a capital channel:** if netting reduces settlement movement but LP capital remains necessary, transactional intermediation is separable from physical inventory transfer but not from market-making capital |
| Brunnermeier and Pedersen (2009) | Funding conditions and market liquidity reinforce each other | **Expand:** test whether lower settlement overhead changes vehicle turnover and LP supply without removing exposure to adverse selection or funding shocks |
| Comerton-Forde et al. (2010) | Market-maker income and inventory shocks predict future liquidity | **Empirical anchor:** carry the LP wealth-shock design into the V4 event and test whether net settlement attenuates balance-sheet sensitivity |
| Hendershott, Jones, and Menkveld (2011) | Trading technology can improve user liquidity while changing liquidity-provider revenue | **Rent-incidence anchor:** compare user all-in cost, gross LP fee yield, LVR, and net LP return after settlement technology changes |

### Accounting premise to test, not assume

V4 flash accounting can reduce intermediate ERC-20 transfers and route gas, but it does not automatically lower the swap fee charged by either pool. An economic \(i\to k\to o\) route still executes both pool swaps, and both LP sets earn their applicable swap fees unless a particular pool or hook changes that rule. Netted intermediate balances therefore motivate an empirical test of physical movement and LP supply; they do not imply that the intermediate LP earns nothing.

### Experiment A: receipt-audited V3/V4 gross-to-net comparison

- **Classification order:** identify ordered endpoints, intermediate \(k\), both swap legs, and protocol version from calls and swap events before reading transfer logs.
- **Sample:** route units in cells \(g\) matched on ordered pair, vehicle, UTC week, fixed route-size bin, and route direction; show full V3/V4 coverage before restricting to cells with both versions.
- **Outcomes:** \(\mathrm{Transfer}_{r,k}\), \(M_{r,k}\), \(\mathrm{SettlementIntensity}_{r,k}\), indirect gas contribution \(C^{I,\mathrm{gas}}_{i,o,k,q,t}\), and all-in indirect cost \(C^I_{i,o,k,q,t}\).

\[Y_{r,k}=\alpha_g+\beta_{\mathrm{V4}}\mathrm{V4}_r+\varepsilon_{r,k}.\]

- **Primary signs:** \(\beta_{\mathrm{V4}}<0\) for transfer incidence, physical movement, settlement intensity, and gas contribution; the sign for all-in indirect cost should be negative if the settlement saving reaches users.
- **Validation:** exact token contracts rather than tickers; wrapped/proxy resolution; exclusion of mint/burn addresses; route-attributed transfer matching; reconciliation of \(M_{r,k}\) to \(\mathrm{GrossLegVol}_{r,k}\); stratified manual receipt audit; one-route-per-transaction robustness.
- **Hook separation:** the primary accounting sample separates pools whose hooks or dynamic fees alter swap cash flows from vanilla swap accounting; hook-bearing routes are reported by economic function rather than pooled into the V4 coefficient.
- **Inference:** two-way clustering by comparison cell and week; report raw matched means and the fixed-effect coefficient.

### Experiment B: does netting expand economic vehicle use?

Use a fixed pair universe and predetermined \(\mathrm{PreV4IndirectShare}_{i,o}\). Estimate an exposure event study around \(t^{\mathrm{V4}}_0\) for \(\mathrm{IndirectRouteShare}_{i,o,t}\), \(\mathrm{VehicleHHI}_{i,o,t}\), and the cheapest \(\Delta C^{D,\mathrm{all}}\):

\[Y_{i,o,t}=\alpha_{i,o}+\delta_t+\sum_{\mu\ne-1}\beta_\mu\mathrm{PreV4IndirectShare}_{i,o}\mathbf{1}_{\{t\in\mu\}}+\varepsilon_{i,o,t}.\]

- **Heterogeneity:** estimate separately by fixed route-size bin because gas savings are a larger fraction of small trades; show V4 availability and \(\mathrm{V4RouteShare}_g\) so treatment intensity is not inferred from the calendar alone.
- **Expansion channel:** physical settlement and gas fall while indirect share or vehicle HHI rises, especially for smaller routes.
- **Pure virtualization:** physical settlement falls but route shares and all-in cost do not move.
- **Contraction channel:** physical settlement falls and indirect route use also falls, consistent with V4 making direct pools relatively more attractive or changing LP allocation.
- **Identification limit:** activation is a global event and actual pool migration is endogenous; without a valid instrument, the pair event study supports a differential exposure interpretation, not an unconditional causal V4 claim.

### Experiment C: does netting encourage or discourage liquidity provision?

The unit is pool-candidate-day. Treatment intensity is predetermined \(\mathrm{VehicleRouteExposure}^{\mathrm{pre}}_{p,k}\), and the event coefficient is its interaction with \(\mathrm{PostV4}_t\). Estimate separate outcomes for total active capital \(\sum_aL_{a,p,t}\), net LP flow \(\sum_aF^{\mathrm{LP}}_{a,p,t}\), \(\mathrm{LPFeeYield}_{a,p,t}\), \(\mathrm{LVR}_{a,p,t}\), \(\mathrm{LPNetReturn}_{a,p,t}\), and \(\mathrm{VehicleTurnover}_{k,t}\), with pool and date fixed effects and event-time leads.

\[Y_{p,k,t}=\alpha_{p,k}+\delta_t+\beta_{\mathrm{LP}}\bigl(\mathrm{VehicleRouteExposure}^{\mathrm{pre}}_{p,k}\times\mathrm{PostV4}_t\bigr)+\varepsilon_{p,k,t}.\]

- **Encouragement:** exposed pools receive positive net flow or capital, fee yield/net return do not deteriorate, and vehicle turnover rises; lower settlement overhead expands route demand enough to attract supply.
- **Discouragement:** exposed pools lose capital or net return despite stable or rising vehicle volume; netting raises capital efficiency or competition so fewer LP dollars are needed, or adverse selection dominates fee gains.
- **No LP effect:** physical movement collapses while LP capital, fee yield, and route use remain stable; settlement balances were not the economically relevant source of LP demand.
- **Capital remains binding:** the RQ2 outside-wealth-shock coefficient remains strong after V4 even though settlement intensity falls; net settlement severs token movement but not market-making balance-sheet dependence.

### Decision rule for RQ5

RQ5 has three separable answers. Experiment A establishes whether economic vehicle use can occur with less physical token movement. Experiment B establishes whether netting expands or contracts route intermediation. Experiment C establishes whether LP capital and rents remain tied to that intermediation. Do not collapse these into a single transfer-incidence result, and do not infer lower LP fees from netting.

**Potentially surprising result:** V4 vehicle volume and both pools' fee revenue can rise while observable intermediate-token movement collapses, demonstrating that transactional centrality, physical settlement, and market-making capital are distinct margins.

## Data acquisition and durable implementation after approval

| RQ | Required acquisition or reconstruction | Durable artifact after approval |
|---|---|---|
| RQ1 | Historical pool state, direct and via-\(k\) quote replay at fixed and observed sizes, route gas usage, block gas prices, token prices, and deterministic cost decomposition | Language-native route-cost panel plus TeX/PDF frontier and route-choice exhibits |
| RQ2 | V3 NFT/position events, position ownership/controller history, pool states, fee growth, tick paths, transaction gas, independent token returns, and provider portfolios | Language-native address-pool-day panel plus TeX/PDF multiplier, shock, commonality, and rent exhibits |
| RQ3 | Pair-candidate route shares, all-in incumbent/challenger costs, exact horizons, candidate prices, and stress events | Language-native incumbent-challenger event panel plus TeX/PDF persistence and displacement exhibits |
| RQ4 | Balanced pre/post V2 and V3 pool states, fixed pair universe, endpoint prices, direct and spoke quote replay, and pool liquidity distributions | Language-native architecture panel plus TeX/PDF event-study and topology exhibits |
| RQ5 | V4 deployment metadata, calls, swap events, ERC-20 transfer receipts, V3 matched routes, V4 pool states, gas, LP positions, fees, and V4 availability | Language-native route-receipt and pool-event panels plus TeX/PDF settlement, adoption, and LP-capital exhibits |

## Review decisions before execution

- [x] **LOCKED BY NODE E, 2026-08-07** — the five-RQ menu is narrowed for the current paper: vehicle transition leads, rent incidence is the mechanism, exact-state direct dominance is the foundation, routing maturation is the first rival, persistence/hysteresis is withheld, and V4 settlement remains an extension.
- [x] **DELEGATED, decided 2026-08-06, Java may veto** — approve the distinction between quote-output cost and all-in route cost, including the fee/price-impact/gas audit decomposition.
- [x] **DELEGATED, decided 2026-08-06, Java may veto** — approve the RQ1 fixed notionals and use of observed transaction size for route-level validation.
- [x] **DELEGATED, decided 2026-08-06, Java may veto** — approve the RQ2 provider-controller look-through rule, outside-token shift-share shock, and fee/LVR/net-return decomposition.
- [x] **DELEGATED, decided 2026-08-06, Java may veto** — approve RQ3 horizons \(7/30/90\), the three-day persistent edge crossing, and fixed challenger-edge knots \(0/25/50/100/200\) basis points.
- [x] **DELEGATED, decided 2026-08-06, Java may veto** — approve the bounded interpretation of the global V3 and V4 event studies; neither is presented as equivalent in strength to a staggered instrument or regression discontinuity.
- [x] **LOCKED BY NODE E, 2026-08-07** — RQ5 is an extension. It does not enter the main claim family unless node I shows that the narrower paper cannot meet the venue bar without it.

## Approval gate (replaces the former execution hold)

Java lifted the execution hold on 2026-08-06 and delegated approval, on the grounds that she asked for an agentic graph and the gate should therefore be enforced by the graph rather than by her inbox. The hold had become a defect in its own right: it blocked on seven checkboxes of which only two needed her, and it tripped every agent that read this file while empirical work proceeded anyway under her live instruction.

What replaces it is stricter in substance and cheaper for Java. Approval requires passing an adversarial self-check against the golden standard she named, published JFE papers, a corpus of which sits in `literature/papers/`. A specification is approved when independent reviewer agents, each reading the corpus directly rather than a summary of it, cannot show that the choice would be rejected at that venue. Reviewers are instructed to try to reject rather than to confirm, because a reviewer asked to check conformance will find it.

Division of rights, stated so the gate cannot silently expand:

- **Java's, and only Java's.** The title, now decided as "The Making of Dominant Vehicle Currencies: Evidence from DeFi". Whether the paper stays a pure-empirics lane. Which results lead. Whether RQ5 is a main RQ or an extension.
- **Delegated, decided in this document with reasoning, and vetoable by Java in one sentence.** RQ1 fixed notionals. RQ3 horizons, the persistent-edge crossing, and the challenger-edge knots. The quote-output versus all-in cost distinction and its fee, price-impact and gas decomposition. The RQ2 provider-controller look-through rule and the shift-share construction. The bounded reading of the V3 and V4 event studies.

Every delegated choice carries its reasoning where it is specified, so a veto costs Java a sentence rather than a re-derivation.

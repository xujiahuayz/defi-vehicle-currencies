# Research questions and empirical design

This note explains the current paper design. The executable definitions are in
[`../specifications/confirmatory.json`](../specifications/confirmatory.json), and
the current numerical results are in [`../findings/`](../findings/README.md).
Ideas that are not in those two places are future work, not unfinished parts of
the present paper.

## Current expansion agenda

The executable gate is green for the two registered baseline families, but the
research target is now stronger than measurement. The open mode is parallel:
keep a presentable paper and deck, send versioned review snapshots when useful,
and continue mechanism search, input building, experiments, and comment response
at the same time. A weak, merely measurable, or literature-incremental result
loops back to more search; it does not stop the paper and slides from being
rebuilt.

Priority experiments:

1. Making of vehicle dominance: estimate which asset, market, and route features
   predict vehicle adoption, dominance intensity, leader switches, entry, exit,
   reversals, and persistence. Preferred designs condition on the same ultimate
   pair and date when feasible, so the comparison is among candidate vehicles in
   the same trading opportunity.
2. Liquidity-provision behavior: separate capital stocks from liquidity-supply
   flows, provider entry/exit, withdrawals, reallocation across vehicles, and
   V3/V4 route or netting behavior where the required inputs exist.
3. Mechanism distinction: compare route cost, executable depth, venue coverage,
   route redundancy, candidate centrality, pool age, and capital concentration
   as competing explanations. Correlations are admissible when causal evidence
   is not defensible, but each result must state the unit, conditioning set,
   strongest rival, and economic magnitude.
4. Framing: motivate the paper with concrete traditional-finance analogies, such
   as a dealer or treasurer routing a thin currency pair through a liquid vehicle
   currency because direct execution is expensive or unavailable. The analogy is
   motivation only; it should not substitute for the DEX evidence.

Draft rule: provisional results may enter the paper and deck if they are clearly
labelled and rebuildable enough for review. Claim-status upgrades are separate:
a result becomes headline evidence only if it is economically material, survives
a serious rival explanation, clarifies the contribution relative to the
literature, and can be rebuilt from declared inputs. If those conditions are not
met, the workflow loops back to mechanism search and additional experiments
while the current draft remains presentable.

## Question and contribution

The paper asks what makes a vehicle currency dominant and how that dominance
changes. Decentralized exchange is the empirical setting because a transaction
records the assets and pools used along its path. It lets us observe a currency
role that conventional pair-level turnover data usually leave latent.

The main contribution is a distinction between two margins:

1. substitution within an ultimate pair, where traders change the intermediary;
2. composition across ultimate pairs, where activity reallocates toward markets
   that already use one intermediary more heavily.

For `A → B → C`, `A → C` is the **ultimate trade** or **ultimate pair** and
`A → B` plus `B → C` are the **atomic trades** or **atomic pairs**. A route is
one reconstructed input-to-output component, not one atomic swap record.

## Measurement

An asset has vehicle status on a route when it is an intermediary rather than an
ultimate endpoint. Vehicle dominance is the degree of that use. The paper reports
both the intermediary share and excess use relative to the asset's endpoint share.
Cost domination is a separate direct-versus-indirect execution comparison.

Route counts are primary because topology is observed more broadly than reliable
dollar value. Value-weighted results are secondary and require source,
intermediary, and destination valuations to agree within 20 percent. Raw values,
coverage, and a wider twofold agreement band remain diagnostics. Canonical
endpoint round trips are excluded from economic-exchange denominators.

## Confirmatory family 1: Vehicle-role rotation

The first family compares the stablecoin share of native-plus-stable
intermediaries in 2024 and 2026 on common January-to-June dates.

- Unit: ordered ultimate pair × date × observed integration scope.
- Main coefficient: the 2026 indicator with ultimate-pair × month-day × scope
  fixed effects.
- Weights: the applicable native-plus-stable route mass.
- Inference: two-way clustering by ultimate pair and date, with Holm adjustment
  across the three registered count/value measures.
- Interpretation: descriptive within-market substitution. Calendar time is not a treatment,
  and realised cross-venue routing is not assigned integration.

The aggregate change is then decomposed into within-common-pair substitution,
reweighting across continuing pairs, common-support mass, and entry/exit-pair
composition. The terms must add exactly to the pooled change. This decomposition
is the paper's central empirical result.

Supporting evidence separates native, fiat-backed, crypto-backed, and hybrid
intermediaries; decomposes USDT excess use; and reports single-venue versus
cross-venue routes and route-complexity cells. These splits test rival composition
stories but do not turn the design causal.

## Confirmatory family 2: V2 deposited-capital predictability

The second family asks whether vehicle use and deposited capital predict one
another within the Uniswap V2 and SushiSwap V2 constant-product family.

- Unit: candidate token address × origin calendar day.
- Candidates: WETH, WBTC, DAI, USDC, and USDT, identified by address.
- Inputs: the all-route vehicle-use panel and candidate-attributed deposited
  capital constructed from validated pool reserves.
- Horizons: exact 1, 7, 30, and 120 calendar days; missing dates remain missing.
- Fixed effects: candidate and origin date.
- Interpretation: predictive association, not causal feedback.

The registered claim requires a positive reciprocal pattern at multiple primary
horizons after multiple-testing adjustment and no contradictory long-horizon
reversal. The paper reports the result at that decision rule rather than selecting
the most favorable coefficient.

Deposited capital is the externally valued capital assigned once across linked
candidates. It is not candidate inventory, marginal depth, executable depth,
quote quality, liquidity-provider profit, or rent.

## Supporting routing analyses and architecture context

The Uniswap V1-to-V2 architecture change supplies institutional evidence. V1
mechanically forced token-to-token ultimate trades through ETH; V2 allowed direct
ERC20 pairs. V1 therefore demonstrates forced vehicle status, while continued
WETH pairing after V2 is descriptive evidence about persistence after the mandate
was withdrawn. It does not identify the later stablecoin transition.

Routing-technology windows, cross-venue routing, route complexity, quote-support
bounds, and venue-coverage bounds discipline alternative explanations. Public
release dates are descriptive windows because executor identity does not reveal
who authored a route and market composition changes at the same time.

## Boundaries

- Architecture availability, adoption, market formation, substitution, and
  reversal are different objects.
- Counts and values answer different questions and are never silently pooled.
- Unsupported values stay visible through coverage rather than being imputed.
- Symbols label assets; contract addresses establish identity.
- Causal language requires treatment timing, balance, pretrends, exclusion, and
  placebos appropriate to the claimed mechanism.
- Withheld direct-cost, rent-incidence, joint V2/V3 flow, and hysteresis branches
  are outside the current paper unless they receive a new specification and a
  complete producer-to-deliverable path.

# Revision plan from the annotated manuscript

Status: active revision map for the paper and deck. This document records the
classes of changes implied by the full annotated review. It is not a
comment-by-comment response letter.

## Benchmark and objective

The primary structural benchmark is Huang, Ranaldo, Schrimpf, and Somogyi,
"Constrained liquidity provision in currency markets," *Journal of Financial
Economics* (2025), retained in `literature/papers/`. The wider fourteen-paper
JFE corpus in `literature/audit.md` remains the language, exhibit, and inference
guard. The benchmark calls for an economic problem first, a compact definition
of the new measure, early magnitudes, a small number of main findings, and
mechanism tests that discriminate among plausible explanations.

The revision objective is not to make every annotation disappear locally. It is
to make the paper answer three connected questions:

1. How does a vehicle currency acquire aggregate dominance?
2. How do endpoint-pair formation, network reach, and local liquidity divide
   that change between new trading relationships and switching inside existing
   relationships?
3. What do these results imply for the liquidity providers and payment systems
   that must make cross-currency exchange possible?

## Current disposition

Completed in the rolling manuscript and deck: the economic FX-provider opening,
the DeFi subtitle, the sub-100-word abstract, endpoint-pair and leg terminology,
the compact pair decomposition, conventional regression equations and table
notes, the matched-window labels, and a core V4 liquidity-provider result. The
rendered PDFs remain tracked review artifacts.

The prior tightening and liquidity-section reviews are complete. The four
endpoint directions are now collected in one exact decomposition, with a
separate issuer split showing that USDT accounts for the stable-to-stable value
channel. Persistent stable-bridge support is now dated against first use of a
stablecoin in the event's exact support set, and event-day depth separates
shallow availability from subsequent adoption. The pre-use capital path now
separates newly capital-positive pools from scaling inside pools active one week
earlier, with a matched WETH comparison and multiplicity-adjusted inference.
Issuance remains outside the local data perimeter. The disconnected-component
boundary is now quantified, including its V4 concentration and a component-as-route
sensitivity that slightly strengthens the aggregate rotation. Each major revision follows the decision rule in
[`writing-and-rhetoric.md`](writing-and-rhetoric.md) before implementation.

## Annotated review checkpoint: 21 August 2026

The comments in Java's annotated `main 3.pdf` have been consolidated here so
the Studio revision does not depend on access to the local PDF. They imply the
following document-wide changes, not isolated word replacements:

- Explain the decomposition in ordinary language before the identity: net
  vehicle switching within continuing pairs, reweighting among continuing
  pairs, and pair entry or exit. Keep the numerical contrast easy to locate.
- Give one numerical route-value example and state why the exact two-leg sample
  identifies one mutually exclusive native-versus-stable vehicle choice.
  Longer routes remain evidence through intermediary-position, participation,
  and network measures; they do not replace the exact decomposition because a
  longer route can contain both vehicle families.
- Separate coverage within the retained sources from representativeness of the
  wider Ethereum DEX market. The wider comparison should use historical market
  volume, including DeFiLlama, and must not relabel within-source shares as a
  market census.
- Prefer full-sample validation where computation is feasible. In particular,
  replace the 79-day round-trip estimate with the all-day result and remove
  arbitrary router snapshots unless the dates answer an economic question.
- Show half-year observations so 2024 H1 and 2026 H1 are visible, retain the
  issuer-level stablecoin split and stable-to-stable endpoint analysis, and
  keep the distinction between the stablecoin family and individual dollar
  claims explicit.
- Define indicators with conventional subscript notation, use that notation
  downstream, and give regression-table units and standard-error conventions
  once in the appropriate header or note.
- Put a discussion and policy-implications section before the conclusion. The
  conclusion synthesizes admitted findings and the market-formation implication;
  motivation belongs at the front of the paper and talk.
- Replace appendix result dumps with grouped economic questions and connect
  each group to the main result it qualifies or extends.

Draft source changes on the M3 already cover the numerical route example,
two-leg rationale, decomposition walkthrough, half-year plotting input,
indicator notation, full-sample round-trip program, separate discussion
section, and corresponding deck/transcript language. These are a checkpoint,
not a completed revision. Studio must rebuild them on the unified V1-inclusive
panel, update every dependent exhibit and quoted number, inspect the rendered
paper and every slide, and then iterate paper, deck, and transcript until their
terminology, evidence, and emphasis agree.

Two points remain deliberate boundaries. Dollar-pegged tokens stay distinct at
the token level because issuer, redemption, and pool-liquidity differences are
economically meaningful, while family-level results remain the headline.
Multi-leg routes broaden the network evidence but cannot be assigned a single
native-versus-stable vehicle when both families appear in the same route.

### Studio resume point

Studio is the sole owner of the next compute-and-revision cycle. Its checkout
was fast-forwarded to `6429062` after preserving the newer generated exhibits.
No project computation was running at handoff. Stage 1 stopped in
`scripts/process/build_vehicle_excess_use.py` after writing the daily and
transition outputs because the final status message references undefined
`OUT_QUARTERLY`. The dependent Stage 2, Stage 3, and Stage 4 watchers therefore
exited with their preceding-stage completion marker absent. Repair that name,
rerun the excess-use step, and resume the remaining Stage 1 sequence: token
prices, the all-day round-trip measure, network betweenness, the venue-technology
comparison, and the exact vehicle frontier. Then relaunch Stages 2 through 4.

The early adjacent-year run also stopped when the cross-venue subsample lacked
positive support in an endpoint year. Treat that as a support rule to handle
explicitly, not as a zero. After computation, rebuild every dependent table,
figure, paper value, slide, and transcript number on the unified V1-inclusive
panel. The next writing pass begins with the interpretation and closing-slide
rules in `writing-and-rhetoric.md`; it must also replace visible layout language
such as “card.”

## Economic motivation and contribution

- Open with the foreign-exchange problem faced by a payment provider that does
  not hold the destination currency. Use BIS Project Nexus, Project Rialto, and
  Project Mariana as authoritative examples of third-party FX provision,
  vehicle currencies, and pooled liquidity in prospective cross-border systems.
- Introduce DeFi as the setting in which the complete pool route is observable,
  not as the contribution by itself.
- State the matched January--June 2024 and 2026 comparison immediately and
  define continuing, entering, and exiting endpoint pairs before using them.
- Sell the paper through the aggregate rotation, near-zero net switching inside
  continuing pairs, persistence after pair entry, and the relation between
  local depth and route choice.

## Terminology, estimands, and sample boundaries

- Define **endpoint pair** once as the ordered source and destination, then use
  **pair**. A **leg** is one directed pool execution, a **route** is the observed
  ordered sequence of legs, and a **path** is a feasible or counterfactual
  alternative. All four are directed unless explicitly stated otherwise.
- Explain that ETH and WETH are one economic settlement asset because wrapping
  is a one-for-one technical representation needed for token contracts, while
  reconstruction still occurs at the token-address level.
- Present the 20% value-agreement rule as a data-quality eligibility screen,
  not a control. Count results retain every reconstructed route; value results
  exclude routes whose token-value accounting does not reconcile. Report
  retained coverage and sensitivity in exhibit notes.
- Recast excess use as intermediation intensity relative to endpoint demand:
  zero means no intermediary use, one means proportional use, and values above
  one mean overrepresentation as a vehicle. It is a role-specialisation measure,
  not the headline dominance ranking.
- Quantify the connected-pool-component limit where the data permit it. The
  PYUSD example must not imply that the broader user instruction is generally
  observed.
- Explain that the 79-day sample validates route construction and round-trip
  prevalence; it is not the support of the core route panel.

## Empirical spine

- Move the pair-composition table directly after its accounting identity.
- Replace the cell-by-cell narrative with two or three result paragraphs:
  aggregate change, continuing-pair switching and reweighting, and pair entry
  and exit. Move named-pair examples, support accounting, WETH-endpoint cuts,
  venue cuts, and detailed cohort arithmetic to the appendix unless they test a
  main rival.
- Collect the four endpoint transitions (stable-to-stable,
  stable-to-native, native-to-stable, native-to-native) in one exhibit or
  compact paragraph instead of scattering them.
- Keep the entry-persistence and network-reach regressions in the main text.
  Move low-information nulls and the USDC/SVB episode to the appendix unless a
  stand-alone event design earns them a main-text role.
- Discuss an exhibit once, immediately after it appears. Do not narrate every
  coefficient that a reader can see in the table.

## Regression presentation

- Put each principal equation before its regression table and cross-reference
  it in the table note.
- Replace workflow labels such as "Specification" and "Margin" with economic
  outcomes or model descriptions. Display coefficients with standard errors in
  parentheses and put fixed effects, weighting, clustering, units, and stars in
  conventional table rows or notes.
- Translate subscripts in ordinary language at first use. Use pair-date-route
  class as the compact observational unit.
- Keep uncertainty in exhibits. Repeat it in prose only when the bound, rather
  than the point estimate, is the economic finding.

## Deck argument

- Replace the abstract bilateral-clearing opener with the cross-border
  liquidity-provider problem, then reveal why a vehicle currency is needed.
- State the matched half-year comparison on the first results slide.
- Keep one decomposition reveal rather than three near-duplicate handout pages.
- Give the PYUSD case a visible data-limit sentence and remove the 20% rule from
  the plot area when it belongs in the note.
- End with the economic implication: new trading relationships inherit a
  vehicle regime, and local liquidity makes that regime contestable or
  persistent.

## Scientific extensions

- The pool-to-route timing test is complete: persistent two-leg support commonly
  precedes stable-vehicle use, event-day depth predicts whether adoption follows,
  and the matched event path shows bridge capital accumulating before first use
  of the supported stablecoin. Pool-level decomposition shows both activation
  and continuing-pool scaling before first use. Stablecoin issuance timing
  remains unmeasured because no verified issuance series is in the local data
  perimeter.
- V4 flash-accounting intensity is linked to subsequent capital, range, and
  position-update outcomes, with same-candidate-date V3 comparisons retained as
  supporting evidence. A new timing split separates actions by transaction
  origins active in the prior 180 days from origins first active later. This
  strengthens the participation evidence without calling transaction origins
  verified LP-position owners. Any stronger supply interpretation still
  requires an exogenous provider-side shift or provider-level identification.
- Persistent 30-day WETH volatility shifts the internal-routing association
  away from near-term incumbent actions and toward first-active origins during
  days 31 to 120. Vehicle-specific and control-specific volatility slopes,
  alternative activity windows, zero-update inclusion, and leave-one-vehicle
  estimates retain the later-entry result. This is state-dependent predictive
  evidence, not an exogenous risk-bearing shock.
- The stable-to-stable, stable-to-native, native-to-stable, and
  native-to-native endpoint directions are separated. The next use of this
  result should test timing or liquidity, not repeat the same composition split.
- Continue systematic specification searches only through registered outcomes,
  fixed effects, support rules, and multiplicity controls. The paper and deck
  remain presentable after every admitted result generation.

## Deliberate pushback

- The 20% value-agreement screen should not be replaced by regression controls.
  A control can absorb observable covariation but cannot turn a misvalued route
  into a valid dollar weight. The right response is transparent eligibility,
  coverage, and sensitivity alongside the unrestricted count result.
- Bare **pair** means the directed endpoint pair after the initial definition.
  Pool-level discussion uses **leg**, pool, or token combination, so the paper
  does not repeatedly rebuild the longer label.
- The PYUSD-to-USDC step cannot be assigned to a vehicle without observing the
  instruction-level execution that produced it. The paper should bound the
  prevalence of disconnected components where possible, but it should not
  infer a missing route from token-transfer proximity alone.
- Confidence intervals belong in tables and figures by default. Removing them
  from repetitive prose improves readability without weakening inference.

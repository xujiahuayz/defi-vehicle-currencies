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
Issuance remains outside the local data perimeter. The open revision class is
to quantify the disconnected-component boundary. Each major revision follows the decision rule in
[`writing-and-rhetoric.md`](writing-and-rhetoric.md) before implementation.

## Economic motivation and contribution

- Open with the foreign-exchange problem faced by a payment provider that does
  not hold the destination currency. Use BIS Project Nexus, Project Rialto, and
  Project Mariana as authoritative examples of third-party FX provision,
  vehicle currencies, and pooled liquidity in prospective cross-border systems.
- Introduce DeFi as the setting in which the complete pool path is observable,
  not as the contribution by itself.
- State the matched January--June 2024 and 2026 comparison immediately and
  define continuing, entering, and exiting endpoint pairs before using them.
- Sell the paper through the aggregate rotation, near-zero net switching inside
  continuing pairs, persistence after pair entry, and the relation between
  local depth and route choice.

## Terminology, estimands, and sample boundaries

- Use **endpoint pair** for the ordered source and destination and **leg** for
  one pool trade. Shorten endpoint pair to pair only where no pool pair is in
  view. Reserve route for the connected execution sequence.
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
  supporting evidence. Any stronger supply interpretation still requires an
  exogenous provider-side shift or provider-level identification.
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
- Bare "pair" cannot be universal because decentralised-exchange readers also
  use pair for the assets in one pool. "Endpoint pair" is the shortest label
  that preserves the distinction; "pair" is safe after local context fixes the
  meaning.
- The PYUSD-to-USDC step cannot be assigned to a vehicle without observing the
  instruction-level execution that produced it. The paper should bound the
  prevalence of disconnected components where possible, but it should not
  infer a missing route from token-transfer proximity alone.
- Confidence intervals belong in tables and figures by default. Removing them
  from repetitive prose improves readability without weakening inference.

# Revision plan from the annotated manuscript

Status: active revision map for the paper and deck. This document records both
the document-wide changes implied by the review and the source-annotation
closure rule. It is not a response letter, but no review can be called complete
without accounting for every annotation in the source PDF.

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

### Source-annotation closure rule

The original annotated PDF, rather than this summary, is the review authority.
At the start of a pass, extract its annotations in page order and record the
source count. Each annotation then receives one disposition: implemented,
declined with a reason, or superseded by a document-wide change that names the
affected sources. “Partly addressed” remains open. After rebuilding, inspect
every affected page in the new PDF and compare the number of dispositions with
the source count. A prose summary, a successful compile, and spot checks cannot
close the pass on their own.

The 21 August source contains 33 annotations. The earlier pass failed this rule:
it revised from a condensed handoff and checked selected pages, so partial work
on market representativeness, the decomposition bridge, plot notes, notation,
and table labels was mistakenly described as complete. This is the recurrence
the rule prevents.

- Explain the decomposition in ordinary language before the identity: net
  vehicle switching within continuing pairs, reweighting among continuing
  pairs, and pair entry or exit. Keep the numerical contrast easy to locate.
- Give one numerical route-value example and state why the exact two-leg sample
  identifies one mutually exclusive native-versus-stable vehicle choice.
  Longer routes remain evidence through intermediary-position, participation,
  and network measures; they do not replace the exact decomposition because a
  longer route can contain both vehicle families.
- Quantify how much intermediary activity lies outside the native and stable
  families and show where the wider intermediary-type results appear. The main
  comparison needs an empirical coverage reason, not “we begin with” language.
- Separate coverage within the retained sources from representativeness of the
  wider Ethereum DEX market. The wider comparison should use historical market
  volume, including DeFiLlama, and must not relabel within-source shares as a
  market census.
- Present Uniswap v1 in the institutional architecture section. The data section
  should state the resulting coverage and reconstruction boundary without
  narrating the re-fetch or other project operations. Label raw pool swaps,
  usable directed legs, transactions, and routes as distinct units.
- Full-sample round-trip validation now covers all 2,449 eligible days. The
  manuscript reports the all-day distribution and no longer relies on arbitrary
  router snapshots.
- Show half-year observations so 2024 H1 and 2026 H1 are visible, retain the
  issuer-level stablecoin split and stable-to-stable endpoint analysis, and
  keep the distinction between the stablecoin family and individual dollar
  claims explicit.
- Develop the stablecoin-supply interpretation without forcing a mechanism
  regression. Growth in stablecoin issuance may create demand for
  stable-to-stable pools. Those pools may also attract capital because
  relative-price variation, and hence impermanent-loss exposure, is smaller
  while both pegs hold. An empirical extension enters only with independent,
  validated issuer-supply and price data. Keep deposited capital, fee income,
  loss-versus-rebalancing, impermanent loss, and provider profitability distinct.
- Use the Bahamian-dollar/US-dollar comparison to discipline the traditional-FX
  analogy. A fixed peg or common dollar numeraire does not erase issuer identity,
  the redemption promise, the liquidity network, or the monetary institution;
  conventional vehicle-currency work would not automatically pool the two
  currencies. Report both the functional stablecoin family and issuer-specific
  token results, and explain which economic question each aggregation answers.
- Define indicators with conventional subscript notation, use that notation
  downstream, and give regression-table units and standard-error conventions
  once in the appropriate header or note.
- Put a discussion and policy-implications section before the conclusion. The
  conclusion synthesizes admitted findings and the market-formation implication;
  motivation belongs at the front of the paper and talk.
- Replace appendix result dumps with grouped economic questions and connect
  each group to the main result it qualifies or extends.
- Inspect the rendered manuscript globally for blank pages, stranded paragraphs,
  float placement, and unused white space. Put sample and construction details
  in table or figure notes when they do not belong in the visual field.
- Treat two-leg depth as one competitive condition, not a sufficient explanation
  for dominance. Route availability, relative all-in prices, pair formation,
  demand, and initial vehicle use remain distinct margins in the interpretation.

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
economically meaningful. Family-level results summarize a shared vehicle
function; issuer-level results preserve the conventional currency analogy and
reveal competition among distinct dollar claims.
Multi-leg routes broaden the network evidence but cannot be assigned a single
native-versus-stable vehicle when both families appear in the same route.

### `main 3.pdf` source ledger

The rebuilt 21 August manuscript closes all 33 source annotations as follows.
“Qualified” records a deliberate boundary rather than an omitted edit.

| No. | Source request | Disposition |
|---:|---|---|
| 1 | Clarify “reallocation” in the abstract | Implemented: the abstract now says activity shifts across continuing pairs. |
| 2 | Avoid implying two-leg liquidity is sufficient | Implemented: depth on both legs is one market condition alongside prices, availability, and formation. |
| 3 | Remove the large blank after the route introduction | Implemented: the route equation and numerical example occupy the page. |
| 4 | Inspect blank space throughout | Qualified: the rebuilt manuscript has no empty page; ordinary float breaks remain where a table must stay intact. |
| 5 | Give a numerical route-value example | Implemented with the hypothetical AAVE--WETH--USDC--UNI route and explicit token and dollar units. |
| 6 | Justify the exact two-leg sample and retain longer routes | Implemented: two legs identify one mutually exclusive vehicle; all route lengths remain in position and participation measures. |
| 7 | Justify and quantify the native-versus-stable focus | Implemented: the two families jointly carry at least 83.8\% of intermediary positions and 76.7\% of supported value in every year from 2020. |
| 8 | Use excess-use notation downstream | Implemented in equations, table notes, and regression discussion; the ratio is explicitly separated from dominance. |
| 9 | Replace the 79-day route summary | Implemented with all 2,449 eligible days. |
| 10 | Remove unnecessary V1 construction detail from the data section | Qualified: retained two concise sentences because V1 belongs to the nine-deployment panel and has a different observable record. |
| 11 | Put V1 only in the architecture section | Declined for the same reason; the economic comparison is in Section 4.2, while the data boundary remains in Section 2.3. |
| 12 | Remove “re-fetch” and related project language | Implemented. |
| 13 | Establish market representativeness, including in the deck | Implemented with a reproducible DeFiLlama comparison: 87.5\% of total Ethereum DEX volume over 2020--2026 H1. |
| 14 | Replace “harmonising” | Implemented with identifying pool events and standardising token units. |
| 15 | Clarify “event identity” | Implemented as pool events. |
| 16 | Distinguish raw swaps, directed legs, transactions, and routes | Implemented in prose and Table 1; no transaction count is inferred from a leg count. |
| 17 | Use all days for route medians | Implemented with all 2,449 eligible days. |
| 18 | State the consequence of incomplete router attribution | Implemented: results are attributed to executed routes, not a named routing service. |
| 19 | Remove or justify the two isolated router snapshots | Implemented by removing them. |
| 20 | Treat stablecoins as distinct issuers and discuss issuance, divergence loss, and the Bahamian-dollar analogy | Implemented in the separate discussion section and issuer-level evidence. |
| 21 | Move the 20\% rule out of the plot | Implemented: the plot text is gone and the rule appears in the figure note. |
| 22 | Plot half-years throughout | Implemented. |
| 23 | Make 2024 H1 and 2026 H1 readable from the plot | Implemented as labelled half-year points. |
| 24 | Explain the pair decomposition step by step | Implemented from the total-share identity through the four terms, including an explicit statement that nothing is deducted from a continuing pair. |
| 25 | Put the indicator condition in a subscript | Implemented. |
| 26 | Remove “sharpens” | Implemented throughout the audience-facing sources. |
| 27 | Remove the announcement defining “stickiness” | Implemented; the paper now states predictive persistence directly. |
| 28 | Remove slash-separated regression headings and cells | Implemented in Table 4 with parentheses for standard errors and clusters. |
| 29 | Use an indicator in Table 4 interactions | Implemented as \(\mathbf 1_{\{y=2026\}}\). |
| 30 | Remove “make visible/feasible/exact” prose | Implemented in audience-facing paper and deck text. |
| 31 | Add discussion and policy implications before the conclusion | Implemented as Section 6. |
| 32 | Put the round-trip condition in the indicator subscript | Implemented. |
| 33 | Organise and interpret appendix results | Implemented with economic subsections, short lead-ins, and main-text cross-references. Weak secondary estimates are not expanded into parallel mini-results sections. |

### Studio resume point

Studio is the sole owner of the current compute-and-revision cycle. Commit
`9c067cd` repaired the retired `OUT_QUARTERLY` completion-message reference.
The V1-inclusive excess-use, half-year, token-price, all-day round-trip,
network-betweenness, cross-venue computations, and the exact vehicle frontier
are complete. Downstream tables, figures, manuscript, deck, and transcript
rebuilds incorporate their outputs.

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
- Explain that the all-day round-trip distribution validates the endpoint
  exclusion; it is not the support of the core route panel.

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
  and continuing-pool scaling before first use. The discussion now treats
  stablecoin issuance and lower stable--stable divergence exposure while pegs
  hold as economic interpretations. The current route-valuation price panel is
  unsuitable for testing that exposure because stablecoin valuation can be
  anchored and historical decimal errors contaminate unfiltered price records.
  A future test requires independent prices, verified issuer supply, provider
  entry dates, fee income, and explicit peg-stress treatment; deposited capital
  alone measures the supplied stock.
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

# Writing and rhetoric guide

Status: live entry point for paper and slide language. Read this before editing
`paper/`, `deck/`, captions, exhibit notes, abstract, introduction, conclusion,
or any audience-facing result text.

This guide consolidates the human rules. The executable checks enforce only the
parts that can be tested mechanically; passing them is not proof that the paper
or slides sound like a JFE article or a finance talk.

## Authority and update rule

1. The root workflow keeps `paper/` and `deck/` presentable while research,
   review, and revisions continue in parallel.
2. This file is the human-facing writing and rhetoric contract.
3. `literature/audit.md` owns paper-level JFE calibration, finding-selling,
   claim scope, and exhibit architecture.
4. `literature/reviews/current/deck-venue-exemplars.md` owns presentation
   rhetoric, pacing, motivation, and conclusion calibration.
5. `literature/reviews/current/deck-visual-composition.md` owns visual-form
   choices for slides.
6. `scripts/verify/check_deliverable_conformance.py` is the one-command
   automated alarm surface for paper/deck handoff.

When a new writing rule is learned, add it here and, if it is mechanically
testable, add it to the verification surface. Do not replace an older rule by
accident. If two standing rules conflict, leave the edit open until Java resolves
the conflict.

## Revision decision rule

Before a major cut, addition, reframing, or new empirical specification, write
down what it is expected to improve: the economic question, identification
against a serious rival, the magnitude or generality of a finding, or the
reader's ability to understand the mechanism. Also identify what the change
would remove or obscure. Make the change only when the expected gain exceeds
that cost. Concision is not an independent objective: institutional intuition,
economic transitions, and mechanism explanations stay when they carry the
argument.

An exploratory regression earns computation only when it has a named economic
hypothesis or rival, a defensible unit and timing convention, an eligible input,
and a stated decision use. A specification grid records the family and controls
multiplicity. Statistical significance alone never promotes a result.

Before a version is called ready, reread the rendered paper and complete core
deck against the primary JFE benchmark and the wider venue corpus. Check the
economic spine, nearby limitations, exhibit order, terminology, prose register,
and every slide boundary visually. Automated checks are alarms; they are not a
substitute for this full-document review.

Apply the repository's resolve-before-caveating rule before drafting a
qualification or mechanism interpretation. A missing field or crosswalk triggers
a fetch or reconstruction. An interpretation with an observable implication
triggers the most direct focused test. Prose retains only the boundary left by
that test: identification, unobserved intent, unavailable external data, or a
genuinely disproportionate extension. Do not add a regression merely to make a
result look formal; choose the design that answers the economic question.

## Shared claim language

- Put the economic object first. The reader should see the actor, market,
  asset, route, pool, provider, quantity, or event before the workflow that
  produced it.
- A paper-facing estimate states its unit, denominator, comparison set,
  conditioning or fixed effects, uncertainty convention, support, strongest
  rival, and economic magnitude.
- A slide-facing result states the result, support, and unresolved alternative
  in ordinary presentation language.
- Keep distinct objects distinct: binary vehicle status, continuous vehicle
  dominance, realised route choice, counterfactual execution cost, deposited
  capital, liquidity-supply flow, inventory, executable depth, provider return,
  leg-level venue formation, pair entry, substitution, exit, reversal, and
  persistence.
- Keep the route vocabulary equally explicit. For an observed exchange
  \(A\rightarrow B\rightarrow C\), \((A,C)\) is the ordered \emph{endpoint
  pair}, the pool executions \(A\rightarrow B\) and \(B\rightarrow C\) are its
  two \emph{legs}, and the full ordered sequence of legs is the \emph{route}.
  A pool is the venue in which a leg executes. Define endpoint pair once near
  the start of each deliverable, then use \emph{pair} unless another kind of
  pair is explicitly introduced.
- Pair, leg, route, and path are directed by token flow unless a passage
  explicitly says otherwise. The pair records the endpoints and direction; the
  route records the observed intervening sequence. Reserve \emph{path} for a
  feasible or counterfactual alternative. Do not use path as a synonym for an
  observed route, and describe persistence from initial vehicle use without the
  loose label “path dependence.” Use compact econometric units such as
  \emph{pair-day} and \emph{pair-date-route class}; do not rebuild the full
  definition inside a unit label.
- Do not append “market” to an endpoint pair unless the text explicitly defines
  a broader market aggregating substitutable direct and indirect routes.
  Reserve corridor for an explicitly bilateral real-economy trade or payment
  relationship, where that term is conventional. These labels keep an endpoint
  relation, its execution sequence, its trading venues, and its settlement
  relationship distinct.
- Use causal verbs only when the design earns them. Otherwise use descriptive,
  predictive, associated, or mechanism-consistent language.
- The paper and deck present an economic argument, not the state of the research
  process. Internal sample-construction nouns, search labels, evidence states,
  provenance, node labels, and review status belong in code, source comments, or
  workflow documents. In reader-facing text, name the economic object, comparison,
  and specification directly. This is a sentence-level translation rule, not a
  synonym list: rewrite the thought when its subject is still the research process.
- Reader-facing prose does not use internal project nouns such as workflow,
  pipeline, node, gate, freeze, claim family, evidence status, producer, generated
  data release, artifact, registry, ledger, or support contract. Replace the underlying thought
  with the market object, sample restriction, estimate, or economic comparison.
- A coverage statement distinguishes a broad protocol-source panel from a
  market census. Name the market designs and venues represented, state the
  material perimeter outside the data, and never relabel shares within observed
  sources as shares of the complete market.
- Provisional, blocked, withheld, unsupported, or retired results may remain in
  source comments and review documents. A result enters reader-facing prose only
  in scientific language that states its design and limitation; workflow status is
  never the limitation shown to the audience.
- Titles, topic sentences, and conclusions state the economic result affirmatively.
  A genuine null or bound remains publishable evidence, but introduce the economic
  benchmark first and quantify the estimate and uncertainty instead of making
  grammatical negation carry the claim.
- Negation in body text earns space only when the excluded alternative or bounded
  effect is itself economically informative. State the affirmative finding first;
  omit unenumerated “but not B, C, or D” contrasts. When a null is load-bearing,
  use conventional statistical language and report the estimate with uncertainty;
  terms such as “statistically clean” describe an internal decision rather than a
  result.
- Descriptive evidence still warrants economic interpretation. State the most
  plausible reading with conventional language such as “suggests,” “is
  consistent with,” or “is indicative of,” then state the narrow remaining
  identification boundary. Do not make “what the evidence cannot tell us” the
  centre of the paragraph merely because motives are unobserved.

## Paper prose

- Write author actions in the first person plural: ``we reconstruct,'' ``we
  estimate,'' ``we find,'' and ``our measure.'' Reserve ``the paper'' for a rare
  organizational pointer whose subject truly is the document. Never make the
  manuscript, table, or research process the actor when the authors, data,
  market, or estimate can carry the sentence. This matches the dominant
  authorial construction in the local JFE comparison corpus.
- A plausible economic channel can remain interpretation. Give its mechanism,
  conditions, and observable implication, and distinguish it from quantities
  already measured. Add an empirical exercise only when the available data
  measure that implication directly; a mechanically anchored proxy or a formal
  regression with the wrong economic object weakens the argument.
- The paper is organized around one economic object: continuous vehicle
  dominance in routed decentralised exchange. Other objects earn space by
  testing or qualifying that central object.
- Use **dominance** for a share-based role measure, **level** or **volume** for
  absolute activity, and **vehicle status** for the binary extensive margin.
  The compact description of the decomposition is that aggregate stablecoin
  dominance changes through net vehicle substitution within continuing pairs
  and through reallocation of routed activity across pairs. Do not make
  “dominance,” “share,” and “volume” interchangeable merely
  to vary the prose.
- Keep one result spine in the abstract and the introduction: state the
  aggregate change in stablecoin dominance, then the net within-continuing-pair
  result, then the positive margins that account for the aggregate change.
  Gross two-way movements may qualify the net result, but they must not make the
  reader lose the distinction between the aggregate change and its sources.
  Liquidity or persistence evidence follows only after this decomposition is
  clear.
- Name the empirical setting as decentralised finance (DeFi) or decentralised
  exchange early enough for the opening to meet the title before route mechanics
  begin. This is a paragraph-function rule, not a required first sentence or a
  fixed word position.
- Introduce an observed route by first saying what it reveals and why that
  information answers the question. Attach the pool-route versus user-instruction
  boundary when the route is first interpreted; do not make a qualification
  carry the opening before the reader knows the object it qualifies.
- Discuss quoting, invoicing, funding, settlement, or other currency functions
  in the introduction only when the comparison locates the route-based object or
  prevents a genuine conceptual confusion. Put that compact boundary after the
  vehicle measure has been introduced. A catalogue of adjacent currency roles is
  not part of the data or findings preview.
- Evidence rises in formality: definition and institutional perimeter, sample
  and support, validation of contested measures, visible descriptive fact,
  conditioned estimate, discriminating mechanism or rival, then implication.
- A regression table cannot introduce a construct the reader has not already
  seen measured.
- Finding-selling is allowed. A strong headline is rejected only when it
  contradicts the measured object, identifying variation, timing, support, or
  inference. Otherwise preserve the strongest defensible economic verb and put
  the decisive qualification nearby.
- Main-text limitations must travel with the result they can change. Do not hide
  support loss, construct disagreement, the strongest falsifier, or a limitation
  that changes sign or interpretation in the appendix.
- If first use or adoption dates an event study, describe both sides of the
  event. A visible post-event reversal must be reported and interpreted with
  the endogenous timing and selection rule before attaching provider or trader
  motives to it.
- The abstract contains no exhibit callouts or reported standard errors. The
  introduction normally previews magnitudes and inference in prose and leaves
  panel, column, and standard-error lookup to the results section. In the local
  fourteen-paper JFE corpus, no introduction reports a standard error and only
  two cite any exhibit; those two references point to an appendix robustness
  result and a conceptual figure. An introduction-level exhibit reference is
  therefore exceptional and must shorten a necessary lookup or introduce an
  exhibit that is itself part of the opening argument. This exception is why the
  rule is not a lexical ban on “Table,” “Panel,” or “Figure.”
- Do not repeat table-reported standard errors or confidence intervals in the
  narrative. Preserve a confidence bound when the bound is the economic result,
  and report uncertainty in prose when no exhibit displays it.
- Introduce an economic class before a named member when the result is about the
  class: stablecoins first, then USDC or USDT as members or sources of
  heterogeneity. A named token may lead when that token is itself the estimand,
  episode, or institutional case. Do not let a prominent member silently stand
  in for the class.
- Paragraph transitions must identify the object on both sides of a change in
  subject. Especially at the literature-to-design and setting-to-contribution
  transitions, state the unresolved question and the empirical opportunity
  before switching to “we.” Replace pronouns or demonstratives whose antecedent
  could refer to this paper, a cited paper, a market, or a location with the
  relevant noun.
- Present contributions through the economic findings and what the route data
  make observable. Do not use a stock “we make three contributions” paragraph or
  count a different dataset as a contribution by itself. Sequencing words remain
  available when they help the argument: seven of the fourteen local JFE
  introductions use a First/Second/Third sequence, typically to organize
  findings, questions, views, or mechanisms, while none announces “three
  contributions.” The data contribution is the otherwise-unobserved economic
  object or validation the data make possible.
- Captions and notes must be portable: object, unit, sample, weighting, support,
  uncertainty, and interpretation boundary should be visible without making the
  reader search through prose.
- Regression tables put a shared unit once in the dependent-variable header or
  note. When outcomes use different units, attach the unit to the corresponding
  row or column label in square brackets. Keep coefficient and standard-error
  cells numeric. Put already-defined notation in parentheses after an economic
  label, or use the notation directly when that materially shortens a paper
  table; the table note then states how every displayed variable is constructed.
  A compact model is ``Route share ($R_{b,t}$) [pp]``. Parentheses identify
  notation, while square brackets identify units or scaling.
- Define percentage points (pp) at first use in both the paper and the deck;
  use the abbreviation thereafter only where compact table labels benefit.
- Interpret a share-on-share coefficient in one-percentage-point units when that
  yields a readable number. Scaling an effect to 10 percentage points or one
  standard deviation is appropriate only when that increment is economically
  meaningful or materially easier to read; state the increment once and never
  use rescaling to make an effect look larger. Keep the coefficient's underlying
  unit recoverable from the equation, table, or accompanying definition.
- Every regression table that prints significance stars states the complete
  mapping in its note: ( * ), ( ** ), and ( *** ) denote statistical
  significance at the 10\%, 5\%, and 1\% levels, respectively. Never leave the
  reader to infer the thresholds from convention.
- Every numbered table and figure is introduced or interpreted in the main text.
  The published-JFE corpus makes this close to universal. Equation practice is
  different: local definitions and derivation steps may stand as unnumbered
  displays, while empirical specifications reused by a result or table are normally
  numbered and cross-referenced. The JFE author guide says displayed equations are
  numbered in the order they are referred to in the text. Number an equation only
  when its number has a narrative use; do not manufacture a callout merely to keep
  a number.
- Put an exhibit reference beside the substantive claim it supports and make the
  reader's lookup short. Name the panel, model or column, and economic row when a
  table contains several estimands; a table-level reference is enough for a short,
  single-object display. This lookup rule governs the results sections; the
  abstract and executive findings preview follow the narrower convention above.
  One precise reference may govern the next few sentences, so do not repeat it
  mechanically. Captions, panel headings, column headings, and row labels must
  make this level of reference possible without internal workflow terminology.
- The introduction roadmap is a compact map of admitted body evidence. Each
  promised empirical object must appear in the named section and matter to the
  argument there; a definition, benchmark under construction, or analysis held
  outside the paper is not advertised as a finding. Recheck the roadmap whenever
  sections move, evidence is withheld, or the abstract and contribution
  paragraphs change.
- The appendix is an audit trail, not a second paper. It mirrors the main claims
  and keeps nulls, failed alternatives, and adverse validation evidence visible.
- Do not add equations, citations, tables, or length as filler to resemble a
  venue statistic.
- Hard style rules enforced by tests: no em dash or en dash in prose, no
  hard-wrapped prose, no loose `p < ...` style prose, no unfinished markers such
  as `PENDING`, `TODO`, `placeholder`, or `XXX`, and a JFE abstract ceiling of
  100 words. Words beginning with `diagnos` are internal workflow language and
  never appear anywhere in paper or deck source, including comments, captions,
  and notes. State the economic or statistical role directly: bound, comparison,
  validation, coverage, sensitivity, or descriptive evidence. Correction-style
  contrasts such as `rather than` and “not X but Y” are also excluded from paper
  and deck prose. Lead with the measured object or result. Preserve a necessary
  scientific boundary as a direct statement of the estimand and its scope. Use
  result, estimate, proposition, inference, instrument, token, or exposure in
  audience prose; reserve `claim` for internal evidence-state metadata.
- Corpus alarms are review signals, not word-replacement instructions. If a known
  or discovered construction is over-used relative to the JFE corpus, rewrite
  the whole thought and paragraph function, then rerun the check.

## Slide language

- Speaker-note headings map one-for-one to the visible slide number and title.
  Timing belongs in rehearsal notes, not in the heading. Use subheadings only
  inside the notes for the same slide.
- Memorable spoken shorthand such as ``sticky'' is welcome when it is tied
  immediately to the measured object. Here it means predictive persistence in
  observed route use; it must not silently become trader inertia or another
  behavioural mechanism the design does not identify.
- The audience-facing unit is a complete claim, not an approved vocabulary item.
- Do not call visible comparisons, text boxes, or results “cards.” Name the
  economic comparisons directly; layout vocabulary stays in source comments.
- A strong finance slide normally makes the economic actor, quantity, or event
  the subject, uses an active verb, and places a substantive condition beside the
  result when the condition changes interpretation.
- Titles and body text should say what happened economically. Do not make
  “the evidence,” “the comparison,” “the design,” “the framework,” or “the
  workflow” narrate the presentation.
- Slides are phrase-driven rather than paragraph-driven. They may be incomplete
  sentences, but they still need a subject, verb, result, condition, and handoff
  to the next slide.
- No slide should describe the project’s own process. Workflow status belongs in
  source comments and review docs, not audience text.
- One idea should dominate each slide. Dense appendix slides are acceptable when
  they defend against questions; core slides need live-explanation pacing.
- Section breaks, references, and appendix-as-defense are legitimate
  finance-talk structures. A generic show-of-hands prompt is not.
- The closing slide is an economic ending. It should synthesize admitted route
  findings, lift them to the market-formation implication, and finish on that
  implication rather than on a test still to run. Motivation and generic
  “why this matters” language belong near the opening, not in the conclusion.
- Speaker notes share the empirical spine with the paper but use a different
  register. Preserve Java's conversational delivery: short bridges, ordinary
  words, occasional fragments, and a little repetition when it helps listeners
  follow the argument. Do not expand slide notes into manuscript prose or polish
  them into a formal essay. Every core slide has a spoken handoff; every backup
  slide has concise bullets that explain the question it answers, the reading of
  the exhibit, and its limitation.

## Visual rhetoric

- Visual form follows the intellectual object: lines for paths, bars for levels
  or endpoint contrasts, slope or dumbbell charts for paired changes, forest
  plots for estimates, heatmaps for matrices or regimes, histograms or densities
  for distributions, scatterplots for relationships, network diagrams for
  topology, transaction traces for observable mechanics, and finance-style
  tables for coefficient patterns.
- Use screenshots or photos only when they document an episode, institution, or
  observed transaction. Do not add generic crypto imagery.
- No current estimand warrants a surface or three-dimensional chart.
- A live reveal may end in a complete static composition. A film that uses time
  as an empirical channel must instead preserve a dimension no single frame can
  encode; its PDF keyframe documents one state and must not be presented as the
  full trajectory. The surrounding static deck still stands alone as a review
  artifact.
- Scientific numbers and plots enter through generated outputs. Do not hard-code
  numeric redraws in slide source.

## Parallel drafting and review

- The manuscript and deck are always-on deliverables. Rebuild them after admitted
  changes and keep the current state presentable.
- Versioned review snapshots can be sent while mechanism search and robustness
  work continue.
- Reviewer comments, new experiments, draft integration, and motivation rewrite
  run in parallel. Do not wait for all experiments to finish before keeping the
  draft coherent.
- Main-text and appendix placement is provisional. Promote a result when it
  materially sharpens the central economic fact, its generality, or a serious
  competing explanation; demote it when it diffuses that spine. Statistical
  significance alone does not determine placement.
- Use explicit evidence-state labels in source comments and review documents, where
  parallel work needs them; keep those labels out of audience-facing prose.
- Use named branches or small focused commits on `main` for parallel work. Do
  not create sibling project folders as a workflow state.

## Required checks after content changes

Run the full conformance surface before calling a paper or deck handoff ready:

```bash
./scripts/run scripts/verify/check_deliverable_conformance.py
```

For narrower edits, run the relevant checks directly:

```bash
./scripts/run -m pytest tests/test_paper_prose.py -q
./scripts/run scripts/verify/audit_deck_evidence.py
./scripts/run scripts/verify/measure_prose_conventions.py
./scripts/run scripts/verify/find_prose_outliers.py
./scripts/run scripts/verify/measure_venue_shape.py
./scripts/run scripts/verify/measure_venue_optics.py
```

If a check fails, fix the economic thought, paragraph function, slide claim, or
evidence boundary. Do not patch only the token that triggered the alarm unless
the surrounding argument is already correct.

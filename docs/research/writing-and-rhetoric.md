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
  market formation, substitution, exit, reversal, and persistence.
- Use causal verbs only when the design earns them. Otherwise use descriptive,
  predictive, associated, or mechanism-consistent language.
- A provisional result may enter the paper or deck if it is clearly labelled and
  rebuildable enough for review. It becomes headline evidence only after it is
  economically material, survives a serious rival explanation, fits the
  literature contribution, and has a complete producer-to-deliverable path.
- Blocked, withheld, unsupported, or retired material may remain in notes or
  appendix context, but it does not enter the abstract, headline tables, or
  audience-facing slides as established evidence.
- Provenance, node labels, workflow status, and review status belong in comments,
  source notes, or workflow docs. They do not narrate the paper or slides.

## Paper prose

- The paper is organized around one economic object: continuous vehicle
  dominance in routed decentralized exchange. Other objects earn space by
  testing or qualifying that central object.
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
- Captions and notes must be portable: object, unit, sample, weighting, support,
  uncertainty, and interpretation boundary should be visible without making the
  reader search through prose.
- The appendix is an audit trail, not a second paper. It mirrors the main claims
  and keeps nulls, failed alternatives, and adverse validation evidence visible.
- Do not add equations, citations, tables, or length as filler to resemble a
  venue statistic.
- Hard style rules enforced by tests: no em dash or en dash in prose, no
  hard-wrapped prose, no loose `p < ...` style prose, no unfinished markers such
  as `PENDING`, `TODO`, `placeholder`, or `XXX`, and a JFE abstract ceiling of
  100 words.
- Corpus alarms are diagnostics, not word-replacement instructions. If a known
  or discovered construction is over-used relative to the JFE corpus, rewrite
  the whole thought and paragraph function, then rerun the check.

## Slide language

- The audience-facing unit is a complete claim, not an approved vocabulary item.
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
  implication rather than on a test still to run.

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
- Every animation or live reveal must end in a complete static composition. The
  PDF must stand alone as a review artifact.
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
- Use explicit labels for provisional, registered, and confirmed evidence.
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

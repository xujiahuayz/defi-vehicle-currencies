# Research graph node checklists

This file is the single human-readable owner of node acceptance rules. `docs/research-requirements.md` owns Java's current requirements; `docs/research-workflow.md` owns dependencies and joins; executable checks enforce the mechanical subset. Do not copy these lists into the workflow or an agent brief.

A package evaluates one node or join only. Passing one checklist never closes another node. The closest raw literature passages are reread where they inform that node; this does not require rereading the entire corpus for every edit.

## Universal closure envelope

Every package records this envelope once and points to the node-specific evidence below.

- Entry: package ID, node, requirement IDs, single owner for each mutable object, immutable input paths and hashes, upstream generation and predecessor certificate.
- Work: exact object and permitted claim, output paths, tests, stop rule, downstream join and any unresolved decision for Java.
- Regression: compatible prior requirements checked against the last accepted object; a new instruction does not silently replace an older one.
- Exit: every applicable item is `pass` or `not_applicable`; each decision names evidence, and each `not_applicable` gives a scientific reason accepted by the reviewer or coordinator.
- Review: builder and reviewer are distinct for a closure review; the reviewer is read-only and ranks fatal, major and minor objections.
- Invalidation: an upstream generation, requirement, source, estimand or output hash change reopens the package automatically.
- Scheduling: compatible interjections fork to the affected package without cancelling unrelated work. A completed package publishes a boundary; the durable queue launches the next ready package or records why none is ready.
- Capacity: on the current four-slot interactive executor, reserve one coordinator and fill science/methods, paper and deck workers by default; Studio data is a separate fifth lane. Monitoring stays with the coordinator unless a bounded diagnosis requires a worker.
- Idle exception: every unused slot names its file conflict, invalid input, measured resource limit or dependency. Serial execution is never the unrecorded default.
- Deviation: change the recorded allocation before departing from it, naming the displaced package and the condition that restores the default.

## O. Operations and supervision

- One durable Studio supervisor owns unattended data work and survives the interactive laptop sleeping, travelling or disconnecting.
- The interactive browser reads selectable Studio output and queues interjections without launching a second token-consuming executor.
- The browser shows each package's owner, node, object, input generation, heartbeat, blocker, next join, checklist passed/total, current item, next failed item, resource use and throughput-based ETA.
- Runtime uses the approved high-effort GPT route and rotates approved GPT accounts. It does not fall back to Qwen or Opus; exhaustion waits or rotates within the approved route.
- Operation does not depend on Tailscale. The local/browser path is primary while independent remote recovery routes remain available.
- Duplicate supervisors are retired only after the active owner, process tree, restart marker and queue are verified.
- Another Studio job launches only when locks, files and bottlenecks are independent; spare cores alone are not a reason.
- Git and required ignored downstream data reconcile at clean boundaries. A running checkout is never force-updated.
- ETA records completed units, recent throughput, remaining units, sequential dependencies and uncertainty; revisions explain which input changed.

## A. Venue and talk benchmark

- Entry names the paper, deck or talk function being benchmarked and the retained source.
- Read the relevant raw venue/talk materials and record the design, structure, rhetoric or visual convention used.
- Distinguish published-paper conventions from presentation conventions and from Java's house voice.
- Output changes a target architecture, section job, visual form or venue-calibrated quality criterion. More notes alone do not close A.
- Exit names any source that could not be retained and the narrower claim still supported.

## B. Domain literature

- Entry names the scientific claim, method, analogy, anecdote, citation or rhetorical function requiring precedent.
- Read the closest raw paper passages, appendices, supplements and corrections; cards and digests are locators only.
- Record the precedent's estimand, comparison set, inference, rival mechanism, claim strength and exact passage.
- Use JFE and top finance practice to calibrate rigor, caveats and finding-selling; do not impose a stricter bar without a design-specific reason.
- Compare scientific scope, depth and breadth with the closest empirical papers: question hierarchy, descriptive foundation, identification, mechanism and rival tests, heterogeneity, robustness, economic magnitude and appendix support. Language resemblance alone is insufficient.
- Output changes C, E, F, G, P0, H or a citation. A literature note with no final use does not close B.

## C. Estimand and measurement

- State the economic question, unit, denominator, comparison set, timing, exposure, outcome, inference target and strongest rival in finance language.
- Separate calendar time, architecture availability, adoption, market formation, role entry, within-market substitution, persistence, exit, reversal and hysteresis.
- Distinguish vehicle status, dominance, network reach, endpoint demand, routed value, route cost, deposited capital, local depth, executable depth, inventory and LVR scale.
- For liquidity and V4, distinguish V2 deposited-capital stocks, V3 signed liquidity-supply flows, V4 intermediary-token transfer incidence, hook exposure, physical settlement quantities and provider returns; none substitutes for another.
- Use exact two-leg routes for one-intermediary dominance and treat longer routes as a separate network-reach object.
- Hold endpoints, intermediary set, venue or architecture, notional, support and comparison set fixed before assigning a mechanism.
- Exit is a claim-specific definition certificate; it does not freeze unrelated questions.

## K. Ideation

- Entry names a data affordance or literature concept not expressed by current C definitions.
- Propose an estimand, feasible input, identification sketch, falsifier and existing claim supported or displaced.
- Cover scientific dimensions Java has requested when feasible: opportunity sets, liquidity provision, V1--V4 design, route cost, persistence, hysteresis, fragmentation, HHI, centrality, routing/search and endpoint demand.
- Reject an idea internally when it has no measurement or identification route.
- Exit sends one bounded proposal to C or records it as a next-paper lead.

## D1. Purpose-bound input contract

- Begin from one C certificate and the smallest sufficient panel; do not inventory fields for unspecified future K ideas.
- Inspect the exact source schemas and real early, middle, late and regime-boundary partitions needed by that estimand.
- Classify missingness by economic weight and concentration across time, venues, assets, treatment groups and stress states.
- Forecast calls, bytes, wall time, memory, disk, locks, host split and a materiality stop rule before scale work.
- Search current data owners and consumers first; reuse the owner and remove superseded duplicates instead of adding a compatibility layer.
- Follow the fixed liquidity/V4 order: V2 deposited capital, V3 signed flow, V4 receipt incidence, route-to-pool hook heterogeneity, then rent after the return contract. Record an absent pointer, missing receipt, stale identity or unavailable quantity as the exact blocker instead of opening a proxy lane.
- Exit freezes only the fields, dates, identities and support perimeter required by the named estimand.

## D2. Certification and material repair

- Verify identity, ordering, cutoff and lineage over the exact D1 perimeter.
- Treat wrong identity or arithmetic, impossible timing, undefined semantics and invalid inference inputs as hard failures.
- Bound a potentially claim-changing defect before repair. Diffuse immaterial dirt remains a disclosed exclusion; it does not trigger perfection work.
- Keep audit dates separate from estimation dates. A full-calendar claim requires full-calendar certification; a fixed-date mechanism test certifies its predeclared dates.
- Record construction choices that affect the economic sample in referee-readable methodology or appendix language.
- Exit reports pass, bounded exclusion or material blocker and stops at the predeclared comparison.

## D3. Analysis panel

- Build the smallest panel at the estimator's economic unit, including explicit zero-use or risk-set rows when required.
- Reconcile denominators, identities, duplicates, units, support, missingness and economic weights.
- Bind code, inputs, sample, schema, rows, content identity and exclusions in a tested generation.
- Produce a panel consumable on the other host without raw access, including approved synchronization of required ignored data.
- Exit is a candidate release; it cannot be consumed until J0 checks it.

## J0. Purpose-bound data release

- Reopen the D1 contract, D2 certificate and D3 generation and verify their exact identity.
- Publish the panel, coverage/materiality ledger, bounded exclusions and cross-host generation equality.
- State which estimands the release supports and which it does not.
- J0 opens only descendants of this release. An unrelated red data branch does not block them.
- Invalidate J0 when code semantics, inputs, scope or content identity changes.

## E0. Exploration and mechanism search

- Inspect levels, changes, non-monotone paths, distributions, tails, concentration, heterogeneity and economically meaningful cases.
- Decompose aggregate change into within-market substitution, market formation/disappearance and activity reallocation.
- Explore liquidity provision, capital, executable depth, venue integration and V4 mechanisms when current J0 data identify them.
- Keep raw hook counts or values outside the paper and deck until their query contract, route-to-pool identity and support pass J0; a count/value contrast alone does not identify hook effects, net settlement or LP supply.
- Evaluate explicitly: OLS/WLS, panel fixed effects, grouped logit/binomial, PPML, discrete-time logit/cloglog, Cox sensitivity, DiD/event study, assignment-level t comparisons and KS/distribution analogues with dependence-aware resampling.
- Preserve all fits, nulls, numerical failures and rejected families. Do not fit a method merely to obtain significance.
- Surface scientific choices, anomalies and interpretation conflicts for live debate.
- Exit sends one candidate finding and its strongest objection to E1; it does not admit a paper claim.
- Keep a method-by-question matrix showing which feasible OLS/WLS, fixed-effect, grouped binary, PPML, duration, event and distributional families were run, rejected or blocked, and why. Method breadth is assessed by distinct economic content rather than specification count.

## E1. Claim-specific lock

- Freeze one claim's estimand, sample, unit, comparison set, primary specification, fixed effects, uncertainty convention, clustering, heterogeneity and falsifiers.
- State which E0 methods are primary, sensitivity, descriptive or rejected and why.
- A causal architecture claim requires a defensible comparison group, predetermined exposure, pretrends, balance and placebos; a global launch or endogenous adoption alone remains descriptive.
- Hold the ordered source-destination pair, intermediary asset, calendar week and trade-size range fixed for V3/V4 route comparisons; add architecture availability, pool formation and hook use separately so calendar time never stands in for design.
- Exit hashes the lock before confirmatory F. Changing the claim reopens E1.

## F. Registered empirics

- Run the E1 primary specification and prespecified sensitivities on the exact J0 release.
- Use a valid risk set, clustering, HAC or bootstrap design; textbook iid inference over repeated routes is not authority.
- Report economic magnitude and statistical uncertainty separately.
- Paper tables use one primary inference statistic unless the design itself requires another.
- Record informative nulls and failed numerical fits; do not discard an estimator because it is insignificant.
- Exit produces reproducible result artifacts and a model-ledger record. It does not choose audience-facing claim language.

## J1. Finding admission

- Reconcile C, J0, E1 and F identities.
- Record magnitude, primary inference, sensitivity results, nulls, strongest rival, literature calibration, scope condition and audience-ready claim.
- Benchmark the full evidence packet against the closest published empirical papers for scientific scope, depth and breadth; schedule a missing scientific comparison or narrow the paper's ambition before admission.
- Distinguish fixed-market substitution, across-market activity reallocation and aggregate share change.
- Lead with the strongest supported affirmative finding while keeping the decisive scope condition nearby.
- Remove superseded claims from current owners and deliverables; provisional historical comparisons remain only in provenance-stamped snapshots.
- Exit admits this packet to G, P0 and H. A reproducible exploratory packet may use the provisional lane but cannot enter J2 or J3.

## G. Scientific interpretation and paper spine

- Place each J1 packet in the economic argument and contribution relative to the literature.
- Explain what the result establishes, what mechanism organizes it, what rival remains and why it matters to finance.
- Decide the motivation, section order, table/figure job and conclusion implication without drafting generic filler.
- The spine demands only estimable results and never turns a null into a softened positive claim.
- Exit updates the canonical argument and claim inventory consumed by P0 and H.

## P0. Working-paper prose

- Entry uses current G and J1 packets or a clearly marked reproducible provisional packet; status and generation live in source comments, not rendered prose.
- Before adding prose, inspect the current section, rhetoric ledger and existing literature/optics work. Amend the canonical owner, incorporate durable material and remove superseded text instead of piling on another version or casually relabelling useful work as legacy.
- Write in the JFE register from the start. Do not create a generic AI draft for later synonym or term replacement.
- Reread the closest raw JFE passage for each section's function. Literature work must appear across motivation, design, interpretation, citations, anecdotes, analogies, paragraph movement and claim calibration.
- Run a whole-paper venue-optics review against raw JFE comparators: motivation before results, contribution positioning, evidence sequence and section balance, sentence- and paragraph-length level and dispersion, citation/equation/exhibit density, and visible page texture. Treat the comparison as a diagnostic; never close a gap with term substitution or filler.
- Review the complete manuscript: every section and subsection opening, substantive paragraph, handoff, referent, connective and close. A local repair never closes P0.
- Audit logical continuity sentence by sentence: demonstratives and definite articles have immediate antecedents; causal connectives follow an explicit premise; section roadmaps, samples and design changes receive the bridge a finance reader needs without explaining basic finance.
- Make actors, quantities and institutions the subjects; avoid backstage workflow language, abstract triads, meta-signposting and repeated contrast-confirmation.
- Use audience-facing finance and economics language. Internal labels such as `candidate`, `cell`, `verdict`, `evidence gate` or `transition margin` do not enter the manuscript unless the field uses them in the same sense or the construct is economically defined where it first appears.
- Use natural sentence and paragraph-length variation driven by the economics, not a statistical mold. Audit each subsection's exact sequence: a brief bridge, developed mechanism, evidence interpretation, literature position and scope paragraph should earn different lengths from their jobs; an unexplained narrow band remains open even when the mean looks acceptable.
- Use finance-calibrated analogies for a finance audience; DeFi-to-TradFi comparisons clarify an unfamiliar institution without explaining basic finance.
- Sell supported magnitude, novelty, breadth and mechanism affirmatively; place scope nearby without letting caveats replace the result.
- Keep general claims general and source non-obvious facts at the field-appropriate threshold; named examples support rather than replace the class. Protocol and institutional facts use primary sources where available, while common field knowledge is not cited pedantically.
- Make the title, abstract, introduction, evidence sequence and conclusion promise the same contribution. A working paper may report reproducible provisional results, but a target design, validated component and estimated result are described as different evidence states.
- Match every definition and equation to the empirical unit, category aggregation, denominator, perimeter and time index actually used. Harmonize notation across protocol families instead of inheriting each cited paper's symbols.
- Match every table and figure label, caption and note to its producer's unit, sample, denominator and evidence generation. A route, intermediary episode, transaction, pool and pair-day are never renamed for presentation convenience.
- Remove a superseded or withdrawn claim completely from current prose, equations, exhibits and notes; Git history retains it. Preserve only a durable scientific lesson rewritten under its current owner.
- Enforce the 100-word abstract, `we`, commented undecided authors, first-use acronyms, harmonized AMM notation, transaction links and mathematical minus signs.
- Generate tables from mapped producers and use estimate plus one conventional inference statistic by default.
- Exhibit notes are singular, full-width and limited to construction, sample, encodings, weighting and inference; interpretation stays in the text. Captions and notes use consistent alignment and enough separation from the exhibit.
- The conclusion synthesizes the answer, economic consequence and scope and ends with the durable implication.
- Exit requires the raw-passage ledger, all compatible prose/evidence tests, clean compile, complete rendered review and comparison with the last accepted manuscript.

## P1. Final integrative paper edit

- Entry requires stable J1 packets and a passed J2-paper candidate.
- Edit the canonical manuscript once for argument flow, contribution, cross-section consistency and final prose quality; do not create a second copy or ground-up rewrite.
- Reopen affected P0 checks and raw passages after every substantive change.
- Exit forces a fresh J2-paper and I pass before J3.

## H. Live deck

- Entry uses current G and J1 packets or a clearly marked reproducible provisional packet; provisional identity stays in source comments.
- Keep one canonical deck ready to present after every touch.
- Consult the persistent visual backlog; map each claim to the visual form that exposes its economic comparison.
- Include an authentic, correctly ordered route case and useful interface/transaction evidence. Verify source asset, intermediary, venues, values and hyperlink.
- Use native TeX/HTML reveals only when useful and provide a static PDF fallback; never embed a synthetic slide animation as MP4.
- Use current generated exhibits, never typed coordinates or copied measurements; remove stale claims completely from the live deck.
- Keep notes limited to unit, construction, encodings, sample, weighting and inference; interpretation stays in visible slide prose.
- Review finance vocabulary, bridges, affirmative framing, visual density, overlap, clipping, type, caption spacing, notes and conclusion against retained finance decks.
- Exit requires producer/evidence/provenance tests, clean local compile, changed-page and whole-deck projection review, and comparison with the last accepted deck.

## I. Independent challenge

- Entry freezes one J1 packet, J2-paper candidate, J2-deck candidate or repository release.
- Reviewer is read-only and procedurally blinded to builder rationale where possible; complete training-corpus blindness is not claimed.
- Rank fatal, major and minor objections separately for science, language, citations, exhibits, replication and presentation.
- Calibrate overclaiming against comparable published finance papers, including how framing and nearby caveats support strong claims.
- Route objections to the original owner. One integrated response normally closes I; another round needs a new material contradiction.
- Exit is an accepted response or an explicit return to the exact invalid node.

## J2-paper. Paper certificate

- Rebuild from current J1 packets and run every compatible paper requirement, not only the newest fix.
- Verify argument, rhetoric ledger, citations, notation, links, table ownership, exhibit notes, compilation and complete rendered manuscript.
- Verify that JFE calibration reaches the scientific package—question hierarchy, identification, mechanism, rivals, heterogeneity, robustness and economic magnitude—not only vocabulary, paragraph rhythm or page texture.
- Provisional packets cannot pass J2-paper.
- Exit records source/output hashes, upstream generations, checklist evidence and independent reviewer.

## J2-deck. Deck certificate

- Rebuild from current J1 packets and run every compatible deck requirement, not only the newest fix.
- Verify scientific claims, producer ownership, citations, notes, source-only status, visual diversity, compilation and complete rendered deck.
- Provisional packets cannot pass J2-deck.
- Exit records source/output hashes, upstream generations, checklist evidence and independent reviewer.

## J3. Submission freeze

- Entry requires current J2-paper and J2-deck certificates after P1 plus a current replication/repository certificate.
- Reconcile common claims, samples, numbers, terminology and links across all submission files.
- Run the final independent desk-reject and ranked-referee review.
- Exit is a current paper, deck, replication package and submission files that pass all scientific, literature, language, citation, notation, visual and reproducibility gates.
- Journal acceptance probability and future scientific revisions are outside the completion guarantee.

## R. Repository and reproducibility

- Inventory code, generated artifacts, authored notes, human/agent consumers and ignored data required downstream.
- Keep substantial directories documented; place authored deck and literature digests with their source families and generated material under its canonical output owner.
- Map each manuscript table and figure one-to-one to a named producer and current provenance.
- Verify a `legacy` label from ownership and consumer evidence; preserve useful content in its current owner before deleting the stale object.
- Run hard-wrap and format checks on authored documentation.
- Rebuild from a clean equivalent boundary and compare deterministic bytes or declared semantic tolerances.
- Exit records the consumer audit, producer map, README coverage, rebuild command and replication result.

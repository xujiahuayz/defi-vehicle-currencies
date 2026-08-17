# DVC autonomous grind brief

You are one iteration of a continuous loop driving the DVC paper to completion.
Do not answer this as a question. Do work, commit it, and exit. The loop starts
the next iteration immediately, so ending your turn is normal and costs nothing.
Never wait for a human and never ask a question: there is nobody reading this
turn.

## The objective, stated as an executable gate

The project is finished when all three of these hold:

1. `./scripts/run scripts/audit_findings_freeze.py` exits 0 (freeze gate GREEN,
   including the `two unchanged findings passes` check).
2. `paper/main.pdf` builds clean from frozen evidence.
3. `deck/main.pdf` builds clean from the same frozen evidence.

Nothing else counts as done. The freeze gate is the definition of "the graph is
through" — not your judgement of it.

## What to do this iteration

1. Read `AGENTS.md`, then run `./scripts/run scripts/research_action_preflight.py data` before selecting or mutating a blocker. This loads the live node boundary and prior-correction route before a plausible fresh plan can bypass them. Before mutation, write a short `REGRESSION-CHECK:` line in the iteration output naming the purpose-bound estimand, evidence generation, and prior correction most at risk from the planned action. If the action contradicts a printed check, revise the plan rather than explaining the contradiction away.
2. Read `logs/grind-ledger.md` (create it if absent). It is the handoff between
   iterations: what the previous workers did, decided, and hit. Read the last
   ~40 lines before anything else.
3. Read `logs/grind-queue.md`. That is the supervisor's channel into this loop.
   Any unchecked item there **outranks the gate's own blocking list** and is
   done first, oldest first. Tick it off (`- [x]`) in the same commit that
   closes it. If the queue is empty, go to step 3.
4. Run `./scripts/run scripts/audit_findings_freeze.py`. Read the blocking list.
5. Classify each live blocker by scientific consequence before choosing work.
   Report whether the defect is concentrated by time, protocol/design, venue,
   pool, vehicle candidate, trade size, or stress state; bound its economic
   weight; and ask whether it can change the estimand, sample composition,
   coefficient, or inference. Pick the unit with the highest scientific value
   among blockers that can change a claim. Metadata-only hygiene comes after
   valid estimators unless it prevents every consumer from reading unchanged
   data. Route-only estimators continue while unrelated exact-state branches are
   red. If the ledger shows the previous iteration was mid-way through a unit,
   continue only when that unit still passes this materiality test.
6. Before adding a script, artifact, rule, test, memo, or queue item, search for
   its existing canonical owner. Amend and consolidate there, remove or mark
   superseded duplicates, and add a new object only if the existing one cannot
   carry the work. Do not make a second consecutive engineering-only iteration
   unless the first exposed a hard failure or a defect that can change a claim.
   Otherwise this iteration must advance a claim, estimand, exhibit, rival test,
   interpretation, deck frame, or paper section.
7. Do the work properly and finish it. Build the real artifact, from real data,
   through the project's own owners and scripts.
8. Run the relevant tests plus the freeze audit again. Commit with a real
   message describing what closed.
9. Append one entry to `logs/grind-ledger.md`: date, the check you targeted, what
   you did, the commit hash, the new blocking count, and anything the next
   iteration must know. Commit that too.
10. Leave the repo publishable (see **Git hygiene** below), then exit.

If a unit is genuinely too large for one iteration, split it, land the first
part in a committed and tested state, and record the exact resumption point in
the ledger. Leaving a working tree broken is the one unforgivable outcome: the
next iteration inherits it.

## Git hygiene (every iteration, not "eventually")

Work on `main` in this worktree. The loop pushes for you after you exit, so the
only thing you owe is a clean, small, honest history:

- **Commit in units that build.** Never leave the tree dirty at exit, and never
  commit a half-migration. If you must stop mid-unit, land the working part and
  record the resumption point.
- **Never exit while your own background work is still running.** Nothing will
  notify you: your turn is the last thing in this process, and the loop starts a
  fresh worker that inherits your uncommitted files with no idea what state they
  are in. If you launched a test suite or a long build in the background, wait
  for it, act on the result, and commit. If you genuinely cannot wait, commit the
  work first with the suite's status stated in the message, so the next iteration
  inherits a clean tree and a known question rather than a mystery diff.
- **Push-safe commits only.** Assume every commit you make is public within
  seconds, because it is. No secrets, no absolute paths in tracked files, no
  large derived artifacts that belong in the data store rather than git.
- **Clean up after yourself.** Delete scratch files, probe scripts, and one-off
  outputs you created, or move them under `scratchpad/`. Untracked debris at exit
  is a defect: the next iteration cannot tell your leftovers from real state.
- **Prune your own worktrees.** If you create a `/private/tmp` worktree, remove
  it before exiting (`git worktree remove`), then `git worktree prune`.
- **Never rewrite published history.** No force-push, no rebase of anything that
  has been pushed, no amend of a pushed commit. Fix forward with a new commit.

## Hard rules

- **Never fake a gate.** Do not stub, touch, hand-write, or shortcut an artifact
  to turn a check green. A green gate over an empty parquet is worse than a red
  one, because it silently enters the paper. If a check cannot be honestly
  closed, record why in the ledger and pick a different one.
- **Never acquire provider data you already have.** Check `data/raw/`, including
  its retained archive, before any fetch. New acquisition writes only to this
  repository's canonical provider folders; the retired sibling repository is
  not a data store.
- **Never rewrite a certified release to get cleaner architecture.** Bound the
  defect's materiality first; defer architecture to the next planned generation.
- **Social-science materiality comes before data perfection.** Random or
  economically bounded missingness is disclosed, bounded with a sensitivity
  where useful, and allowed to proceed. A hard failure is reserved for wrong
  identity, corruption, systematic selection correlated with the treatment or
  outcome, invalid causal timing, or inference invalid for the stated claim. A
  certificate or provenance mismatch is not itself scientific evidence: once
  scientific identity and the relevant rows/bytes are proved unchanged, close
  the bookkeeping through the existing owner and return to estimation. Never
  turn a demand for 100 percent metadata cleanliness into an implicit research
  objective.
- **Respect the project's locked decisions and notation.** They are in the glotl
  brain at `~/glotl/projects/defi-vehicle-currencies.md` under "Locked decisions"
  and "Learnings". Read them before touching prose, notation, or estimands.
- **The paper is an always-ready working deliverable.** Write publication-standard prose for every reproducible current result, including provisional estimates at their exact scientific scope, and refresh the same passage when its input changes. Put provisional identity and refresh requirements in source comments, not in the rendered PDF. Retired, contradicted, or presently irreproducible estimates stay out; the full node P freeze governs submission authority, not whether the working paper may discuss a result that can still evolve. At every tier, cards only locate the closest analogues: reread the named raw published JFE passages and rewrite the economic argument, paragraph sequence, transitions, and sentence functions. Word substitution, vocabulary lint, stored-card synthesis, and a generic rhetorical stencil never count as a prose pass.
- **The deck is always a deliverable.** It remains presentation-ready after
  every iteration even while estimates evolve. Scientific status, evidence
  commit, generation identity, and repository paths live in audited source
  comments, never in audience-facing provisional badges or hash labels. Update
  the single frame in place, compile, visually inspect, run the source audit,
  and commit the canonical PDF.
- **Do not turn realised architecture use into a design shock.** V4 route-share
  entry and exit are endogenous E0 exposure transitions. V4 remains available
  after launch, and the current positive-use risk panel measures within-cell
  substitution exits, not removal of the protocol design or disappearance of
  the vehicle role. The separate active-pair risk panel reports vehicle-role
  appearance and disappearance, but these margins remain endogenous too. A
  design-reversal claim needs independently measured availability or exact
  cost/depth state.
- **Decisions:** when a judgement call blocks you, preserve mathematical and
  inferential validity but do not default to the weakest claim. Calibrate the
  claim and its adjacent caveat directly against the closest published finance
  papers, then record `promote`, `narrow`, `park`, or `reject` under `DECISION:`
  and keep going. A further critic round requires a new objection that can
  materially change that decision; generic residual uncertainty does not.
- **Escalation:** if something is genuinely unsafe to decide alone — deleting
  data, spending money, anything outward-facing — do NOT do it. Record it in the
  ledger under `NEEDS-JAVA:` and work on a different blocking check instead.

## When the gate goes green

Refresh the already-live JFE paper and Nanyang deck from frozen evidence, then
close both through the content, venue-shape, provenance, and clean-build loops.
Only when all three conditions at the top hold does the loop end by itself.

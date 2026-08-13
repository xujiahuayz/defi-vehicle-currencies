# DVC autonomous grind brief

You are one iteration of a continuous loop driving the DVC paper to completion.
Do not answer this as a question. Do work, commit it, and exit. The loop starts
the next iteration immediately, so ending your turn is normal and costs nothing.
Never wait for a human and never ask a question: there is nobody reading this
turn.

## The objective, stated as an executable gate

The project is finished when all three of these hold:

1. `uv run python scripts/audit_findings_freeze.py` exits 0 (freeze gate GREEN,
   including the `two unchanged findings passes` check).
2. `paper/main.pdf` builds clean from frozen evidence.
3. `deck/main.pdf` builds clean from the same frozen evidence.

Nothing else counts as done. The freeze gate is the definition of "the graph is
through" — not your judgement of it.

## What to do this iteration

1. Read `logs/grind-ledger.md` (create it if absent). It is the handoff between
   iterations: what the previous workers did, decided, and hit. Read the last
   ~40 lines before anything else.
2. Run `uv run python scripts/audit_findings_freeze.py`. Read the blocking list.
3. Pick ONE blocking check — the one that unblocks the most others, preferring
   node D data contracts over node E estimators over node B literature, since
   downstream checks depend on upstream ones. If the ledger shows the previous
   iteration was mid-way through a unit, continue that unit instead.
4. Do the work properly and finish it. Build the real artifact, from real data,
   through the project's own owners and scripts.
5. Run the relevant tests plus the freeze audit again. Commit with a real
   message describing what closed.
6. Append one entry to `logs/grind-ledger.md`: date, the check you targeted, what
   you did, the commit hash, the new blocking count, and anything the next
   iteration must know. Commit that too.
7. Exit.

If a unit is genuinely too large for one iteration, split it, land the first
part in a committed and tested state, and record the exact resumption point in
the ledger. Leaving a working tree broken is the one unforgivable outcome: the
next iteration inherits it.

## Hard rules

- **Never fake a gate.** Do not stub, touch, hand-write, or shortcut an artifact
  to turn a check green. A green gate over an empty parquet is worse than a red
  one, because it silently enters the paper. If a check cannot be honestly
  closed, record why in the ledger and pick a different one.
- **Never acquire provider data you already have.** Check the certified sibling
  store `../defi-dominant-currency/data/` and existing release pointers before
  any fetch. A refetch that overwrites a certified partition is how the 2026-08-13
  Fluid incident was manufactured.
- **Never rewrite a certified release to get cleaner architecture.** Bound the
  defect's materiality first; defer architecture to the next planned generation.
- **Respect the project's locked decisions and notation.** They are in the glotl
  brain at `~/glotl/projects/defi-vehicle-currencies.md` under "Locked decisions"
  and "Learnings". Read them before touching prose, notation, or estimands.
- **Prose and slides stay closed** until the freeze gate is green with two
  unchanged passes. Do not "get a head start" on the paper text.
- **Decisions:** when a judgement call blocks you, take the conservative option
  (the one that preserves the estimand and fails closed), record it in the ledger
  under `DECISION:`, and keep going. Do not stop to ask.
- **Escalation:** if something is genuinely unsafe to decide alone — deleting
  data, spending money, anything outward-facing — do NOT do it. Record it in the
  ledger under `NEEDS-JAVA:` and work on a different blocking check instead.

## When the gate goes green

Regenerate the JFE paper and the Nanyang deck from frozen evidence, then close
both through the content, venue-shape, provenance, and clean-build loops. Only
when all three conditions at the top hold does the loop end by itself.

# DVC grind queue — supervisor channel

This is java's channel into the autonomous grind loop. Anything unchecked here
**outranks the freeze gate's own blocking list** and is done first, oldest at the
top. The worker ticks an item off (`- [x]`) in the same commit that closes it,
and leaves a one-line note under the item saying where the work landed.

Format:

```
- [ ] <what to do, stated so a worker with no other context can act on it>
```

Empty queue means: fall through to step 3 of `docs/autonomous-grind-brief.md`
and pick a blocking check from the freeze gate.

## Queue

- [ ] **Forward-port the sample-end single-source hardening onto `main`.**
  Commit `9bd8ce4` ("Derive the sample end from one constant") exists only on the
  local branch `glotl/fgh-evidence`, which is 187 commits behind `main` and whose
  upstream is gone. `main` already has `RESEARCH_SAMPLE_END = "20260630"` as the
  single definition in `src/ddvc/calendar.py`, so today's data boundary is
  correct; what `main` lacks is the hardening around it: the derived spellings
  (ISO, exclusive ISO and stamp, UTC epoch bound, day normalisers), V1's genesis
  named separately so it cannot be mistaken for a second sample end, consumers
  importing instead of restating, and the guard test that fails when a new
  hardcoded spelling appears outside `calendar.py`.
  Do not cherry-pick blind: with 187 commits of divergence, treat
  `git show 9bd8ce4` as a specification and re-implement against today's `main`.
  Known residual site: the snapshot filename in `src/ddvc/fetch/pool_daily.py`.
  Sweep `scripts/`, `tests/` and generated report prose too, not just `src/`.
  Acceptance: guard test exists and passes; editing `RESEARCH_SAMPLE_END` alone
  moves every consumer including derived filenames; full suite green; freeze-gate
  blocking count not increased. Then delete the stale local branch
  `glotl/fgh-evidence` and note that in the ledger.
  Land the guard test first if this needs more than one iteration.

## Closed

_(nothing yet)_

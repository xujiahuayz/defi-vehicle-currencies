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

- [x] **Repair the provenance staleness that `f6ca42b` introduced. Do this first.**
  Two checks regressed to `provenance=stale` immediately after the sample-end
  forward-port: `node D full-calendar directed-route gate` (which was
  `provenance=ok` an hour earlier, and is the gate last night's Fluid repair was
  published to satisfy) and `node D V3 inventory calendar provenance`. Blocking
  count went 14 -> 16.
  Mechanism: `_verify_unlocked` in `src/ddvc/provenance.py` compares
  `code_fingerprint(rec["code_sources"])` against the stamped `code_fingerprint`.
  `f6ca42b` edited `src/ddvc/calendar.py` and twelve consumers, so every artefact
  that stamps those files as code sources now fails `byte_code_ok`. Every data
  field is still clean: 2,332/2,332 calendar days, 12,802/12,802 venue days,
  `failed=0`, `conflicts=0`, `malformed=0`, `missing_columns=none`.
  **Step 1, prove it before touching anything.** For each stale artefact, print
  the full verdict: `code_current`, `byte_code_current`, `content_current`,
  `inputs_current`, `changed_inputs`, `stamped_fingerprint`,
  `current_fingerprint`. If `content_current` is false, or `changed_inputs` is
  non-empty, then this is NOT a fingerprint artefact and you must stop, record it
  under `NEEDS-JAVA:` in the ledger, and work on something else.
  **Step 2, only if content is unchanged and only code moved.** Re-stamp
  provenance through the project's own certification path. Do NOT rebuild from
  raw, do NOT refetch any provider data, and do NOT rewrite a certified release
  to make this go away: that is precisely how the 2026-08-13 Fluid incident was
  manufactured. Re-stamping an artefact whose bytes are provably identical is
  legitimate; regenerating it is not.
  You may consider whether `_legacy_semantic_compatible` should recognise a pure
  single-sourcing refactor as semantics-preserving, but do not widen that escape
  hatch just to turn a gate green. If it cannot be justified on its own terms,
  re-stamp instead.
  Acceptance: both checks back to `provenance=ok`; the directed-route gate still
  reporting 2,332/2,332 and 12,802/12,802 with zero failures; blocking count 14
  or lower; `require_route_release()` still passing.
  _Closed by an exact-payload provenance restamp of the V3 inventory calendar:
  all 1,884 raw cuts reproduce the unchanged panel byte-for-byte, its SHA-256 and
  mtime were unchanged, and both inputs remain current. The route ledger was
  already republished by `672fb3d`; both provenance checks now pass, the route
  release validator passes, and the freeze audit is back to 14 blockers._

- [x] **Forward-port the sample-end single-source hardening onto `main`.**
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
  _Closed in this commit: `ddvc.calendar` now owns the derived spellings
  (`V1_GENESIS_START`, day normalisers, `sample_end_*`), all twelve consumer
  sites import instead of restating (including the known residual in
  `src/ddvc/fetch/pool_daily.py`), and
  `tests/test_sample_end_single_source.py` guards against new hardcoded
  spellings and pins that one edit moves every consumer. Stale branch
  `glotl/fgh-evidence` deleted; it was checked out in the primary worktree
  `~/projects/defi-vehicle-currencies`, which was clean, so that worktree was
  detached in place at `9bd8ce4` with zero file changes._

- [x] **NEEDS-JAVA resolved (ledger line 109): `/private/tmp` worktree disposal is authorized and already done.**
  Java authorized worktree cleanup on 2026-08-13. The supervisor removed all 13
  registered `/private/tmp` worktrees plus 5 orphan scratch dirs git had already
  lost track of, then ran `git worktree prune`. Three worktrees remain and are
  the only ones that should exist: `~/projects/defi-vehicle-currencies`,
  `~/projects/defi-vehicle-currencies-d3` (this one), and
  `~/projects/defi-vehicle-currencies-raw-cert`.
  The dirt was not work: every "modified" file was a deleted `data/` placeholder.
  Nothing was lost. Preserved under
  `~/projects/defi-vehicle-currencies-backups/worktree-cleanup-20260813/`:
  the pre-repair Fluid/Uniswap/Balancer certificates (all five hash differently
  from the live store, so they are the superseded generation), and `raw-cert`'s
  uncommitted raw-certification feature.
  **Do not delete `-raw-cert`:** it holds unlanded work (72 new lines in
  `scripts/fetch_raw_market_data.py` plus four untracked sources) pending a
  land-or-bin decision from Java. Do not re-raise this escalation.

## Closed

_(items are ticked in place above)_

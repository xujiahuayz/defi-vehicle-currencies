# DVC autonomous grind ledger

Handoff between grind iterations. Newest entry at the bottom. Each entry records
the date, the freeze check targeted, what was actually done, the commit, the new
blocking count, and what the next iteration must know.

The gate is `uv run python scripts/audit_findings_freeze.py` (exit 0), then a
clean `paper/main.pdf` and `deck/main.pdf` from frozen evidence. Nothing else
counts as done.

## Standing facts for every iteration

- **Run everything through `./scripts/run <script>`.** It sets
  `PYTHONPATH=<root>/src:<root>` and `PYTHONSAFEPATH=1`. Bare
  `uv run python scripts/x.py` puts `scripts/` on `sys.path` instead of the repo
  root, so any `scripts.*` import fails. `tests/test_project_runner.py` forbids
  entrypoints from mutating `sys.path`, so the runner is the only sanctioned way
  in.
- `.venv` in this worktree has no `pytest`; use `./scripts/run -m pytest`.
- Raw evidence is already local: `data/raw/thegraph` (84G), `data/raw/ethereum`
  (55G), `data/raw/dune/fluid` (hardlinked to the certified sibling store
  `../defi-dominant-currency/data/`). **Never refetch.** `du` reports 0B for
  `data/raw/dune` because those partitions are links, not because they are empty.
- `data/processed/` in this worktree is nearly bare: the whole node-D processed
  layer still has to be rebuilt here from raw. The primary worktree
  `~/projects/defi-vehicle-currencies` holds older processed parquets from a
  183-commits-behind code generation — treat them as unusable, not as a shortcut.

---

## 2026-08-13 — iteration 1

**Targeted:** `node D V2 event-source certificate exists`, via its first
prerequisite — the exact V2 token-decimals registry
(`data/processed/v2_audit_token_decimals.parquet`). This is open item 2 in
`.dvc-resume-brief.md` and is also an input to the pool-capital release, so it
unblocks two node-D checks at once.

**Starting state:** freeze gate RED, 16 blocking checks. `logs/grind-ledger.md`
did not exist; this file is new.

**Tree health.** `tests/test_project_runner.py::test_python_entrypoints_do_not_
mutate_import_paths` was failing on arrival: `scripts/run_vehicle_rotation_e0.py`
inserted `<root>/src` into `sys.path`. Removed the mutation and hoisted the
`ddvc.tables` import to a normal top-level import; the runner already provides
`src`. `tests/test_project_runner.py` now 3 passed.

**Work:** `./scripts/run scripts/audit_v2_event_completeness.py
--token-registry-only --no-fetch --workers 6` — cached RPC chunks only, no
provider acquisition.

_(outcome appended below before commit)_

_Iteration 2 closing note: no outcome was ever appended and no commit followed.
`data/processed/v2_audit_token_decimals.parquet` does not exist, so the
registry run did not complete. What the tree held instead at iteration 2's
start was the finished-but-uncommitted sample-end queue work below. The V2
token-decimals registry remains open and is the natural next target._

---

## 2026-08-13 — iteration 2

**Targeted:** queue item 1 (sample-end single-source hardening), inherited from
a previous worker as a complete but **uncommitted** working tree — the exact
dirty-exit failure the brief forbids. This iteration verified the work instead
of redoing it, finished the one unclosed sub-task, and landed everything.

**Verification, not trust.** Reviewed the full diff (12 consumer sites now
import the boundary from `ddvc.calendar`; new derived forms
`sample_end_{iso,date,exclusive_*,utc_exclusive}`, day normalisers,
`V1_GENESIS_START`). Guard suite `tests/test_sample_end_single_source.py`:
4/4 passed, including the probe that moves `RESEARCH_SAMPLE_END` and asserts
all six consumer modules follow. Full suite: 1,743 passed, 3 failed
(`test_paper_provenance`, `test_transaction_targets`,
`test_variable_registry`); all 3 reproduce byte-identically on the clean
parent commit via stash, so they are pre-existing gate debt, not this change.
Freeze audit: RED, 16 blocking — unchanged from iteration 1's start.

**Branch deletion.** `glotl/fgh-evidence` was checked out in the primary
worktree `~/projects/defi-vehicle-currencies`, which is why a plain delete
would have failed. That worktree was clean, so it was detached in place at
`9bd8ce4` (zero file changes) and the branch deleted. `9bd8ce4` stays
reachable through that detached HEAD and the reflog.

**DECISION:** detaching the primary worktree's HEAD was judged in-scope: the
queue explicitly ordered the branch deletion, the worktree was clean, and the
detach changes no bytes on disk.

**DECISION:** committed `.dvc-resume-brief.md` (until now untracked) because
this ledger already cites it; home-relative `~/projects` paths in it follow
the precedent this ledger set. If java wants it untracked, say so in the queue.

**Commits:** `f6ca42b` (hardening + queue tick), `852cc78` (supervisor's new
no-background-work-at-exit rule — found as an uncommitted edit to the brief),
`07e0419` (track the resume brief).

**Blocking count:** 16 (unchanged; this was hygiene + hardening, not a gate
check).

**For the next iteration:**
- Queue is empty. Resume iteration 1's target: the V2 token-decimals registry
  (`./scripts/run scripts/audit_v2_event_completeness.py --token-registry-only
  --no-fetch --workers 6`, cached RPC chunks only) toward `node D V2
  event-source certificate exists`. No artifact exists yet; assume it starts
  from scratch.
- All 13 registered `/private/tmp` worktrees are dirty (1–345 modified files
  each; surveyed 2026-08-13), so none can be pruned blindly.
  NEEDS-JAVA: authorize disposal per worktree, or tell us which are dead.
- The 3 failing tests above are real gate debt (stale
  `output/tables/summary_statistics.tex` notation among them); they overlap
  the freeze gate's blocking list rather than adding new work.

## 2026-08-13 — iteration 3: repair sample-end provenance regressions

**Targeted check:** supervisor queue item `Repair the provenance staleness that
f6ca42b introduced` (`node D full-calendar directed-route gate` and `node D V3
inventory calendar provenance`).

**Work completed.** Printed the required full provenance verdict for both
artefacts before mutation. The route ledger was already repaired by `672fb3d`
and was fully current. The V3 inventory calendar was the permitted
fingerprint-only case: `content_current=true`, `inputs_current=true`,
`changed_inputs=[]`, and only `byte_code_current=false`. Revalidated the full
calendar contract (1,884/1,884 cuts, exact raw-to-panel identity, valid UTC
cuts, 2–16 persisted RPC calls per cut, zero bad evidence), then re-stamped the
sidecar through `ddvc.provenance.stamp` without rebuilding or fetching. The
payload SHA-256 remained
`af9bfa4ca6a9df570d7fadd261370d638dbecad23085f93df2de349b6929d4cb` and
its mtime was unchanged. `require_route_release()` passes; the route gate still
reports 2,332/2,332 days and 12,802/12,802 venue-days with zero failures.

**Validation.** `./scripts/run -m pytest -q tests/test_provenance_inputs.py
tests/test_data_release.py tests/test_audit_findings_freeze.py`: 95 passed plus
70 subtests. Freeze audit: RED, 14 blocking (down from 16 before the queued
repair; both provenance regressions are now PASS).

**Commits:** `371b1d8` (record the supervisor's inherited worktree-cleanup
resolution), `22e3f37` (exact-payload V3 calendar restamp + queue tick).

**Blocking count:** 14.

**For the next iteration:**
- Queue is empty. Resume the V2 token-decimals registry toward `node D V2
  event-source certificate exists` with `./scripts/run
  scripts/audit_v2_event_completeness.py --token-registry-only --no-fetch
  --workers 6`; use cached RPC chunks only and do not reacquire provider data.
- The freeze audit's V3 calendar and full-calendar directed-route checks are
  both current; do not rebuild either release.

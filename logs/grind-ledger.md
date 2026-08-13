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

## 2026-08-13 — iteration 4: route-only architecture transition support

**Targeted check:** the three overlapping supervisor queue directives to move
the already-green route-only D contract into E0 after integrating the science
branch's denominator, overlap, preflight, and composition-set guards.

**Work completed.** Confirmed the prior science ports were already on `main` as
`dc7d613`, `3ab708d`, `12edf63`, `1096d83`, and `17eda66`, then integrated
upstream `2d11836` as `d72f8c1`. The V3 exact-event preflight failed quickly and
as designed on 124 absent current state inputs; no raw scan or provider fetch
ran. The earlier 62-date state attempt's exact blocker remains: raw files exist,
but the installed local-scan certificate does not authorize
`uniswap_v3/burns/20210515`.

Rebuilt the architecture input from the current released unified layer, not the
stale M3 route panel. The certified route-only payload contains 3,970,589
exclusive coherent route units: 3,063,723 V3 rows over 523 days and 906,866 V4
rows over 518 days. Mixed-source components remain excluded. Its SHA-256 is
`4fc206525d33efb507d700067b87e9a4c248c1a6038ad93a1d56a350f4746f10`.
The 63,193-row weekly architecture panel has SHA-256
`0430e794c49d0ab4930b88973103de6bce7dd3edc9cc864f0e818e0e1a265646`.
All four route/panel/event/contrast provenance verdicts are current with
`code_current=true`, `content_current=true`, `inputs_current=true`, and no
changed inputs.

**E0 support verdict.** The event exhibit has 581 candidates (SHA-256
`18d751eae81a85e57301f96a752398369a27549942d9710bd1dba9ec0f6cbb1c`);
the contrast exhibit SHA-256 is
`03c5f922c4a988e05d017e8b0e25ad708476a4cdfbdf8812843f7b2f5fd1263f`.
At 5%, entry support is 0 usable / 59 overlapping / 0 incomplete / 103
composition-shift and exit support is 0 / 46 / 0 / 33. At 10%, entry is 0 /
50 / 1 / 88 and exit is 0 / 40 / 0 / 29. At 25%, entry is 0 / 34 / 0 / 44
and exit is 0 / 34 / 0 / 20. Thus every candidate fails the isolated,
complete, fixed-comparison-set contract. This is a durable E0 support result,
not a causal estimate; calendar time is not treatment and no contrast is
promoted.

**Validation.** `./scripts/run -m pytest -q
tests/test_architecture_state_transitions.py tests/test_v3_event_completeness.py`:
33 passed. The side-effect-free `--help` path exited 0; `--preflight-only`
failed closed on the expected missing state inputs. Freeze audit: RED, 14
blocking (unchanged; route-only E0 is exploratory and adds no false gate pass).

**Commits:** `d72f8c1` (comparison-set guard) and `76d6c16` (certified small
outputs, immutable payload manifests, and queue closure).

**Blocking count:** 14.

**For the next iteration:**
- Queue is empty. Resume node D at the minimal existing local-scan certification
  owner for the 62 V3 construction-audit dates, beginning with authorization of
  `uniswap_v3/burns/20210515`; do not launch market-state materialization until
  that exact partition is admitted. Do not broaden into the dormant raw-cert
  feature or redesign certification, and do not fetch provider data.
- Route-only E0 is closed as a support audit with zero usable event windows.
  Do not weaken the composition/overlap contract, interpret date as treatment,
  or promote these contrasts. Prose remains closed.

## 2026-08-13 — queued architecture support and provisional-deck handoff

**Targeted check:** the seven queued science/deck integration interjections,
through support-classification tip `377aa25` and the deck-only interpretation
fix `3d8f36b`. These outranked the freeze blocking list.

**Work completed.** Integrated the six science commits after the already-landed
comparison-set guard, without restarting the certified route materialization.
Ran `run_architecture_state_transitions.py` exactly once against route generation
`4fc206525d33`, producing the corrected within-cell support exhibit (SHA-256
`e24b7068d46d19e2454b273238cb37266795bdcd76a6a2abe11e18cc3f828816`),
the separate active-pair role-margin support exhibit (SHA-256
`f99d35ade1527d77fe0eb4b64f264f86793fc6028b8f190d001b255b07096dad`),
and generated slide macros (SHA-256
`c4e2a134f35fcddb349110b9e8ef2a5f476c15e3485316290bdab5fb3feb33dd`).
The new role-risk panel has SHA-256
`025cf04506e00575c5402cf3bea84b0bb6be00a9bb1254392e89c50f77177b7f`.

The corrected within-observed-cell audit has zero usable windows at every
threshold. At 5%/10%/25%, entry detected (usable) is 162 (0), 139 (0), 78 (0),
and substitution exit is 79 (0), 69 (0), 54 (0). Missing pair-weeks are now
`incomplete_window`, not `composition_shift`. In the separate active-pair risk
set, vehicle-role appearance is 9 detected / 4 usable and disappearance is 7 / 3
at every threshold; its reported magnitudes are mechanical descriptive changes,
not causal effects or design removal.

Integrated the tested deck follow-up as `a587f8b`, rebuilt only the deck from the
existing generated macros with Tectonic, and visually checked the three
provisional frames. The populated audit frame has no overflow and explicitly
states the zero substitution support and mechanical extensive-margin magnitudes.
`deck/main.pdf` SHA-256 is
`10f19a7549cb55ab43aad7890d59c7772b2d6b4de5ca7d6f933f9327593f39d0`.
Paper prose remains closed.

**Validation.** Focused architecture/V3 tests: 37 passed. Tectonic deck build:
exit 0, no overfull boxes (one non-blocking underfull paragraph warning on the
interpretation table). Freeze audit: RED, 14 blocking, unchanged.

**Commits:** `25c3bd2`..`cefee55` (science series), `4d8a2b6` (certified
support outputs and first six queue closures), `a587f8b` (tested deck
interpretation fix), and `7f3c8b4` (clean deck build and final queue closure).

**Blocking count:** 14.

**For the next iteration:**
- Queue is empty. Resume node D at the minimal existing local-scan certification
  owner for the 62 V3 construction-audit dates, beginning with authorization of
  `uniswap_v3/burns/20210515`. Do not launch exact-state materialization until
  that partition is admitted; do not fetch provider data or broaden into the
  dormant raw-cert feature.
- Do not rerun the route build or architecture transition owner. Their current
  outputs are durable E0 support audits, not paper evidence or causal estimates.

## 2026-08-13 — V3 raw-stream admission and failed-state preflight

**Targeted check:** `node D V3 event-source certificate exists`, continuing the
62-date exact-state prerequisite at the installed local-scan rejection for
`uniswap_v3/burns/20210515`.

**Work completed.** Ran the project's local certification owner against the
already-installed Uniswap V3 raw generation, with no provider acquisition. The
new exact four-stream perimeter passes 7,536/7,536 partitions (1,884 dates each
for burns, daily, mints, and swaps), with certificate identity
`7d729098cf4490933cb4b420c7c3683caecc844c9093f36b59a0aaf8c556fa51`
and ledger SHA-256
`660400e8fb17ae67dcb92e040059878909de733d43c8664c40b02dff905bd3d5`.
The exact burn, mint, swap, and daily partitions on 2021-05-15 all reopen through
`raw_partition_read_authority`; the earlier burn-partition rejection is closed.

The prescribed 62-date market-state build then ran and installed 62 state and
62 quality files, but correctly published no global ledger: every partition has
`missing_required_streams=1` because the exact V3 Initialize daily release and
certificate do not yet exist. Its owner in turn requires the exact-anchor V2
token-decimals registry. The cached no-fetch registry pass reopened 9,624,212
Graph rows and resumed a 65,095-anchor manifest, then failed closed on 13 missing
cached RPC evidence records. The durable unresolved ledger has 65,082 resolved,
13 unresolved, and unresolved-set SHA-256
`6d0f4447fc977e267fc8bb0429fa5a1e61458ebede8fea14bdbfb662cd334953`
(`data/raw/ethereum/token_decimals/v2_unresolved_tokens.json`, file SHA-256
`26e26437ec5410f08e410b7ee47ed66767fbd53e9c48f32a7403d8e844b32de6`).
The certified sibling store has no copy of those 13 records. No RPC fetch was
made.

Fixed the V3 audit preflight so present-but-stale or failed-quality state files
cannot trigger the expensive raw-inventory audit. The live preflight now reports
`stale=0, failed=62` and stops before scanning. Focused validation: 94 tests and
10 subtests passed. Freeze audit: RED, 14 blocking, unchanged.

**Commit:** `af85d46` (`Reject failed V3 audit state inputs`).

**Blocking count:** 14.

**DECISION:** treated acquisition of the 13 absent historical RPC responses as
new outward provider work and did not authorize it autonomously. The failure
ledger is exact and complete; no provider-reported decimals were substituted.

**For the next iteration:**
- Queue is empty. Continue node D through the 13 exact token-decimals evidence
  gaps listed in `data/raw/ethereum/token_decimals/v2_unresolved_tokens.json`.
  Check for newly installed/certified local evidence first. Do not rerun the
  65,095-anchor selection with `--force`; its manifest SHA-256 is
  `258afe5902e399b99f4abe9dc4bfa16cb03316a38cf8f33c863c761856efc0c6`.
- Once the exact decimals registry passes, run
  `fetch_tick_state_events.py uniswap_v3` without `--fetch` to certify the 1,311
  already-local exact-state chunks and publish daily Initialize inputs. Then
  rerun the 62-date market-state owner; do not launch the V3 event audit until
  its cheap preflight is green.

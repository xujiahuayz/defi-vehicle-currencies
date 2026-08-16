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

## 2026-08-13 — Exact route-release contract exposed at the freeze gate

**Targeted check:** `route measurement panels exist`, beginning with the missing
`cross_venue_routing_daily.parquet` route-only owner after D2 was confirmed
blocked on the 13 exact token-decimals evidence gaps.

**Work completed.** Checked the certified sibling store, both other DVC
worktrees, and the configured local execution environment before acquisition.
None contains the 13 exact token-decimals records, and no local archival RPC is
configured or listening. No provider request was made. The capital owner is
blocked by the same missing audited registry.

The current cross-venue owner was then opened against the certified directed-
route release. Its mandatory `released_route_partitions()` contract rejected
1,884 stale days, beginning exactly at Uniswap V3 genesis on 2021-05-04. The
aggregate freeze check had nevertheless reported the directed-route gate green
because it checked only the 2,332-row ledger and its provenance, not the exact
day-marker contract used by every downstream owner. Fixed that false pass:
`audit_findings_freeze.py` now invokes `require_route_release()` and propagates
its partition-level rejection into the existing full-calendar route gate.

The preserved pre-relocation authority snapshot cannot be reused directly: its
recorded quality-ledger and marker hashes were superseded before the later V3
raw-authority change. No marker, route parquet, route panel, or certified raw
release was rewritten or copied. Focused validation: 48 tests and 9 subtests
passed. Freeze audit: RED, 15 blocking; the new blocker is
`node D full-calendar directed-route gate` with `1,884 stale day(s),
first=20210504`.

**Commit:** `4faa446` (`Gate route panels on exact released partitions`).

**Blocking count:** 15.

**NEEDS-JAVA:** the 13 exact historical decimals RPC records still require
authorization for new provider acquisition unless a certified local copy
appears. Do not substitute Graph-reported decimals.

**DECISION:** failed closed on the route panels instead of copying the ignored
primary-worktree parquets or widening the old relocation escape hatch. The
existing cross-venue and vehicle-extent files have old directory-level stamps
and cannot be admitted while the exact route owner rejects its inputs.

**For the next iteration:**
- Queue is empty. Repair the route-marker authority transition before running
  any route-only D3 panel owner. First identify the exact V3 certificate change
  after `672fb3d`; use the preserved pre-repair certificate bundle and the
  existing authority snapshot only as read-only evidence. Extend the migration
  owner only if it can bind the live marker fingerprints to the prior authority,
  prove every old/current scientific raw identity equal, and preserve every
  route partition's rows, bytes, hash, and mtime. Do not run the old snapshot
  through `--publish`: its ledger/marker bindings are no longer current.
- After `require_route_release()` passes, run
  `build_cross_venue_routing_series.py --workers 8 --panel-only` and
  `build_vehicle_excess_use.py --workers 8 --panel-only` through `./scripts/run`;
  do not copy the old ignored panels into this worktree.

## 2026-08-13 — V3-era route authority rebound and route panels refreshed

**Targeted check:** `node D full-calendar directed-route gate`, followed by the
supervisor's economic-materiality redirection to rebuild only the two required
route panels and compact exhibits.

**Economic result.** The rejection covered all 1,884 days from V3 genesis, so it
could have selected the complete V3/V4 architecture era and changed every
downstream route estimand. The exact migration proof instead finds zero
scientific-identity differences across all 12,802 venue-day inputs and preserves
the rows, bytes, SHA-256, and mtime of every one of 2,332 route partitions. The
partition identity set remains
`49d831f13c8fe0958776b0f4e59aa6411c34315d562127c19ddff9e39cf24f59`.
This bounds the defect as authority bookkeeping rather than a change in period,
protocol/design, venue, pool, vehicle candidate, trade-size, or stress-state
composition; it cannot change an estimand, coefficient, or inference.

**Work completed.** Built a new immutable pre-V3-recertification authority
snapshot from the canonical swaps-only Uniswap V3 certificate and proved its
12,802 scientific identities equal to the earlier relocation snapshot. The
project's journaled migration owner then rebound exactly 1,884 marker
fingerprints and the global quality outputs without rebuilding a route parquet.
`require_route_release()` passes all 2,332 days. Rebuilt only
`cross_venue_routing_daily.parquet` and `vehicle_excess_use_daily.parquet`
through their owners, then refreshed their six compact exhibits. All eight
panel/exhibit provenance verdicts are `ok`; route calendars reconcile at 2,332
days with 55 structurally empty vehicle days, and 43,705,695 intermediated routes
reconcile exactly. The cross-venue panel retains 358,027,668 routes over the
full 2020-02-11..2026-06-30 calendar; the vehicle panel has 2,277 nonempty days
and 8,112,479 token-days. Focused validation: 103 tests and 70 subtests passed.
Freeze audit: RED, 13 blocking, down from 15; the directed-route and vehicle-
dominance checks now pass.

**Commit:** `99e26ab` (`Rebind route release and refresh route panels`).

**Blocking count:** 13.

**DECISION:** stopped certification engineering once exact equality bounded the
defect as economically immaterial. Kept calendar release windows descriptive,
not treatments, and did not open another data family or estimator. The remaining
route-measurement blocker is solely the stale
`intermediation_by_type_daily.parquet`; evaluate its economic support and refresh
through its owner only if it is still required for fixed-opportunity routing.

**For the next iteration:**
- Queue is empty at this commit. Return immediately to science, starting with
  the stale intermediation-by-type panel only if the fixed-opportunity routing
  design still consumes it. State its economic weight and concentration before
  rebuilding; do not resume marker or raw-certificate engineering.
- Keep persistence distinct from hysteresis: the latter needs asymmetric
  retention versus displacement under independently measured cost-state
  reversal. Realised architecture use remains endogenous E0 exposure.
- Paper prose remains closed because the freeze gate is red. Presentation-ready
  provisional deck updates may use only the newly current compact exhibits and
  must retain support and identification labels.

## 2026-08-13 — route measurement provenance current

**Economic scope.** The stale intermediation provenance covered the complete
2,332-day route calendar rather than a selected venue, pool, design, candidate,
trade-size, or stress slice. The installed panel spans 43,705,695 intermediated
routes and 47,606,817 episodes; 72.3% of episodes are single-venue, 27.7% are
cross-venue, 78.4% are exact two-leg, and strict 20% value support retains 82.5%
of raw intermediary value. Its claim use remains necessary: the specification
lock names it as a vehicle-rotation input and uses its integration/complexity
strata before the later fixed-opportunity conditioning.

**Work completed.** Rebuilt `intermediation_by_type_daily.parquet` and all five
owned compact exhibits through `build_intermediation_by_type.py` against the
certified 2,332-partition route release. A preserved pre-build copy and the
owner-built result are byte-identical at SHA-256
`8db2065d8f14b8a3d7b34b6cc2057823a6d74ecc5fc8f8b6beaef33c7afc780b`
and exactly equal in every cell across 2,332 rows and 253 columns. The defect
therefore has zero economic weight and cannot change the estimand, sample,
coefficient, or inference. The current manifest now binds every released route
partition; the panel and all five regenerated exhibits verify `ok` with current
content, inputs, and code. Focused validation: 89 tests and 70 subtests passed.
Freeze audit: RED, 12 blocking, down from 13; route-measurement provenance now
passes and the claim-input gate reports three current inputs with no stale ones.

**Commit:** `111230a` (`Refresh certified intermediation evidence`).

**Blocking count:** 12.

**DECISION:** retained the panel because it is an explicit locked claim input,
but bounded the provenance defect before publication and found exact zero
scientific change. No provider data, certified route partition, paper prose, or
state-dependent estimator was opened.

**For the next iteration:**
- Queue is empty at this commit. Resume upstream D2 data contracts, preferring
  the V2 token-decimals registry and V2 event-source certificate identified in
  the glotl next-actions list; check the certified sibling store and existing
  release pointers before any acquisition.
- Do not rebuild the intermediation panel or route release again. All route-only
  measurement provenance and reconciliation checks are green.
- Paper prose remains closed; the gate still has 12 blockers.

## 2026-08-13 — unresolved V2 token-anchor exposure bounded

**Targeted check:** supervisor queue science/materiality redirection for the 13
unresolved exact V2 token-decimals anchors, ahead of any further acquisition or
registry rebuild.

**Economic scope.** The exact factory perimeters contain 22 pairs touching the
13 tokens (11 anchors in Uniswap V2 and two in SushiSwap V2). The selected
10,235-chunk exact-candidate perimeter contains 229 affected events: 204
Uniswap swaps, seven mints, three burns, and 15 SushiSwap swaps. On the complete
released route graph, deleting every route touching an unresolved token removes
5,950 of 358,027,668 routes (0.00166%) and $10.907m of strict-support route
value, 0.000346% of total released route value. Exposure is temporally
concentrated in 2021 ($7.617m, 69.8% of the strict deletion bound) and primarily
in Uniswap-only routes ($10.378m, 95.1%).

The relevant vehicle-estimand bound is smaller. All 13 tokens are residual
`other`, none clears the $100m rotation materiality screen, and none appears in
the V4 fixed-cell architecture route-unit panel. Their endpoint routes can
carry a prespecified vehicle in the middle, so the audit deletes those too:
1,036 candidate intermediary episodes and $1.284m, only 0.00229% of strict
candidate episodes and 0.000433% of strict intermediary value. WETH accounts
for $1.236m of that conservative deletion. Thus the unresolved set cannot
materially change the promoted vehicle-rotation or current V4 fixed-cell
support, although it still blocks an exact V2 event-source certificate.

**Work completed.** Added `audit_v2_token_anchor_materiality.py`, which
revalidates every consumed selected-anchor lineage file, reopens both exact
factory registries, counts installed exact-candidate events, validates the
certified route release, reconstructs topology and strict 20% value support,
and measures the complete deletion sensitivity for prespecified vehicle
candidates and the V4 architecture panel. Published a compact 71-record,
provenance-current exhibit with token, pool, event-kind, year, venue-set, and
candidate detail. The decimals uncertainty is not filled or guessed: nine
tokens have provider reports of zero, two of 18, two have no usable report, and
the exact quantity scale remains bounded only by the project's fail-closed
0..36 policy. No RPC call, provider scan, raw mutation, certified-release
rewrite, estimator, paper prose, or data acquisition occurred. Focused
validation: 74 tests and 61 subtests passed. Freeze audit: RED, 12 blocking,
unchanged.

**Commit:** `932e18f` (`Bound unresolved V2 token exposure`).

**Blocking count:** 12.

**DECISION:** treat the 13 tokens and all 22 exact V2 factory pairs containing
them as a bounded exclusion in any future exact event/state generation until
historical decimals evidence exists. Do not resume acquisition merely to make
the registry exact. This clears fixed-cell vehicle-rotation science, not the
exact D2 certificate, and it does not license a fabricated registry row.

**For the next iteration:**
- Queue is empty at this commit. Return to fixed-opportunity vehicle-rotation
  science using the deletion bound as a sensitivity; do not reacquire these 13
  decimals records or rebuild the certified route release.
- Keep architecture-use entry and exit endogenous E0 exposure. Exact-state
  reversal still requires independently measured availability or cost/depth
  state; do not interpret route-use disappearance as a design reversal.
- Paper prose remains closed; the freeze gate still has 12 blockers.

## 2026-08-13 — fixed-cell rotation decomposition made executable

**Targeted check:** queued sync/science handoff through `45573a9`, followed by
the fixed-opportunity vehicle-rotation input named in the refreshed paper
spine and `within_pair_composition_decomposition` literature attack.

**Economic scope.** The new decomposition fixes ordered endpoints, observed
venue reach, single- versus cross-venue routing, and protocol sequence before
splitting the 2024-to-2026 stable-share change into within-cell movement,
common-cell reweighting, cell entry, and cell exit. It reports pair, candidate,
and venue-reach/design support entry and exit separately for route counts and
strict-support value. It is explicitly a pre-frontier descriptive estimand:
notional bins and exact search-efficiency state are still absent, calendar time
is not treatment, and the output cannot identify a routing, architecture, or
coordination mechanism.

**Work completed.** Fast-forwarded the requested science/deck series through
`45573a9`, integrated the subsequent executable-preflight correction, and
closed the queue item in `20de4e1`. Added
`vehicle_rotation_composition.py`, its D3-bound E0 runner, and exact arithmetic,
calendar-support, zero-value-support, and entry/exit tests in `af097db`. The
runner owns the three already-registered outputs
`vehicle_transition_pair_{panel,decomposition,support}.jsonl` and refuses to
run unless the typed endpoint-candidate release pointer belongs to the injected
D3 certificate. A two-day real-data smoke check wrote no artifact and closed
both count and strict-value accounting identities within
`5.56e-17`; its low common-cell support was treated only as evidence that the
complete release is necessary, not as a finding.

The designated Studio alias was unavailable from the M3
(`Could not resolve hostname studio`), so no remote job was launched. The
purpose-bound scale pilot covered early, stress, architecture, late, and the
largest route day. A typical 18--20 MB day took 22--23 seconds and 1.0--1.3 GB
peak process memory; the 50 MB maximum day took 40 seconds and 3.1 GB. The full
source is 38.2 GB over 2,332 partitions. No full M3 scan, provider acquisition,
release publication, paper edit, or provisional result occurred.

**Validation.** Focused workflow, D3, release, exploration, paper-spine, and
composition tests: 94 passed plus five subtests. The narrower implementation
suite also passed 36 tests. Freeze audit: RED, 12 blocking, unchanged.

**Commit:** `af097db` (`Add fixed-cell vehicle rotation decomposition`).

**Blocking count:** 12.

**For the next iteration:**
- Queue is empty at this commit. On Studio, fast-forward `main`, rerun the data
  preflight, and publish the complete purpose-bound input with
  `./scripts/run scripts/build_endpoint_candidate_composition.py --workers 8`.
  Do not publish a diagnostic subset or weaken the full-calendar contract.
- After the endpoint-candidate pointer is current and included in the D3
  analysis certificate, run
  `./scripts/run scripts/run_vehicle_rotation_composition_e0.py`; inspect the
  count/value decomposition and common-support concentration before any claim
  update or figure. The result remains pre-frontier until notional and exact
  search-efficiency cells exist.
- Preserve the 13-token bounded exclusion, do not reopen exact-decimals
  acquisition for this route-only estimand, and leave `paper/` unchanged.

## 2026-08-13 — vehicle rotation estimator reconciled to the locked design

**Targeted check:** the queued science gate on `af097db`: make the route-only
vehicle-rotation owner implement the exact E1 seed before publishing its
missing D3 input or generating an exploratory result.

**Economic scope.** The corrected descriptive estimand is the 2026-minus-2024
change in realised stable share within native-plus-stable exact two-leg
intermediation on month-days observed in both endpoint years. The pair panel
uses measure-specific common ordered-pair by month-day by integration-scope
support. The companion aggregate decomposition assigns common versus exclusive
pair membership after pooling scopes for the primary result and separately
inside single- and cross-venue scopes. It does not fix notional, observed
opportunity, or exact search-efficiency state; it identifies neither adoption,
preference, architecture treatment, nor a mechanism.

**Work completed.** Replaced the finer annual endpoint/reach/protocol-cell
accounting with the locked three-measure panel (`count_share`,
`matched_strict_count_share`, and `strict_intermediation_value_share`) and the
exact four-term midpoint identity: `within_common`,
`common_pair_reweighting`, `common_support_mass`, and
`exclusive_pair_contribution`. Zero exclusive mass now receives the lock's
explicit zero normalization and the two support/exclusive terms are also
reported jointly. The release runner's spec IDs distinguish pooled and split
scopes, and its provenance notes preserve descriptive realised-composition
language. Added direct tests for the identity, zero-exclusive normalization,
common month-days, measure-specific support, scope pooling, and row-order/common-
scale invariance. Closed the supervisor queue item in the same commit. No
release, result, deck, or paper artifact was written.

**Validation.** Focused composition, runner, D3, release, workflow, freeze-audit,
and paper-spine suite: 112 passed plus 14 subtests. The complete suite reached
1,793 passed plus 524 subtests; its three failures are unrelated installed-state
residuals already outside this unit: absent withdrawn rent artifacts cited by
the closed paper, installed raw files entering one transaction-target fixture,
and the stale generated summary-statistics notation table. Compileall and
`git diff --check` passed. Freeze audit: RED, 12 blocking, unchanged.

**Commit:** `97b4b94` (`Match vehicle rotation to locked decomposition`).

**Blocking count:** 12.

**For the next iteration:**
- Queue is empty at this commit. Rerun the data preflight, then publish the full
  current route-derived input with
  `./scripts/run scripts/build_endpoint_candidate_composition.py --workers 8`;
  never publish a diagnostic subset or rebuild the certified route release.
- After the pointer is current and bound into the D3 analysis certificate, run
  `./scripts/run scripts/run_vehicle_rotation_composition_e0.py`. Inspect all
  four terms, the joint support/exclusive term, measure-specific common support,
  and pooled versus single/cross concentration before any claim or figure.
- Preserve the accepted 13-token bounded exclusion. Keep notional and fixed-
  opportunity claims gated, treat route-use margins as endogenous realised
  composition, and leave `paper/` unchanged while prose node P is closed.

## 2026-08-13 — endpoint evidence bound and vehicle rotation bridge published

**Targeted check:** the oldest supervisor queue unit: bind the purpose-built
endpoint-candidate release into D3 without rescanning unchanged bytes, then run
the registered E0 vehicle-rotation exploration and determine whether its
extensive margin survives separation into market support and realised vehicle
incidence.

**REGRESSION-CHECK:** the purpose-bound estimand remains the 2026-minus-2024
change in stable-route share within native-plus-stable exact two-leg
intermediation, using endpoint generation
`5fb7cbf36508f168055492d246302331052760a470464ac666816379c05335ee` and
current D3 certificate generation
`9aa4e1d3ecbc9fb899bf70ba70fc18cf1d621003162218e755fd8ecc4cbb3580`.
The correction most at risk was treating endogenous route use as architecture
availability or a design shock; the new bridge therefore remains descriptive
and does not identify demand, preference, opportunity, or search efficiency.

**Economic scope and concentration.** The pooled count-share estimand rises
from 16.87% to 42.54%, a 25.68 percentage-point change. Exact accounting assigns
9.83 points to market-pair support turnover, -0.39 to vehicle-role support
turnover within established markets, 7.90 to market-activity reweighting, 7.03
to realised vehicle-incidence reweighting, and 1.31 to within-pair stable share;
the identity error is zero. Market-turnover pairs carry 41.52% of 2024 and
50.38% of 2026 primary mass. Among established markets, role-turnover mass is
only 3.01% and 1.03%, while established-market stable share rises 15.84 points.
Thus the defect was concentrated in market and vehicle-candidate support, was
large enough to change interpretation, and cannot be dismissed as metadata.

**Work completed.** Added opt-in semantic receipts, leased pointer/member/
sidecar/source identities, and an in-place legacy attestation path to the
canonical release owner; attested the existing endpoint generation without
changing its bytes or pointer generation; routed the 554,188-row support panel
to Parquet; made the freeze provenance gate read typed release inputs; and kept
legacy capital releases receipt-free. Published the first real E0 panel and
then extended its existing owner with exact market-versus-role turnover and a
six-order Shapley bridge over market activity, realised vehicle incidence, and
stable share. Registered the bridge in the specification lock, findings freeze,
workflow, tests, provenance, and current D3 analysis certificate. The first
real run exposed the JSONL exhibit row cap rather than a scientific failure;
the format correction was landed before rerunning. All supervisor queue items
were closed in their owning commits.

**DECISION:** `promote` the extensive-margin result as descriptive evidence
that market composition is quantitatively central; `narrow` the mechanism to
observed market activity and realised vehicle incidence; do not attribute the
terms to architecture, availability, demand, preference, or search efficiency.

**Validation.** The focused release, D3, workflow, composition, provenance,
and freeze-audit suite passed 86 tests plus 11 subtests; earlier release suites
in this unit passed up to 119 focused tests. The complete endpoint exploration
wrote 554,188 cell rows, 10 decomposition rows, and 42 support rows. Provenance
verification passed, `git diff --check` passed, and the final current-identity
freeze audit is RED with five blockers.

**Commits:** `4223a2d`, `0da2c27`, `3b93df8`, `5788056`, `628388d`,
`6f06464`, `ce2cbb0`, `e16796c`, and `23ee3a2`.

**Blocking count:** 5.

**For the next iteration:**
- The queue is empty (apart from its literal template placeholder). The five
  live blockers are E1 specification locking, the empirical model ledger, the
  incomplete full-text literature ledger, the absent route-cost panel, and two
  unchanged findings passes.
- The highest-value next scientific unit is the fixed-opportunity route-cost
  construction required by D3/E1. Preserve the released route and endpoint
  generations, use the registered owner, and do not reinterpret realised use
  as an exogenous opportunity change.
- Leave exact-state coefficient prose outside the paper until its evidence
  locks. The published rotation bridge supports descriptive composition only.

## 2026-08-14 — matched-market vehicle-rotation attack published

**Targeted check:** the oldest supervisor queue unit: execute the registered
`e1_1_pair_panel` estimator once against Studio's current leased D3 release,
independently reconcile its algebra, update the findings record, and surface
the result in the existing pair-composition deck frame.

**REGRESSION-CHECK:** the purpose-bound estimand is the 2026-minus-2024 stable
route-share contrast within the same ordered endpoint pair, calendar position,
and broad realised route scope, using endpoint generation
`5fb7cbf36508f168055492d246302331052760a470464ac666816379c05335ee` and
D3 certificate generation
`9aa4e1d3ecbc9fb899bf70ba70fc18cf1d621003162218e755fd8ecc4cbb3580`.
The correction most at risk was treating endogenous realised route use as
fixed architecture, opportunity, cost, or design treatment. The findings and
deck therefore call these matched markets or like-for-like market comparisons
and state the omitted venue sequence, feasible alternatives, notional,
liquidity, cost, and router state.

**Scientific consequence and concentration.** The pooled count rotation is
+25.68 percentage points, but the denominator-weighted count-share change is
only +0.224 points inside matched markets (two-way ordered-pair and
calendar-date CR1 SE 0.764 points; Holm p=1). Matched strict count is +0.323
points (SE 0.749; Holm p=1), and strict supported value is -1.346 points (SE
2.188; Holm p=1). All three exactly reproduce the independent benchmark. The
aggregate result is therefore concentrated in market support/activity and
realised vehicle-incidence margins rather than pervasive within-market
switching. It materially narrows interpretation but does not identify the
mechanism.

**Work completed.** Preserved the committed bounded V2 exclusion, used the
already-landed canonical estimator and runner, and published the three-row
fixed-effects exhibit plus current provenance from the leased 554,188-cell
panel. Extended the existing deck-value owner to validate and consume that
exhibit, generate coefficient and confidence-interval macros, and fail closed
on the comparison-set and inference contracts. Added the interval to the
existing pair-composition ribbon, updated the findings freeze, and closed the
supervisor queue item without creating another script or diagnostic panel.

**DECISION:** `promote` the matched-market null as a descriptive rival test that
locates the aggregate rotation; `narrow` the economic interpretation to market
composition and realised use; do not claim architecture, opportunity, demand,
preference, search, or cost effects.

**Validation.** The estimator/runner and deck-owner tests passed 29 focused
tests; the final integration/freeze suite passed 78 tests plus 11 subtests. All
four E0 artifacts and the generated deck macros verify against current
provenance. The deck compiled to 31 pages with Tectonic, the deck evidence and
field-language audit passed, the changed frame passed prior-PDF comparison,
and the complete contact sheet showed no clipping or layout regression. The
broader conformance wrapper retained its pre-existing venue-structure alarm and
could not invoke its hardcoded `latexmk` because local TinyTeX lacks Beamer; its
deck-specific evidence, language, and numeric-provenance checks passed. The
final freeze audit remains RED with five blockers.

**Commits:** `b21ed0a` (current-lease evidence) and `dedc7bb` (findings, deck,
and queue closure).

**Blocking count:** 5.

**For the next iteration:**
- The queue is empty apart from its literal template placeholder. Resume the
  highest-value live scientific blocker, currently the fixed-opportunity
  route-cost construction required by D3/E1.
- Treat this result as evidence that the aggregate rotation is not pervasive
  inside comparable realised markets. Do not translate the null into proof
  that pair type causes vehicle choice.
- The paper and exact-state coefficient prose remain outside this unit; node P
  and E1 remain closed.

## 2026-08-14 — V2 exact event source independently reopened

**Targeted check:** the absent release-grade `main_v1` route-cost panel through
its full-calendar market-state prerequisite, beginning with the failed V2 exact
event-source reopening exposed by the canonical state builder.

**REGRESSION-CHECK:** the purpose-bound estimand is the best direct route versus
the best two-hop route for the same endpoints, UTC hour, and notional under
`main_v1` at USD 1,000, 10,000, and 100,000, using quote-engine generation
`e4ff06ed46ff`. The evidence generation closed here is V2 event-source release
`09335f9551339e45b19734f9513511beca4a11bcc82b47adfa3947509a17b5e0`.
The prior corrections most at risk were the common 5% own-price-impact gate
and the prohibition on stale V4/Balancer shards; for V2 specifically, exact
block-log order must govern rather than legacy provider order. This iteration
used `--no-fetch` throughout and did not overwrite certified raw partitions.

**Scientific consequence and concentration.** The independently reopened
77-date construction audit admits 65,082 token decimals, bounds 13 token and
22 factory-pair exclusions, releases 462 summary rows, and has zero exceptions.
Exact supplements are concentrated at the endpoint on Uniswap V2: 38 events on
2025-12-15, nine on 2026-01-15, and one on 2026-02-15; SushiSwap V2 needs none.
Those 48 records are tiny relative to daily event totals but can change
endpoint state reconstruction, so retaining them is claim-relevant rather than
metadata hygiene. Sparse exact-absence exclusions elsewhere are explicitly
classified and economically bounded; there is no launch-timed or venue-wide
coverage break.

**Work completed.** Fixed the canonical exact-log reader so shared chunks can
resolve their persisted old upper-block anchors from the factory evidence root
instead of the separate exact-log cache. Consolidated reconciliation reading
so all correction actions are consumed while bounded excluded pools remain
outside registry/decimals decoding. Applied the same header-root contract to
the transaction-target consumer, added focused regressions for both failures,
and published the first independently reopenable V2 event-source release and
portable provenance manifests. Updated the findings guard to separate the
closed 77-date certificate from the still-open full-calendar state input.

**DECISION:** `promote` the V2 construction-audit certificate as independently
reproducible evidence; `park` full-calendar state materialization at its next
honest input boundary rather than extrapolating the 77 audit dates.

**Validation.** The complete no-fetch V2 audit passed all 77 comparisons and
the final independent replay (`rows=462; exceptions=0`). Focused V2/event-order
tests passed 103 tests; the integrated release/state/freeze suite passed 188
tests plus 72 subtests. The downstream market-state builder now fails closed at
the first legacy non-audit generation, `sushiswap_v2/20241025`. The final freeze
audit passes the V2 certificate check and remains RED with five blockers.

**Commit:** `bb33d79` (V2 evidence reopening, release provenance, and findings
status).

**Blocking count:** 5.

**For the next iteration:**
- Resume the full-calendar market-state owner at
  `sushiswap_v2/20241025`; do not infer that the 77-date construction calendar
  certifies non-audit dates and do not fetch provider data already present.
- After an exact full-calendar V2 generation exists, continue V3/V4 daily state
  materialization before rebuilding `main_v1`; no route-cost shard was created
  in this iteration.
- The remaining executable freeze blockers are E1 lock, the empirical model
  ledger, the full-text literature ledger, the absent route-cost panel, and two
  unchanged findings passes.

## 2026-08-14 — Full-calendar V2 token-anchor boundary measured

**Targeted check:** the absent release-grade `main_v1` route-cost panel through
its full-calendar market-state prerequisite, continuing at the first legacy
V2 correction generation exposed by the prior iteration.

**REGRESSION-CHECK:** the purpose-bound estimand remains the best direct route
versus the best two-hop route for the same endpoints, UTC hour and USD 1,000,
10,000 and 100,000 notionals under `main_v1`, using quote-engine generation
`e4ff06ed46ff` and V2 event release
`09335f9551339e45b19734f9513511beca4a11bcc82b47adfa3947509a17b5e0`.
The correction most at risk was treating audit-calendar token-decimals evidence
as authority for non-audit dates, or admitting provider-reported decimals in
place of exact chain anchors. No provider data was fetched or overwritten, no
legacy pointer was rewritten, and the 77-date certificate remained current.

**Scientific consequence and concentration.** The 35 flat V2 correction days
have complete cached UTC bounds and shared 50-block exact-log evidence, but the
active admitted provider perimeter contains 12,654 unaudited tokens across
12,702 pools and 567,043 Mint/Burn/Swap rows. The gap is concentrated in 34
distinct Uniswap-heavy late-sample dates rather than the certified monthly
construction calendar. It is not metadata hygiene: 199 missing tokens enter
382 of the 6,800 `main_v1` top-200 ordered-pair day rows, carrying $280.831
million of $48.470 billion realised bridge volume, or 0.5794%. Excluding or
mis-scaling them can change endpoint sample composition and route-cost support.

**Work completed.** Added a cached-only audit mode to the existing canonical
market-state owner. It reopens the current event certificate, factory registry,
bounded exclusions and all 65,082 token proofs; identifies every complete flat
generation; content-validates the exact full-day chunk perimeter; and fails
closed with the complete active missing-decimals count before any correction
write. Added focused regressions for complete legacy-generation discovery and
active-pool missing-decimals concentration. Updated the findings guard from the
misleading first-file failure to the actual purpose-bound scientific boundary.

**DECISION:** `promote` the full-calendar token-anchor gap as the next D2 input
boundary; `park` correction refresh until exact anchors cover the 199 tokens
that can enter `main_v1`, and explicitly adjudicate the remaining irrelevant
pools rather than inheriting all 12,654 tokens or trusting provider decimals.

**Validation.** The focused and integrated suites passed 164 tests plus 72
subtests; the final focused rerun passed 38 tests plus 61 subtests. The canonical
cached input audit verified zero missing exact chunks and failed at the expected
12,654-token boundary. The final findings-freeze audit remains RED with five
blockers.

**Commit:** `c14517d` (cached correction-input audit, materiality boundary and
findings status).

**Blocking count:** 5.

**For the next iteration:**
- Resume in the existing token-anchor/materiality owners: derive the exact 199
  `main_v1` endpoint tokens from the top-200 daily pair selector, choose their
  deterministic event anchors, and extend exact evidence without refetching the
  already-complete event-log or provider partitions.
- Register a purpose-bound admitted pool perimeter for those endpoints plus the
  five locked vehicle candidates before regenerating the 35 V2 correction days;
  do not label the other active provider pools exact or silently decode them.
- After V2 corrections are current, rerun the full market-state preflight to
  expose and then address the five legacy V3 correction days. No market-state or
  route-cost shard was published in this iteration.

## 2026-08-14 — Purpose-bound full-calendar V2 corrections current

**Targeted check:** the absent release-grade `main_v1` route-cost panel through
its first full-calendar market-state prerequisite: exact token scale and current
event order for the 35 flat legacy V2 correction generations.

**REGRESSION-CHECK:** lane `D2-purpose-bound-exact-state`, graph edge
`D2-release -> D3-construction-audit`, and estimand best direct versus best
two-hop route for identical endpoints, UTC hour and USD 1,000, 10,000 and
100,000 notionals under `main_v1`. The base evidence remains V2 event release
`09335f9551339e45b19734f9513511beca4a11bcc82b47adfa3947509a17b5e0`;
the correction most at risk was treating audit-calendar or provider-reported
decimals as exact authority outside their certified perimeter. No provider
partition or certified 77-date release byte was fetched or rewritten.

**Scientific consequence and concentration.** The prior bound put 199
unaudited endpoint tokens in 382 of 6,800 selected pair-days and $280.831
million, or 0.5794%, of realised bridge volume, so the gap could change route
support and sample composition. The executable full-calendar union indeed
requires 199 exact endpoint proofs; 197 enter the active admitted V2 quote-pool
decoder, covering 137,535 formerly blocked provider event rows in 691 pools and
2,948 pool-days. The other two endpoint proofs do not justify admitting their
unrelated counterparties. Day-specific admission excludes 154,994 unrelated
pool-days and 3,167,393 provider rows, plus 12 rows already covered by the
certified bounded exclusion.

**Work completed.** Extended the existing market-state prerequisite owner to
reuse the canonical top-200 `main_v1` pair selector, separate the full-calendar
endpoint-anchor perimeter from day-specific active pool admission, select exact
PairCreated anchors, retain bounded RPC evidence, stamp a separate
purpose-bound registry, and publish through the existing marker-last correction
writer. All 35 generations are current. They reconcile 1,493,953 provider rows
to 1,493,978 exact events with 1,115 explicit corrections, 34 supplements and
nine receipt-proved exclusions; duplicate provider rows and remaining missing
token, pool and event rows are all zero. The full 11,009-target market-state
preflight now advances to `uniswap_v3/20230221` and identifies five flat V3
generations: 2023-02-21, 2024-12-06, 2024-12-20, 2025-01-13 and 2025-03-10.

**DECISION:** `promote` the purpose-bound V2 correction family as the current
full-calendar input; `park` market-state materialisation at the newly exposed V3
generation boundary. The broader 12,654-token provider perimeter remains an
explicit nonconsumer, not a data-acquisition objective.

**Validation.** Focused market-state, V2 evidence, route-cost, event-order,
token-decimals and findings-freeze suites passed 183 tests plus 11 subtests.
The live resolver completed all 199 anchors, every refreshed generation passed
its exact reconciliation, and the final findings-freeze audit completed RED
with five blockers.

**Commits:** `af951e2` (purpose-bound evidence and correction owner), `e7f6525`
(full-calendar endpoint perimeter), `bcfa73b` (findings boundary), and `08442ee`
(registry provenance).

**Blocking count:** 5.

**For the next iteration:**
- Resume at the five existing flat V3 correction generations, beginning
  `uniswap_v3/20230221`. Reopen their current raw/provider/exact inputs and
  bound identity, state-support and route-cost materiality before regeneration;
  do not fetch a new provider partition or assume the V2 purpose-bound decimals
  registry is a V3 state certificate.
- Amend the existing event-order/correction owner rather than adding another
  script. After all five V3 generations are current, rerun the full market-state
  preflight before any daily materialisation.
- No market-state ledger or `main_v1` route-cost shard was published in this
  iteration; the freeze audit's five blockers therefore remain honest.

## 2026-08-14 — Legacy V3 correction boundary current

**Targeted check:** the five flat Uniswap V3 event-order generations blocking
the full-calendar market-state prerequisite for release-grade `main_v1` route
costs and the stricter transaction-state frontier.

**REGRESSION-CHECK:** lane `D2-purpose-bound-exact-state`, graph edge
`D2-release -> D3-construction-audit`, and estimand best direct versus best
two-hop route for identical endpoints, UTC hour and USD 1,000, 10,000 and
100,000 notionals under `main_v1`. Evidence is the existing provider capture
and all 719 cached exact-log chunks for 2023-02-21, 2024-12-06, 2024-12-20,
2025-01-13 and 2025-03-10. The correction most at risk was treating provider
order, or a flat audit-span generation, as current exact-state authority. No
provider partition, exact-log chunk or RPC evidence was fetched.

**Scientific consequence and concentration.** This is a potentially
claim-changing state-identity defect, not metadata hygiene. It is concentrated
in Uniswap V3 and five isolated dates. The pre-regeneration bound found 13,062
of the 18,658 actions on 2023-02-21 intersecting the day-specific `main_v1`
pool perimeter; the later flat ledgers had zero, three, one and six intersecting
actions. Across the five dates, 342,679 of 545,172 provider events (62.86%)
lie in active pools joining selected endpoints and locked candidates. The
1,000 selected pair-days carry $9.587 billion of realised bridge volume. The
Nearly all legacy actions touch a candidate-linked pool, and a changed replay
state can alter availability or winners at any of the three notionals and later
hours. Stress-state concentration remains to be measured from corrected quotes;
its absence from the raw action ledger was not treated as evidence of
immateriality.

**Work completed.** Reused the existing
`scripts/reconcile_graph_event_order.py` and marker-last correction owner to
publish five current generations from cached exact evidence. They reconcile
545,172 provider events to 545,178 exact events through 18,671 order or payload
corrections, 18 supplements and 13 receipt-proved exclusions. Ten duplicate
provider rows are explicit, and unmatched provider and exact events are zero
on every date. Full reopening validates every generation and the complete
11,009-target market-state correction preflight now passes. Updated the live
findings boundary in place; no market-state partition, route-cost shard or
state-dependent estimate was published.

**DECISION:** `promote` all five current V3 correction generations as daily
materialization inputs; `park` state-dependent findings at the still-absent
full-calendar market-state ledger. Route-only findings remain closed and were
not reopened.

**Validation.** Graph event-order, V3 event-source, market-state migration,
state-data and findings-freeze suites pass 136 tests plus 11 subtests. The exact
full market-state correction preflight passes 11,009/11,009 targets. The final
`uv run python scripts/audit_findings_freeze.py` completed RED with five honest
blockers: E1 lock, model ledger, full-text literature ledger, route-cost panel
and two unchanged findings passes.

**Commit:** `7e7a31a` (V3 correction boundary and findings state).

**Blocking count:** 5.

**For the next iteration:**
- Resume through the existing full-calendar market-state builder now that its
  correction preflight passes. Use its storage forecast and release owner; do
  not add another correction path or refetch provider/exact inputs.
- Materialize and certify the daily ledger before launching `main_v1` quotes.
  Reopen the V3 event-source release against the new correction identities at
  its existing certificate boundary; do not restamp stale state partitions.
- No market-state ledger or `main_v1` route-cost shard was published here, so
  the freeze audit's five blockers remain the correct live count.

## 2026-08-14 — V3 event-source repeat-scan boundary corrected

**Targeted check:** the queued V3 event-source publication boundary preceding
the full-calendar market-state ledger and `main_v1` route-cost panel.

**REGRESSION-CHECK:** lane `D2-purpose-bound-exact-state`, edge `D2-release ->
D3-construction-audit`, and estimand best direct versus best two-hop route for
identical endpoints, UTC hour and USD 1,000, 10,000 and 100,000 notionals.
Evidence was the 13,093-chunk ordered V3 inventory and the 62-date corrected
canonical state. The correction most at risk was treating a manifest or
provider-reported statics as transaction-state authority.

**Scientific consequence and concentration.** The event-source boundary is
potentially claim-changing because V3 is concentrated in comparable route
opportunities and changed event order or payload can alter availability and
route winners. The completed global classification covered 147,376,618 logs:
144,879,555 factory-canonical and 2,497,063 quarantined. The later failure was
not missing economic evidence: nullable provider decimals occur systemically
across the audit calendar, including 29,320 rows and 495 pools on the first V3
audit date. Exact factory/token authorities already certify the pool statics.

**Work completed.** Amended only the existing event-source owner. Construction
now retains one hashed classification record binding ranges, event totals,
canonical/quarantine splits, reasons and quarantine-ledger identity. Ordinary
reopening binds the ordered manifest, frozen header, pool registry, correction
generations and released quarantine, then decompresses only audit-date chunks.
Focused tests prove manifest drift and changed audit-date events fail and that
out-of-audit-day payloads are not opened. Canonical comparison now accepts
absent provider token/decimal fields only when the certified pool authority
supplies them, while rejecting every present contradiction.

**Run result.** The authorized run completed its sole global classification
and installed the 410,526-block exact header snapshot, then stopped before the
first exact-versus-canonical comparison on the nullable-provider-static bug.
Elapsed time was 20,125.05 seconds; exact comparisons completed: 0/62. No V3
event-source release, market-state ledger or route-cost shard was published.

**DECISION:** `promote` the bounded reopen contract and exact-authority fallback;
`park` publication until one corrected attached run completes all 62 comparisons.

**Validation.** V3 event-source, data-release and freeze suites pass 106 tests
plus 72 subtests. The final findings audit remains honestly RED with five
blockers: E1 lock, model ledger, full-text literature ledger, route-cost panel
and two unchanged findings passes.

**Commit:** `c3a308b` (bounded V3 reopening and nullable-static correction).

**Blocking count:** 5.

**For the next iteration:**
- Resume the same event-source owner. The exact header snapshot is now complete;
  do not fetch it again. The prior full classification passed, but its in-memory
  quarantine ledger was lost when phase 3 failed, so a corrected construction
  run must reconstruct that ledger once before atomic publication.
- Confirm the run performs one global classification, 62 construction
  comparisons and one 62-date post-publication reopen; ordinary freeze must not
  open an out-of-audit-day payload. Report elapsed time and exact comparisons.
- Leave both queued Java interjections unchecked until publication and the
  immediate handoff to the existing full-calendar market-state builder occur.

## 2026-08-14 — V3 audit event source corrected and certified

**Targeted check:** the queued V3 event-source publication boundary preceding
the full-calendar market-state ledger and `main_v1` route-cost panel.

**REGRESSION-CHECK:** lane `D2-purpose-bound-exact-state`, edge `D2-release ->
D3-construction-audit`, and estimand best direct versus best two-hop route for
identical endpoints, UTC hour and USD 1,000, 10,000 and 100,000 notionals.
Evidence was the 13,093-chunk ordered V3 inventory and 62-date corrected
canonical state. The correction most at risk was treating provider statics or
a manifest as transaction-state authority.

**Scientific consequence and concentration.** The first corrected construction
run completed the single global classification, then found 8,183 discrepancies
among 4,640,561 audit-date core events (0.176%): 2,958 omitted identities and
5,225 payload/order mismatches. The payload defect was highly pool-concentrated:
5,118 swap mismatches sat in two pools, while omissions increased in the 2026
tail. This was potentially claim-changing for exact state and route availability,
so it could not be waived as metadata hygiene. The earliest two human-amount
rounding discrepancies were only 19--20 base units on roughly 5.95e35 raw units,
but the omitted identities and later exact-state mismatches required repair.

**Work completed.** Amended the existing V3 event-source owner with a no-network
correction mode. It reads only certified inventory Parquets in the full UTC-day
factory-consumer perimeter, validates all 62 plans before pointer publication,
reuses the installed exact header snapshot for 461 distinct supplement-block
proofs, and writes the existing correction-generation schema. The 62 generations
contain exactly 5,225 corrections and 2,958 supplements. The existing
audit-calendar builder then rematerialized all 62 canonical V3 partitions. A
publication-only directory-lineage failure occurred after every construction
comparison passed; file-level release inputs and bounded resume now reopen the
unselected bytes against current manifests, headers, registry, corrections,
quarantine and audit-date payloads without another global scan. The unreachable
failed generation was removed after the current pointer selected generation
`921dce9cacbc5c1b08592bd2713e6cef50efd723c4c2e65eab69e6d98e1d5e02`.

**Run result.** The post-repair attached construction run took 2:37:34.40. Its
one classification covered 147,376,618 logs: 144,879,555 factory-canonical and
2,497,063 quarantined. All 62 construction comparisons then passed over
4,640,561 core events. Bounded publication resume took 7:25.36 and independently
validated the staged generation before publication, then reopened the published
artifact and reran only the 62 audit-date comparisons. Ordinary reopening did
not decompress out-of-audit-day payloads. No provider or RPC acquisition ran.

**DECISION:** `promote` the V3 construction-audit event-source certificate;
`narrow` it explicitly to the 62-date audit calendar and keep full-calendar
daily V3/V4 state plus every state-dependent descendant red.

**Validation.** V3 event-source, Graph correction, data-release, findings-freeze
and market-state migration suites pass 144 tests plus 72 subtests. The final
findings audit remains honestly RED with five blockers: E1 lock, model ledger,
full-text literature ledger, route-cost panel and two unchanged findings passes.

**Commit:** `3561ae5` (corrected V3 audit event source and release evidence).

**Blocking count:** 5.

**For the next iteration:**
- Proceed immediately to the existing full-calendar market-state builder and
  then `main_v1`; the V3 audit source is now a current prerequisite, not a
  reason to rerun or beautify the certificate.
- A later supervisor interjection requests three M3 commits and one composition
  refresh only after this V3 unit is durably committed. This worker was under an
  explicit no-fetch/no-pull/no-rebase/no-push continuity notice, so it preserved
  the interjection untouched for supervisor reconciliation rather than syncing.
- `logs/grind-queue.md` changed externally during the run and remains the named
  unresolved synchronization-conflict path; do not edit it in this worktree.

---

## 2026-08-15 — Bounded recovery: rotation composition rebind

A recovery worker inherited a dirty tree from an interrupted iteration and committed the finished unit; no queue or standing-brief work ran, and no remote synchronization was performed.

**What was recovered.** The e0 rotation composition rerun at `eeda725` had completed on disk: four vehicle-transition-pair exhibit manifests rebound to D3 analysis-release generation `dbe24bb3` with byte-identical payloads, plus the first ranked pair-contribution ledger (194 MB Parquet) from `f52b43b` with its provenance sidecar and the new generation's certificate manifest. No tmp files remained; `ddvc.provenance.verify` reports ok for all six touched artifacts.

**Decision.** The contributions payload is gitignored under the push-safe rule (no large derived artifacts in git); its tracked manifest binds the exact payload identity and the producer regenerates it.

**Validation.** `tests/test_vehicle_rotation_composition.py` and `tests/test_vehicle_transition_pair_deck_values.py` pass (22 tests).

**Commit:** `057aa4c`.

**For the next iteration:**
- Pre-existing failure unrelated to this unit: `tests/test_vehicle_transition_e0.py::test_vehicle_transition_runner_rejects_missing_stale_and_out_of_release_d3_inputs` fails at HEAD in its own scratch workspace. After tampering the stamped panel, the context-level check now fires first with "model-run D3 certificate context requires current analysis inputs: …certificate.json=stale" while the test expects "not current|does not reproduce". Decide whether the check ordering or the test expectation is the contract, and fix as its own unit.

---

## 2026-08-15 — Composition E0 readout closes the 18:59 science handoff

REGRESSION-CHECK: purpose-bound estimand is the descriptive 2024→2026
realised-composition decomposition (raw conditional stable-share change, locked
`midpoint_common_exclusive_support_v1`); evidence generation is D3
analysis-release `dbe24bb3417a0f828127345b193a2abeb9596bdf47b337b2cc2d62b43115470c`;
the prior correction most at risk is the matched-market/realised-composition
language lock (no entry/exit, design, demand, or preference attribution). This
iteration mutates only the ledger and queue records — no estimator, panel, or
prose changed — so none of the three is disturbed.

**Queue state.** The integration half of the 2026-08-14T18:59 interjection and
the fast-forward half of the 12:03 M3 handoff were already on `main`
(f52b43b, 2b74fd7, 2bd6657, and 7072291 are all ancestors of HEAD via merge
`afd12fe`), and the composition rerun itself completed at `eeda725` and was
committed by the recovery worker in `c1447e7`. What remained of 18:59 was the
science readout; it is below, and the item is ticked in this commit. No V2
liquidity run (pool_capital_release pointer not verified current) and no V4
receipt selection (route-unit block_number contract not yet proved) were
launched, per the same interjection.

**Readout — all from exhibit sha `c14a536b…`, bound to certificate generation
`dbe24bb3…`, identity error ≤ 1.1e-16, 181 common month-days, descriptive
realised composition, noncausal.** Stable share of intermediated routes,
2024 → 2026, total change = within_common + common_pair_reweighting +
common_support_mass + exclusive_pair_contribution (pp):

| metric | scope | 2024 → 2026 | total | within | reweight | support | exclusive |
|---|---|---|---|---|---|---|---|
| count | pooled | 16.87→42.54 | +25.68 | −0.13 | +8.57 | −0.54 | +17.77 |
| count | cross-venue | 16.27→47.68 | +31.41 | −0.26 | +11.37 | −0.22 | +20.52 |
| count | single-venue | 17.00→38.07 | +21.08 | −0.27 | +4.43 | −0.44 | +17.35 |
| matched strict count | pooled | 17.43→42.07 | +24.64 | +0.01 | +7.94 | −0.66 | +17.35 |
| matched strict count | cross-venue | 16.94→46.62 | +29.67 | −0.17 | +10.36 | −0.40 | +19.88 |
| matched strict count | single-venue | 17.53→38.24 | +20.71 | −0.14 | +4.43 | −0.54 | +16.96 |
| strict value | pooled | 34.80→77.65 | +42.84 | −0.03 | +26.22 | −2.52 | +19.17 |
| strict value | cross-venue | 44.10→84.51 | +40.41 | −2.01 | +21.42 | −4.43 | +25.43 |
| strict value | single-venue | 31.47→68.39 | +36.92 | +0.58 | +26.58 | −1.28 | +11.03 |

The Shapley market-incidence bridge (pooled count, `shapley_market_incidence_
stable_bridge_v1`, identity error 0) splits the same +25.68 pp into market-pair
support bridge +9.83, observed market-activity reweighting +7.90, realised
vehicle-incidence reweighting +7.03, vehicle-role support bridge −0.39, and
within-pair stable share +1.31.

**Largest pair contributions** (ranked ledger, 4,593,314 rows, payload
gitignored, manifest-bound). Pooled count: USDT→WETH +2.17 and WETH→USDT +1.93
(common, reweighting), USDC→WETH +1.76, WETH→USDC +1.36, then
comparison-exclusive composition on WETH↔`0xaca92e…` (+0.68/+0.65) and
WETH→`0x829f4b…` +0.61, USDe→WETH +0.60 (common). Pooled strict value:
WETH→USDT +6.10 and USDT→WETH +5.94 (common, reweighting),
USDC→`0xa3931d…` +3.77 (comparison-exclusive), USDe→USDC +3.10 (common),
`0xa3931d…`→USDC +2.52 (comparison-exclusive), USDe→sUSDe +2.28 (common).
Cross-venue value adds one large negative: USDe→USDT −3.16 (common,
reweighting). Addresses left as hashes are not in `ddvc.asset_types`; labelling
them is a registry task, not a readout task.

**Interpretation (descriptive only).** Within-pair stable-share change is near
zero everywhere; the aggregate rotation is composition: reweighting toward
stable-friendly common pairs plus comparison-exclusive pair mass. Value-side
rotation leans more on common-pair reweighting; count-side leans on exclusive
pair composition. These are endogenous realised-composition margins, not
entry/exit effects, not design or demand attribution.

**Validation.** Freeze audit rerun this iteration: RED, same 5 blockers (E1
lock, model ledger, full-text literature ledger, route-cost panel, two
unchanged passes). No estimator or artifact mutated.

**Blocking count:** 5.

**For the next iteration:** the parked 21:58 table-header refinement is now
unblocked (fixed-effects exhibit is bound to the current certified release);
apply it next if this iteration does not. The 12:03 M3 J0 route-cost item
remains the standing large unit: route-cost panel manifest/provenance/scope for
the 113,822,022-row panel is the highest-value open blocker.

---

## 2026-08-15 — Parked table-header refinement applied (same iteration)

REGRESSION-CHECK: purpose-bound estimand is presentation only — the
pair-composition table header; evidence generation at risk is the three
dominance tables' presentation provenance (restamped through their own render
scripts against the unchanged fixed-effects exhibit bound to certificate
generation `dbe24bb3…`); the prior correction at risk is the JFE-register rule
that clustering is stated in the exhibitnote, not the header — the exhibitnote
in `paper/sections/03-dominance.tex` still states two-way clustering, so no
inferential disclosure was lost.

**What closed.** The 2026-08-14T21:58 parked queue item, unblocked by
`c1447e7`. `render_pair_composition` header changed from `Estimate in pp
(clustered s.e.)` to `Estimate in pp`; test assertion updated to the full
header row; all three tables (`pair_composition`, `dominance_rotation`,
`usdt_transition`) restamped via their render scripts without refusal;
`tests/test_dominance_tables.py` passes (8 tests); `paper/main.pdf` compiles
clean via Tectonic with the edited table (latexmk/TinyTeX on this host lacks
tikz — Tectonic is the working toolchain for the paper here too, matching the
deck).

**Blocking count:** 5 (unchanged; presentation-only unit — E1 lock, model
ledger, full-text literature ledger, route-cost panel, two unchanged passes).

**For the next iteration:** the only remaining unchecked queue item is the
12:03 M3 coordinator handoff. Its fast-forward half is done; the live half is
the smallest J0 route-cost release: manifest/provenance/scope for the
113,822,022-row route-cost panel (`route-cost panel exists` blocker), then
E1/D3 generation identities and the two unchanged findings passes. That is the
highest-value open unit.

## 2026-08-15 — Five of six absent literature companions re-materialized

**Targeted check:** `node B full-text literature ledger` (source-sets 27/33,
five-axis-cards 28/34), the highest-value blocker closable from this worktree.

REGRESSION-CHECK: purpose-bound estimand is none — this unit restores node B
literature evidence artifacts, no estimator, panel, or exhibit is touched; the
evidence generation at risk is the committed non-text disposition records in
`literature/pdf-sources.json` and the shared ignored corpus
`../defi-vehicle-currencies/literature/papers/`; the prior correction at risk
is canonical-owner routing for literature claims — records were amended in
place through their existing owners, and no pinned hash was rewritten except
where the archive framing is capture-specific by design and member-level
identity was proved first.

**Why it was red.** The six replication-package dispositions committed on
2026-08-09 (`d5e9590`, authored at UTC+8) pin exact bytes and sha256s, but the
git-ignored artifacts were never synced to this host: no copy existed in any
checkout or backup here. The route-cost panel release (`0121a26`, previous
iteration, no ledger entry was written) had already dropped the blocking list
to 4; this unit attacks the literature blocker.

**What closed.**
- `LeharParlour2024Uniswap`: Wiley supplement zip re-downloaded through the
  shared browser profile; sha256 equals the pinned `10c39614…` byte-for-byte.
- `Somogyi2026DollarDominanceFX`: 5,164,152,397-byte INFORMS zip re-obtained
  through the publisher's acknowledgment form; sha256 equals the pinned
  `5b02fac4…`.
- `GopinathStein2021Making`: fresh Dataverse capture matched all three pinned
  member hashes; the only differing bytes were one DOS timestamp pair
  repeated in six offsets, and a bounded brute force recovered the original
  capture stamp (2026-08-08 14:06:54), reproducing the pinned archive hash
  exactly. Installed byte-identically; no record change.
- `FlandreauJobst2009Empirics`: the ResearchGate URL is bot-walled, but the
  Wayback capture of the EH.net copy (live URL now 404) hashes to the pinned
  `37ce6f70…`, proving the two hosts served identical bytes. Installed; no
  record change.
- `AmitiItskhokiKonings2022Dominant`: Dataverse v1.1 re-download verified all
  55 members against publisher-declared MD5s (185,176,820 bytes, matching the
  note). The 2026-08-09 tar.gz framing used an unrecorded assembly procedure,
  so the disposition and note now carry a deterministic re-archive
  (45,254,976 bytes, sha256 `14c3b03e…`) whose exact tar/gzip parameters are
  documented in the note for byte-identical rebuilds. Member identity, not
  archive framing, is the stable scientific identity.

**Still open in this check.** `Mukhin2022InternationalPriceSystem`: openICPSR
is behind a Cloudflare challenge plus account login; automation cannot fetch
it. Two routes: sync the original 119,236,817-byte artifact
(`1e8e62e5…`) from the host that captured it on 2026-08-09 (M3/Studio), or log
into openicpsr.org once in the shared browser profile and run
`scratchpad/lit-materialize/fetch_hard_targets2.py mukhin`.

**Validation.** `tests/test_audit_findings_freeze.py` +
`test_literature_browser_helpers.py`: 78 passed, 15 subtests. Full freeze
audit rerun: RED, 4 blockers (E1 lock, model ledger, literature ledger now at
32/33 source-sets and 33/34 cards, two unchanged passes).

**Commit:** `4ba208d`.

**Blocking count:** 4.

**For the next iteration:**
- Closing Mukhin closes the literature blocker outright; see routes above.
- The E1 lock and model ledger blockers are structurally downstream of data
  that does not exist yet: the freeze requires stage=confirmatory, which
  requires the closed E0 exploration, and `close_exploration` demands all five
  template families executed — including `liquidity_allocation_e0`
  (blocked_capital_and_lp_flow_releases), `direct_cost_dominance_e0`
  (blocked_exact_state_release) and `routing_maturation_e0`
  (blocked_transaction_state_frontier). The exploration also binds to exactly
  one D3 generation, so starting it before those releases exist under one
  release guarantees a forced reopen. Do not start the exploration
  prematurely; the critical path runs through the Studio-lane exact-state and
  capital releases named by the claims' execution gates.
- The 12:03 M3 coordinator handoff stays unchecked: its remaining live parts
  are the E1/D3 generation identities (gated as above) and the two unchanged
  findings passes.

---

## 2026-08-15 — Bounded recovery: sanctioned scratchpad no longer reads as dirt

A recovery worker inherited untracked `scratchpad/` from the literature
re-materialization iteration; no queue or standing-brief work ran, and no
remote synchronization was performed.

**What was recovered.** Nothing was in progress: the previous iteration had
committed its full unit (`4ba208d`, `406c6b0`) and parked its probe scripts
under `scratchpad/lit-materialize/` exactly as the grind brief directs — but
`scratchpad/` had never been gitignored, so its first real use read as
non-queue worktree dirt and triggered this recovery, the same failure mode as
the e0 test scratch fixed in `eeda725`.

**Decision.** Ignore `scratchpad/` in `.gitignore`. Its contents are
host-local by design (absolute browser-profile paths, captures), so tracking
them would break the push-safe rule; the committed ledger's Mukhin resumption
route (`scratchpad/lit-materialize/fetch_hard_targets2.py mukhin`) references
the on-disk path on this host and is unaffected. All scratchpad files were
preserved byte-for-byte.

**Validation.** `git check-ignore` matches all three scratchpad files against
the new rule; `git ls-files scratchpad/` confirms no tracked file is shadowed;
`git status --porcelain` is clean apart from this unit.

**Commit:** see this commit.

---

## 2026-08-15 — Bounded recovery: downstream consumers rebound to the migrated route release

A recovery worker inherited an uncommitted in-progress unit: the
`--rebind-downstream-consumers` mode of
`scripts/migrate_route_release_markers.py`, its tests, and fourteen already-
rebound provenance sidecars. No queue or standing-brief work ran, and no
remote synchronization was performed.

**What was recovered.** The marker rebind in `873b29c` restored the route
release itself but left its byte-unchanged consumers pinned to the pre-
expansion ledger/marker identities. The previous worker had written and run
the bounded fix: a proof-carrying sidecar rebind that moves only the migrated
quality-ledger and per-day-marker identities (partition identities are never
migratable), refuses any payload, code, or foreign-input drift, restamps the
two migration-owned artifacts whose code fingerprint moved with the amended
owner script, and republishes the endpoint composition pointer only when the
installed generation reproduces exactly. Rebound targets: the three processed
route panels, the endpoint composition release (pointer + four member
sidecars), and the five second-ring vehicle-transition exhibits; plus the
restamped `unified_route_quality` panel and exhibit.

**Validation.** `tests/test_route_marker_migration.py`: 37 passed, including
the ten new rebind/restamp/refusal tests. A second
`--rebind-downstream-consumers` run reports `already current` for all eleven
targets (0/11 rebound) with each target passing `verify()` — the state is
idempotent and current against the certified release.

**Commit:** see this commit.

---

## 2026-08-15 — Retroactive record: liquidity-capital V2 predictability adjudication (66f8858)

The previous science iteration committed its full unit but exited without a
ledger entry; recorded here so the handoff chain stays complete. The
pool-capital release opened the `liquidity_capital_v2_predictability`
execution gate; the runner executed the locked reciprocal design on the full
2020--2026 V2 calendar (five candidates, candidate and origin-date fixed
effects, 30-day score-HAC, Holm within direction, month-block bootstrap) and
every route/capital measure pair failed the pre-stated decision rule in at
least one direction, so the claim records a non-pass under its own falsifier.
Exhibits, support panel, LaTeX table, provenance, and the regenerated
analysis-release certificate are in `66f8858`.

---

## 2026-08-15 — Deck liquidity-timing frame answered from the certified V2 release

REGRESSION-CHECK: purpose-bound estimand at risk was
`liquidity_capital_v2_predictability` (E0, adjudicated non-pass); the evidence
generation at risk was its committed exhibit and sidecar, consumed read-only
through `require_certified_presentation_source`; the prior corrections at risk
were E0-to-deck-only routing (paper untouched), no hand-typed measured
literals, and predictive-not-causal interpretation — all held.

**Queue state.** The 12:03 M3 handoff item stays unchecked: its fast-forward
half was already done (`7072291` is an ancestor); its live half (E1/D3
identities, two unchanged passes) remains gated on Studio-lane releases. The
literature blocker's only remaining unit (Mukhin openICPSR, 32/33) is still
closed from this host: hostname `studio` does not resolve and openICPSR sits
behind Cloudflare plus account login. NEEDS-JAVA: either log into
openicpsr.org once in the shared browser profile (then run
`scratchpad/lit-materialize/fetch_hard_targets2.py mukhin`) or sync the
119,236,817-byte artifact `1e8e62e5…` from the Studio capture.

**What closed.**
- `deck/sections/04-results.tex`: the "Does liquidity lead vehicle use---or
  follow it?" frame now displays the adjudicated answer — neither direction
  predicts at 1/7/30 days (smallest Holm p 0.17); the only strong longer-
  horizon pattern is negative (higher-capital pool-days lose 2.21 pp episode
  share per log point over 120 days, both capital measures concordant).
  Evidence identity lives in source comments (commit `66f8858`, analysis
  release `414f0c27…`); no audience-facing badges.
- `scripts/build_liquidity_capital_v2_deck_values.py`: proof-carrying values
  builder; refuses to render if a reciprocal pair starts passing, a cell turns
  Holm-significant, or the long-horizon negative pattern vanishes — the frame
  text cannot silently outlive its evidence. Five new tests.
- Deck rebuild exposed that the WETH provisional snapshot payloads were absent
  on this host (deck could not compile). Regenerated through the owner
  (`run_route_methodology_robustness.py --provisional-snapshot`): deck-values,
  robustness, and resampling payloads reproduced byte-identically; the
  heterogeneity jsonl restamped under the current code fingerprint with
  downstream display values unchanged.
- The page-13 binding guard was red before this unit: the two WETH frames
  pinned evidence commit `ead5c72f…`, which is dangling in every history
  reachable from this clone and unreachable even in the primary checkout.
  Rebound both frames to `66f8858`, the commit carrying the current exhibits.

**Validation.** Deck compiles clean via Tectonic; page 14 visually inspected;
`audit_deck_evidence.py` PASS; 46 tests across deck-evidence, deck-values,
predictability, and robustness files pass. Full freeze audit rerun: RED, same
4 blockers (E1 lock, model ledger, literature 32/33, two passes) — no
regression.

**Commit:** `4d64476`.

**Blocking count:** 4.

**For the next iteration.** All four blockers are externally gated (Studio
exact-state/frontier releases; Mukhin needs Java or Studio). Do not start the
E0 exploration before the blocked template families' releases exist under one
D3 generation. The paper's rivals section (`paper/sections/05-rivals.tex`)
still frames liquidity timing as an open question; after J1 admits the
predictability result, refresh that passage from the same exhibit. The
`liquidity_capital_flow_predictability` claim (LP flows) remains gated on
`blocked_capital_and_lp_flow_releases` — do not proxy it with the stock
result.

---

## 2026-08-15 — Bounded recovery: V1 registered route case

A recovery worker inherited a dirty tree from an interrupted iteration and committed the finished unit; no queue or standing-brief work ran, and no remote synchronization was performed.

**What was recovered.** The tree held one untracked, fully written producer, `scripts/build_v1_route_case.py`, with no outputs yet. Its stated purpose — replace the deck A6 frame's symbolic forced-route glyph with an authentic registered transaction — matched the frame's own "pending authentic transaction rows" marker, so the bounded unit was: run the producer, verify the selected case, wire the frame, and record the external token-identity verification the manifest note cites.

**What ran.** The producer scanned all 550 mandate-era raw V1 swap days (1,376,633 transactions; 144,442 clean two-row candidates; 129,810 exact-leg matches) and registered `0x4dca160d…a0ca16` (block 9,674,728, 2020-03-15, 439.129687312060203802 ETH on both legs, string-identical). Blockscout token transfers (retrieved 2026-08-15) confirm the legs and identify the tokens: 250 MKR into V1 exchange `0x2c4bd0…0957`, 49,892.40 DAI out of `0x2a1530…8667`, via a DEX.AG proxy. Block and timestamp match the manifest exactly. The verification is recorded in `docs/finding-v1-forced-vehicle.md` section 1 (new registered-case subsection), which the manifest's token-identity note points at.

**Validation.** Deck compiles clean via Tectonic (only pre-existing 04-results overfull vbox); page 24 visually inspected twice (first pass caught edge-label/node overlap, fixed); `audit_deck_evidence.py` PASS; `ddvc.provenance.verify` ok for both new artifacts. No ruff on this host; the script passed py_compile and its real run.

**Commit:** `38aaa86`.

**For the next iteration:**
- The paper (`paper/`) does not yet cite the registered case; if the V1 section wants the single-transaction trace, consume `output/exhibits/v1_route_case.json` rather than retyping values.

---

## 2026-08-15 — Conformance loop closed on Studio after the rivals citation

REGRESSION-CHECK: purpose-bound estimand at risk was the V1 forced-route
composition shares (certified route-only facts, consumed read-only through the
`v1_route_case_deck_values.tex` macros); the evidence generation at risk was
`output/exhibits/v1_route_case.json` (commit `38aaa86`) plus the venue-optics
exhibit, regenerated only through its own owner; the prior corrections at risk
were "word substitution is not prose revision" (no prose changed — this pass
records a reread), "never fake a gate" (the tectonic fallback really compiles
both PDFs), and E0-to-deck-only routing (the predictability result stayed out
of the paper). All held.

**Queue state.** The 12:03 M3 handoff item remains unchecked: fast-forward
half done (`7072291` ancestor), live half still gated on Studio releases.

**What closed.** The previous paper edit (`12a2e8b`) left the writing node's
closing gate red: `check_jfe_rhetoric_review.py` flagged a stale review and
shifted paragraph coverage for `paper/sections/05-rivals.tex`. Recorded a
genuine reread in `docs/reviews/paper-rhetoric.json`: the quantified v1
mandate incidence judged against Carletti et al.'s quantified named reform
(raw lines 120–160), the registered MKR→DAI trace against Lehar–Parlour's
named transaction decode (raw lines 2320–2338), coverage updated to
[9,11,15,22,24], and the paper's transaction case registered as a fingerprinted
draft use with its rhetorical job and evidence handoff.

**Host defects found and fixed (both silently disabled the loop on Studio):**
- PyMuPDF 1.28 prints its deprecation warning to **stdout** on `import fitz`,
  corrupting the JSON extraction, so `measure_venue_optics.py` read all 14
  exemplars as "could not read" and the venue-structure stage hard-failed.
  Fixed by importing the renamed `pymupdf` module.
- `check_deliverable_conformance.py`'s build stage hardcoded `latexmk`, absent
  on this host; it now falls back to `tectonic -X compile --keep-logs` in the
  same order `paper_tables.py` already uses.

**Validation.** `check_deliverable_conformance.py` exits 0: all blocking
checks pass; paper 29 pages / 0 undefined; deck 33 pages / 0 undefined; two
advisories (discovered constructions, prose shape) remain visible. Venue
optics/conventions/outliers/shape exhibits regenerated with provenance.
`test_venue_corpus.py` + `test_venue_optics.py`: 6 passed, 3 subtests. Freeze
audit rerun: RED, same 4 blockers (E1 lock, model ledger, literature 32/33,
two passes) — no regression.

**Commit:** `0da03a1`.

**Blocking count:** 4 (all externally gated: Studio exact-state/frontier
releases; Mukhin needs Java or Studio — NEEDS-JAVA stands from 2026-08-15).

**For the next iteration.** The venue-optics advisory shows the draft below
the exemplar first quartile on words (10,958 vs 18,738), equations, citations,
and greek — never pad, but the gap will close as gated results land. The
conformance loop now runs end-to-end on Studio; run it after every paper/deck
content change, not only the section suites. Paper prose beyond certified
route-only facts stays tiered; the liquidity-timing passage in 05-rivals still
waits for J1.

---

## 2026-08-16 — Recovery: anchor-manifest lineage repin after the marker migration

Bounded recovery worker. A prior worker exited with the marker migration's
downstream rebind in progress; nothing was discarded, reset, or stashed, and no
remote was contacted.

**What was in progress.** The proven route marker migration republished the
route quality ledger (`data/processed/unified_route_quality.parquet`,
456,408 → 459,750 bytes) and its sidecar, and rebound the downstream route
panels and the endpoint composition release. The one consumer the rebind did
not reach was the token-decimals anchor manifest, which pins a byte hash for
every selection input — including exactly those two republished files.

**What this worker finished.** `repin_anchor_manifest_migrated_lineage()` in
`scripts/migrate_route_release_markers.py`, wired as the last step of
`rebind_downstream_route_consumers()`. It fails closed: the republished panel
must verify exactly current, the manifest's `lineage_inputs_sha256` must agree
with its own records, and drift on any path other than the panel/sidecar pair
is a refusal. The durable unresolved-decimals ledger's manifest pin is carried
forward only across a recorded owner repin whose `anchors_sha256` perimeter is
byte-identical; every scientific field is untouched. Repins are appended to a
`lineage_repins` history under the existing rebind policy.

**Validation.** `tests/test_route_marker_migration.py`: 45 passed (5 new,
covering owned-only movement, idempotence, foreign lineage drift, non-current
panel, digest disagreement, lagged ledger pin, foreign ledger pin).
`test_token_decimals.py`, `test_v2_token_anchor_materiality.py`,
`test_provenance_inputs.py`, `test_provenance_publication.py`,
`test_endpoint_candidate_composition_release.py`, `test_v2_event_completeness.py`:
169 passed. On the real tree the manifest carries three recorded repins, all
26,882 lineage inputs hash exactly, and the ledger pin matches the manifest.
Every one of the 17 touched artefacts verifies `ok` except the four endpoint
composition release members, whose staleness is a pre-existing code-fingerprint
drift stamped at `05b68e9` (2026-08-13) with `inputs_current` and
`content_current` both true; the release's own currency check
(`current_endpoint_candidate_composition_release`) passes.

**Not done (recovery scope).** The done gate was not run and the queue was not
started. The 2026-08-16T00:03Z Java interjection (so-what / analogy pass on
paper and deck) is recorded unchecked at the head of `logs/grind-queue.md` and
is the next clean-boundary item.

---

## 2026-08-16 — Queue: Java's so-what / analogy pass on paper and deck

REGRESSION-CHECK: the purpose-bound estimand at risk was the pooled 2024→2026
stablecoin route-share change decomposed into within-pair choice, common-pair
reweighting, common-support mass, and exclusive-pair composition — a descriptive
realised-composition identity, not a causal margin. The evidence generation at
risk was `output/exhibits/vehicle_transition_pair_{decomposition.jsonl,
contributions.parquet}` under D3 certificate `25c755ae…` and endpoint generation
`5fb7cbf…`, read only through the existing certified-presentation owner; no
estimator ran. The prior corrections at risk were "do not call pair composition
entry/exit effects" (2026-08-14), "word substitution is not prose revision", and
the tiered-prose rule. All held.

**What closed.** The head queue item, Java's 00:03 interjection, in all three
parts.

*(1) The compositional reading at first mention.* It now lands wherever the
rotation first appears, not only in the conclusion: the abstract's third
sentence, the introduction's headline paragraph (which now states the
matched-market estimate and its standard error at the point where the aggregate
is first reported), the end of Section 3.1, and the first deck frame that shows
the rotation. Section 3.2 opens on the three margins and says which one did not
move, following Makarov–Schoar's decomposition opening (raw lines 886–991), and
the deck's closing banner states the positive so-what. The single audience-facing
use of "mechanically" is gone, rewritten as *where trading happens rather than
which intermediary a given trade selects*.

*(2) The illustrative margin slide.* New deck frame "Three margins move an
aggregate vehicle share" names one real ordered pair per margin with its own
cells: USDC→WBTC (stable share 10.5%→35.9%, +0.05 pp; margin total −0.1 pp),
USDT→WETH (0.36%→4.52% of routed activity, 7,447→54,112 routes, +2.17 pp; margin
total +8.6 pp), and USDS→WETH (0→3,390 routes, all stablecoin-intermediated,
+0.13 pp; margin total +21.0 pp, less −3.3 pp from pairs traded only in 2024).
The same three pairs now appear in Section 3.2.

*(3) The corridor bridge.* The introduction motivates the second margin with the
China–Brazil renminbi clearing arrangements, footnoting the PBoC/BCB memorandum;
the conclusion adds an external-validity paragraph mapping the two margins onto
corridor composition; a new deck frame sits before the close. All three state
that no settlement share is measured and make no causal or policy claim.

**Where the evidence came from.** Not a new script: the canonical presentation
owner `scripts/build_vehicle_transition_pair_deck_values.py` was extended to read
the certified `vehicle_transition_pair_contributions.parquet` and emit the margin
macros. It fails closed — the contributions must carry the descriptive mechanism
label and the pair-level allocation scope, their aggregate total must equal the
decomposition's, and each component must reconcile its aggregate term before any
pair is named. Only pairs whose two endpoints resolve in the canonical token
taxonomy are eligible, so a slide can never print a bare contract address; since
the long tail of newly traded assets is unlabelled, every named pair is
accompanied by its margin total and the prose says outright that the example
understates its margin.

**Validation.** `test_vehicle_transition_pair_deck_values.py`,
`test_deck_evidence.py`, `test_paper_prose.py`: 34 passed, 438 subtests (4 new
tests: labelled selection, aggregate-term reconciliation, causal-label refusal,
no-labelled-contributor refusal). `check_deliverable_conformance.py` exits 0 —
all blocking checks pass; paper 30 pages / 0 undefined, deck 35 pages / 0
undefined. `audit_deck_evidence.py` PASS. `check_jfe_rhetoric_review.py` current
after recording genuine rereads (Makarov–Schoar 29–38 and 886–991, Li–Ye–Zheng
26–34 and 96–214, Carletti et al. 120–199, Mayer 62–80, Huang et al. 1588–1660)
and registering the corridor analogy as a third draft use. Changed pages of both
PDFs inspected; the margin frame and the close banner were re-laid-out after the
first inspection showed clipping.

**Discrepancy worth Java's eye.** The queue's *count* figures do not reproduce:
it cites common-pair reweighting +7.9 pp and pair-composition +9.8 pp, whereas
the exhibit's pooled count terms are +8.6 pp reweighting and +17.8 pp net
exclusive-pair (+21.0 gross, −3.3 from pairs traded only in 2024). The *value*
figures (+26.2 / +19.2 pp) reproduce exactly, as do the matched-market estimates
(+0.2 pp SE 0.8; −1.3 pp SE 2.2) and both totals (+25.7 / +42.8 pp). Everything
written into the paper and deck comes from the exhibit, not the queue text.

**Commit:** `e26bd69`.

**Freeze gate.** RED, 6 blocking checks: node D capital release current; node E1
specification lock; node D claim-input provenance gate; empirical model ledger;
node B full-text literature ledger (source-sets 32/33, five-axis cards 33/34);
two unchanged findings passes (stable_passes=0). That is two more than the 4
recorded on 2026-08-15. The two additions are both node-D data checks and were
first observable after the marker-migration and anchor-manifest-repin commits
`7e22186`…`6b4050d`, whose recovery worker states it did not run the done gate.
Nothing in this iteration touched a data node: the only artifacts written were
the presentation macro file and its provenance sidecar, plus the regenerated
venue-optics/prose diagnostics that the conformance loop owns.

**For the next iteration.** Take the two node-D blockers first — they are the
only ones that changed state, and they are ordinary provenance/currency
bookkeeping on a release whose scientific identity is not in question, so the
standing rule applies: prove the rows and bytes unchanged, close the bookkeeping
through the existing owner, and return to estimation. Do not treat them as a
reason to rewrite the release. The M3 12:03 handoff item remains the only other
unchecked queue entry and is still gated on Studio. If the pair-composition
evidence is ever regenerated, rerun
`scripts/build_vehicle_transition_pair_deck_values.py` before compiling anything:
Section 3.2 and the new deck frame both name individual token pairs through its
macros, and the producer fails closed rather than printing a stale pair.

---

## 2026-08-16 — Node D: the V2 capital release the corrected scan left stale

**Check targeted.** The two node-D blockers the previous iteration flagged as
the only ones that had changed state: `node D capital release current`
(`ValueError: pool_capital provenance is not current: pool`) and `node D
claim-input provenance gate` (3 of 7 inputs stale).

**REGRESSION-CHECK.** Estimand at risk: purpose-bound V2 deposited capital and
its two downstream liquidity panels. Evidence generation: `00cb588b…` published
at `8a965cd`. Prior correction most at risk: `7e22186`, the `needsComplete` V2
mints/burns admission — a rebuild must not silently re-derive the capital panel
on a different raw perimeter than the one the release certified.

**Diagnosis before touching anything.** Exactly one of the release's ten code
sources moved since its stamp: `src/ddvc/raw_certification.py`, from `7e22186`.
That commit exempts null `amount0`/`amount1`/`logIndex` on rows whose
`needsComplete` guard is exactly true, for the `mints` and `burns` streams only.
The capital panel reads `hourly_reserves`. So the exemption cannot reach it —
and that was verified rather than argued: all 2,248 uniswap_v2 and 2,126
sushiswap_v2 bound reserve days reproduce identical `input_fingerprint`,
`expected_rows` and `expected_bytes` under the corrected certificate. The other
two stale inputs (`token_price_daily.parquet`,
`v2_audit_token_decimals.parquet`) are byte-identical payloads whose sidecars
`6b4050d` restamped. Scientific identity unchanged; the defect is bookkeeping,
which is what the standing rule says to close through the owner and move on.

**What was done.** `scripts/build_pool_capital_panel.py` rebuilt the release:
generation `084f1e16…` republishes all four artifacts **byte-identical** to
`00cb588b…` (8,456,802 pool / 6,891,901 candidate / 1,577,834 quarantined rows;
identical payload digests; identical reserve perimeters). That equality is the
evidence the release is unchanged, not an assumption. Then
`scripts/build_liquidity_capital_flow_panels.py --family v2` rebuilt
`liquidity_capital_v2_candidate_day.parquet` (11,660 rows) and
`liquidity_capital_v2_exact_horizons.parquet` (46,640 rows) off it. Both now
verify `ok`; the capital release resolves.

**Defect found and bounded.** Unlike the capital build, the two V2 panels are
**not bit-reproducible**. Two consecutive runs off one capital release produce
different bytes. Cell-level comparison: max relative difference 3.3e-15 on
`v2_deposited_capital_usd`, `v2_log1p_deposited_capital_usd` and
`v2_five_candidate_capital_share` (24 ULP), and 4.5e-10 on
`future_v2_five_candidate_capital_share_change`, where differencing two
near-equal shares amplifies the same base error. Cause: the capital columns are
DuckDB parallel float sums, so the reduction order varies per run. Nothing at
1e-15 can reach an estimand, sample composition, coefficient or inference — the
V2 predictability standard errors are ~1e-2, ten orders of magnitude away.
Disclosed in a source comment at the owner so a moved byte hash reads as
"rebuilt", not "revised".

**DECISION: park** the determinism fix. Remedy if it is ever taken up:
serialise the DuckDB aggregation (`--threads 1`) or fix a rounding precision on
the capital columns. Cost is another full republish and a further downstream
cascade, and the second option is a scientific choice about precision, not a
build setting. Chasing bit-reproducibility now would be the "100 percent
metadata cleanliness as implicit research objective" the brief forbids. Revisit
only if byte instability starts blocking the two unchanged findings passes; it
cannot today, because `stable_passes` is a declared state field, not a hash
comparison.

**Regression this iteration introduced, stated plainly.**
`output/exhibits/liquidity_capital_v2_predictability.jsonl` was current at
`c0543e3` and is now stale, because its two recorded panel inputs moved bytes.
Its values did not change (bounded above). It cannot be restored now:
`scripts/run_liquidity_capital_v2_predictability.py` fails closed with `INPUT
BLOCKED: model runner lacks its DDVC_D3_CERTIFICATE/DDVC_D3_GENERATION
binding`, and that binding is only issued by the E0 exploration harness, which
is itself blocked. Nothing currently depends on the exhibit's currency: the
freeze gate does not list it, `audit_deck_evidence.py` passes, and the deck
quotes it through `liquidity_capital_v2_deck_values.tex`, which is byte-current
against the unchanged `.jsonl`. **Resumption point: when the E0/D3 binding
exists, rerun that estimator first and confirm the V2 predictability nulls
reproduce before anything else consumes them.**

**Mukhin, re-confirmed not actionable.** The single missing literature
source-set and card is still `Mukhin2022InternationalPriceSystem`. Traced to
ground this time: the source set's `non_text_dispositions` entry is `status:
materialized` for
`literature/papers/2022-…ReplicationPackage-supplement-openicpsr-v1-reconstructed.tar.gz`
(119,236,817 bytes, `1e8e62e5…`), and that file is absent from the canonical
papers store (`../defi-vehicle-currencies/literature/papers/`, 108 entries,
other reconstructed tarballs present) and from every sibling and backup
checkout. Everything else about the set closes: main artifact, appendix
companion, all three discovery checks. **NEEDS-JAVA stands from 2026-08-15**;
the two routes in that entry are unchanged. Downgrading the disposition to
`unavailable` would turn the gate green and is refused — the package was read
and inspected, and the note records that inspection.

**Validation.** `test_pool_capital_panel.py`, `test_capital_validation.py`,
`test_liquidity_predictability.py`,
`test_liquidity_capital_v2_predictability.py`,
`test_liquidity_capital_v2_deck_values.py`, `test_artifact_release.py`,
`test_provenance_inputs.py`, `test_provenance_publication.py`: 242 passed.
`check_deliverable_conformance.py` exits 0 — all blocking checks pass; paper 30
pages / 0 undefined, deck 35 pages / 0 undefined; 2 advisories (over-used
constructions, prose shape) unchanged. `audit_deck_evidence.py` PASS. The deck
PDF differs only in build metadata — extracted text is byte-identical and the
page count is unchanged at 35 — so no page changed and none needed inspection.

**Commit:** `0cde857`.

**Blocking count: 4** (was 6). Both node-D checks closed. Remaining: node E1
specification lock; empirical model ledger; node B full-text literature ledger;
two unchanged findings passes.

**For the next iteration.**
- The four survivors are all still structurally gated, exactly as recorded on
  2026-08-15: E1 and the model ledger need the closed E0 exploration, which
  needs releases the Studio lane has not published; the literature ledger needs
  Java or Studio for Mukhin. None of them is picked up by re-reading the gate.
  Do not start the exploration early — it binds to one D3 generation and would
  force a reopen.
- So the next iteration should advance a claim, exhibit, rival test,
  interpretation, deck frame or paper section rather than the gate. This one
  was data engineering and closed real blockers; two in a row would violate the
  brief's step 6.
- Disk: generation `00cb588b…` (695 MB) is superseded but retained. Removing it
  is a data deletion and was not taken unilaterally.
- The M3 12:03 handoff stays unchecked. Its fast-forward part is satisfied
  (`7072291` is an ancestor of `HEAD`); its live remainder is the E1/D3
  generation identities and the two unchanged findings passes, both gated above.

## 2026-08-16 — Section 5 becomes a rival test: route construction rejected

**Targeted check.** None. The freeze gate is RED at the same four blockers
(node E1 specification lock; empirical model ledger; node B full-text
literature ledger; two unchanged findings passes), all still structurally
gated exactly as recorded on 2026-08-15 and re-confirmed here: E1 and the model
ledger need the closed E0 exploration, and the literature ledger needs Java or
Studio for Mukhin. The previous iteration was data engineering, so under step 6
this one had to advance a scientific object instead.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: spec-lock claim
`vehicle_transition`, whose object is the exact **two-leg** stable share — new
complexity prose must not restate the >2-leg stratum as that estimand. Evidence
generation at risk: `intermediation_complexity_rival.jsonl` behind
`require_certified_presentation_source`; every pre-existing macro had to keep
its value. Prior corrections at risk: the `forbidden_interpretation` bar on
aggregator causality and on reading leg count as efficiency (the producer's own
note says leg count is a complexity proxy), the 2026-08-14 rule against calling
pair composition entry/exit, and the tiered-prose bar on exact-state
coefficients. All three held; the diff contains no aggregator or efficiency
claim and no exact-state number.

**What was wrong.** Section 5 asked "What can account for the rotation?", built
up the Krugman liquidity mechanism over a full paragraph, and then reported no
estimate at all. Its second paragraph restated Section 3.4's venue-span result
with no numbers and no evidence comment. Meanwhile the certified stratification
that answers the leading rival — did the rotation come from how routes were
built? — sat unused in `intermediation_complexity_rival.jsonl`, reaching
neither the paper nor the deck.

**What was done.** Section 5.1 is now a rival test in the Bolton--Kacperczyk
grammar (raw passages reread at lines 1221--1260 and 1635--1702: open on the
named alternative, motivate why it could bind, answer with a magnitude, carry
the survivor forward). The alternative is stated at full strength with its own
2024 base rates — stablecoins already carried 44.5% of native-plus-stable
intermediary episodes on routes of more than two legs against 16.9% on two-leg
routes — and then rejected: two-leg routes gain +25.4 pp by count (SE 1.05) and
+43.9 pp by value (2.02); longer routes gain +16.3 pp (1.86) and +35.9 pp
(1.68). Both classes move and the shortest-path class moves further, so
between-class reweighting cannot supply the aggregate change. All four
venue-span by path-length cells rise; the weakest is +17.0 pp by count (1.36)
and +25.6 pp by value (1.52). A scope paragraph follows the result rather than
displacing it.

Section 5.2 now closes the liquidity argument instead of opening it. The
classical depth channel is defined *within* a market, so it predicts
substitution inside continuing pairs — which is precisely the margin the
decomposition found still. The matched-pair interval already in Section 3.2
(within-pair increases bounded above +1.7 pp) therefore confines depth to
market **formation**, not to intermediary substitution in established markets.
That is a new interpretive claim from evidence already certified, and it is the
affirmative form of Java's compositional so-what.

**Owner discipline.** No new object. `src/ddvc/provisional_results.py` — the
canonical macro owner already reading this exhibit for the two-leg cells —
gained the multi-leg and weakest-cell macros and a `_weakest_complexity_cell`
helper that **refuses to render the four-cell joint statement unless every cell
change is positive**, so the prose sentence cannot silently outlive the data.
The generated macro file diff is 12 pure insertions: every pre-existing value
is byte-identical.

**Deck.** The existing venue-scope frame carries the path-length result in
place; no new frame was added. Page 14 rendered and inspected (no overflow,
cells legible), 35 pages, `audit_deck_evidence.py` PASS. Its `EVIDENCE-COMMIT`
was corrected from the figure's commit `a0c54e9` to the exhibits' commit
`111230a`, which is where the numeric cells actually come from; the audit
parser rejects a parenthetical, so the figure's own commit is recorded on the
following comment line.

**Two undelivered forward references repaired.** The introduction's roadmap
promised Section 5 would relate the evidence to "exchange reach", which the
section no longer does under that name; it now names the rival test. Section 2
promised Section 5 would examine "the major stablecoins and backing groups
separately" — nothing in the manuscript ever delivered backing groups. It now
points to Section 3.3, which does separate USDT and USDC.

**DECISION: park** importing the V2 deposited-capital reciprocal result into
the paper. Verified to ground this iteration:
`scripts/run_liquidity_capital_v2_predictability.py` still exits `INPUT
BLOCKED: model runner lacks its DDVC_D3_CERTIFICATE/DDVC_D3_GENERATION
binding`. Supplying that env binding by hand would bind the estimator to a D3
generation ahead of the E0 exploration and force a reopen, which the 2026-08-15
entry explicitly warns against. The brief's rule that presently irreproducible
estimates stay out therefore governs: the deck's existing frame is
grandfathered on byte-current macros, but the paper takes no new dependency.
Section 5.2 carries a source comment recording exactly this, and the resumption
point from the previous entry is unchanged — when the E0/D3 binding exists,
rerun that estimator first.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass,
paper 31 pages / 0 undefined (was 30), deck 35 pages / 0 undefined, the same 2
advisories (over-used constructions, prose shape). `audit_deck_evidence.py`
PASS. `check_jfe_rhetoric_review.py` current after the ledger was rewritten
with four opening judgments, eight paragraph handoffs, and the relocated v1
transaction-case fingerprint. 234 prose/exhibit/provenance/deck/rhetoric tests
pass.

**Pre-existing failure, not introduced here.** `tests/test_route_cost_panel.py`
and `tests/test_route_state.py` fail at collection with `v2_event_source_release
provenance is not current: input changed:
data/manifests/data/processed/v2_audit_token_decimals.parquet.prov.json`.
Confirmed present at HEAD before this change by stashing the working tree and
rerunning. It does not block the freeze gate, which reports the V2 event-source
certificate as "not required by the executable claim-input perimeter". **The
next iteration should decide whether that manifest drift is real or bookkeeping
before it spreads to a consumer that matters.**

**Commit:** `93281aa`.

**Blocking count: 4** (unchanged).

**For the next iteration.**
- The gate cannot be advanced without Studio or Java; do not re-derive that.
  Keep advancing scientific objects.
- Remaining unused certified rival evidence, in descending value:
  `venue_technology_rival.jsonl` (asset-type excess use by year on the full
  venue perimeter) and `routing_technology_windows.jsonl` (pre/post windows
  around auto-router releases). The second sits under spec-lock claim 1, whose
  `execution_gate` is `blocked_transaction_state_frontier` and whose
  `forbidden_interpretation` bars an aggregator-causality reading — treat any
  use of it as descriptive window composition only.
- The four venue-shape shortfalls (words, equations, citations, greek all below
  the exemplar p25) are the standing structural gap in the manuscript. Section 5
  grew by roughly 400 words this iteration; the shortfall is concentrated in the
  thin Section 6, which defines the cost benchmark and reports nothing because
  route cost is blocked.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes.

## 2026-08-16 — The venue pricing-technology rival, rejected on rebuilt evidence

**Targeted check.** None. The freeze gate is RED at the same four blockers
(node E1 specification lock; empirical model ledger; node B full-text
literature ledger; two unchanged findings passes), verified again before and
after this iteration. All four remain structurally gated exactly as recorded on
2026-08-15: E1 and the model ledger need the closed E0 exploration, and the
literature ledger needs Java or Studio for Mukhin. The previous iteration
advanced a scientific object, so this one could have been engineering; it
turned out to be both, because the evidence it needed was stale.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: the venue rival's
object is the **excess-use ratio** (intermediary share divided by endpoint-demand
share) on complete route components within a venue scope, annual, on the full
route calendar. It is not the spec-lock `vehicle_transition` two-leg stable
share and not the matched January--June window governing Sections 3 and 5.1;
the prose says so and the table note repeats it. Evidence generation at risk:
`venue_technology_rival.jsonl`, which had to be proved current before any macro
could quote it. Prior correction at risk: "calendar time is not treatment" plus
the `forbidden_interpretation` bar on technology and aggregator causality — a
venue-scope restriction is a composition test, and Curve's zero is a support
statement about route components, never a causal null. Both are written into
the subsection's boundary paragraph.

**The evidence was stale, and not only on bookkeeping.** The exhibit failed
`require_certified_presentation_source` because its sidecar predates the
`payload_identity` schema. That alone would have been the "certificate mismatch
is not scientific evidence" case the brief tells us to close through the owner
and move on. It was not that case: `code_fingerprint(record["code_sources"])`
no longer matched the record, and the recorded input directory held **2,277**
entries against **2,332** today. The exhibit was stale on producer code and on
calendar. Rerunning `scripts/test_venue_technology_rival.py` over all 2,332
days and four venue scopes (about 45 minutes, 8 workers) was the only honest
route, and the numbers did move: the 2024 constant-product stable value ratio
went from 0.95 in the stale file to 0.78 in the rerun.

**Cross-producer reproduction, worth recording.** The rerun's 2026 all-venue
count ratios are stable **1.41** and native **0.77**, matching the certified
`docs/findings-freeze.md` figures (1.41 and 0.77) that come from
`vehicle_excess_use.jsonl`, a different producer on a different path. That is an
independent check on both.

**The result.** The rival is that the rotation is an adoption of exchange
technology: Curve's invariant interpolates toward a flat curve near parity, so a
stablecoin leg became cheap once venues priced pegged assets on a curve built
for them, and the stable-specialised pools grew over the same years. Two facts
reject it.

1. Restricting to route components every leg of which prices on the
   constant-product invariant — a rule common to Uniswap v1--v4 and SushiSwap
   v2--v3 and unchanged across the sample, covering **84.8%** of 2026
   candidate-currency intermediary episodes — does not weaken the value
   rotation but **sharpens** it. Stable excess use rises 0.78 to 1.33 there
   against 0.84 to 1.24 across all venues: **+0.55 against +0.40**. Native falls
   to 0.62. By count the two paths are nearly identical (1.28 to 1.42 against
   1.27 to 1.41), which is the honest reading, since stablecoins were already
   over-represented as intermediaries by count from 2020.
2. **All-Curve route components carry zero intermediary episodes in every year
   of the sample.** The venue that embodies the alternative supplies no
   intermediation at all: the specialised invariant is used to exchange two
   pegged assets directly, so the pricing rule that makes stablecoin legs cheap
   operates on trades the vehicle measure excludes by construction. Curve legs
   still appear inside cross-venue routes, which the all-venue scope counts;
   what the sample contains no instance of is a route intermediated entirely
   within the specialised invariant.

Balancer is reported as a composition diagnostic and carries no weight: 39,536
intermediary episodes in its busiest year against 8,767,213 in the
constant-product scope's, with ratios swinging accordingly. The producer leaves
it technologically unlabelled because the source mixes weighted and stable pool
families.

**Owner discipline.** No new estimator and no new exhibit.
`src/ddvc/venue_tables.py`, the existing venue-table owner, gained
`venue_technology_rival_values` and its renderer;
`scripts/tabulate/render_venue_technology_rival.py` follows the one-script-per-table
convention of `render_venue_coverage.py`. `src/ddvc/provisional_results.py`, the
existing macro owner, gained the scope macros behind three guards that withhold
the **entire** macro set if the constant-product movement turns negative, stops
exceeding the all-venue movement, or if any all-Curve scope-year ever reports an
intermediary episode. The table renderer distinguishes a scope-year with no
route components ("no routes", Balancer 2020) from one whose components carry no
intermediation ("no intermediation", Curve throughout) instead of printing the
same blank for both.

**Consumers the shared owner invalidated.** Amending `venue_tables.py` made
`venue_coverage.tex/pdf` stale, and regenerating the macro file made
`pair_composition` and `usdt_transition` stale. All three were re-rendered
through their own scripts; their `.tex` bytes are unchanged and only the PDF
build metadata moved.

**Prose.** Section 5.2 is new, written from the Bolton--Kacperczyk rival grammar
after rereading the raw passages at lines 1221--1260 and 1635--1702: open on the
alternative at full strength with its mechanism and its favourable timing,
answer with a magnitude, state plainly how the restricted magnitude compares
with the unrestricted one, then bound what a scope restriction licenses. The
"about 10%--20% smaller" honesty move in that passage is the model for the
sentence comparing +0.55 with +0.40, and the industry-fixed-effects result at
BK 1246--1260 is the precedent for reporting that a restriction can strengthen
rather than absorb an effect. Table 5 reports all four families for all seven
years. The introduction roadmap now names the pricing rule, and the section's
closing paragraph carries four features rather than three.
`docs/reviews/paper-rhetoric.json` records the new opening, five new paragraph
handoffs, the relocated v1 transaction-case fingerprint, and a rewritten
section judgment.

**Deck.** No new frame. The existing venue-scope frame carries the
pricing-family sentence in place. Its figure was resized from
0.46 to 0.41 `\textheight` with a compensating `\vspace` so that the frame's
overfull-box set is **identical to the pre-change baseline** (I compiled the
baseline to confirm). Page 14 was rendered and inspected: no overflow, figure
legible, 35 pages, `audit_deck_evidence.py` PASS. The frame's ESTIMAND-BOUNDARY
comment now records that the pricing-family sentence is a separate estimand on a
separate support.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass;
paper 34 pages / 0 undefined (was 31), deck 35 pages / 0 undefined, the same 2
advisories (over-used constructions, prose shape). The `rather_than`
construction alarm did fire at 0.802 per 1,000 words against a corpus maximum of
0.572; three complete thoughts were rewritten, not word-substituted, and it is
back in range at 0.501. `audit_deck_evidence.py` PASS.
`check_jfe_rhetoric_review.py` current. 333 prose/exhibit/provenance/deck/
rhetoric/table/venue tests pass.

**Two pre-existing failures, neither introduced here.**
`tests/test_route_cost_panel.py` and `tests/test_route_state.py` still fail at
collection on `v2_audit_token_decimals.parquet.prov.json` drift (carried from
2026-08-16, first entry). **I did not close it**: a `verify()` probe on that
manifest did not return within ~40 minutes — its sidecar is 26 MB — and I
stopped it rather than let it starve the producer rerun. It remains the right
next diagnosis and it is bounded: the freeze gate reports the V2 event-source
certificate as "not required by the executable claim-input perimeter".
Separately, `tests/test_audit_findings_freeze.py::test_optional_artifact_gates_follow_only_executable_claim_inputs`
fails on `docs/specification-lock.json`, which no commit since `66f8858` has
touched and which this iteration did not modify.

**Commit:** `8b30ba6`.

**Blocking count: 4** (unchanged).

**For the next iteration.**
- Do not re-derive that the gate needs Studio or Java. Keep advancing scientific
  objects.
- Remaining unused certified rival evidence: `routing_technology_windows.jsonl`
  (pre/post windows around auto-router releases). It sits under spec-lock claim
  1, whose `execution_gate` is `blocked_transaction_state_frontier` and whose
  `forbidden_interpretation` bars an aggregator-causality reading — any use is
  descriptive window composition only. With this iteration's pass, the
  venue-technology exhibit is now consumed and no longer on that list.
- The `v2_audit_token_decimals` manifest drift is the standing engineering
  question. Budget for a slow `verify()` on a 26 MB sidecar, or read the sidecar
  directly and compare recorded against observed identity fields rather than
  calling the full verifier.
- The four venue-shape shortfalls (words, equations, citations, greek, all below
  the exemplar p25) remain. Section 5 gained roughly 550 words here; the
  shortfall is still concentrated in the thin Section 6, which defines the cost
  benchmark and reports nothing because route cost is blocked.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes.

## 2026-08-16 — The routing-software rival, rejected on three dated router releases

**Targeted check.** None. The freeze gate is RED at the same four blockers (node
E1 specification lock; empirical model ledger; node B full-text literature
ledger; two unchanged findings passes), verified before and after. All four
remain structurally gated on Studio or Java exactly as recorded since
2026-08-15. Queue: only the standing M3 12:03 handoff is unchecked, and its live
remainder is still the E1/D3 generation identities and the two unchanged passes.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: the router-window
object is **market-wide route composition** — indirect-route incidence, true
intermediation incidence, cross-exchange share of intermediated routes, mean legs
and mean exchanges per indirect route — in symmetric 60-day windows either side
of three dated public releases, on the full daily route calendar. It carries
**no currency split at all**, so no sentence from it may be read as a stablecoin
or native quantity, and it is not the matched January--June estimand of Sections
3 and 5.1. Evidence generation at risk: `routing_technology_windows.jsonl`.
Prior corrections at risk: "calendar time is not treatment" and the spec-lock
`routing_maturation_rival` `forbidden_interpretation` barring an
aggregator-causality reading; its `execution_gate` is
`blocked_transaction_state_frontier`, so only the descriptive topology windows,
which are not part of that blocked frontier, were used. A fourth correction was
found during the check and is recorded below.

**The evidence was already current, unlike last iteration's.** Code fingerprint
matched the recorded `code_sources`; the sole input
`cross_venue_routing_daily.parquet` is byte-identical at 1,257,321 bytes and
sha `5b4b48fd…`; the artefact sha matches; `require_certified_presentation_source`
passes. No rerun. This is the "prove identity, then estimate" path the brief
asks for, and it cost minutes rather than the 45 the venue rerun took.

**A would-be fake robustness, caught before it reached prose.** The exhibit
carries `full` and `balanced` venue scopes, and every one of the twelve rows is
identical to sixteen digits. That is not two scopes agreeing; the balanced
five-venue perimeter *is* the full perimeter until 2023-04-05, when the later
entrants first contribute, and all three windows sit in 2021--2022. Reporting it
as a robustness check would have been an invented one. It is instead reported as
what it is — the venue set is held fixed by construction over these windows —
and `routing_window_values` refuses the table and every macro if the two
perimeters ever diverge, which is what a window moved past 2023-04-05 would do.

**The result.** The rival is that automated path search manufactured the
intermediary. Three facts answer it.

1. **Intermediation does not step up at any release**: the share of economic
   routes carrying a third asset between the endpoints moves **-5.67, +0.83 and
   -0.71** percentage points, from 20.8% before the first release to 12.5% after
   the last. The largest single increase is +0.8 pp.
2. **Path length is as still**: mean legs per indirect route move by at most
   **0.049** across the six windows. Indirect routing as a whole falls 3.7 pp at
   the first release and moves less than half a point at the other two.
3. **The margin that does move is exchange span**, which is the margin a router
   should move: the cross-exchange share of intermediated routes rises **+2.5 pp**
   and **+3.1 pp** at the first two releases and changes -2.0 pp at the third.
   Routers integrated the venue set without sending trades through more assets.
   That is the spec-lock's own `admissible_interpretation` — integration expands
   while true intermediation contracts — reached from the exhibit rather than
   assumed.

**Three limits, all in the prose, none discovered by a referee.** The first
release's later window and the second's earlier window share thirty days, so the
comparisons are not independent. The third release's earlier window
(2022-09-18 to 2022-11-16) **contains the November 2022 failure of a large
centralised exchange**, so the composition change there belongs at least as much
to that event as to the router. And a release date is when a contract became
callable, not when traders began routing through it.

**Owner discipline.** No new estimator, no new exhibit, no rerun.
`src/ddvc/venue_tables.py` — which already owned the Section 5 venue rival table
— gained `routing_window_values`, `render_routing_technology_windows` and
`router_event_date_text`, and its docstring was broadened from "venue-rival" to
"rival-scope" tables. `scripts/tabulate/render_routing_technology_windows.py`
follows the one-script-per-table convention.
`src/ddvc/provisional_results.py` gained the router macros behind
`_router_window_changes`, which withholds the **entire** macro set if
intermediation ever rises by a full percentage point at a release, if mean path
length moves by 0.05 legs, if intermediation stops falling at a majority of
releases, or if the balanced perimeter stops reproducing the full one. Six new
tests cover the renderer and three cover the producer guards.

**Two stale durable records repaired in place.**
`docs/router-identification-feasibility.md` owned the pre-rebuild figures for
these exact windows under a heading that says so; it now carries the rebuilt
figures beside them. **Every sign is unchanged**, which is an independent check
that the rebuild did not move the qualitative reading.
`scripts/tabulate/README.md` was missing `render_venue_technology_rival.py` and
`tab:venue-technology` from the previous iteration; both are now listed along
with this iteration's renderer and table, and the generated/inline counts are
corrected to six of thirteen.

**Consumers the shared owners invalidated.** Amending `venue_tables.py` made
`venue_coverage` and `venue_technology_rival` stale; regenerating the macro file
made `pair_composition`, `usdt_transition` and `dominance_rotation` stale. All
were re-rendered through their own scripts. Every `.tex` byte is unchanged; only
PDF build metadata moved.

**Prose.** New Section 5.2, "The software that assembles the path", inserted
between path complexity and the pricing rule because 5.1's closing sentence
already hands off to it; the pricing subsection's opening now reads "third
alternative". Written after rereading the raw NYSE-autoquote passage at
`literature/text/2011-HendershottJonesMenkveld2011Algorithmic-…:439-560`, whose
grammar is: describe the institutional change concretely, name what it did *not*
change, name the channel and for whom it operates, and state plainly what the
design can and cannot support ("we cannot test this conjecture using the
available data"). The subsection uses that order to reach the opposite
conclusion about design, since a router release is market-wide and admits no
staggered comparison. The introduction roadmap and the section's closing
paragraph, now five features rather than four, both name the software.
`docs/reviews/paper-rhetoric.json` records the new opening, five new paragraph
handoffs, the relocated v1 transaction-case fingerprint, and rewritten section
progression and exit judgments.

**A citation attempted, measured, and withdrawn.** Citing
`HendershottJonesMenkveld2011Algorithmic` passed the source-admission gate at
21/21 but moved the already-blocking literature ledger from
`source-sets=32/33; five-axis-cards=33/34` to `32/34; 33/35`: its card is
complete and claim-verified and its source set is declared, but the
autoquote-dates workbook declared in `literature/pdf-sources.json`
(57,856 bytes, sha `8cff31e8…`) is **absent from the shared PDF corpus at
`/Users/java/projects/defi-vehicle-currencies/literature/papers/`**, so
`non_text_dispositions_closed` fails. Rather than make a blocking check worse or
fetch outward, the design paragraph now states the requirement generically —
a technology granted to some securities before others lets the waiting ones
absorb everything else moving in the market — which is general field knowledge
and needs no citation. The admission record is **kept** as an uncited comparator
with the reason written into its rationale, and the raw passage remains the
registered rhetorical exemplar. Ledger figures are back at baseline: 32/33,
33/34, cited 20/20.

**NEEDS-JAVA.** Materialising
`https://faculty.haas.berkeley.edu/hender/Autoquote%20Dates.xls` into the shared
corpus would close the HJM source set and let Section 5.2 cite the design
directly. It is an outward network fetch and a write outside this worktree, so I
did not do it. The expected bytes and sha256 are already recorded, so the fetch
is verifiable on arrival.

**Deck.** No new frame. The existing venue-scope frame (page 14) carries the
sentence in place: "Nor does automated path search: intermediation incidence
never rises by more than +0.8 pp at 3 public router releases, though
cross-exchange reach widens." Adding it overflowed the frame by 25.9pt, so the
surrounding text was tightened (not padded) and the figure resized 0.41 to
0.34 `\textheight`; the frame's overfull-box set is now **identical to the
pre-change baseline** — the third box is the same 5.06264pt, shifted seven lines
by the added source comment. Page 14 rendered and inspected: no overflow, figure
legible, 35 pages, `audit_deck_evidence.py` PASS. The frame's ESTIMAND-BOUNDARY
comment records the router sentence as a third estimand on a third support with
no currency split.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass;
paper 35 pages / 0 undefined (was 34), deck 35 pages / 0 undefined, the same 2
advisories. `check_jfe_rhetoric_review.py` current. `audit_deck_evidence.py`
PASS. 404 prose/exhibit/provenance/deck/rhetoric/table/venue/routing/literature
tests pass. Pages 15--18 of the paper rendered and inspected.

**Pre-existing failures, none introduced here, and the count is larger than
earlier entries suggested.** The **full** suite (excluding the two files that
error at collection) reports **13 failures**, and I verified by stashing the
working tree that the set at HEAD is **byte-identical**:
`test_audit_findings_freeze.py::test_optional_artifact_gates_follow_only_executable_claim_inputs`,
`test_variable_registry.py::test_source_does_not_generate_csv_artifacts`,
three in `test_vehicle_role_models.py`, one in `test_vehicle_transition_e0.py`,
and seven in `test_weighted_quote.py::RoutePanelWiringTests`. Earlier entries
reported only two because they ran the filtered prose/exhibit subset. Separately,
`tests/test_route_cost_panel.py` and `tests/test_route_state.py` still error at
collection on `v2_audit_token_decimals.parquet.prov.json` drift.

**Commit:** `431287a`.

**Blocking count: 4** (unchanged).

**For the next iteration.**
- Do not re-derive that the gate needs Studio or Java. Keep advancing scientific
  objects.
- **There is no unused certified rival evidence left.** Both exhibits the
  2026-08-15 entry listed are now consumed. The next scientific unit has to come
  from a different lane: the thin Section 6 (defines the cost benchmark and
  reports nothing because route cost is blocked), a heterogeneity cut of an
  existing certified exhibit, or a new estimator on released data.
- The `v2_audit_token_decimals` manifest drift is still the standing engineering
  question. Budget for a slow `verify()` on a 26 MB sidecar, or read the sidecar
  directly and compare recorded against observed identity fields.
- The eleven long-standing test failures above are unowned. None is in the
  paper/deck/exhibit path, but they should be classified once so a real
  regression is visible against them.
- The four venue-shape shortfalls remain: words 13,756 against p25 18,738;
  equations 11 against 25; citations 29 against 39; greek 6 against 7. Section 5
  gained roughly 600 words here.
- Consider renaming `src/ddvc/venue_tables.py` to `rival_tables.py` at a future
  consolidation: two of its three tables are now Section 5 rivals rather than
  venue tables. Not done here because it churns five consumers for no scientific
  gain.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes.

---

## 2026-08-16 — How many markets carry each margin: the breadth of the rotation

REGRESSION-CHECK: the purpose-bound estimand at risk was the pooled 2024→2026
stablecoin route-share change decomposed into within-pair choice, common-pair
reweighting, common-support mass, and exclusive-pair composition — a descriptive
realised-composition identity, not a causal margin. The evidence generation at
risk was `output/exhibits/vehicle_transition_pair_contributions.parquet` under
D3 certificate `25c755ae…` and endpoint generation `5fb7cbf…`, read only through
the existing certified-presentation owner; no estimator ran and no release was
rewritten. The prior corrections at risk were "do not call pair composition
entry/exit effects" (2026-08-14), the pair-level allocation scope that excludes
the common-support mass bridge, and "word substitution is not prose revision".
All held.

**Why this unit.** The freeze gate is RED on the same four Studio/Java-gated
blockers, so under step 5 the highest-value available work advances a claim. The
previous entry recorded that no unused certified rival evidence remained and
named a heterogeneity cut of an existing certified exhibit as one of three open
lanes. This is that cut, and it answers the first question a referee asks of the
three-margin result: the totals say how large each margin is, never how many
markets produce it, and a total near zero never says whether nothing moved or
whether movements cancelled.

**What closed.** `scripts/build_vehicle_transition_pair_deck_values.py` — the
canonical reader of the certified contributions ledger, already used to name one
example pair per margin — now also derives, for pooled route-count *and* pooled
dollar weighting, the number of gaining and losing pairs per margin, its gross
gain and gross loss, the largest single pair's share, and the pair counts
reaching half and nine-tenths of the gross gain. It fails closed: the gains and
losses must reconcile the margin total they are reported against, the exclusive
term must reconcile jointly, and the concentration ranks must be ordered. No new
script, artifact, or owner was created.

**The result** (pooled, count unless stated). The two composition margins are
economically different objects. Pairs traded only in 2026 contribute through
**18,446** ordered pairs, the largest supplying **3.2%** of that margin, with
**1,386** needed for nine-tenths of it — a broad extension of the trading
network. Reweighting among continuing pairs is the opposite: **7** pairs supply
half of its **+17.2 pp** gross gain, and it nets to **+8.6 pp** only because
**2,817** continuing pairs lose activity weight (**−8.6 pp** between them). By
value the reweighting margin is more top-heavy still (5 pairs behind half of a
+38.0 pp gross gain). Within continuing pairs, **1,575** raise their stablecoin
share and **1,489** lower it (+1.3 against −1.4 pp by count, +2.3 against −2.4
pp by value), so the near-zero matched-market term is an *offset*, not an
absence of movement — a sharper statement of Java's so-what than "about zero".

DECISION: **promote**, at exact scope — descriptive, non-causal, pooled
2024–2026 pair-level allocation excluding the common-support mass bridge.

**Paper.** A new paragraph closes Section 3.2, written from the raw movement of
Bolton–Kacperczyk §3.5 (raw lines 1899–1935: concede that a handful of units
could drive the result, report the test, interpret what the answer implies), now
registered as a third exemplar for the section and as a handoff at line 78 in
`docs/reviews/paper-rhetoric.json`. It ends on a contribution-relevant point: a
matrix recording which pairs trade at all — the historical exchange structure of
Flandreau and Jobst (2009) — registers the extensive margin and is silent on the
weight margin.

**Deck.** No new frame. The existing "Three margins move an aggregate vehicle
share" frame carries one added sentence; its three panels were tightened from
4.55cm to 4.3cm and the leading space from 0.16cm to 0.06cm, because the first
attempt pushed the last line of the note off the slide. The frame's 0.20pt
overfull vbox is now **gone** and the deck's remaining two boxes are byte-equal
to the pre-change baseline. Page 13 rendered and inspected three times across
the fix.

**Two regressions I introduced and closed inside this iteration.**
1. `neither_nor` went OVERUSED (0.545 against a corpus maximum of 0.294) because
   the draft paragraph used two of them. Both were rewritten as positive
   statements, not synonym-swapped.
2. `test_venue_optics.py::test_exhibit_density_reaches_the_first_quartile`
   (citations) failed at 0.002075 against 0.002081 — the added ~220 words with
   no citation. Closed by the Flandreau–Jobst sentence above, which is
   substantive rather than filler; density is now 30/14,012. This also moved
   "structural resemblance to the venue" from WARN to ok.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper 36 pages / 0 undefined (was 35), deck 35 pages / 0 undefined, 2
advisories. `audit_deck_evidence.py` PASS. 48 prose/exhibit/deck/optics/table
tests plus the producer's own 15 (3 new: breadth reconciliation, value-margin
reconciliation, dollar-weighted allocation required). Full suite mid-iteration:
**14 failures**, of which 13 are the byte-identical long-standing set recorded on
2026-08-15 and the fourteenth was the venue-optics citation regression above,
now fixed and re-verified. `tests/test_route_cost_panel.py` and
`tests/test_route_state.py` still error at collection on the
`v2_audit_token_decimals.parquet.prov.json` drift.

**Commit:** `4687ebd`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- A killed pytest run leaves `d3-release-test-*/` in the repo root and in
  `data/manifests/`. Only the E0 analogue was ignored; both D3 patterns are now
  in `.gitignore`. If you kill a test run, check `git status` before `git add -A`.
- The same breadth machinery is now available for any other certified pair-level
  allocation. The obvious next scientific cut in this lane is *which* corridors
  carry the top of the reweighting margin — whether the top 7 pairs share an
  endpoint asset, a venue, or a size class. That needs no new data, only the
  labelled subset of the same ledger, and it would test whether the
  concentration is a WETH-endpoint artefact.
- Section 6 still defines the cost benchmark and reports nothing; it remains
  blocked on route cost and is still the largest structural hole in the paper.
- Venue-shape shortfalls after this pass: words 14,012 against p25 18,738;
  equations 11 against 25; citations 30 against 39; greek 6 against 7.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still
  needs Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — endpoint eligibility inside the composition margins

**Targeted check.** None of the four blockers is reachable from this worktree:
node B is Mukhin (NEEDS-JAVA, restated 2026-08-15), node E1 and the empirical
model ledger both wait on the Studio D3 generation and certificate identities,
and the two unchanged passes need a quiet gate rather than a unit of work. The
previous iteration was claim-advancing, so under step 6 this one had to advance a
claim too. I took the cut the last ledger entry nominated: whether the top of the
reweighting margin is a WETH-endpoint artefact.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: the pooled
2024--2026 `midpoint_common_exclusive_support_v1` term `common_pair_reweighting`,
descriptive and non-causal — split, never re-estimated, with the locked calendar
and formula ID untouched. Generation at risk:
`vehicle_transition_pair_contributions.parquet` on the current certified release,
read-only through `require_certified_presentation_source`; no producer rerun, no
release rewrite. Prior correction at risk: the M3 affirmative boundary that WETH
eligibility explains most of the count rotation but not the strict-value
rotation. The result sharpens that boundary at corridor level and does not
reopen it.

**What the split is.** A route with wrapped ether at an endpoint cannot use
wrapped ether as its intermediary, so in the native-versus-stablecoin comparison
its stablecoin share is one in both years. Those corridors move the aggregate
only through composition. Membership is decided by one contract address, so
unlike the named-example machinery it does not depend on the token taxonomy and
classifies the unlabelled tail as reliably as the majors. The producer proves the
identity on the certified allocation before reporting: every WETH-endpoint pair
must carry stablecoin share one in both years and a within-pair contribution of
exactly zero, or every macro is withheld. Both hold exactly on the real data
(max |within-pair pp| = 0.0 across 1,499 count and 1,469 value pairs).

**Result.** 1,499 of 26,547 continuing pairs, 5.6%, have a WETH endpoint; their
routed-activity share rises 20.9% -> 33.0% by count and 25.8% -> 41.3% by value.
By count they supply +6.3 pp of the +8.6 pp reweighting margin (73.3%) and
+13.9 pp of the +21.0 pp new-pair margin (65.9%). By value they supply only
+11.2 pp of +26.2 pp (42.6%) and 16.0% of the value new-pair margin. The value
rotation's top corridors are non-WETH: USDe->USDC, USDe->sUSDe, DAI<->USDC,
sUSDe->USDC, USDC->crvUSD. **DECISION: promote.** The count rotation leans on
corridors that had no intermediary to choose; the dollar-weighted rotation does
not. As a by-product the near-zero within-pair term is defended: WETH-endpoint
pairs contribute exactly zero to it, so it is not an average diluted by frozen
corridors — all of it comes from pairs whose intermediary was a live choice.
This is the strongest available support for Java's 00:03 so-what reading, and it
cost no new data.

**Where it landed.** All of it inside the existing owner,
`scripts/build_vehicle_transition_pair_deck_values.py` (new `_endpoint_eligibility`
plus an `ELIGIBILITY_MARGINS` block), not a new script. It is a different object
from `run_route_methodology_robustness.py`'s WETH-exclusion sensitivity, which
drops these corridors and re-estimates the matched within-pair change rather than
splitting the composition margins; both source comments say so, so a later worker
does not merge them.

**A fixture defect the new guard exposed.** The deck-values test fixture put
within-pair movement on WETH-endpoint pairs, which the data cannot produce. It
now respects the identity: five continuing pairs, three contestable and two
endpoint-locked at stablecoin share one. The within-pair named example therefore
moves from USDC->WETH to USDC->USDT. This was a real fixture error, not a
concession to the new check.

**Paper.** A new paragraph closes Section 3.2, written from the movement of
Bolton--Kacperczyk 3.2 (raw lines 1245--1260: name a structural feature of the
data that could account for the result, pose the reader's question, say what you
add, report an answer whose direction cuts against the expectation the question
set up). The rhetoric ledger carries the new sha, the handoff at line 86, and the
renumbered transitions.

**Deck.** No new frame. The margins frame's closing line gains one clause with
the count/value contrast. Adding it produced a 16.25pt overfull vbox, closed by
tightening the three panels from 4.3cm to 3.95cm; the deck's remaining two boxes
(8.14pt at line 65, 5.06pt at line 221) are byte-equal to the pre-change
baseline. Page 13 rendered and inspected — no clipping.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper 36 pages / 0 undefined, deck 35 pages / 0 undefined, the same 2
advisories. `audit_deck_evidence.py` PASS. 64 prose/exhibit/deck/optics/table/
spine/provenance tests pass, including 3 new eligibility tests.

**Commit:** `abfc8e3`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- **The citation-density test is now within ~109 words of failing.** Draft is
  30 citations / 14,305 words = 0.002097 against a first-quartile density of
  0.002081. Any prose pass that adds more than about 109 words without adding a
  citation will break
  `test_venue_optics.py::test_exhibit_density_reaches_the_first_quartile`. Plan
  the citation before the paragraph, not after.
- Venue-shape shortfalls after this pass: words 14,305 against p25 18,738;
  equations 11 against 25; citations 30 against 39; greek 6 against 7.
- The obvious follow-on in this lane is the same eligibility split applied to the
  *venue* dimension rather than the endpoint asset: whether the count rotation's
  eligible corridors are concentrated in single- or cross-exchange scope. The
  contributions ledger already carries `reporting_scope`, so it needs no new data
  and the same producer can carry it.
- Section 6 still defines the cost benchmark and reports nothing; it remains
  blocked on route cost and is still the largest structural hole in the paper.
- `tests/test_route_cost_panel.py` and `tests/test_route_state.py` still error at
  collection on the `v2_audit_token_decimals.parquet.prov.json` drift; unchanged
  by this iteration.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still
  needs Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — the eligibility split taken inside each venue scope

**Targeted check.** None of the four blockers is reachable from this worktree,
for the same reasons the last two entries record: node B is Mukhin
(NEEDS-JAVA, 2026-08-15), node E1 and the empirical model ledger both wait on
the Studio D3 generation and certificate identities, and the two unchanged
passes need a quiet gate rather than a unit of work. `origin/main` is already at
`e4fd414`, so the M3 fast-forward has landed and its live remainder is unchanged.
The previous iteration was claim-advancing, so under step 6 this one had to
advance a claim too. I took the cut the last ledger entry nominated: the same
eligibility split applied to the venue dimension.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: the scope-specific
`midpoint_common_exclusive_support_v1` terms `common_pair_reweighting` and
`exclusive_pair_contribution` at `reporting_scope` single_venue and cross_venue,
pooled 2024--2026, descriptive and non-causal -- split only, calendar and formula
ID untouched. Generation at risk: `vehicle_transition_pair_contributions.parquet`
on the current certified release, read-only; no producer rerun, no release
rewrite. Prior correction at risk: the M3 affirmative boundary (WETH eligibility
carries most of the count rotation but not the strict-value rotation) and
yesterday's pooled split. Discharged concretely: after the refactor every pooled
macro in the deck-values file is byte-identical, verified by diff.

**Result.** By route count the reweighting margin is **+4.4 pp** within a venue
against **+11.4 pp** across venues, and WETH-endpoint corridors carry **55.3%**
and **82.9%** of them. The part contributed by corridors that *did* have a choice
is the same in both scopes: **+2.0 pp** within a venue, **+1.9 pp** across. The
entire cross-venue excess in the count margin is therefore corridors that were
stablecoin-intermediated by definition, and the corridors with a live choice
reallocate activity at the same rate wherever the route runs. Dollar weighting
removes the contrast: **+26.6** against **+21.4 pp**, **48.6%** against **50.5%**
eligible. **DECISION: promote**, at exact scope -- descriptive, non-causal,
pooled 2024--2026, two separate within-scope decompositions that are comparable
to each other but do not add to the pooled margin (stated in source comments on
both deliverables). This resolves a question the paper already raises at what is
now line 140, where the count-share increase is reported as larger across
exchanges than within one.

**Where it landed.** Inside the existing owner,
`scripts/build_vehicle_transition_pair_deck_values.py`. `_pooled_contributions`
now delegates to a new `_scoped_contributions`; `_endpoint_eligibility` takes a
scope plus that scope's own decomposition row and reconciles the scoped
allocation against that scope's `common_pair_reweighting` before reporting, so a
scope share can never be printed against another scope's aggregate. New constant
`ELIGIBILITY_SCOPES`. No new script, artifact, or owner.

**Paper.** A new paragraph closes Section 3.2, written from the movement of
Makarov--Schoar 4.4 (raw lines 1017--1123: concede the limit of the split just
reported, state what the weighted version adds, report it, note where the
weighted answer differs and why the structure predicts that). Registered as a
fourth exemplar for the section and as a handoff at line 98. It cites
`MakarovSchoar2020Arbitrage` -- admitted, `live_citation: true`, previously
uncited -- for their within- and across-region decomposition of bitcoin price
dispersion, and reports that the across-venue excess here goes the other way.
Citations 30 -> 31, which moves the density test off the 109-word cliff the last
entry warned about.

**Deck.** No new frame. The margins frame's closing line gains the scope
contrast. It produced a 17.08pt overfull vbox. **A first fix was wrong and is
recorded so it is not retried:** shrinking the three panels to 3.40cm cleared the
box but clipped their "Margin total" lines into the paragraph below, which the
box counter does not catch. The space came instead from 0.26cm of panel padding
(the internal 0.16/0.14/0.20cm leads are now 0.10/0.08/0.10), a height of
3.66cm, and tighter wording. Page 13 rendered and inspected at both attempts.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper 37 pages / 0 undefined (was 36), deck 35 pages / 0 undefined, the
same 2 advisories. The deck's remaining two boxes (8.14485pt at line 65,
5.06264pt at line 221) are byte-equal to the pre-change baseline.
`audit_deck_evidence.py` PASS. Full suite: **14 failed, 2135 passed**, of which
`test_dominance_tables::test_generated_table_lineage_is_current[pair_composition]`
was mine -- regenerating the deck-values file staled that table's lineage -- and
is closed here by rerunning `scripts/tabulate/render_pair_composition.py`. Its
`.tex` is byte-identical; only the hash moved. That leaves the 13 byte-identical
long-standing failures. `tests/test_route_cost_panel.py` and
`tests/test_route_state.py` still error at collection on the
`v2_audit_token_decimals.parquet.prov.json` drift.

**Commit:** `df5bb3b`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- **Regenerating `vehicle_transition_pair_decomposition_deck_values.tex` stales
  `output/tables/pair_composition.{tex,pdf}`.** Run
  `scripts/tabulate/render_pair_composition.py` in the same unit, or
  `tests/test_dominance_tables.py` fails and the failure looks long-standing when
  it is not. The freeze audit does not catch it.
- The deck's margin panels are now at 3.66cm with 0.28cm of internal padding.
  There is no headroom left in that frame: the next sentence added to its closing
  paragraph needs a word removed, not a smaller panel. Below about 3.5cm the
  panels clip silently.
- Citation density after this pass: 31 / 14,565 = 0.002128 against a
  first-quartile 0.002081, so roughly 340 words of headroom before
  `test_venue_optics.py::test_exhibit_density_reaches_the_first_quartile` fails
  again. Plan the citation before the paragraph.
- Venue-shape shortfalls: words 14,565 against p25 18,738; equations 11 against
  25; citations 31 against 39; greek 6 against 7.
- The scoped machinery now generalises the eligibility split to any
  `reporting_scope`. The remaining unexploited cut in this lane is the *value*
  new-pair margin, whose eligible share is 24.1% single-venue against 14.2%
  cross-venue -- the widest scope gap in the whole table and the one this
  iteration did not interpret. It needs no new data.
- Section 6 still defines the cost benchmark and reports nothing; it remains
  blocked on route cost and is still the largest structural hole in the paper.
- The M3 12:03 handoff stays unchecked; its live remainder is the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still needs
  Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — the entry margin split by venue scope

**Targeted check.** The four blockers are unchanged and none is reachable from
this worktree, for the reasons the last three entries record: node B is Mukhin
(NEEDS-JAVA, 2026-08-15), node E1 and the empirical model ledger both wait on the
Studio D3 generation and certificate identities, and the two unchanged passes
need a quiet gate rather than a unit of work. The queue's only unchecked item is
the M3 handoff, whose live remainder is those same identities. So this iteration
took the cut the last entry nominated as the widest unexploited scope gap in the
table: the *value* new-pair margin, 24.1% eligible single-venue against 14.2%
cross-venue.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: the
`comparison_exclusive_composition` allocation at `reporting_scope` single_venue
and cross_venue, 2024--2026, descriptive and non-causal -- split only, calendar
and formula ID untouched. Generation at risk:
`vehicle_transition_pair_contributions.parquet` on the current certified
release, read-only; no producer rerun, no release rewrite. Prior corrections at
risk: the M3 affirmative boundary, yesterday's rule that a scope share is never
printed against another scope's aggregate, and the note that the two within-scope
decompositions do not add to the pooled margin. The first two are discharged by
construction below; the third is in source comments on both deliverables.

**A trap the preflight did not name and the producer did not either.** The
obvious way to give the entry margin a scope total is to read
`exclusive_pair_contribution` from that scope's decomposition row, exactly as the
reweighting margin does. That is wrong: the decomposition term is **net of the
pairs that stopped trading** (+17.8 pp pooled) while the eligibility split is
taken of the **gross** entry margin (+21.0 pp pooled). A scope share printed
against the netted term would have overstated the eligible fraction by about a
sixth. The producer now records the distinction in `SCOPE_MARGIN_TERMS` -- which
split margin has a decomposition term of its own -- and `_scope_margin_total`
reads the reweighting total from the row (against which the split is still
reconciled) and the entry total from the split's own components.
`test_scope_new_pair_total_is_the_gross_entry_margin` fails if the two are ever
confused: the fixture's netted term is +17.6 pp against a gross +21.0 pp.

**Result.** By route count the entry margin is +21.4 pp within a single exchange
against +23.8 pp across, with WETH-endpoint corridors supplying **65.8%** and
**67.5%** -- the count answer is two-thirds definitional and the route scope
barely moves it. Dollar weighting separates the scopes instead of reversing them.
The margin is **+14.1 pp** within an exchange against **+28.5 pp** across, twice
the size, while the eligible part is **+3.4** and **+4.0 pp**, almost the same in
both. The entire difference is corridors that had a choice: **+10.7** against
**+24.5 pp**, so eligible corridors account for **24.1%** of the margin within an
exchange and **14.2%** across it. **DECISION: promote**, at exact scope --
descriptive, non-causal, 2024--2026, two within-scope decompositions comparable
to each other and not additive to the pooled margin.

**Why it matters beyond the number.** This is the mirror image of yesterday's
reweighting result. There the cross-venue excess was carried *entirely* by
corridors whose vehicle was never in question and the choice-bearing part was
flat across scopes. Here the eligible part is flat across scopes and the entire
cross-venue excess is choice-bearing. Read together: a market already trading
across exchanges gains stablecoin share mainly where no other intermediary was
available, while the dollars arriving with markets that *begin* to trade across
exchanges come from corridors that could have been routed through the native
token and were not. The largest term of the decomposition, in the weighting that
carries economic magnitude and in the scope where the count evidence looked most
definitional, is not an eligibility artefact.

**Where it landed.** Inside the existing owner,
`scripts/build_vehicle_transition_pair_deck_values.py`: new `SCOPE_MARGIN_TERMS`
and `_scope_margin_total`, and the scope loop now emits
`\Pair{infix}{suffix}{prefix}` for both margins rather than only the reweighting
one. Four new macros; every pre-existing macro in the deck-values file is
byte-identical, verified by diff. No new script, artifact, or owner.

**Paper.** A new paragraph closes Section 3.2 at line 112, written from the
movement of Bolton and Kacperczyk (raw lines 1899--1935): name the subset the
reader suspects of driving everything, remove it, report that one outcome if
anything strengthens, report that the second is instead entirely that subset,
and close on a reading that holds both. Registered in
`docs/reviews/paper-rhetoric.json` as handoff line 112 with the section hash
refreshed and the seven following handoff lines shifted. No new citation.

**Deck.** No new frame. The margins frame's closing sentence now carries both
scopes' readings and **produced no new overfull box** -- the two remaining boxes
(8.14485pt at line 65, 5.06264pt at line 221) are byte-equal to the baseline. The
space came from wording, not from the panels: "which had no intermediary to
choose" became "which could not choose", and the two count-scope figures gave way
to the two value-scope ones. Page 13 rendered and inspected; all three "Margin
total" lines are intact, so the 3.66cm panels were not touched.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper 37 pages / 0 undefined, deck 35 pages / 0 undefined, the same 2
advisories. `audit_deck_evidence.py` PASS. `check_jfe_rhetoric_review.py` exits
0. `scripts/tabulate/render_pair_composition.py` rerun in the same unit per the
last entry's warning, so `test_dominance_tables` stays green. Full suite:
**13 failed, 2137 passed**, and all 13 are the long-standing v2
provenance-drift set (`test_weighted_quote` 7, `test_vehicle_role_models` 3,
`test_audit_findings_freeze` 1, `test_variable_registry` 1,
`test_vehicle_transition_e0` 1). `tests/test_route_cost_panel.py` and
`tests/test_route_state.py` still error at *collection* on the same
`v2_audit_token_decimals.parquet.prov.json` drift, which aborts a bare
`pytest -q` run at 48s with no test results at all; use
`--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`.

**Commit:** `b07680a`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- **Citation density is now the binding venue constraint, not a distant one.**
  31 / 14,834 = 0.002090 against a first-quartile 0.002081 leaves roughly **60
  words** of headroom before
  `test_venue_optics.py::test_exhibit_density_reaches_the_first_quartile` fails.
  The next paragraph of any length must carry a citation. Uncited admitted keys
  that could plausibly serve this lane: `MakarovSchoar2022DeFi`,
  `LiuMakarovSchoar2023Terra`, `Krugman1979VehicleCurrenciesWorkingPaper`.
- Regenerating `vehicle_transition_pair_decomposition_deck_values.tex` still
  stales `output/tables/pair_composition.{tex,pdf}`; rerun
  `scripts/tabulate/render_pair_composition.py` in the same unit.
- The deck margins frame has headroom again only because two macros were traded
  for two others. It is still a zero-slack frame at 3.66cm panels; below about
  3.5cm they clip silently.
- The eligibility lane is now fully exploited: both composition margins, both
  weightings, all three scopes. The remaining descriptive cuts in this table are
  the *retired*-pair margin (which no paragraph interprets and which the entry
  margin's net-versus-gross distinction just made visible) and the
  baseline-exclusive composition term.
- Section 6 still defines the cost benchmark and reports nothing; it remains
  blocked on route cost and is still the largest structural hole in the paper.
- The M3 12:03 handoff stays unchecked; its live remainder is the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still needs
  Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — the netted exclusive term read as corridor replacement

**Targeted check.** The four blockers are unchanged and none is reachable from
this worktree: node B is Mukhin (NEEDS-JAVA, 2026-08-15), node E1 and the
empirical model ledger wait on the Studio D3 generation and certificate
identities, and the two unchanged passes need a quiet gate rather than a unit of
work. The queue's only unchecked item is the M3 handoff, whose live remainder is
those same identities. So this iteration took the cut the last entry nominated:
the *retired*-pair margin, which no paragraph interpreted and which the entry
margin's net-versus-gross distinction had just made visible.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: the
`baseline_exclusive_composition` and `comparison_exclusive_composition` cohort
routing rates at all three `reporting_scope` values, 2024--2026, descriptive and
non-causal -- a read-only split of the certified ledger, calendar and formula ID
untouched. Generation at risk: `vehicle_transition_pair_contributions.parquet`
on the current certified release, read-only; no producer rerun, no release
rewrite; one column newly read (`aggregate_mass_share_midpoint`, already
present). Prior corrections at risk: yesterday's net-versus-gross trap (a cohort
statement must never print the gross entry margin against the net term) and the
`component_pp <= 0` guard forbidding an eligibility share of a non-positive
margin. Both discharged below.

**What the term actually is.** The exiting and entering cohorts are weighted by
the *same* midpoint exclusive-support mass, so
`exclusive_pair_contribution = E * (s_enter - s_exit)` exactly. The netted term
is not a residual: it is one activity mass times the gap between how two
populations of corridors are routed. Publishing E, `s_exit`, and `s_enter` turns
the decomposition's largest count margin into a statement about replacement.

**How the negative margin was handled without weakening the old guard.** The
retiring margin is negative in every metric and scope, so `_endpoint_eligibility`
would refuse it -- correctly, because a share of a margin whose parts disagree in
sign is not a share of it. Rather than relax that guard, `_support_cohorts`
proves the split does not straddle zero (`locked_pp * margin_pp >= 0` and the
same for the open part) before forming any share, and separately proves each
open contribution equals its own open mass times its own open routing rate.
Ordering matters and cost two test iterations: the structural premises (one mass
shared by both cohorts; WETH-endpoint corridors at routing rate exactly one) are
checked *before* the arithmetic reconciliations, or a mutation to the mass trips
the margin identity and the error message names the wrong defect.

**Result.** By route count, **48.0%** of activity and by value **27.8%** sits on
corridors alive in only one of the two years. The departing cohort sent
**6.8%** of its routes and **10.8%** of its dollars through a stablecoin; the
arriving cohort sends **43.8%** and **79.8%**. Strip the WETH-endpoint corridors
and the comparison is **1.7%** against **21.0%** by count and **3.2%** against
**76.9%** by value; across exchanges the arriving corridors that could have
chosen route **88.3%** of their dollars through a stablecoin, against **5.3%**
for the ones they replaced. **DECISION: promote**, at exact scope --
descriptive, non-causal, 2024--2026, realised composition and not an entry or
exit effect. The count/value gap (21.0% against 76.9% among choice-bearing
arrivals) says the large new corridors are the stablecoin-routed ones.

**Why it matters beyond the number.** This is the sharpest available form of
Java's queue item (1): the aggregate share moves because the trading network
reorganises around the challenger. Not "new markets adopt the stablecoin" --
the corridor population turns over almost completely, and the population that
arrives is routed six times more often through the stablecoin (twelve times, by
value among corridors that had a choice) than the population it replaced.

**Naming.** The macro family is `Cohort*`, not `Turnover*`. The prose route's
tier rule excludes "turnover" sentences, meaning the blocked vehicle-turnover
hazard; a `Turnover*` macro family would have invited a future reader to
conflate the two. Renamed before the first commit.

**Where it landed.** Inside the existing owner,
`scripts/build_vehicle_transition_pair_deck_values.py`: `SUPPORT_COHORTS`,
`COHORT_SCOPES`, `_support_cohorts`. Sixty new macros; every pre-existing macro
in the deck-values file is byte-identical, verified by diff. Four new tests plus
a rebuilt exclusive-row fixture that satisfies the identity the renderer proves
(previously the fixture carried a single exit row with arbitrary weights). No
new script, artifact, or owner.

**Paper.** A new paragraph closes Section 3.2 at line 126, written from the
movement of Hajda and Nikolov (raw lines 540--570): report the net figure, show
the gross dynamics behind it, and close on where the action is. Registered in
`docs/reviews/paper-rhetoric.json` as handoff line 126, that raw passage added
to both exemplar lists, section hash refreshed, and the seven following handoff
lines shifted (twice -- the second time because a source comment was extended;
the shift is by *file* lines, not paragraph count). Cites
`FlandreauJobst2009Empirics` for persistence without lock-in across a stable
roster of trading relationships, against a setting where the roster itself
turns over. Citations 31 -> 32.

**Deck.** No new frame. The margins frame's closing paragraph now leads with the
replacement reading, replacing the retired-pair giveback clause it supersedes.
**A first attempt overflowed by 8.83pt and a second trim of 30 rendered
characters did not move it at all** -- the vbox overflow is quantised at line
granularity, so a partial trim buys nothing; the fix was to drop a whole clause
(`\MarginReweightHalfPairs` concentration and `\MarginNewPairTopShare` breadth)
and keep the count weighting throughout, because the frame's decknote declares a
route-count denominator and a value figure beside `\PairPooledExclusive` would
have mixed weightings. Final state: no new overfull box, the two remaining
(8.14485pt at line 65, 5.06264pt at line 221) byte-equal to baseline. Page 13
rendered and inspected at each attempt; all three "Margin total" lines intact
and the panels were never touched.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper 38 pages / 0 undefined (was 37), deck 35 pages / 0 undefined, the
same 2 advisories. `audit_deck_evidence.py` PASS. `check_jfe_rhetoric_review.py`
exits 0. `scripts/tabulate/render_pair_composition.py` rerun in the same unit
per the standing warning. Full suite: **13 failed, 2142 passed**, all 13 the
long-standing v2 provenance-drift set (`test_weighted_quote` 7,
`test_vehicle_role_models` 3, `test_audit_findings_freeze` 1,
`test_variable_registry` 1, `test_vehicle_transition_e0` 1); no new failures.
`tests/test_route_cost_panel.py` and `tests/test_route_state.py` still error at
*collection* on the same `v2_audit_token_decimals.parquet.prov.json` drift, so a
bare `pytest -q` aborts with no results; use
`--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`.

**Commit:** `0d805e3`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- **`latexmk` is not on the shell PATH in this worktree**, only inside
  `check_deliverable_conformance.py`, which finds it via `shutil.which` under its
  own environment. A bare `cd deck && latexmk ...` fails silently and leaves a
  stale PDF and a stale `main.log`; an "unchanged overfull box" read from that
  log is a false negative. Recompile through `check_deliverable_conformance.py`
  and only then read `deck/main.log`.
- **Deck vbox overflow is quantised at one line (about 8.8pt at the 8.2/9.2
  closing paragraph).** Trimming a few words buys nothing; either cut a clause or
  do not bother.
- Citation density after this pass: 32 / 15,058 = 0.002125 against a
  first-quartile 0.002081, so roughly **320 words** of headroom before
  `test_venue_optics.py::test_exhibit_density_reaches_the_first_quartile` fails.
- Venue-shape shortfalls: words 15,058 against p25 18,738; equations 11 against
  25; citations 32 against 39; greek 6 against 7.
- The exclusive-support lane is now fully exploited: entry, exit, both
  weightings, all three scopes, and the cohort identity behind the netted term.
  The remaining unexploited descriptive cut in this table is the
  `common_support_mass` term ($-0.5$ pp count, $-2.5$ pp value), which no
  paragraph interprets and which is the only term of the four still unread.
- Three deck macros are now unused (`\MarginRetiredPairTotal`,
  `\MarginReweightHalfPairs`, `\MarginNewPairTopShare`). They remain generated
  and correct; do not delete them to tidy up, they are the natural material for
  a breadth sentence if a frame regains space.
- Section 6 still defines the cost benchmark and reports nothing; it remains
  blocked on route cost and is still the largest structural hole in the paper.
- The M3 12:03 handoff stays unchecked; its live remainder is the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still needs
  Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — the fourth term: support mass as a shift times a block gap

**Targeted check.** No blocking check is honestly closable this iteration.
`audit_findings_freeze.py` reports the same four: node E1 specification lock
(`locked_at`, `d3_generation`, `d3_certificate` all `missing`, stage
`design_seed`), empirical model ledger (`current_runs=0`, exploration
`not_started`), node B full-text literature ledger (32/33 source-sets, 34/35
five-axis cards -- the missing one is Mukhin, NEEDS-JAVA since 2026-08-15), and
two unchanged findings passes (`stable_passes=0`). So this iteration took the
highest-value claim unit the last entry left on the table: the
`common_support_mass` term, the fourth of the identity and the only one no
sentence read.

**What it is.** `common_support_mass = (S_C_bar - S_E_bar)(W_2026 - W_2024)`, a
product of two factors the exhibit publishes and the deck values never exposed.
Reading it as a single netted number hides the economics; reading it as a
factorisation separates *where activity went* from *how the block that received
it routes*. Both factors were sitting unread in every row of
`vehicle_transition_pair_decomposition.jsonl`.

**Result.** The mass shift is enormous and the term is tiny. Corridors alive in
both years fall from **55.5% to 48.6%** of route activity and from **82.0% to
62.4%** of value; across exchanges the dollar shift is **-27.6 pp**. Priced at
the midpoint gap the whole migration contributes **-0.5 pp** by count and
**-2.5 pp** by value against a **+42.8 pp** total. It is small because the two
populations are priced almost alike at their two-year midpoints -- **33.1%**
against **25.3%** by count, **58.2%** against **45.3%** by value. The sign is
negative in **all nine** metric/scope rows, and both factor signs are uniform
too (`dW < 0`, `gap > 0` everywhere). **DECISION: promote**, at exact scope --
descriptive, non-causal, 2024--2026, realised composition. The so-what: the
rotation is *not* activity migrating into corridors that already used the
challenger. That channel is negative. The aggregate rose because the population
receiving the activity routes differently from the one it replaced.

**Why midpoint pricing is not a levels claim.** The midpoint gap is what this
symmetric decomposition pays for a unit of migrated mass; it is not a statement
that the blocks route alike in either year. The exclusive block goes 10.8% to
79.9% by value, which is the *exclusive-pair* term, already published. Both the
paper source comment and the deck estimand boundary say this explicitly, because
a reader who conflates the two will read the small term as "turnover did not
matter".

**Where it landed.** Existing owner only, no new script or artifact:
`SUPPORT_BLOCKS`, `BLOCK_SCOPES`, `BLOCK_COLUMNS`, `_support_mass_factors`, 54
new macros across two weightings and three scopes. The eight block columns join
`_scope_rows`' required and numeric contracts, so the renderer fails closed if a
future exhibit generation drops them. Ordering matters as it did for
`_support_cohorts`: the two structural premises (blocks partition the year; each
year's aggregate share is their activity-weighted mean) are proved *before* the
product reconciliation, or a mutated weight trips the product check and names
the wrong defect. Every pre-existing macro is byte-identical, verified by diff.

**A trap worth recording.** The market-incidence row carries `null` in every
block column. It is excluded from `_scope_rows` by `formula_id`, not by column
presence, so adding the columns to the required set was safe -- but only because
of that filter. Anything that widens `_scope_rows`' row selection will now
collect a row of nulls and fail on finiteness rather than on the real defect.

**Paper.** New closing paragraph at Section 3.2 line 144. Written from Carletti,
De Marco, Ioannidou and Sette (JFE 2021, raw lines 1008--1015), whose two-factor
attribution runs the other way -- "the effects are sizable not because the
treated investors are very price sensitive, but because they hold large volumes
of the securities" -- one factor granted the magnitude and the other denied it.
Cites `AmitiItskhokiKonings2022Dominant`: invoicing currency is close to a fixed
exporter attribute, switching for a small minority of observations over almost
four years, with destination composition explaining little of the variation.
Choice is similarly sticky inside a continuing corridor here; the difference is
that the corridor population turns over fast enough for composition to carry the
whole aggregate change. Registered in `docs/reviews/paper-rhetoric.json` as
handoff 144, Carletti added to both exemplar lists, section hash refreshed, the
seven following handoff lines shifted by 17 file lines. Citations 32 -> 33.

**Two prose traps.** (1) `measure_prose_conventions.py` failed on `what_cleft`
at 0.808 against a corpus max of 0.777 -- the draft was already at the ceiling
and the new paragraph's two "What X is" clefts tipped it. Rewriting both
complete thoughts (not the words) brought it to 0.727. Check this after any
paragraph that opens a clause with "What". (2) `paper-rhetoric.json` is written
with `indent=1`; a `json.dumps(indent=2)` round-trip produced a 3,633-line diff
for a 31-line change. Round-trip and compare lengths before writing it.

**Deck.** The margins frame (page 13) gains one clause -- "Where that mass sits
barely matters: the -6.9 pp shift between the two populations contributes
-0.5 pp" -- count-weighted, matching the frame's declared route-count
denominator. It overflowed by exactly **8.83212pt**, the same quantised
one-line overflow the last entry recorded, so a whole clause had to go: the
elliptical "The third margin's, by value, is corridors that could choose ---
X within a venue against Y across", which was the least legible sentence on the
frame and is fully carried by Section 3.2. Final state: no new overfull box, the
two remaining (8.14485pt line 65, 5.06264pt line 221) byte-equal to baseline.
The frame's `ESTIMAND-BOUNDARY` gained the new factors' proof obligations and
lost the boundary text for the retired clause -- but only the part describing
the two `\OpenValue*` route-scope figures; the reweighting cross-venue-excess
claim is still on the slide, so its boundary text was rewritten and kept. Page
13 rendered and inspected; all three "Margin total" lines and the panels
untouched.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper 38 pages / 0 undefined, deck 35 pages / 0 undefined, the same 2
advisories. `audit_deck_evidence.py` PASS. `check_jfe_rhetoric_review.py` exits
0. `scripts/tabulate/render_pair_composition.py` rerun in the same unit per the
standing warning (its `.tex` is unchanged; only the prov manifest moved, which
is exactly why the warning exists). Full suite: **13 failed, 2147 passed**, all
13 the long-standing v2 provenance-drift set; no new failures. Still use
`--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py` or
a bare `pytest -q` aborts at collection.

**Commit:** `0b2926f`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- **All four terms of the pair decomposition are now interpreted.** Nothing in
  `vehicle_transition_pair_decomposition.jsonl` is unread. The descriptive
  composition lane is exhausted at the aggregate level; further work in it has
  to come from a different exhibit or a different cut, not another term.
- Three macros were unused before this pass (`\MarginRetiredPairTotal`,
  `\MarginReweightHalfPairs`, `\MarginNewPairTopShare`); `\OpenValueSingleNewPair`
  and `\OpenValueCrossNewPair` now join them in the deck, though both remain in
  the paper. Do not delete any of them to tidy up.
- The margins frame has now evicted a clause on two consecutive iterations. It
  is saturated. Do not add to it again without removing a panel or splitting it.
- Citation density after this pass: 33 / 15,336 = 0.002152 against a
  first-quartile 0.002081, so roughly **520 words** of headroom before
  `test_venue_optics.py::test_exhibit_density_reaches_the_first_quartile` fails.
- Venue-shape shortfalls: words 15,336 against p25 18,738; equations 11 against
  25; citations 33 against 39; greek 6 against 7. Equations are the widest gap
  and the decomposition identity itself is currently prose-only in Section 3.2 --
  displaying it would move both the equation and the greek counters.
- Section 6 still defines the cost benchmark and reports nothing; it remains
  blocked on route cost and is still the largest structural hole in the paper.
- The M3 12:03 handoff stays unchecked; its live remainder is the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still needs
  Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — the identity itself: displayed, tabulated, and separated from the Shapley bridge

**Targeted check.** Still none closable. `audit_findings_freeze.py` reports the
same four blockers with identical detail strings: node E1 specification lock
(`stage=design_seed`, `locked_at`/`d3_generation`/`d3_certificate` all
`missing`), empirical model ledger (`current_runs=0`, `exploration=not_started`),
node B full-text literature ledger (32/33 source-sets, 34/35 five-axis cards --
Mukhin, NEEDS-JAVA since 2026-08-15), two unchanged findings passes
(`stable_passes=0`). This iteration took the defect the last entry's own
"next iteration" note pointed at, and it turned out to be larger than a
venue-shape gap.

**The defect.** Section 3.2 spent six paragraphs interpreting the four terms of
`e1_2_conditional_pair_decomposition` without ever stating the identity, and
Table 3 reported **two different factorisations of the same route-count total
under identical row labels**. Panel A was `e1_3_market_incidence_bridge` (a
five-way Shapley allocation over market activity M, vehicle incidence I and
stable share s); Panel B was the four-term midpoint identity, but only its
*value* measure. Both panels carried the rows "Pairs entering or leaving the
sample" and "Trading shifts across continuing pairs" for different objects
(+9.8 against +19.2; +7.9 against +26.2). A reader who met
`\MarketActivityReweight{}` = +7.9 pp in one paragraph and
`\PairPooledReweight{}` = +8.6 pp in another had nothing to reconcile them with.
The exhibit note made it worse by asserting that Panel B "repeats the accounting"
of Panel A. It does not.

**What landed.**
1. **Equation (6)**, the frozen `midpoint_common_exclusive_support_v1` formula,
   displayed with underbrace labels and its notation defined in the sentences
   before it: `W_y`, `\omega_{p,y}`, `s_{p,y}`, `S_com,y`, `S_exc,y`, midpoint
   bars. Verified algebraically against the spec-lock string before writing.
2. **The count identity is now tabulated.** Panel B is the four count terms
   (-0.1, +8.6, -0.5, +17.8, total +25.7); the old Panel B becomes Panel C; the
   regressions become Panel D. Row labels now separate "market activity" from
   "vehicle activity" and "pairs entering or leaving the sample" from "pairs
   traded in only one year".
3. **A paragraph that bounds the overlap.** The two factorisations *agree on
   which pairs continue* -- and this is checked, not asserted. The pooled
   `count_share` `market_incidence_support` rows of
   `vehicle_transition_pair_support.jsonl` give `common_vehicle_role`
   primary-choice mass shares of **0.5546 (2024)** and **0.4858 (2026)**, equal
   to `\BlockWeightBase{}`/`\BlockWeightEnd{}`, the identity's own common-block
   weights. Panel A's two turnover classes exhaust the identity's single
   year-specific class (0.4152 + 0.0301 in 2024; 0.5038 + 0.0103 in 2026). They
   part on weighting (M-and-I against choice mass throughout) and on whether the
   year-specific class is split by market turnover against vehicle-role turnover.
4. **The two within-pair numbers reconciled.** +1.3 pp under the Shapley bridge
   and -0.1 pp under the identity both sit inside the matched estimate's
   confidence interval, whose upper limit is +1.7 pp. This protects Java's
   headline reading: whichever way the count total is cut, comparable trades did
   not switch intermediary. **DECISION: promote** at exact scope (descriptive,
   non-causal, 2024--2026, realised composition).

**One overclaim caught mid-unit.** The first draft of that paragraph said the
two factorisations "assign a pair to the continuing population by different
tests". That is false -- the support exhibit shows the partitions coincide. The
sentence was rewritten to state what is verifiable and the check is recorded in
a source comment beside it. Do not restore the stronger wording.

**Traps for the next iteration.**
- **Citation density headroom is now ~450 words, not 15.** Before this pass it
  was 15 words: 33 citations / 15,840 words against a p25 density of 0.002081.
  Adding `\citet{Somogyi2026DollarDominanceFX}` (already-cited key, so the
  literature gate is untouched) took it to 34 / 15,943. Adding a *new* key is
  not free: `cited_keys` in the findings audit is every distinct `\cite*` key in
  `paper/sections/*.tex`, and each one needs a card at `claim-verified` or
  `independently-re-read`. `ChangDuLouPolk2022Ripples` is only
  `full-text-read`, so citing it would push the node B blocker from 32/33 to
  32/34.
- **`src/ddvc/dominance_tables.py` is shared by three renderers.** Editing it
  makes `dominance_rotation` and `usdt_transition` provenance go `stale` even
  though their `.tex` is byte-identical. Re-render all three in the same unit or
  `test_generated_table_lineage_is_current` fails.
- **`uv run pytest` aborts at collection here** (68 collection errors): the
  `.venv` needs `PYTHONPATH=<root>/src`. Use `./scripts/run -m pytest`. The
  earlier entries' `uv run pytest` instruction is wrong for this worktree.
- **`pgrep -f "pytest ..."` self-matches** a waiter shell whose own command line
  contains the pattern, so an `until pgrep` loop never terminates. Wait on the
  PID.
- The rhetoric review's handoff lines shift twice per prose unit if you add
  source comments after the first `check_jfe_rhetoric_review.py` run. Run it,
  take the `expected=` list it prints, and remap in one pass.
- `deck/main.pdf` is tracked and rebuilds byte-differently at identical length
  even when no deck source changed. Check out the file rather than committing
  the noise.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper **39 pages** / 0 undefined (was 38), deck 35 pages / 0 undefined, the
same 2 advisories. Venue shape moved: equations 11 -> 12, greek 6 -> 7 (now *in
range*, p25 = 7), citations 33 -> 34, words 15,336 -> 15,943. Full suite via
`./scripts/run -m pytest -q --ignore=tests/test_route_cost_panel.py
--ignore=tests/test_route_state.py`: **13 failed, 2148 passed**, all 13 the
long-standing v2 provenance-drift set, no new failures. Paper-facing subset
re-run after the mid-unit correction: 90 passed, 446 subtests.

**Commit:** `c8b49a1`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- Section 3.2's accounting is now complete and self-consistent: identity
  displayed, both measures tabulated, both factorisations distinguished. The
  descriptive composition lane at the aggregate level is finished. Further work
  in it needs a different exhibit or a different cut.
- `vehicle_transition_pair_support.jsonl` carries per-year `primary_choice_mass`
  and `stable_share` for all three market-incidence support classes at pooled
  and scoped reporting. None of it is published as a macro. The
  vehicle-role-turnover class shrinking from 3.0% to 1.0% of choice mass while
  its stable share runs 0.4695 -> 0.7688 is an unread economic fact; publishing
  it needs a producer change in
  `scripts/build_vehicle_transition_pair_deck_values.py`, not a prose pass.
- Equations remain the widest venue gap (12 against p25 25). Section 6 still
  defines the cost benchmark and reports nothing; it is still the largest
  structural hole and is still blocked on route cost.
- The deck was not touched this iteration and needs no change: its margins frame
  reads only identity macros, so it never carried the Panel A / Panel B
  confusion. It remains saturated -- do not add to it without removing a panel.
- The M3 12:03 handoff stays unchecked; its live remainder is the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still needs
  Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — market-incidence support classes published and read

**Targeted check.** Still none closable. `audit_findings_freeze.py` reports the
same four blockers with identical detail strings: node E1 specification lock
(`stage=design_seed`, `locked_at`/`d3_generation`/`d3_certificate` all
`missing`), empirical model ledger (`current_runs=0`, `exploration=not_started`),
node B full-text literature ledger (32/33 source-sets, 34/35 five-axis cards --
Mukhin, NEEDS-JAVA since 2026-08-15), two unchanged findings passes
(`stable_passes=0`). Queue: only the M3 12:03 handoff is unchecked, and its live
remainder is exactly those blockers, so there was nothing there to close either.
This iteration took the unit the last entry's own "next iteration" note named.

**The defect.** Panel A of Table 3 publishes five signed terms and three
aggregate stablecoin shares and nothing about the population underneath them.
Two of those terms -- `market_pair_support_bridge` and
`vehicle_role_support_bridge` -- are each one class's activity mass against that
class's routing rate, so a term near zero cannot be told apart from an inert
class or a shrinking class routing very differently from the average.
`vehicle_transition_pair_support.jsonl` has carried the `market_incidence_support`
class ledger since the E0 run and had **no consumer at all**: the only mention in
the repository was a source comment added last iteration.

**What landed.**
1. **`_market_incidence_classes` in the existing producer.** It publishes the
   three classes' choice-mass weight, stablecoin share and pair count for both
   years (18 macros, prefix `\Incidence`) and withholds all of them unless the
   classes are provably the bridge's own partition. Five premises, checked in
   the order of what they license: each class's stablecoin share is its own
   stable-over-primary choice mass; the three weights close on one in each year;
   their mass-weighted mean reproduces that year's aggregate stablecoin share on
   the bridge row itself; the common class reproduces
   `common_role_*_stable_share`; the two both-years classes renormalise to
   `established_market_*_stable_share`. All five hold on the live ledger to
   1e-12.
2. **`_market_incidence_row` now owns the common-role endpoints.**
   `common_role_baseline_stable_share` and `common_role_comparison_stable_share`
   were present in the exhibit but not required, read, or reconciled. They are
   now in the required set, the finiteness list, and a new "common-role
   endpoints" reconciliation.
3. **A paragraph in Section 3.2 that reads the smallest term.**
   `\VehicleRoleSupportBridge{}` is -0.4 pp. The class behind it carries **3.0%
   of 2024 choice mass across 4,967 ordered pairs and 1.0% of 2026 across
   1,556**, and routes through a stablecoin **more often than either other class
   in either year**: 47.0% and 76.9%, against 25.0%/41.2% for the 26,547 pairs
   carrying a vehicle in both years and 3.9%/43.1% for one-year markets. So the
   extensive margin of intermediation inside established markets is narrow,
   shrinking, and stablecoin-routed where it is used.
4. **A third account of the rotation is now bounded.** "Markets that had been
   trading directly begin routing indirectly and use a stablecoin when they do"
   is confined to a population never larger than 3.0% of routed choice mass and
   cannot carry +25.7 pp. **DECISION: promote** at exact scope (descriptive,
   non-causal, realised incidence, 2024--2026). This strengthens Java's
   compositional headline from a third direction: it is not within-pair
   switching, and it is not established markets switching intermediation on.

**The trap this unit had to avoid, and how.** The obvious move was a Bennet
split of the three classes into a composition term and a within-class term. It
is exact (-1.42 pp composition, +27.10 pp within-class, total +25.68 pp) and it
would have been a **fourth factorisation of the same total**, whose within-class
term reads like a within-pair term and is not one: two of the three classes hold
different pairs in each year by construction, so their "within-class" movement
is pure composition. That is precisely the confusion the 2026-08-16 correction
was written about. It was not published. The paragraph instead states outright
that membership turns over by construction, that no pair in the role-turnover
class carries an intermediary in both years, and that the distance between its
two stablecoin shares records which markets occupied it.

**Traps for the next iteration.**
- **Re-stamp the producer before re-rendering a table that consumes it.**
  `require_certified_presentation_source` compares the *code fingerprint* in the
  sidecar, so editing `build_vehicle_transition_pair_deck_values.py` after
  running it makes `render_pair_composition.py` fail with "presentation producer
  differs from its certificate". Run the producer, then the table renderer.
- **`pair_composition.tex` came out byte-identical** but its `.pdf` and both
  sidecars changed. Commit all four together; do not check out the pdf.
- The ledger's earlier traps all still hold: `dominance_tables.py` is shared by
  three renderers; `uv run pytest` aborts at collection (use `./scripts/run -m
  pytest`); `pgrep -f "pytest ..."` self-matches, so wait on the PID;
  `deck/main.pdf` rebuilds byte-differently at identical length, so check it
  out; citation headroom is ~450 words and a *new* `\cite` key needs a card at
  `claim-verified` or better.
- **`rather_than` has no headroom.** The first draft of the new paragraph put
  the draft at 0.608 per 1,000 words against a corpus maximum of 0.572. The
  closing thought was rewritten (not word-substituted) into three sentences that
  carry the contrast structurally. Any new paragraph using "rather than" will
  re-break `measure_prose_conventions.py`.
- The rhetoric review needed one inserted handoff at line 83 and a +15-line
  remap of the seventeen after it. Raw exemplar read for it was
  `2020-GriffinShams2020Untethered...txt:167-193`, added to both the section's
  `exemplars` and the flow review's `raw_exemplars`.

**Validation.** `check_deliverable_conformance.py` exits 0, all blocking checks
pass; paper 39 pages / 0 undefined, deck 35 pages / 0 undefined, the same 2
advisories. Venue shape: words 16,208 -> 16,240, equations 12, citations 34.
Producer suite 39 passed (32 before, 7 new). Full suite via `./scripts/run -m
pytest -q --ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`:
**13 failed, 2155 passed**, exactly the long-standing v2 provenance-drift set,
no new failures.

**Commit:** `01a2ad2`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- The pooled `count_share` support ledger is now fully published and read. The
  *other* record types in the same file are still unread:
  `decomposition_pair_support` carries `baseline_denominator`,
  `comparison_denominator` and `zero_denominator_cell_years` at pooled,
  single-venue and cross-venue scope for all three metrics, and
  `pair_month_day_scope_support` carries the scope-specific cells. Note that
  `market_incidence_support` exists **only** for pooled `count_share` -- there
  is no value-weighted or scope-specific class ledger, so a value-side version
  of this paragraph would need a producer change in
  `scripts/run_vehicle_rotation_composition_e0.py`, not a prose pass.
- The deck was not touched and needs no change: no frame reads an `\Incidence`
  macro, and the deck remains saturated. Do not add a frame without removing one.
- Equations remain the widest venue gap (12 against p25 25). Section 6 still
  defines the cost benchmark and reports nothing; still the largest structural
  hole, still blocked on route cost.
- The M3 12:03 handoff stays unchecked; its live remainder is the E1/D3
  generation identities and the two unchanged findings passes. Mukhin still
  needs Java or Studio (NEEDS-JAVA stands from 2026-08-15).

## 2026-08-16 — Panel A displayed, and the exact bridge between the two factorisations

**Targeted check.** Still none closable. `audit_findings_freeze.py` reports the
same four blockers with identical detail strings: node E1 specification lock
(`stage=design_seed`, `locked_at`/`d3_generation`/`d3_certificate` all
`missing`), empirical model ledger (`current_runs=0`, `exploration=not_started`,
`confirmatory_context=invalid`), node B full-text literature ledger (32/33
source-sets, 34/35 five-axis cards -- Mukhin, NEEDS-JAVA since 2026-08-15), two
unchanged findings passes (`stable_passes=0`). Queue: only the M3 12:03 handoff
is unchecked and its live remainder is exactly those blockers. Preflight `data`
returned ALLOWED; no data ran.

**REGRESSION-CHECK for this unit.** Estimand at risk `e1_3_market_incidence_bridge`
(raw pooled count-share change, `shapley_market_incidence_stable_bridge_v1`);
evidence generation the current D3-bound `vehicle_transition_pair_decomposition.jsonl`
and `..._support.jsonl`, unchanged; prior correction at risk the 2026-08-16 rule
that a component of Panel A is never the similarly named component of the
identity and that no fourth factorisation of the same total may be published.
The action publishes no new decomposition, no new macro and no new number.

**The defect.** Panel A of Table 3 reported five signed components of a Shapley
allocation the manuscript never wrote down. One sentence carried the whole
method: "A Shapley allocation over market activity, vehicle incidence, and
stablecoin share spreads the interactions among the five resulting components."
A referee could not reproduce the panel, could not see which population each
bridge term narrows, and had to take the non-comparability claim on trust. Worse,
that claim was defended by a sentence that was **wrong**: "Panel A weights a
continuing pair by all of its observed trading ... whereas
Equation~\eqref{eq:pair-decomposition} works throughout in shares of
native-plus-stable choice mass." Both weight a continuing pair by its
primary-choice mass. In the analysis owner, `_factor_share` divides
`sum(M*I*s)` by `sum(M*I)`, and `M*I` **is** choice mass, so the stated
difference does not exist. The real difference is one of scale, and it is exact.

**What landed.**
1. **Two displayed equations in Section 3.1.** `\eqref{eq:incidence-functional}`
   defines the aggregating functional `F_y(Q) = sum M I s / sum M I` over an
   arbitrary set of pairs, with `M` observed market routes, `I` realised
   native-or-stable vehicle incidence, and `s` the stablecoin share of that
   intermediated activity -- the same `s` the identity assigns to a continuing
   pair, which the prose says outright. `\eqref{eq:market-incidence}` is the
   published identity: two bridges that narrow the population from all pairs to
   pairs traded in both years and then to pairs carrying an intermediary in both
   years, plus three order-averaged terms inside the narrowest set. The five
   labelled terms are `market_pair_support_bridge`, `vehicle_role_support_bridge`,
   `market_activity_reweighting`, `vehicle_incidence_reweighting` and
   `within_pair_stable_share`, in that order. Sets are `\mathcal{N}`,
   `\mathcal{N}_M`, `\mathcal{N}_V` -- deliberately not `\mathcal{A}`/`\mathcal{P}`,
   which Section 2 already binds to tradable assets and live pools.
2. **The exact bridge between the two panels, stated and guarded.** On the live
   pooled count row,
   `within_common + common_pair_reweighting = W_bar * common_role_total_change`
   closes at 0.0844459944134132 on both sides with residual **0.0** (W_bar is the
   midpoint of the identity's own 0.5546/0.4858 common-block weights). So Panel
   A's three allocated terms sum to the common block's *own* stablecoin-share
   change (+16.23 pp) while the identity's within-pair and reweighting terms sum
   to the same change scaled by that block's weight (+8.44 pp). That is why the
   two within-pair numbers are +1.3 pp and -0.1 pp and why they must never be
   netted. The paragraph now says this; `_cross_panel_common_bridge` in the
   producer withholds every macro in the subsection unless it still holds to
   1e-12, and also unless the two panels report the same pooled count total.
3. **Contribution positioning where the reader can check it.** The gloss after
   the identity now places Krugman's question -- which intermediary minimises
   the cost of exchanging a given pair -- as the *fifth* of the five terms, with
   the four before it recording where trading happens. Section 3 had never cited
   `Krugman1980VehicleCurrencies` even though it is where the introduction's
   claimed contribution lands.
4. **The producer's test fixture now derives Panel A from the identity row.**
   It previously stated Panel A's five terms as free constants that satisfied
   neither cross-panel relation (totals 0.26 against 0.25; common bridge 0.079
   against 0.0902), so the new guard would have failed on the fixture. The two
   free terms and the 2026 incidence-class shares are now solved out of the
   identity row and the bridge row, which leaves the hand-tuned contributions
   fixture untouched. Two focused tests: one moves choice mass between the
   identity's within-pair and year-specific terms (identity still sums to its own
   total, bridge row untouched) and one grows the identity's total on both sides.

**DECISION: promote** at exact scope. The equations are a transcription of the
frozen `e1_3` formula, not a new estimand; the scale relation is arithmetic on
published cells. **DECISION: park** the universe boundary: the loader takes every
ordered pair in the released pair ledger over the common calendar, while the
spec's `pair_universe` names pairs with positive primary-choice mass in either
year. The two agree for `F`, because a pair with no vehicle route carries zero
weight in both its numerator and its denominator. The prose says "every ordered
pair" and the following clause, which defines `\mathcal{N}_M` as the pairs traded
in both years, fixes the reading.

**The trap this unit had to avoid, and how.** The obvious repair to the wrong
sentence was to delete it and leave the non-comparability asserted. That would
have preserved the 2026-08-16 correction in words while removing its only
support. The published relation does the opposite: it makes the difference
between the panels arithmetic, so a reader who notices that the two within-pair
terms disagree now has the reason in front of them instead of a discrepancy.
Note what the relation does **not** license: it prices the common block only. The
identity charges the year-specific remainder at `1 - W_bar` (+17.23 pp) while
Panel A carries it in two support bridges (+9.44 pp), so the panels still do not
nest term by term. That is written into both the source comment and the guard's
docstring.

**Traps for the next iteration.**
- **Citation density is a hard test, not an advisory.** `test_venue_optics.py::
  test_exhibit_density_reaches_the_first_quartile` compares `citations/words`
  against `39/18,738 = 0.00208133`. Before this unit the draft sat at
  `34/16,240 = 0.00209360`, i.e. **95 words** of headroom, not the ~450 the last
  entry recorded. Adding 310 words broke it, and the fix was one earned
  `\citep`. After this unit: `35/16,596`, about **220 words** of headroom. Any
  prose addition larger than that needs a citation in the same commit.
- **The `structural resemblance to the venue` advisory is the same test.** It
  was WARN mid-unit and is `ok` again now; a run showing three advisories rather
  than two means citation density has gone under.
- The producer re-stamp order still holds: run
  `build_vehicle_transition_pair_deck_values.py`, *then*
  `tabulate/render_pair_composition.py`. `pair_composition.tex` came out
  byte-identical again; its `.pdf` and both sidecars changed.
- Editing a section shifts every `paragraph_flow_review` line after the edit and
  the checker counts post-equation continuation lines as their own paragraphs:
  this edit needed three new handoffs (71, 79, 81) and a +36 remap of the
  eighteen after them. `check_jfe_rhetoric_review.py` prints the expected list,
  so run it first and read the `expected=` array.
- `paper/main.pdf` is untracked; only `deck/main.pdf` is committed, and it
  rebuilds byte-differently at identical length, so check it out when the deck
  is untouched.
- `docs/reviews/paper-rhetoric.json` is written at `indent=1`. Writing it at
  `indent=2` reformats all 3,700 lines.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass, 2
advisories (down from 3 mid-unit). Paper 40 pages / 0 undefined, deck 35 pages /
0 undefined. Venue shape: words 16,240 -> 16,596, equations 12 -> 14, citations
34 -> 35. Producer suite 41 passed (39 before, 2 new). Page 10 inspected: both
displays typeset inside the measure with legible underbrace labels.

**Commit:** `ceca448`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- Equations are now 14 against p25 25 and remain the widest venue gap. The
  honest remaining candidates are Section 6, which still defines the cost
  benchmark and reports nothing and is blocked on route cost, and the matched
  estimator's weighting, which Section 3.1 describes in prose.
- The `decomposition_pair_support` record type of
  `vehicle_transition_pair_support.jsonl` is still unread: `baseline_denominator`,
  `comparison_denominator` and `zero_denominator_cell_years` at pooled,
  single-venue and cross-venue scope for all three metrics, plus
  `pair_month_day_scope_support`. This is support metadata, not a claim, so it
  ranks below anything that can change an estimate.
- `market_incidence_support` still exists only for pooled `count_share`. A
  value-weighted Panel A needs a producer change in
  `scripts/run_vehicle_rotation_composition_e0.py`, not a prose pass.
- The deck was not touched and needs no change: no frame reads an `\Incidence`
  macro or either new equation, and the deck remains saturated.

## 2026-08-16 — Panel D's coverage of the market it speaks for

**REGRESSION-CHECK.** Purpose-bound estimand most at risk:
`common_pair_month_day_realised_integration_scope`, the Panel D matched
estimator — the new prose must not restate its reach as the whole sample, and a
coverage ratio must not be read as an estimate. Evidence generation most at
risk: endpoint-composition `5fb7cbf`, D3 `25c755ae`; nothing was re-run, only
read, plus the macro owner's own re-stamp. Prior correction most at risk: the
2026-08-16 non-nesting correction. The new paragraph compares the matched
denominator only against the *identity's* three blocks and never against Panel
A's three market-incidence classes, which partition a different denominator;
that prohibition is written into the source comment.

**Target.** Not a gate blocker: all four remain non-actionable in this worktree
for the reasons the last several entries record (node B is Mukhin, NEEDS-JAVA
since 2026-08-15; node E1 and the empirical model ledger need Studio
generation identities; two unchanged findings passes follows them). Traced
Mukhin to ground once more this iteration: source-set closure fails only at
`non_text_dispositions_closed`, because the 119,236,817-byte reconstructed
openICPSR package is absent from `literature/papers/` in every checkout on this
host. Everything else about the card and the source set is closed. Under step 6
this had to be a claim iteration, and the ledger's own standing candidate list
supplied it.

**What was done.** The `decomposition_pair_support` record type of
`vehicle_transition_pair_support.jsonl` had sat unread for many iterations,
filed as "support metadata, ranks below anything that can change an estimate".
That filing was wrong. Joined to the fixed-effects exhibit's own
`baseline_denominator_mass`/`comparison_denominator_mass`, those rows answer the
first question a referee asks of a within-unit null: on how much of the market?

- Of 762,737 ordered pairs carrying a native-or-stable route in either year,
  26,547 carry one in both and form the identity's continuing block.
- Requiring the same month-day *and* the same realised route scope leaves 5,432
  pairs by count and 5,278 by value.
- Those pairs carry **14.0%** of 2024 routed activity and **24.3%** of 2026, but
  **41.7%** and **39.3%** of the dollars; inside the block alone, 25.2%/50.1% by
  count and 50.8%/62.9% by value.

`_matched_coverage` in `scripts/build_vehicle_transition_pair_deck_values.py`
does the join and emits twelve macros. It refuses to render unless the support
ledger is provably the identity's own partition: each block reports its own mass
over its own year, each year-specific block is empty on the year it is absent
from, no block carries a zero-denominator cell-year, the common block's two
shares equal the identity row's `W_baseline`/`W_comparison` to 1e-12, and the
matched denominator sits inside the common block's. Five focused tests, one per
premise plus the published cells.

**DECISION: promote** at exact scope. The subset relation is structural, not
assumed: a matched cell requires positive mass on the same month-day in both
years, which requires positive mass in both years, so every matched pair is a
common-block pair — verified on the live exhibits at 0 matched pairs outside the
block for both metrics. **DECISION: narrow** the reading of the disclosure. It
does not weaken the headline: the identity's within-pair term is taken over the
whole block with no date or scope condition, is -0.1 pp by count and 0.0 pp by
value, and each matched interval contains the identity term of its own
weighting ([-1.3, +1.7] around -0.1; [-5.6, +3.0] around 0.0). The narrow
conditioned comparison and the wide accounting term put within-pair
substitution in the same place.

**The trap this unit had to avoid.** The obvious move on discovering that Panel
D reaches 14% of 2024 route counts is either to bury it or to treat it as a
defect and go hunting for a wider estimator. Both are wrong. The count coverage
is low *because the matching is demanding*, which is the estimator's purpose,
and the value coverage is three times larger because dollars concentrate in the
pairs and days present on both sides. The honest unit is to publish both
coverage families, say which question each answers, and hand the reader the
second measurement on the wider population.

**Traps for the next iteration.**
- **Value-weighted Panel A is data-blocked, not merely unbuilt.** Retire it from
  the candidate list. `endpoint_candidate_pair_support.parquet` carries
  `market_route_count` but no market-route *value* and no `integration_scope`,
  so neither a value-weighted nor a venue-split market-incidence bridge can be
  formed: `M` does not exist in dollars or by scope in the released ledger. A
  value Panel A needs a change to the endpoint-composition release, not to
  `run_vehicle_rotation_composition_e0.py`.
- **Citation density had 220 words of headroom and the paragraph needed 227.**
  The fix was one earned `\citep` to Amiti, Itskhoki and Konings, whose raw
  passage at `2022-AmitiItskhokiKonings2022Dominant…txt:1263-1300` does exactly
  the count-versus-value reading this paragraph does. After this unit:
  36 citations / 16,823 words, about **470 words** of headroom.
- **`against` as a preposition is a live construction alarm.** The first draft
  of the paragraph used it twice and pushed the draft to 1.755 per 1,000 words
  over a corpus maximum of 1.715. Removing both cleared it. The margin is one or
  two occurrences; check `measure_prose_conventions.py` after any prose add.
- The paragraph-flow remap this time was **+23 lines** for the fourteen handoffs
  after the insertion point, plus one new handoff at line 146. Run
  `check_jfe_rhetoric_review.py` first and read its `expected=` array; the
  section `sha256` must be refreshed *after* the last prose edit, not before.
- `check_deliverable_conformance.py` recompiles the deck, so `deck/main.pdf`
  comes back byte-different at identical length and identical extracted text
  even when no deck source changed. It was committed once in `9d5e34d` by
  accident and restored in the ledger commit; check it out at the end of any
  paper-only unit.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass, 2
advisories. Paper 40 pages / 0 undefined, deck 35 pages / 0 undefined. Venue
shape: words 16,596 -> 16,823, equations 14 (unchanged), citations 35 -> 36.
Producer suite 46 passed (41 before, 5 new). Repository suite
(`--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`):
**2,161 passed, 14 failed**, all in the long-standing v2 provenance-drift set
(`test_weighted_quote` 7, and the rest as recorded in earlier entries). Pages 11
and 12 inspected: the paragraph sets inside the measure, the `\citet` renders,
and Table 3 is unchanged.

**Commit:** `9d5e34d`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- Equations are still 14 against p25 25 and remain the widest venue gap. Section
  6 still defines the cost benchmark and reports nothing, and is still blocked
  on route cost. There is now ~470 words of citation headroom, so a prose unit
  of normal size no longer needs a citation in the same commit.
- The `pair_month_day_scope_support` record type of the support ledger is the
  last unread one. It is the calendar and scope side of the same coverage
  question this unit opened on the pair side, so it is the natural continuation
  and it can sharpen the same claim.
- The deck was not touched and needs no change: no frame reads a coverage macro,
  and the deck remains saturated.

## 2026-08-16 — What the matched condition selects: the cell census behind Panel D

**REGRESSION-CHECK filed before mutation.** Purpose-bound estimand most at
risk: `common_pair_month_day_realised_integration_scope`, Panel D's matched
estimator. The new paragraph reports a *census* of its cells and a thickness
ratio; neither may be read as a coefficient, and the source comment says so.
Evidence generation most at risk: endpoint-composition `5fb7cbf`, D3
`25c755ae`. Nothing was re-run from data — the support ledger and the
fixed-effects exhibit were read, and only the presentation owners restamped.
Prior correction most at risk: the 2026-08-16 non-nesting correction. Cell
classes are *not* the identity's blocks and *not* Panel A's incidence classes;
they partition a third population (pair x month-day x scope) at a finer grain
than either. The reader is keyed on `record_type` and `reporting_scope`
explicitly so a class can never be substituted across factorisations.

**Target.** No gate blocker was actionable. `audit_findings_freeze.py` reports
the same four with identical detail strings: node E1 specification lock
(`stage=design_seed`, `locked_at`/`d3_generation`/`d3_certificate`/
`exploration_generation`/`exploration_certificate` all `missing`), empirical
model ledger (`current_runs=0`, `exploration=not_started`,
`confirmatory_context=invalid`), node B full-text literature ledger (32/33
source-sets, 34/35 five-axis cards), two unchanged findings passes. Mukhin was
re-traced to ground on 2026-08-16 and is NEEDS-JAVA since 2026-08-15; E1 and the
model ledger need the closed E0 exploration and Studio generation identities.
Under step 6 this had to advance a claim, and the previous entry's own standing
candidate supplied it.

**What was done.** The `pair_month_day_scope_support` record type was the last
unread one in `vehicle_transition_pair_support.jsonl`. It is not support
metadata: it is the exact cell partition Panel D was estimated on. It
reconciles with the fixed-effects exhibit cell for cell — its common class holds
94,260 cells against the exhibit's `fixed_effect_cells` of 94,260 and its
188,520 observations, and its endpoint masses are the exhibit's own
`baseline_denominator_mass` and `comparison_denominator_mass` to the byte.

The previous unit answered *how many markets* the matched null reaches. This one
answers *which of their trading days it keeps*, and that turns out to be the
question that explains the count/value gap the previous unit could only assert:

- 94,260 cells clear the joint condition, out of 1,726,215 active in 2024 and
  815,483 in 2026: **5.5%** and **11.6%** of the two years' cells.
- Those cells carry **14.0%** and **24.3%** of the years' routes, so a matched
  cell is **2.6x** as busy as the average active cell in 2024 and **2.1x** in
  2026.
- On the value perimeter, **5.7%** and **11.6%** of cells are matched and a
  matched cell carries **7.4x** the average cell's dollars in 2024 and **3.4x**
  in 2026.
- The 20% value-agreement requirement empties **142,972** cell-years the count
  measure keeps; the count metric's own figure is 0.

The economic reading, and the point of the paragraph: the joint condition is a
**recurrence** condition. A cell survives only if the same market traded on the
same day of the calendar year in both years, and the chance of that rises with
how often the market trades. So Panel D describes the routinely traded core, and
the dollar multiple says the core is where value concentrates. That is why the
value coverage is three times the count coverage — the same fact the previous
paragraph reported without being able to explain it.

**New owner code, all in the existing presentation owner.**
`_matched_cell_support` and `_cell_support_classes` in
`scripts/build_vehicle_transition_pair_deck_values.py` refuse to render unless:
the three classes exist exactly once each; every class holds cells and finite
non-negative mass; each one-sided class is empty on the year it is absent from;
the three agree on the emptied-cell-year count (it is a property of the measure,
not of a class); the common class holds exactly the exhibit's `fixed_effect_cells`;
`observations` is exactly twice that; and the common class's two endpoint masses
equal the exhibit's own to 1e-12. `_strict_cell_populations_agree` additionally
pins that `matched_strict_count_share` and `strict_intermediation_value_share`
hold one cell population, so the value multiple and the strict count multiple
provably speak for the same cells. Twelve macros; seven focused tests, one per
premise plus the published cells. `_pairs` was generalised to `_units` rather
than duplicated for cells.

**DECISION: promote** at exact scope. Thickness is a ratio of two published
shares over one frozen partition, with the estimator's own artifact pinning the
numerator. It is a selection diagnostic and the source comment forbids reporting
it as a coefficient.

**The trap this unit had to avoid.** The obvious sentence was "the matched
comparison is measured where most of the dollars are." It is not: 41.7% and
39.3% are pluralities. The draft said "most of them do" and it was wrong by the
project's own numbers; the published sentence says two-fifths.

**Traps for the next iteration.**
- **`d3-release-test-afoxinb6/` was tracked in git, not ignored.** Ten files
  plus four manifests, 89 KB, first committed by `0aa532d` on 2026-08-16 while a
  test was running. `.gitignore` line 92 already forbade the pattern, so it never
  showed as untracked dirt and eleven iterations walked past it. It is removed in
  this commit. Its presence was almost certainly the cause of the intermittent
  `test_analysis_release.py::test_d3_publication_leases_ordinary_inputs_through_pointer_install`
  failure seen in this iteration's first full-suite run: that test passed in
  isolation and passed in the full suite after the removal. **A gitignore rule
  does not protect an already-tracked path — check `git ls-tree` for leaked
  fixture directories, not just `git status`.**
- **Regenerating the deck-values macro file stales `output/tables/pair_composition.tex`.**
  Rerun `scripts/tabulate/render_pair_composition.py` in the same unit or
  `tests/test_dominance_tables.py::test_generated_table_lineage_is_current`
  fails. This is now the third entry to record it.
- **Do not `git stash` mid-iteration to baseline the pre-existing failures.**
  Tried here; the verification run hit the 2-minute foreground timeout and left
  the tree at HEAD with the work stashed. Recovered by `git stash pop`, but the
  cheap and safe check is to run the single suspect test in isolation.
- The paragraph-flow remap was **+21 lines** for the fourteen handoffs after the
  insertion point, plus one new handoff at line 169. `docs/reviews/paper-rhetoric.json`
  is written with `indent=1`; a naive `json.dump(..., indent=2)` reformats all
  1,928 lines. Refresh the section `sha256` *after* the last prose edit.
- Citation headroom is now about **255 words** (36 citations / 17,048 words,
  down from ~470 at 16,823). The next prose unit of normal size will need an
  earned `\citep`.
- `against_prep` sits at 1.579 against a corpus max of 1.715: roughly one more
  occurrence of `against` as a preposition is available in the whole manuscript.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass, 2
advisories. Paper 41 pages / 0 undefined (was 40), deck 35 pages / 0 undefined.
Venue shape: words 16,823 -> 17,048, equations 14 (unchanged), citations 36
(unchanged). `audit_deck_evidence.py` PASS. `check_jfe_rhetoric_review.py` exits
0. `measure_prose_conventions.py`: no registered construction out of range.
Producer suite 53 passed (46 before, 7 new); `tests/test_dominance_tables.py` 9
passed after the restamp. Repository suite
(`--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`):
**2,169 passed, 13 failed**, exactly the long-standing v2 provenance-drift set
(`test_weighted_quote` 7, `test_vehicle_role_models` 3,
`test_audit_findings_freeze` 1, `test_variable_registry` 1,
`test_vehicle_transition_e0` 1); no new failures. Page 12 inspected: the
paragraph sets inside the measure, the multiples read correctly, and the
following named-pair paragraph is unchanged. `deck/main.pdf` restored after each
conformance run; no deck source changed.

**Commit:** `fc36e8b`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- Every record type of `vehicle_transition_pair_support.jsonl` is now read and
  published. That candidate list is exhausted.
- Equations remain 14 against p25 25 and are the widest venue gap. Section 6
  still defines the cost benchmark and reports nothing, still blocked on route
  cost.
- Remaining unused certified rival evidence: `routing_technology_windows.jsonl`
  (pre/post windows around auto-router releases), under spec-lock claim 1, whose
  `execution_gate` is `blocked_transaction_state_frontier` and whose
  `forbidden_interpretation` bars an aggregator-causality reading — descriptive
  window composition only.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes.
- The deck was not touched and needs no change: no frame reads a cell-coverage
  macro, and the deck remains saturated.

## 2026-08-16 — What the corridors with a choice are: the dollar-endpoint split

**REGRESSION-CHECK filed before mutation.** Purpose-bound estimand most at
risk: `vehicle_transition`'s pair-level four-term decomposition, Panels B and C.
The new split is a partition of the *same* certified allocation inside each
component, so it had to reconcile to `\MarginNewPairTotal`, `\PairPooledReweight`,
`\PairValueReweight` and the already-published `\Locked*` WETH cells to 1e-6; it
does, on all four margins. Evidence generation most at risk:
`vehicle_transition_pair_contributions.parquet`, endpoint-composition `5fb7cbf`,
D3 `25c755ae`. Nothing was re-run from data. Prior corrections most at risk:
(a) the 2026-08-16 non-nesting correction — these three endpoint classes
partition the pair-level allocation scope, which excludes the common-support
mass bridge, and are not Panel A's incidence classes, not the identity's blocks,
and not Panel D's cells; (b) the WETH-endpoint eligibility identity, which the
producer still proves before anything is reported and which the *new* class had
to be proved **not** to be.

**Target.** No gate blocker was actionable; `audit_findings_freeze.py` reports
the same four with identical detail strings (node E1 specification lock,
`stage=design_seed` with the four generation/certificate fields `missing`;
empirical model ledger, `current_runs=0`; node B full-text literature ledger,
32/33 source-sets and 34/35 five-axis cards, Mukhin NEEDS-JAVA since 2026-08-15;
two unchanged findings passes). Under step 6 this had to advance a claim.

**Where the candidate came from, and a correction to the previous entry.** The
previous entry named `routing_technology_windows.jsonl` as "remaining unused
certified rival evidence." That is wrong and the ledger has now said it twice
(lines 2132 and 3742). It is fully consumed: `paper/sections/05-rivals.tex`
inputs `output/tables/routing_technology_windows.tex` as `tab:router-windows`
and the subsection reads eleven macros off it. **Do not re-open it as unused.**
The real gap was elsewhere. Section 3 publishes the WETH-endpoint eligibility
split of both composition margins and publishes an `\Open*` remainder for each,
but nothing anywhere said what those choice-live corridors *are* — and the
conclusion closes by demanding exactly that: "It has to say why the markets
forming and growing over this period attach themselves to a stablecoin."

**What was done.** The choice-live remainder of each margin is partitioned on
whether a stablecoin stands at an endpoint of the ordered pair. Three classes,
mutually exclusive and exhaustive: WETH endpoint (the published identity),
stablecoin endpoint, and neither candidate at an endpoint.

- The two weightings rank the classes in **opposite orders**. By route count the
  dollar-endpoint corridors supply **26.0%** of the reweighting margin and
  **28.7%** of the entry margin, less than the eligible corridors' 73.3% and
  65.9%. By value they supply **57.3%** and **76.4%**, more than the eligible
  corridors' 42.6% and 16.0%.
- Corridors with neither candidate at an endpoint are the many and the small:
  **142,831** enter in 2026 and **13,390** trade in both years, and they supply
  **+1.7 pp** and **+0.0 pp** of the two value margins.
- Inside the dollar-endpoint class the movement is again reallocation. Its
  activity-weighted stablecoin share by value rises **21.0% → 61.6%** while its
  within-pair term is **−0.0 pp**: the rise is weight moving between corridors
  in the class, not a market changing intermediary. Its own activity weight
  *falls*, 67.7% → 56.7%, so this is not the class taking over the market.

The economic reading, and the answer to the conclusion's closing question:
weighted by the dollars they move, the markets carrying the rotation are markets
that already had a dollar on one side. The challenger's vehicle role expanded
into the corridors where its endpoint demand already sat. That is Krugman's
secure volume, and the paragraph closes on it as an earned citation (raw lines
376--383 of the 1980 JMCB text: a currency short of secure volume cannot take
the vehicle role from an incumbent however transaction costs fall).

**The trap this unit had to avoid.** The dollar-endpoint class would be
worthless if it were a second eligibility class. It is not — a trade into USDC
can still be carried by WETH or by USDT — but that has to be *proved on the
data*, not asserted. `_open_corridor_endpoints` refuses to render unless some
corridor in the class routes below a stablecoin share of one, some routes above
zero, fewer than a quarter sit at one in both years (live: 4.7% by count, 4.8%
by value), and the class's within-pair term is free to move. Two of the five new
tests exercise exactly this.

**New owner code, all in the existing presentation owner.**
`_open_corridor_endpoints` and `OPEN_ENDPOINT_CLASSES` in
`scripts/build_vehicle_transition_pair_deck_values.py`, called from the existing
eligibility block of the renderer. Twenty-two macros per weighting. Five focused
tests, one per premise plus the published cells.

**DECISION: promote** at exact scope. It is a partition of one frozen
allocation, reconciled cell for cell to the margins already published, with the
non-degeneracy of the new class proved before any share of it is reported. The
source comment forbids reading any class share as a coefficient.

**Traps for the next iteration.**
- **The producer fixture encoded continuing-pair activity weights that were not
  a distribution** (five pairs at 0.004/0.045, summing to 0.02 and 0.20). Every
  `\Locked*Weight*` macro is a *share of routed activity*, so the fixture was
  asserting an impossible world. Fixed here via `_COMMON_WEIGHTS`, which closes
  on one in each year; `LockedWeightBase/End` moved 0.8%/9.0% → 20.0%/45.0% and
  `MarginReweightWeightBase/End` 0.40%/4.50% → 12.00%/25.00%. **If you add a
  continuing pair to that fixture you must rebalance the dict.**
- **A share of a decomposition remainder is not always a quantity.** The
  dollar-weighted reweighting remainder is negative in one integration scope, so
  every class figure is published as a share of the *margin*, which
  `_endpoint_eligibility` already guarantees positive. The first draft divided by
  the remainder and would have printed a share of a negative base.
- **Regenerating the deck-values macro file stales `output/tables/pair_composition.tex`.**
  Rerun `scripts/tabulate/render_pair_composition.py` in the same unit. Fourth
  entry to record it.
- **The deck's three-margins frame is at its ceiling.** Adding the new clause
  overflowed page 13 and clipped the `\decknote`. Fixed by dropping the body
  from 8.2/9.2 to 7.8/8.6, matching the sibling frames, and tightening the
  clause. There is no room left on that frame; the next addition must displace
  something.
- **Do not embed a backtick-quoted identifier in a `./scripts/run -c "..."`
  heredoc.** The shell ran `_open_corridor_endpoints` as a command and silently
  wrote an empty string into the deck comment. Use the Edit tool or single
  quotes.
- The paragraph-flow remap was **+20 lines** for the nine handoffs after the
  insertion point, plus one new handoff at line 256. Refresh the section
  `sha256` *after* the last prose edit — it was refreshed twice here because the
  citation landed after the first refresh.
- **Citations are now a live venue gap, not headroom.** 37 against p25 39 at
  17,370 words. The advisory count went 2 → 3 when the paragraph landed and back
  to 2 once Krugman was earned, but the citation line itself stays flagged.
  Closing it needs two or three more *earned* engagements with the literature,
  not padding.
- `against_prep` sits at 1.548 (corpus max 1.715) and `what_cleft` at 0.704
  (max 0.777). Both are one or two occurrences from the ceiling.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass, 2
advisories. Paper 41 pages / 0 undefined, deck 35 pages / 0 undefined. Venue
shape: words 17,048 → 17,370, equations 14 (unchanged), citations 36 → 37.
`audit_deck_evidence.py` PASS. `check_jfe_rhetoric_review.py` exits 0.
`measure_prose_conventions.py`: no registered construction out of range.
Producer suite 58 passed (53 before, 5 new); `tests/test_dominance_tables.py` 9
passed after the restamp. Repository suite
(`--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`):
**2,174 passed, 13 failed**, exactly the long-standing v2 provenance-drift set
(`test_weighted_quote` 7, `test_vehicle_role_models` 3,
`test_audit_findings_freeze` 1, `test_variable_registry` 1,
`test_vehicle_transition_e0` 1); no new failures. Paper pages 15 and 16 and deck
page 13 inspected: the paragraph sets across the page break, the macros render,
and the deck frame now clears its footer.

**Commit:** `669f3a2`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration.**
- The pair-contributions allocation now has three published partitions: breadth,
  WETH eligibility with its two scope splits, and endpoint composition. The
  obvious remaining cut is the **entry cohort's own endpoint composition read
  against the exit cohort's** — the corridor-replacement paragraph reads the two
  cohorts' routing rates but not what the arriving corridors *are*, and this
  unit's classes apply to it unchanged.
- Equations remain 14 against p25 25 and are the widest venue gap. Section 6
  still defines the cost benchmark and reports nothing, still blocked on route
  cost. Section 8's appendix carries **zero** displayed equations, which is
  where a JFE paper of this shape would put the estimator definitions it
  currently states only in prose. That is a real and unblocked unit.
- Citations are now the second venue gap; see the trap above.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes.

## 2026-08-16 — Why the arriving corridors route differently: the replacement gap split

**REGRESSION-CHECK filed before mutation.** Purpose-bound estimand most at risk:
`exclusive_pair_contribution`, the netted corridor-replacement margin (2024--2026,
pooled, both metrics). It compares **two disjoint populations of corridors**, so
the split had to stay an exact partition of that frozen term and no sentence may
read its rate side as a corridor changing intermediary. Evidence generation most
at risk: `vehicle_transition_pair_contributions.parquet`, read through
`require_certified_presentation_source`; nothing was re-run from data. Prior
corrections most at risk: (a) "a share of a decomposition remainder is not always
a quantity" — shares are formed only against the netted term, proved positive,
because the other-endpoint kind's composition term is negative in both
weightings; (b) "regenerating the deck-values macro file stales
`output/tables/pair_composition.tex`" — `render_pair_composition.py` was rerun in
the same unit, fifth entry to record it.

**Target.** No gate blocker was actionable; `audit_findings_freeze.py` reports
the same four (node E1 specification lock; empirical model ledger; node B
full-text literature ledger; two unchanged findings passes). Took the unit the
previous iteration named: the entry cohort's own composition read against the
exit cohort's.

**What the unit is.** `_support_cohorts` publishes the replacement gap and stops.
The gap is two numbers and hides two different economic claims: the arriving
corridors may be a *different mix of markets*, or markets of the *same kind* may
route differently. `_cohort_endpoint_margins` separates them exactly on the three
endpoint kinds already used in the module,

    s_enter - s_exit = sum_c (w_enter,c - w_exit,c) sbar_c
                     + sum_c wbar_c (s_enter,c - s_exit,c),

the standard symmetric midpoint identity, which is **exact, not an
approximation**. The producer proves both sums close on the cohort gap (1e-12)
and the gap on that scope's own `exclusive_pair_contribution` (1e-6) before
rendering. Pooled only: the scoped cohort rates answer a question about
integration, and pairing a scope weight with the pooled gap is exactly the
confusion the scope suffix exists to prevent.

**The result, and it is a real one.** The two weightings disagree, and the
disagreement is the finding.
- **By count**: composition `+11.7` pp of the `+17.8` pp term (65.9%), rate
  `+6.1` pp (34.1%). Of the composition part, `+11.4` pp is a single class —
  wrapped-ether-paired corridors are **28.9%** of arriving activity against
  **5.2%** of departing. Those corridors cannot use wrapped ether to intermediate
  their own endpoint, so a stablecoin carries them by construction and their
  routing rate is one in *both* cohorts. Roughly **two-thirds of the largest
  count margin is the arrival of markets where the vehicle was never in
  question.** That is a material qualifier on a claim already on the deck.
- **By value the ordering reverses**: composition `+3.0` pp (15.4%), rate
  `+16.2` pp (84.6%). Arriving stablecoin-paired corridors send **81.7%** of
  their dollars through a stablecoin where the departing corridors of the same
  kind sent **6.3%**; other-endpoint arrivals **48.3%** against **0.9%**.

**DECISION: promote** at exact scope. It is an exact partition of one frozen
term, reconciled to it before publication, with the wrapped-ether class's zero
rate term proved rather than assumed. The source comments in the producer, the
paper and the deck all forbid reading the rate side as pair-level substitution.

**New owner code, all in the existing presentation owner.**
`_cohort_endpoint_margins` and `COHORT_ENDPOINT_CLASSES` in
`scripts/build_vehicle_transition_pair_deck_values.py`, called from the pooled
branch of the existing cohort block. 22 macros per weighting, prefix `Replace`.
Five focused tests, one per premise.

**Traps for the next iteration.**
- **The `neither_nor` construction alarm has almost no headroom.** Three
  `neither`s in one new paragraph took the draft to 0.480 against a corpus
  maximum of 0.294. It now sits at **0.274**, one occurrence from the ceiling.
  The regex is `\bneither\b|\bnor\b`, so `nor` counts too.
- **Do not line-wrap an artefact path inside a `%` provenance comment.**
  `tests/test_paper_provenance.py` reads the fragment on each line and demanded
  a file called `literature/text/1993-DowdGreenaway1993Cu`.
- **`docs/reviews/paper-rhetoric.json` is written with `indent=1`.** Dumping it
  at `indent=2` reformats all 1,950 lines. Round-trip it with
  `json.dumps(d, indent=1, ensure_ascii=False)` plus the trailing newline.
- **Inserting a paragraph shifts every later handoff line.** Here it was **+27**
  for the seven handoffs after the insertion point, plus one new handoff at 294.
  Refresh the section `sha256` *after* the last prose edit; it was refreshed
  twice here because the prose-convention fix landed after the first refresh.
- **The three-margins deck frame really was at its ceiling.** Adding the
  composition clause pushed the body from four lines to five and pressed the
  `\decknote` onto the footer. Fixed by *displacing* content, as the previous
  entry predicted would be necessary: the fourth-term sentence
  (`\BlockShift`/`\BlockTerm`) left the frame, the closing clause dropped its two
  dollar-endpoint percentages, and the note was tightened by a line. Body stays
  at 7.8/8.6 to match the sibling frames. **When you displace slide text, delete
  the matching sentence from the `ESTIMAND-BOUNDARY` comment** — it described the
  fourth term for a frame that no longer carries it.
- Citations moved 37 -> 38 against p25 39 on an *earned* second engagement with
  Dowd and Greenaway (excess inertia binds the agents already holding the
  incumbent; their closing extension hands displacement to the changing
  composition of the trading population). One more earned engagement closes that
  venue line.

**Validation.** `check_deliverable_conformance.py`: all blocking checks pass, 2
advisories. Paper 42 pages / 0 undefined, deck 35 pages / 0 undefined. Venue
shape: words 17,370 -> 17,691, equations 14 (unchanged), citations 37 -> 38.
`audit_deck_evidence.py` PASS. `check_jfe_rhetoric_review.py` exits 0.
`measure_prose_conventions.py`: no registered construction out of range.
Producer suite 63 passed (58 before, 5 new). Repository suite
(`--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`):
**2,179 passed, 13 failed**, exactly the standing v2 provenance-drift set
(`test_weighted_quote` 7, `test_vehicle_role_models` 3,
`test_audit_findings_freeze` 1, `test_variable_registry` 1,
`test_vehicle_transition_e0` 1); no new failures. Paper page 16 and deck page 13
inspected against the previous build: the paragraph sets, the macros render, and
the frame's note clears the footer with the same margin it had before.

**Commit:** `1e678cf`.

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).

**For the next iteration — READ THIS FIRST.**
- **A new Java interjection landed mid-unit and is the next iteration's whole
  job.** `logs/grind-queue.md` line 338, WeCom 2026-08-16T12:50Z, pushed in
  `fde69fa` and amended in `2555537` *after* this iteration had already read the
  queue: **deck analytics pass — kill the chronological spine, lead with control
  sets, rebuild the conclusion frame.** It says take it at the next clean
  boundary and not to interrupt a running unit, which is why it was not started
  here. It is five parts and at least one full iteration.
- **One internal inconsistency in that item to resolve before building.** Part
  (2) withdraws the specification-curve frame outright — `run_dominance_
  specification_curve.py` is on the retired-estimand list in
  `audit_findings_freeze.py` and building from it would re-red the refresh-graph
  check — but part (4)'s list of designs that hold the market fixed still names
  "the specification curve". Build (4) from the live designs only: matched
  within-pair, pair-by-day FE, and the `(4w)` control-window ladder inside
  `dominance_regressions.jsonl`.
- The composition/rate split landed here is a **third** independent statement of
  the same thesis and belongs in the rebuilt conclusion frame: aggregate share
  rotated hard, matched within-pair shows nothing, and even the corridor
  replacement that carries the count margin is two-thirds the arrival of markets
  where the vehicle was never a choice.
- Equations remain 14 against p25 25 and are still the widest venue gap. Section
  8's appendix carries eleven `\[...\]` displays that `measure_venue_optics.py`
  does not count — it counts only `\begin{equation|align|gather}`. Numbering
  them purely to move the metric would be filler; the real unblocked unit is the
  estimator definitions Section 8 states only in prose.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes.

## 2026-08-16 — Java's deck analytics interjection: control ladder in, chronological spine out

**Targeted.** `logs/grind-queue.md` line 338, the WeCom 2026-08-16T12:50Z
interjection, which outranks the gate's own blocking list. Parts (1), (3), (4)
and (5); part (2) was withdrawn by the supervisor and stayed withdrawn.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: dominance quality
holding the trade fixed, which must never share an axis or a number with the
aggregate share rotation (`docs/research-workflow.md`: coefficients from
different estimands never share one specification curve). Evidence generation at
risk: `dominance_regressions.jsonl` itself. Prior correction at risk: the
`68d4df7` retirement of `run_dominance_specification_curve.py`.

**The thing the queue item did not know.** `output/exhibits/dominance_regressions.jsonl`
**did not certify**. `require_certified_presentation_source` rejected it, and the
reason was real rather than cosmetic: the exhibit was written at `c8a7ccf`, and
`2076e5e` ("use canonical fixed-effect absorption") and `a63e53b` ("centralize
empirical inference") afterwards replaced the producer's hand-rolled `demean`
and `ols_cluster` with `absorb_fixed_effects` and `ols_clustered`. Its input
panel `data/processed/counterfactual_dominance_clean.parquet` **is not in this
checkout and is not in the sibling store either** (searched `../defi-dominant-currency/data/`
and every sibling worktree; only a stale `--help` lock file remains), so the
exhibit cannot be re-derived here. Presenting it blind would have put possibly
superseded coefficients on an audience-facing slide.

Resolved by proving the drift is bookkeeping rather than science, not by
asserting it. `tests/test_dominance_estimator_equivalence.py` runs the
superseded implementation against the canonical one over the same switching-cell
design, both outcomes, three sample sizes: **max |beta, se| difference 3e-18,
max absorption difference 1.8e-15**. The payload is also byte-unchanged since
its only commit. On that basis the sidecar was recertified through `stamp()`
with the evidence written into its `notes`. The test is the standing guard, not
a one-off: if `ols_clustered`'s CR1 scaling ever changes, it fires and the slide
must be regenerated before it is shown again. **Delete it when Studio
regenerates the exhibit from the panel.**

**Built.** `scripts/figure/build_dominance_ladder.py` — one owner for both the
figure (`output/figures/dominance_control_ladder.pdf`) and the macros
(`output/exhibits/dominance_ladder_deck_values.tex`), so the eleven validity
guards exist once. Panel A is specification strictness, panel B the matched-cell
width ladder; one estimand throughout.

**Two deck frames, both cut on a design axis.**
- Page 14, *Holding the trade fixed dissolves the intermediary gap*: pooled
  $-4.9$ points (SE 1.82) over 102,845 routes → same pair, same day $+9.4$
  points (SE 8.47) on 703 switching cells, with the detectable band (23.7
  points) drawn on that column and the 120-day widening at $+10.9$ (SE 6.87,
  n=7,465). Says the bridge out loud: two questions, one answer.
- Page 18, *The market changed, not the trade*: $+25.7$ pp across the whole
  market → $-0.1$ pp within pairs traded in both years → $+0.2$ pp (SE 0.8,
  94,260 matched cells), with the dominance estimand beside it behind a rule in
  its own units. Banner: "Stablecoins won the market, not the trade."

**Chronological-axis inventory (queue part 5).** Primary visual axis is calendar
time: **2 frames before, 1 after**. The rotation bands stay, once and early, as
the motivating fact. Two frames keep a calendar element as *setup* and are
correct on that axis — the 02-objects deployment timeline and the A2
backing-regime heatmap measure exactly deployment dates and time-varying
backing. The V1–V4 strip is cut on protocol design. Nothing else needed re-cutting.

**DECISION: narrow** — guardrail (3)(b) as written cites the retired
specification curve ($-25.26$ bps, p=0.037). On the live estimand the continuous
outcome is $+186$ bps (SE 106, p=0.078) and **agrees** with the binary column.
The frame displays it regardless, so the functional form is visible rather than
chosen; the producer raises if the two ever split, which is when the frame's
sentence has to change.

**Traps for the next iteration.**
- **`uv run pytest` alone cannot import `scripts.*`.** There is no `conftest.py`
  and no `pythonpath` setting; 71 test modules fail to collect. Use
  `PYTHONPATH="$PWD/src:$PWD" uv run pytest` or `./scripts/run`.
- **`latexmk` is not installed on this host.** `tectonic` is, at
  `/opt/homebrew/bin/tectonic`; `check_deliverable_conformance.py` already falls
  back to it. Compile with `tectonic -X compile --keep-logs main.tex`.
- **Do not put `\hyphenpenalty=10000` in a TikZ `font=` key.** It typesets
  `0pt plus2em` into the slide — the `align=center` skip registers leak. Fix
  hyphenation by widening the node or shortening the words. The picture is
  inside a `\resizebox`, so widening the whole `tikzpicture` costs only a few
  percent of type size.
- **Author deck figures at the aspect ratio of the slot they land in.** The
  first cut of the ladder was 10.6×3.9in and the height cap scaled it to 68% of
  the text width, which put the tick labels at under 4pt. At 7.4×2.0in the width
  binds instead and the figure fills the frame.
- The one-day rung of the window ladder is numerically identical to
  `(4) pair-by-day FE` and is the only row carrying `identifying_cells` and
  `mde_80`; specs (1)–(5) still have both as NaN. The producer asserts the
  identity before borrowing them. **Populating them properly needs the panel**,
  so it waits for the Studio regeneration.

**Validation.** Deck 36 pages / 0 undefined; the only overfull boxes are the two
that predate this change (8.14pt, 5.06pt at 04-results). `audit_deck_evidence.py`
PASS. `check_deliverable_conformance.py`: all blocking checks pass, 2 advisories,
paper 42 pages / 0 undefined. Producer suite 116 passed (17 new). Repository
suite: 212 passed with the single standing `test_audit_findings_freeze`
failure, confirmed pre-existing by re-running it on a stashed clean tree.
Pages 14 and 18 inspected against the previous build.

**Commits:** `e8a785c` (evidence layer), `2a797b7` (frames).

**Blocking count: 4** (unchanged: node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes).
`refresh graph excludes retired estimands` still PASSes.

**For the next iteration.**
- The queue is now empty of unchecked items except the M3 12:03 handoff, whose
  live remainder is the E1/D3 generation identities and the two unchanged
  findings passes.
- **NEEDS-JAVA (low urgency, not blocking):** `data/processed/counterfactual_dominance_clean.parquet`
  exists on no reachable host. Regenerating it via `scripts/build_counterfactual_dominance.py`
  would let `run_dominance_regressions.py` restate the ladder under the current
  producer, populate `mde_80`/`identifying_cells` on specs (1)–(5), and retire
  `tests/test_dominance_estimator_equivalence.py`. Until then the deck frame
  rests on the equivalence proof, which is sound but is a standing obligation.
- Equations remain 14 against p25 25 and are still the widest venue gap; the
  unblocked unit there is still the Section 8 estimator definitions that are
  stated only in prose.

## 2026-08-16 — The estimator Section 8 stated only in prose: Balancer parameter identification

**Targeted.** Not a gate blocker. The freeze audit ran twice this iteration and
returned the same four: node E1 specification lock (`locked_at`, `d3_generation`,
`d3_certificate`, `exploration_*` all missing), empirical model ledger
(`current_runs=0`, `exploration=not_started`, `confirmatory_context=invalid`),
node B full-text literature ledger, and two unchanged findings passes. Node B was
traced to ground again and is unchanged: `source_set_record_closed` fails only at
`non_text_dispositions_closed`, because the 119,236,817-byte reconstructed
openICPSR package for `Mukhin2022InternationalPriceSystem` exists in no checkout
on this host and `literature/papers/` is gitignored, so it is not recoverable from
history. Everything else about that card and source set is closed. It stays
**NEEDS-JAVA** (open since 2026-08-15). Under step 6 this had to advance a claim
or a section, and the ledger's own standing candidate supplied it.

**REGRESSION-CHECK filed before mutation.** Estimand at risk: the *constructed*
side of the route-cost comparison, specifically which Balancer pool-days enter the
counterfactual opportunity set. Nothing written may widen or narrow that
perimeter, and the route-cost estimand itself stays blocked and unreported.
Evidence generation at risk: `output/exhibits/weighted_quoter_validation.jsonl`,
read and never regenerated; any new aggregate had to reconcile to the already
published 256 priced pool-days. Prior corrections at risk: (a) a component
validation is never reported as venue coverage, so the standing "not for Balancer
as a whole" sentence had to survive; (b) the ledger's own correction that
numbering displays purely to move `measure_venue_optics.py` is filler, so a
display was added only where it defines an estimator that was prose-only, and
numbered only where cross-referenced.

**What was wrong.** Appendix B.4 stated its estimator in one sentence while B.3
one page earlier displayed the exactly analogous `\widehat A_p`. Four objects that
decide which pool-days can be quoted were invisible to a referee: the fitting-error
functional and the quantile it is read at; the requirement that a candidate
parameter price nine tenths of a pool's fitting trades before it can stand for the
pool (`MIN_QUOTED_SHARE`, mentioned nowhere in the paper); the reciprocal-exponent
pooling of the two trade directions, which is a restriction the invariant implies
and which doubles the trades pinning one number; and the nested three-tier
acceptance rule in `fit_pool_day`, under which reading is tried before fitting and
the fee before the weights so each tier adds at most one free scalar. The paper
also never said how the fitting and evaluation sets are formed, though both tables
quote errors "on trades no fit ever saw" (they alternate: `obs[::2]`, `obs[1::2]`).

**What was done.** All four are now displayed as a transcription of
`src/ddvc/pricing/weighted.py` and `scripts/validate_weighted_quoter.py`. The tier
rule is `\eqref{eq:weighted-fit}` and is cited from the coverage appendix, which
previously confined the priced Balancer sample by state reconstruction alone. The
error functional is `\mathcal{E}_p` and not `E_p`, because `test_paper_provenance`
treats a display line whose first character is not a backslash as prose, and
`Q_{0.90}` on such a line is read as an unsourced numeric claim; the Curve display
above passes only because it opens on `\widehat`.

**New evidence, not notation.** Summing `pools_by_fit_mode` over the twelve
validation days: **209 reported, 43 fee_fitted, 4 weight_fitted**, partitioning the
published 256 `pools_priced`. Four fifths of the priced sample therefore carries no
fitted parameter at all, which bounds how much of the constructed side of the cost
comparison rests on fitting rather than on reading. `tests/test_weighted_quote.py`,
the artefact's own owner, now reconciles that sentence against the exhibit and
checks the three modes partition `pools_priced`. Nothing verified it before:
`test_paper_provenance` deliberately checks that a number cites an artefact and
not that it matches one.

**DECISION: promote** at exact scope. The estimator, its coverage condition, its
tier rule and the tier incidence enter the appendix; the route-cost estimand they
serve stays unreported. Calibrated against Huang, Ranaldo, Schrimpf and Somogyi
(2025 JFE) at `literature/text/...jfe.txt:1140-1215`, whose LSTAR passage states
the functional form, bounds the free parameters and says what the bounds are for,
gives the estimation procedure, and only then reports what it implies. That passage
is now registered in `paper-rhetoric.json` as a raw exemplar for the appendix, with
six new handoffs and the entries for lines 176 and 180 rewritten.

**Validation.** Paper 43 pages / 0 undefined / 0 overfull. Deck untouched at 36
pages; its PDF was rebuilt twice by the conformance runs and restored both times,
so the committed binary is unchanged. `check_deliverable_conformance.py`: all
blocking checks pass, 2 advisories. Freeze audit: RED, same 4 blocking, run before
and after. Repository suite (excluding the two modules whose *collection* aborts on
the standing `v2_audit_token_decimals.parquet.prov.json` drift): **2,198 passed,
13 failed**, and all 13 reproduce at `HEAD~1` in a throwaway worktree, so none are
mine. Pages 33 and 34 of the paper inspected as rendered images.

**Traps found this iteration.**
- **Never run the freeze audit and the full pytest suite at the same time.** The
  audit went to 0% CPU in state `S` and sat there for over an hour while pytest
  held whatever it was waiting on. Run them one after the other. Solo the audit
  takes about 17 minutes.
- **A bare `pytest tests/` spends 75 minutes in collection and then aborts** on
  the `v2_event_source_release` provenance drift. Always pass
  `--ignore=tests/test_route_cost_panel.py --ignore=tests/test_route_state.py`;
  with those two out it is 5 minutes.
- **Prose length has a citation cost.** Adding roughly 700 appendix words with no
  citation pushed citation *density* below the venue quartile and turned
  `test_venue_optics` from green to a third advisory. The fix was the Lehar and
  Parlour reference the passage genuinely needed to position itself against the
  closest published state reconstruction, not filler.
- **`measure_prose_conventions.py` caught `rather than` at 0.593 against a corpus
  maximum of 0.572** from two new uses. Both thoughts were rewritten rather than
  word-substituted; the draft is now at 0.460.
- **`json.dumps` on `paper-rhetoric.json` must use `indent=1`.** At `indent=2` a
  fifty-line edit renders as a 3,950-line diff.

**Commit:** `1172af1`.

**Blocking count: 4** (unchanged). Venue shape: words 17,691 -> 18,416,
equations 14 -> 15, citations 38 -> 39 (now *in range*; equations and words remain
the two gaps).

**For the next iteration.**
- **A new supervisor interjection landed in `logs/grind-queue.md` at
  2026-08-16T15:50Z and is unchecked. It outranks the gate and is the first unit.**
  Java's third statement of the same objection, now about estimators and not deck
  framing: build the non-chronological regression suite. Five parts, all of which
  the interjection states run on green route-only D3 today: (1) promote vehicle
  excess use to a lead result because it is cross-sectional by construction;
  (2) build the backing-regime and token cross-sections as their own arm;
  (3) convert 2024-versus-2026 contrasts into date-by-date repeated cross-sections
  over the 2,332-day release and report the dispersion; (4) re-specify the retired
  non-calendar designs, which were retired for definitional and not design defects;
  (5) state the blocked set plainly instead of letting a calendar comparison stand
  in for a design waiting on data. It also asks for a before/after count of
  headline results whose identifying variation is calendar time. It was carried
  into the tree unchecked by `1172af1`; do not tick it there until it is closed.
- Equations remain 15 against p25 25. The appendix's other prose-only procedure is
  the route-identification rule in Appendix A, which defines connected chains,
  order splits and disconnected groups entirely in words.
- The M3 12:03 handoff stays unchecked; its live remainder is still the E1/D3
  generation identities and the two unchanged findings passes.

**Correction to the handoff above, written minutes later.** The queue slot was
rewritten while this entry was being committed. The 2026-08-16T15:50Z item is
**superseded** by a 2026-08-16T15:55Z interjection in the same slot, and the
instruction changed materially. Java is not asking for calendar comparisons to be
removed: "Time axis is ok but you can just control it in eg fixed effect. Give me
more results ! Ok if on preliminary data - if computation not overwhelmed then keep
trying and building in parallel and write into paper and deck!!" So the unit is to
**absorb the calendar in date fixed effects** and identify from the within-day
cross-section, with preliminary/E0 estimates admissible at stated scope and
uncertainty, written into the paper and deck as each lands.

Read the queue item itself, not this summary. Three things about it that a worker
must not rediscover the hard way:

- **A first batch already exists and works. Extend it, do not redo it.** Scripts and
  outputs live outside the worktree at `~/.local/share/glotl/dvc-supervisor/`
  (`dvc_datefe_ladder.py`, `dvc_datefe_contrasts.py`, and their `.jsonl`), on
  `data/processed/vehicle_excess_use_daily.parquet` restricted to
  `endpoint_supported` token-days with more than 20 route units.
- **`pyfixest` is not installed and must not be added.** The owner is the repo's own
  `ddvc.analysis.regression` (`absorb_fixed_effects`, `ols_clustered`, two-way CR1
  on date and token). That also explains the three standing
  `tests/test_vehicle_role_models.py` failures.
- **There is a blocking caveat before anything ships.** Intermediary share and
  endpoint share come from the same day's route universe and a token cannot
  intermediate a route it is an endpoint of, so a mechanical crowd-out channel
  exists. `scripts/run_dominance_mechanicalness_screen.py` must be run against the
  specification and reported beside the estimates; if it cannot clear the design,
  the result ships as a descriptive association and says so.

Every figure in the queue text must be re-derived from the panel before it enters
prose. The queue explicitly warns against binding a number from it, and the
2026-08-16 pass already caught queue count figures that did not reproduce.

## 2026-08-16 — within-day identification of the vehicle role (queue 15:55Z, parts 1/3/5)

**Targeted:** the unchecked 2026-08-16T15:55Z Java interjection, which outranks the
gate. Not a freeze blocker: the gate's four blockers were unchanged before and after.

**REGRESSION-CHECK (written before mutation).** Estimand at risk: the vehicle
excess-use construct at the token-day unit on the `endpoint_supported` perimeter —
recorded in the paper as a *re-specification*, not a redefinition, and the ratio
exhibits remain the primary extent measure. Evidence generation at risk:
`data/processed/vehicle_excess_use_daily.parquet`, read-only, not rebuilt. Prior
corrections at risk: "calendar time is not treatment" (calendar is a control in the
ladder and a sample split in two rows, never the identifying variation, and the role
is recorded per row in `calendar_role`); the "not X, but Y" owner rule (every
non-separable contrast is reported with its interval and neither side is asserted
from a bare p-value); "do not resurrect a retired estimator" (new owner built under
the live `ddvc.analysis.regression`, not the withdrawn specification-curve frame).

**Did.** Built `scripts/run_excess_use_date_fe_ladder.py` as the owner of the
within-day design: four-rung ladder, slope-by-class interaction with contrasts,
candidate and classified sample cuts, backing-regime and USDC/USDT cuts, calendar
halves, and three mechanicalness screens. Bound it through
`scripts/build_excess_use_date_fe_deck_values.py`, rendered
`output/tables/within_day_ladder.tex` and
`output/figures/within_day_role_contrasts.pdf`, wrote paper section 3.5 (Table 5,
Figure 5) and one deck frame in `04-results`.

**Commit:** `d9ce616` (queue note and this entry follow).

**Blocking count: 4** (unchanged): node E1 specification lock; empirical model
ledger; node B full-text literature ledger; two unchanged findings passes.

**DECISION: promote** — the within-day conditional cross-section ships as an
estimate rather than a descriptive association. Licence: all three screens clear.
The crowd-out ceiling binds almost nowhere (mean utilisation 0.0008, p99 0.0004,
0.08% of currency-days above half the ceiling) and can only push the slope down;
leave-own-out denominators *raise* the slope to 3.209 (SE 0.090); the route-unit
floor moves it from 1.579 at five to 1.595 at one hundred. The route-cost dominance
screen (`scripts/run_dominance_mechanicalness_screen.py`) could not carry this
design — it reads `route_cost_panel_v2` through `pyfixest`, which is not installed —
so the screen concept is instantiated for the share-on-share specification inside
the new owner and documented there.

**DECISION: narrow** — samples with fewer than thirty currencies cluster on date
with a thirty-day Bartlett lag instead of two-way CR1 on date and currency. Two-way
CR1 takes its reference distribution from the smaller dimension, so a five-currency
cut would report four degrees of freedom and a two-currency cut one. The repeated
sampling unit in those cuts is the day, and the live dependence is serial.

**Two figures in the queue text did not reproduce and are superseded.** The queue
warned about exactly this and it paid off.
- The supervisor's saved restricted-sample specifications return **NaN**, not the
  quoted coefficients: with `other` empty, a full set of class dummies is collinear
  with the absorbed date effect. Every sample here declares and drops a base class.
- The five-candidate contrast is **-17.45 pp (SE 7.63, p 0.022, [-32.41, -2.49])**,
  not SE 3.15 / p 3.4e-08 / [-23.6, -11.3]. The 37-currency contrast is
  **-1.51 pp (SE 1.27, [-4.09, +1.06]) and does NOT separate from zero**, against
  the queue's SE 0.076. Both differences are the clustering correction above.
  So the "native intermediates less than a stablecoin conditional on demand" claim
  rests on the candidate set only, and the paper says so in those words.

**What reproduced exactly:** ladder rungs L1--L5 and the calendar halves, to the
digit. Absorbing 2,259 day effects moves the native premium +34.564 -> +34.551 pp.

**New results not in the queue text.** Inside the stablecoin class, within day and
at the same demand, against a fiat-reserve claim: on-chain-collateralised
-0.77 pp [-1.35, -0.20], synthetic -0.61 pp [-1.11, -0.11], non-USD
-0.62 pp [-1.19, -0.04], RWA-mixed -0.50 pp [-1.14, +0.14] (not separable),
time-varying -0.29 pp (not separable). USDT is -5.32 pp [-7.14, -3.51] against
USDC. The class that gains the role over the sample is not homogeneous in it.

**One coefficient demoted.** The route-weighted native intercept is -15.91 pp
against +0.05 pp unweighted, so its sign depends on whether a currency-day or a
route is the unit. Paper and figure carry it as descriptive.

**Calendar role per result** (as the interjection requires): control in L2--L6 and
in every sample and regime cut; sample split in the two calendar-half rows;
identifying variation in none of them.

**Collateral gates this touched, so the next iteration does not rediscover them.**
- Section 3 forbids an inline `tabular`; a table must be a rendered artifact under
  `output/tables/` with a lineage row in `scripts/tabulate/README.md`, and
  `tests/test_paper_tables.py` hard-codes the manuscript label count (now 12).
- `scripts/tabulate/` scripts must be direct runners: no `if __name__` guard.
- A LaTeX macro name may not contain a digit. `\DateFECeilingP99` parsed as a macro
  plus a literal `99` and typeset it in the preamble.
- Adding ~750 words without an exhibit pushed `tests/test_venue_optics.py` below the
  first-quartile figure and citation densities. Fixed substantively, with the
  contrasts figure and two citations the section wanted anyway, then
  `scripts/measure_venue_optics.py` rerun. Equations remain 15 against p25 25.
- `check_deliverable_conformance.py` requires the raw-passage review in
  `docs/reviews/paper-rhetoric.json` to be refreshed for any changed section: a new
  `openings` entry, one handoff record per new paragraph, shifted line anchors for
  the paragraphs that moved, and the section sha256 restamped.

**Test state.** Full suite: 13 failures, all pre-existing and unrelated
(`test_weighted_quote` wiring, `v2_event_source_release` provenance,
`test_vehicle_role_models` needing pyfixest, `.read_csv` in
`run_stress_reallocation_e0.py`). Three collection-error modules are excluded the
same way as before: `test_route_cost_panel`, `test_route_state`,
`test_analysis_release`. No new failures. Paper 45 pages 0 undefined, deck 37 pages
0 undefined, deck evidence audit PASS, conformance blocking checks all pass.

**For the next iteration.**
- The 15:55Z queue item stays unchecked with a progress note. Its remaining parts
  are **2** — add a date-FE rung to every existing headline estimator, keeping the
  existing estimate and reporting which coefficients survive absorption — and **4**,
  pair-level and venue-integration interactions on the same design. Part 2 is the
  higher-value of the two and is mechanical: the owners are
  `scripts/build_intermediation_by_type.py`, `build_vehicle_excess_use.py` and
  `run_dominance_regressions.py`.
- `output/figures/within_day_role_contrasts.pdf` is a stronger deck object than the
  ladder table, because it shows the non-separable rows at the same weight. It is
  not yet on a deck frame; the deck-density interjection above caps the core deck,
  so it should replace rather than join a frame.
- The deck-density interjection's real deliverable — a word-budget check inside
  `audit_deck_evidence.py` — is still unbuilt. The new frame was hand-counted at 40
  visible words against the 55 budget.

## 2026-08-16 — node B literature ledger, and the two-unchanged-passes gate

**Targeted:** two queue items, both older than the 15:55Z interjection and both
closable in one iteration: the Mukhin owner decision (queue line 146) and the
`stable_passes` replacement (queue line 73). Commits `67908dd` and `8f4bbee`.
Blocking count **4 -> 3**: `node E1 specification lock`, `empirical model
ledger`, `two unchanged findings passes`.

**REGRESSION-CHECK recorded before mutation.** Neither unit touches an
estimator, panel or coefficient, so no purpose-bound estimand changes. Evidence
generations at risk were `literature/pdf-sources.json` (must not drop the saved
article/appendix records) and `docs/specification-lock.json` (the fingerprint
must read the claim registry, never write it). Prior corrections at risk: "a
certificate or provenance mismatch is not itself scientific evidence", and
"never fake a gate".

**Mukhin (closed).** The block was one non-text companion, not a text gap. The
premise was verified rather than assumed: article PDF and the official 37-page
appendix are both in the shared corpus (which `literature_papers_dir` resolves
to the primary checkout, 109 files); the 119,236,817-byte reconstructed archive
is in none of the three sibling checkouts, absent from a size-filtered search of
the projects tree and the glotl share, and unrecoverable from git because the
corpus was never tracked. Disposition is now `unavailable` with the sought bytes
and sha256 kept, plus the no-citation rule. Source-sets 32/33 -> 33/33,
five-axis cards 34/35 -> 35/35, check PASS, no other check moved.

**Gotcha that cost a cycle.** Backticks inside a card's `Companions:` field are
parsed as companion bibliography keys by `companion_source_keys`. A backticked
sha256 and a backticked file path silently broke the card even though the source
set had already closed. Keep backticks in that field for bibliography keys only.

**Findings fingerprint (closed).** `ddvc.model_registry.findings_registry_state`
is the single definition: sorted claim ids with statuses, plus sorted retired
families with the claim each served. The retirement unit is the family, not the
claim, because one claim can be served by several batteries.
`scripts/record_findings_pass.py` is the only writer, appends to
`logs/findings-fingerprints.jsonl`, and refuses a second row at the same commit.
`.gitignore` now un-ignores that ledger. The audit requires the last two rows to
be distinct passes at distinct commits, agree, and still match the live
registries, and fails closed if `stable_passes` reappears in the frontmatter.

**The ledger is deliberately empty of rows, and the next iteration should think
before filling it.** A row means "every claim in `docs/specification-lock.json`
was reviewed against its current evidence in this pass". This iteration did not
do that review, so recording one would have been a faked gate in slow motion.
Two genuine passes, at two different commits, are what turns this check green.

**E1 lock (queue line 45) scoped and left open, with a progress note in the
queue.** It cannot be built in the order the item states.
`execute_exploration_plan` requires the plan's family perimeter to equal
`docs/e0-exploration-plan.template.json` exactly (`src/ddvc/exploration.py:433`),
and that template is out of sync with the lock in both directions. It names five
families, three serving claims outside the executable perimeter —
`claim_execution_perimeter` returns only `vehicle_transition` and
`liquidity_capital_v2_predictability` — while
`liquidity_capital_v2_predictability` has no family at all and
`open_question_anomaly_e0` names a claim id absent from the lock. Two of the
five also need V2/V3 exact-state inputs the freeze still records as blocked. The
chain's real first step is therefore the step-2/step-3 adjudication applied to
the whole template, not to `liquidity_rent_incidence` alone: decide what the
confirmatory set contains, land the reconciled template with its citations, then
write `scripts/lock_specification.py`. `empirical model ledger` is a descendant
of the same chain (`exploration=not_started; current_runs=0`), so both remaining
non-pass blockers close together or not at all.

**DECISION: park** the 15:55Z interjection's parts 2 and 4 for one iteration.
Part 2 ("date-FE rung on every existing headline estimator") was scoped and is
narrower than it reads. `run_dominance_regressions.py` belongs to
`retired_native_cost_advantage_battery` and may not be resurrected;
`build_intermediation_by_type.py` estimates year-endpoint changes on a daily
panel where the unit *is* the day, so a date FE is saturated and undefined; and
`run_vehicle_rotation_composition_e0.py` already carries pair x month-day x
scope FE, which is most of part 4's pair-level half. The one live headline
estimator with a well-defined and genuinely missing date-FE rung is the venue
-integration contrast in section 3.6: `intermediation_integration_rival.jsonl`
and `..._interaction.jsonl` identify the cross- versus single-venue stable-share
gap from two-year endpoint windows with HAC, so calendar is the identifying
variation there. Stacking (date, scope) on
`data/processed/intermediation_by_type_daily.parquet` and absorbing the date
turns it into a within-day paired difference over the full 2,332-day calendar,
with the scope x calendar-half interaction as the robustness split. That is one
new estimator owner reading a green panel, it closes part 2 and part 4's
venue-integration half together, and it is the right unit for the next
iteration.

**Test state.** `tests/test_findings_fingerprint.py` 11 passed.
`test_audit_findings_freeze.py`, `test_exploration.py`,
`test_literature_text_cache.py`, `test_project_runner.py`: 101 passed, 11
subtests, 1 failure —
`test_optional_artifact_gates_follow_only_executable_claim_inputs`, confirmed
pre-existing by re-running it with this iteration's changes stashed. The full
freeze audit takes 15-20 minutes when anything else is competing for the box;
do not run it alongside a broad pytest collection.

**Late addition, same iteration (`d09b1d0`): two inherited conformance blockers
closed.** `check_deliverable_conformance.py` was red on arrival and it was not
this iteration's doing —
`git diff f10a4c8 HEAD -- paper/ docs/reviews/ output/ deck/` was empty before
the fix. (1) The within-day figure added in `d9ce616` pushed Section 3's last
three paragraphs from 396/398/400 to 409/411/413 without shifting the anchors in
`docs/reviews/paper-rhetoric.json`, so three handoff lines were invalid. (2)
`against` as a preposition ran at 1.894 per 1,000 words against a corpus maximum
of 1.715, driven by the repeated `A against B by count and C against D by value`
template in the pair-decomposition paragraphs. Fixed by rewriting those thoughts,
not by swapping the word: the rising and falling pairs became the subjects of
their own clause, the entry margin states the cross-exchange figure as twice the
single-exchange one, the cohort comparison names each population and gives it its
own pair of numbers, and the decomposition now subtracts departing corridors
rather than netting against them. All macros and numbers unchanged; section
sha256 restamped. Conformance now green on every blocking check: paper 46 pages
0 undefined, deck 37 pages 0 undefined, deck evidence audit PASS. Two advisories
and the equations-below-p25 note stand.

**Standing warning for the next iteration.** Run
`scripts/check_deliverable_conformance.py` at the START of the iteration as well
as the end. Both of these were introduced by an iteration whose own final run
apparently predated its last edit, and they sat red across a handoff.

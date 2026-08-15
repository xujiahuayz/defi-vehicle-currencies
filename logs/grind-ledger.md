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

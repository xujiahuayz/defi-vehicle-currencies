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

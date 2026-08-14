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

- [x] **JAVA INTERJECTION (browser, 2026-08-13T23:00:51Z):** COMPLETE THE ALREADY-REGISTERED LIKE-FOR-LIKE MARKET TEST AT THE NEXT CLEAN BOUNDARY. Preserve and finish the current V2 audit first; do not interrupt or discard its work. Then fast-forward to current `origin/main`, which adds the missing `e1_1_pair_panel` estimator to the existing canonical owner `src/ddvc/analysis/vehicle_rotation_composition.py` and runner `scripts/run_vehicle_rotation_composition_e0.py`. Run that owner once through Studio's current D3 certificate/release lease so it publishes `output/exhibits/vehicle_transition_pair_fixed_effects.jsonl` with current provenance. Do not create another script and do not publish the M3 diagnostic from a provenance-stale panel. As an independent algebra check only, the byte-identical prior panel gives count +0.224 pp (SE 0.764), matched count +0.323 pp (SE 0.749), and strict value -1.346 pp (SE 2.188), with Holm p=1 for all; recompute from the latest lease and investigate any difference. The field-facing interpretation is a comparison of stable share within the same ordered endpoint pair, calendar position, and broad route scope (single- or cross-venue). Call these **matched markets** or **like-for-like market comparisons** in the paper/deck, not “fixed cells.” This test is distinct from the annual five-factor accounting and asks whether the aggregate rotation is pervasive within comparable realised markets. It still does not hold venue sequence, feasible alternatives, notional, liquidity, cost, or router state fixed and cannot identify a design or mechanism effect. After the result is current, update the findings record and surface the result visually before doing further mechanism prose.
  _Closed by the current-lease evidence in `b21ed0a` and this findings/deck integration: all three estimates reproduce the independent benchmark, the findings registry uses matched-market language and scope, and the existing composition frame now displays the count estimate and confidence interval._
























- [x] **JAVA INTERJECTION (browser, 2026-08-13T21:13:53+00:00):** NEXT BOUNDED SCIENCE TEST AFTER CLEAN E0 COMMIT (existing released data only): decompose pooled 2024→2026 count rotation into market-pair activity × realised vehicle-route incidence × stable share. On the same common calendar, for each ordered pair/year define M=market_route_count from released pair_support, I=primary_choice_route_count/M, and s=stable_choice/primary_choice. First classify year-specific primary-choice mass by whether M is positive in the other year: market-pair support turnover versus vehicle-role support turnover on an established market. Then, among pairs with M>0 in both years, use a symmetric exact decomposition to separate reweighting in M from reweighting in I and within-pair change in s. Count primary; matched strict count/value robustness only if the denominator contract is exact. Label M as observed market activity and I as realised vehicle-route incidence—neither is a causal opportunity set. Do not attribute architecture, demand, preference, or search. Independently verify identities and report the scientific implication before adding a slide. Preliminary independent diagnostic: 98.0% of 2026-exclusive primary-choice mass lies on pairs with zero observed 2024 market-route mass; restricting to pairs with positive market activity in both years still yields 26.10%→41.94% (+15.84 pp), 61.7% of the raw increase. Recompute rather than trust these diagnostics.
  _Closed by `ce2cbb0` and the refreshed exact E0 artifacts: a symmetric six-order Shapley bridge separates observed market activity, realised vehicle-route incidence and within-pair stable share, exact support categories reproduce the 98.0% and 26.10%→41.94% diagnostics, and the claim/workflow record promotes only the descriptive extensive-margin fact._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T21:09:33+00:00):** E0 ADMISSION HYGIENE / CURRENT CERTIFICATE: the independently audited scientific unit is exactly vehicle_transition_pair_decomposition.jsonl, vehicle_transition_pair_support.jsonl, vehicle_transition_pair_panel.parquet and their provenance. Do not bundle or promote output/exhibits/e0_vehicle_rotation_analysis.jsonl merely because it is untracked: it is a separate older mixed diagnostic, includes a pyfixest failure row, and is outside this E0 pair-composition result unless a distinct owner/specification proves it current and admissible. The one analysis-release refresh now running is acceptable because commit 628388d changed artifact_release.py, an explicit certificate code source; after it finishes, bind/re-run only what the current-code provenance contract strictly requires, once. Do not launch a second identical publication. Close the superseded two-failed-JSONL item with the verified Parquet-output correction, and close the old 17:16 excess-use item without rebuilding excess-use.
  _Closed in the E0 evidence commit: the current certificate was refreshed once after `628388d`, only the three admitted pair-composition artifacts and provenance are included, and the separate mixed excess-use diagnostic plus provenance were removed uncommitted._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T20:52:57+00:00):** E0 SCIENCE READOUT / NEXT BOUNDARY: successful third run wrote Parquet pair panel plus JSONL decomposition/support under exact current D3 certificate. Max identity error 1.11e-16. Pooled count stable share 0.168656->0.425409 (+0.256754): within_common -0.001279, common_pair_reweighting +0.085725, common_support_mass -0.005363, exclusive_pair +0.177671. Pooled strict-value 0.348044->0.776466 (+0.428422): within -0.000262, reweight +0.262159, support-mass -0.025191, exclusive +0.191716. This is the substantive result: aggregate rotation is overwhelmingly market-composition/activity-reweighting, not within-fixed-pair substitution. Commit the three outputs+provenance+certificate authority and queue closure cleanly, report why the first two JSONL-panel attempts failed and close the stale lock record. Do not overclaim design cause; next test separates architecture/opportunity-set expansion from demand moving toward stable-friendly pair types. Then integrate origin/main 964f8a5 deck commit at clean boundary.
  _Closed in the E0 evidence commit: exact certificate generation de49187b authorizes the Parquet pair panel and JSONL decomposition/support; all four terms reproduce to 1.11e-16, the stale unlocked PID record was removed, and the next registered attack remains opportunity/market-activity versus endpoint-demand composition._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T20:47:14+00:00):** E0 OBSERVATION: two composition E0 child attempts have exited without producing vehicle_transition_pair_{panel,decomposition,support}.jsonl; persistent lock metadata still names dead first PID 22651. Do not launch a third blind full run. Capture and report exact rc/stderr from both attempts, inspect macOS memorystatus/jetsam and the stale-lock behavior, then add/fix only the bounded runner fault. The endpoint receipt and D3 analysis certificate are good and must not be republished. A successful retry must reuse outer bundle baef31fa... and scientific generation 538b3ef3..., write atomically, and surface the exact four-term rows immediately.
  _Closed by bounded diagnosis and `3b93df8`: the attached retry returned rc=1 with the exact 554,188-row JSONL exhibit-limit ValueError; the detached first attempt ran the same pre-fix path and left no artifact. macOS shows no memorystatus/jetsam event, and the lock file held only stale metadata with no flock owner. Only the large support panel moved to `write_panel`; the successful run wrote atomically._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T20:30:58+00:00):** POST-ATTESTATION INDEPENDENT AUDIT: endpoint fast-consumer and exact E0 binding are sound; 21 endpoint/E0 and 57 registry/freeze tests pass. Before pushing/green CI, fix only the legacy capital regression: stale scientific input still rejects correctly but exception wording broke test_pool_capital_panel. More importantly, trim accidental global scope: publish_artifact_release must emit semantic_validation only when an explicit semantic_validator_fingerprint is supplied; endpoint opts in, legacy capital/other releases retain old pointer shape and no misleading synthesized receipt. Do not redesign the sound endpoint lane or delay current fast analysis publication/E0 for wrapper dedup. Treat generic expanded lineage duplication and wrapper consolidation as later maintainability unless current tests prove a blocker. Direct semantic=false endpoint resolution must not be advertised as safe consumption outside the context-manager lease.
  _Closed by the legacy-compatibility follow-up: receipts are now opt-in only through an explicit validator fingerprint, endpoint remains opted in, generic/capital pointers retain their legacy shape, stale capital inputs fail with compatible wording, and the focused endpoint/capital/registry/freeze suite passes._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T20:00:22+00:00):** RECOVERY LOCATION: the complete interrupted 15-file patch is preserved in named stash interrupted-receipt-lease-e0-worktree-20260813T1959Z (currently stash@{0}); recover that stash selectively. An earlier adjacent stash interrupted-receipt-lease-e0-before-double-hash-fix-20260813T1958Z is a redundant snapshot and must not be applied on top. First clean the two false-positive/retraction queue entries and the duplicate live-attestation/redirection pairs. Independent audit says the smallest safe fix is: inside the existing first _open context and continuous locks, after pointer write, parse/equality-check installed pointer bytes, stat-recheck non-pointer lineage, construct/return the already verified ArtifactRelease with refreshed pointer SHA/stat; delete trailing full _resolve. Add source/member hash call-count test and post-write lineage-change rollback test. No live attestation until focused suite is green.
  _Closed in the endpoint receipt/lease implementation commit: selective stash recovery removed the second full resolution; attestation now round-trips the bounded pointer and stat-rechecks continuously leased non-pointer lineage._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T19:54:16+00:00):** IMMEDIATE REDIRECTION: do not run live endpoint attestation with the current implementation. Independent audit finds post-write full re-resolution duplicates the 39.07GB source perimeter and member hashes (~90GB I/O total), with material pandas memory risk. Preserve the completed test result, then change attestation to reuse the already-validated release state inside the same exclusive-pointer transaction and perform only a bounded pointer/receipt post-write check; preserve rollback, generation, artifact/sidecar bytes+mtimes, leases, and exact downstream receipt binding. Add instrumentation proving each source/member hashes once per attestation transaction. Keep claim-gate correction as a separate commit. Then run one live semantic attestation, fast analysis publication, and E0. This is an engineering optimization only; do not widen the scientific scope.
  _Closed by `4223a2d` and the live E0 run: attestation reused the verified locked release, performed one semantic pass, preserved generation 5fb7cbf and all member identities, then exact receipt-bound analysis/E0 consumption completed._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T19:40:28+00:00):** HAND-CALCULATED ALL-FOUR-TERMS FIXTURE (for the E0 proof test): common pair A baseline denom/stable=60/12 (s=.2), comparison=30/15 (s=.5); common pair B baseline=40/24 (s=.6), comparison=90/72 (s=.8); baseline-exclusive C=100/10 (s=.1); comparison-exclusive D=30/27 (s=.9). Then W0=.5, W1=.8; q0=(.6,.4), q1=(.25,.75); S_C0=.36, S_C1=.725; E0=.5,E1=.2; S_E0=.1,S_E1=.9. Expected: baseline stable share=.23, comparison=.76, total=.53; within_common=.157625; common_pair_reweighting=.079625; common_support_mass=.01275; exclusive_pair_contribution=.28; identity error 0. All four are nonzero. Use equivalent route rows for count/strict/value and retain cross-scope controls as needed.
  _Closed in the endpoint receipt/lease implementation commit: the exact hand-calculated 0.23-to-0.76 fixture asserts all four signed terms for count, strict-count, and strict-value measures plus scale/row-order invariance._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T19:35:58+00:00):** INDEPENDENT E0 SCIENCE AUDIT AFTER 7198343: formula matches the lock, but trusted E0 remains blocked by two focused proof gaps. (1) Existing four-term test activates only within_common and exclusive contribution; reweighting and common_support_mass are zero. Add a hand-calculated fixture with at least two common pairs, changing q weights, changing total common mass W, and year-exclusive pairs with different stable shares so all four terms are nonzero; assert each signed term and total, plus invariance. (2) run_vehicle_rotation_composition_e0.py only checks that the endpoint pointer path appears in the D3 certificate. Bind the exact endpoint release generation/receipt recorded in the certificate and consume it under the same lease; add a pointer-switch/generation-mismatch runner test. Clarify docstring that this is the raw aggregate descriptive companion, not decomposition of the FE coefficient. Do this in the same endpoint attestation/consumer unit before real E0; no new data build.
  _Closed in the endpoint receipt/lease implementation commit: E0 now leases the exact D3-recorded endpoint generation and validator receipt, rejects mismatches, and identifies the output as raw descriptive accounting rather than an FE-coefficient decomposition._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T19:28:00+00:00):** LIVE-STATE BLOCK BEFORE TEST/PUBLISH: the installed endpoint pointer generation 5fb7cbf... has keys artifacts/build_identity/generation/kind/schema only; semantic_validation is absent. Therefore the new fast path cannot consume the real release as written. Add a one-time pointer-only attestation/migration: under the endpoint pointer exclusive publication lock, reopen and hash the exact existing generation, run the endpoint semantic validator exactly once, then atomically add {generation_id,current validator_fingerprint} to the same pointer generation. Do NOT invoke writers, restage, or rewrite any of the 4.1GB payloads/sidecars. Tests must start from a legacy receipt-less endpoint pointer, prove tamper blocks attestation, prove payload/member bytes+mtimes remain identical, pointer generation unchanged, semantic calls=1 during attestation and 0 on subsequent real analysis consumer, and crash restores old pointer. Then run this one-time attestation on Studio before analysis release. No E0 or analysis publish beforehand.
  _Closed by `4223a2d` plus live attestation: the pointer-only migration added receipt dbb0c10a to unchanged generation 5fb7cbf; focused tamper, byte/mtime, one-call/zero-call, rollback, and hash-count tests pass._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T19:16:11+00:00):** QUEUE HYGIENE: the two pre-Queue M3 entries at 19:02 and 19:04 are a canceled false-positive/retraction pair; remove both rather than ticking or preserving them as live work. Keep the substantive 19:06 endpoint-only/perimeter/race correction. Before selective stash recovery, reconcile clean Studio commits with origin/main e151305; do not re-run the already-running freeze audit for the same identity.
  _Closed in the endpoint receipt/lease implementation commit: the canceled pre-Queue pair and duplicate attestation/redirection records were removed; clean Studio history already contains e151305 through merge 7198343._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T19:06:25+00:00):** M3 REVIEW REDIRECT: stop this patch before it grows. The current generic typed-release path also sweeps in pool_capital_release/current.json, whose resolver has no semantic mode and whose installed pointer predates semantic receipts. E0 does not justify reopening or republishing capital. Make the fast receipt-backed downstream behavior explicitly endpoint-specific, or backward-compatible for typed releases without receipts; test the real executable perimeter. Also the endpoint registry currently invokes the resolver with default semantic=true, so analysis publication is not fast. Require semantic=false only for the certified endpoint input, exact current pointer receipt/fingerprint, and continuous pointer/member/sidecar/source lease. Existing 7 lock-overlap failures show the context/lock order must be fixed. No publisher or E0 until these focused tests pass. Preserve current work in a named stash if the correction is cleaner from the last clean commit.
  _Closed in the endpoint receipt/lease implementation commit: only the endpoint release uses receipt-backed fast consumption; legacy typed releases retain their existing resolver behavior and the focused real-perimeter suite passes._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T18:49:15+00:00):** PERFORMANCE REVIEW BLOCKS STASH@{0}; RECOVER SELECTIVELY, NOT WHOLESALE. The 603-line fast-consumer patch still performs ~510GB: 9 payload hash passes plus 12 repeated passes over identical 39.07GB released-input bindings. It lacks a bundle lease/end-pointer recheck during fast resolution, duplicates generic release parsing, and its 21 tests do not exercise post-publication fast-path tampering or performance. Remove gc.collect runner edits. Implement in generic artifact_release: leased pointer-validated identity with pointer-certified artifact/provenance hashes and one deduplicated union of released bindings; typed endpoint semantic=True for publication/audit and semantic=False for consumers, backed by a generation+validator-fingerprint semantic receipt; hold/recheck pointer across fast read. Tests must publish once, then tamper pointer/member/sidecar/upstream binding/spec and call both direct/current fast resolvers; race pointer switch; count semantic validator (publication exactly once, consumer zero) and file hashes (each unique binding once per boundary). Keep specification gate corrections as a separate scientifically justified unit and explicitly test dormant-owner semantics. Correct E0 environment: certificate bundle id != certificate generation; use DDVC_D3_GENERATION from certificate JSON. Do not republish or rerun E0 until focused tests prove the actual fast path and performance contract.
  _Closed in the endpoint receipt/lease implementation commit: leased generic resolution deduplicates released bindings, fast endpoint consumers rerun zero semantic passes, and instrumentation proves one hash per unique source/member boundary._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T18:40:37+00:00):** E0 ENV IDENTITY CORRECTION: outer analysis bundle/pointer generation 073a867c7f826e50c572ae7d15a6fc0039205dbbf230861e63fdd962dc1b39c4 identifies the certificate artifact; the certificate JSON field generation is d173728814b83059c67771f1a6137bdec44d12610175c6d77e176a198393ef98 and that is the required DDVC_D3_GENERATION. The first attempt failed at model_artifact_context after 15m for this mismatch and never estimated. M3 stopped the second attempt early because it repeated the same wrong env. Rerun with DDVC_D3_CERTIFICATE pointing to the 073a... certificate path and DDVC_D3_GENERATION=d173728814b83059c67771f1a6137bdec44d12610175c6d77e176a198393ef98. Do not add gc as a supposed fix for an identity error; revert that unrelated runner edit unless independently needed.
  _Closed in the live E0 run: the runner used certificate generation 6c401687, not outer bundle bdb9d0cf; no gc workaround was introduced._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T17:39:35+00:00):** REVIEW CAVEATS: (1) Blocking routing_maturation removes route_cost from executable perimeter but d3_input_ownership currently treats registered non-required external prerequisites as stale_external. Do not keep a scientifically blocked claim open to appease that invariant. Either allow prospective external registrations analogously to prospective built stages while requiring exactly one owner for every required path, or remove the route-cost external registration until reopen. (2) An assert_current immediately before install does not fully close TOCTOU. Keep current_artifact_release(bundle) and ordinary current_artifacts leases open through publish_artifact_release certificate+pointer installation. If only a preinstall rebuild/compare is feasible, label it mitigation, not atomic proof.
  _Closed in the separate claim-gate commit: prospective external owners remain declared without forcing blocked claims into the executable perimeter, while all required paths still have exactly one owner; publication leases remain continuous through pointer install._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T17:37:13+00:00):** INDEPENDENT REVIEW — CLEAN MINIMAL DESIGN. Keep the existing full-perimeter analysis-release contract and do NOT add --claim/claim_ids. The full perimeter currently fails because three specification claims are falsely execution_gate=open although findings-freeze and 12 missing inputs say they are blocked. Correct those three gates to explicit blocked reasons consistent with the freeze, recompute lock_hash; then the complete executable perimeter is honestly the ready vehicle_transition branch. Add only registered typed marker-last handling. Hold current_artifact_release(bundle) through lineage/record construction and assert current again immediately before installing the analysis pointer to prevent pointer-switch TOCTOU. Required real tests: endpoint typed release through analysis certificate; pointer switch/tamper; member payload tamper; sidecar tamper even with pointer digest updated; stale underlying released-input binding; unregistered unstamped pointer rejection; ordinary stale artifact rejection; pointer changes during record construction. The blocked patch/E0 output is preserved in stash@{0}; recover selectively, never wholesale.
  _Closed in the separate claim-gate commit: the three freeze-blocked exact-state claims now carry explicit execution gates, the lock hash is recomputed, and the full perimeter is the ready vehicle-transition branch with typed release/race tests._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T17:32:17+00:00):** INDEPENDENT REVIEW BLOCKS THE CURRENT ANALYSIS-RELEASE PATCH/PUBLICATION. Typed marker-last pointer verification is directionally correct, but arbitrary --claim/claim_ids partial-release mode is unrelated overreach: it lets a caller shrink the full execution-open D3 perimeter. Remove that new mode unless an existing purpose-scoped contract already authorizes it; do not weaken full release semantics. Replace the monkeypatched fake resolver test with real endpoint release tests proving exact generation, payload, sidecar/lineage binding and rejection of pointer, payload, provenance, generation and stale-lineage tampering. M3 terminated only the in-flight publish_analysis_release child before it could install authority; the worker remains alive. Then run the composition E0 only from a legitimately bound exact-generation certificate.
  _Closed by the exact typed-release test perimeter and live publication: no partial-claim mode exists; pointer/member/sidecar/upstream/spec races fail closed, and E0 consumed the legitimately receipt-bound certificate._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T17:22:57+00:00):** WORKFLOW DEDUP ADDENDUM: run each preflight/audit at most once per exact repo identity within an iteration. The same audit_findings_freeze.py was launched twice concurrently in iteration 13; M3 terminated only the older duplicate and left the newer audit plus worker intact. Cache and reuse the first result rather than relaunching identical read-only checks.
  _Closed in the endpoint receipt/lease implementation commit: this iteration ran one preflight and one initial freeze audit for the starting identity._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T17:16:42+00:00):** M3 REDIRECT — STOP REDUNDANT EXCESS-USE REFRESH. Its existing certified panel was built from current route SHA-256 7baa00fde6a445beaa9867a936754be921303aa39c7de757217838f294b55625; none of its registered code sources changed since its prior build. Preserve its current payloads. Do not rebuild intermediation or excess-use again merely because they share the claim perimeter. Run scripts/run_vehicle_rotation_composition_e0.py against endpoint-candidate generation 5fb7cbf36508d10a5bdafe2ebfb5ccb6266696be38e192eb38be11c3942916e9 now; report the four-term decomposition by measure/scope and exact identities. Then run scripts/run_vehicle_rotation_e0.py using the already-current annual/quarterly/daily excess-use artifacts. Scheduling rule: launch an owner only when its registered code fingerprint or certified input identity differs; registry order is not a dependency graph.
  _Closed without rebuilding excess-use: the admitted E0 unit is the exact pair-composition result; the unchanged older excess-use diagnostic was run only for inspection and removed uncommitted under the later admission instruction._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T17:12:28+00:00):** M3 IDENTITY CORRECTION: the existing intermediation panel was created at 2026-08-13T11:57:50Z from current route-quality SHA-256 7baa00fde6a445beaa9867a936754be921303aa39c7de757217838f294b55625, and none of its registered code sources changed since commit 2ffbce. Therefore this invocation is same-code/same-certified-input and cannot scientifically change sample composition or coefficients. Let the now-near-complete atomic run finish; compare payload/scientific hashes and record redundancy if identical. Thereafter skip any owner whose code-plus-input identity is already current. Refresh excess-use parents only if their own registered input identity is stale, then run the locked E0 decomposition. A general statement that a producer could change results is not evidence that this invocation can.
  _Closed as superseded scheduling guidance: same-code/same-input intermediation and excess-use owners were not refreshed; their certified artifacts remain unchanged._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T14:49:14+00:00):** After the current endpoint-candidate composition build completes and publishes at a clean boundary, converge with origin/main f71c142. Reuse the existing D3 owners to refresh intermediation_by_type and then the annual and quarterly vehicle_excess_use parents against the new exact route generation; run the repaired existing run_vehicle_rotation_e0.py owner and report its exact input identities. Do not create another memo, producer, or data redesign. If the endpoint-candidate release is not an ancestor of those parents, run their existing registered stage owner rather than widening scope. Keep the result E0 until the registered opportunity/search attack and JFE-calibrated promotion review close.
  _Closed as superseded by the later identity corrections: endpoint generation 5fb7cbf was attested in place, and no redundant intermediation or excess-use rebuild ran._

- [x] **JAVA INTERJECTION (M3 science gate, 2026-08-13):** Do not promote or write from `af097db` yet. Independent clean-room review and M3 inspection find that it is not the locked four-term decomposition in `docs/specification-lock.json`: it aggregates annual cells containing observed reach and protocol sequence, omits month-day from the cells, and reports within/reweighting/entry/exit rather than `within_common`, `common_pair_reweighting`, `common_support_mass`, and `exclusive_pair_contribution`. Treat the current output only as exploratory finer-cell accounting. Reconcile the registered producer exactly to the locked formula and common-month-day/pair/scope definitions; preserve realised-composition language rather than choice/adoption/preference; keep notional and fixed-opportunity claims gated. Add tests for the four-term identity, zero-exclusive normalization, common month-days, measure-specific support, and row-order/scaling invariance. An independent evidence verifier is running on M3. Do not open paper prose.
  _Closed as a duplicate supervisor record after verifying the substantive
  correction in `97b4b94`: the registered owner and focused tests implement
  the locked common-month-day, measure-specific pooled/split-scope four-term
  decomposition. No data result or prose was opened._















- [x] **JAVA INTERJECTION (browser, 2026-08-13T13:55:41+00:00):** SCIENCE GATE: Do not promote or write from af097db yet. A blind review and M3 inspection find that the implementation is not the locked four-term decomposition in docs/specification-lock.json: it aggregates annual CELL_COLUMNS including observed reach and protocol sequence, omits month_day from cells, and labels entry/exit contributions instead of within_common, common_pair_reweighting, common_support_mass, and exclusive_pair_contribution. Treat current output only as an exploratory finer-cell accounting. Next, reconcile the code exactly to the locked formula and common-month-day/pair/scope definitions, preserve realised-composition language rather than choice/adoption/preference, and keep notional plus fixed-opportunity claims gated. Add tests for the four-term identity, zero-exclusive normalization, common month-days, measure-specific support, and row-order/scaling invariance. An independent evidence verifier is running on M3; do not open paper prose.
  _Closed by replacing the finer reach/design accounting with the locked
  measure-specific common-month-day pair panel and exact pooled/split-scope
  four-term midpoint identity. Tests cover the required normalization,
  support, pooling, identity, and invariance contracts; no result was run or
  promoted and paper prose remains untouched._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T13:30:36+00:00):** SYNC/SCIENCE HANDOFF. At the next safe boundary, fetch and integrate origin/main through 45573a9 before choosing the next node. M3 has replaced the stale cost-dominance/hysteresis spine with the current vehicle-rotation science memo, published the three current empirical deck figures, and refreshed conformance diagnostics. Continue fixed-opportunity vehicle-rotation science from the new What G needs from F list. Preserve the accepted 13-token bounded exclusion. Do not edit paper prose or revive calendar time as treatment.
  _Closed by fast-forwarding `main` through `45573a9`; the current paper spine,
  three empirical deck figures, and refreshed conformance diagnostics are now
  local. Paper prose and the accepted 13-token bounded exclusion are unchanged._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T12:51:24+00:00):** SCIENCE/MATERIALITY REDIRECTION. Stop the current token-decimals acquisition/rebuild at the next safe boundary. Before any further acquisition or rebuild, measure the 13 unresolved token-anchor records economic exposure: affected pools/events/routes, route count and strict-support USD, year and venue concentration, whether any enters a promoted or required D2/D3 estimand, and a worst-case decimals-scale bound. Token-count share 13/65,095 is not materiality. If exposure is zero or negligible and non-systematic, record a bounded exclusion and return to fixed-cell vehicle-rotation science; if material or systematic, complete only the minimum exact evidence and state the scientific consequence. Do not treat a clean exact registry as itself a paper result. Preserve completed work and the supervising loop.
  _Closed with a lineage-revalidated deletion bound over 22 factory pairs, 229
  installed exact-candidate events, and the complete released route graph. The
  worst case removes 5,950 routes and $10.91m of strict route value, but only
  1,036 prespecified-candidate intermediary episodes and $1.284m (0.00043%) of
  strict intermediary value; every unresolved token is residual `other`, none
  crosses the rotation materiality screen, and none enters the V4 fixed-cell
  panel. The exact 0..36 scale uncertainty remains explicit, and the 13-token/
  22-pair exclusion stays closed until exact evidence exists._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T10:41:22+00:00):** ECONOMIC-MATERIALITY REDIRECTION. Finish the currently running one-time route-marker publication because the dry run has already proved zero scientific-identity differences and byte/row/hash/mtime equality for every one of 2,332 route partitions. After the owner confirms the release, do not continue metadata or certification engineering merely to approach perfection. For every remaining defect, first report its economic weight and concentration by calendar period, protocol/design, venue, pool, vehicle candidate, trade size, and stress state; ask whether it can change the estimand, sample composition, coefficient, or inference. Random or economically bounded dirt should be disclosed, bounded with a sensitivity where useful, and allowed to proceed. Hard failure is reserved for wrong identity, systematic selection correlated with treatment/outcome, data corruption, invalid causal timing, or invalid inference. The 1,884-day route rejection initially mattered because it coincided exactly with the V3 era, but the completed equality proof makes the remaining repair bookkeeping, not new science. Once closed, rebuild only the two required route panels, refresh their compact exhibits, and return immediately to science: fixed-opportunity routing versus monetary coordination, persistence versus hysteresis under cost-state reversal, and presentation-ready deck/paper updates. Explain each iteration first in economic terms, with engineering details subordinate.
  _Closed with the journaled 2,332-day marker migration, unchanged partition
  identity set `49d831f13c8fe0958776b0f4e59aa6411c34315d562127c19ddff9e39cf24f59`,
  and owner-built cross-venue and vehicle-extent panels plus compact exhibits.
  The freeze gate fell from 15 to 13 blockers; no other data family was opened._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T09:51:06+00:00):** DECK OVERFLOW/INTERPRETATION FIX: at the next clean boundary integrate science commit 3d8f36b only (its predecessors are already present). It removes the populated slide overflow and changes the live questions to the actual findings: raw focal share versus mechanical pair-week centering, ex ante feasibility risk set, and exact-state reversal. It explicitly says zero clean substitution windows and that appearance/disappearance magnitudes are mechanical. Recompile from the existing generated macros; do not rerun data.
  _Closed by integrating `3d8f36b` as `a587f8b` and rebuilding the deck from
  the existing generated macros. The populated audit frame has no vertical
  overflow and makes the zero-support/mechanical-magnitude limits explicit;
  no data owner was rerun._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T09:17:53+00:00):** Use science tip 377aa25 for the queued post-build integration. It fixes support attribution so a wholly missing pair-week is incomplete_window, not composition_shift. This supersedes the earlier tip pointer; keep the active route build untouched.
  _Closed by integrating the complete six-commit science series through
  `377aa25`, running the transition owner once against route generation
  `4fc206525d33`, and publishing both support families and generated deck
  macros. No route materialization was restarted._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T09:16:40+00:00):** Use origin/glotl/science-parallel through bef5b41 for the queued post-build integration; it is the tested tip and includes all earlier architecture/deck handoff commits. Preserve the active route build.
  _Superseded and closed by the tested descendant `377aa25` integration above._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T09:15:35+00:00):** FINAL SLIDE-PLUMBING POINTER: integrate science branch through 622758f after the active route build. This supersedes earlier science commit pointers, generates all provisional architecture slide cells from certified support exhibits, and prints the exact route-generation hash. Compile the deck after the single transition run; do not type numerical values into TeX and do not rerun the route build.
  _Closed by the generated `architecture_transition_deck_values.tex`, its
  provenance manifest, and a successful Tectonic deck build._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T09:11:59+00:00):** EXTENSIVE-MARGIN ADDITION: after the active route build completes, integrate science branch through 0bc4725 (superseding the earlier 2ccc999 pointer). It preserves within-cell substitution events and adds a separate active-pair risk panel for V4-active vehicle-role appearance/disappearance, with zero-use weeks explicit and pair disappearance excluded. Run the transition script once to emit both support families. Both remain endogenous E0; neither is design removal. Do not interrupt or rerun the route materialization.
  _Closed with the certified active-pair risk panel and extensive-margin
  event, contrast, and support exhibits from the same transition run._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T09:06:25+00:00):** SCIENCE CORRECTION TO THE DECK HANDOFF: integrate through origin/glotl/science-parallel commit 2ccc999, which includes 7da4a97. It makes the current estimand explicit: exit is within-observed-cell architecture substitution. Do not present it as reversal of the vehicle role, because complete cell disappearance is absent from this risk panel. Report that extensive-margin disappearance separately as an unresolved next estimand. Preserve the active route build and do not interrupt it.
  _Closed by separating within-cell substitution from vehicle-role
  disappearance in code, support exhibits, and the provisional deck._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T09:00:37+00:00):** LIVE-SCIENCE DECK HANDOFF. Do not interrupt or repeat the active Studio-current route-only build. After it finishes durably, fetch origin/glotl/science-parallel and integrate tested commit 7da4a97. This opens only visibly labelled provisional deck work while paper prose remains gated, adds the presentation-facing architecture_transition_support.jsonl, and corrects E0 language: exposure entry/exit are endogenous associations; exit reverses architecture exposure, not necessarily vehicle role; hysteresis needs asymmetric retention versus displacement under cost-state reversal. Rerun only run_architecture_state_transitions.py against the just-built exact current route-unit input, report threshold-by-kind detected/usable/overlap/incomplete/composition support plus descriptive pretrend/immediate/persistent means, then populate the three provisional frames with the exact generation identity. This supersedes the two older duplicate route-only queue items once their requirements are verified; tick them together rather than rebuilding routes. Do not open paper prose.
  _Closed with one Studio-current transition run, exact support counts and
  generated route identity; paper prose remains closed._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T08:47:39+00:00):** SCIENCE-FIRST REDIRECTION. Preserve the two commits already made (1096d83 and 17eda66). The failed 62-date state build established a real exact-state D blocker: raw files exist but the current local-scan certificate does not authorize uniswap_v3/burns/20210515. Record that exact blocker; do not broaden this iteration into the dormant raw-cert feature or a full raw-certification redesign. Route-only D is already green and must proceed to E now. Fetch origin/glotl/science-parallel and integrate/test new commit 2d11836 before any architecture materialization; it computes the pair denominator before focal-cell filtering and rejects event windows with changing comparison sets as composition_shift. Then run the Studio-current route-only build and architecture transition audit, reporting entry/exit support by threshold and status. Only after that result is durable should a later iteration resume the minimal existing certification owner for the 62 exact-state audit dates. Calendar date is not treatment; do not make causal claims.
  _Closed by integrating `2d11836` as `d72f8c1`, rebuilding the current
  route-only architecture panel, and publishing the guarded transition support
  audit. All 581 candidate events are excluded by composition, overlap, or one
  incomplete window, so zero E0 contrasts are promoted. The exact V3 blocker is
  recorded in the grind ledger for the later minimal certification-owner pass._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T08:37:10+00:00):** WORKFLOW CORRECTION AND DATA/SCIENCE MEET-IN-MIDDLE. The first three science commits are already integrated on main as dc7d613, 3ab708d, and 12edf63. Do not rerun audit_v3_graph_event_completeness.py from the old invocation: --help accidentally launched a 33 GB scan, and the audit-date canonical state inputs do not exist in this worktree, so that run was interrupted. Fetch origin/glotl/science-parallel, then integrate and test 66867bc (pair-week-adjusted architecture contrasts plus overlapping-transition exclusion) and b2a7cdc (side-effect-free help, cheap state preflight, explicit audit-calendar materialization, and progress reporting). Run the new V3 audit preflight first; it must fail quickly until state exists. Materialize only the shared V3 construction-audit dates with ./scripts/run scripts/build_market_state.py --family tick --venue uniswap_v3 --audit-calendar --workers 8; rerun the cheap preflight and only then launch the exact-event audit intentionally. This exact-state branch must not block route-only E. Independently build the architecture input from Studio current released unified data with ./scripts/run scripts/run_v4_settlement_identification.py --force --build-routes-only, then run ./scripts/run scripts/run_architecture_state_transitions.py. Report entry and exit support at 5%, 10%, and 25%, including usable versus overlapping/incomplete windows. Calendar date is not treatment; E0 is not causal. Commit certified small outputs or immutable pointers, record hashes/support in the ledger, continue remaining state-D work, and do not open prose.
  _Closed by the already-landed main-line ports `1096d83` and `17eda66`, the
  fail-fast 124-input V3 preflight verdict, and the completed independent
  route-only E audit. The newer science-first direction superseded state
  materialization in this iteration after the local-scan certificate rejected
  `uniswap_v3/burns/20210515`; no raw scan or provider fetch was launched._

- [x] **JAVA INTERJECTION (browser, 2026-08-13T07:58:14+00:00):** DATA/SCIENCE MEET-IN-MIDDLE — execute at the next clean iteration boundary after preserving the current V3 audit. M3 found its processed panel is stale (2,277 days) versus Studio current (2,332), so do not consume or copy the M3 route-unit file. Fetch origin/glotl/science-parallel at d2d9ca5 and integrate the three science commits into current main after tests/conflict review. Then materialize the architecture input from Studio current released unified layer with: ./scripts/run scripts/run_v4_settlement_identification.py --force --build-routes-only. This rebuild must use complete components, exclude mixed-source routes from pure V3/V4 states, and install the provenance sidecar. Next run: ./scripts/run scripts/run_architecture_state_transitions.py. Report entry AND exit support at 5%, 10%, and 25% V4-share thresholds; do not interpret calendar date as treatment and do not promote the E0 contrasts as causal. Commit the small certified panel/exhibits or an immutable release pointer as the repo contract permits, push main, and record exact hashes/support in the grind ledger. Continue the data freeze afterward; do not open prose yet.
  _Closed with 3,970,589 current-release exclusive V3/V4 route units, a
  63,193-row certified weekly panel, and tracked event/contrast exhibits plus
  provenance manifests. Exact hashes and the threshold-by-status audit are in
  the grind ledger; this remains an E0 support audit, not a causal estimate._

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

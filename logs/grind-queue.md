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

- [ ] **OWNER RULE (Java, 2026-08-16): NO HUMAN DECLARATIONS. THE LOOP ADJUDICATES.**
  Standing, supersedes any earlier instruction that routes a scientific judgement
  call to Java. Java does not sign, declare, stamp or hand-type any gate field.
  The design intent is auto-pilot from the start.
  When a choice would otherwise be a human judgement call, resolve it in this
  order and record the resolution in the ledger under `DECISION:`:
  1. **Golden standard: existing JFE literature.** Adjudicate against the saved
     corpus (`docs/literature-audit.md`, `literature/use-contracts.json`, the
     venue exemplars in `docs/reviews/`). Cite the exact source key and the page,
     section or table that settles it. "Common practice" with no citation is not
     an adjudication.
  2. **Finishability.** Between two defensible options, take the one that lets
     the paper actually finish. A claim whose required data may never arrive is
     demoted, not waited on.
  3. **Conservative fallback.** If JFE practice is genuinely split, take the
     option that preserves the estimand and fails closed, and say so.
  `NEEDS-JAVA:` is retired as a blocking state. It survives ONLY for actions that
  are genuinely unsafe to take alone: deleting data, spending money, or anything
  outward-facing. Everything currently parked under it is now a `DECISION:` for
  the loop, including the standing
  `data/processed/counterfactual_dominance_clean.parquet` regeneration, which
  should simply be run via `scripts/build_counterfactual_dominance.py` so the
  dominance ladder restates under the current producer.
  This rule does NOT license faking a gate. It licenses the loop to *earn* a gate
  by a recorded, citable adjudication that a reader could check and disagree with.

- [ ] **Make the E1 specification lock self-stamping under the owner rule above.**
  E1 is currently blocked only because `locked_at` and the generation/certificate
  bindings were treated as needing a human. Under the owner rule they do not.
  Build `scripts/lock_specification.py` so the lock is earned by a script that can
  fail, never by a person typing a date. It must, in order:
  1. Re-validate the design seed exactly as `audit_findings_freeze.py` does
     (hash, claim ids, execution policy, semantic rules, horizons, transition
     design). Abort loudly on any failure; never write a field on a red seed.
  2. **Adjudicate the two open design choices against JFE literature and record
     the citations in the lock payload itself**, so the lock carries its own
     justification: (a) episode count as primary weighting with value secondary,
     versus value-weighting primary, for a share-of-use estimand; (b) whether
     `liquidity_rent_incidence` belongs in this paper's confirmatory set at all.
  3. Apply the finishability rule to claim 5: if the external intraday
     reference-price panel is not acquired and validated by the time the
     exploration run closes, demote `liquidity_rent_incidence` to `withheld` with
     the reason recorded, and let the paper finish without it. Never leave the
     lock waiting on data that may never arrive.
  4. Run the exploration harness, bind `exploration_generation` and
     `exploration_certificate` plus the D3 pair, rewrite each executable claim to
     its `registered_*` status with a validated registered plan, set
     `stage=confirmatory` and `analytical_choices_status=registered_after_exploration`,
     stamp `locked_at`, and recompute `lock_hash`.
  Acceptance: `audit_findings_freeze.py` reports the E1 check PASS with every
  field machine-issued; the lock payload names the adjudicating citations; and a
  deliberately corrupted seed still makes the script refuse. Closes blockers 1
  and 2 as one chain.

- [ ] **Replace the hand-declared `stable_passes` with a computed findings fingerprint.**
  Today `stable_passes` is a hand-typed YAML field on line 3 of
  `docs/findings-freeze.md`, read at `scripts/audit_findings_freeze.py:4402` and
  required to be >= 2. Nothing in the repository writes it, no per-pass snapshot
  of the claim registry exists to diff against, and the field sits inside the very
  document the gate audits. It is unreachable by design and Java will not declare
  it. Replace it:
  1. At the end of each F->G pass, compute a fingerprint of the claim registry:
     the sorted set of claim ids with their status, plus the retired set. Nothing
     else, so that evidence updates and prose edits do not disturb it.
  2. Append it with the pass identity and commit sha to a machine-written ledger
     (e.g. `logs/findings-fingerprints.jsonl`); never edit an existing row.
  3. The audit replaces the `stable_passes` read with: the last two fingerprints
     exist, come from distinct passes, and are identical. Delete the YAML field so
     it cannot be edited by hand at all.
  This is strictly stricter than today's check: it catches a silent status change
  a human read would skim past. It does not depend on the E1 lock, so land it in
  parallel rather than after. Acceptance: the check fails on a synthetic registry
  change and passes on two genuinely identical consecutive passes.

- [ ] **JAVA INTERJECTION (2026-08-16): THE LIVE DECK IS TOO BUSY TO PERFORM.**
  The always-ready deck is working as a document and failing as a talk. Measured
  now: 35 frames at a median of 124 visible words. The deck's own venue benchmark
  in `docs/deck-outline.md` is 40-55 words per page, so it is running at roughly
  2.3x its own standard, with the worst frames at 421-553 words
  (`04-results` f5, `01-identification` f4, `90-appendix` f8, `05-close` f2).
  Three defects, all of them fixable as standing rules rather than a one-off pass:
  1. **Density.** Enforce the existing benchmark mechanically. Core deck at most
     13 frames; at most 55 visible words per frame excluding exhibit internals and
     presenter notes, hard fail above 70; one empirical object per frame; at most
     three short bullets. Text that comes off a slide moves into Beamer `\note{}`
     presenter notes; it is not deleted. Add the word-budget check to
     `audit_deck_evidence.py` (or a sibling) so the always-ready loop cannot drift
     back into density on the next update. That check is the real deliverable.
  2. **Takeaway.** There is no single memorable line a listener can repeat the
     next day. Adjudicate three candidate spine sentences against the saved deck
     exemplars and pick one, then use the same sentence verbatim in exactly three
     places: the opening frame, the frame that shows the headline result, and the
     close.
     **OWNER RULE (Java, 2026-08-16), binding on paper and deck alike: a
     contrast-confirmation construction ("not X, but Y", "it is not A, it is B")
     is FORBIDDEN unless both sides are evidenced on the same frame or in the same
     sentence's own exhibit.** The negated side must be carried by an interval
     that excludes the economically relevant magnitude, stated as a bound, never
     by a bare non-significant p-value or the words "about zero"; absence of
     evidence is not the evidence of absence that this rhetorical form asserts.
     The affirmed side must carry its own estimate with uncertainty in the same
     units. If either side cannot be shown that way, drop the contrast and use a
     plain descriptive line. This rule fails closed: when in doubt, no contrast.
     The seed candidate below is offered ONLY as a test of that rule, to be beaten
     rather than accepted: *"A vehicle currency does not win trades, it wins
     corridors."* Its licence, if it is to survive, is
     `output/exhibits/vehicle_transition_pair_fixed_effects.jsonl`, which bounds
     the negated side rather than merely failing to reject it: within matched
     markets the 2024-to-2026 change is +0.22 pp with a 95% interval of
     [-1.28, +1.73] pp on count, +0.32 pp [-1.15, +1.80] pp on matched strict
     count, and -1.35 pp [-5.65, +2.96] pp on strict value, on 94,260 and 91,417
     fixed-effect cells and 362 calendar-date clusters. Against aggregate moves of
     roughly +25.7 pp count and +42.8 pp value, those intervals cap the within-
     market channel at well under a tenth of the total, which is a bound and not a
     null result. The affirmed side must appear beside it with its own numbers,
     read from `vehicle_transition_pair_decomposition.jsonl` and never from this
     queue text: use the exhibit's pooled reweighting and net exclusive-pair terms
     with their standard errors. If the frame cannot show both sides in the same
     units, the sentence does not ship.
  3. **TradFi analogy is missing from the slides.** The China-Brazil corridor
     analogy currently lives in the paper's introduction and conclusion only. It
     needs its own core frame before the close, mapping the corridor story onto
     the reweighting and exclusive-pair margins, with the cited source in the
     presenter note and no causal or geopolitical claim on the slide itself.
  Guardrails unchanged: descriptive interpretation, pair composition is never
  called entry/exit, one deck, refreshed in place, no fork, no new data runs.

- [ ] **OWNER DECISION (Java, 2026-08-16): close the Mukhin literature blocker by
  recording the replication package as unavailable.**
  Scope: `Mukhin2022InternationalPriceSystem` only. The missing artefact is the
  openICPSR replication package (119,236,817 bytes, `1e8e62e5…`), not the text:
  the article and the official 37-page online appendix are saved, read in full
  and carded. Java's instruction was that a working-paper version is acceptable
  if it closes the gate, and that if that is difficult the item should be left.
  A working paper cannot supply a replication package, so the fallback applies.
  Do this: record the package's disposition as unavailable in
  `literature/pdf-sources.json` and in the card in `docs/literature-audit.md`,
  stating (a) the exact byte count and hash sought, (b) the checks that failed to
  locate it, (c) that the article and appendix remain fully read, and (d) that no
  claim may cite the package's contents or any reproduction run from it.
  Do NOT downgrade the card's `Status: claim-verified` — that status rests on the
  text, which is complete.
  Acceptance: the literature source-set check passes at 33/33, the freeze gate's
  blocking count drops by exactly one, and no other card or check changes state.

- [x] **JAVA INTERJECTION (iMessage via glotl, 2026-08-16T00:03:30+00:00):** SO-WHAT / ANALOGY PASS ON PAPER AND DECK — prose and deck only, no new data runs; take it at the next clean boundary without interrupting the current unit. Java finds both deliverables still too literally data-focused. Three instructions. (1) Her reading of the headline result is: "the vehicle-currency rotation is mostly compositional — controlling for pair composition, within-pair change is about zero." The current evidence supports this (within matched markets: +0.2 pp count, SE 0.8; −1.3 pp value, SE 2.2; vs. totals +25.7 pp count / +42.8 pp value carried by common-pair reweighting +7.9/+26.2 pp and pair-composition margins +9.8/+19.2 pp). Audit the paper and deck so this reading is unmistakable at first mention of the rotation, not only in the conclusion; if any passage could be read as pair-level stable-for-native switching, rewrite it. Do not use the word "mechanical" in audience-facing prose — state the positive so-what instead: the aggregate share moves because the trading network reorganises around the challenger, not because comparable trades switch intermediary. (2) The conclusion's three margins by which a vehicle gains aggregate share (more common within a pair; activity shifting toward pairs that already use it; newly active pairs routing through it) need one illustrative deck slide with actual token examples — pull the largest correctly labelled pair contributions from output/exhibits/vehicle_transition_pair_decomposition.jsonl and name concrete tokens/pairs with their real numbers, one example per margin. (3) Bridge to a TradFi story for motivation and external validity: e.g. China–Brazil now settling bilateral trade without the US dollar — the aggregate dollar vehicle share can fall while established corridors keep using it, because new and growing corridors never adopt it; map this explicitly onto the reweighting and pair-composition margins in both the deck and the introduction/conclusion. Keep it an illustrative analogy with a cited source, no causal or geopolitical claims. Guardrails: keep interpretation descriptive and do not call pair composition entry/exit effects (per the 2026-08-14 interjection); refresh the single existing draft in place, no fork.
  _Closed in this iteration. (1) The compositional reading now lands at every first mention: abstract sentence three, the introduction's headline paragraph (which states the matched-market estimate and its standard error where the aggregate is first reported), the end of Section 3.1, and the first slide that shows the rotation. Section 3.2 now opens on the three margins and says which one did not move; the deck's closing banner states the positive so-what. The one audience-facing use of "mechanically" is gone, rewritten as where trading happens rather than which intermediary a trade selects. (2) The new deck frame "Three margins move an aggregate vehicle share" names one real ordered pair per margin with its own cells, and the same three pairs appear in Section 3.2. (3) The corridor analogy is in the introduction (with a footnote citing the PBoC/BCB memorandum), the conclusion's external-validity paragraph, and a new deck frame before the close. Guardrails held: nothing is called an entry or exit effect, no data run occurred, and the single draft was refreshed in place. Note for Java: the queue's count figures (+7.9 reweighting, +9.8 pair-composition) do not reproduce; the exhibit's pooled count terms are +8.6 pp reweighting and +17.8 pp net exclusive-pair, and the value figures (+26.2/+19.2) do reproduce exactly. Every number in the paper and deck comes from the exhibit, not the queue text._



- [x] **JAVA INTERJECTION (browser, 2026-08-14T18:59:14+00:00):** CLEAN-BOUNDARY SCIENCE HANDOFF — do not interrupt the running corrected V3 event-source certificate. After that run is durably validated and its code/evidence are committed, fetch origin/main and integrate the independently reviewed M3 commits f52b43b (ranked route-contribution ledger), 2b74fd7 (V4 settlement identity hardening), and 2bd6657 (V2 liquidity predictability workflow), resolving only real conflicts and preserving Studio data ownership. Then, using Studio's complete current endpoint-candidate release and current D3 binding, run only scripts/run_vehicle_rotation_composition_e0.py. Report the 2024–2026 total change and its within-pair choice, common-pair reweighting, common-support-mass, and exclusive-pair-composition components by count/value and integration scope; list the largest correctly labelled pair contributions and exact release generation. Keep interpretation descriptive, do not call pair composition entry/exit effects, and do not open paper prose. Do not run V2 liquidity until pool_capital_release/current.json and its registered inputs are current; do not run V4 receipt selection until the route-unit source carries exact block_number and passes the new contract. Preserve the current V3 task first, then continue the grind.
  _Closed across `afd12fe` (integration of f52b43b/2b74fd7/2bd6657), the recovery-committed rerun `c1447e7` (exhibits bound to D3 generation dbe24bb3…), and this iteration's full readout in `logs/grind-ledger.md`: within-pair change is near zero on every metric/scope; rotation is common-pair reweighting plus exclusive-pair composition. V2 liquidity and V4 receipt selection were not run, per their stated preconditions._

- [ ] **M3 COORDINATOR HANDOFF (2026-08-14T12:03:00Z):** DO NOT INTERRUPT THE CURRENT STUDIO-OWNED FULL-CALENDAR MARKET-STATE OR ROUTE-COST WORK. At its next marker-complete clean boundary, fetch and fast-forward to `origin/main` at or beyond `7072291`, preserving the completed Studio generation and reopening only descendants whose code or input identity changed. M3's reconciled packet is tested (924 repository tests, paper/deck compile and deliverable conformance) but its WETH-eligibility, non-WETH value decomposition, stable-concentration and method-family results remain E0/provisional while the freeze is red; do not promote them to J1 merely because they are now on `main`. Continue the existing D2/D3 owner toward the smallest J0 release that closes the currently observed blockers: current directed-route and claim-input provenance; explicit E1/D3 generation and certificate identities; manifest/provenance/scope for the existing 113,822,022-row route-cost panel; memory-bounded semantic audit; route calendar/count/value reconciliation; and two unchanged findings passes. Preserve the affirmative scientific boundary: WETH endpoint eligibility explains most of the count rotation but not the strict-value rotation, whose non-WETH change decomposes as +21.48 pp = +23.52 pp activity-weight reallocation - 2.04 pp within-market change. After J0, rerun only the affected E0/E1/F owners on the current release, report any numerical change live, and continue through J1 rather than stopping at an engineering certificate.

- [x] **JAVA INTERJECTION (browser, 2026-08-14T09:51:25+00:00):** SUPERSEDES THE EARLIER EFFICIENCY REDIRECT: direct inspection confirms the active child is about 88 percent through pass 1 of three identical 13,093-chunk classifications. Interrupt now. Amend the EXISTING V3 event-source owner only; do not create a parallel pipeline. Preserve one full classification as construction evidence. Reuse its ranges and perimeter for pre-publication checks. After atomic publication, reopen artifact bytes and rerun only the 62-date exact-versus-canonical comparison while binding the certified ordered-manifest, frozen-header, pool-registry, correction-generation and quarantine identities. Ordinary freeze validation must not decompress out-of-audit-day payloads. Add focused tests that changed manifest identity and changed audit-day events fail, and that out-of-audit-day payloads are not opened. Then rerun once, report elapsed time and exact comparisons, and on pass proceed immediately to the existing full-calendar market-state builder. No V3 refetch, no new certificate family, no further certificate beautification.
  _Closed by the amended V3 event-source owner in `3561ae5`: one preserved global classification (2:37:34.40), bounded 7:25.36 publication resume, audit-date-only reopening with focused manifest/event/payload tests, and all 62 exact comparisons passing._

- [x] **JAVA INTERJECTION (browser, 2026-08-14T09:50:24+00:00):** EFFICIENCY REDIRECT. The active V3 audit is scientifically material for main_v1 because V3 dominates comparable route opportunities, so allow the current child to finish. But the existing owner can classify the same 13,093-chunk global raw inventory up to three times in one build/reopen cycle. Do not rerun this command unchanged and do not spend another iteration polishing its certificate. If it passes, record runtime and move immediately to the existing full-calendar market-state builder, then main_v1. If it fails or remains in its first global pass at four hours total, stop and amend the existing owner so the 62-date comparison reuses the already-certified global manifest and inherited quarantine ledger; scan only scientifically relevant date chunks and test the narrowed boundary. Never refetch V3 raw data or broaden the estimand.
  _Closed as superseded by the 09:51 interjection and the same `3561ae5` unit: the owner was amended rather than rerun unchanged, no V3 raw refetch occurred, and the estimand stayed the 62-date audit calendar._


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

- [x] **M3 SUPERVISOR (2026-08-14T21:55Z): recovery churn cleared; leaked test scratch is not work.**
  Iterations 9–14 were bounded recovery workers re-dispatched against the same
  untracked `e0-release-test-kvipg68h/` + `data/manifests/e0-release-test-kvipg68h/`
  pair — scratch leaked by a killed `tests/test_exploration.py` run (its fixture
  builds `tempfile.TemporaryDirectory(prefix="e0-release-test-", dir=REPO_ROOT)`,
  so a worker killed mid-test leaves the directory behind). Iteration 9's worker
  already diagnosed the pair as inert byproducts but recovery constraints forbade
  deletion, which re-triggered recovery every boundary. The M3 supervisor archived
  the pair to `~/projects/defi-vehicle-currencies-backups/e0-test-leak-20260814/leaked-dirs.tar.gz`
  on Studio, removed it from the d3 worktree, and landed a `.gitignore` guard
  (`e0-release-test-*/`, `data/manifests/e0-release-test-*/`) so leaked fixture
  scratch can never read as worktree dirt again. A live `e0-release-test-k08_pzi7/`
  belonging to the then-running iteration-14 worker was deliberately left alone;
  if it remains after that worker exits, it is ignored dirt and safe to delete.
  Proceed with the open queue items above.

- [x] **M3 SUPERVISOR (2026-08-14T21:58Z): parked table-header refinement — apply only AFTER the queued composition E0 refresh regenerates `output/exhibits/vehicle_transition_pair_fixed_effects.jsonl` on the current certified release.**
  Change the `pair_composition` column header from `Estimate in pp (clustered s.e.)`
  to `Estimate in pp` in `src/ddvc/dominance_tables.py::render_pair_composition`
  (the `\exhibitnote` in `paper/sections/03-dominance.tex` already states the
  two-way clustering, so the header annotation is redundant and off JFE register);
  update the matching assertion in `tests/test_dominance_tables.py` to
  `"Margin or estimate & Estimate in pp & Obs."`. Because the fixed-effects
  exhibit's certificate pins the presentation producer, editing the renderer
  before the exhibit refresh makes `render_pair_composition` refuse to restamp
  (verified on M3, 2026-08-14): so after the exhibit refresh, apply the edit,
  rerun `scripts/tabulate/render_pair_composition.py`,
  `render_dominance_rotation.py` and `render_usdt_transition.py` to restamp all
  three tables, and confirm `tests/test_dominance_tables.py` is green.
  _Closed after the precondition landed in `c1447e7` (fixed-effects exhibit bound to certificate generation dbe24bb3…): the header is now `Estimate in pp`, all three tables restamped through their render scripts, the updated assertion and full `tests/test_dominance_tables.py` pass (8 tests), and `paper/main.pdf` compiles clean with the edited table._

- [x] **JAVA INTERJECTION (WeCom via glotl, 2026-08-16T12:50Z):** DECK ANALYTICS PASS — KILL THE CHRONOLOGICAL SPINE, LEAD WITH CONTROL SETS; AND REBUILD THE CONCLUSION FRAME. Deck only (plus the paper hooks named in (4)); no new data acquisition. Take it at the next clean boundary; do not interrupt a running unit. Java's verbatim objection: "way too much emphasis on the chronological axis and few more sophisticated analytics with different sets of control variables; the conclusion slide is confusing and not powerful."

  **Diagnosis to act on (verified by the supervisor against the working tree, 2026-08-16).** Two full specification ladders already exist, are produced by owned scripts, and are consumed by *neither* the deck nor the paper — `grep -rl` finds them only in their producers and in `audit_findings_freeze.py`:
  - `output/exhibits/dominance_regressions.jsonl` (12 rows, producer `scripts/run_dominance_regressions.py`). Estimand: is the native intermediary less often dominated, **holding the trade fixed**. Ladder: (1) pooled −0.0486 (0.0182) p=0.008, n=102,845 → (2) + log notional −0.0507 (0.0192) p=0.008 → (3) + year effects −0.0494 (0.0187) p=0.008 → (4) pair-by-day FE **+0.0937 (0.0847) p=0.269, n=3,865**. Plus a `gap_bps` outcome at (5) and a 1/3/7/14/30/60/120-day control-window ladder that holds the same sign and non-significance out to n=7,465.
  - `output/exhibits/dominance_specification_curve.jsonl` (12 rows, producer `scripts/run_dominance_specification_curve.py`), varying six dimensions independently: fixed-effect depth, outcome definition, venue restriction, candidate-count restriction, an interaction with log size, and era.

  **(1) New primary results frame: the control ladder as the argument.** Build one frame that walks specification strictness left to right and shows the raw association dissolving as the trade is held fixed: pooled → + size → + year → pair-by-day FE, with confidence intervals, `n`, and the identifying-cell count on the FE column. This is the *same* thesis the rotation result carries (the pattern is about **where** trading happens, not **which** intermediary a comparable trade picks), arriving from a second and independent estimand. Say that relationship explicitly on the frame — two different questions, one answer.

  **(2) WITHDRAWN BY THE SUPERVISOR, 2026-08-16 — do not implement.** This slot originally asked for a specification-curve frame built from `dominance_specification_curve.jsonl`. That was a supervisor error, corrected on re-reading the gate: `run_dominance_specification_curve.py` is on the **retired-estimand list** in `audit_findings_freeze.py` ("refresh graph excludes retired estimands; only validated diagnostics may run", retired in `68d4df7`), and `docs/research-workflow.md` separately forbids what the exhibit does structurally — "coefficients from different estimands receive only a conceptual bridge and **never share one specification curve**". Its 12 rows mix FE depth, outcome definition, venue, candidate count, interaction and era across estimands, which is exactly the prohibited object. Building this frame would put a retired estimator on an audience-facing slide and re-red the refresh-graph check. **Do not resurrect the exhibit and do not cite it.** If a robustness frame is wanted, build it only from within-estimand variation of a live estimator — the `(4w)` 1/3/7/14/30/60/120-day control-window ladder inside `dominance_regressions.jsonl` is live, is one estimand, and already carries the needed variation.

  **(3) HONESTY GUARDRAILS — these are blocking, not advisory.** (a) The FE column is a **precision loss as well as a sign flip**: n falls 102,845 → 3,865 and the SE nearly quintuples. Do NOT present it as an estimated null. State the minimum detectable effect (`mde_80` is already a field in the exhibit; populate it if NaN) and the identifying-cell count on the frame itself. The honest sentence is "not distinguishable from zero, and here is what we could have detected", never "no effect". (b) The continuous `gap_bps` outcome IS significant at (5)/spec-curve (−25.26, p=0.037) where the binary outcome is not: show that disagreement, do not bury it — functional form is a real caveat and hiding it is the kind of thing a referee finds. (c) Keep the two estimands **labelled distinctly**: dominance-quality-holding-the-trade-fixed is NOT the aggregate share rotation. Do not let the frame blur them into one number. (d) These exhibits are E0/provisional while the freeze is red; bind them through the normal audited evidence-comment mechanism and the render scripts, never by hand-typed numbers.

  **(4) REBUILD THE CONCLUSION FRAME** (`deck/sections/05-close.tex`, the frame "Stablecoins regained the routed-value lead as trading shifted"). It currently fails Java's test because two of its three panels are time arrows — panel 1 is a 2022 / 2023–24 / 2025–26 lead sequence and panel 2 is a 2024→2026 dumbbell — so the closing image of the whole talk is a chronology, and the actual economic claim is demoted to a banner of running text underneath. Rebuild it so the punchline is the *invariance*, not the timeline: the aggregate share rotated hard, and every design that holds the market fixed — matched within-pair, pair-by-day FE, the window ladder, the specification curve — shows nothing comparable. One time element may survive as setup, not as the argument. The frame must state one sentence a listener can repeat from memory, and that sentence should be the composition result, not "the lead changed".

  **(5) Chronological-axis audit across the whole deck.** Inventory every frame whose primary visual axis is calendar time. Where a frame's scientific content is a comparison across specifications, groups, venues, scopes, or candidate sets, re-cut it on that axis instead. Report the before/after count of time-axis frames in the ledger. Do not delete the rotation time series itself — it is the motivating fact — but it should appear once, early, as setup.

  Guardrails: single draft refreshed in place, no fork; compile, visually inspect every touched page, run `audit_deck_evidence.py` and the deliverable-conformance check; nothing audience-facing gains a provisional badge or hash label.

  _Closed in `e8a785c` (evidence layer) and `2a797b7` (frames). **(1)** built as deck page 14, "Holding the trade fixed dissolves the intermediary gap", from a new owned producer `scripts/figure/build_dominance_ladder.py`; it states the two-questions-one-answer bridge on the frame. **(2)** not implemented, as instructed; `refresh graph excludes retired estimands` still passes and the retired exhibit is neither read nor cited. **(3)** all four guardrails met: the strictest column carries its detectable effect (23.7 points) and switching-cell count (703) on the column itself and is never called a null; the continuous outcome is displayed on the same cells; the two estimands are kept on separate scales with no shared axis on either frame; and every number binds through generated macros. **(4)** rebuilt as page 18, "The market changed, not the trade", a conditioning ladder (+25.7 pp → −0.1 pp → +0.2 pp) with the dominance estimand beside it behind a rule. **(5)** frames with calendar time as the primary visual axis: 2 before, 1 after; the rotation series stays once and early. Two frames keep a calendar element as setup and are correct on that axis (the 02-objects deployment timeline, the A2 backing-regime heatmap); the V1–V4 strip is cut on protocol design, not the calendar._
  _One correction to (3)(b): the −25.26 bps (p=0.037) figure is from the retired specification curve. On the live estimand the continuous outcome is +186 bps (SE 106, p=0.078) and **agrees** with the binary column rather than disagreeing with it. The frame shows it either way, so a referee sees the functional form rather than a choice._

- [ ] **JAVA INTERJECTION (WeCom via glotl, 2026-08-16T15:55Z):** CONTROL THE CALENDAR IN FIXED EFFECTS AND SHIP VOLUME. Java's verbatim instruction, which **supersedes** the supervisor's earlier framing in this same slot: "Time axis is ok but you can just control it in eg fixed effect. Give me more results ! Ok if on preliminary data - if computation not overwhelmed then keep trying and building in parallel and write into paper and deck!!"

  Read that precisely. She is **not** asking to remove calendar comparisons; she is asking to stop treating the time axis as the identifying variation and start **absorbing it in date fixed effects** so identification comes from the cross-section within a day. She has also explicitly lowered the bar for what may enter the deliverables: **preliminary/E0 estimates are admissible**, provided they carry their scope and uncertainty, and she wants **throughput** and **parallelism** where compute allows, with results written into the paper and deck as they land rather than held back.

  **The supervisor already ran a first batch and it works. Do not redo it, extend it.** Scripts and outputs are outside the worktree at `~/.local/share/glotl/dvc-supervisor/` (`dvc_datefe_ladder.py`, `dvc_datefe_contrasts.py`, and their `.jsonl`). Panel: `data/processed/vehicle_excess_use_daily.parquet`, restricted to `endpoint_supported` token-days with more than 20 route units, giving 1,828,862 token-days over 304,572 tokens and 2,259 dates. Estimator: the repo's own `ddvc.analysis.regression` (`absorb_fixed_effects` alternating projections, `ols_clustered` two-way CR1 on date and token). `pyfixest` is NOT installed and must not be added; the shared estimator is the right owner.

  Headline of the first batch, stated so a worker can reproduce and then supersede it. **Every figure below must be re-derived from the panel before it enters prose; never bind a number from this queue text.**
  - Absorbing date FE moves the type contrasts essentially not at all (native 34.56 → 34.55 pp, stable 2.420 → 2.418 pp). The cross-sectional differences between asset classes are **not** a calendar artefact. Say this explicitly; it is the direct answer to the objection.
  - Conditioning on the token's own endpoint (trade-demand) share within the day collapses the native premium from 34.56 pp to **0.053 pp (SE 0.556)**, while stable holds **+0.846 pp (SE 0.499)**. Native's apparent intermediary dominance is accounted for by its own trade demand.
  - On the five named candidates with date FE and stable as the base (n=11,233 over 2,258 days), **native intermediates 17.45 pp less than a stablecoin (SE 3.15, p=3.4e-08, 95% CI [−23.6, −11.3])** conditional on demand. On all 37 classified tokens the same contrast is −1.51 pp (SE 0.076); the magnitudes differ because share mass differs by sample, and **both must be shown together** rather than quoting the larger one.
  - Demand pass-through is 1.59 (SE 0.026) pooled cross-sectionally, 1.98 (SE 0.082) among the five candidates, and **0.985 (SE 0.301, p=0.001)** within token and within day under two-way token+date FE absorbing 306,830 degrees of freedom, so part of the cross-sectional excess is between-token composition.
  - Slope-by-type contrasts: stable minus native is **+0.351 (SE 0.263, p=0.18, CI [−0.17, +0.87]), NOT separable** — do not write that stables out-intermediate natives on pass-through. Native minus imported is +0.075 (SE 0.028, p=0.007) and is separable.
  - Splitting the sample into calendar halves and re-fitting leaves the structure intact (demand slope 1.605 early, 1.554 late; native premium +0.70 (SE 0.98) early, −0.72 (SE 0.94) late, neither separable from zero). Calendar is a **sample split** here, not the identifying variation. This is the template for every result: keep the time dimension, demote it to a robustness cut.

  **Blocking caveat before any of this ships:** intermediary share and endpoint share are drawn from the same day's route universe, and a token cannot be the intermediary on a route where it is an endpoint, so a mechanical crowd-out channel exists. The estimated pass-through is positive, which argues against crowd-out dominating, but this is not a substitute for the screen. Run `scripts/run_dominance_mechanicalness_screen.py` against this specification and report it beside the estimates. If the screen cannot clear the design, the result is reported as descriptive association and says so.

  **Now extend, in parallel where the box allows** (16 cores, load was 1.78 when this was queued; keep total load under about 12 and never contend with a running Studio reduction):
  1. Promote the conditional-on-demand cross-section to a lead result in **both** paper and deck, with the ladder shown as a ladder (pooled → date FE → + own demand → two-way FE) so the reader sees the calendar absorbed and the answer unchanged.
  2. Re-run every existing headline estimator with date FE added rather than replaced: keep the estimate, add the rung. Report which coefficients survive absorption and which do not, and demote the ones that do not to descriptive.
  3. Add the backing-regime cut (fiat-reserve vs on-chain-collateralised vs synthetic) and the token-level cut (USDC vs USDT) to the same date-FE design, so "which kind of asset takes the role" is answered within-day.
  4. Add pair-level and venue-integration interactions to the same design where the green panels support them.
  5. Report every contrast that is **not** separable as prominently as the ones that are, with its interval. The 2026-08-16 "not X, but Y" rule binds all of this: both sides evidenced in the same frame and units, negated side carried by an interval excluding the economically relevant magnitude, otherwise dropped for a plain descriptive line.

  Guardrails: single draft refreshed in place, no fork; every number binds through generated macros from a committed exhibit; preliminary/E0 results are admissible at their stated scope per Java's instruction, but must carry scope and uncertainty and must not be labelled submission-authoritative. Write results into the paper and deck as each lands rather than batching to the end. Do not resurrect a retired estimator to do any of the above; build new owners under the live estimators. Record in the ledger, per result, whether calendar time is the identifying variation, a control, or a robustness split.

## Closed

_(items are ticked in place above)_

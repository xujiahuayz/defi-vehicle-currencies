# NBC 2026 slide-deck pipeline (device/LLM-agnostic spec)

**Purpose:** produce a reviewable slide deck for the invited talk at Nanyang Blockchain Conference 2026 (NTU Singapore, 21-22 Aug 2026, 30-minute slot including Q&A). Not the paper, not conference-feedback incorporation — deck only.

**Hard deadline: complete and compiled by 10 Aug 2026.** That leaves 10 Aug-20 Aug for Java's own review, revision, and rehearsal before flying. This is the binding constraint on every phase below, not a soft target.

**Portability rule:** this file, and every phase's output, is a plain tracked file in this repo. No phase's real state may live only inside a model-specific session (a Claude `Workflow` run, a Codex session, etc.). Whatever is executing this — Claude, Codex, Gemini, or a human — reads this file and the on-disk outputs of the last completed phase, and continues. The *mechanism* used to parallelize/verify a phase (subagent fan-out, sequential passes, whatever the executor has) is an implementation choice; the *spec, inputs, and outputs* are not.

**Sync rule:** commit AND push to `origin` after every phase completes, not just locally. Local-only commits don't help if the active executor or host changes mid-run — the next executor needs to `git pull` and find the latest phase output on the remote, not rediscover it. Treat an unpushed completed phase as an unfinished phase.

**Hard scope fence:** liquidity provision in relation to vehicle currencies. Nothing further out (no reviving the retired CDOM/asset-pricing leg) without an explicit Java decision.

**Core design principle:** no agent/step may inherit another agent's interpretation of a source as ground truth. A shared corpus of actual primary documents is fine to point many readers at (it's data, not opinion). Any interpretive claim — what a paper's identification licenses, whether a structure matches precedent, whether a result overclaims — gets independently re-derived by whoever needs it, by opening the primary source itself. The highest-stakes interpretive calls get 2-3 independent reads cross-checked against each other, not one pass trusted everywhere.

**Calibration standard, split by what it's for:** AFA/WFA/NBER-caliber presentations calibrate the deck's *pacing, motivation, and layout* — how a talk is paced and structured, not how deep the underlying paper needs to be. Conference-stage presentations are routinely more preliminary than what eventually gets published; if this project's evidence is more mature or resolved than a typical conference-stage talk shows, that is not a mismatch to flag, it's expected. For *scope, experiment depth, and robustness* — the actual golden benchmark used in Phase 0/3/5 scoring — use the final **published** versions of the golden-benchmark comparator papers, not their earlier conference-presented drafts, since a paper's scope and results can drift substantially between conference presentation and publication. NBC 2026 is the delivery venue only — described by Java as a young venue being used as a test — never the calibration target for either axis. The one narrow exception is the Q&A backup appendix, which may draw on NBC's actual blockchain/CS-leaning audience profile, capped and confined to appendix content (see Phase 6).

**Cosmetic language gate** (checked mechanically against literal rendered slide text, soft gate — use only if there is truly no workable alternative in that specific sentence, and log a documented rewrite attempt for any claimed exception): avoid "rather than," "genuinely," "honest"/"honestly," "broader"; avoid em-dashes; avoid "·" as a list/label separator; at most one "X, not Y" / "it's not X, it's Y" construction in the whole deck; no redundant trailing "so ..." clause that only restates something already said on the same slide.

**Branding:** UCL CBT logo on the cover slide only — `~/Library/CloudStorage/OneDrive-SharedLibraries-UniversityCollegeLondon/UCL CBT - Documents/Operations (internal)/Media & Identity/Logos/Centre for Blockchain/Full colour/UCL_S_2C_DP_RGB_Ctr_Block_Tech_logos.png`. Every other slide stays plain — no running footer logo, no heavy template.

**Target size:** 12-18 core content slides, plus a large backup/appendix sized for Q&A (standard practice at this caliber of talk).

---

## Phases and on-disk outputs

Each phase writes its output to `output/nbc_pipeline/<phase>/` (create as needed) so the next phase — run by any executor — can pick it up by reading files, not by inheriting in-memory state.

**0. Corpus manifest** (blocking, gates Phase 1) → `output/nbc_pipeline/00_manifest.md`
Pointers only, no synthesis: co-author papers (Kathy Yuan, Emre Ozdenoren, Olga Klein's three papers), the already-classified anchor papers, 3-6 golden-benchmark JFE/RFS/Management Science/JFQA comparators picked for structural precedent. Each comparator must be the **final published version** (journal PDF/version of record), not an earlier conference-presented working-paper draft, since scope and results can drift between conference stage and publication — note explicitly if a comparator's published version differs materially from any conference-stage draft found along the way. Each comparator tagged with its empirical genre/subfield so a genre mismatch is visible before it poisons downstream scoring. Plus an inventory of what already exists in this repo and the reference `defi-dominant-currency` repo (old slide file, the RQ1-5 design doc, old result tables).

**0′. Exemplar retrieval** (parallel with Phases 1-2, must land before Phase 6) → `output/nbc_pipeline/00_exemplars.md`
Real decks/talks from AFA/WFA/NBER specifically, for pacing/motivation/layout only — faculty pages, SSRN/NBER slide postings, seminar recordings. These calibrate how a talk moves, not how deep the paper needs to be; conference-stage material is routinely more preliminary than the eventual published paper, so this lane's takeaways feed Phase 6's drafting only, never Phase 0/3/5's scope-and-depth scoring.

**1. Source-fidelity cross-check** → `output/nbc_pipeline/01_source_fidelity.md`
For every co-author/anchor paper a candidate framing might lean on: 2 independent reads characterizing what it actually licenses, cross-checked against each other, before any framing may cite it.

**2-5. Research-quality loop (the priority iteration target — this is where more rounds are worth spending, not Phase 7)** → `output/nbc_pipeline/0{2,3,4,5}_.../round_M/`

This is one iterative unit, not four one-shot phases. It runs until the winning framing's evidence genuinely meets the golden-benchmark bar, and is allowed to loop all the way back to framing generation if verification reveals the core mechanism doesn't hold up, not just patch individual results in place. Cosmetic/presentation concerns (Phase 7) do not belong in this loop and do not gate it.

- **2. Candidate framings** — no preset count. Generate candidate framings (each: headline mechanism, evidence hierarchy, narrative arc, built only on cross-checked Phase-1 claims) one at a time, keep going as long as a fresh attempt is genuinely novel (differs in headline mechanism or evidence hierarchy, not just wording) from every framing already generated, stop after two consecutive non-novel attempts (loop-until-dry), backstop cap of 5. Don't manufacture false diversity to hit a number — if 2 genuinely distinct framings are all the evidence supports, stop at 2. Free to abandon any RQ-numbered structure. Each includes a named, locatable slide spec for bridging the already-public conference abstract.
- **3. Benchmark scoring** — 3 independent judges per candidate framing against the Phase-0 published comparators, re-deriving source-fidelity as well as structural fit. Converge-within-tolerance auto-selects; divergence beyond threshold triggers a 4th arbitration agent that re-reads the disputed dimension's primary sources; near-ties are tagged and flagged to Java. Coherence check on the winning (possibly grafted) framing.
- **4. Evidence build** — reuse-biased: check for a valid existing result before rebuilding, build fresh only for genuine gaps. Not-closeable rule: a claim needing new data pulls/estimation code that can't realistically finish within roughly the first half of the remaining runway is presumptively not closeable, named as a gap.
- **5. Rigor + golden-benchmark-depth verification** — full 2-3-independent-skeptic treatment on the 4-6 results landing on core slides (decomposition sums correctly, signs match, FE/clustering/N reported, and — the actual exit test for this loop — robustness depth and identification credibility checked against what the Phase-0 published comparators actually show for an equivalent claim, not an internal sense of "good enough").

**Loop-back rule:** after step 5, classify any shortfall as either (a) **evidence-level** — a specific claim needs more robustness/depth to match the comparator bar — loop back to step 4 to strengthen only that claim, or (b) **framing-level** — the core mechanism itself doesn't survive golden-standard scrutiny (e.g. an identification strategy a published comparator would not accept) — loop back to step 2, informed by what step 5 learned, to generate a better framing rather than patching evidence onto a weak one. Do not silently proceed to Phase 6 with a framing-level shortfall.

**Exit condition:** the loop ends when step 5 finds no further evidence-level or framing-level shortfall against the golden-benchmark bar, or after 3 full loop iterations, or by 8 Aug end-of-day, whichever comes first. If the cap is hit with an unresolved framing-level shortfall, that is escalated to Java as a blocking flag before Phase 6 starts — this is exactly the kind of scientific-judgment call that should reach Java, unlike the cosmetic items in Phase 7.

**6. Narrative + slide draft** → `output/nbc_pipeline/06_draft/` (Beamer source; free to discard the old `slides/nanyang_vehicle_currencies.tex` skeleton if the winning framing doesn't fit it)
Drafting reads the Phase-0′ AFA/WFA/NBER exemplars directly for density/pacing/visual convention, and the verified Phase-5 evidence, sized to ~20 minutes of content / 12-18 core slides. Renders the abstract-bridging slide from Phase 2's spec. Builds an explicit Q&A-coverage map — anticipated questions from NBC's actual blockchain/CS-leaning audience (the one place that audience gets a say), each mapped to a specific backup slide.

**7. Cosmetic/presentation pass — one round, not a loop** → `output/nbc_pipeline/07_cosmetic_pass.md`
This phase does not iterate. Java will eyeball timing, language, and layout herself, so the automation here just needs to catch what's cheap and mechanical, fix it, and stop — it is not where the pipeline's iteration budget goes (that's the research-quality loop above). One pass covering: completeness/scope-fence/abstract-bridging-slide-presence check; calibration-fit spot-check against the Phase-0′ AFA/WFA/NBER set (not NBC's actual room); a capped 1-2 slide check that the Q&A appendix reflects NBC's actual audience without touching core density/language/layout; a mechanical grep of the cosmetic-language gate above; a citation-identity check against the Phase-0 manifest; a timing estimate against the ~20-minute target; a number-fidelity diff against the verified Phase-5 values. Fix what's found. Anything non-mechanical or debatable gets left for Java's own pass rather than driving a second round.

**8. Compile and thorough final QA** → the finished PDF + source
Build fidelity (fonts embedded, no overflow, pagination, PDF integrity) **and** a careful visual pass for rendering defects — overlapping text/figures, content bleeding off slide edges, misalignment, illegible figures/tables at actual rendered size. This does not reopen audience-calibration, density, or language decisions already settled in Phase 7 — it catches what a critique pass focused on content wouldn't: literal rendering breakage. Cover slide gets the UCL CBT logo per the branding note above; every other slide stays plain. Hand Java only the compiled PDF plus source.

## Learnings

- (populate as the pipeline runs)

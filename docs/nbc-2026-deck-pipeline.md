# NBC 2026 slide-deck pipeline (device/LLM-agnostic spec)

**Purpose:** produce a reviewable slide deck for the invited talk at Nanyang Blockchain Conference 2026 (NTU Singapore, 21-22 Aug 2026, 30-minute slot including Q&A). Not the paper, not conference-feedback incorporation — deck only.

**Hard deadline: complete and compiled by 10 Aug 2026.** That leaves 10 Aug-20 Aug for Java's own review, revision, and rehearsal before flying. This is the binding constraint on every phase below, not a soft target.

**Portability rule:** this file, and every phase's output, is a plain tracked file in this repo. No phase's real state may live only inside a model-specific session (a Claude `Workflow` run, a Codex session, etc.). Whatever is executing this — Claude, Codex, Gemini, or a human — reads this file and the on-disk outputs of the last completed phase, and continues. The *mechanism* used to parallelize/verify a phase (subagent fan-out, sequential passes, whatever the executor has) is an implementation choice; the *spec, inputs, and outputs* are not.

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
For every co-author/anchor paper a candidate spine might lean on: 2 independent reads characterizing what it actually licenses, cross-checked against each other, before any spine may cite it.

**2. Spine candidates** (3, not 4-5 — this is a talk deck, not a paper submission) → `output/nbc_pipeline/02_spines/spine_{1,2,3}.md`
Each built only on cross-checked Phase-1 claims. Free to abandon any RQ-numbered structure. Each must include a named, locatable slide spec for bridging the already-public conference abstract (old three-role/flight-to-dominance framing) — not just a stated intent.

**3. Benchmark scoring** → `output/nbc_pipeline/03_scoring.md`
3 independent judges per spine, scoring against Phase-0 comparators and re-deriving whether each spine's characterization of its sources is faithful (not just structural fit). Resolution rule: if judges converge within a stated tolerance, auto-select the top scorer. If any two diverge beyond threshold, a 4th arbitration agent re-reads the disputed dimension's primary sources and produces a citation-backed tie-break. Any near-tie is tagged (runner-up + disputed dimensions) and flagged for Java before Phase 4 starts. Followed by an explicit coherence check on the winning (possibly grafted) spine before it's treated as locked.

**4. Evidence build** → `output/nbc_pipeline/04_evidence/`
Reuse-biased given the deadline: for each claim the winning spine needs, check whether a valid existing result in this repo or the reference repo already covers it, independently re-derive/re-check it against the underlying data/scripts rather than trusting an old caption, and build fresh only for genuine gaps. **Not-closeable rule (tightened for the 10 Aug cutoff):** a claim requiring new data pulls or new estimation code that cannot realistically finish within roughly the first half of the remaining runway is presumptively not closeable — becomes a named gap for the talk, not a blocker. If the volume or severity of flagged gaps would make the winning spine evidence-thin, that reopens Phase 3 rather than proceeding silently.

**5. Rigor verification** → `output/nbc_pipeline/05_verification.md`
Full 2-3-independent-skeptic treatment only for the 4-6 results that will actually land on core content slides (decomposition sums correctly, signs match the claim, FE/clustering/N reported, robustness depth checked against Phase-0 comparators). Backup/appendix-only results get a single sanity pass. Includes a mechanical citation-identity check against the Phase-0 manifest (catches wrong-paper/wrong-co-author credit, which independent re-reading alone won't catch).

**6. Narrative + slide draft** → `output/nbc_pipeline/06_draft/` (Beamer source; free to discard the old `slides/nanyang_vehicle_currencies.tex` skeleton if the winning spine doesn't fit it)
Drafting reads the Phase-0′ AFA/WFA/NBER exemplars directly for density/pacing/visual convention, and the verified Phase-5 evidence, sized to ~20 minutes of content / 12-18 core slides. Renders the abstract-bridging slide from Phase 2's spec. Builds an explicit Q&A-coverage map — anticipated questions from NBC's actual blockchain/CS-leaning audience (the one place that audience gets a say), each mapped to a specific backup slide.

**7. Critique loop** (capped: max 4 rounds, hard stop by 9 Aug regardless of convergence) → `output/nbc_pipeline/07_critique/round_N.md`
- Completeness critic (+ scope-fence check, + abstract-bridging-slide presence check)
- Calibration-fit critic — reference standard is the Phase-0′ AFA/WFA/NBER set only, never NBC's actual room
- Delivery-context critic — capped at 1-2 slides, confined to the Q&A appendix, cannot touch core density/language/layout
- Cosmetic-language critic — mechanical grep against the gate above
- Timing rehearsal (word-count-per-slide against a spoken-words-per-minute baseline)
- Number-fidelity check (every rendered-slide number diffed against its verified Phase-5 value)

Anything still open at the round/date cap becomes either a named limitation slide or an explicit item flagged to Java — the critic states which.

**8. Compile and thorough final QA** → the finished PDF + source
Build fidelity (fonts embedded, no overflow, pagination, PDF integrity) **and** a careful visual pass for rendering defects — overlapping text/figures, content bleeding off slide edges, misalignment, illegible figures/tables at actual rendered size. This does not reopen audience-calibration, density, or language decisions already settled in Phase 7 — it catches what a critique pass focused on content wouldn't: literal rendering breakage. Cover slide gets the UCL CBT logo per the branding note above; every other slide stays plain. Hand Java only the compiled PDF plus source.

## Learnings

- (populate as the pipeline runs)

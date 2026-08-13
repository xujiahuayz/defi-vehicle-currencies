# Nanyang deck architecture

The Nanyang Blockchain Conference slot is 30 minutes including questions. The canonical deck therefore targets 12–13 core slides and a curated appendix of 13–17 slides. The deck is one live source tree under `deck/`; git history is the archive, and no second deck survives after replacement.

## Venue benchmark

The visual and language benchmark is the five saved full finance/economics presentations in the literature corpus. The modern Terra author deck and the Bouvard and Liao discussions use a median of roughly 40–55 visible words per page; the old Brunnermeier–Pedersen deck is useful for intellectual sequencing but is a negative density benchmark. The live deck uses 11-point Beamer, no exhibit text below 10–11 points, one empirical object per slide, and at most three short explanatory bullets around a chart or diagram. Functional titles state a topic or result directly. Poetic titles, symmetric status dashboards, visible workflow labels, grey italic exhibit notes and full-slide reference lists are not part of the design.

## Pre-findings slide architecture gate

| Claim family | Proof before promotion | Live-deck consequence |
|---|---|---|
| `vehicle_transition_e0` | Denominator, count/value agreement, excess use, calendar support, within-pair and composition decomposition | Continuous dominance and its decomposition may enter after E1 |
| `routing_maturation_e0` | Topology versus reach, exact route reproduction, fixed opportunity cells and horizons | Keep routing complexity separate from execution quality and aggregator attribution |
| `direct_cost_dominance_e0` | Same-state quotes, selection, value, gas, reach and support loss | Show incidence and magnitude on one support or omit the result |
| `liquidity_allocation_e0` | Separate capital, inventory and executable depth; exact horizons and validated ownership | Keep protocol families and directions separate until the evidence supports synthesis |
| `open_question_anomaly_e0` | Reproduction, magnitude, concentration, denominator stability and strongest rival | An anomaly earns a slide only after a separate confirmatory generation |

## Core dependency order

1. Cover, UCL CBT affiliation and the question.
2. Audience poll on the source of dominance.
3. Binary vehicle status versus continuous vehicle dominance.
4. Identification: observed and counterfactual routes at one state.
5. Institutional origin: V1 imposed ETH intermediation and later designs made the role a choice.
6. Certified sample perimeter.
7. Measurement map separating vehicle share, excess use, network position and execution advantage.
8. Mechanism map: liquidity provision, coordination, market integration and holding cost.
9. Empirical design separating formation, rotation and persistence.
10. Promoted result blocks in contribution order.
11. Close containing only results already shown.

The result block is generated from the best current evidence set. A result that fails its scientific gate disappears with its setup; retired or internally rejected estimates appear in neither the core deck nor the conference appendix. Evidence may evolve, but the deck is always a deliverable: updating an estimate regenerates the relevant frame in place and never authorizes a parallel deck or a stale slide. Evidence status, commit identity, generation identity, and repository paths remain machine-checkable source comments rather than audience-facing labels.

## Always-ready evolution loop

The canonical loop is claim register $\rightarrow$ generated evidence binding $\rightarrow$ slide and paper consumers $\rightarrow$ compile and visual review $\rightarrow$ source audit $\rightarrow$ commit. `docs/findings-freeze.md` is the durable claim and objection register. A scientific interjection changes the relevant claim row, estimand, or blocking attack there; it does not survive only in chat or in a parallel memo. A delivery-only correction changes the canonical slide and its source metadata directly.

Every evidence-managed frame carries three non-rendered comments immediately above it: `EVIDENCE-STATUS`, `EVIDENCE-COMMIT`, and `EVIDENCE-SOURCES`. The first records the scientific state, including a live support objection. The second identifies the commit that owns the displayed evidence. The third names the generated exhibit and claim-register entry. These comments are audited, but no provisional badge, repository hash, path, or workflow state is shown to the audience.

Each loop iteration has seven closure checks:

1. Scientific: the claim, estimand, strongest rival, support loss, and falsifier agree across the register, deck, and paper.
2. Data: every measured cell is generated from the latest admitted artefact or explicitly recorded as evolving evidence; no number is typed into slide source.
3. Narrative: titles and takeaways remain substantive even when estimates update, and the close contains only results already shown.
4. Visual: compile cleanly, inspect a full contact sheet, inspect changed or dense frames individually, and reject clipping or overflow.
5. Provenance: source comments identify status, evidence commit, and sources; audience-facing source lines contain only citations or sample information useful in the room.
6. Continuity: commit the single deck and PDF on `main`; future data refreshes replace the same generated binding and frames.
7. Field language: scan audience-visible source against the saved finance/economics corpus and the executable backstage-language blocklist, then repeat on extracted PDF text after compilation. Terms such as `verdict`, `findings freeze`, `evidence gate`, `data pipeline`, `workflow status`, `provenance status`, and `scientific certificate` remain in comments or logs; the slide states the economic result, identifying comparison, limitation, or interpretation directly.

## Visual grammar

- Vehicle status uses a route diagram or zero/one indicator. Vehicle dominance uses an explicit share axis and names the denominator.
- Count and value shares remain separate panels because they measure frequency and economic scale.
- Rotation changes shares, fragmentation changes concentration, and replacement requires a persistent change in leader. The deck does not use succession without the replacement condition.
- Support loss is visible on the relevant exhibit when it can change interpretation. Minor provider omissions enter the evidence ledger and sensitivity bound, not a workflow-status slide.
- Candidate colors remain stable across the talk. The UCL CBT mark appears once on the cover; affiliation and logo strips are not repeated.
- Source attribution needed by an audience appears as a restrained `Source: Author (year); sample` line beneath the exhibit. Repository paths, generation hashes and detailed provenance stay in source comments and the replication package.
- The display follows the intellectual object. Charts and diagrams lead for shapes, mechanisms and time paths; finance-style tables may appear in the core or appendix when the coefficient pattern across specifications is the result. Slide tables retain only the columns needed for the spoken comparison, keep projection-readable type and visually mark the cells under discussion.

## Appendix map

The appendix contains only defensible material likely to answer a conference question: definitions and data; reconstruction and validation; robustness and time clocks; mechanisms; references. It excludes internal process, artefact inventories, failed tests, retired estimates and diagnostics whose scientific object has been superseded.

## Delivery gate

The deck is not delivered from source alone. Every edit requires a clean compile, a full-page visual contact sheet, individual inspection of any dense frame, no overfull boxes, no clipped content, and the repository conformance checks. The current PDF must be presentation-ready after every iteration. Evidence status can change without changing that delivery standard; the source register and comments carry the distinction between evolving, admitted, diagnostic, and support-failure evidence.

## Legacy pre-E1 outline

Removed after the 2026-08-12 rebuild. Git history retains it; the obsolete 45-frame topology is not a second live authority.

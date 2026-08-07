---
status: open
---

# Literature audit

Status opened 2026-08-07. This ledger repairs a project-level evidence gap: earlier workflow documents claimed first-hand readings of fourteen JFE venue exemplars and later used a nine-paper architecture subset, but the paper-level evidence lived in transient agent output. Aggregate scripts and extracted text survive; the individual reading record does not. Until the cards below are complete, venue counts and source characterisations are provisional and findings cannot freeze.

## Completion contract

Each paper is classified as load-bearing, contextual, venue exemplar, or more than one. A complete card records five distinct reading axes, not a generic prose summary:

- exact title, authors, year, publication/version and saved source;
- project roles and every bibliography key or manuscript claim that uses it;
- `Scientific`: question, contribution, theory or mechanism, data, measurement, identification, main estimates, boundary conditions and credible alternative readings;
- `Structure`: top-level and subsection architecture and the function of each major block;
- `Depth`: where the paper spends analytical, institutional and robustness effort, and what it treats lightly;
- `Breadth`: scope, literatures, mechanisms, objections, alternatives and boundary discipline;
- `Optics`: title, opening, claim calibration, tables, figures, captions, notation, prose density, page allocation and reviewer-facing credibility;
- exact page, section, table or equation supporting every project use;
- first reader, completion status and independent-reader status.

Allowed statuses are `discovered`, `abstract-screened`, `full-text-read`, `claim-verified` and `independently-re-read`. Keyword retrieval, text extraction and corpus-level counts never advance a paper beyond `abstract-screened` on their own.

## Current audit perimeter

The manuscript currently cites 47 unique bibliography keys. The saved scientific corpus contains 54 PDFs, with 53 text extracts; the LVR paper is cited but was not present in the saved PDF/text corpus when this audit opened. The venue corpus contains 14 JFE PDFs. These sets overlap only partly and serve different purposes, so both require explicit cards.

Priority order:

1. Repair missing source/version coverage, beginning with the LVR paper and the published-versus-working-paper ambiguity for Flandreau and Jobst.
2. Full-text cards for every source carrying the contribution, mechanism, measurement or empirical-design argument.
3. Full-text cards for all 14 JFE venue exemplars, covering content depth and breadth as well as structure and optics.
4. Claim-location verification for every one of the 47 cited keys.
5. Independent re-read of central uses before the second stable F to G pass.

## Incident findings already established

| Source/use | Prior status | Audit verdict | Required closure |
|---|---|---|---|
| Milionis, Moallemi and Roughgarden, *A Myersonian Framework for Optimal Liquidity Provision in Automated Market Makers* | Cited for the LVR closed form | Wrong paper; it contains no LVR result | Keep only for claims actually supported by its Bayesian liquidity-provision model |
| Milionis, Moallemi, Roughgarden and Zhang, *Automated Market Making and Loss-Versus-Rebalancing* | Corrected bibliography entry | Correct source identified, but the PDF/text was absent from the saved corpus when this audit opened | Retrieve, save, read in full, write card and verify the equation location |
| Flandreau and Jobst, *The Empirics of International Currencies* | Working-paper text used while prose also referred to the published article | Extracted table columns are scrambled and the version mapping is not closed | Verify the cited number and interpretation against the exact published version; record both versions separately |
| Fourteen JFE venue exemplars | “One independent reader each; full detail in agent output” | No durable paper cards; individual substantive and venue readings cannot be audited | Re-read each full text and complete both scientific and venue axes |
| Nine-paper architecture subset in `docs/paper-spine.md` | “Read first-hand” | Several paper-specific checks are durable, but the denominator does not reconcile with the fourteen-paper corpus | Map the nine papers into the fourteen-paper ledger or document why they are a separate corpus |

## Paper cards

Cards are added one paper at a time below. No aggregate venue statement is final unless every paper in its denominator has a completed card.

The fourteen required venue-card identifiers are `venue:bolton-kacperczyk-carbon`, `venue:carletti-banks-patient-lenders`, `venue:chang-ripples-into-waves`, `venue:cong-li-wang-token-platform`, `venue:diamond-hu-rajan-liquidity-pledgeability`, `venue:eren-malamud-dominant-currency-debt`, `venue:graham-corporate-culture`, `venue:hajda-nikolov-product-market`, `venue:hinzen-bitcoin-adoption`, `venue:huang-constrained-liquidity-fx`, `venue:li-ye-zheng-refusing-best-price`, `venue:makarov-schoar-crypto-arbitrage`, `venue:mayer-financing-breakthroughs`, and `venue:pastor-sustainable-investing`.

Each completed card starts with a level-three heading containing its bibliography key or venue identifier. The executable schema requires `Status`, `Roles`, `Source`, `Version`, `Uses`, `Scientific`, `Structure`, `Depth`, `Breadth`, `Optics`, `Locations`, `Implication`, `First reader`, and `Independent`. `Locations` records exact page, section, table or equation evidence; `Implication` states what the paper should preserve, change or decline on the five axes. `Status: claim-verified` is required for cited sources; `Status: full-text-read` is sufficient for venue-only exemplars. A card with `central` among its roles requires `Independent: complete`.

# Finance-talk venue and deck exemplars

**Status:** Current deck-craft review guide. This record is a canonical agent route for presentation structure and pacing, not scientific evidence and not a source for empirical values. The external deck PDFs read in the original pass were not retained in this repository, so the observations below are durable review notes but are not independently re-verifiable from the current checkout. Any new claim about a source deck must record and retain its source route before this guide is amended.

Use only for pacing, motivation, layout and appendix calibration. Scientific claims and paper-level venue calibration remain governed by [`literature/audit.md`](../../audit.md).

## Rhetorical grammar

The audience-facing unit is a complete claim, not an approved vocabulary item. A strong finance slide normally makes the economic actor, quantity or event the subject, states the relationship with an active verb, and places a substantive condition beside the result when it changes interpretation. Provenance, workflow and review status remain in source comments. Titles and body text should say what happened economically; phrases that make `the evidence`, `the comparison`, `the design` or `the framework` narrate the presentation require a whole-thought rewrite.

Review each changed slide for subject, verb, result, condition and handoff to the next slide. Abstract-noun stacks, mechanically balanced taxonomies and meta-signposting can pass a word list while still sounding synthetic. Use this structural review first and the executable vocabulary scan only as a final alarm.

## Real decks actually retrieved and read

- **"Who Wins Ethereum Block Building Auctions and Why?"** (Sui, Öz, Thiery), Crypto-Market Microstructure session, 2025 ASSA/AFA meeting. 24 slides for a ~15-20 min talk within a multi-paper session. Dark modern theme, one chart/plot per slide at ~70% of slide area, 2-4 line assertion-style titles doing the argumentative work, minimal bullets, no dense equations or regression tables on-slide. A deliberately blank joke slide for an omitted proprietary-data point. Ends with a thank-you + QR-to-paper slide.
- **"Asymmetric Information Risk in FX Markets"** (Ranaldo & Somogyi), presented AFA 2019 Atlanta, published JFE 2021. Slide deck (48 unique slides after collapsing Beamer overlay duplication) recovered from a later webinar re-presentation, structurally representative of the AFA talk. Classic Beamer template, explicit outline slide, "Questions?" divider slides as pacing breathers between sections, text-dense literature-review slide (~10 citations), raw VAR equations shown unsimplified, robustness tables pasted in verbatim from the paper. **Nearly half the deck (slides 27-48 of 48) is appendix material** built to defend against audience questions, not to be walked through live.
- **Kent Daniel's discussant-slide archive** (Columbia GSB) — three fully read: a 2015 AFA currency-betas discussion (30 slides), a 2023 SFS Cavalcade liquidity discussion (19 slides), a 2011 NBER bond-liquidity discussion (46 slides). Consistent structural skeleton across all three: title slide (paper/authors/discussant/venue/date) → 3-5 item outline → content under a persistent section-breadcrumb header → "Conclusions and Suggestions" → full References slide(s). Heavy Beamer progressive-reveal (inflates raw page count relative to distinct visual slides audiences actually see). One idea per slide; rarely more than 4-5 short bullet lines; real empirical exhibits (charts, regression tables reproduced with discussant annotations) rather than decorative graphics. Pacing: roughly 1.5-2 minutes per distinct visual slide once overlay-duplicates are discounted — a 19-slide deck maps to a ~10-min discussant slot, a 30-46 slide deck to a ~15-20 min slot.
- **Eric Budish, "The Case for Frequent Batch Auctions,"** NBER Market Design @25 Conference (2023) — dense Beamer overlay build (~100 raw PDF page-objects), consistent with the pattern above once overlays are collapsed.

## Confirmed real programs/sessions (paper-level detail, slides not always posted)

- WFA 2024 official program (65pp, fully read): sessions directly on-topic include "Currency Risk Premia," "Dealers and Market Functioning" (Duffie et al. on Treasury dealer capacity), "Traders and Algorithms" (incl. "Learning from DeFi: Would Automated Market Makers Improve Equity Trading?" — Malinova & Park), "Money Markets and Liquidity Dynamics," "International Finance."
- AFA 2022 program with timing confirmed: "Liquidity" (4 papers, 2hr), "Over the Counter Markets" (4 papers, 2hr), "Market Microstructure: Trading on Information" (4 papers, 2hr) — implies ~25-30 min per paper (15-18 min presenter + 7-10 min discussant + floor Q&A) at these venues, the closest real analogue to a single compressed invited talk.

## Gaps, stated plainly rather than papered over

- WFA does not appear to post a public video archive the way AFA does.
- NBER conference pages link to papers, not presenter slide decks, as a rule (confirmed via a 2013 NBER Market Microstructure program negative-control check).
- No recording could actually be listened to in the original pass — pacing conclusions above are inferred from program structure and session timing, not from watching a talk. **The Microstructure Exchange** (microstructure.exchange, YouTube channel with individual market-microstructure seminar talks) was flagged as a possible source if verified minute-by-minute delivery pacing is needed — its ~45–60 minute open-floor format is more useful for verbal register than compressed pacing.

## Takeaways for deck drafting

1. Two legitimate house styles coexist even within AFA/NBER-caliber talks: a dense, mostly-visual, minimal-text style (crypto/microstructure-adjacent) and a classical Beamer style (verbatim tables/equations, heavy appendix). Given the target deck sits at the intersection (DeFi data, finance-microstructure audience aspiration), either is defensible — lean toward the classical Beamer style given the finance-journal target and Nanyang's mixed audience, but keep the visual discipline (one idea dominating each slide) from the crypto-talk example.
2. Appendix-as-defense is a real, load-bearing structural pattern, not a nice-to-have — budget roughly as much appendix material as core content when the question set warrants it.
3. Section-break pacing markers between the 4-5 major parts of a ~20-minute talk are standard, not filler.
4. References get their own dense slide(s) at the very end — the one place these decks abandon low density, since it's reference material, not spoken content.

## Conclusion slides: retained raw evidence

The final slide is reviewed as an economic ending, separately from the deck's result slides. Two source decks are retained as raw text in this checkout. Brunnermeier and Pedersen close by compressing each empirical result into its mechanism and end with the joint movement of market liquidity and funding conditions (`literature/text/2009-BrunnermeierPedersen2009LiquiditySlides-supplement-market-liquidity-and-funding-liquidity-slides.txt`, lines 1828--1865). Liu, Makarov, and Schoar move from Terra's subsidy and fragility to run amplification and investor losses, then end on the distributional implication that open access does not put investors on equal footing (`literature/text/2023-LiuMakarovSchoar2023TerraPresentation-supplement-riksbank-presentation.txt`, lines 217--230). Both endings state what the evidence changes economically. Neither ends on an unresolved test, data requirement, or workflow status.

For this deck, the last slide must synthesize the route findings at their admitted strength, lift them to the paper's market-formation implication, and finish on that implication. A bounded unresolved mechanism belongs before the final line or on the preceding slide. Whenever the findings change, review the close again against these retained passages; do not inherit approval from an older result generation.

# Historical Nanyang pipeline corpus manifest

**Status:** Historical supporting digest from the 2026-08-04 Nanyang pipeline. It is retained beside the literature corpus for provenance and possible source discovery, but it is not current citation, claim, venue, or workflow authority. Use [`literature/source-admission.json`](../source-admission.json), [`literature/vehicle-currencies.bib`](../vehicle-currencies.bib), and [`docs/literature-audit.md`](../../docs/literature-audit.md) for current decisions.

Pointers only. No interpretive synthesis here — Phase 1 does the independent-read source-fidelity work on whichever of these a candidate framing actually leans on.

## Co-author papers (Kathy Yuan, Emre Ozdenoren)

Yuan and Ozdenoren are long-standing co-authors (since 2008); nearly all of Ozdenoren's finance-relevant published work is joint with Yuan. His solo output (auction theory, ambiguity/compound lotteries, industrial organization) is off-topic and excluded.

- **Goldstein, Ozdenoren & Yuan (2011), "Learning and Complementarities: Implications for Speculative Attacks," Review of Economic Studies 78(1), 263-292.** Global-games model where speculator order flow reveals information to a central bank and shapes its policy; the information channel creates a learning-induced coordination motive generating large currency attacks. Closest published template for a vehicle-currency identification strategy built on information aggregation and multiple equilibria.
- **Ozdenoren, Yuan & Zhang (2023), "Dynamic Asset-Backed Security Design," Review of Economic Studies 90(6), 3282-3314.** Adverse selection endogenous to a collateral asset's price: higher price lowers adverse selection, permits more funding, raises value further (self-fulfilling multiplicity), resolved by an optimal security-design result implementable as a repo contract. Direct academic predecessor of the same team's unpublished working paper **Chiu, Ozdenoren, Yuan & Zhang, "On the Fragility of DeFi Lending" (Bank of Canada SWP 23-14, 2023)** — confirmed still unpublished, not journal-appeared, flagged as background/mechanism precedent only, not a benchmark comparator.
- **Yuan (2005, solo), "The Liquidity Service of Benchmark Securities," Journal of the European Economic Association 3(5), 1156-1180.** A benchmark security lets heterogeneously-informed investors decompose systematic vs. idiosyncratic risk; investors informed about systematic risk trade it exclusively via the benchmark, raising liquidity and price informativeness economy-wide. **Conceptually the closest precedent to "vehicle currency" of anything found** — a benchmark asset concentrating trading of a common risk factor is structurally the same idea as a vehicle currency intermediating cross-pair liquidity.
- **Denbee, Julliard, Li & Yuan (2021), "Network Risk and Key Players: A Structural Analysis of Interbank Liquidity," Journal of Financial Economics 141(3), 831-859.** Structural model estimating a "liquidity multiplier" in an interbank payment network; strategic complements/substitutes in reserve-holding depending on payment velocity vs. opportunity cost of liquidity. Identification: network topology explains cross-sectional heterogeneity, complements/substitutes regime shifts explain time-series variation. Template if the paper goes structural/network rather than pure reduced-form.
- **Ozdenoren & Yuan (2008), "Feedback Effects and Asset Prices," Journal of Finance 63(4), 1939-1975.** Price-to-fundamentals feedback loop modeled via global games; stronger feedback strength raises excess volatility. Template for how coordinated LP behavior in a vehicle-currency pool could itself move the fundamental traders are pricing.
- **Goldstein, Ozdenoren & Yuan (2013), "Trading Frenzies and Their Impact on Real Investment," Journal of Financial Economics 109(2), 566-582.** Capital providers learn from price when allocating capital; coordination among speculators can help or hurt price informativeness depending on parameters. Template for herding/informed-LP dynamics.

*Not yet done: a full sweep of Yuan's ~30+ paper bibliography beyond these 6 — this is the "4-6 most relevant" cut, not exhaustive. Expand only if Phase 1/2 finds a specific gap these don't cover.*

## Olga Klein (Warwick Business School — being invited by Kathy)

Already confirmed earlier in this project from the local literature cache:
- **Klein, Kozhan, Viswanath-Natraj & Wang (2026), "Informed Liquidity Provision on Decentralized Exchanges."** LP price discovery/adverse selection on DEXs, ETH-USDC low-fee pool — directly on-topic for the LP-informedness mechanism.
- **Caparros, Chaudhary & Klein (2024), "Blockchain Scaling and Liquidity Concentration on Decentralized Exchanges."** Gas costs, LP repositioning, concentration, slippage.
- **Klein & Song (2021), "Commonality in Intraday Liquidity and Multilateral Trading Facilities."** Liquidity commonality across venues — TradFi precedent for a common-liquidity-factor argument.

## Anchor literature (already in `literature/vehicle-currencies.bib` and `literature/papers/`)

Full list and classification already exists in `docs/research-questions-and-empirical-design.md` (lines 17-34) — Krugman (1980), Dowd & Greenaway (1993), Grossman & Miller (1988), Ho & Stoll (1981), Brunnermeier & Pedersen (2009), Gopinath & Stein (2021), Chen & Duffie (2021), Somogyi (2026), Lehar & Parlour (2024), Chordia/Roll/Subrahmanyam (2000), Coughenour & Saad (2004), Comerton-Forde et al. (2010), Hendershott/Jones/Menkveld (2011), Anand & Venkataraman (2016), Clark-Joseph/Ye/Zi (2017), Bessembinder/Hao/Zheng (2020), Li/Wang/Ye (2021), Heimbach/Pahari/Schertenleib (2024). Not re-derived here; Phase 1 does the independent-read cross-check on whichever of these a candidate framing leans on. That doc's own RQ1-5 *structure* is not binding — only its literature classification is being reused as a pointer.

## Golden-benchmark structural comparators (published, non-topical — chosen for scope/depth/structure precedent, not subject-matter overlap)

All confirmed published (DOI resolves to a firm publisher record, not a working paper) as of 2026-08-04. Tagged by genre/empirical archetype so a mismatch is visible before it drives downstream scoring.

| Paper | Venue | Genre / archetype | Why it's a useful comparator |
|---|---|---|---|
| Ranaldo & Santucci de Magistris (2022), "Liquidity in the global currency market," JFE 146(3):859-883 | JFE | FX market microstructure; new measure + validation, no formal model | Best fit if the DVC contribution is centrally "a new measure (route/vehicle-share metric) + validation + determinants," not model-driven |
| Lu, Malliaris & Qin (2023), "Heterogeneous liquidity providers and night-minus-day return predictability," JFE 148(3):175-200 | JFE | Equity microstructure; light model + calibrated comparative-statics empirics | Best fit if a light theoretical model sits alongside the empirics, with fewer but model-disciplined headline tables |
| He, Khorrami & Song (2022), "Commonality in Credit Spread Changes: Dealer Inventory and Intermediary Distress," RFS 35(10):4630-4673 | RFS | Corporate bond liquidity commonality; intermediary-capacity-driven, clean IV identification | Closest mechanism match to the flight-to-dominance/stress-rotation thesis — commonality-in-liquidity explained by intermediary capacity, not just common demand |
| Eisfeldt, Herskovic, Rajan & Siriwardane (2023), "OTC Intermediaries," RFS 36(2):615-677 | RFS | CDS market; core-periphery network model + counterfactual dealer-exit simulation | Maps directly onto architecture/liquidity-provider-exit questions (V3/V4 architecture shocks) |
| Bräuning & Stein, "The Effect of Primary Dealer Constraints on Intermediation in the Treasury Market," RFS (advance article, DOI assigned, pagination pending as of 2026-08-04) | RFS | Treasury market; capacity-constraint DiD | Closest structural parallel to a protocol-capacity/architecture-change mechanism; cite as "forthcoming," pagination not final |

**DeFi-native proof points** (confirms a DeFi/on-chain transaction-level empirical paper can clear these venues' scope/depth bar — not chosen for structural precedent, chosen as an existence check):
- **Barbon & Ranaldo, "On the Quality of Cryptocurrency Markets: Centralized vs. Decentralized Exchanges," Management Science (Articles in Advance, DOI 10.1287/mnsc.2024.07703).** Confirmed accepted/published, pagination pending. Transaction-level CEX-vs-DEX comparison, gas-fee causal effects, arbitrage-deviation persistence — closest DeFi-native precedent to DVC found in any of the four target venues.
- **Ranaldo, Viswanath-Natraj & Wang, "Blockchain Currency Markets," JFQA (First View, dated April 2026).** Confirmed published (First View). EURC/USDC Uniswap V3 data matched against CLS FX benchmarks, regression + SVAR + event-study toolkit. Strongest direct existence proof that a DeFi-transaction-level paper clears JFQA's bar.
- **Lehar & Parlour, "Decentralized Exchange: The Uniswap Automated Market Maker," Journal of Finance 80:321-374 (2025).** Outside the four requested venues but the single clearest cross-journal existence proof: full population of 95.8M Uniswap interactions vs. a matched centralized order book. Already in the local literature cache as a theory+empirics comparator; worth citing as reviewer-recognizable precedent regardless of venue.

**Explicitly not usable as "published" comparators (checked, excluded):** Lehar, Parlour & Zoican's RFS DEX-liquidity-fragmentation paper is R&R, not published; Chiu/Ozdenoren/Yuan/Zhang's DeFi-lending paper is a Bank of Canada working paper, not journal-published.

## Repo inventory (what already exists)

- Historical `slides/nanyang_vehicle_currencies.tex` — deleted after the live deck replaced it; recoverable from git history only and not binding on current deck work.
- `docs/research-questions-and-empirical-design.md` — the RQ1-5 redesign doc (2026-07-17), execution hold never lifted. Its literature classification (above) is reused; its RQ-numbered structure is explicitly not binding per Java's instruction.
- `output/core_empirical_rq_results.md` and the retired RQ1-7 memos now under `docs/retired-rq1-7-*.md` are pre-redesign artifacts. They are not current findings or execution authority; current claims come only through the findings freeze and registered evidence chain.
- Reference repo `defi-dominant-currency` (ddc) — deeper historical data engine and 115G raw data layer; frozen, reference/data-engine only per the project's locked decisions.

## Historical next step

The original Phase 1 source-fidelity cross-check is preserved in [`legacy-nbc-source-fidelity.md`](legacy-nbc-source-fidelity.md). Current work follows the live literature gate instead.

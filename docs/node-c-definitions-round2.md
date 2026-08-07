# Node C round 2: what the target literature formalises, and which of our definitions it can engage with

Node C output, 2026-08-06, the first reopening since the early pass. Trigger: `docs/research-workflow.md` section 6, the note beginning "C IS THE HIGHEST-LEVERAGE NODE AND IT WAS THE ONE THAT COULD NOT LEARN". The charge was to read the corpus for how the international-currency and market-microstructure literatures FORMALISE the objects this paper measures, and to say whether our definitions are the ones that literature can engage with.

The corpus is `literature/text/*.txt`, 53 papers over 1,974 pages. Every count below was produced by grepping that extract. No PDF was opened.

---

## 0. Two corpus facts that change how the rest of this file should be read

**0.1 Grep on this corpus silently returns zero unless you pass `-a`.** Every one of the 53 extracts contains bytes that make BSD grep classify the file as binary, and macOS grep then suppresses matches without saying so. A search for `vehicle` in `2026-Somogyi2026DollarDominanceFX` returns nothing; the same search with `-a` returns 85 hits. Any prior sweep of this corpus that reported a null and did not use `-a` reported a false null. A second trap sits underneath: the extracts hyphenate across line breaks using at least five distinct Unicode hyphen codepoints, so `grep "vehicle currency"` misses Krugman's own abstract, which reads `becoming "vehi- cles" through which transactions between other currencies were made`. The searches in this file ran against a de-hyphenated, newline-collapsed copy and used `-a` throughout.

**0.2 Three of the 53 files are not the paper the index names, and one of them is load-bearing.** `1989-KiyotakiWright1989MoneyMedium-on-money-as-a-medium-of-exchange.txt`, 108 pages and the largest single item in the corpus, contains zero occurrences of `Kiyotaki`, zero of `double coincidence`, zero of `medium of exchange` and zero of `barter`. Its first page reads `2026 CATALOG` and its content is a University of Chicago Press book catalogue. `1981-HoStoll1981OptimalDealer` (45 pages) and `1985-GlostenMilgrom1985BidAsk` (31 pages) extracted to zero characters of body text and are scanned images with no OCR layer. That is 184 pages, 9.3% of the stated corpus, which is not what the index says it is. The search-theoretic strand survives the loss because `2005-LagosWright2005Unified` is present and correct, but the workflow note that grounds our definitions in "Kiyotaki and Wright" is grounding them in a file that does not contain them.

**0.3 Flandreau and Jobst is not in the corpus.** `grep -ari flandreau literature/text/` returns nothing, including from every reference list. The definitional decision to measure the vehicle role as betweenness centrality is justified in the header of `scripts/build_vehicle_centrality.py` and again in `docs/finding-fragmentation-not-succession.md` by the sentence "Flandreau and Jobst (2009) model currency use as a network with externalities". Node C cannot check that sentence against anything in this repository. It is a citation carrying a definitional decision, and it is uncheckable here. Either the paper is added to the corpus and read, or the justification is withdrawn and the definition has to stand on something we can see.

---

## 1. Vehicle status and vehicle dominance

**Correction after the 2026-08-07 semantic audit.** Vehicle status is binary: an asset is used as an intermediary on a route or it is not. Vehicle dominance is continuous: it is the degree to which an asset holds that role. The raw intermediary share measures dominance within vehicle use; the excess-use ratio measures normalized dominance after netting out endpoint demand. The paper's question is what makes a vehicle currency dominant, not what makes an asset a vehicle currency.

**Current definition.** Two live measures. A volume share of intermediation episodes, and, since commit `d0429b7`, betweenness centrality by token and day in `data/processed/vehicle_centrality.parquet`, computed on an undirected daily graph with an edge wherever a direct pool joined two tokens carrying at least $1,000, with source-node sampling at k=150. `docs/finding-fragmentation-not-succession.md` makes betweenness the primary measure and the volume share the proxy.

**What the literature does. Zero of 53 corpus papers use any graph centrality statistic for currency use.** `grep -aci` over the de-hyphenated corpus returns 0 files for `centrality`, 0 for `betweenness`, 0 for `eigenvector`, 0 for `closeness centrality`, and 0 for `shortest path`. The word `network structure` appears in 2 files, both about blockchain topology and neither about currency use. The eight corpus papers that operationalise a currency's international role all use the same shape of statistic, and it is not a graph statistic. It is a use share divided by, or netted against, a benchmark of fundamental demand.

Krugman 1980 states it in words at journal page 519: the vehicle "enters into more transactions than A's role in world payments would by itself justify", and at page 521 he tabulates the mechanism, "Each currency market has a 'secure' volume arising from counterclockwise payments: the volume is then increased above this level if one of the currencies traded serves as a vehicle." Extent is the increase above the secure volume, which is a residual.

Gopinath and Stein 2021 give the ratio form directly: "the dollar's share as an invoicing currency for imported goods is approximately 4.7 times the share of U.S. goods in imports. This stands in sharp contrast to the euro, where in the same sample the euro invoicing share and the share of imports coming from countries using the euro are much closer to one another, so that the corresponding multiple is only 1.2." The statistic is dimensionless, it is comparable across currencies, and it equals one when a currency's use is exactly proportional to its fundamental demand.

Somogyi 2026, the corpus paper closest to this one in object and the most recent, builds the same residual with an identification strategy: "my measure of vehicle currency trading activity is the difference between interdealer volume and my implied measure of fundamental trading demand based on nonoverlapping holidays", giving "on average 13% of the daily trading volume in dollar currency pairs (around $8 billion per day)" and 25% to 38% for the largest pairs.

Amiti, Itskhoki and Konings 2022 run the leave-one-out version: "If we drop the United States as an export destination, the share of the dollar use in Belgian ex-EU export invoicing only falls from 51% to 44%", and they say explicitly why a raw share will not do, that "to gauge the relative importance of the U.S. dollar, a more informative benchmark may be the Belgian trade share with dollarized and dollar-pegged countries."

**Do they match. No, and the mismatch is a tautology.** Betweenness on our graph is a restatement of degree, and degree is the property by which `src/ddvc/asset_types.py` defines the native asset ("Thickest incumbent pairing network"). Measured on the committed panel across 18 days:

| check | value |
|---|---|
| Spearman correlation, WETH betweenness share against WETH degree share, across days | **+0.958** |
| Spearman correlation, betweenness HHI against degree HHI, across days | **+0.948** |
| Days on which the betweenness leader is also the degree leader | **18 of 18** |
| Share of nodes with exactly zero betweenness, per day | 87.8% to 96.8% |

So the committed sentence "By network centrality the role fragments and never changes hands. The native asset leads in every year" is, to a rank correlation of 0.95, the sentence "WETH has the most pool listings, and the share of listings that are WETH listings fell." The native asset was defined as the asset with the most listings. This is the same failure that Node I caught in "native intermediation is cheaper", one layer up and unnoticed because the statistic looks unfamiliar.

**Is betweenness the right graph statistic anyway.** The question was whether eigenvector, closeness, or current-flow betweenness would be better given that routing is a flow problem. Computed exactly on the giant component of two real days:

| day | statistic | leader | leader share | HHI | Spearman vs degree |
|---|---|---|---|---|---|
| 2022-03-27 | shortest-path betweenness | WETH | 0.817 | 0.676 | +0.606 |
| 2022-03-27 | current-flow betweenness | WETH | 0.704 | 0.515 | +0.615 |
| 2022-03-27 | eigenvector | WETH | 0.275 | 0.160 | +0.303 |
| 2022-03-27 | closeness | WETH | 0.001 | 0.001 | +0.684 |
| 2026-03-06 | shortest-path betweenness | WETH | 0.558 | 0.346 | +0.752 |
| 2026-03-06 | current-flow betweenness | WETH | 0.441 | 0.262 | +0.700 |
| 2026-03-06 | eigenvector | **USDC** | 0.298 | 0.202 | +0.361 |
| 2026-03-06 | closeness | WETH | 0.002 | 0.001 | +0.391 |

Current-flow betweenness is the theoretically correct object for a routing problem and it changes nothing: same leader on both days, same qualitative fall, and a correlation with degree of +0.62 and +0.70, which is at or above shortest-path betweenness's. Closeness is degenerate on a scale-free graph and carries no concentration information at all. Eigenvector centrality is the one that moves, and it moves the headline: on 2026-03-06 the eigenvector top three are USDC 0.664, USDT 0.569, WETH 0.465, so the native asset is third and the role has changed hands. **The claim "fragments without changing hands" is a fact about which of four graph statistics was picked, and none of the four has corpus support.**

**What the definition should become.** Vehicle dominance is the continuous intermediary-use share. Normalized vehicle dominance is an asset's share of intermediate legs divided by its share of endpoint legs, per period, value-weighted. That normalization is Gopinath and Stein's multiple, Krugman's excess over secure volume, and Somogyi's residual, computed the way this data allows. `data/unified/*.parquet` already carries `tin_role` and `tout_role` with values `source`, `intermediate` and `sink`, so no new reconstruction is needed. Computed now on `single` and `coherent` routes:

| day | asset | intermediate share | endpoint share | **vehicle ratio** |
|---|---|---|---|---|
| 2020-08-04 | WETH | 0.717 | 0.415 | **1.73** |
| 2020-08-04 | USDT | 0.096 | 0.035 | **2.74** |
| 2020-08-04 | USDC | 0.129 | 0.056 | **2.31** |
| 2022-03-27 | WETH | 0.373 | 0.374 | **1.00** |
| 2022-03-27 | USDC | 0.303 | 0.210 | **1.45** |
| 2026-03-06 | USDT | 0.287 | 0.241 | **1.19** |
| 2026-03-06 | USDC | 0.286 | 0.287 | **0.99** |
| 2026-03-06 | WETH | 0.204 | 0.218 | **0.93** |

This is a third answer, and it is the one the target literature can engage with. WETH's excess vehicle role is gone by 2022, when its intermediation is exactly proportional to its endpoint demand, and by 2026 it is below one, meaning WETH is used as an intermediary less than its own endpoint demand would predict. USDT is the only major asset above one in 2026, at a multiple of 1.19 against the dollar's 4.7 in Gopinath and Stein's trade data. The ratio is not tautological because it nets out precisely the thick endpoint network by which the native type is defined, so an asset cannot score high merely by being widely listed.

The ratio also works as a data screen for free. On 2026-03-06 the token `0xbffa38…`, symbol "The Glitch", carries 13.8% of all intermediation value with an endpoint share of exactly zero. A vehicle with no endpoint demand at all is not an economic object, and the volume share hides it while the ratio makes it undefined and therefore visible. Two more meme tokens sit in the same position. The round-trip filter is not catching this and the route panel should be screened on it before any extent figure is quoted.

**Cost to switch.** The panel builder is roughly thirty lines against `data/unified/` using columns that already exist, and it needs no graph library. Betweenness stays as a robustness exhibit with its degree correlation reported alongside it, which is what the corpus's silence licenses: an unfamiliar statistic reported as a check, never as the primary.

**What this invalidates.** The primary table of `docs/finding-fragmentation-not-succession.md`, the whole `centrality *` column block, and the sentence "By network centrality the role fragments and never changes hands." Also the paragraph headed "What the definition rests on" in that file, both because the Flandreau and Jobst justification is uncheckable here and because the two-measure disagreement it presents as the finding is a four-measure disagreement in which the fourth measure is the one with corpus support and reverses the conclusion.

---

## 2. Cost domination and route regret

**Correction after the 2026-08-07 semantic audit.** This section had conflated currency dominance with route cost domination. Somogyi's triplet-period object is defined from vehicle-use volumes and fundamental demand, so it supports section 1's continuous dominance measure. It does not license calling a route's cost disadvantage `dominance`. The route-level binary is now `cost-dominated`; the signed continuous object is route regret or cost gap. These measures discipline mechanisms for vehicle dominance but do not define it.

**Current definition.** A binary at the route level, the best direct route returning more than the best two-leg route at the same reconstructed state. Node I objected that a coefficient on a binary at an absorbed threshold is a shift in a CDF and not a cost, the objection was accepted in `docs/paper-spine.md` section 2.5, and the project moved to a continuous gap in basis points, currently reported as -25.3 bps with a standard error of 11.4.

**What the literature does.** Krugman supports reporting both the binary direct-versus-indirect cost boundary and the continuous signed cost gap. That support is for route economics, not for naming either object vehicle dominance.

Krugman 1980 page 519 states the binary as a parameter condition, "We have labeled the currencies so that t_ab and t_ca are both less than t_bc, and this insures the alphas will be used as a vehicle", and then splits the outcome into two regimes at exactly our threshold: partial indirect exchange when `(1-t_ab)(1-t_ca) < (1-t_bc)`, meaning indirect is more costly than direct, and total indirect exchange when the inequality reverses. Our binary is Krugman's regime boundary, so the form is right.

Krugman also names the continuous object and it is ours. His `D`, which he calls the clockwisdom, is the deviation from triangular arbitrage, and in the partial-indirect equilibrium it equals `(1-t_bc)/((1-t_ab)(1-t_ca))`, which is the log gap between the direct route and the two-leg route. That is our basis-point gap with a different name.

Somogyi 2026 is decisive for section 1, not for the cost object here. Definition 1 classifies a triplet as dollar-dominated from the relative volumes of the two dollar pairs, the nondollar pair, and excess trading over fundamental demand. Equation (10) reports a continuous triplet-period measure of that same vehicle-use construct. It is evidence that currency dominance belongs on the volume/excess-use axis and evidence against the old conflation with a signed route-cost gap.

**Do they match. The cost form matches Krugman's boundary; the old name does not match the currency-use literature.** The route is the correct primitive for asking whether an executed path left output on the table at its own pre-trade state. A pair-candidate-period cell is the correct aggregation only for a persistence or transition estimand. The matched sample's 1.9% coverage and its inversion toward large stable-intermediated routes remain selection problems, but Somogyi's triplet unit does not solve them by relabeling the cost gap.

**What the definition should become.** Keep the route-level binary cost-domination indicator and continuous cost gap as measurement primitives. Aggregate them to **(pair, candidate vehicle, period)** only when the estimand concerns persistence or transition at that level. Somogyi's triplet-period unit motivates the dominance measure in section 1, not the aggregation of a cost gap.

**Cost to switch, and why it is a benefit and not only a cost.** The aggregation is a groupby on a panel we already have. The gain is that the selection problem which forced the 27.2% reweighting attaches to the route level and mostly dissolves at the triplet level, because a triplet is either priced in a period or it is not, and coverage becomes a stated property of the panel instead of a composition bias inside it. The gain also includes comparability: a referee who knows Somogyi can read our number against his.

**What this invalidates.** Nothing yet measured is wrong, but the headline changes shape. "27.2% of realised multi-leg routing was strictly dominated" becomes a statement about a share of triplet-periods, which is a different denominator and will produce a different number. The 41.3% raw matched mean and the 70.1% enumeration bound are both route-level and become diagnostics of the measurement instead of results.

---

## 3. The asset types

**Current definition.** `native`, `staked_native`, `stable`, `imported`, `other` in `src/ddvc/asset_types.py`, with TradFi analogues asserted in the module docstring.

**What the literature does.** The corpus cuts crypto assets on two dimensions and neither is the one we use.

The top-level cut is stablecoin against non-stablecoin. Makarov and Schoar 2022 section 3.2: "Non-stablecoins constitute a large and diverse group", isolating first "coins that have no other function than being a cryptocurrency, either used for transaction purposes or as a store value... positioned as the new 'gold' — a digital store of value." Gorton and Zhang 2023 make the same cut in law-review terms: cryptocurrencies "can be divided into two categories. The first includes cryptocurrencies that are not backed by anything, like Bitcoin and Ethereum. These are so-called 'fiat cryptocurrencies.'"

The second cut, and the one the corpus spends the most pages on, is **backing regime inside the stable category**. Catalini, de Gortari and Shah 2022 split stablecoins into fiat-backed, crypto-asset-backed, and those "backed partially or fully by their own investment token [which] only rely on their own algorithms and smart contracts", and state the consequence: "unlike stablecoins backed by fiat assets or cryptocurrencies, the true solvency of an algorithmic coin is linked to the public's confidence in the coin, allowing death spirals to materialize even in unstressed conditions." Lyons and Viswanath-Natraj 2023 build their whole result on that line: "in contrast to dollar-backed stablecoins, there is no clear arbitrage mechanism to restore prices when TerraUSD is priced at a discount." Four corpus papers exist principally because backing regimes differ in behaviour: Uhlig 2022, Liu, Makarov and Schoar 2023, Anadu et al 2023 and Lyons and Viswanath-Natraj 2023.

Gorton and Zhang also supply the property that makes an asset usable as a vehicle at all, the no-questions-asked principle, "which requires that the money be accepted in a transaction without due diligence on its value... accepted at par." That is the concept our `stable` bucket is reaching for and it is not the same as low volatility.

**Do they match. Partly. The primary types survive, but `stable` needs a crossing attribute.** Fiat reserves include USDC, USDT, PYUSD, TUSD, USDP, GUSD, BUSD and USD1. LUSD, crvUSD, alUSD, DOLA and MIM are on-chain collateralized; sUSD is synthetic; USDe and sUSDe are synthetic delta-hedged; DAI changes regime when fiat-stablecoin and then real-world-asset collateral become admissible; USDS inherits the RWA-mixed regime; and FRAX changes from fractional-algorithmic to a transition toward full exogenous collateralization after its governance decision. The type also pools a yield-bearing wrapper, sUSDe, with a non-yield-bearing one, which changes what holding the vehicle costs and therefore feeds directly into section 5.3 of the spine. The corpus treats ignoring these distinctions as the error its own literature exists to correct.

`imported` survives and is well supported: Makarov and Schoar's "new 'gold' — a digital store of value" is exactly our stated analogue for WBTC and PAXG, in the corpus's own words.

`staked_native` survives as a separate type on corpus grounds we do not currently state. The relevant property is not the underlying exposure, it is that a staked derivative fails the no-questions-asked test because accepting it requires due diligence on the redemption queue.

**Implemented definition.** Keep the five types as the primary axis and cross `stable` with dated composition regimes: `fiat_reserve`, `on_chain_collateralized`, `mixed_with_fiat_stablecoin`, `mixed_including_rwa`, `synthetic`, `fractional_algorithmic`, `transition_to_full_exogenous_collateralization` and `non_usd`. Report primary results at type level and stable results once at backing level, normalized inside the stable class.

**Cost to switch. Low in code and material in interpretation.** The full 2,277-day vehicle-extent rebuild shows fiat reserves carrying 91.11% of stable intermediary value in 2024, 95.82% in 2025 and 96.84% in 2026, against endpoint-demand shares of 86.07%, 89.50% and 90.29%. RWA-mixed DAI/USDS falls from a within-stable excess-use ratio of 1.35 in 2021 to 0.22 in 2026. The native-to-stable transition is therefore increasingly a USDC/USDT result, not a result shared uniformly across stablecoin designs. Cells below 1% of either side, including the large non-USD ratios, remain diagnostics.

**What this invalidates.** The first static backing split and its `crypto_collateral` label are withdrawn. The top-level stable result survives, but any prose treating it as common to stablecoins does not. Every stable result needs the dated backing row, and the late-sample interpretation must name its concentration in the large fiat-reserve units.

---

## 4. Succession against fragmentation

**Current definition.** A Herfindahl index over vehicle shares plus the leader's identity, in `docs/finding-fragmentation-not-succession.md` and `scripts/build_vehicle_concentration.py`, with the rule stated as "a stable HHI with a changing leader is succession and a falling HHI with a stable leader is fragmentation."

**What the literature does. It does not use a Herfindahl.** `grep -aicE "herfindahl|HHI"` returns 3 files of 53, and all three are about something else: Klein and Song on venue concentration, Catalini on protocol concentration, Anadu on money-market-fund concentration. Zero international-currency papers in the corpus use one.

The corpus does have a standard for this, and it is a per-cell regime classification. Somogyi 2026 section 5.2.2: "Based on the empirical estimates of dollar dominance DD and on the three dominance conditions, I classify the 15 triplets in Figure 4 into three regions: (i) dollar dominance, (ii) **multiplicity**, and (iii) nondollar dominance." The middle region is defined as "triplets for which only one or two conditions are satisfied while the dollar is still the dominant currency. This supports the idea that the status quo of dollar dominance can potentially be scrutinised in triplets currently within the region of multiplicity." He then aggregates by counting: "12 out of 15 triplets of currency pairs lie either in the region of multiplicity or in that of dollar dominance. Six currency pair triplets lie in the region of multiplicity."

Mukhin 2022 supplies the succession object in the same shape. His Figure 3, "Transition from One Vehicle Currency to Another", is not a concentration index; it is an **ordering of which trade flows switch first**, numbered 1 to 3: US-to-small-economies first, then small economies with one another, then UK-to-small-economies. Dowd and Greenaway 1993 supply the threshold: with network benefit `b·ln(N)` and a fixed switching cost `s`, "it is better to switch currency 2 for currency 1 only if N2 < N1", and outcomes are labelled excess inertia or excess momentum in Farrell and Saloner's terms.

**Do they match. No, and the HHI is not merely non-standard, it is not identified for this question.** A Herfindahl over aggregate vehicle shares cannot separate the two worlds it is being asked to separate. HHI = 0.5 over two vehicles is produced both by a world where every pair splits its routing evenly between two vehicles, which is fragmentation, and by a world where half the pairs route entirely through vehicle A and the other half entirely through vehicle B, which is two coexisting monopolies and is not fragmentation at all. The aggregate share vector is the same in both. Only a per-pair leader assignment tells them apart, and that is exactly what Somogyi's regime classification and Mukhin's switching order are.

**What the definition should become.** Assign a regime label to every (pair, period) cell using vehicle-use shares and the normalized dominance conditions from section 1, taking three values: incumbent-dominant, multiplicity, challenger-dominant. Then report two statistics. The first is the count of cells in each regime by period, which is Somogyi's Figure 4 aggregated. The second is the switching order, meaning for the cells that changed leader, the distribution of switch dates by pair characteristic, which is Mukhin's Figure 3 made empirical. Succession is many cells switching leader with each cell staying concentrated. Fragmentation is cells moving into the multiplicity region and staying there.

**Cost to switch.** The pair-period panel is the same object section 2 already needs, so this is one additional labelling step on top of it. The current `build_vehicle_concentration.py` HHI can remain as a one-line descriptive statistic and stops being the instrument that answers the question.

**What this invalidates.** The reasoning of `docs/finding-fragmentation-not-succession.md`, though not necessarily its conclusion. The claimed identification, that HHI plus leader identity separates succession from fragmentation, does not hold, and the document should not claim it. Combined with section 1, the file needs rebuilding on the excess-use ratio and the per-cell regime label, and the direction its conclusion moves is open, because the excess-use ratio says WETH's vehicle role ended around 2022 while the betweenness measure says WETH led every year.

---

## 5. What counts as a route

**Current definition.** A reconstructed multi-leg path within one transaction, one coherent component being one route unit regardless of leg count, with round trips excluded at 12.7% of multi-leg routes by count and 21.7% by value on the median of 79 sampled days, 25.9% and 91.3% on 2025-12-06, the worst.

**What the literature does.** The exclusion of round trips is the best-supported definition in this file. Heimbach, Pahari and Schertenleib 2024 name cyclic arbitrage as one of the three canonical MEV types, "the most commonly observed and measured types of MEV on Ethereum are sandwich attacks, cyclic arbitrage, and liquidations", and treat it as extraction and not as user trading throughout. Daian et al 2020 establish the same category. A route whose first input equals its last output is a member of that category and not a payment.

Krugman's unit is the payment `P_ij` between two parties, resolved either directly or through one vehicle, which is our route unit exactly. Somogyi's measurement unit is the triplet-day, which is an aggregate of ours.

**Do they match. The primitive matches. The claim attached to it does not.** No corpus paper measures the vehicle role on individual routes. Krugman's route is a modelling primitive and his measured object is market volume; Somogyi's measured object is a triplet-day. Our route-level unit is finer than anything in the target literature, and section 2 already gives the reason that costs us: route-level matching selects on trade size and candidate type.

There is one gap the corpus exposes. Multi-leg is treated as equivalent to intermediated in our definition, but a two-leg route through an asset is a vehicle route only when a direct pool existed and was passed over. When no direct pool exists the two-leg route is the only route, which is Krugman's total indirect exchange, and it is a statement about the feasible set. Our current definition pools the forced case with the chosen case. Krugman keeps them apart at page 519 and calls them different equilibrium structures, and the distinction survives into `docs/finding-v1-forced-vehicle.md` under a different name without being carried into the route definition.

**What the definition should become.** Keep the route primitive unchanged. Add a required binary attribute to every multi-leg route, `direct_pool_existed`, and never report a vehicle-dominance or cost-regret figure that pools the two values of it. Aggregate to the (pair, candidate, period) cell only for estimands defined at that level.

**Cost to switch.** The attribute is a lookup against the same pool registry the counterfactual quoter already uses, so the cost is a join, not a rebuild. Reporting doubles in width for the affected tables.

**What this invalidates.** No measured number, but it splits several of them. Any figure combining forced and chosen intermediation is answering two questions at once, and the 2020 figures are the ones most exposed, because Uniswap v1's architecture forced the native asset into the middle of every route.

---

## 6. Tautology audit

Applied to every definition in this file, the test being whether the result could have come out otherwise given the definitions.

| Object | Tautological | Evidence |
|---|---|---|
| Betweenness centrality as vehicle extent | **Yes** | Rank correlation +0.958 with degree share, leader identical on 18 of 18 days, and the native type is defined by degree |
| Volume share as vehicle extent | **Nearly** | Krugman's own model sets `t = F(V)` with `F' < 0` at page 520, so cost falling in volume is the model's assumption and regressing cost on a volume share recovers `F` |
| Excess-use ratio as vehicle extent | No | Nets out endpoint demand, so an asset cannot score high by being widely listed; WETH's ratio falls below 1.0 by 2026 while its volume share stays second |
| Continuous route-cost gap | No | The gap can take either sign at any state and its sign is not implied by any type definition |
| Binary route cost domination | No, but underpowered | The threshold is a real regime boundary in Krugman, and the objection Node I raised is about the estimator and not the definition |
| Asset types with backing crossed in | No | Backing regime is an issuance fact and is not derived from any routing quantity |
| HHI plus leader identity for succession | Not tautological, not identified | Two different worlds produce the same share vector, so the statistic cannot answer the question it is assigned |
| Round-trip exclusion | No | Corpus-supported as an MEV category and defined on the transaction and not on any outcome |

The pattern worth naming: **both of this project's tautologies came from defining an object by the same primitive used to define the asset types.** The native type is defined by network thickness, so any measure of network thickness reproduces it. The escape is a benchmark, and the corpus has used one for forty-five years.

---

## 7. Summary of recommended changes

| Object | Verdict | Change | Invalidates |
|---|---|---|---|
| Vehicle status and dominance | **Replace** | Status is binary intermediary use; dominance is continuous intermediary share; normalized dominance is the excess-use ratio. Betweenness is demoted to a robustness exhibit reported with its degree correlation | The `centrality` columns and the "never changes hands" sentence in `docs/finding-fragmentation-not-succession.md` |
| Cost domination and regret | **Rename and separate** | Keep the route-level indicator and continuous signed cost gap; aggregate to pair-candidate-period only for a period-level persistence estimand | Invalidates using 27.2%, 41.3% or 70.1% as measures of vehicle dominance; they remain cost-friction diagnostics on their stated denominators |
| Asset types | **Keep, extend** | Add dated `backing` regimes crossing the `stable` type and normalize backing shares within stablecoins | Withdraws the static backing split; preserves the top-level transition while narrowing its interpretation to increasingly fiat-reserve intermediation |
| Succession against fragmentation | **Replace** | Per-cell three-region regime label plus switching order, after Somogyi and Mukhin | The identification argument in `docs/finding-fragmentation-not-succession.md` |
| What counts as a route | **Keep, split** | Add `direct_pool_existed` and never pool across it | Splits the 2020 figures, where the architecture forced the vehicle |

Two items are not definitional and are logged for whoever owns the corpus. The Kiyotaki and Wright extract is a book catalogue, Ho and Stoll and Glosten and Milgrom are un-OCRed images, and Flandreau and Jobst is absent while carrying a definitional decision in two committed files. Any sweep of this corpus that did not pass `-a` to grep produced false nulls, including possibly the four-lane prior-art sweep cited in `docs/paper-spine.md` section 2.1 as "returning zero".

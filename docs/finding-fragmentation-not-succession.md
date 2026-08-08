# The vehicle role fragments without changing hands, and the two measures disagree

> **THE CENTRALITY HALF IS COMPROMISED, corrected 2026-08-09 after the Krugman source audit.** Native status is the platform identity and must not be defined by pairing degree. The earlier circularity diagnosis was therefore wrong. The substantive fragility remains: the betweenness leader equals the degree leader on 15 of 15 sampled days, while eigenvector centrality reverses the ordering and puts the stable numéraire first. "Fragments without changing hands" is partly a result of which graph statistic was chosen, with no ex ante economic reason yet established for privileging betweenness.
>
> **What survives.** The FRAGMENTATION half is a statement about the distribution, though any graph-based version remains metric-specific. The VOLUME and COUNT share transition is stronger because it measures realised routing directly: the native share of intermediation value falls while the stable share rises, and that survived its sharpest threat when the venue-technology rival was tested and killed on constant-product venues alone.
>
> **A citation error, now resolved.** The betweenness definition was justified in two committed files by appeal to Flandreau and Jobst (2009) before that source entered the corpus. The published article and source package have since been read and reproduced. They do not support betweenness: their measure of a currency's international role is the number of foreign markets quoting it, a degree statistic. This supports degree as a historical dominance measure, not betweenness as the unique on-chain centrality measure, and it does not define which asset is native.
>
> The lead result is therefore the share transition, not the centrality story, and the centrality panel is retained as a descriptive companion whose relationship to degree must be stated wherever it appears.

The lead result. It uses realised routing only and touches no counterfactual quote, so it is unaffected by the support, timing and coverage problems that constrain every cost-based estimand in this project.

## The distinction the international currency literature cannot settle

A falling incumbent share is consistent with two different worlds. Under SUCCESSION one vehicle replaces another, so concentration holds and only the leader's identity changes, which is the sterling-to-dollar transition. Under FRAGMENTATION the role spreads across several assets, so concentration falls while the incumbent may still lead. The dollar against the euro and the renminbi is exactly this question, and FX data cannot settle it because the counterfactual currency network is unobservable: you see the shares that occurred, not the paths that were available.

A Herfindahl index over vehicle shares separates them when it is read together with the leader's identity. Neither statistic does it alone, because a stable HHI with a changing leader is succession and a falling HHI with a stable leader is fragmentation.

## The result

| year | volume HHI | effective vehicles | volume CR1 | volume leader | centrality HHI | effective | centrality CR1 | centrality leader |
|---|---|---|---|---|---|---|---|---|
| 2020 | 0.495 | 2.06 | 68.9% | WETH | 0.773 | 1.32 | 87.4% | WETH |
| 2021 | 0.390 | 2.87 | 57.7% | WETH | 0.710 | 1.41 | 83.9% | WETH |
| 2022 | 0.171 | 6.06 | 28.2% | USDC | 0.623 | 1.61 | 78.0% | WETH |
| 2023 | 0.181 | 5.55 | 32.1% | WETH | 0.688 | 1.47 | 82.4% | WETH |
| 2024 | 0.206 | 4.94 | 39.7% | WETH | 0.708 | 1.42 | 83.8% | WETH |
| 2025 | 0.163 | 6.16 | 27.3% | USDC | 0.498 | 2.10 | 69.0% | WETH |
| 2026 | 0.092 | 10.84 | 20.4% | USDC | 0.332 | 3.01 | 54.6% | WETH |

**By volume the role both fragments and changes hands.** The effective number of vehicles rises from 2.06 to 10.84, the leader's share collapses from 68.9% to 20.4%, and leadership alternates between the native asset and the stable numéraire from 2022 onward.

**By network centrality the role fragments and never changes hands.** The native asset leads in every year of the sample while its share of betweenness falls from 87.4% to 54.6% and the effective number of structurally indispensable assets rises from 1.32 to 3.01.

## Why the disagreement is the finding

Trading volume migrates to the stable numéraire while the network remains unable to route around the native asset. A currency's transaction share can fall a long way while it stays the node the system structurally cannot bypass, and the two measures pull apart precisely because they answer different questions: volume asks where trade flows, betweenness asks which asset paths must cross.

This is the empirical content of "dominance eroding without displacement", and it is a distinction the FX literature states but cannot measure. Flandreau and Jobst reach the same shape of finding on the pre-1914 system: they code which currencies were quoted in which foreign exchange markets as a binary exchange matrix, let each quoting decision depend on the others through a liquidity and popularity feedback, estimate the product of the two feedback parameters at 0.463, and conclude that "there is persistence but no lock-in effects". The version now in this corpus is CEPR Discussion Paper 5529 of March 2006, the author-deposited precursor to the *Economic Journal* article of 2009, and nothing here is attributed to the published version, which could not be retrieved. Two things that paper does not supply. Its measure of a currency's international role is the number of foreign markets quoting it, which is DEGREE in that network, so it is no warrant for betweenness. And its counterfactual is computed inside an estimated model, where here both the shares and the network are observed directly.

## What the definition rests on

A vehicle currency is an asset that lies on the paths between other assets, so betweenness centrality is the direct measure of the role and a volume share is a proxy for it. That correction is definitional and it changes which of the two tables above is the primary one. Centrality is computed on the realised trading graph, one graph per sampled day, with an edge wherever a direct pool joined two tokens and carried at least $1,000 of volume. Source nodes are sampled at k=150 for tractability and the sample is reported so the estimate's noise is visible.

## Limits, stated

**The two bases weight differently by construction.** Volume shares weight an asset by the value routed through it; betweenness weights it by topological position irrespective of size. An asset can be structurally indispensable on many thin pairs and carry little value, and the divergence above is partly that. Separating "indispensable because there is no alternative path" from "indispensable because the alternative paths are worse" needs the cost-weighted graph, which is specified and not yet built.

**Sampled days and sampled sources.** Centrality is computed on every 120th day with k=150 source nodes, so year-level figures rest on a handful of graphs each.

**Round trips are excluded** from the volume basis, since a route whose first input equals its last output moved no value, and leaving them in inverted an earlier result in this project. They run 12.7% of multi-leg routes by count and 21.7% by value on the median of 79 sampled days, reaching 25.9% and 91.3% on 2025-12-06, the worst.

**No causal claim.** This is a description of how the role's concentration evolved. Nothing here identifies why, and the architectural events that plausibly drive it are the subject of the cross-venue spillover work.

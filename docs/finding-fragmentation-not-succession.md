# The vehicle role fragments without changing hands, and the two measures disagree

> **THE CENTRALITY HALF IS COMPROMISED, 2026-08-06, on node C's reopening and verified independently.** Betweenness centrality is close to a restatement of how this project DEFINES the native asset. `src/ddvc/asset_types.py` defines native as the asset with the "thickest incumbent pairing network", which is degree, and the betweenness leader equals the degree leader on 15 of 15 sampled days. So "the native asset leads on centrality in every year" is close to "the asset with the thickest pairing network has the thickest pairing network". That is the same circularity that retired "native intermediation is cheaper", one layer up, and it was not caught because the statistic looked unfamiliar. Node C also reports that eigenvector centrality REVERSES the ordering, putting the stable numéraire first, so "fragments without changing hands" is partly a fact about which of four graph statistics was chosen.
>
> **What survives.** The FRAGMENTATION half is a statement about the distribution and not about the leader, so it is not circular in the same way, though it is a fact about the degree distribution and needs restating in those terms. The VOLUME and COUNT share transition is not circular at all, because it measures realised routing and not a defined property: the native share of intermediation value falls while the stable share rises, and that survived its sharpest threat when the venue-technology rival was tested and killed on constant-product venues alone.
>
> **A citation error to correct with it.** The betweenness definition was justified in two committed files by appeal to Flandreau and Jobst (2009) modelling currency use as a network. That paper is NOT IN THE CORPUS, zero files, so it was cited from memory of a summary. This project has retracted claims for exactly this reason before and the rule is that a claim about what a paper does must rest on the paper.
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

This is the empirical content of "dominance eroding without displacement", and it is a distinction the FX literature states but cannot measure. Flandreau and Jobst (2009) model currency use as a network with externalities and report persistence without strong lock-in, which is the same shape, reached with a structural model on the shares that occurred. Here both the shares and the network are observed directly.

## What the definition rests on

A vehicle currency is an asset that lies on the paths between other assets, so betweenness centrality is the direct measure of the role and a volume share is a proxy for it. That correction is definitional and it changes which of the two tables above is the primary one. Centrality is computed on the realised trading graph, one graph per sampled day, with an edge wherever a direct pool joined two tokens and carried at least $1,000 of volume. Source nodes are sampled at k=150 for tractability and the sample is reported so the estimate's noise is visible.

## Limits, stated

**The two bases weight differently by construction.** Volume shares weight an asset by the value routed through it; betweenness weights it by topological position irrespective of size. An asset can be structurally indispensable on many thin pairs and carry little value, and the divergence above is partly that. Separating "indispensable because there is no alternative path" from "indispensable because the alternative paths are worse" needs the cost-weighted graph, which is specified and not yet built.

**Sampled days and sampled sources.** Centrality is computed on every 120th day with k=150 source nodes, so year-level figures rest on a handful of graphs each.

**Round trips are excluded** from the volume basis, since a route whose first input equals its last output moved no value, and leaving them in inverted an earlier result in this project. They run 12.7% of multi-leg routes by count and 21.7% by value on the median of 79 sampled days, reaching 25.9% and 91.3% on 2025-12-06, the worst.

**No causal claim.** This is a description of how the role's concentration evolved. Nothing here identifies why, and the architectural events that plausibly drive it are the subject of the cross-venue spillover work.

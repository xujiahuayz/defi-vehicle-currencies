# The vehicle role fragments without changing hands, and the two measures disagree

**DEFINITIONAL CORRECTION, node C round 2, 2026-08-06. This file's centrality columns and its identification argument do not survive. Read `docs/node-c-definitions-round2.md` sections 1 and 4 before citing anything below.** Three things are wrong here. The Flandreau and Jobst justification cannot be checked, because that paper is absent from the corpus and from every reference list in it. The betweenness measure is close to a restatement of degree, at Spearman +0.958 between WETH's betweenness share and its degree share and an identical leader on 18 of 18 days, and degree is the property by which `src/ddvc/asset_types.py` defines the native asset, so "the native asset leads in every year" is close to restating a definition. And the identification claim, that a Herfindahl plus a leader identity separates succession from fragmentation, does not hold, because a world where every pair splits evenly between two vehicles and a world where half the pairs route entirely through one and half entirely through the other produce the same aggregate share vector. The corpus statistic is a per-cell three-region regime label after Somogyi (2026) with a switching order after Mukhin (2022). On the excess-use ratio that the corpus actually uses, WETH's vehicle role ends around 2022 and USDT leads in 2026, so the conclusion may reverse and this file's direction is open until it is rebuilt.

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

**Round trips are excluded** from the volume basis, since a route whose first input equals its last output moved no value, and leaving them in inverted an earlier result in this project at 25.6% of multi-leg routes by count and 90.5% by value.

**No causal claim.** This is a description of how the role's concentration evolved. Nothing here identifies why, and the architectural events that plausibly drive it are the subject of the cross-venue spillover work.

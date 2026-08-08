# Cross-venue spillover from an architecture change

Built 2026-08-06 by `scripts/build_cross_venue_spillover_panel.py` and `scripts/run_cross_venue_spillover.py` over `data/unified/` (2,277 days, 2020-02-11 to 2026-06-30). Asset types from `src/ddvc/asset_types.py`. Artefacts: `data/processed/cross_venue_spillover_daily.parquet`, `data/processed/cross_venue_spillover_strata.parquet`, `output/exhibits/cross_venue_spillover_{estimates,pretrends,robustness,persistence,selection,screens}.jsonl`, `output/figures/cross_venue_spillover.pdf`.

## What the design is

Version 1 of this project ran an event study around the Uniswap V3 launch and it died on a confound: everything changed on the launch date, so a break there is unattributable. The spillover design was recommended in section 8 of the workflow as the fix and as the cleanest identification available. Measure the outcome only on venues whose architecture did not change. If an architecture change on venue A moves the vehicle role on venue B, and B did not change, the mechanical migration of activity onto A cannot be the explanation for what happens on B.

Three events. The Uniswap V3 launch, 2021-05-05, treated `uniswap_v3`, untreated `uniswap_v2`, `sushiswap_v2`, `curve`, `balancer`. The Uniswap V4 launch, 2025-01-31, treated `uniswap_v4`, untreated every other venue, an event that also restored native ETH as a pool asset with no wrapping and is therefore a vehicle-currency mechanism directly. The Merge, 2022-09-15, as a placebo, since it changed block time and gas dynamics without changing AMM architecture. Both launch dates were read off the data and not assumed: `uniswap_v3` legs go from 14 on 2021-05-04 to 2,869 on 2021-05-05, and `uniswap_v4` legs go from 74 on 2025-01-30 to 556 on 2025-01-31 and 2,742 on 2025-02-01.

Three outcomes, each a composition contrast between the native platform asset and the stable numéraire, measured on untreated venues only. Route share is the share of intermediation episodes on multi-leg routes whose every leg settles on an untreated venue. Betweenness share is the share of total topological betweenness centrality in the daily token graph rebuilt from untreated-venue legs alone, which asks whether the architecture change altered which asset is structurally indispensable somewhere it did not operate. New-pair share is the asset-type composition of token pairs appearing for the first time anywhere on the untreated venues. Every headline number is the native measure minus the stable measure, estimated as its own regression, because reading a difference off two point estimates is how an insignificant gradient became load-bearing in four places in this project.

## What the betweenness outcome can and cannot say

Corrected after the 2026-08-09 Krugman source audit: native status is the platform identity, not a pairing-degree definition, so the pre-event native-minus-stable betweenness share of 0.689 is not mechanically fixed by the taxonomy. The outcome remains fragile for a different reason. The betweenness leader equals the degree leader on 15 of 15 sampled days while eigenvector centrality reverses the ordering, and the project lacks an ex ante economic reason to privilege betweenness. The CHANGE in betweenness around an event is still not fixed by any level ordering, but the placebo and control-group failures below demote it independently. Flandreau and Jobst's exact published source and package are now in the corpus; their historical dominance measure is degree, not betweenness.

## Inference basis and identifying units

The V3 event has four untreated venues and the V4 event has seven, so clustering on venue is not available and is not used. The identifying units are days: 180 pre-event and 181 post-event at the primary window. The analytic standard error is Newey-West with a Bartlett kernel at 30 daily lags. Every coefficient also carries a randomisation p-value built by refitting the identical specification at 235 admissible placebo dates spaced three days apart across the whole sample, each at least 200 days from every real event. The randomisation p-value is the one to quote, because it is exact under the sharp null of no date effect and it prices in whatever serial correlation the daily series actually has. The specification is a level break at event time zero on top of a linear trend that is itself allowed to break, so a drift already under way cannot be collected as a jump.

The V3 window rests on 5,213,668 pre-event and 3,828,216 post-event intermediation episodes on untreated venues, with a mean untreated-venue graph of 1,510 tokens. The V4 window rests on 6,943,548 and 5,970,036 episodes, with a mean graph of 2,281 tokens.

## Screens, reported

| screen | untreated_v3 set | untreated_v4 set |
|---|---|---|
| days in panel | 2,277 | 2,277 |
| days dropped, fewer than 25 episodes | 42 | 42 |
| multi-leg routes | 33,879,280 | 61,603,474 |
| round trips dropped as atomic arbitrage or wash | 3,121,196 (9.2%) | 8,410,560 (13.7%) |
| intermediation episodes retained | 32,835,759 | 61,866,811 |
| candidate graph edges | 8,248,779 | 9,899,168 |
| edges dropped below the 1,000 USD dust floor | 55.4% | 53.1% |
| first-appearance pairs | 366,406 | 391,925 |

Legs priced at zero or above 1e9 USD are dropped as pricing artefacts before anything else. Nothing is conditioned on a function of the outcome: the denominators screened on are episode counts, graph size and new-pair counts, none of which is the asset-type composition being measured.

## Result, native minus stable, primary window

| event | outcome | pre mean | jump | HAC se | HAC p | randomisation p | MDE at 80% power |
|---|---|---|---|---|---|---|---|
| Uniswap V3 | route share | 0.489 | +0.037 | 0.051 | (0.463) | (0.634) | 0.253 |
| Uniswap V3 | betweenness share | 0.689 | +0.020 | 0.011 | (0.082) | (0.489) | 0.106 |
| Uniswap V3 | new-pair share | 0.701 | +0.236 | 0.089 | (0.008) | (0.000) | 0.050 |
| Uniswap V4 | route share | 0.494 | −0.293 | 0.054 | (0.000) | (0.000) | 0.212 |
| Uniswap V4 | betweenness share | 0.697 | −0.071 | 0.023 | (0.002) | (0.038) | 0.092 |
| Uniswap V4 | new-pair share | 0.940 | +0.018 | 0.014 | (0.185) | (0.426) | 0.058 |
| Merge placebo, V3 set | route share | 0.507 | +0.149 | 0.062 | (0.017) | (0.089) | 0.253 |
| Merge placebo, V3 set | betweenness share | 0.621 | +0.006 | 0.015 | (0.678) | (0.787) | 0.106 |
| Merge placebo, V3 set | new-pair share | 0.916 | +0.055 | 0.016 | (0.000) | (0.000) | 0.050 |
| Merge placebo, V4 set | route share | 0.317 | +0.125 | 0.057 | (0.028) | (0.132) | 0.212 |
| Merge placebo, V4 set | betweenness share | 0.600 | +0.007 | 0.016 | (0.661) | (0.783) | 0.092 |
| Merge placebo, V4 set | new-pair share | 0.891 | +0.062 | 0.017 | (0.000) | (0.000) | 0.058 |

The minimum detectable effect is the size an effect must reach for this design to find it 80% of the time at the 5% level, computed from the randomisation distribution of the same coefficient at dates where nothing happened. It is reported for every row so that a small coefficient is read as a bounded negative and never as a null.

## Pre-trends

A spillover claim with a pre-trend is not a spillover claim. Two diagnostics run on the pre-window alone. The first is the pre-window slope in units of the outcome per 100 days. The second is a pseudo-break fitted at the midpoint of the pre-window using pre-window data only, which asks whether the identical specification finds jumps in this series at dates where nothing happened.

| event | outcome | pre-window slope per 100 days | p | pseudo-break | p |
|---|---|---|---|---|---|
| Uniswap V3 | route share | +0.188 | (0.006) | +0.277 | (0.015) |
| Uniswap V3 | betweenness share | +0.017 | (0.270) | +0.043 | (0.000) |
| Uniswap V3 | new-pair share | −0.003 | (0.965) | −0.003 | (0.954) |
| Uniswap V4 | route share | +0.004 | (0.914) | −0.081 | (0.015) |
| Uniswap V4 | betweenness share | −0.035 | (0.037) | −0.033 | (0.035) |
| Uniswap V4 | new-pair share | −0.035 | (0.000) | −0.012 | (0.265) |
| Merge placebo, V4 set | route share | −0.099 | (0.039) | +0.164 | (0.000) |
| Merge placebo, V4 set | betweenness share | −0.045 | (0.000) | +0.018 | (0.024) |
| Merge placebo, V4 set | new-pair share | −0.039 | (0.003) | +0.072 | (0.000) |

Only one cell in the whole matrix is clean on both diagnostics, and it is the V3 new-pair outcome. The V4 betweenness estimate sits on a pre-window slope of the same sign at (0.037) and a pre-window pseudo-break of the same sign at (0.035), which means the series was already moving that way and the specification was already finding steps of about half the estimated size before the event. The V3 route-share estimate sits on a pre-window slope of +0.188 per 100 days at (0.006), which is four times the estimated jump per quarter.

## The Merge placebo

The placebo does not come up empty, and this is the single most consequential result in the exercise. The betweenness outcome passes cleanly on both untreated sets, +0.006 (0.787) and +0.007 (0.783) against a minimum detectable effect of about 0.10. The route-share outcome is not significant at 5% by randomisation, +0.149 (0.089) and +0.125 (0.132), which is a marginal pass with a very wide bound. The new-pair outcome fails outright, +0.055 (0.000) and +0.062 (0.000). A date on which no AMM architecture changed produces a highly significant break in the new-pair composition of venues that did not change, so the new-pair outcome family cannot support a causal spillover reading on its own. The magnitude comparison is the most that can be salvaged: the Merge moves that outcome by about 0.06 and the V3 launch moves it by 0.236, so the date-artefact component is bounded at roughly a quarter of the V3 estimate.

## Selection, the one mechanical story that had to be excluded

The purity rule drops any route with a leg on the treated venue, so the post-event population differs from the pre-event population by construction. If the migrating routes were disproportionately intermediated by one asset type, the composition of what stays behind would move by arithmetic with nothing happening on the untreated venues. `data/processed/cross_venue_spillover_strata.parquet` measures the migrating stratum directly.

| event | stratum | share of post-event episodes | native share | stable share | jump, native minus stable |
|---|---|---|---|---|---|
| Uniswap V3 | routes touching the treated venue | 28.1% | 50.2% | 38.6% | not estimable, no pre-period |
| Uniswap V3 | pure untreated routes | 71.9% | 79.4% | 16.2% | +0.037 (0.463) |
| Uniswap V3 | all routes including treated | 100% | 71.2% | 22.5% | −0.121 (0.043) |
| Uniswap V4 | routes touching the treated venue | 25.1% | 25.6% | 39.9% | not estimable, no pre-period |
| Uniswap V4 | pure untreated routes | 74.9% | 56.2% | 22.0% | −0.293 (0.000) |
| Uniswap V4 | all routes including treated | 100% | 48.5% | 26.5% | −0.346 (0.000) |

The migrating routes are stable-tilted on both events, so removing them would push the retained native share up. Both estimates therefore run against the direction selection would produce, and selection is excluded as the source of the V4 result. The same table carries the bad news. At the V3 launch the market-wide composition moves toward the stable numéraire, −0.121 (0.043), while the untreated venues do not move at all, and the whole market-wide move is accounted for by the new venue itself. At the V4 launch the untreated-venue move of −0.293 recovers most of the market-wide move of −0.346, which means restricting to untreated venues buys almost no differencing against whatever else was happening in early 2025. That is the confound the design was chosen to solve, and on the V4 event it does not solve it.

## Robustness to the window

| event | outcome | ±90 days | ±180 days | ±270 days | ±180 with a 14-day donut |
|---|---|---|---|---|---|
| Uniswap V3 | route share | +0.076 (0.369) | +0.037 (0.634) | +0.081 (0.302) | +0.047 (0.600) |
| Uniswap V3 | betweenness share | +0.014 (0.606) | +0.020 (0.489) | +0.088 (0.059) | +0.022 (0.443) |
| Uniswap V3 | new-pair share | +0.070 (0.039) | +0.236 (0.000) | +0.244 (0.000) | +0.328 (0.000) |
| Uniswap V4 | route share | −0.184 (0.011) | −0.293 (0.000) | −0.178 (0.000) | −0.349 (0.000) |
| Uniswap V4 | betweenness share | −0.009 (0.781) | −0.071 (0.038) | −0.055 (0.146) | −0.092 (0.009) |
| Uniswap V4 | new-pair share | −0.003 (0.850) | +0.018 (0.426) | +0.025 (0.585) | +0.022 (0.357) |
| Merge placebo, V4 set | route share | +0.018 (0.846) | +0.125 (0.132) | +0.119 (0.307) | +0.183 (0.000) |
| Merge placebo, V4 set | new-pair share | +0.038 (0.129) | +0.062 (0.000) | +0.029 (0.522) | +0.067 (0.000) |

The V4 route-share sign survives every window, which is the strongest thing in this document. The V4 betweenness result does not: it is a clean null at ±90 days, (0.781), and significant only in the middle of the window range. The V3 new-pair result grows from +0.070 to +0.328 as the window widens, which is the signature of a slow composition change and not of a break. The Merge placebo route-share and new-pair estimates both become significant under the donut, which is a placebo firing under a specification chosen for robustness.

## Persistence

An architecture change is permanent, so a break it caused should still be visible a year on. The table reports the outcome level in post-event horizon bands against the pre-window mean.

| event | outcome | pre | +1 to +90 | +91 to +180 | +181 to +365 | +366 to +730 |
|---|---|---|---|---|---|---|
| Uniswap V4 | route share | 0.494 | −0.243 | −0.053 | −0.215 | −0.223 |
| Uniswap V4 | betweenness share | 0.697 | −0.096 | −0.054 | −0.141 | −0.208 |
| Uniswap V4 | new-pair share | 0.940 | +0.007 | +0.031 | +0.025 | +0.021 |
| Merge placebo, V4 set | route share | 0.317 | +0.066 | +0.139 | +0.287 | +0.218 |
| Merge placebo, V4 set | betweenness share | 0.600 | −0.030 | −0.027 | +0.091 | +0.106 |

The V4 effects persist and the betweenness effect grows. The placebo drifts by as much over the same horizons and in the opposite direction, so persistence separates nothing here. These series wander over a year at the scale of the estimates, which is the same fact the wide minimum detectable effects report.

## What the three events give

**Does spillover exist at the V3 launch?** No, on the two routing outcomes, and the negative is weakly bounded. Route share +0.037 (0.634) against a minimum detectable effect of 0.253, and betweenness share +0.020 (0.489) against 0.106. The betweenness bound is the useful one: an architecture change on Uniswap V3 shifted the native-minus-stable betweenness share of venues that did not change by less than about 11 percentage points, from a base of 0.689. The new-pair outcome does show +0.236 (0.000) with clean pre-trends, and it is the only clean-pre-trend cell in the exercise, but its outcome family fails the Merge placebo and its magnitude more than triples as the window widens from ±90 to ±180 days, so it reads as a slow composition change that the break specification is mislabelling.

**Does spillover exist at the V4 launch?** On the route-share outcome, yes as a statistical matter: −0.293 (0.000) against a minimum detectable effect of 0.212, robust in sign across every window, persistent to two years, and not attributable to selection, since the routes that migrated to V4 were stable-tilted and their removal pushes the retained native share the other way. On the betweenness outcome the estimate is −0.071 (0.038) against a minimum detectable effect of 0.092, so the effect is smaller than what the design can reliably detect and it vanishes at ±90 days. On the new-pair outcome there is nothing, +0.018 (0.426) against 0.058. The direction is away from the native asset, which is the opposite of what V4's restoration of unwrapped native ETH predicts, so if this is the architectural channel it is running through something other than the native-ETH mechanism.

**Are pre-trends clean?** No, in most places. One cell of nine passes both pre-trend diagnostics. The V4 betweenness estimate has a same-signed pre-window slope at (0.037) and a same-signed pre-window pseudo-break at (0.035). The V3 route-share estimate has a pre-window slope of +0.188 per 100 days at (0.006). The V4 route-share estimate has no pre-window slope, +0.004 (0.914), which is the one thing supporting it, though the pre-window still contains a pseudo-break of −0.081 (0.015).

**What did the Merge placebo give?** A pass on betweenness, +0.006 (0.787) and +0.007 (0.783). A marginal pass on route share, +0.149 (0.089) and +0.125 (0.132), which becomes a failure at +0.183 (0.000) under the donut specification. An outright failure on new pairs, +0.055 (0.000) and +0.062 (0.000). A design whose placebo fires on two of three outcome families under at least one reasonable specification has not demonstrated that its event dates are doing the work.

## Verdict

This cannot carry a JFE result as it stands, and the recommendation in section 8 that it is the cleanest identification available should be downgraded. The reason is specific and it is not a power problem. The spillover logic buys exactly one thing, which the selection table confirms it buys: the mechanical migration of activity onto the new venue is excluded as the source of the estimates. It does not buy what section 8 claimed for it. The argument was that a macro episode is shared by both venues and differences out, and that argument is false as applied here, because the untreated venues are most of the market and any market-wide compositional shock passes straight through them. The V4 numbers make this concrete: the untreated-venue move of −0.293 recovers 85% of the all-venue move of −0.346, so the untreated restriction removes almost nothing. Early 2025 contains a large market-wide rotation of intermediation toward the stable numéraire on every venue, and the V4 launch date sits inside it. The design cannot separate the two, which is version 1's confound in a new costume.

Two things here are worth keeping. The first is the betweenness outcome, which is the only one that passes the Merge placebo cleanly and the only one whose bound is tight enough to say something. Its V3 reading is a real bounded negative worth stating in the paper: a concentrated-liquidity architecture arriving on one venue moved the structural indispensability of the native asset on venues that did not adopt it by less than 11 percentage points from a base of 69. That is a finding about the locality of architectural change and it is reportable as a null with a bound. The second is the selection table itself, which is a clean descriptive result: at the V3 launch the entire market-wide compositional move toward the stable numéraire is accounted for by the new venue, −0.121 (0.043) on all routes against +0.037 (0.463) on untreated venues, while at the V4 launch it is not. Those two events differ in exactly the way the vehicle-currency question cares about, and describing that difference does not require a causal claim.

What would be needed to make this an identified result is a control group inside the same day, which this design lacks. The untreated venues are a control for the treated venue and they are not a control for the calendar. A within-day contrast that holds the calendar fixed, such as token pairs whose routing options the architecture change touched against pairs it could not touch, would difference out the market-wide rotation that currently swamps the V4 estimate. That is a different design on the same events and it is the version worth building.

# 30-minute presentation transcript

The timings below total 30 minutes and cover the core deck only. Appendix slides are for questions.

## Cover (0:00 to 1:15)

Hi everyone. It is a great pleasure to be here. I have collaborated with several researchers at NTU, many of them in computer science, so I see both familiar faces and familiar names in the programme. My own background is in business economics and finance, but much of my work sits between finance and computer science. At UCL I am also part of the Financial Computing research group, which reflects that same interdisciplinary interest.

Today I will talk about the making of dominant vehicle currencies, using decentralised finance as the empirical setting. The question is familiar from international finance: when two currencies do not trade efficiently with each other, which third currency bridges them? The new part is that decentralised exchanges let us observe the connected trading path and the liquidity behind it. The line on the left is the argument I want to develop: new trading relationships can change which vehicle becomes dominant.

## A cross-border payment needs someone to make the FX market (1:15 to 2:30)

Start with an ordinary cross-border payment. A payment provider receives one currency but has to deliver another currency that it may not hold. Someone must quote the exchange rate and supply the liquidity. Current payment-system projects make this explicit. Project Nexus requires an FX provider, and Project Rialto considers using a vehicle currency when direct conversion is unavailable.

So the vehicle is not merely a label in a network. It solves a balance-sheet and market-making problem. The provider can bridge currency A and currency B through currency k because liquidity in A against k and k against B is deeper than liquidity in A against B. This gives us the two sides of the paper: which currency occupies the middle of the route, and how liquidity providers support that position.

## Pool routes reveal the vehicle currency (2:30 to 3:50)

Since we are in Singapore, consider a payment from Singapore dollars into Norwegian kroner. It may be converted first into US dollars and then into kroner. This is an illustration, not a claim that every SGD to NOK payment follows this exact route. The important point is that the dollar can bridge a pair that is costly to trade directly.

In conventional FX data, we may observe turnover in SGD against USD and turnover in USD against NOK. We generally cannot tell whether those two trades came from one customer instruction. Connecting them requires assumptions.

In decentralised finance, or DeFi, exchanges execute trades through smart contracts and liquidity pools. The logs from one transaction preserve the ordered pool path. If a user trades token A for token B through a stablecoin or the native asset, we observe the intermediary directly. That is the measurement advantage of this setting.

## The route panel links pool-level swaps (3:50 to 5:00)

We assemble 472 million pool-level swaps over 2,332 calendar dates, from February 2020 through June 2026. The panel covers eight major Ethereum deployments: Uniswap versions 2, 3, and 4; SushiSwap versions 2 and 3; Curve; Balancer; and Fluid.

I want to be precise about the perimeter. This is a large panel of the listed deployments, not every swap ever executed on Ethereum. We use structured Graph and Dune records, then reconstruct connected pool components within each transaction.

Uniswap V1 is treated separately. Its retained records identify the exchange contracts but do not provide a complete mapping from every exchange to the underlying token address. Shared transaction hashes and matching ETH legs let us recover forced token-to-token paths, which is enough to study the V1 architecture. They do not let us assign endpoint token identities uniformly, so V1 does not enter the principal endpoint-pair panel.

## Inside the pools, USDT links USDC to USDe (5:00 to 6:30)

This is one authentic transaction from January 2026. The user's broader instruction is PYUSD to USDe. The connected component that we observe in our exchange panel begins with USDC, then goes through USDT, and ends with USDe. The first pool is on Fluid and the second is on Uniswap V4. Within this observed component, USDC and USDe are the endpoints, and USDT is the vehicle.

The distinction at the top matters. We do not claim that PYUSD was swapped into USDC on some exchange outside our panel. The executor may instead have supplied USDC from inventory. The pool logs identify the connected component, not the full economic instruction or the executor's inventory decision.

We retain longer connected routes as well. In the supplementary all-length measure, every intermediary used in a route contributes an observation. For the headline native-versus-stable comparison, we use the cleaner exact two-leg case with one intermediary.

## Vehicle dominance is an intermediary share (6:30 to 7:55)

Our central object is vehicle dominance. For asset k, it is k's share of indirect trade as an intermediary. Count-weighted dominance gives each route equal weight. Value-weighted dominance weights by the dollar value carried through the route.

The main comparison has an especially transparent denominator: exact two-leg routes whose sole intermediary is either the native currency or a stablecoin. For value weighting, the dollar values at the source, vehicle, and destination must agree within 20 percent. That restriction removes routes for which token pricing or route reconstruction gives inconsistent notions of value.

This is why we do not use betweenness centrality as the main outcome. Betweenness describes how central a token could be in the graph of available connections. Our dominance measure records how often traders actually route through it. Network reach remains useful as a predictor and a competing mechanism, but realised intermediary share is the economic outcome.

## Architecture changes routing opportunities (7:55 to 9:25)

The protocol architecture changes what traders and liquidity providers can choose. In Uniswap V1, every token pool is paired with ETH. A token-to-token trade therefore has to pass through ETH. Here the native vehicle is imposed by design.

V2 allows an arbitrary token pair, so direct trading and alternative vehicles become feasible. The vehicle is now a market outcome. V3 adds another choice: providers place liquidity within price ranges and choose among fee tiers, so the active depth of a route depends on where liquidity sits, not only on total deposits.

V4 changes the settlement boundary. Its singleton and flash accounting track token deltas across the transaction and settle the net amount at the end. Intermediate transfers can be netted, but the economic route does not disappear. The transaction still uses particular pools and particular intermediary liquidity. This distinction lets us ask whether internal routing under shared accounting predicts subsequent provider activity.

## Three margins can make a vehicle dominant (9:25 to 10:25)

The rest of the talk separates three margins.

First, market formation: when a new endpoint pair begins trading, which vehicle does it coordinate on, and does that initial choice persist?

Second, liquidity provision: does an endpoint pair route through the vehicle with deeper capital on both atomic legs, and does capital appear before the vehicle is first used?

Third, market integration: if we widen the exact price opportunity set across exchanges and alternative vehicles, does the observed vehicle identity survive?

Volatility enters later as a market state for the V4 provider response. I do not present it as a fourth mechanism on equal footing because the evidence does not support four symmetric claims.

## Native-asset pairing persists after it becomes optional (10:25 to 11:40)

The move from V1 to V2 provides a useful institutional transition. In V1 we recover 217,003 token-to-token routes that pass through ETH because the contract requires it.

V2 removes that mandate, but native pairing remains extraordinarily persistent. In 2026, 95.5 percent of single-leg V2 trades use a WETH pool, and 97.9 percent of endpoint pairs first traded on V2 include WETH.

This slide is not yet the stablecoin result. Its purpose is to show why architecture alone is insufficient. Once arbitrary pairs are possible, traders and providers still coordinate around a common asset. The economic question becomes how a stablecoin can displace part of that inherited native-asset role. That takes us to the time series.

## Stablecoins regain the routed-value lead by 2026 H1 (11:40 to 13:05)

The figure shows the annual history of intermediary composition. Native assets lead early, stablecoins move ahead, native assets regain share in 2023 and 2024, and stablecoins recover the routed-value lead in 2025. So this is not a smooth technological trend.

For the headline comparison, we match January through June in 2024 with the same dates in 2026 because the 2026 panel ends in June. Stablecoin dominance among native and stable vehicles rises from 16.9 to 42.3 percent by route count, an increase of 25.4 percentage points. By routed value it rises from 32.7 to 76.5 percent, an increase of 43.9 points.

The full-year points through 2025 provide the history; the 2026 endpoint is visibly H1. The next question is whether this reflects a general increase in demand for stablecoins as endpoints or a distinct intermediary role.

## Endpoint demand predicts vehicle use within day (13:05 to 14:15)

This equation formalises that comparison. The subscript a denotes an asset or currency, and t denotes the date. I is asset a's share of the day's intermediary episodes. D is the same asset's share of route-endpoint appearances. Both are measured in percentage points.

The asset-class indicators distinguish native currencies, stablecoins, staked-native assets, imported currencies, and a residual group. Date effects absorb market-wide conditions on each day. Currency effects absorb persistent differences across individual currencies.

The coefficient beta asks a simple question: when a currency becomes more important in endpoint demand, how much more important does it become as an intermediary? This is descriptive, not a causal demand elasticity, because trading demand and route selection are jointly determined.

## The demand relationship survives currency and date effects (14:15 to 15:40)

Here is the regression table in the form commonly used in a finance paper. In the pooled and date-effect specifications, the native and stablecoin rows compare those classes with the residual asset class. Once endpoint demand enters, the native coefficient falls from about 34.6 points to essentially zero. The stablecoin coefficient is 0.85 points and only marginally precise.

The important row is endpoint-demand share. Across currencies within a date, one additional percentage point of endpoint demand is associated with 1.59 points more intermediary share. After adding currency fixed effects, the estimate is 0.98. So within a given currency over time, endpoint demand passes through almost one for one into intermediary use.

The dashes in column four are deliberate: currency fixed effects absorb time-invariant native and stablecoin indicators. The table tells us that demand matters strongly. It does not by itself explain the large aggregate rotation, so we next decompose where the changing demand comes from.

## WETH-linked endpoint pairs carry the count rotation (15:40 to 16:50)

Endpoint identity creates a mechanical restriction. If WETH is one endpoint, it cannot also be the intermediary, so stablecoins are the eligible vehicles in the native-versus-stable comparison.

Across all matched endpoint pairs, the stablecoin route-count share rises by 21.1 percentage points. When we remove pairs with WETH at an endpoint, the increase falls to 3.7 points. More importantly, after fixing the endpoint pair, month-day, and route scope, the within-pair changes are only 0.2 points overall and 0.3 points without WETH endpoints.

The count rotation is therefore mainly about which endpoint relationships carry trading activity, especially WETH-linked relationships. It is not primarily incumbent pairs switching their vehicle en masse.

## Who trades with whom makes the vehicle (16:50 to 18:10)

This exact decomposition shows the contribution of three endpoint categories to the headline increase.

By route count, other endpoint pairs contribute 15.2 percentage points, one-native-one-stable pairs contribute 9.2, and two-stable endpoint pairs contribute only 1.0.

By routed value, the pattern differs. Other pairs contribute 20.6 points, native-stable pairs contribute 10.1, and stable-to-stable endpoint pairs contribute 13.2 points, almost one third of the total 43.9-point increase.

Issuer identity inside that high-value stable-to-stable channel is striking. USDT alone contributes 13.7 percentage points, while USDC, DAI, and the remaining stablecoin intermediaries jointly contribute minus 0.5. This is the direct additive issuer result. It avoids ranking currencies by intermediary use minus endpoint use.

## Trading shifts toward stablecoin-heavy endpoint pairs (18:10 to 19:25)

Now remove WETH endpoints and focus on routed value, where the stablecoin increase is still 21.5 percentage points. The decomposition is exact day by day.

Routed-value reallocation across endpoint-pair groups contributes plus 23.5 points. The change in stablecoin share within the same groups contributes minus 2.0 points. In other words, aggregate dominance rises because value moves toward trading relationships that already use stablecoin vehicles more intensively. The fixed groups themselves show no broad conversion toward stablecoin routing.

This is economically different from a representative pair switching vehicles. It is a composition result: the market creates and expands relationships whose routing convention is already stablecoin-heavy.

## New endpoint pairs deliver the largest positive component (19:25 to 20:45)

The route-count decomposition makes the extensive margin explicit. Stablecoin share rises from 16.9 to 42.5 percent, a 25.7-point rotation.

Inside continuing endpoint pairs, net vehicle switching contributes minus 0.1 point. Reallocation of activity among those continuing pairs contributes plus 8.6 points. Newly traded endpoint pairs contribute plus 21.0 points, while endpoint-pair exit contributes minus 3.3 points. A small continuing-pair weight term closes the identity.

The key result is that entry is not a residual footnote. It is the largest positive component. The initial vehicle choice also persists: the first routes of a new pair predict its vehicle share 30 and 120 days later. That is the coordination margin in the title, and it turns the paper from measurement into a theory-relevant result about market formation.

## Local bridge depth predicts route choice (20:45 to 22:00)

We now turn to liquidity provision. For each endpoint pair and date, we compare five possible vehicles. A vehicle route needs capital on two legs, so its effective local depth is the deposited capital on the weaker leg.

The vehicle with the deepest local bridge captures 84.1 percent of routes. That share rises from 75.5 percent in 2024 to 86.5 percent in 2026. In a horse-race regression that also controls for the vehicle's broader network reach, one log point more weaker-leg capital is associated with 6.79 percentage points more route share.

The bottleneck matters economically: abundant capital on only one leg is not enough. A vehicle becomes usable for a particular endpoint relationship when both legs are deep enough.

## Stablecoin penetration rises with relative bridge depth (22:00 to 23:15)

This slide follows a stablecoin bridge after it first becomes available beside a WETH bridge. In the first 30 days, the supported stablecoin captures only 2.4 percent of routes when its depth is below one tenth of WETH depth. At parity with WETH, its share is 53.0 percent. At twice WETH depth, it reaches 69.9 percent.

The extensive-margin result is equally large. Only 42.6 percent of shallow stablecoin bridges are used within the first month, compared with 84.1 percent when their depth is at least one tenth of WETH depth. With controls, the gap is still 25.2 percentage points.

These are predictive comparisons because demand and capital are jointly determined. The timing evidence on the next slide helps distinguish capital that is already present from capital that merely follows observed route use.

## Bridge capital builds before use (23:15 to 24:30)

We align 246 events around the first use of a supported stablecoin vehicle. The sample requires the bridge to exist persistently before adoption, so day zero is first route use, not first pool creation.

From day minus seven to day zero, log deposited capital on the weaker stablecoin leg rises by 0.86. Relative to the matched WETH bridge, the pre-use increase is 0.78. From day zero to day plus seven, stablecoin bridge capital falls by 0.44.

The shape is consistent with providers building route-specific capital before traders use the bridge, followed by partial retrenchment. It does not identify provider intent, and the sample conditions on eventual adoption. Still, the timing is difficult to reconcile with a story in which all measured capital arrives only after route demand becomes visible.

## Most first-use capital sits in pools already active (24:30 to 25:35)

Where does that pre-use capital come from? At the first-use date, 92.5 percent of stablecoin bridge capital sits in pools that were already active one week earlier. Continuing-pool capital grows by 0.16 log points relative to the matched WETH pools.

There is also an entry margin. The probability of a newly active pool rises by 6.9 percentage points relative to WETH. So providers use both margins: they scale existing pools, which hold most of the capital, and they activate some additional pools before route adoption.

These are deposited-capital stocks. They are not direct measures of provider cash flow, inventory, or profitability. The result is about where route-supporting capital is located and when it becomes available.

## V4 internal routing forecasts later entry in volatile markets (25:35 to 27:15)

V4 lets us study provider behaviour under shared accounting. The predictor is internal same-asset routing: transfers that can be netted inside the singleton while the transaction still uses identifiable pools and vehicles.

Ten percentage points more internal routing predicts 0.086 log points more actions by origins that were already active during the prior 180 days, measured over days 1 to 30. Over days 31 to 120, it predicts 0.153 log points more activity from origins that become active only after the measurement date.

The state dependence is stronger. One standard deviation more persistent 30-day WETH volatility adds 0.318 log points to that later first-active-origin response. Incumbents move first; new origins follow later, especially when volatility remains high.

Origins are accounts, not identified beneficial owners of LP positions, and the design is predictive. A same-vehicle-date V3 comparison does not separate the mature-period level or volatility slope, so I do not interpret this as a clean causal V4 treatment effect. It is evidence that the flash-accounting routing state forecasts economically meaningful provider participation.

## Vehicle identity survives broader price competition (27:15 to 28:50)

A serious rival is simple price improvement. Perhaps the observed vehicle appears dominant only because the router missed a better path.

For 777,651 routes on 73 monthly dates, we reconstruct the exact pre-transaction state and keep the same input. Within the venue families used by the realised route, 6.6 percent have more than one basis point higher gross output with the same vehicle. Searching all three exact exchanges raises that to 44.4 percent. This shows substantial venue-level price competition.

But opening the set to any named vehicle or a direct route raises the incidence only to 46.4 percent, another 2.0 points. Reassigning every route to its best path reduces stablecoin vehicle share by only 1.2 points, with a standard error of 0.2. So price improvements often change the venue, while rarely changing the vehicle identity. The median gain among improved standard quotes is 21.9 basis points, so this is not driven only by trivial numerical differences.

## Dominance forms through entry, depth, and provider response (28:50 to 30:00)

Let me close with three findings.

First, dominant vehicles are made when new trading relationships enter and coordinate on them. Newly traded endpoint pairs provide the largest positive component of the stablecoin rotation, and their initial vehicle choices persist.

Second, dominance is locally contestable through liquidity. The deepest two-leg bridge captures most routes, and stablecoin adoption rises sharply once its weaker leg becomes competitive with WETH.

Third, liquidity providers respond before and after route use. Capital builds before adoption, incumbents act quickly under V4 internal routing, and first-active origins follow later in volatile markets.

The broader implication is that a dominant currency is not only the asset with the largest aggregate network. It is the asset around which new trading relationships form, local liquidity becomes usable on both legs, and provider participation reinforces the route. Thank you.

---

# Q&A backup notes

These notes are not part of the timed 30-minute transcript.

## Why can V1 forced routes be recovered when endpoint identities cannot?

The retained V1 records identify exchange contracts and transaction hashes but lack a complete exchange-to-token address mapping. Matching the two ETH legs inside one transaction reveals the forced token-to-ETH-to-token structure. Without the missing crosswalk, the two non-ETH token identities cannot be assigned uniformly, so V1 supports the architecture count but not the principal endpoint-pair analysis.

## Does the analysis include routes with more than two legs?

Yes. The route reconstruction retains complete connected routes. The supplementary all-length dominance measure counts every intermediary use. The headline native-versus-stable rotation uses exact two-leg routes with one intermediary because its denominator and vehicle identity are unambiguous.

## What does the PYUSD example establish?

It establishes only the connected pool component USDC to USDT to USDe. It does not establish how the broader PYUSD instruction became USDC. That could reflect an unobserved pool leg or executor inventory. The example therefore illustrates both the route measure and its economic boundary.

## Why is betweenness centrality not the dominance measure?

Betweenness measures feasible graph position. Vehicle dominance measures realised intermediary use. Network reach and related graph measures remain explanatory variables because they capture coordination and availability, but they are not substitutes for the realised outcome.

## What exactly does V4 flash accounting change?

V4 records token deltas across operations inside one singleton and settles net balances at the end of the transaction. This can avoid repeated intermediate transfers. It does not erase the pool sequence, the pricing state, or the liquidity used by the route.

## Why is excess use no longer a core slide?

Intermediary share divided by endpoint share measures role specialisation, not aggregate dominance. It can rank a heavily used endpoint below an inactive token if interpreted incorrectly, and observed endpoint boundaries can be affected by executor inventory. The paper retains it as a bounded supplementary comparison. The talk uses the direct additive decomposition for the issuer claim.

## Why not replace the annual chart with half-year points throughout?

Full-year points through 2025 show the non-monotonic historical path. The 2026 point is explicitly labelled H1, and the headline estimate compares January through June in both 2024 and 2026. Replacing every historical point with half-year estimates would add sampling noise while discarding the annual history.

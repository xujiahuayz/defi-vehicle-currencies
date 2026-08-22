# 30-minute talk notes

Spoken notes for the current deck. The main talk takes about 29 minutes, including transitions and the 18-second film. Nothing in the spoken text points at tables, panels, or columns; every number said aloud is visible on the slide or is a natural answer to it. The backup section has bullets for every appendix page.

## Cover. The Making of Dominant Vehicle Currencies

Hi everyone. Great pleasure to be here.

I have worked with quite a few people at NTU, mainly in computer science. My own background is finance and business economics, and much of my work sits between the two. So, some familiar faces, and many new ones. Very nice to be back in Singapore.

Today I want to talk about dominant vehicle currencies, with evidence from DeFi.

The question itself is old. When the direct market between two currencies is thin, something sits in the middle. What decides which currency gets that role, and keeps it?

What DeFi adds is that we can watch the middle asset, route by route, and watch the role being won and lost. That is the talk.

## Slide 1. A cross-border payment needs someone to make the FX market

Let me start with a familiar payment problem.

A payment provider receives currency A and has to deliver currency B. If the direct market is thin, the provider goes through a common currency k. A into k, then k into B.

That sounds like plumbing, but economically it needs two markets. Someone has to quote both legs and hold inventory on both sides. That someone is why vehicle currencies exist: two liquid legs can bridge a pair that has no market of its own.

And we know how concentrated this role is in practice. More than 85% of FX transactions have the US dollar on one side, far beyond America's share of world trade. The middle position feeds on itself. Trading concentrates there, liquidity follows, and the same currency is cheaper to use the next time.

Central banks are wrestling with exactly this. Project Nexus, which the MAS is closely involved in, requires an FX provider inside the rail. Rialto reaches for a vehicle whenever direct exchange is unavailable.

In traditional FX we rarely see the full chain. In DeFi, the transaction records it. So let me show you what we see.

## Slide 2. Pool routes reveal the vehicle currency

Since we are in Singapore: take a Singapore-dollar payment to Norway.

It may go SGD to US dollar, then US dollar to krone. The dollar is the vehicle.

Three words will carry the whole talk. The ordered endpoints, SGD to NOK, are the pair. Each exchange along the way is a leg. The full ordered sequence is the route. All three follow the direction of the trade.

Conventional turnover data would show those two legs separately, and stitching them back into one customer exchange takes assumptions. Inside a DeFi transaction, the pool calls are ordered. We see A go into one pool and k come out, then k go into the next pool and B come out. The vehicle is simply there, in the record.

Let me make that concrete with one real transaction.

## Slide 3. One transaction reveals the connected route

On the left, the scale we work at. 475 million pool-level swaps, November 2018 through June this year, across 9 Ethereum deployments: 4 generations of Uniswap, 2 of SushiSwap, Curve, Balancer, and Fluid. In DeFiLlama terms these families cover roughly 87.5% of Ethereum DEX volume over the period.

On the right, one transaction from January.

Fluid turns USDC into USDT, and Uniswap v4 turns USDT into USDe. So the pair is USDC to USDe, and USDT sits in the middle. That is the vehicle, observed, in a route between two other dollar tokens.

Notice something else: even the vehicle role between two stablecoins is itself a stablecoin. Hold that thought.

Now, the earliest exchange design in our panel gives us an unusually clean starting point.

## Slide 4. V2 turns a mandate into a market choice

Uniswap v1 had one rule: every pool paired a token with ETH. If you wanted token-to-token, you went through ETH whether you liked it or not. We recover 217,003 of those forced routes. There, the vehicle is written into the protocol.

In May 2020, v2 removes the rule. Any two tokens can form a pool. From that day on, the vehicle is a market choice.

And yet, 6 years later, 95.5% of single-leg v2 trades still touch a WETH pool, and 97.9% of token combinations first trading in 2026 include WETH.

The mandate is long gone. The liquidity it created is still steering choices. That, in miniature, is the whole formation question: a design change opens the choice, and inherited markets keep shaping it.

## Slide 5. Aggregate dominance can change in three ways

So suppose stablecoin dominance rises in the aggregate. There are only three ways that can happen.

A continuing pair can switch vehicles. Trading can move across continuing pairs, toward the ones that already lean stablecoin. Or pairs can enter and exit, each arriving with a vehicle already attached.

The aggregate line mixes all three, and they mean very different things economically. Mass switching would say incumbency is weak. Entry would say dominance is built into new relationships as they form.

One housekeeping point before the numbers. I group stablecoins as one vehicle family, and keep each token's identity underneath. USDC, USDT, and DAI target the same unit of account with different issuers, redemption, risk, and pools. Think of the Bahamian dollar: pegged 1:1 to the US dollar, still its own currency. Same discipline here.

## Slide 6. Stablecoins regain the routed-value lead by 2026 H1

Here is the broad history, using every route length.

Native assets dominate early. Stablecoins push up in 2022, native assets come back through 2023 and 2024, and then stablecoins take the value lead again in 2025 and hold it into this year. By count, the two families are near parity; by routed value, stablecoins now carry roughly 70%.

I want you to notice the reversal in the middle. This is a rotation that changes direction. Whatever explains it cannot be a smooth technology trend.

The film gives this same history one more dimension.

## Slide 7. Vehicle leadership turns over through time

Let this run. 18 seconds.

Horizontal position is share of routes, vertical is share of routed value, bubble size is how many pairs an asset serves, and each token drags a 6-month trail.

Watch WETH first: large, high, far right. Then USDC gains value weight, later USDT moves sharply, and by the end the stablecoins carry most of the value while WETH stays broad across pairs.

The movement only exists across frames. No single snapshot contains it.

So, the central question: where does that rotation actually come from?

## Slide 8. Pair formation supplies most of the rotation

This identity is the heart of the paper, and it is exact. Take matched January-to-June dates in 2024 and 2026, exact two-leg routes, and split the change in the stablecoin share into the four terms on the slide. They add up. No residual.

Walk the terms with me. Switching inside continuing pairs: −0.1 pp. Essentially zero, and that is not because nothing moves; pairs switch in both directions and cancel almost perfectly. Reallocation across continuing pairs: +8.4 pp. The weight term is small. And the pairs that exist in only one period contribute +17.8 pp, with brand-new pairs alone supplying +20.1 pp.

So the share rises from 16.9% to 42.4%, and about 79% of that rise walks in the door with new pairs. Weighted by dollars the picture is even sharper: inside continuing pairs, nothing.

Dominance here is not won by flipping old relationships. It arrives with new ones. Which raises the obvious question: when a new pair starts on one vehicle, does that choice last?

## Slide 9. A pair carries its first vehicle into later trading

It lasts. This table is the persistence result.

Take every entering pair, drop the entry day itself, and look at two later windows: the first month, and days 31 to 120. Among pairs that trade again, a 10 pp higher stablecoin share on the entry day predicts +8.92 pp more stablecoin use in the first month, and +8.40 pp after that. Near 1-for-1.

A fair worry here: many pairs trade only once or twice on day one, so their entry share can only be 0% or 100%, a very coarse measure. The two lower rows rerun the identical regression keeping only pairs with at least 5, then at least 10, routes on the entry day, where the share is a genuine mix. The estimates edge up toward +10 pp instead of shrinking, exactly what you expect when measurement noise fades. The samples get smaller, so the standard errors widen, but the result holds.

Now, only 19.4% of entrants trade again in the first month, so survival itself could drive the result. We measure that too: entry mix barely changes who trades again. The persistence is in how the survivors trade.

So the first vehicle sticks. The next three slides ask what builds it, and then what can break it.

## Slide 10. Two-leg capital opens the stablecoin contest

First, when does a stablecoin route become possible at all?

We date that event using only yesterday's pool state. Take a pair that has been using WETH, and mark the first day a stablecoin has at least $10,000 of deposited capital on both required legs. 1,618 pairs cross that line before their first stablecoin route.

Once they cross it, adoption is real but unhurried: 38.3% try the stablecoin route within a month, 47.0% within 4 months. And a first try is not a takeover. 62.4% of the first-month adopters come back to a supported stablecoin in days 30 to 119, but stablecoins carry just 8.2% of those pairs' routes in that window.

So viability comes first, and dominance grows slowly on top of it. Now look at what the capital itself is doing around that first route.

## Slide 11. Capital arrives before the first stablecoin route

This is my favourite picture in the paper. Day 0 is the pair's first stablecoin route. The green line is stablecoin capital on the bottleneck leg; the blue line is the matched WETH bridge.

In the week before first use, stablecoin bridge capital climbs steeply, by 0.86 log points, while the incumbent bridge barely moves. After first use, it partly unwinds.

We are careful about what this is. Both providers positioning ahead of demand and traders waiting for usable depth would produce this shape, and the honest reading keeps both. Either way, the liquidity does not follow the first trade. It comes first, and the route follows.

How much liquidity does it take to actually win flow? That is the next slide.

## Slide 12. Relative depth divides trading after the bridge forms

The answer is: it is all relative, leg by leg.

The bars condition on relative depth in the first month after a bridge gains persistent support. While the stablecoin bridge holds less than 0.1× WETH's depth on its bottleneck leg, and most pair-days sit there, it carries 2.4% of routes. Rounding error. Match WETH's depth and it carries 53.0% of the market. Double it, 69.9%.

The estimate on the right says the same thing continuously: 10 pp more of the depth share buys +6.9 pp of route share in the first month, +8.35 pp later.

One caution I want on the record: capital and route demand are jointly determined, so read this as a steep, well-measured association. But it reframes the incumbency we saw at v2. WETH's persistence is largely the persistence of shallow challengers. Where a challenger gets deep, flow moves.

And once both routes are genuinely usable, the contest turns on price.

## Slide 13. Current prices can overturn incumbency

For each trade we quote both alternatives, the best stablecoin route and the best WETH route, on the same pair, the same input, and the exact pool state immediately before execution.

Now take each pair's first sampled date on which both routes are actually usable, so the first real contest between the two vehicle families. Even at that moment, 83.1% of routes still go through the family the pair entered with. Incumbency is real.

But split those contests by who returns more output, and the picture snaps. When the incumbent quotes better, it keeps 93.3%. When the challenger quotes better, retention collapses to 27.2%. Within the same pair and date, challenger price leadership swings retention by 58 pp.

So the stickiness is conditional. Traders are loyal until the prices tell them to stop being loyal.

You can see the same thing in the cleanest possible event: the month the price lead actually changes hands.

## Slide 14. When the price lead flips, route share follows

A crossing month is when the challenger goes from at least 1 bp behind to at least 1 bp ahead, on exact output, within the same pair.

The month before, the incumbent carries 66.9% of the routes. In the crossing month, 38.1%. And compared with the same pair's own earlier drift, the crossing itself accounts for an extra 29.0 pp drop. The flow break sits right on the price break.

Depth plays a different role here. It does little on impact, but it predicts durability: the deeper the challenger's bridge was beforehand, the more likely the new price lead survives the next month.

So prices move flow today, and earlier capital decides whose price leadership lasts. Does any of this loyalty actually cost traders money? Less than you might think, and where it costs is informative.

## Slide 15. Shortfalls cluster in young pairs and small trades

Same exact comparisons, now asking what retention leaves on the table. The shortfall is simply the output you give up: for the same trade, at the same moment, how much more the best route through the other vehicle family would have returned. Zero if your route was already best.

Across all trade sizes, the value-weighted shortfall is about 7.5 bp, and accounting for gas barely moves it. For trades under $1,000, gas takes a shortfall that was already twice as large from 16 to 22 bp. The fixed toll bites the small trader.

Age matters more. Pairs under 90 days old leave 16.8 bp; mature pairs, past a year, leave 2.1 bp. Old routes track the price frontier closely.

I read this as the boundary of the friction: vehicle inertia is mostly a phenomenon of young, thin markets, exactly where formation happens, and it fades as the market matures.

Let me pull the threads together.

## Slide 16. Key takeaways

Here is the whole talk in one chain, left to right.

The rotation came in through the door: new pairs supply 79% of the rise, and switching inside old pairs nets to zero. The vehicle chosen at entry persists, close to 1-for-1 over the following 120 days. Liquidity decides how the contest goes: match the incumbent's depth and you carry 53% of the flow. Prices are what break incumbency, a 58 pp retention swing when the challenger leads. And the shortfall, the output cost of loyalty, fades as pairs mature, down to 2.1 bp after a year.

So currency competition acts at two stages: which vehicle a new relationship builds around, and which vehicle survives later price and depth changes. The first stage is where the action was.

And the middle asset is not a private matter. Every pair routed through it inherits its liquidity and its risks. Which brings me to the part I suspect this audience cares most about.

## Slide 17. Implications for market design and oversight

Now the implications, and I will take them in two slides: first market design and oversight, then monetary policy. If dominance is made at formation, the levers sit at formation too.

For payment systems, and Nexus is the natural example in this room: whoever is allowed to make markets inside the rail decides which currency's markets new corridors inherit. Access policy looks like plumbing and acts like currency policy.

For stablecoin oversight: what we watched on-chain is re-dollarisation through private issuers. Remember the value chart at the start: stablecoins now sit in the middle of roughly 70% of routed value. That is the finding, and it says the exposure to measure is the bridge role, not just how many tokens an issuer has outstanding. What a stress event would do to all the pairs routed through that middle asset is the natural worry, but I want to be upfront that we interpret there; we have not tested a stress episode in this paper. The little buttons on these rows jump back to the slide each claim rests on.

And for anyone promoting an alternative instrument, a non-dollar stablecoin, a tokenised deposit: undercutting prices in existing corridors dethrones nobody. Remember the decomposition: switching inside old pairs netted to zero. Challengers win by being liquid where new trading relationships form. Early liquidity is cheap; late price wars are not.

One line, if you keep only one: liquidity at formation beats price competition later. And that line matters most for the actors on the next slide.

## Slide 18. Implications for sovereign monetary policy

Suppose you are a monetary authority and you want your currency to play an international role. This is the live conversation around the renminbi, around multi-CBDC platforms, around every regional payment initiative. Our findings say the levers are timed, and the window is when new corridors form.

Before anything else, monitor formation. Aggregate dominance follows entry, so the vehicle that newly forming corridors choose is your leading indicator. Aggregate turnover tells you what already happened.

The window itself is when new corridors are born. Swap lines, designated market makers, seeded liquidity on both legs of newly forming corridors: that spending buys a position that persists, because the entry choice sticks near 1-for-1.

After lock-in it gets expensive. Price cuts move flow only where you have already built depth, and the new price lead survives only on top of prior capital.

And one lesson from the very beginning of our sample. Uniswap v1 forced every route through ETH. The mandate ended in 2020; the network it seeded is still steering choices in 2026. Design rules leave liquidity legacies. For a sovereign, that is both the opportunity and the warning.

## Slide 19. What we are asking next

This is very much a living project, so let me end with what we are working on now.

The supply side: who actually provides the bridge capital we saw arriving before first use. We are tracing provider networks across pairs, asking whether the same providers specialise in stablecoin legs, whether growth in an issuer's circulation flows into bridge pools, and how providers respond to fee and incentive changes.

Architecture: Uniswap v4 moves settlement into one shared accounting layer. We want to know whether settlement design itself relocates liquidity, and the v4-versus-v3 contrasts are looking promising.

Incidence: who earns the rents of dominance. Traders, providers, or issuers.

And the one I would most like your reactions to: taking this entry-first account back to conventional FX, where the corridors are currencies and the formation events are trade relationships.

Comments on any of these are very welcome. Thank you.

---

# Backup slide speaking bullets

These are Q&A notes. Usually two or three bullets are enough; stop once the question is answered.

## Appendix map

- Left column: definitions and route construction.
- Middle: robustness and market structure.
- Right: extra empirical results. Jump directly to the relevant page.

## Pool data may start after the user instruction

- Same transaction as the core example, now with the explorer trace visible.
- The user begins with PYUSD; our connected pool component begins with USDC.
- We observe pool execution. Executor inventory and any earlier transfer stay outside the measured route.

## A1. One reconstructed route is one unit

- A connected (i\rightarrow k\rightarrow o) sequence counts as one route.
- (k) occupies one intermediary position; the route contains two legs.
- Dominance can weight that route once or weight the supported dollars it carries.

## How we reconstruct a route from one transaction

- Direct trade, sequential vehicle route, parallel split, and round trip are different objects.
- Sequential flows join when one pool's output funds a later pool input.
- Round trips are removed from the dominance measures.

## A2. Stablecoin backing changes over time

- The stablecoin family is economically heterogeneous: fiat reserve, mixed collateral, on-chain collateral, synthetic.
- Classification follows the backing regime at the time, so a token can change category.
- The headline family result is followed by issuer-level splits where they matter.

## Peg parity preserves currency identity

- The Bahamian dollar trades at one-for-one parity with the U.S. dollar and remains a separately issued currency.
- Likewise, USDC, USDT, and DAI share a unit of account while retaining issuer, redemption, and liquidity differences.
- Stable--stable pools may offer LPs lower divergence loss, while issuer-linked market makers may seed conversion pools; profitability also depends on fees, entry prices, hedges, and peg stress.

## A3. One route universe supports two measurements

- All route lengths describe participation across the whole network.
- Exact two-leg routes isolate one vehicle choice.
- Both come from the same reconstructed routes; the denominator changes with the question.

## A4. State is reconstructed immediately before execution

- Start from a verified pool state, apply events in blockchain order, then quote the route.
- The relevant state is immediately before the transaction.
- A daily closing reserve can already include the trade and gives the wrong counterfactual.

## A5. Each AMM family has a different state vector

- Constant-product pools need reserves and fees.
- Concentrated-liquidity pools also need active liquidity and ticks.
- Weighted pools and v4 hooks require their own pricing inputs. Each family keeps its own pricing equation.

## A5.1. Pool formation determines available paths

- V1 permits ETH-token pools, so ETH is built into the feasible route set.
- V2 lets any two ERC-20 tokens form a pool, making direct paths and alternative vehicles possible.
- Pool creation changes the opportunity set before any router chooses a path.

## A5.2. Executable depth is path-specific

- V3 liquidity can sit outside the current price range.
- Total deposits and executable depth can therefore differ sharply.
- For a given trade size, the quote across the price curve is the relevant object.

## A5.3. Shared accounting moves route settlement

- V4 records deltas inside one singleton and settles net balances after the lock.
- Intermediate token transfers can be netted.
- The route still uses identifiable pools, prices, and liquidity.

## A6. V1 forced routes have an on-chain signature

- Two token-exchange contracts, same transaction, matching ETH out and ETH in.
- That exact ETH flow identifies forced token-to-ETH-to-token routing.
- The exchange registry maps all 1,744 observed v1 contracts to their exact tokens.
- V1 enters the shared route panel; this slide isolates the venue rule that forced ETH intermediation.

## A7. Daily and weekly frequencies answer different questions

- Calendar-day comparisons preserve day-level variation.
- Complete weeks give balanced weekly aggregates.
- Exact future dates keep the stated 30- or 120-day horizon instead of using a convenient nearby date.

## A7b. Stablecoin share rises within each venue scope

- Stablecoin shares rise within single-exchange and cross-exchange routes.
- The rotation appears within each venue scope.
- The bars show the same comparison by intermediary positions and routed value.

## A8. Count versus value weighting

- Count weighting gives each route one unit.
- Value weighting lets economically larger routes carry more weight.
- The same route population underlies both; only the weight changes.

## Vehicle dominance aggregates realised intermediary choices

- One route records who actually sits in the middle.
- Aggregate dominance sums those realised choices.
- Endpoint use, graph position, and execution cost are nearby objects and stay separate.

## A9. Intermediary and route-endpoint use are separate

- Intermediary share asks how often an asset sits inside a route.
- Endpoint share asks how often it appears at either observed end.
- Their difference or ratio describes role specialisation. It is supplementary because observed endpoints can reflect executor inventory.

## A10. Capital, inventory, and depth differ

- Inventory is the exact token balance held by a pool.
- Deposited capital is the broader value supplied by liquidity providers.
- Executable depth is the quantity available for this trade size within a price-impact band.

## A11. Additional venues expand the feasible route set

- More venues can add a better pool for the same vehicle.
- They can also add an alternative vehicle path or a direct path.
- The exact-price exercise opens those sets step by step.

## A11b. Venue scope and vehicle type in 2026

- Cross-exchange routing and stablecoin routing are related but distinct.
- Both single- and cross-exchange routes contain native and stable vehicles.
- This is why venue integration stays separate from vehicle identity.

## A12. References: vehicle currencies and market structure

- These papers provide the vehicle-currency, liquidity, coordination, and network foundations.
- Somogyi is the closest empirical FX comparison; it infers connected vehicle use from separate market records.
- Our route data observe the connection directly.

## A13. References: exchange design

- These papers provide the AMM pricing, routing, and liquidity-provision foundations.
- The route-cost exercise sits closest to the optimal-routing literature.
- Our distinctive object is the vehicle and the formation of the trading network around it.

## A14. WETH stays the graph hub as realised use shifts

- If someone asks about betweenness: WETH still ranks first in all eight annual leg graphs and is 0.925 in 2026 H1.
- Realised use moves much more. WETH falls from 76.2 to 42.4 percent; USDC and USDT together rise from 14.9 to 37.2.
- The graph is unweighted. An edge records leg presence; depth, trade size, and price enter through realised routes.

## A15. Endpoint demand predicts intermediary use

- This asks whether a currency is used in the middle simply because it is popular at the endpoints.
- In column 4, after date and currency effects, one point more endpoint demand maps into 0.98 points more intermediary use.
- Currency effects absorb permanent asset-class differences. The estimate is a within-currency, within-date association.

## A16. Pair composition contains a mechanical component

- A WETH endpoint mechanically rules out WETH as the vehicle. This page isolates that part.
- Removing WETH endpoints reduces the count rotation.
- Net movement inside fixed pairs remains small. The composition result survives the eligibility restriction.

## A17. Endpoint direction splits count and value

- This breaks the rotation down by endpoint type.
- Pairs with two stablecoin endpoints are small by route count and large by routed value.
- USDT supplies essentially all of that high-value two-stable-endpoint channel. Useful issuer heterogeneity inside the stablecoin family.

## A17b. Rotation survives time and endpoint restrictions

- First check: all seven adjacent first-half comparisons. The within-pair term stays between minus 0.4 and plus 1.0 points, including years when stablecoins lose share.
- Second check: remove every pair with WETH or a stablecoin endpoint. Stablecoin share still rises from 1.1 to 9.0 percent by count and from 0.9 to 39.1 percent by routed value.
- Pair entry and exit contribute 7.2 and 33.8 points in that restricted sample.

## A18. Local depth remains informative alongside network reach

- This puts local depth and broader network reach in one regression.
- The deepest available bridge carries 84.1 percent of routes. Weak-leg capital and same-day reach both predict vehicle share.
- Broader reach is observed trading outside the local pair. It is closer to realised network use than unweighted betweenness.

## A19. First-use capital lies in active pools

- This asks whether first use comes from a brand-new pool or a deeper existing pool.
- 92.5 percent of capital at first use sits in pools already active one week earlier.
- Existing pools supply most of the increase. Newly active pools add a smaller piece. Provider anticipation and trader waiting can still line up at the same date.

## A20. Relative depth predicts route flow

- This is the continuous version of bridge competition. Take deposited capital on the weaker leg and compare stablecoin with WETH.
- Below one tenth of WETH depth, stablecoins carry 2.4 percent of routes. At WETH depth, 53.0 percent. At twice WETH depth, 69.9 percent.
- Depth and route demand are jointly determined. The slide establishes a steep, continuous association.

## A21. Usable depth turns support into first use

- A pool can exist and still be economically tiny. So this page asks when a supported stablecoin bridge actually carries its first route.
- Below one tenth of WETH depth, 42.6 percent see first use within 30 days. Once the bridge reaches that threshold, 84.1 percent do.
- Both legs have to deepen. Lower divergence loss and issuer-linked pool seeding are two possible supply channels.

## A22. Bridge capital builds before first use

- Day zero is the first stablecoin route. Over the preceding week, weak-leg stablecoin capital rises by 0.86 log points; the matched increase relative to WETH is 0.78.
- Over the next week it partly unwinds: minus 0.44, or minus 0.46 relative to WETH.
- First use is endogenous. The timing is consistent with capital building into route use, with provider anticipation and trader waiting still combined.
- The main talk now shows this figure; this page stays for detailed follow-up.

## A23. Broader price search mostly changes the venue

- Same pair, same input, pretrade state. We open the available quote set one step at a time.
- A better quote appears for 6.6 percent within used venues, 44.5 percent across all exact venues with the same vehicle, and 46.4 percent after opening other vehicles and the direct route.
- So most price improvement changes the venue. Opening the vehicle set adds 2.0 points, and aggregate stablecoin share moves by minus 1.2 points. These are gross-output quotes over the declared exact venues.

## A24. Persistence is equally strong on busy entry days

- This checks whether a thin entry day creates the persistence result.
- Requiring at least five entry routes gives 9.70 and 9.31 points across the two windows. Requiring ten gives 9.65 and 9.35.
- The entry day stays outside the outcomes, the windows stay disjoint, and the controls match the main persistence specification.
- These rows now also appear in the main-talk table; this page keeps the sample detail.

## A25. Divergence risk helps locate bridge capital

- This is the direct check of the LP-risk interpretation.
- Ten points more prior relative volatility predicts 0.117 lower log bridge capital now and 0.093 lower capital 30 days later. See the divergence-risk appendix table, panel A, columns 1 and 3.
- Stablecoin bridges have higher median volatility, 148.4 against 126.9 percent, and lower risk in 29.4 percent of pair-months. Risk helps allocate capital locally, while the aggregate rotation is much larger than this channel.

# 30-minute talk notes

Spoken notes for the current deck. Short chunks on purpose. The main talk takes about 29 minutes, including transitions and the 18-second film. The backup section has bullets for every appendix page.

## Cover. The Making of Dominant Vehicle Currencies

Hi everyone. Great pleasure to be here.

I have worked with quite a few people at NTU, mainly in computer science. My own background is finance and business economics, and quite a bit of my work sits between finance and CS. So, some familiar faces. Also many new ones. Very nice to be back in Singapore.

Today: dominant vehicle currencies. Evidence from DeFi.

The question is old. If two currencies do not trade easily with each other, what sits in the middle?

The useful thing about DeFi is that we can see that middle asset, route by route. Then a harder question. How does one asset get that role and keep it?

That is the talk.

## Slide 1. A cross-border payment needs someone to make the FX market

Let me start with a familiar payment problem.

A payment provider receives currency A and needs to deliver currency B. The direct A-to-B market may be thin. So the provider goes through a common currency, k.

A to k. Then k to B.

That sounds simple. Economically, it needs two markets. Someone has to quote both legs and hold enough liquidity on both sides.

That is where the vehicle currency comes from. Two liquid legs can bridge a difficult pair.

And the middle position feeds on itself. Trading and liquidity concentrate there. The same currency can become cheaper and easier to use the next time.

In traditional FX, seeing the full connection is difficult. In DeFi, the transaction records it.

So first: what exactly do we see?

## Slide 2. Pool routes reveal the vehicle currency

Since we are in Singapore, take SGD to NOK.

The payment may go SGD to USD, then USD to NOK. USD is the vehicle.

I will use three words throughout. The ordered endpoints, SGD to NOK, are the pair. Each adjacent exchange is a leg. The full ordered sequence is the route. Pair, leg, and route all follow the direction of the trade.

Conventional turnover data normally show the two legs separately. Linking them back to one customer exchange needs extra assumptions.

Inside a DeFi transaction, the pool calls are ordered. We see A enter one pool, k leave, then k enter the next pool and B leave. The vehicle is observed directly.

That is what the route data buy us.

Now let me show one actual route.

## Slide 3. One transaction reveals the connected route

On the left, the scale. 475 million pool-level swaps, from November 2018 through June 2026.

Nine Ethereum deployments: Uniswap v1, v2, v3 and v4; SushiSwap v2 and v3; Curve; Balancer; and Fluid.

How broad is that? In DeFiLlama, these exchange families account for 87.5 percent of Ethereum DEX volume from 2020 through 2026 H1. Broad coverage across the main AMM designs. Other Ethereum venues remain outside the panel.

On the right, one transaction from January 2026.

Fluid changes USDC into USDT. Uniswap v4 changes USDT into USDe. So the pair is USDC to USDe. The two legs are USDC to USDT and USDT to USDe. USDT sits in the middle. That is the vehicle.

The explorer describes a broader PYUSD-to-USDe instruction. Our connected pool route begins at USDC. So we stop at USDC. It may have come from another venue or from the executor's inventory. The pools tell us the connected route they actually execute.

V1 is part of the same panel. We recover the token behind every observed v1 exchange and link its two legs through the shared transaction and matching ETH flow.

That early design gives us a useful institutional starting point.

## Slide 4. V2 turns a mandate into a market choice

Uniswap v1 had a very simple rule. Every pool paired a token with ETH. A token-to-token route had to go through ETH.

We recover 217,003 of those forced ETH routes. Here the vehicle is built into the protocol.

V2 changes the rule in May 2020. Any two ERC-20 tokens can form a pool. Now the market can choose the vehicle.

Yet native-asset pairing remains everywhere. In 2026, 95.5 percent of single-leg v2 trades use a WETH pool. And 97.9 percent of token combinations first traded in that year include WETH.

So the mandate ends. The inherited liquidity remains.

This is the formation question in miniature. A design change opens the choice; existing markets can keep steering it.

## Slide 5. Aggregate dominance can change in three ways

Suppose stablecoin dominance rises. There are three ways that can happen.

One. A continuing pair switches from WETH to a stablecoin.

Two. The pairs continue, but trading moves toward pairs that already use stablecoins more heavily.

Three. Pairs enter and exit with different vehicles.

The aggregate line mixes all three. Table 2 separates them exactly.

One small point before the numbers. We group stablecoins as one vehicle family, then keep each token's identity in the issuer results. USDC, USDT, and DAI target the same unit of account and still have separate issuers, redemption arrangements, risks, and pools. Think of the Bahamian dollar: one-for-one with the U.S. dollar, still a separately issued currency. Currency identity survives a shared unit of account.

All route lengths give the broad history. Exact two-leg routes then give one vehicle choice for the decomposition.

## Slide 6. Stablecoins regain the routed-value lead by 2026 H1

This is the broad history. Every complete route length. Every intermediary position.

Native assets lead early. Stablecoins gain in 2022. Native assets come back in 2023 and 2024. Then stablecoins regain the value lead in 2025 and stay ahead in 2026 H1.

So this is a rotation. It even reverses along the way.

From 2024 H1 to 2026 H1, stablecoins rise from 19.4 to 41.8 percent of intermediary positions. Route participation moves from 19.7 to 46.0 percent. Routed value moves from 35.4 to 71.1 percent. These are the three series behind Figure 1.

Longer routes stay here. If a route contains two intermediary currencies, both count. That is useful because longer routes are economically real. For the native-versus-stable decomposition, I move to two-leg routes so each route has one vehicle.

The film gives the same history one more dimension.

## Slide 7. Vehicle leadership turns over through time

Let this run. Eighteen seconds.

Horizontal position is share of intermediary routes. Vertical position is share of routed value. Bubble size is the number of active pairs. Each token keeps a six-month trail.

Watch WETH first. Large, high, far to the right.

Then USDC gains value weight. Later USDT moves sharply. By the end, stablecoins carry most routed value while WETH remains broad across pairs.

The turnover appears only across frames. That is the point of the film.

Now the central result. Where does the rotation come from?

## Slide 8. Pair formation supplies most of the rotation

Same January-to-June dates in 2024 and 2026. Exact two-leg routes. Stablecoin share rises from 16.9 to 42.4 percent. A 25.5 percentage-point rotation.

Now split it.

Inside the same continuing pair: minus 0.1 point net. Table 2, panel A.

Trading moving across continuing pairs: plus 8.4 points.

Now use each pair's full history to open that last number up.

Pairs first observed after 2024 H1 contribute plus 20.1 points. Reactivation adds 0.2. Vehicle-role turnover inside pairs active in both periods subtracts 0.8. Pair exits subtract 1.7. Those lifecycle terms leave the plus 17.8 period-specific net shown in Table 2, panel A.

So first-observed entry alone supplies 78.9 percent of the total route-count rotation. A further minus 0.5 point comes from the total weight on continuing pairs, so the four decomposition terms add exactly.

The value decomposition in Table 2, panel B is even sharper. The total change is 42.8 points. Zero inside continuing pairs. Plus 26.2 from activity moving across continuing pairs. First-observed entry contributes 21.94 points; reactivation, vehicle-role turnover, and exits reduce the period-specific net to 19.16.

There is switching in both directions. In the count decomposition, pairs moving toward stablecoins add 1.3 points and pairs moving toward WETH subtract 1.4. They almost perfectly offset.

So the aggregate rise comes from where trading grows and which pairs appear. That is a different story from mass replacement inside old pairs.

The natural next question: when a new pair starts with one vehicle, does that first allocation last?

## Slide 9. A pair carries its first vehicle into later trading

Take every new pair with a full 120 days left in the sample. Remove the entry day from every later outcome. Then use two separate windows: days 1 to 30 and days 31 to 120.

Table 3, panel A, columns 2 and 5.

A 10-point higher stablecoin share on the entry day predicts 8.92 points more stablecoin use during days 1 to 30. In the later, disjoint window: 8.40 points more.

So, very persistent. Sticky is fair shorthand here. Sticky in observed route use.

There is a selection issue we can measure directly. Of 157,262 entrants, 19.4 percent trade again during days 1 to 30 and 12.3 percent during days 31 to 120. Panel B puts that survival margin into the regression. A 10-point higher entry stablecoin share raises later trading by 0.30 and 0.98 points. Much smaller than the vehicle-share effect.

The controls include cohort, endpoint type, entry activity, direct-route share, and route complexity. The activity-weighted estimates are 8.55 and 9.00 points. Same message.

What does sticky mean economically? Prices and depth may themselves persist. So now put both vehicle routes side by side, with the same pair, input, and pretrade pool state.

First, though, one step between technical availability and an actual route.

## Slide 10. Two-leg capital opens the stablecoin contest

Here the clock starts from information available the day before. No looking forward to decide when the bridge began.

Take a pair that used WETH earlier and has never used a stablecoin route. The event date is the first day when DAI, USDC, or USDT has at least ten thousand dollars on each required leg, using yesterday's pool state.

There are 1,618 such events.

Within 30 days, 38.3 percent use one of those supported stablecoins. By 120 days, 47.0 percent do.

So enough capital to open both legs comes first. Adoption is gradual.

And first use is not the same as taking over the pair. Among the first-month adopters, 62.4 percent use a supported stablecoin again in days 30 to 119. But stablecoins carry only 8.2 percent of their routes in that later window.

Now use the amount of capital, not just the threshold.

## Slide 11. Relative depth divides trading after the bridge forms

Stablecoin route share rises by 5.60 points in the first 30 days after the event and stays 5.49 points above the prior period during days 30 to 119.

Then compare the two bridges inside the same event. A 10-point increase in the stablecoin share of weak-leg depth predicts 6.90 points more stablecoin route activity in the first month. The later estimate is 8.35 points.

Weak-leg depth is the bottleneck across the two required pools. One deep leg cannot rescue one shallow leg.

This gives us a useful separation. Capital on both legs permits entry. Relative depth helps decide how much flow the new route wins. Neither number needs the later route outcome to date the event.

Once both alternatives are usable, current output gives us a sharper contest.

## Slide 12. Current prices can overturn incumbency

For each trade, we quote the best stablecoin route and the best WETH route. Same pair. Same input. Same pool state immediately before execution. Both routes have to be feasible, and every leg stays below 5 percent own-price impact.

First, the raw split. When the incumbent vehicle gives more output, it keeps 93.3 percent of routes. When the challenger gives more, incumbent retention falls to 27.2 percent.

Then the regressions in Table 6.

Column 1: stablecoin price leadership raises stablecoin choice by 57.59 percentage points, within the same pair and date.

Column 2: challenger price leadership lowers incumbent retention by 58.08 points. Same pair and date. Standard error 2.82 points.

So the incumbent is sticky. Current price leadership can overturn it.

That is the broad contest. Now go back to the first time both vehicle families can compete after pair entry.

## Slide 13. The entry vehicle carries 83.1% of first-contest routes

This is a narrower and cleaner question. What happens at the first sampled monthly date when the same trade can use either vehicle family?

The entry family still carries 83.1 percent of routes. Give each pair equal weight, and it is 84.4 percent. Table 5, panel A.

There is an important scope point. We begin with 118,447 material entrants. Only 580 reach this strict sampled exact contest. Exact pool states are sampled monthly, and both paths must pass the same quote rules. So this result belongs to that observed opportunity set.

Now panel B. On the common V2-capital sample, a 100-basis-point exact-output advantage for the entry family adds 10.31 points to retention. Add prior capital, and it is 10.20. Basically the same.

The capital coefficient itself is 1.85 points for a 10-point shift, with a standard error of 4.58. Here, current output explains survival. Earlier V2 capital adds little once output is in the same model.

That is one contest date. We can also watch the same pair when the price lead actually changes hands.

## Slide 14. When the price lead flips, route share follows

A crossing means the challenger moves from at least one basis point behind to at least one basis point ahead. Same pair. Consecutive months. Exact output on both sides.

Immediately before the crossing, the incumbent carries 66.9 percent of routes. In the crossing month, 38.1 percent. Table 7, panel A.

The matched comparison in panel B, column 4 is minus 29.0 points. It compares the actual crossing with the same event's earlier move, from month minus three to minus two. So the route-share break lines up with the price-rank break.

Depth is doing something different. Its immediate coefficient in column 1 is tiny. In column 2, a 10-point larger challenger share of prior weak-leg capital raises the chance that the new price lead lasts one month by 3.70 points.

So prices move the flow now. Earlier depth helps the new lead stick.

Then the consequence. What does using the lower-output vehicle cost?

## Slide 15. Output shortfalls concentrate in younger pairs

Use the same contestable routes behind Table 6.

12.9 percent use a vehicle family that returns at least one basis point less than the other family.

Conditional on that choice, the median shortfall is 27.2 basis points. The 90th percentile is 171.5. Across all contestable routes, weighting by input value, the shortfall is 7.4 basis points.

Age changes the magnitude. The value-weighted shortfall is 16.8 basis points for pairs under 90 days old, 19.0 for pairs aged 90 to 364 days, and 2.1 after one year.

So younger relationships can leave meaningful output on the table. Among mature relationships, current prices still move route choice, and the average cost of retaining the incumbent is much smaller.

I read this as an economically useful boundary on stickiness. The first vehicle predicts later use. Current prices can overturn it. Earlier depth is especially informative about whether a new price lead lasts.

That brings me back to the larger point.

## Slide 16. Dominance grows when new pairs choose a vehicle

Let me leave you with three things.

First, dominance moves through pair entry. Between 2024 H1 and 2026 H1, net switching inside continuing pairs is almost zero. Pairs first observed after 2024 H1 contribute 20.1 points, or 78.9 percent of the total route-count rotation. Activity moving across continuing pairs adds another 8.4 points.

Second, vehicle identity persists after pair entry. A 10-point higher entry share maps into roughly 8 to 9 points more use over the next four months.

Third, persistence has structure. Current output explains survival at the first exact contest. When the price lead flips, route share follows, and earlier challenger depth predicts which lead lasts. The output shortfall is concentrated among younger pairs.

Dominance carries the history of market formation. New trading relationships form, liquidity gathers on both legs, and later prices either reinforce or challenge that first vehicle.

That is the connection back to traditional currency competition and cross-border payments. The vehicle used when a new relationship forms can shape the markets that grow around it.

Thank you.

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
- They can also add a different vehicle path or a direct route.
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
- The graph is unweighted. One edge says a leg exists. It says little about depth, trade size, or price. So centrality is useful, then the realised routes take over.

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

## A23. Broader price search mostly changes the venue

- Same pair, same input, pretrade state. We open the available quote set one step at a time.
- A better quote appears for 6.6 percent within used venues, 44.5 percent across all exact venues with the same vehicle, and 46.4 percent after opening other vehicles and the direct route.
- So most price improvement changes the venue. Opening the vehicle set adds 2.0 points, and aggregate stablecoin share moves by minus 1.2 points. Quotes are before gas and cover the declared exact venues.

## A24. Persistence is equally strong on busy entry days

- This checks whether a thin entry day creates the persistence result.
- Requiring at least five entry routes gives 9.70 and 9.31 points across the two windows. Requiring ten gives 9.65 and 9.35.
- The entry day stays outside the outcomes, the windows stay disjoint, and the controls match Table 3.

## A25. Divergence risk helps locate bridge capital

- This is the direct check of the LP-risk interpretation.
- Ten points more prior relative volatility predicts 0.117 lower log bridge capital now and 0.093 lower capital 30 days later. See the divergence-risk appendix table, panel A, columns 1 and 3.
- Stablecoin bridges have higher median volatility, 148.4 against 126.9 percent, and lower risk in 29.4 percent of pair-months. So risk helps allocate capital locally; it cannot carry the aggregate stablecoin rotation.

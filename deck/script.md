# 30-minute talk notes

These notes follow the current core deck. The tone is spoken on purpose. Short bridges, fragments, a little repetition. The backup section covers every appendix slide.

Timing target: cover and slides 1--3, 5 minutes; slides 4--8, 7 minutes; slides 9--11, 7 minutes; slides 12--17, 9 minutes; slide 18, 2 minutes. The 18-second film and normal slide transitions are included in those blocks.

## Cover. The Making of Dominant Vehicle Currencies

Hi everyone. Great pleasure to be here.

I have worked with quite a few people at NTU, mainly in computer science. My own background is finance and business economics, and much of my work sits between finance and CS. So, familiar faces, familiar names, and also many new ones. Very nice to be back in Singapore.

Today: dominant vehicle currencies. Evidence from DeFi.

The basic question is old. If two assets do not trade easily with each other, what sits in the middle? The useful thing about DeFi is that we can actually see that middle asset, trade by trade. And then we can ask a second question: how does one asset get that role in the first place?

That is the talk.

## Slide 1. A cross-border payment needs someone to make the FX market

Start with a familiar payment problem.

A payment provider receives currency A and needs to deliver currency B. It may have no deep A–B market and may not hold B. So it goes through a common currency, (k).

This is more than drawing a network. Someone has to quote both legs and hold enough liquidity on both sides. A to (k). Then (k) to B.

That is why I start with the market maker. A vehicle currency is useful because two liquid legs can bridge a difficult pair.

And winning that middle position matters. Trading and liquidity concentrate in the vehicle. That can make the same currency cheaper and easier to use the next time.

Now, in traditional FX, seeing that full connection is difficult. In DeFi, the route is recorded inside the transaction.

## Slide 2. Pool routes reveal the vehicle currency

Since we are in Singapore, take SGD to NOK.

The payment may go SGD to USD, then USD to NOK. USD is the vehicle. The ordered endpoint pair, which I will just call the pair, is SGD to NOK. The legs are SGD to USD and USD to NOK. The full sequence is the route. Pair, leg, and route all follow the direction of the payment.

Conventional turnover data normally show the two legs separately. Linking them back to one customer exchange needs extra assumptions.

Inside a DeFi transaction, the pool calls are ordered. We see A go into one pool, (k) come out, then (k) go into the next pool and B come out. So the vehicle is observed directly.

That is the measurement advantage. Next, the scale.

## Slide 3. The route panel links pool-level swaps

We collected 475 million pool-level swaps, across 2,798 calendar dates, from November 2018 to June 2026.

Nine Ethereum deployments: Uniswap v1, v2, v3 and v4; SushiSwap v2 and v3; Curve; Balancer; and Fluid.

V1 is in the same route panel. Its events name the exchange contract. The exchange registry gives us the token behind that contract, so all 1,744 v1 exchanges in the daily data now have an exact token address and symbol.

Within a transaction, the shared hash and matching ETH amount link the token-to-ETH and ETH-to-token legs. So the early forced-ETH routes and the later market routes now sit in one continuous panel. We still look at v1 separately when the protocol rule itself is the question.

What exactly do we observe? The connected sequence of pool trades. That sequence can begin after the user's broader instruction begins.

How representative is this? We selected the exchange families for their historical Ethereum volume. In DeFiLlama they account for 87.5% of total Ethereum DEX volume from 2020 through the first half of 2026. The nine deployments span the main AMM designs: constant product, concentrated liquidity, stable swap, weighted pools, the v4 singleton, and Fluid's integrated liquidity. Other Ethereum venues remain outside the panel.

## Slide 4. Inside the pools, USDT links USDC to USDe

Here is a real transaction from January 2026.

The explorer describes a PYUSD to USDe instruction. The connected pool route we observe begins with USDC. Fluid turns USDC into USDT; Uniswap v4 turns USDT into USDe.

So, inside the observed route, the pair is USDC to USDe. The legs are USDC to USDT and USDT to USDe. USDT is the vehicle.

What happened between PYUSD and USDC? The data allow two possibilities. Another trade outside our exchange panel, or USDC supplied from the executor's inventory. We stop at USDC because that is where the pool evidence begins.

This example also makes the language concrete. Pair, legs, complete route. All directed by the token flow.

## Slide 5. The full route and the one-vehicle choice answer different questions

We use the routes in two ways.

First, all route lengths. Every intermediary position counts. If a route uses two intermediary currencies, both appear. These shares divide all the intermediary work, so they sum to 100 percent across currencies.

We also report route participation: the fraction of complete routes containing each currency. Those shares can add above 100 percent because one long route may contain several intermediary currencies. That is fine; it is a presence measure.

Second, the exact two-leg route. One route, one intermediary, one vehicle choice. This is the sample used to decompose stablecoin against WETH use. A longer route can contain both WETH and a stablecoin, so there is no single native-or-stable choice to assign to that route.

Why stablecoins and the native asset? They are the two broad vehicle families present throughout the sample. The all-route figure still shows the other categories.

One small distinction matters here. A one-for-one peg can align prices without erasing currency identity. The Bahamian dollar is pegged to the U.S. dollar and remains a separate currency. In the same way, USDC, USDT, and DAI target the dollar but keep separate issuers, redemption arrangements, risks, and pools. We group their vehicle role here and keep the token identities in the issuer results.

With the measures clear, we can ask where aggregate dominance comes from.

## Slide 6. Aggregate dominance can change in three ways

Three possibilities.

One: the same continuing pair switches its vehicle.

Two: the pairs continue, but trading moves toward pairs that already use one vehicle more heavily.

Three: pairs enter or leave. Entrants bring the vehicle they use in the later period; exits remove the vehicle they used in the earlier period. The decomposition records the net effect of both.

The aggregate series alone mixes all three. The decomposition separates them exactly.

Before that result, one historical reason to expect persistence: Ethereum's early pool architecture built the network around ETH.

## Slide 7. Protocol design changes the route set in steps

The market does not arrive all at once.

V1 begins in November 2018. ETH sits inside every token-to-token route because every pool pairs one token with ETH.

V2 arrives in May 2020 and lets any two ERC-20 tokens form a pool. Vehicle choice becomes possible.

V3 arrives a year later and lets liquidity providers concentrate capital around selected prices. Then v4, in January 2025, puts pools inside one singleton and settles balances after the route.

The key break for us is v1 to v2. The rule forcing ETH disappears. The inherited market structure remains.

## Slide 8. Native-asset pairing persists after it becomes optional

In Uniswap v1, token-to-token trading had to pass through ETH. We recover 217,003 such trades. Native intermediation was written into the protocol.

V2 removed that rule. Any two tokens could form a pool. Yet WETH pairing remained overwhelming: 95.5 percent of single-leg v2 trades use a WETH pool in 2026, and 97.9 percent of token combinations first traded in 2026 include WETH.

So architecture opens a choice. The data show what followed: WETH pairing remained pervasive after any two ERC-20 tokens could form a pool. Now watch the stablecoins begin to challenge it.

## Slide 9. Stablecoins regain the routed-value lead by 2026 H1

This uses every complete route length.

Native assets lead early. Stablecoins gain in 2022. Native assets come back in 2023 and 2024. Then stablecoins take the routed-value lead again in 2025 and remain ahead in 2026 H1.

So the path is uneven. The leadership actually turns over.

Among all intermediary positions, the stablecoin share rises from 17.2 percent in 2024 to 41.8 percent in 2026 H1. Route participation tells the same story: 17.6 to 46.0 percent. Longer routes stay in this measure and carry part of the result.

The value shift is even larger. The short film makes the turnover easier to see because frequency, value, and pair breadth move at the same time.

## Slide 10. Vehicle leadership turns over through time

Let this run for 18 seconds.

Horizontal position is route-count share. Vertical position is supported-value share. Bubble size is the number of active pairs. The trail keeps only six months. Along the bottom, the v1, v2, v3, and v4 markers keep the protocol changes in view.

Watch WETH first. Large, high, far to the right. Then USDC gains value weight. Later USDT rises sharply. By the end, the stablecoin family carries most supported value even while WETH remains broad across pairs.

The transition lives in the movement across frames.

Now the central question: did existing pairs switch, or did trading form around different pairs?

## Slide 11. Pair formation supplies most of the rotation

This is the central decomposition. Same January-to-June dates in 2024 and 2026.

Pooling route activity over these matched dates, stablecoin share rises from 16.9 to 42.4 percent. A 25.5 percentage-point rotation. If I instead give each day equal weight, the endpoint is 42.1 percent and the change is 25.2 points. The conclusion is the same; pooling is what lets the components add exactly.

Inside continuing pairs, positive and negative switches almost exactly offset: minus 0.1 point net.

Activity shifting across continuing pairs adds 8.4 points.

Pairs present in only one period add 17.8 points. The largest component. That number is net of both entry and exit: new pairs bring their 2026 vehicle into the comparison, while disappearing pairs remove their 2024 vehicle.

Gross switching is active in both directions. Many continuing pairs move toward stablecoins and many move back toward WETH. Those movements nearly cancel. The aggregate rise comes from where trading grows and which relationships appear or disappear.

That changes the economic story. Dominance can move because the network grows around a vehicle, even when established relationships show little net replacement.

Two quick checks. Run the same decomposition for every adjacent first half from 2019 to 2026: the within-pair term stays between minus 0.4 and plus 1 point, including the years when stablecoins lose share. Then remove every pair with WETH or a stablecoin at either endpoint. Stablecoin share still rises from 1.1 to 9 percent by count and from 0.9 to 39.1 percent by value. So neither the chosen endpoints nor mechanical vehicle eligibility creates the composition result.

The next question is whether the first vehicle of a new relationship lasts.

## Slide 12. The first vehicle is sticky

Take a newly observed pair. Look at its stablecoin share at entry. Then follow the same pair.

One percentage point more stablecoin use at entry predicts 0.86 points more over the next 30 days and 0.74 points more over 120 days.

Large persistence. Same pair, long after the first routes. In ordinary language: sticky.

“Initial” simply means the first observed routes of that new pair. The pair is new to the data; its first vehicle identity is still well defined.

The estimates control for entry size, cohort, endpoint type, direct routing, and route complexity. I use sticky as shorthand for predictive persistence in the observed routes. Trader habit is one possible force. Persistent depth, prices, and venue access are others. The first vehicle is an equilibrium outcome.

Entry predicts later use, but the same pattern can contain deep and shallow challenges. So next we measure the two legs behind the challenger.

## Slide 13. A shallow stablecoin bridge attracts little route flow

A stablecoin route needs two legs: source to stablecoin, then stablecoin to destination. The weaker one is the bottleneck.

When the best stablecoin bridge has less than one tenth of WETH's depth, stablecoins carry only 2.4 percent of routes.

At least as deep as WETH: 53 percent.

Twice as deep: almost 70 percent.

Useful bridge support rises continuously with depth. A pool can carry positive capital and still be far shallower than the incumbent. Depth makes the contest meaningful.

So the measurable part of the persistence story is depth. A challenger can have positive capital and still sit near zero on the competitive spectrum.

## Slide 14. Usable depth turns support into route use

Now take the same point in event time.

Among bridges below one tenth of WETH depth, 42.6 percent carry their first stablecoin route within 30 days. Once the bridge reaches that threshold, 84.1 percent do.

That is a big gap between technical support and economically usable support. Both legs have to become deep enough.

There are also two plausible supply-side reasons stablecoin links can form. While both pegs hold, a stablecoin--stablecoin pool has much less relative-price movement than a stablecoin--WETH pool. For a constant-product LP, that means less loss versus holding, usually called impermanent or divergence loss. Lower risk may make those links attractive to supply. A peg break can reverse the comparison.

A new stablecoin also benefits from a liquid conversion link into incumbent dollar tokens. An issuer or affiliated market maker may seed that link. Both ideas are interpretations. Deposited capital tells us how much was supplied. Provider identities, funding relationships, entry prices, fees, hedges, and expectations would be needed to separate them and measure profitability.

Next: does depth arrive before or after first use?

## Slide 15. Bridge capital builds before first use

Day zero is the first observed use of a supported stablecoin. The pool bridge already exists before then.

Over the preceding week, capital on the weaker stablecoin leg rises by 0.86 log points. Relative to the matched WETH bridge, the increase is 0.78.

Human version: liquidity builds, then the first routed trade appears.

After first use, stablecoin bridge capital falls by 0.44 log points over the next week, or 0.46 relative to WETH. So the picture is a build-up into first use and then a partial unwind.

The appendix split tells us where that capital comes from. About 92.5 percent is in pools already active one week earlier. So this is mainly an existing bridge getting deeper, with a smaller contribution from newly active pools.

The timing is suggestive. Providers may anticipate route demand. Traders may wait until the bridge is usable. Both can happen together. First use and capital are jointly determined, so I read the figure as formation around a route, with the two forces still combined.

The useful takeaway: vehicle competition moves continuously with depth, and capital is concentrated around the moment the new route first carries flow.
One last rival: perhaps the observed vehicle survives only because the router missed a better price.

## Slide 16. Price competition usually changes the venue

Here we reconstruct the exact state immediately before each transaction and reprice the same input. Then we widen the set of alternatives one step at a time.

Among venues already used by the route, 6.6 percent have a same-vehicle quote at least one basis point better.

Open all exact venues: 44.5 percent. Lots of venue competition.

Then open every named vehicle and the direct route: 46.4 percent. Only another 2 points.

If every route takes its best quoted path, stablecoin vehicle share moves by minus 1.2 percentage points.

So the big jump comes from searching more venues with the same vehicle: 6.6 to 44.5 percent. Letting the route change its vehicle, or go direct, adds only 2 more points. And even if every route takes its best quoted path, aggregate stablecoin vehicle share moves by only 1.2 points.

Every observation has its own exact counterfactual quote. The three steps show how often each wider opportunity set beats the executed route by more than one basis point.

Now narrow the price comparison to the two vehicle families. Same pair, same input, same pretrade state. Best stablecoin path against best WETH path. Both have to be executable.

## Slide 17. Current prices discipline persistence

This is the direct comparison.

When the entry vehicle still gives more output, it carries 93.4 percent of routes.

When the other vehicle gives more than one basis point more output, entry-vehicle use falls to 22.4 percent. Pair-day weighting gives almost the same split: 94.6 against 24.5.

So the first vehicle is sticky in the reduced-form sense. It predicts later use. Current price leadership disciplines that persistence. Depth and price make an established vehicle contestable.

That brings the pieces together. New relationships inherit a vehicle. Two-leg depth makes the alternative usable. And current prices determine whether the first vehicle keeps the route.

## Slide 18. New pairs reshape currency dominance

Let me leave you with the bigger point.

Three findings.

First, pair formation and activity shifting across continuing pairs carry most of the aggregate rotation. Net switching inside continuing pairs is tiny.

Second, the first vehicle predicts later use while its path remains competitive. Current prices discipline persistence.

Third, two-leg depth makes a bridge competitive. Stablecoin route use rises sharply as the weaker leg approaches WETH depth, and capital builds into first use.

That is what I would carry back to traditional currency competition. Aggregate dominance reflects the vehicle used inside established relationships and the one chosen when new relationships form. Early presence and deep two-sided markets matter alongside quoted prices.

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

## A2.1. Peg parity preserves currency identity

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
- Weighted pools and v4 hooks require their own pricing inputs. One formula cannot be imposed on all families.

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
- Exact future dates keep the stated 30- or 120-day horizon; they do not substitute a convenient nearby date.

## A7b. Stablecoin share rises within each venue scope

- Stablecoin shares rise within single-exchange and cross-exchange routes.
- So exchange integration alone does not generate the rotation.
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

- WETH ranks first in betweenness in all eight annual leg graphs and remains at 0.925 in 2026 H1.
- Its realised intermediary-position share still falls from 76.2 to 42.4 percent; USDC and USDT together rise from 14.9 to 37.2.
- An unweighted edge records an available connection. It does not record route depth or execution cost, so graph position alone cannot explain realised use.

## A15. Endpoint demand predicts intermediary use

- (I_{a,t}) is currency (a)'s intermediary share on date (t); (D_{a,t}) is its endpoint-demand share.
- With date and currency effects, one extra percentage point of endpoint demand maps into 0.98 points of intermediary use.
- Currency effects absorb permanent asset-class indicators, so those rows disappear in model 4.

## A16. Pair composition contains a mechanical component

- WETH at an endpoint rules out WETH as the intermediary.
- Removing those pairs reduces the count rotation sharply.
- Fixed pairs still show only small net stablecoin movement, so the central composition result survives the eligibility issue.

## A17. Endpoint direction splits count and value

- Other pairs supply the largest count and value contribution.
- Pairs with two stablecoin endpoints are small by count and large by value.
- USDT supplies essentially that entire high-value two-stable-endpoint channel.

## A17b. Rotation survives time and endpoint restrictions

- Across all seven adjacent H1 comparisons, the within-pair term stays between minus 0.4 and plus 1.0 percentage points.
- After removing every pair with WETH or a stablecoin endpoint, stablecoin share rises from 1.1 to 9.0 percent by count and from 0.9 to 39.1 percent by supported value.
- Pair entry and exit contribute 7.2 points by count and 33.8 points by value in that restricted sample.

## A18. Local depth remains informative alongside network reach

- The deepest supported bridge carries 84.1 percent of routes.
- Local weak-leg capital and broader same-day reach both predict route share.
- Betweenness asks a related graph-position question; this regression uses observed reach outside the local pair.

## A19. First-use capital lies in active pools

- 92.5 percent of capital at first use sits in pools that were already active a week earlier.
- Providers mainly deepen existing pools; newly active pools add a smaller route-formation channel.
- The data show where capital appears, while trader waiting and provider anticipation remain observationally close.

## A20. V4 participation broadens after internal routing

- More internal same-asset routing predicts near-term activity from already active origins.
- Later, it predicts activity from origins first seen after the measurement date.
- Persistent volatility strengthens the later association. Origins are accounts, so beneficial ownership remains unknown.

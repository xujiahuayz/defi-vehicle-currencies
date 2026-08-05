# Node E screen: is "the role persists through dominance" a finding or an artefact?

A candidate result is rejected at design time when its sign is guaranteed by construction. The previous estimand failed a version of this test late, after it had been reported, so this one is screened before it is written up. Four ways the persistence result could be mechanical, in descending order of how much they threaten it.

## 1. The router did not see what we price, because we price the wrong instant

This is the most dangerous and it is not yet closed. A smart-order router quotes at a specific block and executes in the next. The panel prices at the end of an hour. If a route was cheapest when the router chose and dominated by the time the hour closed, the panel records a dominated route that the router had no way to avoid, and persistence would be an artefact of timing rather than a behavioural fact.

The magnitude is knowable and has already been measured once in this project for a different reason: intra-day state movement on the deepest USDC/WETH pool ran at a median 0.345% with a worst hour of 1.04%, against route-cost differences of tens of basis points. So the mispricing from an hour of staleness is the same order as the effect. **This must be closed by re-pricing each realised route at its own block rather than at its hour boundary**, which the data supports because every swap carries `blockNumber` and Uniswap v3 and v4 carry `sqrtPriceX96` per swap. Until it is closed the persistence result is not safe.

Note what this does NOT threaten. The dominance FREQUENCY is a statement about the state at a moment and survives, since it does not require the router to have been able to act. Persistence is the claim that needs the router to have had a choice.

## 2. Our counterfactual sees venues the router did not, or misses ones it did

If the panel's best direct route runs through a venue the router did not query, then the route was not dominated from the router's position. Six venues are priced and the router population is fragmented, so this cuts both ways. It is bounded rather than eliminated: `docs/venue-coverage-bounds.md` shows the remaining gaps are Curve crypto-pools and Balancer's linear families, both of which would make the direct alternative BETTER and therefore raise measured dominance, so the frequency is a floor. For persistence the sign is less clean, because a router that could not see a cheaper direct pool is a router that had no choice to make.

## 3. The router optimises something other than quoted output

Quoted output is not the router's objective. It also weighs gas, MEV exposure, failure probability and, for aggregators, private orderflow. A route dominated on quoted output may be preferred on any of those, and that would be a rational choice and not persistence. Gas is handled, since the all-in comparison charges the extra hop at receipt-measured units. The others are not observable here and are a stated limit rather than a controlled confound. This is the strongest referee objection to the persistence claim and the honest response is to name what fraction of the persisting volume could plausibly be explained by each, which is not yet done.

## 4. Persistence is definitionally close to "shares move slowly"

If a pair's routing shares are sticky for any reason, a vehicle dominated today will still carry volume tomorrow, and calling that persistence adds nothing. This is the one screen the result already passes, because the comparison is not against zero but against the same vehicle's share when NOT dominated: native 68.6% against 39.4%, stable 43.4% against 28.2%. Shares move a great deal on dominance, and the finding is that they do not move all the way. A definitional stickiness story predicts no differential at all.

## What this screen licenses today

The dominance frequency at 27.2% is admissible now. It is a statement about a state, it does not require the router to have had a choice, and its coverage gaps are signed as a floor.

The persistence result is admissible only as a cross-sectional fact about share differentials, and only with threat 1 named as open. It does not license the word hysteresis, which needs the displacement arm, and it does not license a causal reading, which needs threat 3 bounded.

## The order of work this implies

Re-price realised routes at their own block, which closes threat 1 and is the highest-value remaining piece of empirical work. Then run the displacement arm on the full rebuild, which is what turns persistence into an asymmetry claim. Then bound threat 3 by decomposing the persisting volume against what gas, failure risk and split routing could each account for.

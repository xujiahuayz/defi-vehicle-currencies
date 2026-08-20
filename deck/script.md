# Cover page

Hi everyone. Great pleasure to be here. I collaborate actively with researchers from NTU, mainly from the CS . But my background is actually business economics / finance and work in the interdisciplinary field of fiance and CS, and at UCL I'm also a member of the financiao computing research group, which again is interdispliniary as the name implies.. So it's great to be hear see both a lot familar faces and familar names in the agenda as well as new faces and new names.

Today I'm taking about Dominant Currencies in DeFi with a partilcular focus on vehicle currency dominance.

<!-- not sure if we should have the tagline on the left already - feels difficult to embed in the script and feel like a spoiler? -->

<!-- not sure how to describe the liquidty provider problem -->

# Pool routes
<!-- i want to use singapore dollar because we are in singapore -->
Dominant currency is a well-researched field in traditional finance. However, data availability is a big issue in tradfi. For example, if you are excahnging Singapore Dollar to, say Norwegian kron, a financial insitution in singapore might exchange your singapor dollar to us dollar, and then send the us dollar to a norwegian financial instituion who will happily accept us dollar and return a commonsurate amount of norwegian krown. So here the US dollar is the viehcle currency, bridging the exchange between singapore dollar and norwegian kron. 
However, the issue is, you might be able to obtain data from the financial institution in singapore, or in norway, or even both, but those data would come in siloed, and without heauristics and quite some assumptions, you wouldnt be able to link two trades as one larger transaction. 
<!-- is there truth in it? -->
With DeFi where we can decentralized exchanges whose data are publicaly available, this is no longer an issue. If you are swapping a token, say Aave token, with, say Sushi token fromm Sushi, you'd be able to observe whether it is a direct swap, or a bridged swap, usually through a stablecoin like USDT or USDC, or a native token, like ETH on Ethereum.

# Route Panel

And the data we've collected is massive, We fetched every single swap transaction on Ethereum of major exchanges, including different versions of Uniswap, Sushiswap, Curve, Balancer and Fluid -- combined they cover x% of all the swaps on Ethereum. Thats 472 million pool-level swaps, basically a leg across over 2 thousand days.

We fetched data from the Graph and Dune, as they provide structured data that is much easier to parse compared with fetching raw from Ethereum node.

Uniswap v1 is exluced in many analyses because we are not able to recover endpoint pair identities.
<!-- can you expand on that? why for other exchanges we can and for uniswap v1 we cannot? in the paper you said you can force it, but then also said you cannot renconstruct .. why? -->

# Pool data

Because we didn't get all the swap data so omission is unavoidable. For example, in this case a suer started to trade with PYUSD, and the PYUSD to USDC swap occured outside of our exchamnge universe, so we dont have transactions as such in our record. Afterwards, starting from USDC, the trade goes through USDT and then finally USDE, with the former leg taking place in the dex Fluid, and the latter in Uniswap v4 - so we have both of these in our data. We'd then record USDT as the vehicle currency and USDC as endpoint currency. Whereas in fact USDC here is also a vehicle currency, so there will be some underestimation, but because of the large coverage of the data, we belive the underestimation is neglible and because it spreads across different vehicle currencies, it would not be biased.

<!-- question: do we have multi-leg swaps included in the analyses? i see i in the early paper you said mainly two-leg swaps? needs to specify in slides-->

# Viehicle dominance

So how exactly do we measure vehicle dominance? Simple, for each asset k, we measure the share of swaps that are bridged by k among all the intermediated swaps 
<!-- is it true? -->

We look at the share both in terms of count and in terms of value.

For value-weighted share in particular, we look at comparable trades in terms of xxxx.

<!-- in earlier version we had betweenness centrality also as a measure - any particular reason that got retired? -->

# Architechture

Before diving into the results, it is important to understand some of the mechanical, architectural changes that took place in decentralized exchanges as they are highly relevant to vehecle dominance.

With Uniswap V1, each liquidity pool must be paired with ETH (or WETH?) So as you can imagine, at Uniswap v1 era, ETH was pretty much the sole vehicle currency. So unless you are swapping from to to ETH, you always have to go through ETH as a vehicle currency - it's imposed.

With Uniswap V2, the restriction is lifted -- any two tokens can form a pair. However, as you can imagine, liquidity providers would just go and establish a random liquidity pool of some random token pairs - they need to think about demand, think about trading volume as that would decide the liquidy provision profitability. So liquidity providers still tend to have at least one common / popular token in a liquidity pool, usually the native currency like ETH on ethereum or stablecoin like USDC / USDT.

With V3, the liquidity provision can be concentrated in a particular range, also fee tiers are introduced, so the same token pair can form two different liquidity pools due to different fee tiers. 

With V4, flash accounting is introduced, that means with a typical trading route A to k to B, previously some amount of token k would need to be swapped out of liquidity pool A-k, and then swapped into liquidity pool k-B, now the physical move doesnt need to take place anymore because they all share the same accounting.
<!-- not sure about v4 description -->

<!-- unsure about four economic forces slide - do we have findings on each ot them or how do we introduce the slide? -->

# native-asset pairing 

<!-- unsure how to introduce the slide -- is it about demand? it doesnt seem to be about liquidity provision or viehcle token in particular? and how can it be transitioned to the next slide? -->

# Stablecoin gain

<!-- you have each data point representing a year but given 2026 only has half year why dont you do one data point per half year? -->

# USDT

<!-- again i dont understand why we use intermediary minus endpoint .. two reasons why it's weird (1) as mentioned (and you might have explained but i missed), imagine 2 extreme cases, Token A is just cereated so never used as vehicle or endpoint, so it has 0 vihcle in excess of endpoint, token B is a super popular vhecle token, but even more used as endpoint, so it has negatvie viehcle in excess of endpoint.. so how do you compare A and B's value? A has a higher value than B but what does that even mean? how do you interprete this value? (2) you had the PYUSD example, where USDC was actually the  vehicle but due to data coverage its considered as endpoint, so it gets penalized twice! its not counted as vehicle and then get decuted as considered (wrongly to be endpoint!)   -->

# Intermediary demand

<!-- whats the subscript a, and t? how do we interprete native currency and stablecoin indicator's coefficients -->

<!--  -->




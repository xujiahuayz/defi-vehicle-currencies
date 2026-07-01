# Olga Klein Lens - Experiment Menu for the Vehicle-Currency Paper

Purpose: preempt likely comments from Olga Klein, given her work on liquidity
provision, liquidity concentration, intraday liquidity commonality, and informed LP
behavior. This file records concrete experiments to consider before or during a
Kathy/Olga discussion.

## Relevant Olga Klein Work Checked

### Caparros, Chaudhary, and Klein - Blockchain scaling and liquidity concentration on decentralized exchanges

Core idea: LPs actively manage adverse-selection risk. Lower repositioning costs
on Arbitrum/Polygon make LPs update more often and more precisely, which
concentrates liquidity near the market price and lowers small-trade slippage.

What Olga may ask:

- Is vehicle liquidity actively managed, or are we only measuring passive TVL?
- Does the vehicle role strengthen when LPs can reposition more cheaply?
- Is the vehicle-route advantage coming from concentrated executable liquidity near
  the current price, not just total pool size?
- Are small and large trades affected differently?

Experiments to add:

1. **Vehicle-pair liquidity concentration**
   - Unit: pool-day or pool-hour.
   - Sample: pools with WETH, USDC, USDT, DAI, WBTC, and top route vehicles on one side.
   - Measures: active liquidity within 10, 50, 100, and 200 bps of current price,
     scaled by TVL.
   - Test: compare concentration in vehicle-linked pools versus non-vehicle pools.
   - Main use: Section 4, Figure 3 and Table 3.

2. **LP repositioning intensity in vehicle-linked pools**
   - Unit: pool-day or pool-hour.
   - Measures: mint count, burn count, gross liquidity moved, net liquidity moved,
     average time since last repositioning, and position range width.
   - Test: vehicle-linked pools should have more frequent and more precise
     repositioning if vehicle status is a liquidity-provision equilibrium.
   - Main use: Table 3.

3. **Scaling-chain or low-gas quasi experiment**
   - Unit: chain-pool-day, where the same pair exists on Ethereum, Arbitrum, and
     Polygon.
   - Treatment: lower gas cost on scaling solutions or major gas-fee declines.
   - Outcomes: repositioning intensity, liquidity concentration, vehicle-route
     advantage, slippage for fixed trade sizes.
   - Test: cheaper repositioning should strengthen executable vehicle liquidity,
     especially for small trades.
   - Main use: Section 7 architecture or Appendix, depending on strength.

4. **Trade-size heterogeneity**
   - Unit: source-destination pair by simulated notional.
   - Outcomes: direct-route cost, vehicle-route cost, route advantage.
   - Test: small trades may benefit more from concentrated liquidity, while large
     trades may still require deep Ethereum/WETH routes.
   - Main use: Table 6 or appendix.

### Klein, Kozhan, Viswanath-Natraj, and Wang - Informed Liquidity Provision on Decentralized Exchanges

Core idea: LP mints and burns near the current price can have permanent price
impact. LPs are not passive; some liquidity provision is informed and reflects
future returns, adverse-selection management, and wallet sophistication.

What Olga may ask:

- Are LPs in vehicle pools informed, or just mechanically following swaps?
- Does liquidity movement precede route-share changes?
- Does vehicle dominance follow LP positioning rather than only trader routing?
- Are sophisticated LPs disproportionately active in vehicle-linked pools?

Experiments to add:

5. **LP flow predicts vehicle share**
   - Unit: vehicle token by hour/day.
   - Key variables: net active liquidity added near the current price in pools
     linked to a candidate vehicle.
   - Outcome: future vehicle share or route betweenness.
   - Test: liquidity provision should lead route use if LPs make the vehicle.
   - Main use: Table 4.

6. **Mint/burn price impact in vehicle-linked pools**
   - Unit: liquidity event.
   - Event types: aggressive mints, aggressive burns, wide-range mints/burns.
   - Outcomes: future pool price returns, future route costs, future route share.
   - Test: near-price LP events in vehicle pools should have predictive content if
     vehicle liquidity is informed.
   - Main use: Table 4.

7. **Public arbitrage versus private LP information**
   - Unit: pool-hour.
   - Measure: CEX-DEX price deviation or cross-DEX arbitrage deviation.
   - Test: separate liquidity repositioning that follows public arbitrage signals
     from residual liquidity repositioning that predicts route quality.
   - Main use: Table 4 or appendix.

8. **LP sophistication and vehicle provision**
   - Unit: wallet-pool-day if wallet identities can be linked.
   - Measures: wallet size, frequency, priority/gas paid, range width, historical
     profitability if feasible.
   - Test: sophisticated LPs concentrate more in vehicle-linked pools and move
     before route-share changes.
   - Main use: appendix unless clean.

### Klein and Song - Commonality in intraday liquidity and multilateral trading facilities

Core idea: market structure that connects trading venues can increase
network-wide liquidity commonality, especially in down markets and among assets
more intensely traded on the new venue.

What Olga may ask:

- Does vehicle-currency liquidity move as a common factor across pools?
- Is commonality stronger for pools sharing the same vehicle token?
- Does commonality increase in stress states?
- Do architecture changes connect liquidity across pools/venues the way Chi-X did
  across equity markets?

Experiments to add:

9. **Vehicle liquidity-commonality beta**
   - Unit: pool-hour or pool-day.
   - Outcome: pool liquidity, spread, slippage, price impact, or active depth.
   - Regressor: aggregate liquidity of other pools sharing the same vehicle token.
   - Controls: token-pair fixed effects, day/hour fixed effects, volume, volatility.
   - Test: vehicle-linked pools should load more on a common liquidity factor.
   - Main use: Table 5.

10. **Stress-state liquidity commonality**
    - Interact vehicle liquidity beta with downside market states.
    - Test: commonality should rise in down markets if vehicle liquidity transmits
      shocks across the network.
    - Main use: Table 5 or appendix.

11. **Architecture and liquidity commonality**
    - Compare commonality before and after V3 launch, V4 launch, or cross-chain
      scaling adoption where applicable.
    - Test: architecture that connects or concentrates routing should change the
      common liquidity factor around vehicle-linked pools.
    - Main use: Section 7 or appendix.

## Priority Recommendation

For the current paper, the highest-value additions are:

1. Vehicle-pair liquidity concentration.
2. LP repositioning intensity and precision in vehicle-linked pools.
3. LP flow predicting future vehicle share.
4. Direct-versus-vehicle route advantage by trade size.

These four experiments directly connect Kathy's "liquidity provision in the
setting of vehicle currency" framing to Olga's publication record and make the
paper stronger before a coauthor conversation.

Keep the following as appendix/supplement candidates unless one becomes
surprisingly strong: cross-chain low-gas quasi experiments, wallet sophistication,
public-versus-private LP information, and the full liquidity-commonality battery.
One compact commonality table can sit in the paper appendix as a bridge to Klein
and Song, but it should not become a second paper inside the main text.

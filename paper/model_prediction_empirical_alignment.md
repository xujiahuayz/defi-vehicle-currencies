# Model Prediction and Empirical Alignment

This note checks whether the formal Mathematica predictions in
`paper/vehicle_currency_model.wl` line up with the current empirical results.
The Mathematica output is in `output/model/model_derivations.txt`.

## Summary

The model and empirics are aligned if the claims are written in their bounded
form. The model should not be used to claim full causal validation of every
mechanism. It supports a disciplined empirical spine:

1. vehicle routes are valuable through availability and thin-direct-market
   protection;
2. vehicle-linked liquidity predicts bridge-use persistence, without causal LP
   feedback identification;
3. risk shocks lower incumbent vehicle use on impact;
4. direct-route architecture reduces reliance on vehicle-only opportunities;
5. V4 flash accounting separates route intermediation from physical transfer.

## P1. Availability and Thin-Direct-Market Protection

Formal result:

- `VehicleUsefulCondition` requires the vehicle route to be available and one of
  three conditions to hold: direct route unavailable, direct route thin, or
  vehicle route cheaper in common support.
- `dBridgeShare_dAdvantage > 0` because the derivative is proportional to
  `lambda * Sech[...]^2 / 4`, and `lambda > 0`.

Empirical alignment:

- WETH has 9,584 no-direct/WETH-available rows.
- Thin-direct median advantages are large: 142.65, 190.21, and 349.28 bp for
  $1k, $10k, and $100k trade sizes.
- Common-support medians are heterogeneous and not universally positive.

Assessment: aligned. The correct claim is availability and thin-direct-market
protection, not universal WETH cost superiority.

## P2. Liquidity Concentration and Bridge-Use Persistence

Formal result:

- `dAdvantage_dLIK > 0` and `dAdvantage_dLKJ > 0`: more executable liquidity in
  the vehicle legs raises route advantage.
- `dBridgeShare_dLIK > 0` and `dBridgeShare_dLKJ > 0`: bridge share rises with
  route advantage.
- `dExpectedBridgeShareNext_dVehicleLiquidity = betaL >= 0`.
- `dExpectedBridgeShareNext_dCurrentBridgeShare = r >= 0`.

Empirical alignment:

- LP concentration predicts future BridgeShare: within-token beta 0.2817,
  `p<0.001`.
- BridgeShare is persistent.
- V3 LP repositioning does not provide a clean positive causal mechanism.

Assessment: aligned only as a reduced-form predictability/persistence result.
The formal model is consistent with the signs, but the empirical design does not
identify causal LP feedback.

## P3. Impact Stress Rotation

Formal result:

- `dAdvantage_dVehicleRisk = -1`.
- `dBridgeShare_dVehicleRisk < 0` because the derivative is
  `-lambda * Sech[...]^2 / 4`.

Empirical alignment:

- WETH downside stress reduces WETH-minus-stable BridgeShare on impact.
- Decomposed same-day result: WETH share falls 1.48 pp, stable share rises
  1.48 pp, and WETH-minus-stable falls 2.96 pp, `p=0.018`.
- Threshold and overlap robustness preserves sign and significance.
- Hourly, weekly, and longer windows attenuate.

Assessment: aligned. The model predicts an impact response; the data support the
same-day implementation, not persistent stress-regime rotation.

## P4a. Direct-Route Opportunity Expansion

Formal result:

- `dAdvantage_dDirectLiquidityMultiplier < 0`: increasing direct-route liquidity
  lowers the relative advantage of vehicle routing.
- `dBridgeShare_dDirectLiquidityMultiplier < 0` under the logit bridge-share
  mapping.

Empirical alignment:

- Around V3, no-direct/WETH-available cases fall by 25.81 pp, `p<0.001`.
- This outcome has no detectable pretrend, `p=0.922`.
- Other direct-route availability outcomes have positive pretrends, so broad V3
  launch causality is not supported.

Assessment: aligned in the narrow architecture sense. V3 should be written as
route-opportunity evidence, not broad causal launch evidence.

## P4b. V4 Flash Accounting and Settlement Virtualization

Formal result:

- `PhysicalVehicleMovement = (1 - n) * GrossVehicleExposure`.
- `CompressionRatio = n`.
- `dPhysicalMovement_dNetting < 0`.
- `dCompression_dNetting = 1`.

Empirical alignment:

- V4 intermediary-token transfer incidence is 81.4% versus 100% for matched V3.
- The transfer-incidence gap is strongest for small routes and remains visible
  in size-bin robustness.
- All 93 audited V4 no-transfer route units have populated receipts, endpoint
  token transfers, and zero intermediary-token transfers.

Assessment: aligned. V4 does not eliminate vehicle routing; it weakens the link
between route intermediation and physical intermediary-token movement.

## Bottom Line

The formal model and empirical results line up after the reframing. The paper
should present the model as generating bounded comparative statics, not as a
fully identified causal system.

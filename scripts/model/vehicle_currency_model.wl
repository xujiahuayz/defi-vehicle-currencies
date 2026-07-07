(* ::Package:: *)
(* Vehicle-currency route model for symbolic checks in Wolfram Mathematica. *)

ClearAll["Global`*"];

(* Assumptions used by FullSimplify. q is trade size, L* are executable
   liquidity terms, f* are fees, theta scales price impact, rho is vehicle
   risk/credibility cost, and lambda is route-choice sensitivity. *)
$Assumptions =
  q > 0 && theta > 0 && lambda > 0 &&
  LD > 0 && LIK > 0 && LKJ > 0 && Lv > 0 &&
  Lmin > 0 && Lthin > Lmin &&
  a > 0 && n >= 0 && n <= 1 &&
  betaL >= 0 && betaB >= 0 && r >= 0 && psi >= 0 &&
  r <= 1 && psi <= 1 && alphaK >= 0 && alphaL >= 0 &&
  phi > 0 && Dv > 0 && kappa0 >= 0 && kappa1 >= 0 && chi > 0 &&
  fD >= 0 && fIK >= 0 && fKJ >= 0 &&
  sD >= 0 && sK >= 0 && rhoK >= 0;

DirectCost[q_, LD_, fD_, sD_, theta_] :=
  fD + sD + theta*q/LD;

VehicleCost[q_, LIK_, LKJ_, fIK_, fKJ_, sK_, rhoK_, theta_] :=
  fIK + fKJ + sK + rhoK + theta*q*(1/LIK + 1/LKJ);

RouteAdvantage =
  FullSimplify[
    DirectCost[q, LD, fD, sD, theta] -
      VehicleCost[q, LIK, LKJ, fIK, fKJ, sK, rhoK, theta]
  ];

BridgeShare[delta_] := 1/(1 + Exp[-lambda*delta]);

BridgeShareLevel = BridgeShare[RouteAdvantage];

DirectAvailable = LD >= Lmin;
VehicleRouteAvailable = LIK >= Lmin && LKJ >= Lmin;
ThinDirectMarket = LD <= Lthin;
VehicleUsefulCondition =
  FullSimplify[
    VehicleRouteAvailable && (! DirectAvailable || ThinDirectMarket || RouteAdvantage > 0)
  ];

(* Proposition 1: the vehicle route is valuable as availability and thin-direct
   market protection. Cost advantage is heterogeneous and is only one component
   of the vehicle role. *)
Prop1AvailabilityProtection = <|
  "RouteAdvantage" -> RouteAdvantage,
  "DirectAvailableCondition" -> DirectAvailable,
  "VehicleRouteAvailableCondition" -> VehicleRouteAvailable,
  "ThinDirectMarketCondition" -> ThinDirectMarket,
  "VehicleUsefulCondition" -> VehicleUsefulCondition,
  "dBridgeShare_dAdvantage" ->
    FullSimplify[D[BridgeShare[delta], delta] /. delta -> RouteAdvantage]
|>;

(* Proposition 2: liquidity-route feedback. Vehicle-linked liquidity predicts
   future bridge use, and current bridge use predicts future vehicle-linked
   liquidity. This is the model object for a Matthew-effect interpretation; the
   empirical design still determines whether the paper can claim causality. *)
ExpectedBridgeShareNext = alphaK + betaL*Lv + r*BridgeShareLevel;
ExpectedVehicleLiquidityNext = alphaL + betaB*BridgeShareLevel + psi*Lv;

Prop2LiquidityRouteFeedback = <|
  "dAdvantage_dLIK" -> FullSimplify[D[RouteAdvantage, LIK]],
  "dAdvantage_dLKJ" -> FullSimplify[D[RouteAdvantage, LKJ]],
  "dBridgeShare_dLIK" -> FullSimplify[D[BridgeShareLevel, LIK]],
  "dBridgeShare_dLKJ" -> FullSimplify[D[BridgeShareLevel, LKJ]],
  "ExpectedBridgeShareNext" -> ExpectedBridgeShareNext,
  "ExpectedVehicleLiquidityNext" -> ExpectedVehicleLiquidityNext,
  "dExpectedBridgeShareNext_dVehicleLiquidity" ->
    FullSimplify[D[ExpectedBridgeShareNext, Lv]],
  "dExpectedBridgeShareNext_dCurrentBridgeShare" ->
    FullSimplify[D[alphaK + betaL*Lv + r*b, b]],
  "dExpectedVehicleLiquidityNext_dCurrentBridgeShare" ->
    FullSimplify[D[alphaL + betaB*b + psi*Lv, b]],
  "dExpectedVehicleLiquidityNext_dCurrentLiquidity" ->
    FullSimplify[D[ExpectedVehicleLiquidityNext, Lv]]
|>;

(* Proposition 3: stress or reserve-credibility shocks to the incumbent vehicle
   reduce vehicle use. rhoK can represent WETH own-risk under ETH stress or a
   reserve-credibility wedge for a stablecoin vehicle. *)
Prop3StressRotation = <|
  "dAdvantage_dVehicleRisk" -> FullSimplify[D[RouteAdvantage, rhoK]],
  "dBridgeShare_dVehicleRisk" -> FullSimplify[D[BridgeShareLevel, rhoK]]
|>;

(* Proposition 4a: concentrated liquidity in the direct pool makes direct routes
   more feasible. a scales direct executable liquidity after an architecture
   change, such as concentrated liquidity adoption. *)
DirectCostV3 = DirectCost[q, a*LD, fD, sD, theta];
RouteAdvantageV3 =
  FullSimplify[
    DirectCostV3 -
      VehicleCost[q, LIK, LKJ, fIK, fKJ, sK, rhoK, theta]
  ];

Prop4aConcentratedLiquidity = <|
  "RouteAdvantageWithDirectLiquidityMultiplier" -> RouteAdvantageV3,
  "dAdvantage_dDirectLiquidityMultiplier" ->
    FullSimplify[D[RouteAdvantageV3, a]],
  "dBridgeShare_dDirectLiquidityMultiplier" ->
    FullSimplify[D[BridgeShare[RouteAdvantageV3], a]]
|>;

(* Proposition 4b: settlement netting changes LP supply incentives. Netting
   lowers the operational inventory cost of serving vehicle-routed flow, raising
   optimal vehicle-linked LP supply when kappa1 > 0. *)
GrossVehicleExposure = q*(1/LIK + 1/LKJ);
PhysicalVehicleMovement = (1 - n)*GrossVehicleExposure;
CompressionRatio = FullSimplify[1 - PhysicalVehicleMovement/GrossVehicleExposure];
OperationalCostPerLiquidity = kappa0 + kappa1*(1 - n);
LPPayoff = phi*Dv*Lv - OperationalCostPerLiquidity*Lv - chi*Lv^2/2;
OptimalVehicleLiquidity =
  FullSimplify[Lv /. First[Solve[D[LPPayoff, Lv] == 0, Lv]]];

Prop4bSettlementNettingLiquidity = <|
  "GrossVehicleExposure" -> GrossVehicleExposure,
  "PhysicalVehicleMovement" -> PhysicalVehicleMovement,
  "CompressionRatio" -> CompressionRatio,
  "LPPayoff" -> LPPayoff,
  "OptimalVehicleLiquidity" -> OptimalVehicleLiquidity,
  "dPhysicalMovement_dNetting" ->
    FullSimplify[D[PhysicalVehicleMovement, n]],
  "dCompression_dNetting" ->
    FullSimplify[D[CompressionRatio, n]],
  "dOptimalVehicleLiquidity_dNetting" ->
    FullSimplify[D[OptimalVehicleLiquidity, n]],
  "dOptimalVehicleLiquidity_dRoutedDemand" ->
    FullSimplify[D[OptimalVehicleLiquidity, Dv]]
|>;

AllPropositions = <|
  "P1AvailabilityProtection" -> Prop1AvailabilityProtection,
  "P2LiquidityRouteFeedback" -> Prop2LiquidityRouteFeedback,
  "P3StressRotation" -> Prop3StressRotation,
  "P4aConcentratedLiquidity" -> Prop4aConcentratedLiquidity,
  "P4bSettlementNettingLiquidity" -> Prop4bSettlementNettingLiquidity
|>;

AllPropositions

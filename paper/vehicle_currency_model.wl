(* ::Package:: *)
(* Vehicle-currency route model for symbolic checks in Wolfram Mathematica. *)

ClearAll["Global`*"];

(* Assumptions used by FullSimplify. q is trade size, L* are executable
   liquidity terms, f* are fees, theta scales price impact, rho is vehicle
   risk/credibility cost, and lambda is route-choice sensitivity. *)
$Assumptions =
  q > 0 && theta > 0 && lambda > 0 &&
  LD > 0 && LIK > 0 && LKJ > 0 && Lv > 0 &&
  a > 0 && n >= 0 && n <= 1 &&
  phi >= 0 && Lbar > 0 &&
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

(* Proposition 1: vehicle use rises when the vehicle route becomes cheaper
   relative to the direct route. *)
Prop1VehicleUse = <|
  "RouteAdvantage" -> RouteAdvantage,
  "VehicleChosenCondition" -> FullSimplify[RouteAdvantage > 0],
  "dBridgeShare_dAdvantage" ->
    FullSimplify[D[BridgeShare[delta], delta] /. delta -> RouteAdvantage]
|>;

(* Proposition 2: vehicle-linked liquidity raises bridge share and creates a
   persistence channel when LP liquidity responds to expected route flow. *)
LpLawOfMotion = Lbar + phi*BridgeShareLevel;

Prop2LiquidityFeedback = <|
  "dAdvantage_dLIK" -> FullSimplify[D[RouteAdvantage, LIK]],
  "dAdvantage_dLKJ" -> FullSimplify[D[RouteAdvantage, LKJ]],
  "dBridgeShare_dLIK" -> FullSimplify[D[BridgeShareLevel, LIK]],
  "dBridgeShare_dLKJ" -> FullSimplify[D[BridgeShareLevel, LKJ]],
  "NextLiquidity" -> LpLawOfMotion,
  "dNextLiquidity_dCurrentBridgeShare" ->
    FullSimplify[D[Lbar + phi*b, b]]
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

(* Proposition 4b: V4 flash accounting separates route intermediation from
   physical transfer. Gross vehicle exposure can remain positive while physical
   movement falls with netting intensity n. *)
GrossVehicleExposure = q*(1/LIK + 1/LKJ);
PhysicalVehicleMovement = (1 - n)*GrossVehicleExposure;
CompressionRatio = FullSimplify[1 - PhysicalVehicleMovement/GrossVehicleExposure];

Prop4bFlashAccounting = <|
  "GrossVehicleExposure" -> GrossVehicleExposure,
  "PhysicalVehicleMovement" -> PhysicalVehicleMovement,
  "CompressionRatio" -> CompressionRatio,
  "dPhysicalMovement_dNetting" ->
    FullSimplify[D[PhysicalVehicleMovement, n]],
  "dCompression_dNetting" ->
    FullSimplify[D[CompressionRatio, n]]
|>;

AllPropositions = <|
  "P1VehicleUse" -> Prop1VehicleUse,
  "P2LiquidityFeedback" -> Prop2LiquidityFeedback,
  "P3StressRotation" -> Prop3StressRotation,
  "P4aConcentratedLiquidity" -> Prop4aConcentratedLiquidity,
  "P4bFlashAccounting" -> Prop4bFlashAccounting
|>;

AllPropositions

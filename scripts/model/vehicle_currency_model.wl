(* ::Package:: *)
(* Vehicle-currency route model for symbolic checks in Wolfram Mathematica. *)

ClearAll["Global`*"];

(* Assumptions used by FullSimplify. q is dollar trade size, C* are deposited
   dollar-capital terms, D* are executable-dollar-depth terms, eta* map capital
   into depth under an exact protocol state, Cv is aggregate vehicle-linked
   capital, f* are ad-valorem fees, theta scales price impact, rho is a
   vehicle risk/credibility cost, and lambda is route-choice sensitivity. *)
$Assumptions =
  q > 0 && theta > 0 && lambda > 0 &&
  CDD > 0 && CIK > 0 && CKJ > 0 && Cv > 0 &&
  etaD > 0 && etaIK > 0 && etaKJ > 0 &&
  DD > 0 && DIK > 0 && DKJ > 0 &&
  Dmin > 0 && Dthin > Dmin &&
  a > 0 && n >= 0 && n <= 1 &&
  betaC >= 0 && betaB >= 0 && r >= 0 && psi >= 0 &&
  r <= 1 && psi <= 1 && alphaK >= 0 && alphaC >= 0 &&
  phi > 0 && Qv > 0 && kappa0 >= 0 && kappa1 >= 0 && chi > 0 &&
  fD >= 0 && fIK >= 0 && fKJ >= 0 &&
  sD >= 0 && sK >= 0 && rhoK >= 0;

(* eta is invariant- and state-specific capital efficiency. It represents
   range placement, weights, amplification, rate providers, hooks and other
   protocol state needed to turn deposited capital into executable depth. The
   empirical registry, not this reduced-form model, supplies the exact map. *)
ProtocolDepth[capital_, stateEfficiency_] := stateEfficiency*capital;

DDFromCapital = ProtocolDepth[CDD, etaD];
DIKFromCapital = ProtocolDepth[CIK, etaIK];
DKJFromCapital = ProtocolDepth[CKJ, etaKJ];

DirectCost[q_, DD_, fD_, sD_, theta_] :=
  fD + sD + theta*q/DD;

VehicleCost[q_, DIK_, DKJ_, fIK_, fKJ_, sK_, rhoK_, theta_] :=
  fIK + fKJ + sK + rhoK + theta*q*(1/DIK + 1/DKJ);

RouteAdvantage =
  FullSimplify[
    DirectCost[q, DD, fD, sD, theta] -
      VehicleCost[q, DIK, DKJ, fIK, fKJ, sK, rhoK, theta]
  ];

BridgeShare[delta_] := 1/(1 + Exp[-lambda*delta]);

BridgeShareLevel = BridgeShare[RouteAdvantage];

RouteAdvantageFromCapital =
  FullSimplify[
    DirectCost[q, DDFromCapital, fD, sD, theta] -
      VehicleCost[
        q, DIKFromCapital, DKJFromCapital,
        fIK, fKJ, sK, rhoK, theta
      ]
  ];

BridgeShareFromCapital = BridgeShare[RouteAdvantageFromCapital];

DirectAvailable = DD >= Dmin;
VehicleRouteAvailable = DIK >= Dmin && DKJ >= Dmin;
ThinDirectMarket = DD <= Dthin;
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

(* Proposition 2: capital-route feedback. Vehicle-linked deposited capital
   predicts future bridge use, and current bridge use predicts future capital.
   Executable depth affects route cost separately above. The empirical design
   still determines whether the paper can claim causality. *)
ExpectedBridgeShareNext = alphaK + betaC*Cv + r*BridgeShareLevel;
ExpectedVehicleCapitalNext = alphaC + betaB*BridgeShareLevel + psi*Cv;

Prop2CapitalRouteFeedback = <|
  "DepthMapping" -> <|
    "Direct" -> DDFromCapital,
    "FirstVehicleLeg" -> DIKFromCapital,
    "SecondVehicleLeg" -> DKJFromCapital
  |>,
  "RouteAdvantageFromCapital" -> RouteAdvantageFromCapital,
  "dBridgeShare_dFirstLegCapital" ->
    FullSimplify[D[BridgeShareFromCapital, CIK]],
  "dBridgeShare_dSecondLegCapital" ->
    FullSimplify[D[BridgeShareFromCapital, CKJ]],
  "dBridgeShare_dFirstLegCapitalEfficiency" ->
    FullSimplify[D[BridgeShareFromCapital, etaIK]],
  "dBridgeShare_dSecondLegCapitalEfficiency" ->
    FullSimplify[D[BridgeShareFromCapital, etaKJ]],
  "dAdvantage_dDIK" -> FullSimplify[D[RouteAdvantage, DIK]],
  "dAdvantage_dDKJ" -> FullSimplify[D[RouteAdvantage, DKJ]],
  "dBridgeShare_dDIK" -> FullSimplify[D[BridgeShareLevel, DIK]],
  "dBridgeShare_dDKJ" -> FullSimplify[D[BridgeShareLevel, DKJ]],
  "ExpectedBridgeShareNext" -> ExpectedBridgeShareNext,
  "ExpectedVehicleCapitalNext" -> ExpectedVehicleCapitalNext,
  "dExpectedBridgeShareNext_dVehicleCapital" ->
    FullSimplify[D[ExpectedBridgeShareNext, Cv]],
  "dExpectedBridgeShareNext_dCurrentBridgeShare" ->
    FullSimplify[D[alphaK + betaC*Cv + r*b, b]],
  "dExpectedVehicleCapitalNext_dCurrentBridgeShare" ->
    FullSimplify[D[alphaC + betaB*b + psi*Cv, b]],
  "dExpectedVehicleCapitalNext_dCurrentCapital" ->
    FullSimplify[D[ExpectedVehicleCapitalNext, Cv]]
|>;

(* Proposition 3: stress or reserve-credibility shocks to the incumbent vehicle
   reduce vehicle use. rhoK can represent WETH own-risk under ETH stress or a
   reserve-credibility wedge for a stablecoin vehicle. *)
Prop3StressRotation = <|
  "dAdvantage_dVehicleRisk" -> FullSimplify[D[RouteAdvantage, rhoK]],
  "dBridgeShare_dVehicleRisk" -> FullSimplify[D[BridgeShareLevel, rhoK]]
|>;

(* Proposition 4a: an architecture change can raise direct-route capital
   efficiency at fixed deposited capital. a scales etaD, not capital itself. *)
DirectCostV3 =
  DirectCost[q, ProtocolDepth[CDD, a*etaD], fD, sD, theta];
RouteAdvantageV3 =
  FullSimplify[
    DirectCostV3 -
      VehicleCost[q, DIK, DKJ, fIK, fKJ, sK, rhoK, theta]
  ];

Prop4aConcentratedLiquidity = <|
  "RouteAdvantageWithDirectCapitalEfficiencyMultiplier" -> RouteAdvantageV3,
  "dAdvantage_dDirectCapitalEfficiencyMultiplier" ->
    FullSimplify[D[RouteAdvantageV3, a]],
  "dBridgeShare_dDirectCapitalEfficiencyMultiplier" ->
    FullSimplify[D[BridgeShare[RouteAdvantageV3], a]]
|>;

(* Proposition 4b: settlement netting changes LP capital incentives. q is gross
   vehicle settlement value; unlike the prior dimensional error, physical flow
   is not inverse depth. Netting lowers the operational cost of supporting routed
   demand and raises optimal vehicle-linked deposited capital when kappa1 > 0. *)
GrossVehicleSettlement = q;
PhysicalVehicleSettlement = (1 - n)*GrossVehicleSettlement;
CompressionRatio = FullSimplify[1 - PhysicalVehicleSettlement/GrossVehicleSettlement];
OperationalCostPerCapital = kappa0 + kappa1*(1 - n);
LPPayoff = phi*Qv*Cv - OperationalCostPerCapital*Cv - chi*Cv^2/2;
OptimalVehicleCapital =
  FullSimplify[Cv /. First[Solve[D[LPPayoff, Cv] == 0, Cv]]];

Prop4bSettlementNettingCapital = <|
  "GrossVehicleSettlement" -> GrossVehicleSettlement,
  "PhysicalVehicleSettlement" -> PhysicalVehicleSettlement,
  "CompressionRatio" -> CompressionRatio,
  "LPPayoff" -> LPPayoff,
  "OptimalVehicleCapital" -> OptimalVehicleCapital,
  "dPhysicalSettlement_dNetting" ->
    FullSimplify[D[PhysicalVehicleSettlement, n]],
  "dCompression_dNetting" ->
    FullSimplify[D[CompressionRatio, n]],
  "dOptimalVehicleCapital_dNetting" ->
    FullSimplify[D[OptimalVehicleCapital, n]],
  "dOptimalVehicleCapital_dRoutedDemand" ->
    FullSimplify[D[OptimalVehicleCapital, Qv]]
|>;

AllPropositions = <|
  "P1AvailabilityProtection" -> Prop1AvailabilityProtection,
  "P2CapitalRouteFeedback" -> Prop2CapitalRouteFeedback,
  "P3StressRotation" -> Prop3StressRotation,
  "P4aConcentratedLiquidity" -> Prop4aConcentratedLiquidity,
  "P4bSettlementNettingCapital" -> Prop4bSettlementNettingCapital
|>;

AllPropositions

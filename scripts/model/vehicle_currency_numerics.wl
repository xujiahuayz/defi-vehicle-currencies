(* Numerical illustrations for vehicle_currency_model.wl.
   Run from the repo root after Mathematica/Wolfram is activated:
   wolframscript -file scripts/model/vehicle_currency_numerics.wl
*)

Get[FileNameJoin[{Directory[], "scripts", "model", "vehicle_currency_model.wl"}]];

outputDir = FileNameJoin[{Directory[], "output", "model"}];
If[! DirectoryQ[outputDir], CreateDirectory[outputDir, CreateIntermediateDirectories -> True]];

params = {
  q -> 1, theta -> 0.08, lambda -> 4,
  DD -> 1.4, fD -> 0.003, fIK -> 0.003, fKJ -> 0.003,
  sD -> 0.0005, sK -> 0.0005
};

tightRange[expr_, var_Symbol, lo_, hi_] := Module[{vals, ymin, ymax, pad},
  vals = Table[N[expr /. var -> z], {z, lo, hi, (hi - lo)/200}];
  ymin = Min[vals];
  ymax = Max[vals];
  pad = Max[0.01*(ymax - ymin), 0.002];
  {Max[0, ymin - pad], Min[1, ymax + pad]}
];

depthPlot = Plot[
  Evaluate[BridgeShareLevel /. params /. {rhoK -> 0.01, DIK -> x, DKJ -> x}],
  {x, 0.25, 5},
  Frame -> True,
  FrameLabel -> {"Vehicle-route executable depth", "Bridge share"},
  PlotRange -> tightRange[BridgeShareLevel /. params /. {rhoK -> 0.01, DIK -> x, DKJ -> x}, x, 0.25, 5],
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

riskPlot = Plot[
  Evaluate[BridgeShareLevel /. params /. {DIK -> 1, DKJ -> 1, rhoK -> r}],
  {r, 0, 0.12},
  Frame -> True,
  FrameLabel -> {"Vehicle risk / credibility cost", "Bridge share"},
  PlotRange -> tightRange[BridgeShareLevel /. params /. {DIK -> 1, DKJ -> 1, rhoK -> r}, r, 0, 0.12],
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

architecturePlot = Plot[
  Evaluate[BridgeShare[RouteAdvantageV3] /. params /. {DIK -> 1, DKJ -> 1, rhoK -> 0.01, a -> x}],
  {x, 0.5, 5},
  Frame -> True,
  FrameLabel -> {"Direct-route capital-efficiency multiplier", "Bridge share"},
  PlotRange -> tightRange[BridgeShare[RouteAdvantageV3] /. params /. {DIK -> 1, DKJ -> 1, rhoK -> 0.01, a -> x}, x, 0.5, 5],
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

nettingPlot = Plot[
  Evaluate[{CompressionRatio, PhysicalVehicleSettlement/GrossVehicleSettlement} /. params /. n -> x],
  {x, 0, 1},
  Frame -> True,
  FrameLabel -> {"Netting intensity", "Share"},
  PlotLegends -> {"Compression ratio", "Physical settlement / gross settlement"},
  PlotRange -> {0, 1},
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

feedbackPath = NestList[
  {
    Min[1, 0.04 + 0.22*#[[2]] + 0.70*#[[1]]],
    Min[1, 0.02 + 0.18*#[[1]] + 0.62*#[[2]]]
  } &,
  {0.35, 0.15},
  24
];

feedbackPlot = ListLinePlot[
  {feedbackPath[[All, 2]], feedbackPath[[All, 1]]},
  Frame -> True,
  FrameLabel -> {"Period", "State"},
  PlotLegends -> {"Bridge share", "Vehicle-linked deposited capital"},
  PlotRange -> {0, 1},
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

lpCapitalPlot = Plot[
  Evaluate[OptimalVehicleCapital /. {phi -> 0.08, Qv -> 1, kappa0 -> 0.02, kappa1 -> 0.035, chi -> 0.09}],
  {n, 0, 1},
  Frame -> True,
  FrameLabel -> {"Settlement netting intensity", "Optimal vehicle-linked deposited capital"},
  PlotRange -> All,
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

Export[FileNameJoin[{outputDir, "model_bridge_share_depth.png"}], depthPlot];
Export[FileNameJoin[{outputDir, "model_bridge_share_risk.png"}], riskPlot];
Export[FileNameJoin[{outputDir, "model_bridge_share_direct_depth.png"}], architecturePlot];
Export[FileNameJoin[{outputDir, "model_v4_netting_compression.png"}], nettingPlot];
Export[FileNameJoin[{outputDir, "model_capital_route_feedback.png"}], feedbackPlot];
Export[FileNameJoin[{outputDir, "model_netting_lp_capital.png"}], lpCapitalPlot];
Export[FileNameJoin[{outputDir, "model_derivations.txt"}], ToString[AllPropositions, InputForm], "Text"];

Grid[{
  {"dBridgeShare/dVehicleRouteDepth", FullSimplify[D[BridgeShareLevel, DIK]]},
  {"dBridgeShare/dVehicleRisk", FullSimplify[D[BridgeShareLevel, rhoK]]},
  {"dBridgeShare/dDirectCapitalEfficiencyMultiplier", FullSimplify[D[BridgeShare[RouteAdvantageV3], a]]},
  {"dCompression/dNetting", FullSimplify[D[CompressionRatio, n]]},
  {"dExpectedVehicleCapitalNext/dCurrentBridgeShare", FullSimplify[D[alphaC + betaB*b + psi*Cv, b]]},
  {"dOptimalVehicleCapital/dNetting", FullSimplify[D[OptimalVehicleCapital, n]]}
}]

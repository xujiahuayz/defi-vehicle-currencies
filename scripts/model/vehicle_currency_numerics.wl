(* Numerical illustrations for vehicle_currency_model.wl.
   Run from the repo root after Mathematica/Wolfram is activated:
   wolframscript -file scripts/model/vehicle_currency_numerics.wl
*)

Get[FileNameJoin[{Directory[], "scripts", "model", "vehicle_currency_model.wl"}]];

outputDir = FileNameJoin[{Directory[], "output", "model"}];
If[! DirectoryQ[outputDir], CreateDirectory[outputDir, CreateIntermediateDirectories -> True]];

params = {
  q -> 1, theta -> 0.08, lambda -> 4,
  LD -> 1.4, fD -> 0.003, fIK -> 0.003, fKJ -> 0.003,
  sD -> 0.0005, sK -> 0.0005
};

tightRange[expr_, var_Symbol, lo_, hi_] := Module[{vals, ymin, ymax, pad},
  vals = Table[N[expr /. var -> z], {z, lo, hi, (hi - lo)/200}];
  ymin = Min[vals];
  ymax = Max[vals];
  pad = Max[0.01*(ymax - ymin), 0.002];
  {Max[0, ymin - pad], Min[1, ymax + pad]}
];

liquidityPlot = Plot[
  Evaluate[BridgeShareLevel /. params /. {rhoK -> 0.01, LIK -> x, LKJ -> x}],
  {x, 0.25, 5},
  Frame -> True,
  FrameLabel -> {"Vehicle-linked executable liquidity", "Bridge share"},
  PlotRange -> tightRange[BridgeShareLevel /. params /. {rhoK -> 0.01, LIK -> x, LKJ -> x}, x, 0.25, 5],
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

riskPlot = Plot[
  Evaluate[BridgeShareLevel /. params /. {LIK -> 1, LKJ -> 1, rhoK -> r}],
  {r, 0, 0.12},
  Frame -> True,
  FrameLabel -> {"Vehicle risk / credibility cost", "Bridge share"},
  PlotRange -> tightRange[BridgeShareLevel /. params /. {LIK -> 1, LKJ -> 1, rhoK -> r}, r, 0, 0.12],
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

architecturePlot = Plot[
  Evaluate[BridgeShare[RouteAdvantageV3] /. params /. {LIK -> 1, LKJ -> 1, rhoK -> 0.01, a -> x}],
  {x, 0.5, 5},
  Frame -> True,
  FrameLabel -> {"Direct-route liquidity multiplier", "Bridge share"},
  PlotRange -> tightRange[BridgeShare[RouteAdvantageV3] /. params /. {LIK -> 1, LKJ -> 1, rhoK -> 0.01, a -> x}, x, 0.5, 5],
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

nettingPlot = Plot[
  Evaluate[{CompressionRatio, PhysicalVehicleMovement/GrossVehicleExposure} /. params /. n -> x],
  {x, 0, 1},
  Frame -> True,
  FrameLabel -> {"Netting intensity", "Share"},
  PlotLegends -> {"Compression ratio", "Physical movement / gross exposure"},
  PlotRange -> {0, 1},
  PlotTheme -> "Scientific",
  ImageSize -> 700
];

Export[FileNameJoin[{outputDir, "model_bridge_share_liquidity.png"}], liquidityPlot];
Export[FileNameJoin[{outputDir, "model_bridge_share_risk.png"}], riskPlot];
Export[FileNameJoin[{outputDir, "model_bridge_share_direct_liquidity.png"}], architecturePlot];
Export[FileNameJoin[{outputDir, "model_v4_netting_compression.png"}], nettingPlot];
Export[FileNameJoin[{outputDir, "model_derivations.txt"}], ToString[AllPropositions, InputForm], "Text"];

Grid[{
  {"dBridgeShare/dVehicleLiquidity", FullSimplify[D[BridgeShareLevel, LIK]]},
  {"dBridgeShare/dVehicleRisk", FullSimplify[D[BridgeShareLevel, rhoK]]},
  {"dBridgeShare/dDirectLiquidityMultiplier", FullSimplify[D[BridgeShare[RouteAdvantageV3], a]]},
  {"dCompression/dNetting", FullSimplify[D[CompressionRatio, n]]}
}]

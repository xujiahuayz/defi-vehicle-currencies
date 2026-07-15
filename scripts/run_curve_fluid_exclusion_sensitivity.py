#!/usr/bin/env python3
"""Bridge-use sensitivity to excluding Curve and Fluid.

Curve and Fluid are material but not exact-quoteable from the current raw state.
This script asks the narrower empirical question that matters before writing:
if the paper scopes route-cost counterfactuals to quoteable venues, do the
realized vehicle-use facts collapse when Curve and Fluid legs are excluded?
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _pct, _write_table  # noqa: E402

VEHICLES = ("WETH", "USDC", "USDT", "DAI", "WBTC")
EXCLUDED = {"curve", "fluid"}


def _load_empirical():
    path = SCRIPTS / "run_empirical_proposition_tests.py"
    spec = importlib.util.spec_from_file_location("dvc_empirical_curve_fluid", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bridge_for_legs(legs: pd.DataFrame, empirical) -> dict[str, float]:
    routes = empirical._routes(legs[legs["route_class"].isin(empirical.CLEAN_ROUTE_CLASSES)])
    indirect = [r for r in routes if r["inter"]]
    denom = sum(float(r["vol"]) for r in indirect)
    pairs = {(r["src"], r["tgt"]) for r in indirect}
    out: dict[str, float] = {}
    for token in VEHICLES:
        vol = 0.0
        covered_pairs: set[tuple[str, str]] = set()
        for r in indirect:
            if token in r["inter"]:
                vol += float(r["vol"])
                covered_pairs.add((r["src"], r["tgt"]))
        out[f"{token}_BridgeShare"] = vol / denom if denom > 0 else 0.0
        out[f"{token}_PairCoverage"] = len(covered_pairs) / len(pairs) if pairs else 0.0
    out["indirect_volume_usd"] = denom
    out["indirect_pair_count"] = len(pairs)
    return out


def run(year: int = 2026) -> pd.DataFrame:
    empirical = _load_empirical()
    files = sorted((DATA / "unified").glob(f"{year}[0-9][0-9][0-9][0-9].parquet"))
    rows = []
    for i, path in enumerate(files, 1):
        date = f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:]}"
        legs = pd.read_parquet(
            path,
            columns=[
                "tx_hash",
                "component_id",
                "source",
                "route_class",
                "token_in_sym",
                "token_out_sym",
                "amount_usd",
                "tin_role",
                "tout_role",
            ],
        )
        all_result = _bridge_for_legs(legs, empirical)
        kept_result = _bridge_for_legs(legs[~legs["source"].isin(EXCLUDED)], empirical)
        for sample, res in [("all venues", all_result), ("exclude Curve+Fluid", kept_result)]:
            row = {"date": date, "sample": sample}
            row.update(res)
            rows.append(row)
        if i % 50 == 0 or i == len(files):
            print(f"Curve/Fluid exclusion sensitivity [{i}/{len(files)}] {date}", flush=True)
    panel = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(DATA / "empirical" / f"curve_fluid_exclusion_sensitivity_{year}.parquet", index=False)

    out_rows = []
    for token in VEHICLES:
        for metric in ["BridgeShare", "PairCoverage"]:
            col = f"{token}_{metric}"
            wide = panel.pivot(index="date", columns="sample", values=col).dropna()
            if wide.empty:
                continue
            diff = wide["exclude Curve+Fluid"] - wide["all venues"]
            out_rows.append(
                {
                    "Token": token,
                    "Metric": metric,
                    "All venues (%)": _pct(wide["all venues"].mean()),
                    "Exclude Curve+Fluid (%)": _pct(wide["exclude Curve+Fluid"].mean()),
                    "Difference (pp)": _num(100 * diff.mean(), 2),
                }
            )
    summary = pd.DataFrame(out_rows)
    summary.to_pickle(EMP / f"curve_fluid_exclusion_sensitivity_{year}.pkl")
    _write_table(
        summary,
        "table_r30_curve_fluid_exclusion_sensitivity",
        f"Vehicle-use sensitivity to excluding Curve and Fluid, {year}.",
        "tab:curve-fluid-exclusion-sensitivity",
        note=(
            "The table rebuilds realized BridgeShare and PairCoverage after dropping Curve "
            "and Fluid legs from the unified route table. This is not an executable-depth "
            "quote; it checks whether realized vehicle-use facts are driven mechanically by "
            "the non-quoteable venues."
        ),
    )
    return summary


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Re-estimate the headline dominance specification in R's fixest and compare.

pyfixest is a port of fixest's alternating-projections algorithm, and porting is
exactly where a subtle disagreement hides. This session also surfaced several bugs in
my own code that each produced a plausible number rather than an error, so the
headline specification is re-estimated in the reference implementation and the two are
compared to a stated tolerance. fixest output is additionally what an empirical
finance referee recognises.

R is a VERIFIER, never part of the pipeline. This script exports a transient sample
under data/interim/, invokes Rscript, parses the estimate back, compares, and deletes
the transient. Nothing in output/ depends on R being installed.

Writes  output/exhibits/dominance_crosscheck.jsonl
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

TRANSIENT = ROOT / "data" / "interim" / "hdfe_crosscheck_sample.tsv"
RSCRIPT = ROOT / "scripts" / "verify" / "crosscheck_dominance_fixest.R"
OUT = ROOT / "output" / "exhibits" / "dominance_crosscheck.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", type=int, default=12,
                    help="control-window width in HOURS")
    ap.add_argument("--min-notional", type=float, default=100.0)
    ap.add_argument("--tol", type=float, default=1e-4,
                    help="absolute tolerance on the coefficient; the two engines "
                         "should agree far inside this")
    args = ap.parse_args()

    from scripts import run_vehicle_dominance_hdfe as hdfe

    df = hdfe.load(args.window, args.min_notional)
    df["mid_type"] = df.vehicle.map({v: classify(v)[1] for v in df.vehicle.unique()})
    df["native"] = (df.mid_type == "native").astype(int)
    py = hdfe.summarise(df.assign(native=df.native.astype(float)), args.window)
    if py is None:
        print("no identifying fixed effects")
        return 1

    mix = df.groupby("fe_id").native.agg(["mean", "size"])
    ident = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
    sub = df[df.fe_id.isin(ident)][["dominated", "native", "fe_id", "pair_id"]]
    TRANSIENT.parent.mkdir(parents=True, exist_ok=True)
    # Written by DuckDB rather than pandas: the repository forbids emitting delimited
    # text from source, DuckDB's COPY is far faster on 11 million rows, and this keeps
    # the export in the same engine that produced the sample.
    import duckdb

    con = duckdb.connect()
    con.register("sub", sub)
    con.execute(
        f"COPY (SELECT * FROM sub) TO '{TRANSIENT.as_posix()}' "
        "(FORMAT CSV, DELIMITER '\t', HEADER)")
    con.close()
    try:
        r = subprocess.run(["/usr/local/bin/Rscript", str(RSCRIPT), str(TRANSIENT)],
                           capture_output=True, text=True, timeout=3600, cwd=ROOT)
        text = r.stdout
    finally:
        TRANSIENT.unlink(missing_ok=True)

    m = re.search(r"coef\s+(-?[\d.]+)\s+se\s+([\d.]+)\s+t\s+(-?[\d.]+)\s+p\s+([\d.eE+-]+)", text)
    if not m:
        print("could not parse fixest output:\n", text[-800:])
        return 1
    r_coef, r_se = float(m.group(1)), float(m.group(2))
    delta = abs(r_coef - py["coef"])
    agree = delta < args.tol

    print(f"window {args.window}h, {py['n']:,} rows, {py['identifying_groups']:,} identifying fixed effects")
    print(f"  pyfixest  coef {py['coef']:+.6f}  se {py['se']:.6f}")
    print(f"  R fixest  coef {r_coef:+.6f}  se {r_se:.6f}")
    print(f"  |difference| {delta:.2e}  ->  {'AGREE' if agree else 'DISAGREE, do not use either until resolved'}")

    write_exhibit(pd.DataFrame([{
        "window_hours": args.window, "n": py["n"],
        "identifying_groups": py["identifying_groups"], "clusters": py["clusters"],
        "pyfixest_coef": py["coef"], "pyfixest_se": py["se"],
        "r_fixest_coef": r_coef, "r_fixest_se": r_se,
        "abs_difference": delta, "tolerance": args.tol, "agree": agree,
    }]), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0 if agree else 1


if __name__ == "__main__":
    sys.exit(main())

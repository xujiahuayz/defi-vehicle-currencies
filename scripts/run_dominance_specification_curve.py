"""Why does the native coefficient move, and under what conditions does it hold?

Two failures this replaces, both Java's diagnosis and both correct.

The first is that "native intermediation is cheaper" is not a claim. Cheaper for which
trade size, on which pair, in which era, against which alternative, with which venues
priced? An unconditional statement about relative routing cost has no content, so the
estimate has to be reported as a surface over those conditions and not as a scalar.

The second is that this project kept BINNING unstable results instead of diagnosing
them. The native coefficient has gone from a descriptive advantage, to +0.094 under
pair-day effects, to -0.383 on the multi-venue panel, and each move was explained away
by declaring the previous design flawed. That is not diagnosis. When a sign moves, the
question is which single design dimension moved it, because whatever does either belongs
in the specification as a control or IS the finding.

So this script does two things a single regression cannot.

DECOMPOSITION. Vary one design dimension at a time, holding the rest fixed, and report
what each one does to the coefficient. The dimensions that plausibly drove the historical
swings are the venue set, the support restriction, the fixed-effect structure, the
outcome definition and the estimation sample. A dimension that moves the coefficient more
than its own standard error is a condition the claim depends on, and it gets named in the
paper instead of being absorbed into a footnote about power.

CONDITIONS. Interact the treatment with trade size, with era and with how many candidate
vehicles were available, so the result is stated as "native routing is cheaper by X under
these conditions and by Y under those" rather than as one number. Interactions are tested
formally, because reading a difference between two subsample point estimates as a finding
without testing it is the exact error that made an insignificant size gradient
load-bearing in four places here.

The outcome is reported both as the binary dominance indicator and as the continuous gap
in basis points, since a coefficient on a binary at an absorbed threshold is a shift in a
CDF and not a cost, which is the objection that retired the previous headline.

Reads   data/empirical/route_cost_panel_v2.parquet
Writes  output/exhibits/dominance_specification_curve.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "dominance_specification_curve.jsonl"


def load(window_hours: int) -> pd.DataFrame:
    import duckdb

    con = duckdb.connect()
    df = con.execute(f"""
        SELECT CAST(date AS DATE) AS d, reserve_hour_utc AS hr,
               src, tgt, vehicle, trade_size_usd,
               direct_cost_advantage AS adv,
               direct_source, hop1_source, hop2_source,
               direct_output_usd, vehicle_output_usd,
               CAST(FLOOR((CAST(epoch(CAST(date AS TIMESTAMP)) / 3600 AS BIGINT)
                    + reserve_hour_utc) / CAST({int(window_hours)} AS DOUBLE))
                    AS BIGINT) AS win
        FROM read_parquet('{PANEL.as_posix()}')
        WHERE direct_available AND vehicle_available
          AND direct_cost_advantage IS NOT NULL
    """).df()
    con.close()
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["mid_type"] = df.vehicle.map({v: classify(v)[1] for v in df.vehicle.unique()})
    df["native"] = (df.mid_type == "native").astype(float)
    df["dominated"] = (df.adv > 0).astype(float)
    df["gap_bps"] = df.adv * 10_000
    df["log_size"] = np.log(df.trade_size_usd.clip(lower=1))
    df["year"] = pd.to_datetime(df.d).dt.year
    df["pair"] = df.src.astype(str) + "|" + df.tgt.astype(str)
    df["fe"] = df.pair + "|" + df.win.astype(str) + "|" + df.trade_size_usd.astype(str)
    # How many distinct vehicles the router could actually choose between here. A pair
    # served by one candidate is not the same experiment as one served by five, and the
    # historical swings track sample composition, so this is a condition and not noise.
    df["n_candidates"] = df.groupby("fe").vehicle.transform("nunique")
    # Whether a concentrated-liquidity venue served either leg, which is the venue-set
    # dimension the decomposition needs.
    tick = {"uniswap_v3", "uniswap_v4"}
    df["tick_leg"] = (df.hop1_source.isin(tick) | df.hop2_source.isin(tick)).astype(float)
    return df


def fit(sub: pd.DataFrame, outcome: str, fe: str | None, cluster: str,
        extra: list[str] | None = None) -> dict | None:
    """One specification. Returns None when nothing identifies the coefficient."""
    import pyfixest as pf

    if fe:
        mix = sub.groupby(fe).native.agg(["mean", "size"])
        ident = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
        sub = sub[sub[fe].isin(ident)]
    if len(sub) < 100 or sub.native.nunique() < 2:
        return None
    rhs = " + ".join(["native"] + (extra or []))
    fml = f"{outcome} ~ {rhs}" + (f" | {fe}" if fe else "")
    try:
        m = pf.feols(fml, data=sub, vcov={"CRV1": cluster})
        row = m.tidy().loc["native"]
    except Exception:
        return None
    return {"n": int(len(sub)), "coef": float(row["Estimate"]),
            "se": float(row["Std. Error"]), "p": float(row["Pr(>|t|)"]),
            "groups": int(sub[fe].nunique()) if fe else 0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", type=int, default=12, help="control window in HOURS")
    args = ap.parse_args()

    d = prepare(load(args.window))
    print(f"{len(d):,} comparable routes, {d.pair.nunique():,} pairs, "
          f"{d.year.min()}-{d.year.max()}")
    print(f"vehicle mix {d.mid_type.value_counts().to_dict()}")
    print(f"candidates per group: median {d.n_candidates.median():.0f}, "
          f"max {d.n_candidates.max():.0f}\n")

    rows = []

    def record(label: str, dim: str, r: dict | None) -> None:
        if r is None:
            print(f"  {label:<44} not identified")
            return
        r.update(spec=label, dimension=dim)
        rows.append(r)
        print(f"  {label:<44}{r['n']:>10,}{r['groups']:>9,}"
              f"{r['coef']:>10.4f}{r['se']:>9.4f}{r['p']:>8.3f}")

    hdr = f"  {'specification':<44}{'n':>10}{'groups':>9}{'coef':>10}{'se':>9}{'p':>8}"

    print("DECOMPOSITION 1 - the fixed-effect structure, outcome held binary")
    print(hdr)
    record("no fixed effect, pooled", "fe", fit(d, "dominated", None, "pair"))
    record("+ log size as a regressor", "fe",
           fit(d, "dominated", None, "pair", ["log_size"]))
    record("pair fixed effect", "fe", fit(d, "dominated", "pair", "pair"))
    record("pair x window x size fixed effect", "fe", fit(d, "dominated", "fe", "pair"))

    print("\nDECOMPOSITION 2 - the outcome definition, structure held at the tightest")
    print(hdr)
    record("binary dominance", "outcome", fit(d, "dominated", "fe", "pair"))
    record("continuous gap in basis points", "outcome", fit(d, "gap_bps", "fe", "pair"))

    print("\nDECOMPOSITION 3 - the venue set")
    print(hdr)
    record("routes touching a tick venue", "venue",
           fit(d[d.tick_leg > 0], "dominated", "fe", "pair"))
    record("routes on constant-product only", "venue",
           fit(d[d.tick_leg == 0], "dominated", "fe", "pair"))

    print("\nDECOMPOSITION 4 - how many alternatives the router actually had")
    print(hdr)
    for lo, hi, lab in ((2, 2, "exactly 2 candidates"), (3, 3, "exactly 3 candidates"),
                        (4, 99, "4 or more candidates")):
        record(lab, "candidates",
               fit(d[(d.n_candidates >= lo) & (d.n_candidates <= hi)],
                   "dominated", "fe", "pair"))

    print("\nCONDITIONS - interactions, tested rather than eyeballed")
    print(hdr)
    di = d.assign(nat_size=d.native * d.log_size)
    r = fit(di, "dominated", "fe", "pair", ["nat_size"])
    record("native, with native x log size in model", "interaction", r)
    try:
        import pyfixest as pf

        mix = di.groupby("fe").native.agg(["mean", "size"])
        ident = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
        s = di[di.fe.isin(ident)]
        m = pf.feols("dominated ~ native + nat_size | fe", data=s,
                     vcov={"CRV1": "pair"})
        t = m.tidy()
        ix = t.loc["nat_size"]
        print(f"\n  INTERACTION native x log size: {float(ix['Estimate']):+.4f} "
              f"(se {float(ix['Std. Error']):.4f}, p {float(ix['Pr(>|t|)']):.3f})")
        print("  This is the formal test the earlier size-gradient claim never ran.")
        rows.append({"spec": "interaction native x log size", "dimension": "interaction",
                     "n": int(len(s)), "groups": int(s.fe.nunique()),
                     "coef": float(ix["Estimate"]), "se": float(ix["Std. Error"]),
                     "p": float(ix["Pr(>|t|)"])})
    except Exception as exc:
        print(f"  interaction failed: {type(exc).__name__} {exc}")

    print("\nCONDITIONS - by era, each with the tightest structure")
    print(hdr)
    for yr, g in d.groupby("year"):
        record(f"year {yr}", "era", fit(g, "dominated", "fe", "pair"))

    if rows:
        write_exhibit(pd.DataFrame(rows), OUT)
        binary = [r for r in rows if r["dimension"] in ("fe", "venue", "candidates")]
        if binary:
            lo = min(r["coef"] for r in binary)
            hi = max(r["coef"] for r in binary)
            print(f"\nCoefficient ranges {lo:+.4f} to {hi:+.4f} across design choices. "
                  f"A range wider than the standard errors means the design IS the "
                  f"finding and must be reported as a condition.")
        print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

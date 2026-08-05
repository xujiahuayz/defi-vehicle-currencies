#!/usr/bin/env python3
"""Is the native asset a better intermediary, holding the trade fixed? HDFE version.

Supersedes `run_vehicle_dominance_multivenue.py`, whose implementation rather than
whose design was wrong. That script built the fixed-effect fixed effect key by concatenating
strings, so 30 million long Python strings were materialised and then grouped, and it
passed 21 GB before being killed. Hand-rolled within-group demeaning is also simply
the wrong instrument for high-dimensional fixed effects at this scale, which is what
`reghdfe` exists for in Stata. The same alternating-projections algorithm is
available in Python through `pyfixest`, so the pipeline stays in one language and the
provenance chain stays unbroken.

Two changes carry the whole difference:

  DuckDB does the data work. It queries the Parquet panel directly with predicate
  and projection pushdown, so the 123.8-million-row file is never materialised. Only
  the roughly 30 million rows with both a direct and a vehicle route quoted come back,
  and the fixed-effect groups arrive as dense integer codes computed in SQL rather
  than as concatenated strings.

  pyfixest does the estimation, absorbing the pair-by-window-by-size effect properly
  and clustering by pair.

The design is unchanged and is the point of the exercise. A fixed effect absorbs (source token, target token, time window, trade size). Within one, pool depth on both legs, token
characteristics, that window's volatility and the gas regime are held fixed, so the
residual variation is which asset the route went through. Trade size belongs in the group because gas is a fixed cost per route, making dominance mechanically
size-dependent, so pooling sizes would compare a $1,000 trade against a $100,000 one.

Every specification reports the number of fixed effects that actually identify the estimate
and the minimum detectable effect, because an unbounded negative is not a null. The
v2-only predecessor rested on 703 identifying fixed effects out of 22,991, with 96.2% of its
data contributing nothing and a detectable effect near 24 percentage points against
an estimate of +0.094. The multi-venue panel quotes every vehicle candidate for every
pair-window, so identification holds by construction instead of by two intermediaries
happening to co-occur.

Window widths are integers in HOURS. A calendar month drifts between 28 and 31 days,
so a month-based control window silently changes width across the sample.

Reads   data/empirical/route_cost_panel_v2.parquet
Writes  output/exhibits/vehicle_dominance_hdfe.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
OUT = ROOT / "output" / "exhibits" / "vehicle_dominance_hdfe.jsonl"

# Control-window widths in HOURS, because the panel prices 24 hours of each day and
# the hour is its finest state. Blocks were considered and dropped: pool depth and gas
# do change every block, but v2 reserves in this dataset are hourly snapshots, so a
# window below one hour cannot be populated and a block window is a relabelling of an
# hour window. Java's call, and the measurement agrees.
#
# Why the ladder can start as tight as one hour. Identification does not depend on two
# intermediaries happening to coincide, because the panel prices EVERY vehicle
# candidate for every pair-window by construction. The identifying share is therefore
# flat at 22% to 28% across a 2,880-fold range of widths, and the rows inside
# identifying groups barely move, from 10.7 million at one hour to 11.8 million at 120
# days. At one hour there are still 3,881,534 identifying groups. So the tightest
# conditioning the data allows is reportable, and "within the same pair, the same hour
# and the same trade size" is a stronger sentence than the same claim at daily width.
WINDOW_HOURS = (1, 6, 12, 24, 72, 168, 720, 2880)


def _label(hours: int) -> str:
    return f"{hours}h" if hours < 24 else f"{hours // 24}d"


def load(window_hours: int, min_notional: float) -> pd.DataFrame:
    """Comparable routes with integer fixed-effect codes, built in SQL.

    The fixed effect and cluster identifiers are produced by DENSE_RANK in DuckDB, so what
    crosses into Python is integers rather than the concatenated strings that made
    the previous implementation exceed 21 GB.
    """
    import duckdb

    con = duckdb.connect()
    q = f"""
    WITH base AS (
        SELECT
            CAST(date AS DATE)                            AS d,
            reserve_hour_utc                               AS hr,
            src, tgt, vehicle,
            trade_size_usd,
            direct_cost_advantage                          AS adv,
            -- Integer division with an explicit FLOOR. DuckDB's `/` on BIGINT is
            -- FLOAT division, so `day_index / 3` returned 6707.667 and stayed unique
            -- per day: the window never widened, every width produced identical
            -- fixed effects, and the script then reported that the window choice did not
            -- matter. That is a fabricated robustness result, not a finding.
            -- Hours since epoch, from the date plus the panel's own hour column, then
            -- floored into windows. Explicit FLOOR because DuckDB's `/` on BIGINT is
            -- FLOAT division: dividing a day index by the width once left it unique per
            -- day, so every width produced identical groups and the script reported
            -- that the window choice did not matter, which is a fabricated robustness
            -- result rather than a finding.
            CAST(FLOOR((CAST(epoch(CAST(date AS TIMESTAMP)) / 3600 AS BIGINT)
                        + reserve_hour_utc) / CAST({int(window_hours)} AS DOUBLE))
                 AS BIGINT)                                  AS win
        FROM read_parquet('{PANEL.as_posix()}')
        WHERE direct_available
          AND vehicle_available
          AND direct_cost_advantage IS NOT NULL
          AND abs(direct_cost_advantage) <= 1.0
          AND trade_size_usd >= {float(min_notional)}
    )
    SELECT
        d, vehicle, trade_size_usd, adv,
        CAST(adv > 0 AS INTEGER)                                   AS dominated,
        DENSE_RANK() OVER (ORDER BY src, tgt)                       AS pair_id,
        DENSE_RANK() OVER (ORDER BY src, tgt, win, trade_size_usd)  AS fe_id
    FROM base
    """
    df = con.execute(q).df()
    con.close()
    return df


def summarise(df: pd.DataFrame, window_hours: int) -> dict | None:
    """Absorb the fixed effect effect, cluster by pair, and bound the estimate."""
    import pyfixest as pf

    # Only fixed effects containing BOTH a native and a non-native candidate identify the
    # coefficient; everything else is absorbed and contributes nothing.
    mix = df.groupby("fe_id").native.agg(["mean", "size"])
    ident = mix[(mix["mean"] > 0) & (mix["mean"] < 1)]
    sub = df[df.fe_id.isin(ident.index)]
    if sub.empty or sub.native.nunique() < 2:
        return None

    fit = pf.feols("dominated ~ native | fe_id", data=sub, vcov={"CRV1": "pair_id"})
    tidy = fit.tidy()
    row = tidy.loc["native"]
    coef, se = float(row["Estimate"]), float(row["Std. Error"])
    mde = 2.80 * se                       # 80% power, 5% two-sided
    return {
        "window_hours": window_hours,
        "n": int(len(sub)),
        "fe_groups": int(df.fe_id.nunique()),
        "identifying_groups": int(len(ident)),
        "clusters": int(sub.pair_id.nunique()),
        "coef": coef,
        "se": se,
        "t": float(row["t value"]),
        "p": float(row["Pr(>|t|)"]),
        "mde_80": mde,
        "bounded": bool(abs(coef) <= mde),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-notional", type=float, default=100.0)
    ap.add_argument("--windows", type=int, nargs="+", default=list(WINDOW_HOURS))
    args = ap.parse_args()

    rows = []
    for w in args.windows:
        df = load(w, args.min_notional)
        if df.empty:
            print(f"  {w}d: no comparable rows")
            continue
        df["mid_type"] = df.vehicle.map(
            {v: classify(v)[1] for v in df.vehicle.unique()})
        df["native"] = (df.mid_type == "native").astype(float)
        if w == args.windows[0]:
            print(f"comparable routes: {len(df):,}")
            print(f"vehicle mix: {df.mid_type.value_counts().to_dict()}")
            print(f"native share {df.native.mean():.1%}   "
                  f"dominated overall {df.dominated.mean():.1%}\n")
            print(f"  {'window':>8}{'groups':>12}{'ident.':>10}{'ident%':>8}"
                  f"{'rows':>12}{'clusters':>10}{'coef':>10}{'se':>9}{'p':>8}{'MDE80':>9}")
        r = summarise(df, w)
        if r is None:
            print(f"  {w}d: no identifying fixed effects")
            continue
        rows.append(r)
        print(f"  {str(w)+'d':>8}{r['fe_groups']:>12,}{r['identifying_groups']:>10,}"
              f"{r['identifying_groups']/max(r['fe_groups'],1):>7.1%}{r['n']:>12,}"
              f"{r['clusters']:>10,}{r['coef']:>10.4f}{r['se']:>9.4f}"
              f"{r['p']:>8.3f}{r['mde_80']:>9.4f}")

    if not rows:
        print("no estimates produced")
        return 1
    spread = max(r["coef"] for r in rows) - min(r["coef"] for r in rows)
    med_se = float(pd.Series([r["se"] for r in rows]).median())
    print(f"\ncoefficient spread across windows {spread:.4f} against a median "
          f"standard error of {med_se:.4f}: "
          f"{'the window choice is not driving the answer' if spread < 2*med_se else 'THE WINDOW CHOICE MATTERS, do not pick one silently'}")
    bounded = [r for r in rows if r["bounded"]]
    if bounded:
        print(f"{len(bounded)} of {len(rows)} windows give a BOUNDED estimate: the "
              f"design cannot rule out effects smaller than its detectable size, so "
              f"these are not nulls.")
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

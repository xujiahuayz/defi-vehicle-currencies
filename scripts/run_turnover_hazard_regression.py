#!/usr/bin/env python3
"""Does observed cost disadvantage predict next-day vehicle-role turnover within pairs?

`scripts/measure_survival_at_block.py` reports an unconditional comparison: the role turns
over on 12.9% of pair-days when its holder is beaten on cost against 11.0% when it is the
cheapest available, a ratio of 1.17. That is a difference in raw rates and it identifies
nothing. Pairs differ in how contested they are, the number of candidates on a pair
mechanically raises the chance that some challenger overtakes the incumbent, market-wide
conditions move both the dominance state and the turnover rate together, and the composition
of pairs changes across six years. Any of those produces a ratio above one with no
incumbency story behind it.

So the estimand is estimated here as a conditional change in the next-day turnover
probability on a discrete-time panel of pair-days, with the turnover event as the outcome:

    y_{ab,t+1} = 1{ the asset holding the largest routing share on (a,b) changes at t+1 }

against the incumbent's dominance state at t, absorbing a pair fixed effect and a calendar
fixed effect, with the candidate count entered as a control because it changes the number of
ways the event can occur without changing anyone's incentive. Standard errors cluster on the
pair, since spells within a pair are the repeated observations.

The implemented estimator is a linear probability model with high-dimensional absorption.
Its coefficient is a probability change, not a complementary-log-log coefficient, and the
reported ratio is only that probability change divided by the undominated baseline rate.
It must not be described as a fitted proportional-hazard ratio. A grouped-time logit or
complementary-log-log model belongs in a separate runner with the identical risk set.

What would falsify the incumbency reading. A conditional probability change at or below zero
says the observed cost comparison does not predict who intermediates next. A large positive
change says turnover follows the observed comparison more closely. The raw 1.17 sits close
enough to one that the conditional estimate can land either side, which is why it has to be
run.

Reads   output/exhibits/survival_at_block_panel.jsonl   (written by measure_survival_at_block.py)
Writes  output/exhibits/turnover_hazard_regression.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "output" / "exhibits" / "survival_at_block_panel.jsonl"
OUT = ROOT / "output" / "exhibits" / "turnover_hazard_regression.jsonl"


def load() -> pd.DataFrame:
    if not PANEL.exists():
        raise SystemExit(f"no panel at {PANEL.relative_to(ROOT)}; run "
                         f"scripts/measure_survival_at_block.py --emit-panel first")
    d = pd.read_json(PANEL, lines=True)
    d["pair"] = d.src.astype(str) + "|" + d.tgt.astype(str)
    d["day"] = d.day.astype(str)
    d["month"] = d.day.str.slice(0, 6)
    d["log_candidates"] = np.log(d.n_candidates.clip(lower=1))
    return d


def fit(d: pd.DataFrame, fe: str | None, controls: list[str], label: str) -> dict | None:
    import pyfixest as pf

    sub = d
    if fe:
        # A fixed effect identifies nothing where the treatment does not vary inside it.
        for f in fe.split("+"):
            f = f.strip()
            mix = sub.groupby(f).holder_dominated.agg(["mean", "size"])
            keep = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
            sub = sub[sub[f].isin(keep)]
    if len(sub) < 100 or sub.holder_dominated.nunique() < 2 or sub.turned_over.nunique() < 2:
        return None
    rhs = " + ".join(["holder_dominated"] + controls)
    fml = f"turned_over ~ {rhs}" + (f" | {fe}" if fe else "")
    try:
        m = pf.feols(fml, data=sub, vcov={"CRV1": "pair"})
        row = m.tidy().loc["holder_dominated"]
    except Exception as exc:
        print(f"    {label}: {type(exc).__name__} {str(exc)[:70]}")
        return None
    base = float(sub[sub.holder_dominated == 0].turned_over.mean())
    coef = float(row["Estimate"])
    standard_error = float(row["Std. Error"])
    return {"spec": label, "n": int(len(sub)),
            "groups": int(sub[fe.split("+")[0].strip()].nunique()) if fe else 0,
            "coef": coef, "se": standard_error,
            "confidence_interval_lower": coef - 1.96 * standard_error,
            "confidence_interval_upper": coef + 1.96 * standard_error,
            "p": float(row["Pr(>|t|)"]),
            "baseline_rate": base,
            # Scale the linear-probability change by the undominated baseline for a
            # descriptive ratio. This is not a fitted proportional-hazard ratio.
            "baseline_scaled_probability_ratio": (
                (base + coef) / base if base > 0 else float("nan")
            )}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-pair-days", type=int, default=5)
    args = ap.parse_args()

    d = load()
    counts = d.groupby("pair").size()
    d = d[d.pair.isin(counts[counts >= args.min_pair_days].index)]
    print(f"{len(d):,} pair-days, {d.pair.nunique():,} pairs, "
          f"{d.day.nunique()} days {d.day.min()}..{d.day.max()}")
    print(f"unconditional turnover: dominated {d[d.holder_dominated == 1].turned_over.mean():.2%}, "
          f"cheapest {d[d.holder_dominated == 0].turned_over.mean():.2%}\n")

    rows = []
    print(f"  {'specification':<44}{'n':>9}{'coef':>10}{'se':>9}{'p':>8}{'ratio':>8}")
    for label, fe, ctrl in (
        ("pooled, no controls", None, []),
        ("+ candidate count", None, ["log_candidates"]),
        ("pair fixed effect", "pair", ["log_candidates"]),
        ("calendar month fixed effect", "month", ["log_candidates"]),
        ("pair and month fixed effects", "pair + month", ["log_candidates"]),
    ):
        r = fit(d, fe, ctrl, label)
        if r is None:
            print(f"  {label:<44}{'not identified':>44}")
            continue
        rows.append(r)
        print(f"  {label:<44}{r['n']:>9,}{r['coef']:>10.4f}{r['se']:>9.4f}"
              f"{r['p']:>8.3f}{r['baseline_scaled_probability_ratio']:>8.2f}")

    if not rows:
        print("\nNothing identified. With a pair fixed effect the treatment has to vary")
        print("within a pair, and on a short window most pairs are dominated throughout.")
        return 1

    write_exhibit(pd.DataFrame(rows), OUT)
    tight = [r for r in rows if r["groups"]]
    if tight:
        r = tight[-1]
        print(f"\nUnder the tightest absorption the dominance indicator moves the daily "
              f"turnover probability by {r['coef']:+.4f} ({r['p']:.3f}) on {r['n']:,} "
              f"pair-days in {r['groups']:,} groups, a baseline-scaled probability ratio of "
              f"{r['baseline_scaled_probability_ratio']:.2f} against an undominated baseline of "
              f"{r['baseline_rate']:.2%}.")
        if r["p"] > 0.10:
            print("The estimate is imprecise at conventional levels. It does not establish")
            print("either a cost response or its absence; the coefficient and interval bound")
            print("what this realised-route panel can resolve.")
        else:
            print("The conditional effect survives absorption, so turnover does respond to")
            print("cost within a pair, and the incumbency premium is the residual.")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

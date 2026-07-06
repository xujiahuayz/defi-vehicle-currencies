#!/usr/bin/env python3
"""Assess non-Uniswap executable-depth quote coverage and exclusions.

The JFE pre-write review asked whether Curve, Balancer, and Fluid should be in
the executable-depth route-cost panel. This script does not fake quote support:
it measures the realized volume at stake and records which sources have enough
state in the rebuilt raw layer for an auditable quote.
"""
from __future__ import annotations

import gzip
import json
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

NONUNI = ["curve", "balancer", "fluid"]


def _unified_volume() -> pd.DataFrame:
    rows = []
    files = sorted((DATA / "unified").glob("[0-9]" * 8 + ".parquet"))
    for i, path in enumerate(files, 1):
        d = pd.read_parquet(path, columns=["source", "amount_usd", "tx_hash"])
        g = d.groupby("source", as_index=False).agg(
            leg_volume_usd=("amount_usd", "sum"),
            legs=("amount_usd", "size"),
            transactions=("tx_hash", "nunique"),
        )
        g["date"] = path.stem
        rows.append(g)
        if i % 250 == 0 or i == len(files):
            print(f"non-Uni volume scan [{i}/{len(files)}] {path.stem}", flush=True)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _iter_jsonl_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _state_rows(source: str) -> dict[str, int | float]:
    if source == "fluid":
        files = sorted((DATA / "raw" / "dune" / "fluid").glob("fluid_daily_*.jsonl.gz"))
    else:
        files = sorted((DATA / "raw" / "thegraph" / source).glob(f"{source}_daily_*.jsonl.gz"))
    days = 0
    rows = 0
    quoteable = 0
    weighted = 0
    stable_like = 0
    for path in files:
        day_rows = 0
        for rec in _iter_jsonl_gz(path):
            rows += 1
            day_rows += 1
            if source == "balancer":
                pool = rec.get("pool") or {}
                tokens = pool.get("tokens") or []
                ptype = str(pool.get("poolType") or "")
                has_state = (
                    len(tokens) >= 2
                    and all(float(t.get("balance") or 0) > 0 for t in tokens)
                    and all(t.get("weight") not in (None, "") for t in tokens)
                    and rec.get("pool", {}).get("swapFee") not in (None, "")
                )
                if has_state:
                    quoteable += 1
                    if ptype.lower() == "weighted":
                        weighted += 1
            elif source == "curve":
                balances = rec.get("inputTokenBalances") or []
                tokens = (rec.get("pool") or {}).get("inputTokens") or []
                weights = rec.get("inputTokenWeights") or []
                has_balances = len(tokens) >= 2 and len(balances) == len(tokens)
                if has_balances:
                    stable_like += 1
                # Exact StableSwap quoting requires amplification / ramp state.
                # The rebuilt raw snapshot does not contain it, so exact quoteable
                # remains deliberately zero rather than approximated.
            elif source == "fluid":
                # Dune dex.trades aggregates gave trades and daily volume, not
                # pool reserve/depth state.
                pass
        if day_rows:
            days += 1
    return {
        "state_days": days,
        "state_rows": rows,
        "quoteable_rows": quoteable,
        "weighted_rows": weighted,
        "balance_rows_no_a": stable_like,
    }


def run() -> pd.DataFrame:
    vol = _unified_volume()
    source = vol.groupby("source", as_index=False).agg(
        volume_usd=("leg_volume_usd", "sum"),
        days=("date", "nunique"),
        legs=("legs", "sum"),
        transactions=("transactions", "sum"),
    )
    total_volume = float(source["volume_usd"].sum())
    rows = []
    for src in NONUNI:
        g = source[source["source"].eq(src)]
        state = _state_rows(src)
        volume = float(g["volume_usd"].iloc[0]) if not g.empty else 0.0
        days = int(g["days"].iloc[0]) if not g.empty else 0
        legs = int(g["legs"].iloc[0]) if not g.empty else 0
        if src == "balancer":
            status = "Quoteable for weighted pools"
            reason = "Balances, weights, token decimals, and swap fees are in daily pool snapshots."
            exact_rows = int(state["quoteable_rows"])
        elif src == "curve":
            status = "Excluded from exact quotes"
            reason = "Balances are present, but amplification/ramp state is not in the raw daily snapshot."
            exact_rows = 0
        else:
            status = "Excluded from exact quotes"
            reason = "Dune Fluid data has executed trades and daily volume, not reserve/depth state."
            exact_rows = 0
        rows.append({
            "Source": src,
            "Unified days": _int(days),
            "Unified legs": _int(legs),
            "Volume share (%)": _pct(volume / total_volume if total_volume else float("nan")),
            "Daily state days": _int(state["state_days"]),
            "Daily state rows": _int(state["state_rows"]),
            "Exact quoteable rows": _int(exact_rows),
            "Decision": status,
            "Reason": reason,
        })
    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    out.to_csv(EMP / "nonuni_quote_coverage.csv", index=False)
    _write_table(
        out,
        "table_r08_nonuni_quote_coverage",
        "Executable-depth coverage for Curve, Balancer, and Fluid.",
        "tab:nonuni-quote-coverage",
        note=(
            "The table reports realized unified-route volume by source and whether the rebuilt "
            "raw layer contains enough pool state for auditable executable-depth quotes. Curve "
            "and Fluid are excluded from exact route-cost quotes rather than approximated."
        ),
    )
    print(f"wrote {len(out)} rows -> {EMP / 'nonuni_quote_coverage.csv'}")
    return out


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

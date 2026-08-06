#!/usr/bin/env python3
"""Full-panel daily series of route composition across the consolidated venue layer.

Answers one descriptive question on every day of the sample: of the routes that
pass through an intermediary at all, what share span more than one venue?

The same measures are also reported for a balanced five-venue perimeter observed
throughout the V3 era. That series excludes any route touching a later entrant, so
growth within it cannot be produced mechanically by adding Sushi V3, Fluid or V4.

Motivation. A single-venue study of vehicle-currency formation is not merely
incomplete. If routers increasingly split a single economic trade across
venues, then the venue is the wrong unit of analysis and the intermediating
asset is the right one. An eight-day sample suggested the cross-venue share
quadruples over the sample; this computes it on all ~2,277 days so the claim
can be stated with a full series behind it.

Definitions used here, narrow by design so nothing depends on the
still-open vehicle-asset definitions:
  route       one reconstructed input-to-output path, keyed (tx_hash, component_id)
  multi-leg   a route whose legs number more than one
  cross-venue a multi-leg route whose legs touch more than one `source`
  economic    a multi-leg route whose first input token differs from its last
              output token

WHY THE ECONOMIC FILTER EXISTS. A route that starts and ends in the same token
(A -> K -> A) moves no value between two parties: it is atomic arbitrage or wash
trading. On 2025-12-06 such round trips were 25.6% of multi-leg routes by count
and 90.5% by dollar value, which is the most extreme day of 79 sampled across the
corpus, where the median day runs 12.7% by count and 21.7% by value and no other
sampled day exceeds 81.8% by value. That single day drove the cross-venue
value share to 9.6% while the count share sat at 60.6%. Excluding them puts the
value share at 88.8%. So the entire apparent 2025-Q4 reversal in the
value-weighted series was round-trip flow in the denominator. One contributing
case: six separate transactions each running WETH -> (junk token) -> WETH on one
venue, each repriced to exactly $9,113,892.

This is the same threat the reference repo's `ddc.integrity` module addresses
with citations (Cong, Li, Tang and Yang 2023 on wash trading; Daian et al. 2020
and Heimbach et al. 2024 on MEV and non-atomic arbitrage, the latter measuring
over a quarter of Ethereum DEX volume as likely non-atomic arbitrage). That
module's conclusion applies here directly: volume-weighted measures are more
exposed to inflation than count-based ones, so the count series is reported as
primary and the value series as secondary.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/cross_venue_routing_daily.parquet
        output/exhibits/cross_venue_routing_series.jsonl
        output/exhibits/cross_venue_routing_inference.jsonl

Run     ./scripts/run scripts/build_cross_venue_routing_series.py [--workers N]
Rebuild is idempotent: delete the outputs and rerun to regenerate byte-identically.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.analysis.regression import year_endpoint_change
from ddvc.asset_types import canonical_token
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
OUT_PARQUET = DATA_DIR / "processed" / "cross_venue_routing_daily.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "cross_venue_routing_series.jsonl"
OUT_INFERENCE = OUTPUT_DIR / "exhibits" / "cross_venue_routing_inference.jsonl"
MAX_WORKERS = 8
CODE_SOURCES = [
    "scripts/build_cross_venue_routing_series.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/reconstruct/__init__.py",
]

COLS = ["tx_hash", "component_id", "source", "amount_usd", "route_class",
        "token_in", "token_out", "log_index"]

# These five venue families are all observed from 2021-05-04 through the sample end.
# Keeping only complete reconstructed routes whose every leg is in this set separates
# maturation inside a fixed market perimeter from the mechanical addition of Sushi V3,
# Fluid and Uniswap V4 later in the sample.
BALANCED_VENUES = frozenset(
    {"uniswap_v2", "sushiswap_v2", "curve", "balancer", "uniswap_v3"}
)


def bounded_workers(requested: int) -> int:
    return min(MAX_WORKERS, max(1, requested))


def empty_day(date: object) -> dict[str, object]:
    return {
        "date": date,
        "legs": 0,
        "routes": 0,
        "single_leg_routes": 0,
        "multi_leg_routes": 0,
        "round_trip_routes": 0,
        "economic_routes": 0,
        "economic_multileg_routes": 0,
        "economic_multileg_share": float("nan"),
        "economic_multileg_swap_legs": 0,
        "economic_multileg_venue_count": 0,
        "economic_multileg_over_two_routes": 0,
        "economic_multileg_mean_legs": float("nan"),
        "economic_multileg_mean_venues": float("nan"),
        "economic_multileg_over_two_share": float("nan"),
        "balanced_routes": 0,
        "balanced_single_leg_routes": 0,
        "balanced_multi_leg_routes": 0,
        "balanced_round_trip_routes": 0,
        "balanced_economic_routes": 0,
        "balanced_economic_multileg_routes": 0,
        "balanced_economic_multileg_share": float("nan"),
        "balanced_economic_multileg_swap_legs": 0,
        "balanced_economic_multileg_venue_count": 0,
        "balanced_economic_multileg_over_two_routes": 0,
        "balanced_economic_multileg_mean_legs": float("nan"),
        "balanced_economic_multileg_mean_venues": float("nan"),
        "balanced_economic_multileg_over_two_share": float("nan"),
        "balanced_cross_venue_routes": 0,
        "balanced_cross_venue_share": float("nan"),
        "balanced_cross_venue_usd_share": float("nan"),
        "balanced_economic_multileg_usd": 0.0,
        "balanced_cross_venue_usd": 0.0,
        "cross_venue_routes": 0,
        "cross_venue_share": float("nan"),
        "cross_venue_usd_share": float("nan"),
        "cross_venue_share_unfiltered": float("nan"),
        "cross_venue_usd_share_unfiltered": float("nan"),
        "round_trip_share_of_multileg": float("nan"),
        "round_trip_usd_share_of_multileg": float("nan"),
        "economic_multileg_usd": 0.0,
        "cross_venue_usd": 0.0,
        "total_usd": 0.0,
        "venues_active": 0,
    }


def one_day(path: Path) -> dict | None:
    """Reduce a single day of swap legs to route-composition counts."""
    try:
        df = pd.read_parquet(path, columns=COLS)
    except Exception as exc:  # a malformed day should not kill the panel
        return {"date": path.stem, "error": str(exc)[:120]}
    df = df[df["route_class"].isin(["single", "coherent"])].copy()
    if df.empty:
        return empty_day(pd.to_datetime(path.stem, format="%Y%m%d"))

    df = df.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    df["_balanced_venue"] = df["source"].isin(BALANCED_VENUES)
    g = df.groupby(["tx_hash", "component_id"], sort=False)
    legs = g.size()
    venues = g["source"].nunique()
    balanced = g["_balanced_venue"].all()
    usd = g["amount_usd"].max()  # route notional, not the sum of its legs
    first_in = g["token_in"].first().map(canonical_token)
    last_out = g["token_out"].last().map(canonical_token)

    multi = legs > 1
    same_endpoint = first_in == last_out
    round_trip = multi & same_endpoint            # atomic arbitrage / wash
    economic_route = ~same_endpoint
    econ = multi & economic_route                 # genuine A -> K -> B exchange
    cross_all = multi & (venues > 1)             # unfiltered, kept for the audit
    cross = econ & (venues > 1)                  # headline
    complex_route = econ & (legs > 2)
    balanced_econ = econ & balanced
    balanced_economic_route = economic_route & balanced
    balanced_cross = balanced_econ & (venues > 1)
    balanced_complex = balanced_econ & (legs > 2)

    def share(num, den):
        d = den.sum()
        return float(num.sum() / d) if d else float("nan")

    def ushare(num, den):
        d = usd[den].sum()
        return float(usd[num].sum() / d) if d else float("nan")

    return {
        "date": pd.to_datetime(path.stem, format="%Y%m%d"),
        "legs": int(len(df)),
        "routes": int(len(legs)),
        "single_leg_routes": int((~multi).sum()),
        "multi_leg_routes": int(multi.sum()),
        "round_trip_routes": int(round_trip.sum()),
        "economic_routes": int(economic_route.sum()),
        "economic_multileg_routes": int(econ.sum()),
        "economic_multileg_share": share(econ, economic_route),
        "economic_multileg_swap_legs": int(legs[econ].sum()),
        "economic_multileg_venue_count": int(venues[econ].sum()),
        "economic_multileg_over_two_routes": int(complex_route.sum()),
        "economic_multileg_mean_legs": float(legs[econ].mean()),
        "economic_multileg_mean_venues": float(venues[econ].mean()),
        "economic_multileg_over_two_share": share(complex_route, econ),
        "balanced_routes": int(balanced.sum()),
        "balanced_single_leg_routes": int((balanced & ~multi).sum()),
        "balanced_multi_leg_routes": int((balanced & multi).sum()),
        "balanced_round_trip_routes": int((balanced & round_trip).sum()),
        "balanced_economic_routes": int(balanced_economic_route.sum()),
        "balanced_economic_multileg_routes": int(balanced_econ.sum()),
        "balanced_economic_multileg_share": share(
            balanced_econ, balanced_economic_route
        ),
        "balanced_economic_multileg_swap_legs": int(legs[balanced_econ].sum()),
        "balanced_economic_multileg_venue_count": int(venues[balanced_econ].sum()),
        "balanced_economic_multileg_over_two_routes": int(balanced_complex.sum()),
        "balanced_economic_multileg_mean_legs": float(legs[balanced_econ].mean()),
        "balanced_economic_multileg_mean_venues": float(venues[balanced_econ].mean()),
        "balanced_economic_multileg_over_two_share": share(
            balanced_complex, balanced_econ
        ),
        "balanced_cross_venue_routes": int(balanced_cross.sum()),
        "balanced_cross_venue_share": share(balanced_cross, balanced_econ),
        "balanced_cross_venue_usd_share": ushare(balanced_cross, balanced_econ),
        "balanced_economic_multileg_usd": float(usd[balanced_econ].sum()),
        "balanced_cross_venue_usd": float(usd[balanced_cross].sum()),
        "cross_venue_routes": int(cross.sum()),
        # headline: of ECONOMIC intermediated routes, what share spans venues
        "cross_venue_share": share(cross, econ),
        "cross_venue_usd_share": ushare(cross, econ),
        # audit trail: the same statistic WITHOUT the economic filter, so the
        # contamination is visible in the panel rather than only in a comment
        "cross_venue_share_unfiltered": share(cross_all, multi),
        "cross_venue_usd_share_unfiltered": ushare(cross_all, multi),
        "round_trip_share_of_multileg": share(round_trip, multi),
        "round_trip_usd_share_of_multileg": ushare(round_trip, multi),
        "economic_multileg_usd": float(usd[econ].sum()),
        "cross_venue_usd": float(usd[cross].sum()),
        "total_usd": float(usd.sum()),
        "venues_active": int(df["source"].nunique()),
    }


def routing_incidence_change_tests(
    panel: pd.DataFrame,
    *,
    baseline_year: int = 2022,
    comparison_year: int = 2026,
    hac_lag: int = 30,
) -> pd.DataFrame:
    """Test the change in indirect-route incidence on full and fixed perimeters."""
    data = panel.copy().sort_values("date", kind="stable")
    data["year"] = pd.to_datetime(data["date"]).dt.year
    data = data[data["year"].between(baseline_year, comparison_year)]

    def yearly_sum(column: str, year: int) -> float:
        return float(data.loc[data["year"].eq(year), column].sum())

    def support_share(year: int) -> float:
        denominator = yearly_sum("economic_routes", year)
        return yearly_sum("balanced_economic_routes", year) / denominator

    def complement_incidence(year: int) -> float | None:
        denominator = yearly_sum("economic_routes", year) - yearly_sum(
            "balanced_economic_routes", year
        )
        if denominator <= 0:
            return None
        numerator = yearly_sum("economic_multileg_routes", year) - yearly_sum(
            "balanced_economic_multileg_routes", year
        )
        return numerator / denominator

    rows: list[dict[str, object]] = []
    for scope, prefix in (("full", ""), ("balanced", "balanced_")):
        share_column = f"{prefix}economic_multileg_share"
        numerator_column = f"{prefix}economic_multileg_routes"
        denominator_column = f"{prefix}economic_routes"
        sample = data[["year", share_column]].dropna()
        estimate = year_endpoint_change(
            sample[share_column],
            sample["year"],
            baseline_year=baseline_year,
            comparison_year=comparison_year,
            hac_lag=hac_lag,
        )

        def ratio_of_totals(year: int) -> float:
            selected = data["year"].eq(year)
            denominator = data.loc[selected, denominator_column].sum()
            if denominator <= 0:
                raise ValueError("routing-incidence denominator must be positive")
            return float(data.loc[selected, numerator_column].sum() / denominator)

        rows.append(
            {
                "scope": scope,
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "baseline_ratio_of_totals": ratio_of_totals(baseline_year),
                "comparison_ratio_of_totals": ratio_of_totals(comparison_year),
                "baseline_daily_mean": estimate.baseline_mean,
                "comparison_daily_mean": estimate.comparison_mean,
                "change": estimate.change,
                "hac_standard_error": estimate.standard_error,
                "t_statistic": estimate.t_statistic,
                "p_value": estimate.p_value,
                "days": estimate.n_observations,
                "hac_lag_days": hac_lag,
                "share_denominator": "economic routes excluding canonical endpoint round trips",
                "balanced_route_coverage_baseline": support_share(baseline_year),
                "balanced_route_coverage_comparison": support_share(comparison_year),
                "entrant_touching_incidence_baseline": complement_incidence(baseline_year),
                "entrant_touching_incidence_comparison": complement_incidence(comparison_year),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="first N days only, for a smoke test")
    args = ap.parse_args()
    args.workers = bounded_workers(args.workers)

    days = sorted(UNIFIED.glob("*.parquet"))
    if args.limit:
        days = days[: args.limit]
    if not days:
        sys.exit(f"no unified day files under {UNIFIED}")
    print(f"reducing {len(days):,} days with {args.workers} workers", flush=True)

    rows, errors = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one_day, d): d for d in days}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r is None:
                continue
            (errors if "error" in r else rows).append(r)
            if i % 250 == 0:
                print(f"  {i:,}/{len(days):,}", flush=True)

    if errors:
        print(f"\n{len(errors)} day(s) failed to read:")
        for e in errors[:10]:
            print("  ", e["date"], e["error"])
        print("refusing to write a partial cross-venue panel")
        return 1

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if len(df) != len(days):
        print(f"expected {len(days):,} days but built {len(df):,}; refusing partial output")
        return 1
    if args.limit is not None:
        print(f"smoke reduction complete on {len(df):,} days; canonical outputs unchanged")
        return 0

    write_panel(
        df,
        OUT_PARQUET,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        notes="clean single/coherent routes only; round trips retained as diagnostics",
    )
    write_exhibit(
        df,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
    )
    inference = routing_incidence_change_tests(df)
    write_exhibit(
        inference,
        OUT_INFERENCE,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
        notes="equal-weighted daily indirect-route incidence; Newey-West Bartlett covariance",
    )

    print(f"\ndays retained: {len(df):,}   {df.date.min().date()} to {df.date.max().date()}")
    print(f"total legs: {df.legs.sum():,}   total routes: {df.routes.sum():,}")
    print("\nannual ratios of totals (count-weighted, then value-weighted):")
    a = df.set_index("date").resample("YS").agg(
        econ=("economic_multileg_routes", "sum"),
        econ_legs=("economic_multileg_swap_legs", "sum"),
        econ_venues=("economic_multileg_venue_count", "sum"),
        complex_routes=("economic_multileg_over_two_routes", "sum"),
        cross=("cross_venue_routes", "sum"),
        cross_usd=("cross_venue_usd", "sum"),
        econ_usd=("economic_multileg_usd", "sum"),
        round_trip=("round_trip_routes", "sum"),
        multi=("multi_leg_routes", "sum"),
        routes=("routes", "sum"),
        economic_routes=("economic_routes", "sum"),
        venues_active=("venues_active", "max"),
        balanced_econ=("balanced_economic_multileg_routes", "sum"),
        balanced_routes=("balanced_routes", "sum"),
        balanced_economic_routes=("balanced_economic_routes", "sum"),
        balanced_econ_legs=("balanced_economic_multileg_swap_legs", "sum"),
        balanced_econ_venues=("balanced_economic_multileg_venue_count", "sum"),
        balanced_complex_routes=("balanced_economic_multileg_over_two_routes", "sum"),
        balanced_cross=("balanced_cross_venue_routes", "sum"),
        balanced_cross_usd=("balanced_cross_venue_usd", "sum"),
        balanced_econ_usd=("balanced_economic_multileg_usd", "sum"),
    )
    a["cross_venue_share_of_multileg"] = a["cross"] / a["econ"]
    a["cross_venue_usd_share"] = a["cross_usd"] / a["econ_usd"]
    a["round_trip_share"] = a["round_trip"] / a["multi"]
    a["economic_multileg_share"] = a["econ"] / a["economic_routes"]
    a["mean_legs"] = a["econ_legs"] / a["econ"]
    a["mean_venues"] = a["econ_venues"] / a["econ"]
    a["complex_share"] = a["complex_routes"] / a["econ"]
    print("  year   count   value   multi/all   >2 legs   mean legs   mean venues   rt share   venues")
    for idx, row in a.iterrows():
        print(f"  {idx.year}   {row.cross_venue_share_of_multileg:6.1%}"
              f"  {row.cross_venue_usd_share:6.1%}"
              f"     {row.economic_multileg_share:6.1%}"
              f"     {row.complex_share:6.1%}"
              f"        {row.mean_legs:5.2f}"
              f"          {row.mean_venues:5.2f}"
              f"     {row.round_trip_share:6.1%}"
              f"        {int(row.venues_active)}")
    a["balanced_cross_share"] = a["balanced_cross"] / a["balanced_econ"]
    a["balanced_cross_usd_share"] = a["balanced_cross_usd"] / a["balanced_econ_usd"]
    a["balanced_economic_multileg_share"] = a["balanced_econ"] / a["balanced_economic_routes"]
    a["balanced_complex_share"] = a["balanced_complex_routes"] / a["balanced_econ"]
    a["balanced_mean_legs"] = a["balanced_econ_legs"] / a["balanced_econ"]
    a["balanced_mean_venues"] = a["balanced_econ_venues"] / a["balanced_econ"]
    print("\nbalanced five-venue ratios (same perimeter throughout the V3 era):")
    print("  year   count   value   multi/all   >2 legs   mean legs   mean venues   routes")
    for idx, row in a[a.index >= "2021-05-04"].iterrows():
        print(f"  {idx.year}   {row.balanced_cross_share:6.1%}"
              f"  {row.balanced_cross_usd_share:6.1%}"
              f"     {row.balanced_economic_multileg_share:6.1%}"
              f"    {row.balanced_complex_share:6.1%}"
              f"        {row.balanced_mean_legs:5.2f}"
              f"          {row.balanced_mean_venues:5.2f}"
              f"   {int(row.balanced_econ):>10,}")
    print(
        f"\nwrote {OUT_PARQUET.relative_to(REPO_ROOT)}, "
        f"{OUT_EXHIBIT.relative_to(REPO_ROOT)} and "
        f"{OUT_INFERENCE.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

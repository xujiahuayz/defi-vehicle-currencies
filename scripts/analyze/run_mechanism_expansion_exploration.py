#!/usr/bin/env python3
"""Run provisional mechanism-search experiments for the JFE expansion loop.

This runner is intentionally exploratory. It asks whether the current measurable
paper can be turned into a stronger mechanism paper by documenting how vehicle
dominance is made and how liquidity-capital stocks relate to the vehicle role.

The estimates are correlations with fixed effects, not causal treatment effects.
Every row carries `analysis_status = exploratory_provisional` so the paper and
deck can use the results for review while stronger specifications continue.

Reads:
  data/processed/endpoint_candidate_choices.parquet
  data/processed/endpoint_candidate_pair_support.parquet
  data/processed/liquidity_capital_v2_candidate_day.parquet

Writes:
  output/exhibits/mechanism_expansion_regressions.jsonl
  output/exhibits/mechanism_expansion_market_formation.jsonl
  output/exhibits/mechanism_expansion_note.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


CHOICES = REPO_ROOT / "data/processed/endpoint_candidate_choices.parquet"
PAIR_SUPPORT = REPO_ROOT / "data/processed/endpoint_candidate_pair_support.parquet"
V2_CANDIDATE_DAY = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"

REGRESSION_OUTPUT = OUTPUT_DIR / "exhibits/mechanism_expansion_regressions.jsonl"
FORMATION_OUTPUT = OUTPUT_DIR / "exhibits/mechanism_expansion_market_formation.jsonl"
NOTE_OUTPUT = OUTPUT_DIR / "exhibits/mechanism_expansion_note.md"

CODE_SOURCES = [
    "scripts/analyze/run_mechanism_expansion_exploration.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/tables.py",
]
INPUTS = [
    "data/processed/endpoint_candidate_choices.parquet",
    "data/processed/endpoint_candidate_pair_support.parquet",
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
]

BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
MAX_MONTH = 6
MIN_PAIRDAY_ROUTES = 5


def _require_inputs() -> None:
    for path in (CHOICES, PAIR_SUPPORT, V2_CANDIDATE_DAY):
        if not path.exists():
            raise FileNotFoundError(path)


def load_pairday_panel(
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
    max_month: int = MAX_MONTH,
    min_pairday_routes: int = MIN_PAIRDAY_ROUTES,
) -> pd.DataFrame:
    """Return the pair-day choice surface used by the mechanism search."""

    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    query = f"""
    WITH choice AS (
      SELECT
        date,
        src,
        tgt,
        integration_scope,
        SUM(route_count) AS total_routes,
        SUM(CASE WHEN candidate_type = 'stable' THEN route_count ELSE 0 END) AS stable_routes,
        SUM(CASE WHEN candidate_type = 'native' THEN route_count ELSE 0 END) AS native_routes,
        COUNT(DISTINCT candidate_address) AS candidate_count,
        SUM(route_count * route_count) AS route_sq_sum
      FROM read_parquet('{CHOICES}')
      WHERE EXTRACT(year FROM date) IN ({baseline_year}, {comparison_year})
        AND EXTRACT(month FROM date) <= {max_month}
      GROUP BY 1, 2, 3, 4
    ),
    support AS (
      SELECT
        date,
        src,
        tgt,
        SUM(primary_choice_route_count) AS primary_choice_route_count,
        SUM(direct_route_count) AS direct_route_count,
        SUM(multiple_intermediary_route_count) AS multiple_intermediary_route_count,
        SUM(split_or_join_route_count) AS split_or_join_route_count,
        SUM(nonsequential_two_leg_route_count) AS nonsequential_two_leg_route_count,
        MIN(pair_first_supported_date) AS pair_first_supported_date,
        MAX(pair_entry_on_day) AS pair_entry_on_day
      FROM read_parquet('{PAIR_SUPPORT}')
      WHERE EXTRACT(year FROM date) IN ({baseline_year}, {comparison_year})
        AND EXTRACT(month FROM date) <= {max_month}
      GROUP BY 1, 2, 3
    )
    SELECT
      c.*,
      s.primary_choice_route_count,
      s.direct_route_count,
      s.multiple_intermediary_route_count,
      s.split_or_join_route_count,
      s.nonsequential_two_leg_route_count,
      s.pair_first_supported_date,
      s.pair_entry_on_day
    FROM choice c
    LEFT JOIN support s USING(date, src, tgt)
    WHERE c.total_routes >= {min_pairday_routes}
    """
    frame = con.execute(query).df()
    con.close()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["pair"] = frame["src"].astype(str) + ">" + frame["tgt"].astype(str)
    frame["pair_scope"] = frame["pair"] + "|" + frame["integration_scope"].astype(str)
    frame["year"] = frame["date"].dt.year
    frame["month_day"] = frame["date"].dt.strftime("%m-%d")
    frame["stable_share"] = frame["stable_routes"] / frame["total_routes"]
    frame["native_share"] = frame["native_routes"] / frame["total_routes"]
    frame["stable_winner"] = (
        frame["stable_routes"].fillna(0) >= frame["native_routes"].fillna(0)
    ).astype(float)
    frame["route_hhi"] = frame["route_sq_sum"] / frame["total_routes"].pow(2)
    denominator = frame["primary_choice_route_count"].replace(0, np.nan)
    for column in (
        "direct_route_count",
        "multiple_intermediary_route_count",
        "split_or_join_route_count",
        "nonsequential_two_leg_route_count",
    ):
        name = column.replace("_route_count", "_share")
        frame[name] = (frame[column] / denominator).replace(
            [np.inf, -np.inf], np.nan
        ).fillna(0.0)
        frame[name] = frame[name].clip(0.0, 1.0)
    frame["log_routes"] = np.log1p(frame["total_routes"])
    frame["pair_first_supported_date"] = pd.to_datetime(
        frame["pair_first_supported_date"], errors="coerce"
    )
    frame["pair_age_days"] = (
        frame["date"] - frame["pair_first_supported_date"]
    ).dt.days.clip(lower=0)
    frame["log_pair_age"] = np.log1p(frame["pair_age_days"].fillna(0))
    frame["pair_entry_on_day"] = frame["pair_entry_on_day"].fillna(False).astype(bool)
    return frame


def _fit_absorbed_grid(
    frame: pd.DataFrame,
    *,
    outcome: str,
    predictors: list[str],
    fixed_effects: tuple[str, ...],
    sample_name: str,
    family: str,
) -> list[dict[str, object]]:
    needed = list(dict.fromkeys([outcome, *predictors, *fixed_effects, "date"]))
    data = frame.loc[:, needed].replace([np.inf, -np.inf], np.nan).dropna()
    yx = pd.concat([data[outcome], data[predictors]], axis=1)
    groups = tuple(data[name] for name in fixed_effects)
    residual = absorb_fixed_effects(yx, *groups)
    fit = ols_clustered(
        residual[outcome],
        residual[predictors],
        data["date"],
        add_constant=False,
        absorbed_groups=groups,
        min_observations=1000,
        min_clusters=30,
    )
    rows: list[dict[str, object]] = []
    for predictor, beta, se, t_stat, p_value in zip(
        predictors,
        fit.beta,
        fit.standard_errors,
        fit.t_statistics,
        fit.p_values,
        strict=True,
    ):
        rows.append(
            {
                "analysis_status": "exploratory_provisional",
                "family": family,
                "sample": sample_name,
                "outcome": outcome,
                "predictor": predictor,
                "coefficient": float(beta),
                "standard_error": float(se),
                "t_statistic": float(t_stat),
                "p_value": float(p_value),
                "n_observations": int(fit.n_observations),
                "date_clusters": int(fit.n_clusters),
                "fixed_effects": "+".join(fixed_effects),
                "inference": "CR1 clustered by date after absorbing declared fixed effects",
                "interpretation": "descriptive association, not causal treatment effect",
            }
        )
    return rows


def run_pairday_regressions(pairday: pd.DataFrame) -> pd.DataFrame:
    """Fit the first mechanism-search grid for stable vehicle dominance."""

    predictors = [
        "log_routes",
        "direct_share",
        "multiple_intermediary_share",
        "split_or_join_share",
        "log_pair_age",
    ]
    rows: list[dict[str, object]] = []
    for outcome in ("stable_share", "stable_winner"):
        for fixed_effects in (("date",), ("pair_scope",), ("pair_scope", "month_day")):
            rows.extend(
                _fit_absorbed_grid(
                    pairday,
                    outcome=outcome,
                    predictors=predictors,
                    fixed_effects=fixed_effects,
                    sample_name=(
                        f"{BASELINE_YEAR}_{COMPARISON_YEAR}_jan_jun_min_"
                        f"{MIN_PAIRDAY_ROUTES}_routes"
                    ),
                    family="vehicle_dominance_pairday_features",
                )
            )
    return pd.DataFrame(rows)


def market_formation_rows(pairday: pd.DataFrame) -> pd.DataFrame:
    """Summarize whether stable dominance is made in new markets or old pairs."""

    rows: list[dict[str, object]] = []
    total_by_year = pairday.groupby("year", sort=True)["total_routes"].sum()
    for (year, entry), group in pairday.groupby(["year", "pair_entry_on_day"], sort=True):
        weighted_stable_share = float(group["stable_routes"].sum() / group["total_routes"].sum())
        rows.append(
            {
                "analysis_status": "exploratory_provisional",
                "family": "vehicle_dominance_market_formation",
                "row_type": "entry_status_by_year",
                "year": int(year),
                "entry_status": "entry_pair_day" if bool(entry) else "continuing_pair_day",
                "pair_day_rows": int(len(group)),
                "route_count": int(group["total_routes"].sum()),
                "route_mass_share_within_year": float(
                    group["total_routes"].sum() / total_by_year.loc[year]
                ),
                "stable_route_share": weighted_stable_share,
                "stable_winner_pairday_rate": float(group["stable_winner"].mean()),
                "interpretation": (
                    "new endpoint-pair activity can be compared with continuing-pair "
                    "activity, but entry timing is descriptive rather than randomized"
                ),
            }
        )

    annual = (
        pairday.groupby(["pair_scope", "year"], sort=True)
        .agg(
            stable_routes=("stable_routes", "sum"),
            native_routes=("native_routes", "sum"),
            total_routes=("total_routes", "sum"),
            observed_days=("date", "nunique"),
        )
        .reset_index()
    )
    annual = annual[annual["observed_days"] >= 3].copy()
    annual["stable_share"] = annual["stable_routes"] / annual["total_routes"]
    annual["stable_leader"] = annual["stable_routes"] >= annual["native_routes"]
    wide = annual.pivot(index="pair_scope", columns="year")
    if BASELINE_YEAR in annual["year"].unique() and COMPARISON_YEAR in annual["year"].unique():
        wide.columns = [f"{left}_{right}" for left, right in wide.columns]
        wide = wide.dropna(
            subset=[
                f"stable_share_{BASELINE_YEAR}",
                f"stable_share_{COMPARISON_YEAR}",
                f"stable_leader_{BASELINE_YEAR}",
                f"stable_leader_{COMPARISON_YEAR}",
            ]
        )
        if not wide.empty:
            delta = (
                wide[f"stable_share_{COMPARISON_YEAR}"]
                - wide[f"stable_share_{BASELINE_YEAR}"]
            )
            weights = (
                wide[f"total_routes_{BASELINE_YEAR}"]
                + wide[f"total_routes_{COMPARISON_YEAR}"]
            )
            switch_to_stable = (
                ~wide[f"stable_leader_{BASELINE_YEAR}"].astype(bool)
                & wide[f"stable_leader_{COMPARISON_YEAR}"].astype(bool)
            )
            switch_from_stable = (
                wide[f"stable_leader_{BASELINE_YEAR}"].astype(bool)
                & ~wide[f"stable_leader_{COMPARISON_YEAR}"].astype(bool)
            )
            rows.append(
                {
                    "analysis_status": "exploratory_provisional",
                    "family": "vehicle_dominance_market_formation",
                    "row_type": "common_pair_leader_switch",
                    "baseline_year": BASELINE_YEAR,
                    "comparison_year": COMPARISON_YEAR,
                    "common_pair_scopes": int(len(wide)),
                    "mean_stable_share_change": float(delta.mean()),
                    "route_weighted_stable_share_change": float(
                        np.average(delta, weights=weights)
                    ),
                    "switch_to_stable_count": int(switch_to_stable.sum()),
                    "switch_from_stable_count": int(switch_from_stable.sum()),
                    "interpretation": (
                        "within-common-pair switching is a distinct mechanism from "
                        "entry and market-composition reweighting"
                    ),
                }
            )
    return pd.DataFrame(rows)


def run_v2_liquidity_level_regressions() -> pd.DataFrame:
    """Fit contemporaneous V2 capital-stock associations with date and candidate FE."""

    frame = pd.read_parquet(V2_CANDIDATE_DAY)
    frame["origin_date"] = pd.to_datetime(frame["origin_date"])
    frame = frame.rename(columns={"origin_date": "date"})
    outcomes = ["intermediary_episode_share", "vehicle_excess_use_count_ratio"]
    predictors = [
        "v2_five_candidate_capital_share",
        "v2_log1p_deposited_capital_usd",
        "v2_candidate_pool_count",
        "v2_candidate_venue_count",
    ]
    rows: list[dict[str, object]] = []
    for outcome in outcomes:
        for predictor in predictors:
            rows.extend(
                _fit_absorbed_grid(
                    frame,
                    outcome=outcome,
                    predictors=[predictor],
                    fixed_effects=("candidate_address", "date"),
                    sample_name="v2_five_candidate_daily_full_calendar",
                    family="liquidity_capital_stock_vehicle_role_levels",
                )
            )
    result = pd.DataFrame(rows)
    result["inference"] = (
        "CR1 clustered by calendar date after absorbing candidate and date fixed effects"
    )
    result["interpretation"] = (
        "relative V2 capital-stock association in levels, contrasted with the "
        "registered change-predictability family; not LP flow or causal feedback"
    )
    return result


def write_note(regressions: pd.DataFrame, formation: pd.DataFrame) -> Path:
    """Write a short human-readable note for paper/deck triage."""

    def _coefficient(family: str, outcome: str, predictor: str, fixed_effects: str) -> str:
        match = regressions[
            regressions["family"].eq(family)
            & regressions["outcome"].eq(outcome)
            & regressions["predictor"].eq(predictor)
            & regressions["fixed_effects"].eq(fixed_effects)
        ]
        if match.empty:
            return "not estimated"
        row = match.iloc[0]
        return (
            f"{row['coefficient']:.4g} "
            f"(se {row['standard_error']:.4g}, p {row['p_value']:.3g})"
        )

    entry = formation[
        formation["row_type"].eq("entry_status_by_year")
        & formation["entry_status"].eq("entry_pair_day")
        & formation["year"].eq(COMPARISON_YEAR)
    ]
    common = formation[formation["row_type"].eq("common_pair_leader_switch")]
    lines = [
        "# Mechanism expansion exploratory note",
        "",
        "Status: exploratory provisional. These results may enter review drafts only",
        "with that label; they are not causal treatment evidence.",
        "",
        "## Current signal",
        "",
        (
            "- Same-pair-scope regressions: in pair-scope plus calendar-day-position "
            "fixed effects, multiple-intermediary share predicts stable vehicle share "
            f"by {_coefficient('vehicle_dominance_pairday_features', 'stable_share', 'multiple_intermediary_share', 'pair_scope+month_day')}."
        ),
        (
            "- Split/join complexity goes the other way in the same specification: "
            f"{_coefficient('vehicle_dominance_pairday_features', 'stable_share', 'split_or_join_share', 'pair_scope+month_day')}."
        ),
        (
            "- V2 capital levels line up with vehicle-role levels: log deposited "
            "capital predicts vehicle excess use by "
            f"{_coefficient('liquidity_capital_stock_vehicle_role_levels', 'vehicle_excess_use_count_ratio', 'v2_log1p_deposited_capital_usd', 'candidate_address+date')}."
        ),
    ]
    if not entry.empty:
        row = entry.iloc[0]
        lines.append(
            "- New endpoint-pair days in "
            f"{COMPARISON_YEAR} have a route-weighted stable share of "
            f"{row['stable_route_share']:.1%}, with "
            f"{row['route_mass_share_within_year']:.1%} of that year's route mass."
        )
    if not common.empty:
        row = common.iloc[0]
        lines.append(
            "- Common pair-scopes show limited leader rotation: "
            f"{int(row['switch_to_stable_count'])} switch to stable and "
            f"{int(row['switch_from_stable_count'])} switch away from stable; "
            f"route-weighted stable-share change is {row['route_weighted_stable_share_change']:.1%}."
        )
    lines.extend(
        [
            "",
            "## So what",
            "",
            (
                "The emerging paper angle is not simply that vehicle dominance is "
                "measurable. The stronger mechanism is that dominance is made through "
                "market formation and route architecture: new activity increasingly "
                "routes through stable vehicles, while old common pairs do not show a "
                "large clean conversion from native to stable leadership."
            ),
            "",
            (
                "The liquidity result is complementary rather than causal: deposited "
                "capital stocks track the vehicle role in levels, but the registered "
                "future-change design does not support a reciprocal feedback claim. "
                "That points toward coordination/infrastructure capital rather than a "
                "simple LPs-chase-flow story."
            ),
            "",
            "## Next experiments",
            "",
            "1. Add candidate-level risk-set choice models if feasible alternatives can be declared.",
            "2. Split market formation by endpoint type, venue scope, and route notional support.",
            "3. Build or restore LP-flow inputs before making provider-behavior claims.",
            "4. Translate this into the paper/deck as provisional, review-facing mechanism evidence.",
            "",
        ]
    )
    with atomic_output(NOTE_OUTPUT) as temporary:
        temporary.write_text("\n".join(lines), encoding="utf-8")
    return NOTE_OUTPUT


def run() -> tuple[Path, Path, Path]:
    _require_inputs()
    pairday = load_pairday_panel()
    regressions = pd.concat(
        [run_pairday_regressions(pairday), run_v2_liquidity_level_regressions()],
        ignore_index=True,
        sort=False,
    )
    formation = market_formation_rows(pairday)
    write_exhibit(
        regressions,
        REGRESSION_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        notes="exploratory JFE expansion mechanism regressions",
    )
    write_exhibit(
        formation,
        FORMATION_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        notes="exploratory market-formation and common-pair switch summaries",
    )
    write_note(regressions, formation)
    return REGRESSION_OUTPUT, FORMATION_OUTPUT, NOTE_OUTPUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    paths = run()
    print("wrote " + ", ".join(str(path) for path in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

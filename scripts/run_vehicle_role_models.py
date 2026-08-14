#!/usr/bin/env python3
"""Estimate realised vehicle utilisation and role formation/loss on explicit zeros.

The source panel must contain every candidate ever observed for an ordered pair
in every week in which that pair is active.  A zero therefore means no realised
use inside this selected ever-observed candidate set.  It is not evidence that
the route was feasible, quoted, or considered by a router.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.asset_types import classify
from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    write_model_exhibit,
    write_model_panel,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT


SOURCE_PANEL = DATA_DIR / "processed" / "architecture_role_risk_weekly.parquet"
RISK_PANEL = OUTPUT_DIR / "empirical" / "vehicle_role_transition_risk.parquet"
RESULTS = OUTPUT_DIR / "exhibits" / "vehicle_role_methodology_results.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "vehicle_role_methodology_support.jsonl"
KEYS = ("src", "sink", "vehicle_id")
CODE_SOURCES = ["scripts/run_vehicle_role_models.py", "src/ddvc/asset_types.py"]


def _finite_inference(row: pd.Series, *, model_name: str) -> tuple[float, float, float]:
    coefficient = float(row["Estimate"])
    standard_error = float(row["Std. Error"])
    p_value = float(row["Pr(>|t|)"])
    if not np.isfinite([coefficient, standard_error, p_value]).all() or standard_error <= 0:
        raise ValueError(
            f"{model_name} produced non-finite or non-positive inference; "
            "the specification is unidentified or numerically unstable"
        )
    return coefficient, standard_error, p_value


def prepare_candidate_panel(source: pd.DataFrame) -> pd.DataFrame:
    required = {"week", *KEYS, "vehicle", "total_routes"}
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"vehicle-role source panel lacks columns: {missing}")
    data = source.copy()
    data["week"] = pd.to_datetime(data["week"], errors="raise").dt.normalize()
    data["total_routes"] = pd.to_numeric(data["total_routes"], errors="raise")
    if data["total_routes"].lt(0).any() or not np.isfinite(data["total_routes"]).all():
        raise ValueError("vehicle-role source panel has invalid realised route counts")
    if data.duplicated(["week", *KEYS]).any():
        raise ValueError("vehicle-role source panel repeats a pair-candidate-week")
    data["candidate_type"] = data["vehicle_id"].map(lambda value: classify(value)[1])
    data = data[data["candidate_type"].isin(("stable", "native"))].copy()
    if data.empty:
        raise ValueError("vehicle-role source panel has no stable/native candidates")
    data["used"] = data["total_routes"].gt(0).astype(np.int8)
    data["pair"] = data["src"].astype(str) + "|" + data["sink"].astype(str)
    data["owner"] = data["pair"] + "|" + data["vehicle_id"].astype(str)
    data["pair_week"] = data["pair"] + "|" + data["week"].dt.strftime("%Y-%m-%d")
    data["week_id"] = data["week"].dt.strftime("%Y-%m-%d")
    data["stable_candidate"] = data["candidate_type"].eq("stable").astype(np.int8)
    data["year_2026"] = data["week"].dt.year.eq(2026).astype(np.int8)
    data["stable_x_2026"] = data["stable_candidate"] * data["year_2026"]
    return data.sort_values([*KEYS, "week"], kind="stable").reset_index(drop=True)


def build_transition_risk(source: pd.DataFrame) -> pd.DataFrame:
    data = prepare_candidate_panel(source)
    previous_week = data.groupby(list(KEYS), observed=True)["week"].shift()
    previous_state = data.groupby(list(KEYS), observed=True)["used"].shift()
    new_spell = previous_week.isna() | data["week"].sub(previous_week).dt.days.ne(7) | data["used"].ne(previous_state)
    data["spell_number"] = new_spell.groupby(
        [data[key] for key in KEYS], observed=True
    ).cumsum().astype(int)
    data["duration_weeks"] = (
        data.groupby([*KEYS, "spell_number"], observed=True).cumcount() + 1
    )
    data["next_week"] = data.groupby(list(KEYS), observed=True)["week"].shift(-1)
    data["next_used"] = data.groupby(list(KEYS), observed=True)["used"].shift(-1)
    data["consecutive_next"] = data["next_week"].sub(data["week"]).dt.days.eq(7)
    data = data[data["consecutive_next"]].copy()
    data["formation_event"] = ((data["used"] == 0) & (data["next_used"] == 1)).astype(np.int8)
    data["loss_event"] = ((data["used"] == 1) & (data["next_used"] == 0)).astype(np.int8)
    data["duration_2"] = data["duration_weeks"].eq(2).astype(np.int8)
    data["duration_3_4"] = data["duration_weeks"].between(3, 4).astype(np.int8)
    data["duration_5_8"] = data["duration_weeks"].between(5, 8).astype(np.int8)
    data["duration_9_plus"] = data["duration_weeks"].ge(9).astype(np.int8)
    return data


def fit_discrete_logit(risk: pd.DataFrame, transition: str) -> dict[str, object]:
    import pyfixest as pf

    if transition not in {"formation", "loss"}:
        raise ValueError(f"unknown vehicle-role transition: {transition}")
    state = 0 if transition == "formation" else 1
    outcome = f"{transition}_event"
    sample = risk[risk["used"].eq(state)].copy()
    if len(sample) < 100 or sample[outcome].nunique() < 2:
        raise ValueError(f"vehicle-role {transition} logit lacks event variation")
    rhs = "stable_candidate + duration_2 + duration_3_4 + duration_5_8 + duration_9_plus"
    model = pf.feglm(
        f"{outcome} ~ {rhs} | pair_week",
        data=sample,
        family="logit",
        vcov={"CRV1": "owner"},
        lean=True,
    )
    row = model.tidy().loc["stable_candidate"]
    coefficient, standard_error, p_value = _finite_inference(
        row, model_name=f"vehicle-role {transition} logit"
    )
    return {
        "method": "discrete_time_logit",
        "transition": transition,
        "coefficient": coefficient,
        "odds_ratio": float(np.exp(coefficient)),
        "standard_error": standard_error,
        "t_statistic": float(coefficient / standard_error),
        "p_value": p_value,
        "observations": int(len(sample)),
        "events": int(sample[outcome].sum()),
        "owners": int(sample["owner"].nunique()),
        "pair_week_cells": int(sample["pair_week"].nunique()),
        "fixed_effects": "ordered_pair_x_calendar_week",
        "duration_controls": "1|2|3-4|5-8|9+ weeks in current role state",
        "covariance": "pair_candidate_cluster_cr1",
        "estimand": f"stable-versus-native difference in next-week vehicle-role {transition} odds",
        "interpretation": "descriptive_role_duration_on_ever_observed_candidate_risk_set",
        "falsifier": f"stable and native candidates have the same conditional {transition} odds",
    }


def fit_ppml_utilisation(candidate_panel: pd.DataFrame) -> dict[str, object]:
    import pyfixest as pf

    years = sorted(candidate_panel["week"].dt.year.unique())
    if 2026 not in years or not any(year < 2026 for year in years):
        raise ValueError("PPML utilisation requires pre-2026 and 2026 weeks")
    model = pf.fepois(
        "total_routes ~ stable_x_2026 | pair_week + owner",
        data=candidate_panel,
        vcov={"CRV1": "pair + week_id"},
        lean=True,
    )
    row = model.tidy().loc["stable_x_2026"]
    coefficient, standard_error, p_value = _finite_inference(
        row, model_name="PPML realised-utilisation model"
    )
    return {
        "method": "ppml_realised_utilisation",
        "transition": "stable_relative_use_in_2026",
        "coefficient": coefficient,
        "incidence_rate_ratio": float(np.exp(coefficient)),
        "standard_error": standard_error,
        "t_statistic": float(coefficient / standard_error),
        "p_value": p_value,
        "observations": int(len(candidate_panel)),
        "zero_use_rows": int(candidate_panel["total_routes"].eq(0).sum()),
        "owners": int(candidate_panel["owner"].nunique()),
        "pair_week_cells": int(candidate_panel["pair_week"].nunique()),
        "fixed_effects": "ordered_pair_x_calendar_week_and_ordered_pair_x_candidate",
        "covariance": "two_way_ordered_pair_calendar_week_cr1",
        "estimand": "2026 relative change in realised stable-versus-native intermediary route counts",
        "interpretation": "realised_utilisation_not_preference_or_feasible_route_choice",
        "falsifier": "stable relative realised utilisation does not increase in 2026",
    }


def _spell_table(risk: pd.DataFrame, transition: str) -> pd.DataFrame:
    state = 0 if transition == "formation" else 1
    outcome = f"{transition}_event"
    sample = risk[risk["used"].eq(state)].copy()
    spells = (
        sample.groupby([*KEYS, "pair", "owner", "stable_candidate", "spell_number"], observed=True)
        .agg(duration=("duration_weeks", "max"), event=(outcome, "max"))
        .reset_index()
    )
    return spells


def fit_stratified_cox_sensitivity(risk: pd.DataFrame, transition: str) -> dict[str, object]:
    """One-covariate Breslow Cox sensitivity, stratified by ordered pair."""

    spells = _spell_table(risk, transition)
    beta = 0.0
    for _ in range(100):
        score = 0.0
        information = 0.0
        for _pair, group in spells.groupby("pair", observed=True, sort=False):
            for duration, failures in group[group["event"].eq(1)].groupby("duration", observed=True):
                at_risk = group[group["duration"].ge(duration)]
                x = at_risk["stable_candidate"].to_numpy(float)
                weight = np.exp(beta * x)
                s0 = weight.sum()
                s1 = float(weight @ x)
                s2 = float(weight @ np.square(x))
                d = len(failures)
                score += float(failures["stable_candidate"].sum()) - d * s1 / s0
                information += d * (s2 / s0 - (s1 / s0) ** 2)
        if information <= 0:
            raise ValueError(f"Cox {transition} sensitivity has no within-pair type variation")
        step = score / information
        beta += step
        if abs(step) < 1e-11:
            break
    else:
        raise RuntimeError(f"Cox {transition} sensitivity did not converge")
    owner_scores = pd.Series(0.0, index=spells["owner"].drop_duplicates())
    for _pair, group in spells.groupby("pair", observed=True, sort=False):
        for duration, failures in group[group["event"].eq(1)].groupby("duration", observed=True):
            at_risk = group[group["duration"].ge(duration)]
            x = at_risk["stable_candidate"].to_numpy(float)
            weight = np.exp(beta * x)
            d = len(failures)
            failure_contribution = failures.groupby("owner", observed=True)[
                "stable_candidate"
            ].sum()
            owner_scores.loc[failure_contribution.index] += failure_contribution.to_numpy(float)
            risk_contribution = pd.Series(
                d * weight * x / weight.sum(), index=at_risk["owner"].to_numpy()
            ).groupby(level=0).sum()
            owner_scores.loc[risk_contribution.index] -= risk_contribution.to_numpy(float)
    owner_count = len(owner_scores)
    meat = float(np.square(owner_scores.to_numpy()).sum())
    if owner_count > 1:
        meat *= owner_count / (owner_count - 1)
    standard_error = float(np.sqrt(meat) / information)
    z = beta / standard_error if standard_error > 0 else (0.0 if beta == 0 else np.sign(beta) * np.inf)
    return {
        "method": "cox_breslow_pair_stratified_sensitivity",
        "transition": transition,
        "coefficient": float(beta),
        "hazard_ratio": float(np.exp(beta)),
        "standard_error": standard_error,
        "t_statistic": float(z),
        "p_value": float(2.0 * stats.norm.sf(abs(z))),
        "observations": int(len(spells)),
        "events": int(spells["event"].sum()),
        "owners": owner_count,
        "fixed_effects": "ordered_pair_strata",
        "duration_controls": "nonparametric continuous-time baseline with Breslow weekly ties",
        "covariance": "pair_candidate_cluster_score_sandwich",
        "estimand": f"stable-versus-native vehicle-role {transition} hazard ratio",
        "interpretation": "sensitivity_only_same_spells_without_calendar_fixed_effects",
        "falsifier": f"Cox sensitivity reverses the discrete-time {transition} ordering",
    }


def run(
    *,
    source_path: Path = SOURCE_PANEL,
    risk_path: Path = RISK_PANEL,
    result_path: Path = RESULTS,
    support_path: Path = SUPPORT,
    root: Path = REPO_ROOT,
    environment=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = pd.read_parquet(source_path)
    candidate_panel = prepare_candidate_panel(source)
    risk = build_transition_risk(source)
    rows = [fit_ppml_utilisation(candidate_panel)]
    for transition in ("formation", "loss"):
        rows.append(fit_discrete_logit(risk, transition))
        rows.append(fit_stratified_cox_sensitivity(risk, transition))
    results = attach_spec_ids(
        pd.DataFrame(rows), prefix="vehicle_role_methodology", columns=("method", "transition")
    )
    support = pd.DataFrame(
        [
            {
                "source_rows": len(source),
                "stable_native_candidate_rows": len(candidate_panel),
                "zero_use_rows": int(candidate_panel["total_routes"].eq(0).sum()),
                "ordered_pairs": int(candidate_panel["pair"].nunique()),
                "pair_candidates": int(candidate_panel["owner"].nunique()),
                "weeks": int(candidate_panel["week"].nunique()),
                "formation_risk_rows": int(risk["used"].eq(0).sum()),
                "formation_events": int(risk["formation_event"].sum()),
                "loss_risk_rows": int(risk["used"].eq(1).sum()),
                "loss_events": int(risk["loss_event"].sum()),
                "candidate_set": "stable_or_native_candidates_ever_observed_for_pair",
                "zero_definition": "no_realised_use_while_ordered_pair_active",
                "opportunity_set_status": "unobserved_and_not_imputed",
            }
        ]
    )
    context = model_artifact_context(root=root, environment=environment)
    write_model_panel(
        risk,
        risk_path,
        role="support",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=[source_path],
        notes="explicit ever-observed pair-candidate weekly formation/loss risk set",
    )
    write_model_exhibit(
        results,
        result_path,
        role="diagnostic",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=[source_path, risk_path],
        notes="realised utilisation and descriptive role-duration models; no feasible opportunity set",
    )
    write_model_exhibit(
        support,
        support_path,
        role="support",
        context=context,
        code_sources=CODE_SOURCES,
        inputs=[source_path, risk_path],
        notes="risk-set construction and event support",
    )
    return results, support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PANEL)
    args = parser.parse_args()
    results, support = run(source_path=args.source)
    print(support.to_string(index=False))
    print(results.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

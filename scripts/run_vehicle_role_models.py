#!/usr/bin/env python3
"""Estimate post-first-use vehicle utilisation and substitution exits.

The source panel admits a candidate in its first observed week and retains it
through later weeks in which the ordered pair is active.  A zero therefore
means post-first-use realised non-use.  Formation before first use is
unobserved; zero does not establish that a route was feasible, quoted, or
considered by a router.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.vehicle_role_risk import (
    add_transition_taxonomy,
    build_vehicle_role_risk_panel_from_release,
)
from ddvc.artifact_release import SemanticValidationReceipt
from ddvc.asset_types import classify
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    EndpointCandidateCompositionRelease,
    current_endpoint_candidate_composition_release,
)
from ddvc.model_artifacts import (
    ModelArtifactContext,
    assert_model_artifact_certificate_identity,
    attach_spec_ids,
    model_artifact_context,
    write_model_exhibit,
    write_model_panel,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import current_artifacts, sidecar_path


RISK_PANEL = OUTPUT_DIR / "empirical" / "vehicle_role_transition_risk.parquet"
RESULTS = OUTPUT_DIR / "exhibits" / "vehicle_role_methodology_results.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "vehicle_role_methodology_support.jsonl"
KEYS = ("src", "sink", "vehicle_id")
CODE_SOURCES = [
    "scripts/run_vehicle_role_models.py",
    "src/ddvc/analysis/vehicle_role_risk.py",
    "src/ddvc/asset_types.py",
]


def _record_path(path: Path, *, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _d3_endpoint_release_record(
    context: ModelArtifactContext,
    pointer_path: Path,
    *,
    root: Path,
) -> tuple[dict[str, object], SemanticValidationReceipt]:
    relative = _record_path(pointer_path, root=root)
    if relative not in context.d3_input_relatives:
        raise ValueError(
            "vehicle-role endpoint release is outside the bound D3 release: "
            f"{relative}"
        )
    raw = context.d3_input_records.get(relative)
    if not isinstance(raw, dict) or raw.get("input_kind") != "release_pointer":
        raise ValueError(
            "vehicle-role endpoint release lacks an exact typed D3 identity record: "
            f"{relative}"
        )
    semantic = raw.get("semantic_validation")
    if not isinstance(semantic, dict):
        raise ValueError("vehicle-role endpoint D3 identity lacks semantic validation")
    generation = semantic.get("generation_id")
    fingerprint = semantic.get("validator_fingerprint")
    if not isinstance(generation, str) or not isinstance(fingerprint, str):
        raise ValueError("vehicle-role endpoint D3 semantic receipt is invalid")
    return dict(raw), SemanticValidationReceipt(generation, fingerprint)


def _assert_endpoint_release_matches_d3(
    record: dict[str, object],
    release: EndpointCandidateCompositionRelease,
    *,
    root: Path,
) -> None:
    bundle = release.bundle
    observed = {
        "path": _record_path(bundle.pointer_path, root=root),
        "input_kind": "release_pointer",
        "bytes": bundle.pointer_path.stat().st_size,
        "content_sha256": bundle.pointer_sha256,
        "release_generation": bundle.generation_id,
        "release_artifacts": [
            {
                "name": name,
                "path": _record_path(path, root=root),
                "content_sha256": bundle.artifact_sha256[name],
                "provenance_path": _record_path(sidecar_path(path), root=root),
                "provenance_sha256": bundle.provenance_sha256[name],
            }
            for name, path in sorted(bundle.artifacts.items())
        ],
        "format": "release_pointer",
        "rows": len(bundle.artifacts),
        "columns": sorted(bundle.artifacts),
        "semantic_validation": (
            bundle.semantic_receipt.as_record()
            if bundle.semantic_receipt is not None
            else None
        ),
    }
    mismatched = sorted(
        field for field, value in observed.items() if record.get(field) != value
    )
    if mismatched:
        raise ValueError(
            "vehicle-role endpoint release differs from its bound D3 identity: "
            f"fields={mismatched}"
        )


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
    required = {
        "week",
        *KEYS,
        "vehicle",
        "candidate_type",
        "total_routes",
        "pair_observed_days",
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"vehicle-role source panel lacks columns: {missing}")
    data = source.copy()
    data["week"] = pd.to_datetime(data["week"], errors="raise").dt.normalize()
    identity_columns = ["week", *KEYS, "vehicle", "candidate_type"]
    if data[identity_columns].isna().any().any():
        raise ValueError("vehicle-role source panel has missing identities or metadata")
    data["total_routes"] = pd.to_numeric(data["total_routes"], errors="raise")
    if data["total_routes"].lt(0).any() or not np.isfinite(data["total_routes"]).all():
        raise ValueError("vehicle-role source panel has invalid realised route counts")
    data["pair_observed_days"] = pd.to_numeric(
        data["pair_observed_days"], errors="raise"
    )
    if (
        data["pair_observed_days"].lt(1).any()
        or data["pair_observed_days"].gt(7).any()
        or data["pair_observed_days"].mod(1).ne(0).any()
        or not np.isfinite(data["pair_observed_days"]).all()
    ):
        raise ValueError("vehicle-role source panel has invalid observed-day cadence")
    data["pair_observed_days"] = data["pair_observed_days"].astype("int8")
    if data.duplicated(["week", *KEYS]).any():
        raise ValueError("vehicle-role source panel repeats a pair-candidate-week")
    canonical_type = data["vehicle_id"].map(lambda value: classify(value)[1])
    supplied_type = data["candidate_type"].astype(str).str.lower()
    if supplied_type.ne(canonical_type).any():
        raise ValueError(
            "vehicle-role source candidate_type metadata disagrees with canonical classification"
        )
    data["candidate_type"] = canonical_type
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
    data = data.sort_values([*KEYS, "week"], kind="stable").reset_index(drop=True)
    first_rows = data.groupby(list(KEYS), observed=True, sort=False).head(1)
    if first_rows["total_routes"].le(0).any():
        raise ValueError(
            "vehicle-role source backfills candidates before their first realised week"
        )
    return data


def build_transition_risk(source: pd.DataFrame) -> pd.DataFrame:
    data = prepare_candidate_panel(source)
    previous_week = data.groupby(list(KEYS), observed=True)["week"].shift()
    previous_state = data.groupby(list(KEYS), observed=True)["used"].shift()
    new_spell = (
        previous_week.isna()
        | data["week"].sub(previous_week).dt.days.ne(7)
        | data["used"].ne(previous_state)
    )
    data["spell_number"] = new_spell.groupby(
        [data[key] for key in KEYS], observed=True
    ).cumsum().astype(int)
    data["duration_weeks"] = (
        data.groupby([*KEYS, "spell_number"], observed=True).cumcount() + 1
    )
    data["selected_pair_routes"] = data.groupby(
        ["week", "src", "sink"], observed=True
    )["total_routes"].transform("sum")
    data = add_transition_taxonomy(data)
    data["duration_2"] = data["duration_weeks"].eq(2).astype(np.int8)
    data["duration_3_4"] = data["duration_weeks"].between(3, 4).astype(np.int8)
    data["duration_5_8"] = data["duration_weeks"].between(5, 8).astype(np.int8)
    data["duration_9_plus"] = data["duration_weeks"].ge(9).astype(np.int8)
    return data


def _fitted_sample(
    model,
    input_sample: pd.DataFrame,
    *,
    model_name: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Recover exact fitted rows after singleton and separation removal."""

    fitted_data = getattr(model, "_data", None)
    fitted_n = getattr(model, "_N", None)
    if (
        not isinstance(fitted_data, pd.DataFrame)
        or "_role_row_id" not in fitted_data
        or not isinstance(fitted_n, (int, np.integer))
    ):
        raise RuntimeError(
            f"{model_name} does not expose exact fitted-row identities; refusing guessed support"
        )
    row_ids = fitted_data["_role_row_id"]
    if row_ids.isna().any() or row_ids.duplicated().any():
        raise RuntimeError(f"{model_name} exposes invalid fitted-row identities")
    indexed = input_sample.set_index("_role_row_id", drop=False)
    if not row_ids.isin(indexed.index).all():
        raise RuntimeError(f"{model_name} fitted rows escape its declared input sample")
    fitted = indexed.loc[row_ids.tolist()].reset_index(drop=True)
    if int(fitted_n) != len(fitted):
        raise RuntimeError(f"{model_name} fitted-row count disagrees with model _N")
    separation_dropped = int(getattr(model, "n_separation_na", 0) or 0)
    total_dropped = len(input_sample) - len(fitted)
    singleton_dropped = total_dropped - separation_dropped
    if singleton_dropped < 0:
        raise RuntimeError(f"{model_name} reports inconsistent dropped-row counts")
    return fitted, {
        "input_observations": int(len(input_sample)),
        "observations": int(len(fitted)),
        "dropped_observations": int(total_dropped),
        "singleton_dropped_observations": int(singleton_dropped),
        "separation_dropped_observations": int(separation_dropped),
    }


def fit_discrete_logit(risk: pd.DataFrame, transition: str) -> dict[str, object]:
    if transition != "substitution_exit":
        raise ValueError(f"unknown vehicle-role transition: {transition}")
    import pyfixest as pf

    outcome = f"{transition}_event"
    sample = risk[
        risk["used"].eq(1) & risk["transition_observed"].astype(bool)
    ].copy()
    if len(sample) < 100 or sample[outcome].nunique() < 2:
        raise ValueError(f"vehicle-role {transition} logit lacks event variation")
    sample = sample.reset_index(drop=True)
    sample["_role_row_id"] = np.arange(len(sample), dtype=np.int64)
    rhs = "stable_candidate + duration_2 + duration_3_4 + duration_5_8 + duration_9_plus"
    model = pf.feglm(
        f"{outcome} ~ {rhs} | pair_week",
        data=sample,
        family="logit",
        vcov={"CRV1": "owner + week_id"},
        separation_check=["fe"],
        lean=False,
    )
    fitted, support = _fitted_sample(
        model, sample, model_name=f"vehicle-role {transition} logit"
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
        **support,
        "events": int(fitted[outcome].sum()),
        "owners": int(fitted["owner"].nunique()),
        "pair_candidate_clusters": int(fitted["owner"].nunique()),
        "calendar_week_clusters": int(fitted["week_id"].nunique()),
        "pair_week_cells": int(fitted["pair_week"].nunique()),
        "fixed_effects": "ordered_pair_x_calendar_week",
        "duration_controls": "1|2|3-4|5-8|9+ weeks in current role state",
        "covariance": "two_way_pair_candidate_and_calendar_week_cluster_cr1",
        "estimand": "stable-versus-native difference in next-week candidate substitution-exit odds",
        "interpretation": "descriptive_post_first_use_role_duration_on_observed_consecutive_weeks",
        "falsifier": f"stable and native candidates have the same conditional {transition} odds",
    }


def fit_ppml_utilisation(candidate_panel: pd.DataFrame) -> dict[str, object]:
    import pyfixest as pf

    years = sorted(candidate_panel["week"].dt.year.unique())
    if 2026 not in years or not any(year < 2026 for year in years):
        raise ValueError("PPML utilisation requires pre-2026 and 2026 weeks")
    sample = candidate_panel.reset_index(drop=True).copy()
    sample["_role_row_id"] = np.arange(len(sample), dtype=np.int64)
    model = pf.fepois(
        "total_routes ~ stable_x_2026 | pair_week + owner",
        data=sample,
        vcov={"CRV1": "pair + week_id"},
        separation_check=["fe"],
        lean=False,
    )
    fitted, support = _fitted_sample(
        model, sample, model_name="PPML post-first-use realised-utilisation model"
    )
    row = model.tidy().loc["stable_x_2026"]
    coefficient, standard_error, p_value = _finite_inference(
        row, model_name="PPML realised-utilisation model"
    )
    return {
        "method": "ppml_post_first_use_realised_utilisation",
        "transition": "post_first_use_stable_relative_use_in_2026",
        "coefficient": coefficient,
        "incidence_rate_ratio": float(np.exp(coefficient)),
        "standard_error": standard_error,
        "t_statistic": float(coefficient / standard_error),
        "p_value": p_value,
        **support,
        "zero_use_rows": int(fitted["total_routes"].eq(0).sum()),
        "owners": int(fitted["owner"].nunique()),
        "ordered_pair_clusters": int(fitted["pair"].nunique()),
        "calendar_week_clusters": int(fitted["week_id"].nunique()),
        "pair_week_cells": int(fitted["pair_week"].nunique()),
        "fixed_effects": "ordered_pair_x_calendar_week_and_ordered_pair_x_candidate",
        "covariance": "two_way_ordered_pair_calendar_week_cr1",
        "estimand": (
            "2026 relative change in post-first-use realised stable-versus-native "
            "intermediary route counts"
        ),
        "risk_set_entry": "candidate_first_observed_week",
        "cohort_limit": (
            "candidates are observed only after first realised use; initial formation "
            "is unobserved"
        ),
        "interpretation": (
            "post_first_use_realised_utilisation_not_preference_or_"
            "feasible_route_choice"
        ),
        "falsifier": "stable relative realised utilisation does not increase in 2026",
    }


def _spell_table(risk: pd.DataFrame, transition: str) -> pd.DataFrame:
    if transition != "substitution_exit":
        raise ValueError(
            "candidate-level Cox sensitivity is defined only for substitution exit"
        )
    outcome = f"{transition}_event"
    sample = risk[risk["used"].eq(1)].copy()
    spells = (
        sample.groupby([*KEYS, "pair", "owner", "stable_candidate", "spell_number"], observed=True)
        .agg(
            duration=("duration_weeks", "max"),
            event=(outcome, lambda values: int(values.fillna(0).max())),
            competing_event=(
                "selected_stable_native_primary_route_cessation_event",
                lambda values: int(values.fillna(0).max()),
            ),
            ends_without_observed_next=(
                "transition_observed", lambda values: int(not values.iloc[-1])
            ),
        )
        .reset_index()
    )
    if (spells["event"].eq(1) & spells["competing_event"].eq(1)).any():
        raise ValueError("substitution exit and selected-route cessation overlap")
    spells["terminal_or_gap_censor"] = (
        spells["event"].eq(0)
        & spells["competing_event"].eq(0)
        & spells["ends_without_observed_next"].eq(1)
    ).astype("int8")
    return spells


def fit_stratified_cox_sensitivity(risk: pd.DataFrame, transition: str) -> dict[str, object]:
    """One-covariate Breslow Cox sensitivity, stratified by ordered pair."""

    spells = _spell_table(risk, transition)
    beta = 0.0
    for _ in range(100):
        score = 0.0
        information = 0.0
        for _pair, group in spells.groupby("pair", observed=True, sort=False):
            for duration, failures in group[group["event"].eq(1)].groupby(
                "duration", observed=True
            ):
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
    z = (
        beta / standard_error
        if standard_error > 0
        else (0.0 if beta == 0 else np.sign(beta) * np.inf)
    )
    return {
        "method": "cox_breslow_pair_stratified_cause_specific_sensitivity",
        "transition": transition,
        "coefficient": float(beta),
        "hazard_ratio": float(np.exp(beta)),
        "standard_error": standard_error,
        "t_statistic": float(z),
        "p_value": float(2.0 * stats.norm.sf(abs(z))),
        "observations": int(len(spells)),
        "events": int(spells["event"].sum()),
        "right_censored_spells": int(spells["event"].eq(0).sum()),
        "terminal_or_gap_censored_spells": int(
            spells["terminal_or_gap_censor"].sum()
        ),
        "competing_selected_route_cessation_spells": int(
            spells["competing_event"].sum()
        ),
        "owners": owner_count,
        "fixed_effects": "ordered_pair_strata",
        "duration_controls": "nonparametric continuous-time baseline with Breslow weekly ties",
        "covariance": "pair_candidate_cluster_score_sandwich",
        "estimand": (
            "stable-versus-native cause-specific candidate substitution-exit "
            "hazard ratio"
        ),
        "interpretation": (
            "sensitivity_only_same_spells_without_calendar_fixed_effects; "
            "selected-route cessation is censored at its competing-event week"
        ),
        "falsifier": f"Cox sensitivity reverses the discrete-time {transition} ordering",
    }


def summarize_transition_support(
    source: pd.DataFrame,
    candidate_panel: pd.DataFrame,
    risk: pd.DataFrame,
) -> pd.DataFrame:
    """Count candidate exits and pair-level selected-route cessation distinctly."""

    pair_keys = ["week", "src", "sink"]
    observed = risk[risk["transition_observed"]].copy()
    pair_consistency = observed.groupby(pair_keys, observed=True).agg(
        current_route_values=("selected_pair_routes", "nunique"),
        next_route_values=("next_selected_pair_routes", "nunique"),
    )
    if pair_consistency.gt(1).any().any():
        raise ValueError("pair-level route totals are not pair-week common")
    cessation_column = "selected_stable_native_primary_route_cessation_event"
    cessation_consistency = (
        observed[observed["used"].eq(1)]
        .groupby(pair_keys, observed=True)[cessation_column]
        .nunique()
    )
    if cessation_consistency.gt(1).any():
        raise ValueError(
            "selected stable/native primary-route cessation differs across at-risk candidates"
        )
    pair_risk = (
        observed.groupby(pair_keys, observed=True, as_index=False)
        .agg(
            selected_pair_routes=("selected_pair_routes", "first"),
            next_selected_pair_routes=("next_selected_pair_routes", "first"),
        )
    )
    pair_risk = pair_risk[pair_risk["selected_pair_routes"].gt(0)].copy()
    pair_risk[cessation_column] = pair_risk[
        "next_selected_pair_routes"
    ].eq(0)
    return pd.DataFrame(
        [
            {
                "source_rows": len(source),
                "stable_native_candidate_rows": len(candidate_panel),
                "zero_use_rows": int(candidate_panel["total_routes"].eq(0).sum()),
                "ordered_pairs": int(candidate_panel["pair"].nunique()),
                "pair_candidates": int(candidate_panel["owner"].nunique()),
                "weeks": int(candidate_panel["week"].nunique()),
                "reentry_risk_rows": int(
                    (observed["used"].eq(0) & observed["prior_use_observed"]).sum()
                ),
                "reentry_events": int(observed["reentry_event"].sum()),
                "initial_formation_status": "unobserved_before_candidate_first_use",
                "continuing_use_events": int(observed["continuing_use_event"].sum()),
                "substitution_exit_risk_rows": int(observed["used"].eq(1).sum()),
                "substitution_exit_events": int(
                    observed["substitution_exit_event"].sum()
                ),
                "selected_stable_native_primary_route_cessation_risk_pair_weeks": int(
                    len(pair_risk)
                ),
                "selected_stable_native_primary_route_cessation_event_pair_weeks": int(
                    pair_risk[cessation_column].sum()
                ),
                "selected_stable_native_primary_route_cessation_analysis": (
                    "descriptive_ordered_pair_week_outcome_not_permanent_disappearance"
                ),
                "candidate_set": "stable_or_native_candidates_from_first_observed_week",
                "zero_definition": "post_first_use_nonuse_while_ordered_pair_active",
                "weekly_cadence": (
                    "calendar-week aggregation over observed release dates; "
                    "pair_observed_days retains sampled-day support"
                ),
                "opportunity_set_status": "unobserved_and_not_imputed",
            }
        ]
    )


def run(
    *,
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    risk_path: Path = RISK_PANEL,
    result_path: Path = RESULTS,
    support_path: Path = SUPPORT,
    root: Path = REPO_ROOT,
    environment=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    context = model_artifact_context(root=root, environment=environment)
    with current_artifacts(
        [context.d3_certificate_path],
        consumer="vehicle-role D3 certificate",
    ) as leased_certificate:
        assert_model_artifact_certificate_identity(context, leased_certificate[0])
        record, receipt = _d3_endpoint_release_record(
            context, pointer_path, root=root
        )
        with current_endpoint_candidate_composition_release(
            pointer_path,
            expected_semantic_receipt=receipt,
        ) as release:
            _assert_endpoint_release_matches_d3(record, release, root=root)
            source = build_vehicle_role_risk_panel_from_release(release.artifacts)
            candidate_panel = prepare_candidate_panel(source)
            risk = build_transition_risk(source)
            rows = [
                fit_ppml_utilisation(candidate_panel),
                fit_discrete_logit(risk, "substitution_exit"),
                fit_stratified_cox_sensitivity(risk, "substitution_exit"),
            ]
            results = attach_spec_ids(
                pd.DataFrame(rows),
                prefix="vehicle_role_methodology",
                columns=("method", "transition"),
            )
            support = summarize_transition_support(source, candidate_panel, risk)
            write_model_panel(
                risk,
                risk_path,
                role="support",
                context=context,
                code_sources=CODE_SOURCES,
                inputs=list(release.bundle.lineage_paths),
                notes=(
                    "post-first-use candidate weekly risk set; terminal and gap rows "
                    "retained for right censoring; no initial-formation inference"
                ),
            )
            with current_artifacts(
                [risk_path], consumer="vehicle-role fitted-output writers"
            ) as leased_risk:
                shared_inputs = [*release.bundle.lineage_paths, leased_risk[0]]
                write_model_exhibit(
                    results,
                    result_path,
                    role="diagnostic",
                    context=context,
                    code_sources=CODE_SOURCES,
                    inputs=shared_inputs,
                    notes=(
                        "post-first-use realised utilisation and candidate "
                        "substitution-exit models; no initial formation or feasible "
                        "opportunity set"
                    ),
                )
                write_model_exhibit(
                    support,
                    support_path,
                    role="support",
                    context=context,
                    code_sources=CODE_SOURCES,
                    inputs=shared_inputs,
                    notes=(
                        "post-first-use risk-set construction, observed-date weekly "
                        "cadence, event support, and right censoring"
                    ),
                )
            return results, support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-pointer",
        type=Path,
        default=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    )
    args = parser.parse_args()
    results, support = run(pointer_path=args.release_pointer)
    print(support.to_string(index=False))
    print(results.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the paired dominance-cost exploratory sub-ledger; no paper tables or prose."""

from __future__ import annotations

import argparse
import json
import math
import numbers
import os
from pathlib import Path
from collections.abc import Mapping

import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from scipy import stats

from ddvc.analysis.dominance_cost_e0 import (
    CAPABLE_OF_E0_CLOSURE,
    CALENDAR_YEARS,
    CONTROL_BLOCK_COLUMNS,
    CONTROL_REQUIRED_COLUMNS,
    EXPLORATORY_STATUS,
    FIT_LEDGER,
    OUTCOME_REQUIRED_SUPPORT_STAGE,
    PAIR_REQUIRED_COLUMNS,
    PROVISIONAL_STATUS,
    PROVISIONAL_SUBSETS,
    UNAVAILABLE_COVERAGE_GAPS,
    SUBLEDGER_ID,
    fit_dominance_cost_e0,
    fit_unadjusted_parquet,
    specification_semantics,
)
from ddvc.analysis.regression import holm_adjusted_pvalues
from ddvc.analysis.dominance_cost_release import (
    DOMINANCE_COST_RELEASE,
    resolve_dominance_cost_release,
)
from ddvc.artifact_release import ArtifactRelease, publish_artifact_release
from ddvc.paths import REPO_ROOT
from ddvc.provenance import require_current_artifacts


CONTROL_PANEL = REPO_ROOT / "data" / "processed" / "liquidity_capital_flow_candidate_day.parquet"
EXPLORATORY_OUTPUT_POINTER = REPO_ROOT / "output" / "exploratory" / "dominance_cost_native_comparator_release" / "current.json"
PROVISIONAL_OUTPUT_POINTER = REPO_ROOT / "output" / "provisional" / "dominance_cost_native_comparator_release" / "current.json"
OUTPUT_FILENAMES = {
    "results": "dominance_cost_native_comparator_results.jsonl",
    "support": "dominance_cost_native_comparator_support.jsonl",
    "metadata": "dominance_cost_native_comparator_metadata.json",
}
OUTPUT_SCHEMA_VERSION = 1
MIN_FULL_CONTROL_MEMORY_BYTES = 48 * 1024**3
SERIALIZED_ARITHMETIC_RTOL = 5e-12
SERIALIZED_ARITHMETIC_ATOL = 5e-12
RESULT_SCHEMA = {
    "auxiliary_scope", "block_contribution_contrast_inference", "block_contribution_covariance", "block_contribution_covariance_labels", "block_contributions_to_raw_mean_gap", "capable_of_e0_closure", "cluster_counts", "clustering", "coefficients", "control_blocks", "control_contributions_to_raw_mean_gap", "controls", "controls_mean_centered", "decomposition_identity_error", "decomposition_reconstructed_mean", "decomposition_status", "dropped_collinear_design_columns", "estimand", "estimates_average_weth_edge", "exact_sample_unconditional_mean", "exact_sample_unconditional_median", "exact_sample_unconditional_standard_deviation", "fixed_effect_support", "fixed_effects", "holm_p_values_within_fit_exploratory_only", "inference_owner", "joint_slope_tests", "n_dates", "n_observations", "n_ordered_endpoint_pairs", "outcome", "p_values", "raw_control_means", "raw_mean_inference", "raw_mean_owner", "regression_adjusted_mean_at_sample_means_inference", "regressors", "sample", "sample_sha256", "spec_id", "standard_errors", "status", "subledger_id", "support_stage", "t_statistics", "zero_difference_reference_category_profile_definition", "zero_difference_reference_category_profile_estimate", "zero_difference_reference_category_profile_inference",
}
SUPPORT_REQUIRED_FIELDS = {
    "sample",
    "observations",
    "share_of_primary",
    "dates",
    "ordered_endpoint_pairs",
    "sample_sha256",
}
CODE_SOURCES = [
    "scripts/run_dominance_cost_e0.py",
    "src/ddvc/analysis/dominance_cost_e0.py",
    "src/ddvc/analysis/dominance_cost_contract.py",
    "src/ddvc/analysis/dominance_cost_release.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/artifact_release.py",
    "src/ddvc/liquidity_predictability.py",
    "src/ddvc/route_cost.py",
    "src/ddvc/transaction_targets.py",
]


def _physical_memory_bytes() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return 0


def run(
    *,
    control_path: Path = CONTROL_PANEL,
    pointer_path: Path = DOMINANCE_COST_RELEASE,
    pair_panel_path: Path | None = None,
    provisional_subset: str | None = None,
    high_memory_full_control: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    """Resolve certified inputs by default and quarantine only named provisional subsets."""

    provisional = provisional_subset is not None
    if provisional and provisional_subset not in PROVISIONAL_SUBSETS:
        raise ValueError(f"unknown provisional subset: {provisional_subset}")
    if pair_panel_path is not None and not provisional:
        raise ValueError("an injected pair panel is permitted only for a named provisional subset")
    if pair_panel_path is None:
        release = resolve_dominance_cost_release(pointer_path)
        pair_panel_path = release.artifacts["panel"]
        inputs = list(release.lineage_paths)
    else:
        pair_panel_path = pair_panel_path.resolve()
        if not pair_panel_path.is_file():
            raise FileNotFoundError(f"provisional dominance-cost pair panel is absent: {pair_panel_path}")
        inputs = [pair_panel_path]

    spec_ids = PROVISIONAL_SUBSETS[provisional_subset] if provisional else tuple(spec.spec_id for spec in FIT_LEDGER)
    if spec_ids == ("dc00_full_primary",):
        results, support = fit_unadjusted_parquet(pair_panel_path, status=PROVISIONAL_STATUS if provisional else EXPLORATORY_STATUS)
        return results, support, inputs
    needs_controls = any(spec_id != "dc00_full_primary" for spec_id in spec_ids)
    controls = None
    if needs_controls:
        if not control_path.is_file():
            kind = "provisional" if provisional else "certified"
            raise FileNotFoundError(f"{kind}-input dominance-cost exploratory sub-ledger requires the candidate-day control panel: {control_path}")
        if not high_memory_full_control or _physical_memory_bytes() < MIN_FULL_CONTROL_MEMORY_BYTES:
            raise RuntimeError("full-control dominance-cost execution requires explicit assignment to a worker with at least 48 GiB physical memory")
        if not provisional:
            require_current_artifacts([control_path], consumer="immutable-input dominance-cost exploratory sub-ledger")
        controls = pd.read_parquet(control_path, columns=sorted(CONTROL_REQUIRED_COLUMNS))
        inputs.append(control_path)
    status = PROVISIONAL_STATUS if provisional else EXPLORATORY_STATUS
    pair_columns = sorted({column for column in PAIR_REQUIRED_COLUMNS if column in pq.ParquetFile(pair_panel_path).schema_arrow.names})
    results, support = fit_dominance_cost_e0(
        pd.read_parquet(pair_panel_path, columns=pair_columns),
        controls,
        specification_ids=spec_ids,
        status=status,
    )
    return results, support, inputs


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is absent or invalid: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def build_subledger_metadata(
    results: pd.DataFrame,
    *,
    provisional: bool,
) -> dict[str, object]:
    """Describe a standalone diagnostic that cannot satisfy plan-owned attacks."""

    spec_ids = results["spec_id"].tolist()
    if len(spec_ids) != len(set(spec_ids)) or not set(spec_ids).issubset({spec.spec_id for spec in FIT_LEDGER}):
        raise ValueError("standalone dominance-cost metadata received invalid specification IDs")
    calendar_executed = "dc15_calendar_year_heterogeneity" in set(spec_ids)
    if calendar_executed and not {"dc00_full_primary", "dc16_calendar_year_stable_design_sensitivity"}.issubset(spec_ids):
        raise ValueError("calendar-year heterogeneity lacks its intercept-only or stable-design support bridge")
    metadata: dict[str, object] = {
        "schema_version": 1,
        "kind": "dominance_cost_native_comparator_exploratory_subledger",
        "subledger_id": SUBLEDGER_ID,
        "status": PROVISIONAL_STATUS if provisional else EXPLORATORY_STATUS,
        "capable_of_e0_closure": CAPABLE_OF_E0_CLOSURE,
        "integration_mode": "standalone_nonclosing_diagnostic",
        "closure_limitation": "This seventeen-fit native-versus-comparator indirect-cost sub-ledger cannot close E0. Executable attack bindings, fixed artifact paths, exact spec IDs, released-schema validation, artifact hashes, triage, and closure remain owned by scripts/run_exploration.py and ddvc.exploration.",
        "fit_count": len(results),
        "spec_ids": spec_ids,
        "claimed_attack_ids": [],
        "unavailable_coverage_gaps": {name: list(fields) for name, fields in UNAVAILABLE_COVERAGE_GAPS.items()},
        "executed_diagnostics": {
            "calendar_year_heterogeneity": {"spec_ids": ["dc00_full_primary", "dc15_calendar_year_heterogeneity", "dc16_calendar_year_stable_design_sensitivity"], "interpretation_boundary": "raw quote-attempt-composition profile plus stable quote-design sensitivity; neither is market maturation or aggregator attribution"}
        } if calendar_executed else {},
    }
    return metadata


def _validate_result_contract(results: pd.DataFrame, support: pd.DataFrame, *, expected_status: str) -> None:
    if set(results.columns) != RESULT_SCHEMA or set(support.columns) != SUPPORT_REQUIRED_FIELDS:
        raise ValueError("dominance-cost standalone release violates its exact schema")

    def finite_number(value: object, *, nonnegative: bool = False) -> bool:
        return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(float(value)) and (not nonnegative or float(value) >= 0)

    def integer(value: object, *, positive: bool = False) -> bool:
        return finite_number(value, nonnegative=True) and float(value).is_integer() and (not positive or int(value) > 0)

    def sha256(value: object) -> bool:
        text = str(value)
        return len(text) == 64 and all(character in "0123456789abcdef" for character in text)

    def json_value(value: object, expected_type: type, *, label: str) -> object:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"dominance-cost release contains invalid JSON: {label}") from error
        if not isinstance(parsed, expected_type):
            raise ValueError(f"dominance-cost release contains wrong JSON type: {label}")
        return parsed

    def finite_mapping(value: object, *, label: str) -> dict[str, float]:
        parsed = json_value(value, dict, label=label)
        if any(not isinstance(key, str) or not finite_number(number) for key, number in parsed.items()):
            raise ValueError(f"dominance-cost release contains nonfinite mapping values: {label}")
        return parsed

    def close(left: object, right: object) -> bool:
        return finite_number(left) and finite_number(right) and math.isclose(float(left), float(right), rel_tol=SERIALIZED_ARITHMETIC_RTOL, abs_tol=SERIALIZED_ARITHMETIC_ATOL)

    def contrast(value: object, *, label: str) -> dict[str, float | int] | None:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"dominance-cost release contains invalid contrast JSON: {label}") from error
        if parsed is None:
            return None
        required = {"estimate", "standard_error", "t_statistic", "p_value", "confidence_interval_lower", "confidence_interval_upper", "degrees_freedom"}
        if not isinstance(parsed, dict) or set(parsed) != required or any(not finite_number(parsed[field]) for field in required - {"degrees_freedom"}) or not integer(parsed["degrees_freedom"], positive=True) or float(parsed["standard_error"]) <= 0 or not 0 <= float(parsed["p_value"]) <= 1:
            raise ValueError(f"dominance-cost release contains invalid contrast values: {label}")
        expected_t = float(parsed["estimate"]) / float(parsed["standard_error"])
        expected_p = float(2 * stats.t.sf(abs(expected_t), int(parsed["degrees_freedom"])))
        critical = float(stats.t.ppf(0.975, int(parsed["degrees_freedom"])))
        if not close(parsed["t_statistic"], expected_t) or not close(parsed["p_value"], expected_p) or not close(parsed["confidence_interval_lower"], float(parsed["estimate"]) - critical * float(parsed["standard_error"])) or not close(parsed["confidence_interval_upper"], float(parsed["estimate"]) + critical * float(parsed["standard_error"])):
            raise ValueError(f"dominance-cost release contains arithmetically inconsistent contrast values: {label}")
        return parsed

    def is_missing(value: object) -> bool:
        return value is None or (isinstance(value, numbers.Real) and bool(pd.isna(value)))

    def string_list(value: object, *, label: str) -> list[str]:
        parsed = json_value(value, list, label=label)
        if any(not isinstance(item, str) for item in parsed) or len(parsed) != len(set(parsed)):
            raise ValueError(f"dominance-cost release contains invalid string-list values: {label}")
        return parsed

    def semantic_equal(observed: object, expected: object) -> bool:
        return is_missing(observed) if expected is None else observed == expected

    def joint_test_mapping(value: object, *, label: str) -> dict[str, dict[str, object]]:
        parsed = json_value(value, dict, label=label)
        required = {"status", "f_statistic", "numerator_df", "denominator_df", "p_value", "reason"}
        for name, test in parsed.items():
            if not isinstance(name, str) or not isinstance(test, dict) or set(test) != required or test["status"] not in {"estimated", "unavailable"} or not integer(test["numerator_df"], positive=True) or not integer(test["denominator_df"], positive=True):
                raise ValueError(f"dominance-cost release contains invalid joint-test structure: {label}")
            if test["status"] == "estimated":
                if not finite_number(test["f_statistic"], nonnegative=True) or not finite_number(test["p_value"], nonnegative=True) or float(test["p_value"]) > 1 or test["reason"] is not None:
                    raise ValueError(f"dominance-cost release contains invalid estimated joint test: {label}")
            elif not is_missing(test["f_statistic"]) or not is_missing(test["p_value"]) or not isinstance(test["reason"], str) or not test["reason"]:
                raise ValueError(f"dominance-cost release contains invalid unavailable joint test: {label}")
        return parsed

    specifications = {spec.spec_id: spec for spec in FIT_LEDGER}
    spec_ids = results["spec_id"].tolist()
    if not spec_ids or len(spec_ids) != len(set(spec_ids)) or not set(spec_ids).issubset(specifications):
        raise ValueError("dominance-cost standalone release violates its exact specification perimeter")
    for row in results.to_dict(orient="records"):
        spec = specifications[row["spec_id"]]
        regressors = string_list(row["regressors"], label=f"{spec.spec_id}/regressors")
        statistic_mappings = {field: finite_mapping(row[field], label=f"{spec.spec_id}/{field}") for field in ("coefficients", "standard_errors", "t_statistics", "p_values", "holm_p_values_within_fit_exploratory_only")}
        cluster_counts = json_value(row["cluster_counts"], list, label=f"{spec.spec_id}/cluster_counts")
        fixed_effect_support = json_value(row["fixed_effect_support"], dict, label=f"{spec.spec_id}/fixed_effect_support")
        controls = string_list(row["controls"], label=f"{spec.spec_id}/controls")
        fixed_effects = string_list(row["fixed_effects"], label=f"{spec.spec_id}/fixed_effects")
        control_blocks = string_list(row["control_blocks"], label=f"{spec.spec_id}/control_blocks")
        dropped = string_list(row["dropped_collinear_design_columns"], label=f"{spec.spec_id}/dropped_collinear_design_columns")
        raw_control_means = finite_mapping(row["raw_control_means"], label=f"{spec.spec_id}/raw_control_means")
        control_contributions = finite_mapping(row["control_contributions_to_raw_mean_gap"], label=f"{spec.spec_id}/control_contributions_to_raw_mean_gap")
        block_contributions = finite_mapping(row["block_contributions_to_raw_mean_gap"], label=f"{spec.spec_id}/block_contributions_to_raw_mean_gap")
        block_inference = json_value(row["block_contribution_contrast_inference"], dict, label=f"{spec.spec_id}/block_contribution_contrast_inference")
        block_labels = string_list(row["block_contribution_covariance_labels"], label=f"{spec.spec_id}/block_contribution_covariance_labels")
        block_covariance = json_value(row["block_contribution_covariance"], list, label=f"{spec.spec_id}/block_contribution_covariance")
        joint_tests = joint_test_mapping(row["joint_slope_tests"], label=f"{spec.spec_id}/joint_slope_tests")
        expected_blocks = [block for block, columns in CONTROL_BLOCK_COLUMNS.items() if any(column in spec.controls for column in columns)]
        expected_joint_tests = (["all_declared_slopes"] if spec.controls else []) + expected_blocks
        expected_regressors = (["constant"] if not spec.fixed_effects else []) + list(spec.controls)
        parsed_block_inference = {}
        for block, value in block_inference.items():
            if not isinstance(block, str):
                raise ValueError(f"dominance-cost release contains an invalid block-inference key: {spec.spec_id}")
            parsed_block_inference[block] = contrast(json.dumps(value), label=f"{spec.spec_id}/block_contribution_contrast_inference/{block}")
        if len(block_covariance) != len(block_labels) or any(not isinstance(covariance_row, list) or len(covariance_row) != len(block_labels) or any(not finite_number(value) for value in covariance_row) for covariance_row in block_covariance):
            raise ValueError(f"dominance-cost release contains an invalid block covariance: {spec.spec_id}")
        if block_covariance and not np.allclose(np.asarray(block_covariance, dtype=float), np.asarray(block_covariance, dtype=float).T, rtol=0, atol=1e-12):
            raise ValueError(f"dominance-cost release contains an asymmetric block covariance: {spec.spec_id}")
        contrasts = {
            field: contrast(row[field], label=f"{spec.spec_id}/{field}")
            for field in ("raw_mean_inference", "regression_adjusted_mean_at_sample_means_inference", "zero_difference_reference_category_profile_inference")
        }
        n_observations = row["n_observations"]
        n_dates = row["n_dates"]
        n_pairs = row["n_ordered_endpoint_pairs"]
        semantics = specification_semantics(spec)
        if (
            row["status"] != expected_status
            or row["subledger_id"] != SUBLEDGER_ID
            or bool(row["capable_of_e0_closure"])
            or row["outcome"] != spec.outcome
            or row["support_stage"] != OUTCOME_REQUIRED_SUPPORT_STAGE[spec.outcome]
            or row["sample"] != spec.sample
            or controls != list(spec.controls)
            or fixed_effects != list(spec.fixed_effects)
            or control_blocks != list(spec.control_blocks)
            or not isinstance(row["controls_mean_centered"], (bool, np.bool_))
            or bool(row["controls_mean_centered"]) != semantics["controls_mean_centered"]
            or row["clustering"] != "two_way_date_ordered_endpoint_pair_cr1"
            or any(not semantic_equal(row[field], semantics[field]) for field in ("inference_owner", "estimand", "auxiliary_scope", "decomposition_status", "raw_mean_owner", "zero_difference_reference_category_profile_definition"))
            or not integer(n_observations, positive=True)
            or not integer(n_dates, positive=True)
            or not integer(n_pairs, positive=True)
            or int(n_dates) > int(n_observations)
            or int(n_pairs) > int(n_observations)
            or any(not finite_number(row[field], nonnegative=field == "exact_sample_unconditional_standard_deviation") for field in ("exact_sample_unconditional_mean", "exact_sample_unconditional_median", "exact_sample_unconditional_standard_deviation"))
            or not sha256(row["sample_sha256"])
            or regressors != expected_regressors
            or any(set(mapping) != set(regressors) for mapping in statistic_mappings.values())
            or any(value <= 0 for value in statistic_mappings["standard_errors"].values())
            or any(not 0 <= value <= 1 for field in ("p_values", "holm_p_values_within_fit_exploratory_only") for value in statistic_mappings[field].values())
            or len(cluster_counts) != 2
            or any(not integer(value, positive=True) for value in cluster_counts)
            or min(cluster_counts) < 20
            or cluster_counts != [int(n_dates), int(n_pairs)]
            or not isinstance(row["estimates_average_weth_edge"], (bool, np.bool_))
            or bool(row["estimates_average_weth_edge"]) != semantics["estimates_average_weth_edge"]
            or set(raw_control_means) != set(spec.controls)
            or set(control_contributions) != (set() if spec.fixed_effects else set(spec.controls))
            or set(block_contributions) != (set() if spec.fixed_effects else set(expected_blocks))
            or set(block_inference) != (set() if spec.fixed_effects else set(expected_blocks))
            or block_labels != ([] if spec.fixed_effects else expected_blocks)
            or set(joint_tests) != set(expected_joint_tests)
            or dropped != []
            or (spec.fixed_effects and (not is_missing(row["zero_difference_reference_category_profile_estimate"]) or not is_missing(row["decomposition_reconstructed_mean"]) or not is_missing(row["decomposition_identity_error"])))
            or (not spec.fixed_effects and any(not finite_number(row[field]) for field in ("zero_difference_reference_category_profile_estimate", "decomposition_reconstructed_mean", "decomposition_identity_error")))
            or (not spec.fixed_effects and not math.isclose(float(row["decomposition_reconstructed_mean"]), float(row["exact_sample_unconditional_mean"]), rel_tol=0, abs_tol=1e-9 * max(abs(float(row["exact_sample_unconditional_mean"])), 1.0)))
            or (not spec.fixed_effects and not math.isclose(float(row["decomposition_identity_error"]), 0.0, rel_tol=0, abs_tol=1e-9 * max(abs(float(row["exact_sample_unconditional_mean"])), 1.0)))
            or ("quote_design_cell" in spec.fixed_effects and (not fixed_effect_support or fixed_effect_support.get("all_declared_regressors_identified") is not True))
            or ("quote_design_cell" not in spec.fixed_effects and fixed_effect_support != {})
            or (spec.spec_id == "dc16_calendar_year_stable_design_sensitivity" and (not integer(fixed_effect_support.get("cells_spanning_multiple_calendar_years"), positive=True) or not integer(fixed_effect_support.get("observations_in_multiple_calendar_year_cells"), positive=True) or not finite_number(fixed_effect_support.get("share_in_multiple_calendar_year_cells")) or not 0 < float(fixed_effect_support["share_in_multiple_calendar_year_cells"]) <= 1))
        ):
            raise ValueError(f"dominance-cost result violates its specification contract: {row['spec_id']}")
        degrees_freedom = min(int(value) for value in cluster_counts) - 1
        coefficient_values = np.asarray([statistic_mappings["coefficients"][name] for name in regressors], dtype=float)
        standard_error_values = np.asarray([statistic_mappings["standard_errors"][name] for name in regressors], dtype=float)
        expected_t_values = coefficient_values / standard_error_values
        expected_p_values = 2 * stats.t.sf(np.abs(expected_t_values), degrees_freedom)
        expected_holm_values = holm_adjusted_pvalues(expected_p_values)
        if any(not close(statistic_mappings["t_statistics"][name], expected_t_values[position]) or not close(statistic_mappings["p_values"][name], expected_p_values[position]) or not close(statistic_mappings["holm_p_values_within_fit_exploratory_only"][name], expected_holm_values[position]) for position, name in enumerate(regressors)):
            raise ValueError(f"dominance-cost coefficient inference is arithmetically inconsistent: {spec.spec_id}")
        for record in contrasts.values():
            if record is not None and int(record["degrees_freedom"]) != degrees_freedom:
                raise ValueError(f"dominance-cost contrast degrees of freedom disagree with clustering: {spec.spec_id}")
        for test in joint_tests.values():
            if int(test["denominator_df"]) != degrees_freedom:
                raise ValueError(f"dominance-cost joint-test degrees of freedom disagree with clustering: {spec.spec_id}")
            if test["status"] == "estimated" and not close(test["p_value"], stats.f.sf(float(test["f_statistic"]), int(test["numerator_df"]), degrees_freedom)):
                raise ValueError(f"dominance-cost joint-test p-value is arithmetically inconsistent: {spec.spec_id}")
        expected_joint_numerator_df = {"all_declared_slopes": len(spec.controls), **{block: sum(column in spec.controls for column in columns) for block, columns in CONTROL_BLOCK_COLUMNS.items() if block in expected_blocks}}
        if any(int(joint_tests[name]["numerator_df"]) != expected_joint_numerator_df[name] for name in expected_joint_tests):
            raise ValueError(f"dominance-cost joint-test numerator degrees of freedom disagree with declared controls: {spec.spec_id}")
        if not spec.fixed_effects:
            coefficient_by_name = statistic_mappings["coefficients"]
            contributions_expected = {control: coefficient_by_name[control] * raw_control_means[control] for control in spec.controls}
            if any(not close(control_contributions[control], expected) for control, expected in contributions_expected.items()):
                raise ValueError(f"dominance-cost control decomposition is arithmetically inconsistent: {spec.spec_id}")
            for block, columns in CONTROL_BLOCK_COLUMNS.items():
                included = [column for column in columns if column in spec.controls]
                if included and not close(block_contributions[block], sum(contributions_expected[column] for column in included)):
                    raise ValueError(f"dominance-cost block decomposition is arithmetically inconsistent: {spec.spec_id}")
            reference_estimate = coefficient_by_name["constant"] - sum(contributions_expected.values())
            if not close(row["zero_difference_reference_category_profile_estimate"], reference_estimate) or not close(row["decomposition_reconstructed_mean"], coefficient_by_name["constant"]) or not close(row["exact_sample_unconditional_mean"], coefficient_by_name["constant"]):
                raise ValueError(f"dominance-cost mean decomposition disagrees with coefficients: {spec.spec_id}")
            expected_contrast_estimates = {
                "regression_adjusted_mean_at_sample_means_inference": coefficient_by_name["constant"],
                "zero_difference_reference_category_profile_inference": reference_estimate,
            }
            if not spec.controls:
                expected_contrast_estimates["raw_mean_inference"] = coefficient_by_name["constant"]
            if any(contrasts[field] is None or not close(contrasts[field]["estimate"], estimate) for field, estimate in expected_contrast_estimates.items()):
                raise ValueError(f"dominance-cost contrast estimate disagrees with coefficients: {spec.spec_id}")
            for position, block in enumerate(block_labels):
                block_record = parsed_block_inference[block]
                if block_record is None or not close(block_record["estimate"], block_contributions[block]) or not close(block_covariance[position][position], float(block_record["standard_error"]) ** 2):
                    raise ValueError(f"dominance-cost block inference disagrees with decomposition: {spec.spec_id}")
        expected_raw_mean = not spec.controls and not spec.fixed_effects
        if (contrasts["raw_mean_inference"] is not None) != expected_raw_mean or (contrasts["regression_adjusted_mean_at_sample_means_inference"] is not None) != (not spec.fixed_effects) or (contrasts["zero_difference_reference_category_profile_inference"] is not None) != (not spec.fixed_effects):
            raise ValueError(f"dominance-cost result contains an invalid inference ownership pattern: {spec.spec_id}")
        if "quote_design_cell" in spec.fixed_effects:
            expected_support_keys = {"support_kind", "quote_design_cells", "cells_observed_on_multiple_dates", "observations_in_multiple_date_cells", "share_in_multiple_date_cells", "declared_regressors", "within_fixed_effect_regressor_rank", "all_declared_regressors_identified", "identification"}
            if spec.spec_id == "dc16_calendar_year_stable_design_sensitivity":
                expected_support_keys |= {"cells_spanning_multiple_calendar_years", "observations_in_multiple_calendar_year_cells", "share_in_multiple_calendar_year_cells", "adjacent_calendar_year_bridge_cell_counts"}
            if set(fixed_effect_support) != expected_support_keys or fixed_effect_support["support_kind"] != ("within_date_quote_design" if spec.spec_id == "dc02_risk_absorbed_slope_diagnostic" else "within_calendar_year_quote_design") or fixed_effect_support["identification"] != "within stable quote-design cells over time" or fixed_effect_support["declared_regressors"] != len(spec.controls) or fixed_effect_support["within_fixed_effect_regressor_rank"] != len(spec.controls) or any(not integer(fixed_effect_support[field], positive=True) for field in ("quote_design_cells", "cells_observed_on_multiple_dates", "observations_in_multiple_date_cells")) or int(fixed_effect_support["quote_design_cells"]) > int(n_observations) or int(fixed_effect_support["cells_observed_on_multiple_dates"]) > int(fixed_effect_support["quote_design_cells"]) or int(fixed_effect_support["observations_in_multiple_date_cells"]) > int(n_observations) or not finite_number(fixed_effect_support["share_in_multiple_date_cells"]) or not close(fixed_effect_support["share_in_multiple_date_cells"], int(fixed_effect_support["observations_in_multiple_date_cells"]) / int(n_observations)):
                raise ValueError(f"dominance-cost result contains invalid fixed-effect support: {spec.spec_id}")
            if spec.spec_id == "dc16_calendar_year_stable_design_sensitivity":
                bridge_counts = fixed_effect_support["adjacent_calendar_year_bridge_cell_counts"]
                expected_bridges = {f"{left}_{right}" for left, right in zip(CALENDAR_YEARS, CALENDAR_YEARS[1:])}
                if not isinstance(bridge_counts, dict) or set(bridge_counts) != expected_bridges or any(not integer(value) or int(value) > int(fixed_effect_support["cells_spanning_multiple_calendar_years"]) for value in bridge_counts.values()) or int(fixed_effect_support["cells_spanning_multiple_calendar_years"]) > int(fixed_effect_support["quote_design_cells"]) or int(fixed_effect_support["observations_in_multiple_calendar_year_cells"]) > int(fixed_effect_support["observations_in_multiple_date_cells"]) or not close(fixed_effect_support["share_in_multiple_calendar_year_cells"], int(fixed_effect_support["observations_in_multiple_calendar_year_cells"]) / int(n_observations)):
                    raise ValueError(f"dominance-cost result contains invalid calendar bridge support: {spec.spec_id}")
    if len(support) != 7 or support["sample"].duplicated().any() or set(support["sample"]) != {"primary_full", "calendar_complete", "risk_complete", "use_complete", "mechanism_complete", "heterogeneity_complete", "direct_complete"}:
        raise ValueError("dominance-cost support release violates its exact sample perimeter")
    support_by_sample = support.set_index("sample")
    primary_observations = support_by_sample.loc["primary_full", "observations"]
    if not integer(primary_observations, positive=True):
        raise ValueError("dominance-cost primary support count is invalid")
    for sample, row in support_by_sample.iterrows():
        observations = row["observations"]
        dates = row["dates"]
        pairs = row["ordered_endpoint_pairs"]
        share = row["share_of_primary"]
        if (
            not integer(observations)
            or not integer(dates)
            or not integer(pairs)
            or not finite_number(share, nonnegative=True)
            or float(share) > 1
            or int(dates) > int(observations)
            or int(pairs) > int(observations)
            or (int(observations) == 0 and (int(dates) != 0 or int(pairs) != 0))
            or not math.isclose(float(share), int(observations) / int(primary_observations), rel_tol=0, abs_tol=1e-12)
            or not sha256(row["sample_sha256"])
        ):
            raise ValueError(f"dominance-cost support row violates its domain: {sample}")
    primary = support_by_sample.loc["primary_full"]
    calendar = support_by_sample.loc["calendar_complete"]
    if any(primary[field] != calendar[field] for field in ("observations", "dates", "ordered_endpoint_pairs", "sample_sha256")):
        raise ValueError("dominance-cost calendar support does not match primary support")
    for row in results.to_dict(orient="records"):
        evidence = support_by_sample.loc[row["sample"]]
        if any(row[field] != evidence[support_field] for field, support_field in (("n_observations", "observations"), ("n_dates", "dates"), ("n_ordered_endpoint_pairs", "ordered_endpoint_pairs"), ("sample_sha256", "sample_sha256"))):
            raise ValueError(f"dominance-cost result disagrees with support: {row['spec_id']}")


def publish_subledger_release(
    results: pd.DataFrame,
    support: pd.DataFrame,
    *,
    inputs: list[Path],
    provisional: bool,
    pointer_path: Path | None = None,
) -> ArtifactRelease:
    """Publish results, support, and authority metadata under one atomic marker."""

    default_pointer = PROVISIONAL_OUTPUT_POINTER if provisional else EXPLORATORY_OUTPUT_POINTER
    pointer = (pointer_path or default_pointer).resolve()
    forbidden = EXPLORATORY_OUTPUT_POINTER if provisional else PROVISIONAL_OUTPUT_POINTER
    if pointer == forbidden.resolve():
        raise ValueError("provisional and non-provisional dominance-cost outputs cannot share a release pointer")
    expected_status = PROVISIONAL_STATUS if provisional else EXPLORATORY_STATUS
    _validate_result_contract(results, support, expected_status=expected_status)
    if provisional != ("provisional" in pointer.parts):
        raise ValueError("dominance-cost output pointer does not match its provisional namespace")
    metadata = build_subledger_metadata(results, provisional=provisional)

    def write_jsonl(frame: pd.DataFrame):
        return lambda path: frame.to_json(path, orient="records", lines=True, double_precision=15)

    def write_metadata(path: Path) -> None:
        path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def validate_staged(paths: Mapping[str, Path]) -> None:
        reopened_results = pd.read_json(paths["results"], lines=True)
        reopened_support = pd.read_json(paths["support"], lines=True)
        reopened_metadata = _read_json(paths["metadata"], label="staged dominance-cost metadata")
        _validate_result_contract(reopened_results, reopened_support, expected_status=expected_status)
        if reopened_results["spec_id"].tolist() != results["spec_id"].tolist():
            raise ValueError("staged dominance-cost results changed specification identity")
        if "spec_id" in reopened_support or len(reopened_support) != len(support):
            raise ValueError("staged dominance-cost support changed its zero-fit perimeter")
        if reopened_metadata != metadata or reopened_metadata.get("capable_of_e0_closure") is not False:
            raise ValueError("staged dominance-cost metadata changed its closure boundary")

    return publish_artifact_release(
        pointer_path=pointer,
        kind="dominance_cost_native_comparator_provisional" if provisional else "dominance_cost_native_comparator_exploratory",
        schema_version=OUTPUT_SCHEMA_VERSION,
        filenames=OUTPUT_FILENAMES,
        writers={
            "results": write_jsonl(results),
            "support": write_jsonl(support),
            "metadata": write_metadata,
        },
        row_counts={"results": len(results), "support": len(support), "metadata": 1},
        code_sources=CODE_SOURCES,
        inputs=list(dict.fromkeys(inputs)),
        notes="native-versus-comparator indirect-cost exploratory sub-ledger; incapable of E0 closure",
        validate_staged=validate_staged,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls", type=Path, default=CONTROL_PANEL)
    parser.add_argument("--release-pointer", type=Path, default=DOMINANCE_COST_RELEASE)
    parser.add_argument("--pair-panel", type=Path)
    parser.add_argument("--provisional-subset", choices=tuple(PROVISIONAL_SUBSETS))
    parser.add_argument("--output-release-pointer", type=Path)
    parser.add_argument("--high-memory-full-control", action="store_true")
    args = parser.parse_args()
    results, support, inputs = run(
        control_path=args.controls,
        pointer_path=args.release_pointer,
        pair_panel_path=args.pair_panel,
        provisional_subset=args.provisional_subset,
        high_memory_full_control=args.high_memory_full_control,
    )
    release = publish_subledger_release(
        results,
        support,
        inputs=inputs,
        provisional=args.provisional_subset is not None,
        pointer_path=args.output_release_pointer,
    )
    print(
        f"fitted specifications={len(results)}; support samples={len(support)}; "
        f"status={results['status'].iloc[0]}; generation={release.generation_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic provisional heterogeneity probe for paired dominance-cost output."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import gc
from itertools import combinations, product
import json
import math
from numbers import Integral, Real
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa

from ddvc.analysis.dominance_cost_contract import COMPARATOR_SYMBOLS, COMPARATOR_VEHICLES, SUPPORT_STAGES, validate_support_counts
from ddvc.analysis.dominance_cost_release import (
    DOMINANCE_COST_RELEASE_FILENAMES,
    DOMINANCE_COST_RELEASE_KIND,
    DOMINANCE_COST_RELEASE_SCHEMA_VERSION,
    resolve_dominance_cost_release,
)
from ddvc.analysis.regression import ClusteredOLSResult, joint_wald_f, ols_clustered
from ddvc.analysis.routing_technology import ROUTING_ERA_CUTOFFS, ROUTING_ERA_NAMES, routing_era_case_sql, routing_era_for_date
import ddvc.analysis.routing_technology as routing_technology_module
from ddvc.artifact_release import (
    canonical_json_sha256,
    file_sha256,
    generation_id,
    generation_paths,
    is_sha256,
)
from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.paths import REPO_ROOT
from ddvc.runtime import atomic_output, serialized_output_install


PROBE_SCHEMA_VERSION = 2
CANONICAL_FLOAT_SIGNIFICANT_DIGITS = 7
SERIALIZED_P_VALUE_FLOOR = 1e-12
OUTCOME = "weth_symmetric_output_edge_bps"
REFERENCE = {
    "trade_size_usd": 10_000.0,
    "reserve_hour_utc": 12,
    "architecture": "both_tick",
    "available_candidate_count": "3",
    "routing_era": "universal_router_era",
}
LEVELS = {
    "trade_size_usd": (10_000.0, 1_000.0, 100_000.0),
    "architecture": ("both_tick", "asymmetric", "both_non_tick"),
    "available_candidate_count": ("3", "2", "4_plus"),
    "routing_era": ("universal_router_era", *ROUTING_ERA_NAMES[:-1]),
}
HOUR_COLUMNS = ("hour_sin1", "hour_cos1", "hour_sin2", "hour_cos2")
COMPARATOR_MASKS = {symbol: 1 << index for index, symbol in enumerate(COMPARATOR_SYMBOLS)}
COMPARATOR_MODEL_NAMES = (
    "m0_raw",
    "m1_size_architecture_breadth",
    "m2_plus_routing_era",
    "m3_plus_hour_harmonics",
    "m3_equal_date",
    "m3_flexible_hour",
    "m3_date_cluster_only",
    "m3_endpoint_cluster_only",
)
TAIL_FRACTIONS = (0.005, 0.01)
ENDPOINT_DELETION_RULES = ("largest_endpoint_pair", "largest_one_percent_endpoint_pairs")
POOLED_MODEL_NAMES = ("year", "routing_era")
MATCHED_YEAR_START = 2024
MATCHED_YEAR_END = 2026
MATCHED_CELL_KEYS = (
    "comparator_symbol",
    "endpoint_pair",
    "trade_size_usd",
    "reserve_hour_utc",
    "architecture",
    "available_candidate_count",
)
COMMON_SUPPORT_MODEL_LADDER = tuple(
    (model, blocks, cluster_mode)
    for model, blocks in (
        ("m3_plus_hour_harmonics", ("trade_size_usd", "architecture", "available_candidate_count", "routing_era", "hour")),
        ("m2_plus_routing_era", ("trade_size_usd", "architecture", "available_candidate_count", "routing_era")),
        ("m1_size_architecture_breadth", ("trade_size_usd", "architecture", "available_candidate_count")),
        ("m0_raw", ()),
    )
    for cluster_mode in ("two_way", "date")
)
LEDGER_REQUIRED_FIELDS = {
    "sample_summary": {"sample"},
    "support_attrition_summary": {"support_attrition"},
    "matched_year_change_summary": {"matched_year_change"},
    "pooled_model": {"model", "status", "covariance", "estimate"},
    "comparator_summary": {"comparator", "support", "reference_support", "reference_raw_mean_bps"},
    "main_level_support": {"comparator", "field", "level", "n", "dates", "endpoint_pairs"},
    "comparator_model": {"comparator", "model", "status", "support", "covariance", "estimate"},
    "architecture_breadth_era_state": {"comparator_symbol", "architecture", "available_candidate_count", "routing_era", "status", "n", "dates", "endpoint_pairs", "reference_support"},
    "tail_deletion": {"comparator", "tail_fraction_each_side", "lower_bps", "upper_bps", "estimate"},
    "endpoint_deletion": {"comparator", "rule", "deleted_endpoint_pair_count", "deleted_endpoint_pair_ids", "deleted_set_sha256", "deleted_n", "estimate"},
    "leave_one_year_out": {"comparator", "deleted_year", "estimate"},
    "common_support_sensitivity": {"comparators", "support", "estimates", "support_mask", "selected_model", "selected_cluster_mode", "rejected_models"},
}
FIT_STATUSES = {"pass", "covariance_nonpd", "fit_nonfinite"}
SUPPORT_COLUMNS = ("date", "comparator", "comparator_symbol", "trade_size_usd", *SUPPORT_STAGES)
SUPPORT_REQUIRED_FIELDS = set(SUPPORT_COLUMNS)
CANONICAL_SUPPORT_DATES = tuple(f"{day[:4]}-{day[4:6]}-{day[6:]}" for day in calendar_days(RESEARCH_SAMPLE_START, RESEARCH_SAMPLE_END))
FIT_FIELDS = {"n", "dates", "endpoint_pairs", "cluster_counts", "coefficient_names", "coefficients", "standard_errors", "p_values", "covariance", "joint_tests", "status"}
COVARIANCE_FIELDS = {"finite", "positive_definite", "rank", "dimension", "minimum_eigenvalue"}
SUPPORT_FIELDS = {"n", "dates", "endpoint_pairs"}
REPORT_FIELDS = {
    "schema_version",
    "status",
    "input",
    "instrument_source_sha256",
    "formulas",
    "reference",
    "routing_era_cutoffs",
    "sample",
    "support_attrition",
    "matched_year_change",
    "pooled_models",
    "comparator_models",
    "common_support_sets",
    "state_admissibility_counts",
    "support_thresholds",
    "old_estimand_bridge",
    "headline_boundary",
    "ledger_manifest",
    "result_sha256",
}

MATCHED_CHANGE_COUNT_FIELDS = {
    "candidate_cells_start",
    "candidate_cells_end",
    "matched_cells",
    "candidate_rows_start",
    "candidate_rows_end",
    "matched_rows_start",
    "matched_rows_end",
}
MATCHED_CHANGE_SHARE_FIELDS = {
    "matched_cell_share_of_start",
    "matched_cell_share_of_end",
    "matched_row_share_of_start",
    "matched_row_share_of_end",
}
MATCHED_CHANGE_ESTIMATE_FIELDS = {
    "equal_cell_delta_bps",
    "median_cell_delta_bps",
    "min_support_weighted_delta_bps",
}


@dataclass(frozen=True)
class SupportThresholds:
    observations: int = 1_000
    dates: int = 30
    endpoint_pairs: int = 30
    reference_observations: int = 100
    reference_dates: int = 30
    reference_endpoint_pairs: int = 30


def _finite_json(value: object) -> object:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        normalized = float(format(value, f".{CANONICAL_FLOAT_SIGNIFICANT_DIGITS}g"))
        return 0.0 if normalized == 0.0 else normalized
    if isinstance(value, dict):
        return {str(key): _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    return value


def _serialized_p_value(value: float) -> float:
    return 0.0 if value < SERIALIZED_P_VALUE_FLOOR else value


def _validate_domain_series(series: pd.Series, field: str, domain: set[object]) -> None:
    if series.isna().any() or not set(series.dropna().astype(object).tolist()).issubset(domain):
        raise ValueError(f"paired dominance-cost prepared frame has out-of-domain {field}")


def _validate_comparator_mapping(frame: pd.DataFrame) -> None:
    if frame[["comparator", "comparator_symbol"]].isna().any().any():
        raise ValueError("paired dominance-cost comparator mapping is incomplete")
    addresses = frame["comparator"].astype(str).str.lower()
    expected = addresses.map(COMPARATOR_VEHICLES)
    actual = frame["comparator_symbol"].astype(str)
    if expected.isna().any() or not expected.eq(actual).all():
        raise ValueError("paired dominance-cost comparator address-symbol mapping disagrees with the canonical contract")


def _validate_prepared_frame(frame: pd.DataFrame) -> None:
    required = {"date", "reserve_hour_utc", "endpoint_pair", "attempt_id", "comparator_support_mask", "comparator", "comparator_symbol", "trade_size_usd", "available_candidate_count", "sample_year", "routing_era", "architecture", OUTCOME, *HOUR_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"paired dominance-cost prepared frame lacks fields: {missing}")
    domains = {
        "comparator_symbol": set(COMPARATOR_SYMBOLS),
        "trade_size_usd": set(LEVELS["trade_size_usd"]),
        "architecture": set(LEVELS["architecture"]),
        "available_candidate_count": set(LEVELS["available_candidate_count"]),
        "routing_era": set(LEVELS["routing_era"]),
    }
    for field, domain in domains.items():
        _validate_domain_series(frame[field], field, domain)
    _validate_comparator_mapping(frame)
    hour = pd.to_numeric(frame["reserve_hour_utc"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(hour).all() or not np.equal(hour, np.floor(hour)).all() or ((hour < 0) | (hour > 23)).any():
        raise ValueError("paired dominance-cost reserve_hour_utc must be an integer from 0 through 23")
    outcome = pd.to_numeric(frame[OUTCOME], errors="coerce").to_numpy(dtype=float)
    trade_size = pd.to_numeric(frame["trade_size_usd"], errors="coerce").to_numpy(dtype=float)
    year = pd.to_numeric(frame["sample_year"], errors="coerce").to_numpy(dtype=float)
    harmonics = frame[list(HOUR_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(outcome).all() or not np.isfinite(trade_size).all() or not np.isfinite(year).all() or not np.isfinite(harmonics).all() or not np.equal(year, np.floor(year)).all():
        raise ValueError("paired dominance-cost prepared frame has non-finite or non-integral core values")
    if frame["endpoint_pair"].isna().any():
        raise ValueError("paired dominance-cost prepared frame has missing endpoint pairs")
    attempt_id = pd.to_numeric(frame["attempt_id"], errors="coerce").to_numpy(dtype=float)
    support_mask = pd.to_numeric(frame["comparator_support_mask"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(attempt_id).all() or not np.equal(attempt_id, np.floor(attempt_id)).all() or (attempt_id < 1).any():
        raise ValueError("paired dominance-cost attempt_id must be a positive integer")
    if not np.isfinite(support_mask).all() or not np.equal(support_mask, np.floor(support_mask)).all() or (support_mask < 1).any() or (support_mask > sum(COMPARATOR_MASKS.values())).any():
        raise ValueError("paired dominance-cost comparator support mask is invalid")
    expected_bits = frame["comparator_symbol"].astype(str).map(COMPARATOR_MASKS).to_numpy(dtype=int)
    if ((support_mask.astype(int) & expected_bits) != expected_bits).any() or frame.duplicated(["attempt_id", "comparator_symbol"]).any():
        raise ValueError("paired dominance-cost attempt membership is inconsistent")
    dates = frame["date"].astype(str)
    parsed_dates = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    if parsed_dates.isna().any() or not np.array_equal(year.astype(int), parsed_dates.dt.year.to_numpy(dtype=int)):
        raise ValueError("paired dominance-cost dates and sample years disagree")


def resolve_probe_input(pointer_path: Path, *, allow_quarantined: bool) -> dict[str, object]:
    """Resolve a certified release or hash-verify a quarantine missing only sidecars."""

    pointer_path = Path(pointer_path)
    strict_error: str | None = None
    try:
        release = resolve_dominance_cost_release(pointer_path)
        return {
            "artifacts": dict(release.artifacts),
            "generation_id": release.generation_id,
            "pointer_sha256": file_sha256(pointer_path),
            "provenance_status": "certified",
            "strict_resolver_error": None,
        }
    except (FileNotFoundError, ValueError) as error:
        strict_error = str(error)
        if not allow_quarantined:
            raise
        if "lacks provenance" not in strict_error:
            raise
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("dominance-cost quarantine pointer is invalid") from error
    records = pointer.get("artifacts") if isinstance(pointer, dict) else None
    generation = pointer.get("generation_id") if isinstance(pointer, dict) else None
    build_identity = pointer.get("build_identity_sha256") if isinstance(pointer, dict) else None
    if (
        not isinstance(pointer, dict)
        or pointer.get("kind") != DOMINANCE_COST_RELEASE_KIND
        or pointer.get("schema_version") != DOMINANCE_COST_RELEASE_SCHEMA_VERSION
        or not is_sha256(generation)
        or not is_sha256(build_identity)
        or not isinstance(records, dict)
        or set(records) != set(DOMINANCE_COST_RELEASE_FILENAMES)
    ):
        raise ValueError("dominance-cost quarantine pointer contract is invalid")
    hashes: dict[str, str] = {}
    for name, filename in DOMINANCE_COST_RELEASE_FILENAMES.items():
        record = records.get(name)
        if not isinstance(record, dict) or record.get("filename") != filename or not is_sha256(record.get("sha256")) or not is_sha256(record.get("provenance_sha256")):
            raise ValueError(f"dominance-cost quarantine pointer record is invalid: {name}")
        hashes[name] = str(record["sha256"])
    if generation_id(hashes, str(build_identity)) != generation:
        raise ValueError("dominance-cost quarantine generation identity disagrees")
    paths = generation_paths(pointer_path.parent, str(generation), DOMINANCE_COST_RELEASE_FILENAMES)
    for name, path in paths.items():
        if not path.is_file() or file_sha256(path) != hashes[name]:
            raise ValueError(f"dominance-cost quarantine artifact digest disagrees: {name}")
    return {
        "artifacts": paths,
        "artifact_sha256": hashes,
        "generation_id": str(generation),
        "pointer_sha256": file_sha256(pointer_path),
        "provenance_status": "quarantined_missing_provenance",
        "strict_resolver_error": strict_error,
    }


def load_panel(path: Path) -> pd.DataFrame:
    """Read only fields in the declared provisional estimand and conditioning set."""

    routing_case = routing_era_case_sql("date")
    mask_case = "CASE comparator_symbol " + " ".join(f"WHEN '{symbol}' THEN {mask}" for symbol, mask in COMPARATOR_MASKS.items()) + " ELSE 0 END"
    connection = duckdb.connect()
    try:
        table = connection.execute(
            f"""
            SELECT date, reserve_hour_utc::UTINYINT AS reserve_hour_utc,
                   dense_rank() OVER (ORDER BY src, tgt)::INTEGER AS endpoint_pair,
                   dense_rank() OVER (ORDER BY date, reserve_hour_utc, src, tgt, trade_size_usd)::INTEGER AS attempt_id,
                   bit_or({mask_case}) OVER (PARTITION BY date, reserve_hour_utc, src, tgt, trade_size_usd)::UTINYINT AS comparator_support_mask,
                   comparator, comparator_symbol, trade_size_usd,
                   CASE WHEN available_candidate_count >= 4 THEN '4_plus'
                        ELSE available_candidate_count::VARCHAR END AS available_candidate_count,
                   CAST(substr(date, 1, 4) AS SMALLINT) AS sample_year,
                   {routing_case} AS routing_era,
                   CASE WHEN (weth_hop1_source IN ('uniswap_v3','uniswap_v4') OR weth_hop2_source IN ('uniswap_v3','uniswap_v4'))
                                  AND (comparator_hop1_source IN ('uniswap_v3','uniswap_v4') OR comparator_hop2_source IN ('uniswap_v3','uniswap_v4')) THEN 'both_tick'
                        WHEN NOT (weth_hop1_source IN ('uniswap_v3','uniswap_v4') OR weth_hop2_source IN ('uniswap_v3','uniswap_v4'))
                                  AND NOT (comparator_hop1_source IN ('uniswap_v3','uniswap_v4') OR comparator_hop2_source IN ('uniswap_v3','uniswap_v4')) THEN 'both_non_tick'
                        ELSE 'asymmetric' END AS architecture,
                   weth_output_usd, comparator_output_usd, weth_symmetric_output_edge_bps
            FROM read_parquet(?)
            """,
            [str(path)],
        ).to_arrow_table()
    finally:
        connection.close()
    frame = table.to_pandas(categories=["date", "comparator", "comparator_symbol", "available_candidate_count", "routing_era", "architecture"])
    if frame.empty or frame.isna().any().any() or not np.isfinite(frame[OUTCOME]).all():
        raise ValueError("paired dominance-cost probe requires complete finite core fields")
    reconstructed = 20_000.0 * (frame["weth_output_usd"] - frame["comparator_output_usd"]) / (frame["weth_output_usd"] + frame["comparator_output_usd"])
    if not np.allclose(reconstructed, frame[OUTCOME], rtol=0.0, atol=1e-10):
        raise ValueError("paired dominance-cost outcome disagrees with its declared formula")
    frame.drop(columns=["weth_output_usd", "comparator_output_usd"], inplace=True)
    return prepare_frame(frame)


def _validate_support_arrow_schema(table: pa.Table) -> None:
    expected_types = {
        "date": pa.string(),
        "comparator": pa.string(),
        "comparator_symbol": pa.string(),
        "trade_size_usd": pa.decimal128(7, 1),
        **{stage: pa.int64() for stage in SUPPORT_STAGES},
    }
    if table.column_names != list(SUPPORT_COLUMNS):
        raise ValueError("dominance-cost support sidecar Arrow columns disagree with the canonical schema")
    for field in table.schema:
        if field.type != expected_types[field.name]:
            raise ValueError(f"dominance-cost support sidecar Arrow type is invalid for {field.name}: {field.type}")


def load_support(path: Path, *, expected_dates: Iterable[str] = CANONICAL_SUPPORT_DATES) -> pd.DataFrame:
    """Load and validate the complete sidecar support lattice."""

    connection = duckdb.connect()
    try:
        table = connection.execute("SELECT * FROM read_parquet(?)", [str(path)]).to_arrow_table()
    finally:
        connection.close()
    _validate_support_arrow_schema(table)
    return prepare_support(table.to_pandas(), expected_dates=expected_dates)


def prepare_support(frame: pd.DataFrame, *, expected_dates: Iterable[str] = CANONICAL_SUPPORT_DATES) -> pd.DataFrame:
    """Validate and attach canonical calendar fields to one support sidecar."""

    support = frame.copy()
    missing = sorted(SUPPORT_REQUIRED_FIELDS - set(support.columns))
    if missing or support.empty:
        raise ValueError(f"dominance-cost support sidecar lacks required fields: {missing}")
    if set(support.columns) != SUPPORT_REQUIRED_FIELDS:
        raise ValueError("dominance-cost support sidecar has undeclared fields")
    if support.isna().any().any() or support.duplicated(["date", "comparator", "comparator_symbol", "trade_size_usd"]).any():
        raise ValueError("dominance-cost support sidecar has missing or duplicate strata")
    for field in ("date", "comparator", "comparator_symbol"):
        if not support[field].map(lambda value: isinstance(value, str)).all():
            raise ValueError(f"dominance-cost support sidecar requires string values for {field}")
    if not support["date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError("dominance-cost support sidecar dates must use YYYY-MM-DD strings")
    _validate_comparator_mapping(support)
    support["comparator"] = support["comparator"].astype(str).str.lower()
    _validate_domain_series(support["comparator_symbol"], "comparator_symbol", set(COMPARATOR_SYMBOLS))
    _validate_domain_series(support["trade_size_usd"], "trade_size_usd", set(LEVELS["trade_size_usd"]))
    for stage in SUPPORT_STAGES:
        if pd.api.types.is_bool_dtype(support[stage].dtype) or not pd.api.types.is_integer_dtype(support[stage].dtype):
            raise ValueError(f"dominance-cost support sidecar has invalid integer counts: {stage}")
        if not support[stage].map(lambda value: isinstance(value, Integral) and not isinstance(value, (bool, np.bool_))).all() or (support[stage] < 0).any():
            raise ValueError(f"dominance-cost support sidecar has invalid integer counts: {stage}")
    for row in support[list(SUPPORT_STAGES)].itertuples(index=False, name=None):
        validate_support_counts({stage: int(value) for stage, value in zip(SUPPORT_STAGES, row, strict=True)})
    dates = support["date"]
    parsed = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any() or not parsed.dt.strftime("%Y-%m-%d").eq(dates).all():
        raise ValueError("dominance-cost support sidecar has invalid dates")
    perimeter = tuple(expected_dates)
    if not perimeter or len(perimeter) != len(set(perimeter)) or any(not isinstance(date, str) for date in perimeter):
        raise ValueError("dominance-cost support external calendar perimeter is invalid")
    address_by_symbol = {symbol: address for address, symbol in COMPARATOR_VEHICLES.items()}
    expected_strata = {
        (date, address_by_symbol[symbol], symbol, float(notional))
        for date in perimeter
        for symbol in COMPARATOR_SYMBOLS
        for notional in LEVELS["trade_size_usd"]
    }
    actual_strata = set(zip(dates, support["comparator"], support["comparator_symbol"].astype(str), support["trade_size_usd"].astype(float), strict=True))
    if actual_strata != expected_strata:
        raise ValueError("dominance-cost support sidecar does not cover the full date-comparator-notional lattice")
    support["sample_year"] = parsed.dt.year.astype(int)
    support["routing_era"] = pd.Categorical(dates.map(routing_era_for_date), categories=LEVELS["routing_era"], ordered=True)
    support["comparator_symbol"] = pd.Categorical(support["comparator_symbol"], categories=COMPARATOR_SYMBOLS, ordered=True)
    support["trade_size_usd"] = pd.Categorical(support["trade_size_usd"].astype(float), categories=LEVELS["trade_size_usd"], ordered=True)
    return support


def reconcile_panel_support(frame: pd.DataFrame, support: pd.DataFrame) -> None:
    """Require the primary panel to equal sidecar positive-finite support exactly."""

    keys = ["date", "comparator", "comparator_symbol", "trade_size_usd"]
    panel_counts = frame.groupby(keys, observed=True, sort=True).size().rename("panel_positive_finite_indirect_outputs").reset_index()
    expected = support[keys + ["positive_finite_indirect_outputs"]].copy()
    expected["comparator_symbol"] = expected["comparator_symbol"].astype(str)
    expected["trade_size_usd"] = expected["trade_size_usd"].astype(float)
    observed = panel_counts.copy()
    observed["comparator_symbol"] = observed["comparator_symbol"].astype(str)
    observed["trade_size_usd"] = observed["trade_size_usd"].astype(float)
    joined = expected.merge(observed, on=keys, how="outer", validate="one_to_one")
    if joined["positive_finite_indirect_outputs"].isna().any():
        raise ValueError("dominance-cost panel and support sidecar strata disagree")
    joined["panel_positive_finite_indirect_outputs"] = joined["panel_positive_finite_indirect_outputs"].fillna(0)
    if not joined["positive_finite_indirect_outputs"].astype(int).eq(joined["panel_positive_finite_indirect_outputs"].astype(int)).all():
        raise ValueError("dominance-cost panel does not reconcile to positive-finite indirect support")


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the one declared architecture, calendar, cluster, and hour contract."""

    result = frame.copy()
    if "comparator" not in result:
        raise ValueError("paired dominance-cost frame lacks canonical comparator addresses")
    result["comparator"] = pd.Categorical(result["comparator"].astype(str).str.lower(), categories=tuple(COMPARATOR_VEHICLES), ordered=True)
    if "endpoint_pair" not in result:
        result["endpoint_pair"] = result["src"].astype(str) + ">" + result["tgt"].astype(str)
    if "sample_year" not in result:
        result["sample_year"] = result["date"].astype(str).str[:4].astype(int)
    if "routing_era" not in result:
        result["routing_era"] = result["date"].astype(str).map(routing_era_for_date)
    if "architecture" not in result:
        tick_sources = {"uniswap_v3", "uniswap_v4"}
        weth_tick = result["weth_hop1_source"].isin(tick_sources) | result["weth_hop2_source"].isin(tick_sources)
        comparator_tick = result["comparator_hop1_source"].isin(tick_sources) | result["comparator_hop2_source"].isin(tick_sources)
        result["architecture"] = np.select(
            [weth_tick & comparator_tick, ~weth_tick & ~comparator_tick],
            ["both_tick", "both_non_tick"],
            default="asymmetric",
        )
    breadth = pd.to_numeric(result["available_candidate_count"].astype(str).str.replace("4_plus", "4"), errors="raise")
    if not np.isfinite(breadth).all() or not np.equal(breadth, np.floor(breadth)).all():
        raise ValueError("paired dominance-cost available_candidate_count must be a finite integer")
    result["available_candidate_count"] = np.where(breadth >= 4, "4_plus", breadth.astype(int).astype(str))
    for column, levels in LEVELS.items():
        _validate_domain_series(result[column], column, set(levels))
        result[column] = pd.Categorical(result[column], categories=levels, ordered=True)
    _validate_domain_series(result["comparator_symbol"], "comparator_symbol", set(COMPARATOR_SYMBOLS))
    result["comparator_symbol"] = pd.Categorical(result["comparator_symbol"], categories=COMPARATOR_SYMBOLS, ordered=True)
    result["reserve_hour_utc"] = pd.to_numeric(result["reserve_hour_utc"], errors="coerce")
    hour = result["reserve_hour_utc"].to_numpy(dtype=float)
    reference_hour = float(REFERENCE["reserve_hour_utc"])
    for harmonic in (1, 2):
        angle = 2 * np.pi * harmonic / 24
        result[f"hour_sin{harmonic}"] = np.sin(angle * hour) - np.sin(angle * reference_hour)
        result[f"hour_cos{harmonic}"] = np.cos(angle * hour) - np.cos(angle * reference_hour)
    _validate_prepared_frame(result)
    result["reserve_hour_utc"] = result["reserve_hour_utc"].astype(np.uint8)
    return result


def _design(frame: pd.DataFrame, blocks: Iterable[str], *, flexible_hour: bool = False) -> tuple[pd.DataFrame, dict[str, list[int]]]:
    pieces: list[pd.DataFrame] = []
    labels: list[str] = []
    for block in blocks:
        if block == "hour":
            if flexible_hour:
                category = pd.Categorical(frame["reserve_hour_utc"], categories=(12, *[hour for hour in range(24) if hour != 12]), ordered=True)
                piece = pd.get_dummies(category, prefix="reserve_hour_utc", dtype=float, drop_first=True)
                piece.index = frame.index
            else:
                piece = frame[list(HOUR_COLUMNS)].astype(float)
        else:
            piece = pd.get_dummies(frame[block], prefix=block, dtype=float, drop_first=True)
        pieces.append(piece)
        labels.extend([block] * len(piece.columns))
    design = pd.concat(pieces, axis=1) if pieces else pd.DataFrame(index=frame.index)
    keep = design.nunique(dropna=False).gt(1)
    design = design.loc[:, keep]
    labels = [label for label, retained in zip(labels, keep, strict=True) if retained]
    block_positions: dict[str, list[int]] = {}
    for position, label in enumerate(labels, start=1):
        block_positions.setdefault(label, []).append(position)
    return design, block_positions


def _covariance_status(fit: ClusteredOLSResult) -> dict[str, object]:
    covariance = (fit.covariance + fit.covariance.T) / 2
    if not np.isfinite(covariance).all():
        return {"finite": False, "positive_definite": False, "rank": None, "dimension": len(fit.beta), "minimum_eigenvalue": None}
    eigenvalue = float(np.linalg.eigvalsh(covariance).min())
    rank = int(np.linalg.matrix_rank(covariance))
    return {"finite": True, "positive_definite": eigenvalue > 0 and rank == len(fit.beta), "rank": rank, "dimension": len(fit.beta), "minimum_eigenvalue": eigenvalue}


def fit_model(frame: pd.DataFrame, blocks: Iterable[str], *, weights: np.ndarray | None = None, flexible_hour: bool = False, cluster_mode: str = "two_way") -> dict[str, object]:
    """Fit one reference-cell model and retain invalid covariance as evidence."""

    design, positions = _design(frame, blocks, flexible_hour=flexible_hour)
    if cluster_mode == "pair":
        primary, additional = frame["endpoint_pair"], ()
    else:
        primary = frame["date"]
        additional = (frame["endpoint_pair"],) if cluster_mode == "two_way" else ()
    fit = ols_clustered(frame[OUTCOME], design, primary, additional_clusters=additional, weights=weights, min_observations=100, min_clusters=30)
    covariance = _covariance_status(fit)
    joint_tests: dict[str, object] = {}
    names = ["reference", *design.columns.tolist()]
    for block, block_positions in positions.items():
        tested = [names[position] for position in block_positions]
        try:
            statistic, numerator_df, denominator_df, p_value = joint_wald_f(fit, names, tested)
            joint_tests[block] = {"status": "pass", "f": statistic, "q": numerator_df, "denominator_df": denominator_df, "p": _serialized_p_value(p_value)}
        except ValueError as error:
            joint_tests[block] = {"status": "invalid", "reason": str(error)}
    result = {
        "n": len(frame),
        "dates": int(frame["date"].nunique()),
        "endpoint_pairs": int(frame["endpoint_pair"].nunique()),
        "cluster_counts": list(fit.cluster_counts),
        "coefficient_names": names,
        "coefficients": fit.beta.tolist(),
        "standard_errors": fit.standard_errors.tolist(),
        "p_values": [_serialized_p_value(value) for value in fit.p_values.tolist()],
        "covariance": covariance,
        "joint_tests": joint_tests,
        "status": "pass" if covariance["positive_definite"] and np.isfinite(fit.beta).all() and np.isfinite(fit.standard_errors).all() and np.isfinite(fit.p_values).all() else "fit_nonfinite" if not np.isfinite(fit.beta).all() or not np.isfinite(fit.standard_errors).all() or not np.isfinite(fit.p_values).all() else "covariance_nonpd",
    }
    normalized = _finite_json(result)
    del design, fit
    gc.collect()
    return normalized


def _support(frame: pd.DataFrame) -> dict[str, int]:
    return {"n": len(frame), "dates": int(frame["date"].nunique()), "endpoint_pairs": int(frame["endpoint_pair"].nunique())}


def _reference_mask(frame: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for key, value in REFERENCE.items():
        mask &= frame[key].eq(value)
    return mask


def _raw_summary(frame: pd.DataFrame) -> dict[str, object]:
    daily = frame.groupby("date", observed=True)[OUTCOME].mean()
    return {**_support(frame), "opportunity_weighted_mean_bps": float(frame[OUTCOME].mean()), "equal_date_mean_bps": float(daily.mean()), "median_bps": float(frame[OUTCOME].median())}


def _attrition_cell(frame: pd.DataFrame) -> dict[str, object]:
    counts = {stage: int(frame[stage].sum()) for stage in SUPPORT_STAGES}
    transitions: dict[str, object] = {}
    for prior, current in zip(SUPPORT_STAGES, SUPPORT_STAGES[1:]):
        transitions[current] = {
            "lost_from_prior_stage": counts[prior] - counts[current],
            "share_of_prior_stage": None if counts[prior] == 0 else counts[current] / counts[prior],
            "share_of_attempted": None if counts[SUPPORT_STAGES[0]] == 0 else counts[current] / counts[SUPPORT_STAGES[0]],
        }
    return _finite_json({"strata": len(frame), "counts": counts, "transitions": transitions})


def _attrition_summary(support: pd.DataFrame) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for label, field in (("comparator", "comparator_symbol"), ("notional", "trade_size_usd"), ("year", "sample_year"), ("routing_era", "routing_era")):
        records = []
        for level, cell in support.groupby(field, observed=True, sort=True):
            records.append({field: level, **_attrition_cell(cell)})
        grouped[label] = records
    return {
        "estimand_population": "attempted WETH-versus-comparator route pairs with positive finite outputs for both indirect routes",
        "conditioning_stage": "positive_finite_indirect_outputs",
        "overall": _attrition_cell(support),
        "by": grouped,
    }


def _level_support(frame: pd.DataFrame) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    declared = {
        "trade_size_usd": LEVELS["trade_size_usd"],
        "architecture": LEVELS["architecture"],
        "available_candidate_count": LEVELS["available_candidate_count"],
        "routing_era": LEVELS["routing_era"],
        "reserve_hour_utc": tuple(range(24)),
    }
    for comparator in COMPARATOR_SYMBOLS:
        subset = frame[frame["comparator_symbol"].eq(comparator)]
        for field, levels in declared.items():
            for level in levels:
                cell = subset[subset[field].eq(level)]
                records.append({"record_type": "main_level_support", "comparator": comparator, "field": field, "level": level, **_support(cell)})
    return records


def _state_records(frame: pd.DataFrame, thresholds: SupportThresholds) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    keys = ["comparator_symbol", "architecture", "available_candidate_count", "routing_era"]
    states = product(COMPARATOR_SYMBOLS, LEVELS["architecture"], LEVELS["available_candidate_count"], LEVELS["routing_era"])
    for key in states:
        mask = pd.Series(True, index=frame.index)
        for field, level in zip(keys, key, strict=True):
            mask &= frame[field].eq(level)
        cell = frame[mask]
        reference = cell[cell["trade_size_usd"].eq(REFERENCE["trade_size_usd"]) & cell["reserve_hour_utc"].eq(REFERENCE["reserve_hour_utc"])]
        record = {"record_type": "architecture_breadth_era_state", **dict(zip(keys, key, strict=True)), **_support(cell), "reference_support": _support(reference), "raw_mean_bps": None if cell.empty else float(cell[OUTCOME].mean())}
        failures = []
        if len(cell) < thresholds.observations:
            failures.append("observations")
        if cell["date"].nunique() < thresholds.dates:
            failures.append("dates")
        if cell["endpoint_pair"].nunique() < thresholds.endpoint_pairs:
            failures.append("endpoint_pairs")
        if len(reference) < thresholds.reference_observations:
            failures.append("reference_observations")
        if reference["date"].nunique() < thresholds.reference_dates:
            failures.append("reference_dates")
        if reference["endpoint_pair"].nunique() < thresholds.reference_endpoint_pairs:
            failures.append("reference_endpoint_pairs")
        if failures:
            record.update(status="support_fail", failed_thresholds=failures)
        else:
            estimate = fit_model(cell, ("trade_size_usd", "hour"))
            record.update(status=estimate["status"], estimate=estimate)
        records.append(_finite_json(record))
    return records


def _influence_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    blocks = ("trade_size_usd", "architecture", "available_candidate_count", "routing_era", "hour")
    for comparator in COMPARATOR_SYMBOLS:
        subset = frame[frame["comparator_symbol"].eq(comparator)]
        for fraction in TAIL_FRACTIONS:
            lower, upper = subset[OUTCOME].quantile([fraction, 1 - fraction])
            cell = subset[subset[OUTCOME].between(lower, upper)]
            records.append({"record_type": "tail_deletion", "comparator": comparator, "tail_fraction_each_side": fraction, "lower_bps": float(lower), "upper_bps": float(upper), "estimate": fit_model(cell, blocks)})
        counts = subset["endpoint_pair"].value_counts()
        largest = int(counts.index[0])
        largest_ids = [largest]
        records.append({"record_type": "endpoint_deletion", "comparator": comparator, "rule": "largest_endpoint_pair", "deleted_endpoint_pair_count": 1, "deleted_endpoint_pair_ids": largest_ids, "deleted_set_sha256": canonical_json_sha256(largest_ids), "deleted_n": int(counts.iloc[0]), "estimate": fit_model(subset[subset["endpoint_pair"].ne(largest)], blocks)})
        count = max(1, int(math.ceil(len(counts) * 0.01)))
        deleted = counts.head(count)
        deleted_ids = sorted(int(value) for value in deleted.index)
        records.append({"record_type": "endpoint_deletion", "comparator": comparator, "rule": "largest_one_percent_endpoint_pairs", "deleted_endpoint_pair_count": count, "deleted_endpoint_pair_ids": deleted_ids, "deleted_set_sha256": canonical_json_sha256(deleted_ids), "deleted_n": int(deleted.sum()), "estimate": fit_model(subset[~subset["endpoint_pair"].isin(deleted_ids)], blocks)})
        for year in sorted(subset["sample_year"].unique()):
            records.append({"record_type": "leave_one_year_out", "comparator": comparator, "deleted_year": int(year), "estimate": fit_model(subset[subset["sample_year"].ne(year)], blocks)})
        del subset
        gc.collect()
    return records


def _matched_year_change(frame: pd.DataFrame) -> dict[str, object]:
    """Compare endpoint-year means only inside cells observed in both endpoint years."""

    selected = frame[frame["sample_year"].isin((MATCHED_YEAR_START, MATCHED_YEAR_END))]
    grouped = (
        selected.groupby([*MATCHED_CELL_KEYS, "sample_year"], observed=True, sort=True)[OUTCOME]
        .agg(["mean", "size"])
        .reset_index()
    )
    means = grouped.pivot(index=list(MATCHED_CELL_KEYS), columns="sample_year", values="mean")
    sizes = grouped.pivot(index=list(MATCHED_CELL_KEYS), columns="sample_year", values="size")
    matched_index = means.dropna(subset=[MATCHED_YEAR_START, MATCHED_YEAR_END]).index

    def summarize(comparator: str | None) -> dict[str, object]:
        candidate = grouped if comparator is None else grouped[grouped["comparator_symbol"].eq(comparator)]
        candidate_start = candidate[candidate["sample_year"].eq(MATCHED_YEAR_START)]
        candidate_end = candidate[candidate["sample_year"].eq(MATCHED_YEAR_END)]
        current_index = matched_index
        if comparator is not None:
            current_index = matched_index[matched_index.get_level_values("comparator_symbol") == comparator]
        matched_means = means.loc[current_index]
        matched_sizes = sizes.loc[current_index]
        delta = matched_means[MATCHED_YEAR_END] - matched_means[MATCHED_YEAR_START]
        weights = np.minimum(
            matched_sizes[MATCHED_YEAR_START].to_numpy(dtype=float),
            matched_sizes[MATCHED_YEAR_END].to_numpy(dtype=float),
        )
        candidate_cells_start = int(len(candidate_start))
        candidate_cells_end = int(len(candidate_end))
        candidate_rows_start = int(candidate_start["size"].sum())
        candidate_rows_end = int(candidate_end["size"].sum())
        matched_cells = int(len(current_index))
        matched_rows_start = int(matched_sizes[MATCHED_YEAR_START].sum()) if matched_cells else 0
        matched_rows_end = int(matched_sizes[MATCHED_YEAR_END].sum()) if matched_cells else 0
        return {
            "candidate_cells_start": candidate_cells_start,
            "candidate_cells_end": candidate_cells_end,
            "matched_cells": matched_cells,
            "candidate_rows_start": candidate_rows_start,
            "candidate_rows_end": candidate_rows_end,
            "matched_rows_start": matched_rows_start,
            "matched_rows_end": matched_rows_end,
            "matched_cell_share_of_start": matched_cells / candidate_cells_start if candidate_cells_start else None,
            "matched_cell_share_of_end": matched_cells / candidate_cells_end if candidate_cells_end else None,
            "matched_row_share_of_start": matched_rows_start / candidate_rows_start if candidate_rows_start else None,
            "matched_row_share_of_end": matched_rows_end / candidate_rows_end if candidate_rows_end else None,
            "equal_cell_delta_bps": float(delta.mean()) if matched_cells else None,
            "median_cell_delta_bps": float(delta.median()) if matched_cells else None,
            "min_support_weighted_delta_bps": float(np.average(delta.to_numpy(dtype=float), weights=weights)) if weights.sum() else None,
        }

    result = {
        "status": "provisional_descriptive_not_admissible",
        "start_year": MATCHED_YEAR_START,
        "end_year": MATCHED_YEAR_END,
        "cell_keys": list(MATCHED_CELL_KEYS),
        "pooled": summarize(None),
        "comparators": {comparator: summarize(comparator) for comparator in COMPARATOR_SYMBOLS},
        "interpretation": "same-cell descriptive change; matching fixes comparator, ordered endpoints, notional, reserve hour, architecture, and candidate breadth but does not identify an aggregator effect",
    }
    return _finite_json(result)


def _common_support_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for size in range(2, len(COMPARATOR_SYMBOLS) + 1):
        for comparators in combinations(COMPARATOR_SYMBOLS, size):
            required_mask = sum(COMPARATOR_MASKS[comparator] for comparator in comparators)
            common = frame[(frame["comparator_support_mask"].astype(int) & required_mask).eq(required_mask) & frame["comparator_symbol"].isin(comparators)]
            if common.empty:
                continue
            attempt_counts: list[int] = []
            for comparator in comparators:
                cell = common[common["comparator_symbol"].eq(comparator)]
                attempt_counts.append(int(cell["attempt_id"].nunique()))
            if len(set(attempt_counts)) != 1 or len(common) != attempt_counts[0] * len(comparators):
                raise ValueError("paired dominance-cost common-support membership is not balanced")
            estimates: dict[str, object] | None = None
            selected_model: str | None = None
            rejected_models: list[dict[str, object]] = []
            selected_cluster_mode: str | None = None
            for model_name, model_blocks, cluster_mode in COMMON_SUPPORT_MODEL_LADDER:
                candidate = {comparator: fit_model(common[common["comparator_symbol"].eq(comparator)], model_blocks, cluster_mode=cluster_mode) for comparator in comparators}
                if all(estimate["status"] == "pass" for estimate in candidate.values()):
                    estimates = candidate
                    selected_model = model_name
                    selected_cluster_mode = cluster_mode
                    break
                rejected_models.append({"model": model_name, "cluster_mode": cluster_mode, "statuses": {comparator: estimate["status"] for comparator, estimate in candidate.items()}})
            if estimates is None or selected_model is None or selected_cluster_mode is None:
                raise ValueError("paired dominance-cost common-support ladder has no jointly valid specification")
            records.append(
                {
                    "record_type": "common_support_sensitivity",
                    "comparators": list(comparators),
                    "support_mask": required_mask,
                    "selected_model": selected_model,
                    "selected_cluster_mode": selected_cluster_mode,
                    "rejected_models": rejected_models,
                    "support": {
                        "attempts_per_comparator": attempt_counts[0],
                        "dates": int(common["date"].nunique()),
                        "endpoint_pairs": int(common["endpoint_pair"].nunique()),
                        "observed_superset_masks": sorted(int(value) for value in common["comparator_support_mask"].unique()),
                    },
                    "estimates": estimates,
                }
            )
            del common
            gc.collect()
    return records


def _ledger_identity(record: Mapping[str, object]) -> list[object]:
    record_type = str(record["record_type"])
    if record_type in {"sample_summary", "support_attrition_summary", "matched_year_change_summary"}:
        return [record_type]
    if record_type == "pooled_model":
        return [record_type, record["model"]]
    if record_type == "comparator_summary":
        return [record_type, record["comparator"]]
    if record_type == "main_level_support":
        return [record_type, record["comparator"], record["field"], record["level"]]
    if record_type == "comparator_model":
        return [record_type, record["comparator"], record["model"]]
    if record_type == "architecture_breadth_era_state":
        return [record_type, record["comparator_symbol"], record["architecture"], record["available_candidate_count"], record["routing_era"]]
    if record_type == "tail_deletion":
        return [record_type, record["comparator"], record["tail_fraction_each_side"]]
    if record_type == "endpoint_deletion":
        return [record_type, record["comparator"], record["rule"]]
    if record_type == "leave_one_year_out":
        return [record_type, record["comparator"], record["deleted_year"]]
    if record_type == "common_support_sensitivity":
        return [record_type, *record["comparators"]]
    raise ValueError(f"paired dominance-cost ledger record type is unknown: {record_type}")


def _ledger_manifest(ledger: list[Mapping[str, object]]) -> dict[str, object]:
    counts = pd.Series([record["record_type"] for record in ledger]).value_counts().sort_index().to_dict()
    identities = sorted((_ledger_identity(record) for record in ledger), key=lambda value: json.dumps(value, sort_keys=True))
    return {"record_count": len(ledger), "record_counts": counts, "identity_sha256": canonical_json_sha256(identities), "ledger_sha256": canonical_json_sha256(ledger)}


def run_probe(frame: pd.DataFrame, support: pd.DataFrame, input_identity: Mapping[str, object], *, thresholds: SupportThresholds = SupportThresholds()) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Return a deterministic report and a complete support/admissibility ledger."""

    _validate_prepared_frame(frame)
    reconcile_panel_support(frame, support)
    sample = _raw_summary(frame)
    sample.update(comparators={comparator: _raw_summary(frame[frame["comparator_symbol"].eq(comparator)]) for comparator in COMPARATOR_SYMBOLS})
    sample["unique_priceable_attempts"] = int(frame["attempt_id"].nunique())
    sample["prepared_frame_deep_bytes"] = int(frame.memory_usage(index=True, deep=True).sum())
    mask_counts = frame[["attempt_id", "comparator_support_mask"]].drop_duplicates()["comparator_support_mask"].value_counts().sort_index()
    sample["common_support_mask_attempts"] = {str(int(mask)): int(count) for mask, count in mask_counts.items()}
    sample["all_four_common_attempts"] = int(mask_counts.get(sum(COMPARATOR_MASKS.values()), 0))
    sample["observed_years_by_comparator"] = {comparator: sorted(int(year) for year in frame.loc[frame["comparator_symbol"].eq(comparator), "sample_year"].unique()) for comparator in COMPARATOR_SYMBOLS}
    support_attrition = _attrition_summary(support)
    matched_year_change = _matched_year_change(frame)
    pooled: dict[str, object] = {}
    for name, time_block in (("year", "sample_year"), ("routing_era", "routing_era")):
        if time_block == "sample_year":
            years = [2024, *[year for year in sorted(frame["sample_year"].unique()) if year != 2024]]
            frame["sample_year"] = pd.Categorical(frame["sample_year"], categories=years, ordered=True)
        pooled[name] = fit_model(frame, ("comparator_symbol", "trade_size_usd", "architecture", "available_candidate_count", time_block))
    comparator_models: dict[str, object] = {}
    ledger = [
        {"record_type": "sample_summary", "sample": sample},
        {"record_type": "support_attrition_summary", "support_attrition": support_attrition},
        {"record_type": "matched_year_change_summary", "matched_year_change": matched_year_change},
        *[
            {"record_type": "pooled_model", "model": model_name, "status": pooled[model_name]["status"], "covariance": pooled[model_name]["covariance"], "estimate": pooled[model_name]}
            for model_name in POOLED_MODEL_NAMES
        ],
        *_level_support(frame),
    ]
    blocks = ("trade_size_usd", "architecture", "available_candidate_count", "routing_era", "hour")
    for comparator in COMPARATOR_SYMBOLS:
        subset = frame[frame["comparator_symbol"].eq(comparator)]
        reference = subset[_reference_mask(subset)]
        date_counts = subset.groupby("date", observed=True)[OUTCOME].transform("size").to_numpy(dtype=float)
        models = {
            "m0_raw": fit_model(subset, ()),
            "m1_size_architecture_breadth": fit_model(subset, blocks[:3]),
            "m2_plus_routing_era": fit_model(subset, blocks[:4]),
            "m3_plus_hour_harmonics": fit_model(subset, blocks),
            "m3_equal_date": fit_model(subset, blocks, weights=1.0 / date_counts),
            "m3_flexible_hour": fit_model(subset, blocks, flexible_hour=True),
            "m3_date_cluster_only": fit_model(subset, blocks, cluster_mode="date"),
            "m3_endpoint_cluster_only": fit_model(subset, blocks, cluster_mode="pair"),
        }
        comparator_summary = {"support": _support(subset), "reference_support": _support(reference), "reference_raw_mean_bps": float(reference[OUTCOME].mean())}
        comparator_models[comparator] = {**comparator_summary, "models": models}
        ledger.append({"record_type": "comparator_summary", "comparator": comparator, **comparator_summary})
        for model_name, model in models.items():
            ledger.append({"record_type": "comparator_model", "comparator": comparator, "model": model_name, "status": model["status"], "support": _support(subset), "covariance": model["covariance"], "estimate": model})
    states = _state_records(frame, thresholds)
    ledger.extend(states)
    influence = _influence_records(frame)
    ledger.extend(influence)
    common_support = _common_support_records(frame)
    ledger.extend(common_support)
    report = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "status": "provisional_descriptive_not_admissible",
        "input": dict(input_identity),
        "instrument_source_sha256": {
            "dominance_cost_pair_probe.py": file_sha256(Path(__file__)),
            "dominance_cost_contract.py": file_sha256(REPO_ROOT / "src/ddvc/analysis/dominance_cost_contract.py"),
            "dominance_cost_release.py": file_sha256(REPO_ROOT / "src/ddvc/analysis/dominance_cost_release.py"),
            "regression.py": file_sha256(Path(ols_clustered.__code__.co_filename)),
            "routing_technology.py": file_sha256(Path(routing_technology_module.__file__)),
            "run_dominance_cost_pair_probe.py": file_sha256(REPO_ROOT / "scripts/run_dominance_cost_pair_probe.py"),
        },
        "formulas": {
            "outcome": "20000*(weth_output_usd-comparator_output_usd)/(weth_output_usd+comparator_output_usd)",
            "positive_sign": "WETH returns more output than the named comparator",
            "architecture": "a candidate route is tick-touched when either selected hop uses uniswap_v3 or uniswap_v4; both_tick means both candidate routes are tick-touched; both_non_tick means neither is; asymmetric means exactly one is",
            "candidate_breadth": "2 and 3 remain distinct; every available_candidate_count >= 4 maps to 4_plus before model construction",
            "equal_date_weight": "1 / comparator-specific paired opportunities on that date",
            "inference": "CR1 clustered by date and ordered src>tgt endpoint pair unless the diagnostic name states otherwise",
            "hour": "two centered UTC Fourier harmonics; reference hour 12",
            "common_support": "fit comparators on identical priceable attempt IDs; select the first jointly valid specification in the declared M3-to-M0 ladder, trying two-way then date-only clustering at each model rung; a date-only fallback after non-PD endpoint-pair covariance remains descriptive sensitivity evidence and is not confirmatory inference",
            "matched_year_change": "2026 minus 2024 mean outcome inside cells with the same comparator, ordered endpoint pair, notional, reserve hour, architecture, and candidate breadth; report equal-cell, median-cell, and minimum-support-weighted changes",
            "numeric_serialization": "finite floating outputs are rounded to 7 significant digits before hashing; fit status is evaluated at machine precision",
            "p_value_serialization": "p-values below 1e-12 are serialized as 0.0; hypothesis-test decisions use machine-precision values",
        },
        "reference": REFERENCE,
        "routing_era_cutoffs": [{"date": date, "era_from_date": era, "source": source} for date, era, source in ROUTING_ERA_CUTOFFS],
        "sample": sample,
        "support_attrition": support_attrition,
        "matched_year_change": matched_year_change,
        "pooled_models": pooled,
        "comparator_models": comparator_models,
        "common_support_sets": [{"comparators": record["comparators"], "support_mask": record["support_mask"], "support": record["support"], "selected_model": record["selected_model"], "selected_cluster_mode": record["selected_cluster_mode"], "rejected_models": record["rejected_models"]} for record in common_support],
        "state_admissibility_counts": pd.Series([record["status"] for record in states]).value_counts().sort_index().to_dict(),
        "support_thresholds": thresholds.__dict__,
        "old_estimand_bridge": {
            "older_cp_native_dummy": 0.0535,
            "older_breadth_four_plus_native_dummy": -0.2048,
            "direct_numeric_comparison_valid": False,
            "reason": "the older native-dummy coefficient uses a different outcome, contrast, support, and sign scale; only conceptual sign-pattern comparison is valid",
        },
        "headline_boundary": "The probe can establish descriptive comparator, architecture, breadth, and calendar heterogeneity. It cannot establish a universal native-asset cost advantage, causality, or an aggregator effect.",
    }
    normalized_ledger = [_finite_json(record) for record in ledger]
    report["ledger_manifest"] = _ledger_manifest(normalized_ledger)
    normalized_report = _finite_json(report)
    result_sha256 = canonical_json_sha256({"report": normalized_report, "ledger": normalized_ledger})
    normalized_report["result_sha256"] = result_sha256
    return normalized_report, normalized_ledger


def _plain_integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, Integral) and not isinstance(value, (bool, np.bool_)) and int(value) >= minimum


def _finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(float(value))


def _validate_support_payload(value: object, *, name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != SUPPORT_FIELDS:
        raise ValueError(f"paired dominance-cost {name} schema is invalid")
    if not all(_plain_integer(value[field]) for field in SUPPORT_FIELDS):
        raise ValueError(f"paired dominance-cost {name} counts are invalid")
    if value["dates"] > value["n"] or value["endpoint_pairs"] > value["n"] or (value["n"] == 0 and (value["dates"] or value["endpoint_pairs"])):
        raise ValueError(f"paired dominance-cost {name} geometry is invalid")


def _validate_covariance_payload(value: object, *, dimension: int, status: str) -> None:
    if not isinstance(value, Mapping) or set(value) != COVARIANCE_FIELDS:
        raise ValueError("paired dominance-cost covariance schema is invalid")
    if not isinstance(value["finite"], bool) or not isinstance(value["positive_definite"], bool) or value["dimension"] != dimension:
        raise ValueError("paired dominance-cost covariance flags are invalid")
    if value["rank"] is not None and (not _plain_integer(value["rank"]) or value["rank"] > dimension):
        raise ValueError("paired dominance-cost covariance rank is invalid")
    if value["minimum_eigenvalue"] is not None and not _finite_number(value["minimum_eigenvalue"]):
        raise ValueError("paired dominance-cost covariance eigenvalue is invalid")
    if value["finite"] != (value["rank"] is not None and value["minimum_eigenvalue"] is not None):
        raise ValueError("paired dominance-cost covariance finite evidence is inconsistent")
    expected_pd = bool(value["finite"] and value["rank"] == dimension and float(value["minimum_eigenvalue"]) > 0)
    if value["positive_definite"] != expected_pd or (status == "pass" and not expected_pd) or (status == "covariance_nonpd" and expected_pd):
        raise ValueError("paired dominance-cost covariance status is inconsistent")


def _validate_fit_payload(value: object, *, expected_support: Mapping[str, object] | None = None, require_pass: bool = False) -> None:
    if not isinstance(value, Mapping) or set(value) != FIT_FIELDS or value.get("status") not in FIT_STATUSES:
        raise ValueError("paired dominance-cost fit schema is invalid")
    support = {field: value[field] for field in SUPPORT_FIELDS}
    _validate_support_payload(support, name="fit support")
    if expected_support is not None and support != expected_support:
        raise ValueError("paired dominance-cost fit and declared support disagree")
    names = value["coefficient_names"]
    vectors = [value["coefficients"], value["standard_errors"], value["p_values"]]
    if not isinstance(names, list) or not names or names[0] != "reference" or len(names) != len(set(names)) or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("paired dominance-cost coefficient-name schema is invalid")
    if any(not isinstance(vector, list) or len(vector) != len(names) for vector in vectors):
        raise ValueError("paired dominance-cost coefficient vectors are truncated or misaligned")
    status = str(value["status"])
    if require_pass and status != "pass":
        raise ValueError("paired dominance-cost selected fit must pass")
    finite_fit = all(_finite_number(item) for vector in vectors for item in vector)
    if status == "fit_nonfinite":
        if finite_fit:
            raise ValueError("paired dominance-cost nonfinite fit status lacks nonfinite evidence")
    else:
        if not finite_fit or any(float(item) < 0 for item in value["standard_errors"]) or any(not 0 <= float(item) <= 1 for item in value["p_values"]):
            raise ValueError("paired dominance-cost fitted vectors are invalid")
    clusters = value["cluster_counts"]
    if not isinstance(clusters, list) or not 1 <= len(clusters) <= 2 or any(not _plain_integer(count, minimum=1) for count in clusters):
        raise ValueError("paired dominance-cost cluster-count schema is invalid")
    _validate_covariance_payload(value["covariance"], dimension=len(names), status=status)
    tests = value["joint_tests"]
    if not isinstance(tests, Mapping) or any(not isinstance(name, str) or not name for name in tests):
        raise ValueError("paired dominance-cost joint-test schema is invalid")
    for test in tests.values():
        if not isinstance(test, Mapping) or test.get("status") not in {"pass", "invalid"}:
            raise ValueError("paired dominance-cost joint-test record is invalid")
        if test["status"] == "pass":
            if set(test) != {"status", "f", "q", "denominator_df", "p"} or not _finite_number(test["f"]) or not _plain_integer(test["q"], minimum=1) or not _plain_integer(test["denominator_df"], minimum=1) or not _finite_number(test["p"]) or not 0 <= float(test["p"]) <= 1:
                raise ValueError("paired dominance-cost passing joint-test schema is invalid")
        elif set(test) != {"status", "reason"} or not isinstance(test["reason"], str) or not test["reason"]:
            raise ValueError("paired dominance-cost invalid joint-test schema is invalid")


def _expected_attrition_cell(strata: int, counts: Mapping[str, object]) -> dict[str, object]:
    return _finite_json(
        {
            "strata": strata,
            "counts": dict(counts),
            "transitions": {
                current: {
                    "lost_from_prior_stage": int(counts[prior]) - int(counts[current]),
                    "share_of_prior_stage": None if counts[prior] == 0 else int(counts[current]) / int(counts[prior]),
                    "share_of_attempted": None if counts[SUPPORT_STAGES[0]] == 0 else int(counts[current]) / int(counts[SUPPORT_STAGES[0]]),
                }
                for prior, current in zip(SUPPORT_STAGES, SUPPORT_STAGES[1:], strict=False)
            },
        }
    )


def _validate_attrition_cell(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"strata", "counts", "transitions"} or not _plain_integer(value["strata"]):
        raise ValueError("paired dominance-cost support-attrition cell schema is invalid")
    counts = value["counts"]
    if not isinstance(counts, Mapping) or set(counts) != set(SUPPORT_STAGES) or any(not _plain_integer(counts[stage]) for stage in SUPPORT_STAGES):
        raise ValueError("paired dominance-cost support-attrition counts are invalid")
    validate_support_counts({stage: int(counts[stage]) for stage in SUPPORT_STAGES})
    if value != _expected_attrition_cell(int(value["strata"]), counts):
        raise ValueError("paired dominance-cost support-attrition arithmetic disagrees")


def _validate_support_attrition(value: object, sample: Mapping[str, object], *, canonical_perimeter: bool) -> None:
    if not isinstance(value, Mapping) or set(value) != {"estimand_population", "conditioning_stage", "overall", "by"} or value["conditioning_stage"] != "positive_finite_indirect_outputs" or not isinstance(value["estimand_population"], str):
        raise ValueError("paired dominance-cost support-attrition schema is invalid")
    _validate_attrition_cell(value["overall"])
    overall = value["overall"]
    expected_strata = len(CANONICAL_SUPPORT_DATES) * len(COMPARATOR_SYMBOLS) * len(LEVELS["trade_size_usd"])
    if (canonical_perimeter and overall["strata"] != expected_strata) or (not canonical_perimeter and overall["strata"] % (len(COMPARATOR_SYMBOLS) * len(LEVELS["trade_size_usd"]))) or overall["counts"]["positive_finite_indirect_outputs"] != sample["n"]:
        raise ValueError("paired dominance-cost support-attrition perimeter disagrees with the sample")
    groups = value["by"]
    expected = {
        "comparator": ("comparator_symbol", COMPARATOR_SYMBOLS),
        "notional": ("trade_size_usd", LEVELS["trade_size_usd"]),
        "year": ("sample_year", tuple(range(2020, 2027)) if canonical_perimeter else None),
        "routing_era": ("routing_era", LEVELS["routing_era"] if canonical_perimeter else None),
    }
    if not isinstance(groups, Mapping) or set(groups) != set(expected):
        raise ValueError("paired dominance-cost support-attrition grouping schema is invalid")
    for group_name, (field, levels) in expected.items():
        records = groups[group_name]
        observed_levels = [record.get(field) for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []
        if not isinstance(records, list) or (levels is not None and observed_levels != list(levels)) or (levels is None and (not observed_levels or len(observed_levels) != len(set(observed_levels)))):
            raise ValueError(f"paired dominance-cost support-attrition levels are invalid: {group_name}")
        for record in records:
            if not isinstance(record, Mapping) or set(record) != {field, "strata", "counts", "transitions"}:
                raise ValueError(f"paired dominance-cost support-attrition record schema is invalid: {group_name}")
            _validate_attrition_cell({key: record[key] for key in ("strata", "counts", "transitions")})
        if sum(int(record["strata"]) for record in records) != overall["strata"] or any(sum(int(record["counts"][stage]) for record in records) != overall["counts"][stage] for stage in SUPPORT_STAGES):
            raise ValueError(f"paired dominance-cost support-attrition totals disagree: {group_name}")
    comparator_records = {record["comparator_symbol"]: record for record in groups["comparator"]}
    for comparator in COMPARATOR_SYMBOLS:
        if comparator_records[comparator]["counts"]["positive_finite_indirect_outputs"] != sample["comparators"][comparator]["n"]:
            raise ValueError("paired dominance-cost comparator attrition disagrees with the sample")


def _validate_matched_change_cell(value: object) -> None:
    expected = MATCHED_CHANGE_COUNT_FIELDS | MATCHED_CHANGE_SHARE_FIELDS | MATCHED_CHANGE_ESTIMATE_FIELDS
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("paired dominance-cost matched-year cell schema is invalid")
    if any(not _plain_integer(value[field]) for field in MATCHED_CHANGE_COUNT_FIELDS):
        raise ValueError("paired dominance-cost matched-year counts are invalid")
    if value["matched_cells"] > min(value["candidate_cells_start"], value["candidate_cells_end"]):
        raise ValueError("paired dominance-cost matched-year cell support exceeds its candidates")
    if value["matched_rows_start"] > value["candidate_rows_start"] or value["matched_rows_end"] > value["candidate_rows_end"]:
        raise ValueError("paired dominance-cost matched-year row support exceeds its candidates")
    expected_shares = {
        "matched_cell_share_of_start": None if value["candidate_cells_start"] == 0 else value["matched_cells"] / value["candidate_cells_start"],
        "matched_cell_share_of_end": None if value["candidate_cells_end"] == 0 else value["matched_cells"] / value["candidate_cells_end"],
        "matched_row_share_of_start": None if value["candidate_rows_start"] == 0 else value["matched_rows_start"] / value["candidate_rows_start"],
        "matched_row_share_of_end": None if value["candidate_rows_end"] == 0 else value["matched_rows_end"] / value["candidate_rows_end"],
    }
    for field, expected_share in expected_shares.items():
        observed = value[field]
        if expected_share is None:
            if observed is not None:
                raise ValueError("paired dominance-cost matched-year zero-support share is invalid")
        elif not _finite_number(observed) or not math.isclose(float(observed), expected_share, rel_tol=1e-6, abs_tol=1e-7):
            raise ValueError("paired dominance-cost matched-year support share is invalid")
    estimates = [value[field] for field in MATCHED_CHANGE_ESTIMATE_FIELDS]
    if value["matched_cells"]:
        if any(not _finite_number(item) for item in estimates) or not value["matched_rows_start"] or not value["matched_rows_end"]:
            raise ValueError("paired dominance-cost matched-year estimates lack support")
    elif any(item is not None for item in estimates) or value["matched_rows_start"] or value["matched_rows_end"]:
        raise ValueError("paired dominance-cost unsupported matched-year estimates are not null")


def _validate_matched_year_change(value: object) -> None:
    expected = {"status", "start_year", "end_year", "cell_keys", "pooled", "comparators", "interpretation"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("paired dominance-cost matched-year schema is invalid")
    if value["status"] != "provisional_descriptive_not_admissible" or value["start_year"] != MATCHED_YEAR_START or value["end_year"] != MATCHED_YEAR_END:
        raise ValueError("paired dominance-cost matched-year perimeter is invalid")
    if value["cell_keys"] != list(MATCHED_CELL_KEYS) or not isinstance(value["interpretation"], str) or not value["interpretation"]:
        raise ValueError("paired dominance-cost matched-year contract is invalid")
    comparators = value["comparators"]
    if not isinstance(comparators, Mapping) or set(comparators) != set(COMPARATOR_SYMBOLS):
        raise ValueError("paired dominance-cost matched-year comparator coverage is invalid")
    _validate_matched_change_cell(value["pooled"])
    for cell in comparators.values():
        _validate_matched_change_cell(cell)
    for field in MATCHED_CHANGE_COUNT_FIELDS:
        if int(value["pooled"][field]) != sum(int(cell[field]) for cell in comparators.values()):
            raise ValueError("paired dominance-cost matched-year pooled support disagrees with comparators")


def _validate_sample_summary(value: object) -> None:
    raw_fields = SUPPORT_FIELDS | {"opportunity_weighted_mean_bps", "equal_date_mean_bps", "median_bps"}
    fields = raw_fields | {"comparators", "unique_priceable_attempts", "prepared_frame_deep_bytes", "common_support_mask_attempts", "all_four_common_attempts", "observed_years_by_comparator"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("paired dominance-cost sample-summary schema is invalid")
    _validate_support_payload({field: value[field] for field in SUPPORT_FIELDS}, name="sample")
    if any(not _finite_number(value[field]) for field in raw_fields - SUPPORT_FIELDS) or not _plain_integer(value["unique_priceable_attempts"], minimum=1) or not _plain_integer(value["prepared_frame_deep_bytes"], minimum=1) or not _plain_integer(value["all_four_common_attempts"]):
        raise ValueError("paired dominance-cost sample-summary values are invalid")
    comparators = value["comparators"]
    if not isinstance(comparators, Mapping) or set(comparators) != set(COMPARATOR_SYMBOLS):
        raise ValueError("paired dominance-cost comparator sample schema is invalid")
    for summary in comparators.values():
        if not isinstance(summary, Mapping) or set(summary) != raw_fields:
            raise ValueError("paired dominance-cost comparator sample record is invalid")
        _validate_support_payload({field: summary[field] for field in SUPPORT_FIELDS}, name="comparator sample")
        if any(not _finite_number(summary[field]) for field in raw_fields - SUPPORT_FIELDS):
            raise ValueError("paired dominance-cost comparator sample values are invalid")
    if sum(int(summary["n"]) for summary in comparators.values()) != value["n"]:
        raise ValueError("paired dominance-cost comparator sample counts disagree")
    masks = value["common_support_mask_attempts"]
    if not isinstance(masks, Mapping) or any(not isinstance(mask, str) or not mask.isdigit() or not 1 <= int(mask) <= sum(COMPARATOR_MASKS.values()) or not _plain_integer(count, minimum=1) for mask, count in masks.items()):
        raise ValueError("paired dominance-cost common-support mask summary is invalid")
    if sum(int(count) for count in masks.values()) != value["unique_priceable_attempts"] or sum(int(mask).bit_count() * int(count) for mask, count in masks.items()) != value["n"] or value["all_four_common_attempts"] != masks.get(str(sum(COMPARATOR_MASKS.values())), 0):
        raise ValueError("paired dominance-cost common-support mask arithmetic disagrees")
    for comparator, bit in COMPARATOR_MASKS.items():
        if sum(int(count) for mask, count in masks.items() if int(mask) & bit) != comparators[comparator]["n"]:
            raise ValueError("paired dominance-cost common-support comparator count disagrees")
    years = value["observed_years_by_comparator"]
    if not isinstance(years, Mapping) or set(years) != set(COMPARATOR_SYMBOLS) or any(not isinstance(items, list) or items != sorted(set(items)) or any(not _plain_integer(year, minimum=1900) for year in items) for items in years.values()):
        raise ValueError("paired dominance-cost observed-year schema is invalid")


def _validate_publish_payload(report: Mapping[str, object], ledger: list[Mapping[str, object]]) -> None:
    if set(report) != REPORT_FIELDS or report.get("schema_version") != PROBE_SCHEMA_VERSION or report.get("status") != "provisional_descriptive_not_admissible" or not is_sha256(report.get("result_sha256")):
        raise ValueError("paired dominance-cost probe report contract is invalid")
    for field in ("input", "instrument_source_sha256", "formulas", "reference", "sample", "support_attrition", "matched_year_change", "pooled_models", "comparator_models", "state_admissibility_counts", "support_thresholds", "old_estimand_bridge", "ledger_manifest"):
        if not isinstance(report.get(field), Mapping):
            raise ValueError(f"paired dominance-cost probe report field is invalid: {field}")
    if set(report["formulas"]) != {"outcome", "positive_sign", "architecture", "candidate_breadth", "equal_date_weight", "inference", "hour", "common_support", "matched_year_change", "numeric_serialization", "p_value_serialization"} or any(not isinstance(value, str) or not value for value in report["formulas"].values()):
        raise ValueError("paired dominance-cost formula schema is invalid")
    if set(report["old_estimand_bridge"]) != {"older_cp_native_dummy", "older_breadth_four_plus_native_dummy", "direct_numeric_comparison_valid", "reason"} or report["old_estimand_bridge"]["direct_numeric_comparison_valid"] is not False or not isinstance(report["old_estimand_bridge"]["reason"], str) or not _finite_number(report["old_estimand_bridge"]["older_cp_native_dummy"]) or not _finite_number(report["old_estimand_bridge"]["older_breadth_four_plus_native_dummy"]):
        raise ValueError("paired dominance-cost old-estimand bridge schema is invalid")
    if not isinstance(report["headline_boundary"], str) or not report["headline_boundary"]:
        raise ValueError("paired dominance-cost headline boundary is invalid")
    if set(report["ledger_manifest"]) != {"record_count", "record_counts", "identity_sha256", "ledger_sha256"}:
        raise ValueError("paired dominance-cost ledger-manifest schema is invalid")
    if set(report["pooled_models"]) != set(POOLED_MODEL_NAMES) or set(report["comparator_models"]) != set(COMPARATOR_SYMBOLS):
        raise ValueError("paired dominance-cost report model coverage is invalid")
    if not isinstance(report.get("common_support_sets"), list) or report.get("reference") != REFERENCE:
        raise ValueError("paired dominance-cost common-support report is invalid")
    _validate_sample_summary(report["sample"])
    _validate_matched_year_change(report["matched_year_change"])
    canonical_perimeter = report["input"].get("provenance_status") != "synthetic"
    _validate_support_attrition(report["support_attrition"], report["sample"], canonical_perimeter=canonical_perimeter)
    if not is_sha256(report["input"].get("panel_sha256")) or not is_sha256(report["input"].get("support_sha256")):
        raise ValueError("paired dominance-cost report does not bind both input artifacts")
    input_fields = set(report["input"])
    production_fields = {"generation_id", "pointer_sha256", "provenance_status", "strict_resolver_error", "panel_filename", "panel_sha256", "panel_bytes", "support_filename", "support_sha256", "support_bytes"}
    if input_fields not in (production_fields, production_fields | {"artifact_sha256"}, {"panel_sha256", "support_sha256", "provenance_status"}):
        raise ValueError("paired dominance-cost input identity schema is invalid")
    if input_fields == {"panel_sha256", "support_sha256", "provenance_status"}:
        if report["input"]["provenance_status"] != "synthetic":
            raise ValueError("paired dominance-cost synthetic input identity is invalid")
    else:
        if not is_sha256(report["input"].get("generation_id")) or not is_sha256(report["input"].get("pointer_sha256")) or report["input"].get("provenance_status") not in {"certified", "quarantined_missing_provenance"} or not isinstance(report["input"].get("panel_filename"), str) or not isinstance(report["input"].get("support_filename"), str) or not _plain_integer(report["input"].get("panel_bytes"), minimum=1) or not _plain_integer(report["input"].get("support_bytes"), minimum=1):
            raise ValueError("paired dominance-cost production input identity is invalid")
        if report["input"]["panel_filename"] != DOMINANCE_COST_RELEASE_FILENAMES["panel"] or report["input"]["support_filename"] != DOMINANCE_COST_RELEASE_FILENAMES["support"] or (report["input"]["provenance_status"] == "certified") != ("artifact_sha256" not in report["input"]) or (report["input"]["provenance_status"] == "certified" and report["input"]["strict_resolver_error"] is not None) or (report["input"]["provenance_status"] == "quarantined_missing_provenance" and (not isinstance(report["input"]["strict_resolver_error"], str) or not report["input"]["strict_resolver_error"])):
            raise ValueError("paired dominance-cost production input provenance is inconsistent")
        if "artifact_sha256" in report["input"] and (not isinstance(report["input"]["artifact_sha256"], Mapping) or report["input"]["artifact_sha256"] != {"panel": report["input"]["panel_sha256"], "support": report["input"]["support_sha256"]}):
            raise ValueError("paired dominance-cost input artifact hashes disagree")
    expected_sources = {"dominance_cost_pair_probe.py", "dominance_cost_contract.py", "dominance_cost_release.py", "regression.py", "routing_technology.py", "run_dominance_cost_pair_probe.py"}
    if set(report["instrument_source_sha256"]) != expected_sources or any(not is_sha256(value) for value in report["instrument_source_sha256"].values()):
        raise ValueError("paired dominance-cost instrument source binding is invalid")
    expected_cutoffs = [{"date": date, "era_from_date": era, "source": source} for date, era, source in ROUTING_ERA_CUTOFFS]
    if report.get("routing_era_cutoffs") != expected_cutoffs:
        raise ValueError("paired dominance-cost routing-era registry disagrees")
    threshold_fields = set(SupportThresholds.__dataclass_fields__)
    thresholds = report["support_thresholds"]
    if not isinstance(thresholds, Mapping) or set(thresholds) != threshold_fields or any(not _plain_integer(value, minimum=1) for value in thresholds.values()):
        raise ValueError("paired dominance-cost support-threshold schema is invalid")
    if not isinstance(ledger, list) or not ledger:
        raise ValueError("paired dominance-cost probe ledger must be a nonempty list")
    records_by_type: dict[str, list[Mapping[str, object]]] = {record_type: [] for record_type in LEDGER_REQUIRED_FIELDS}
    state_statuses: list[str] = []
    for record in ledger:
        if not isinstance(record, Mapping):
            raise ValueError("paired dominance-cost probe ledger record is invalid")
        record_type = record.get("record_type")
        required = LEDGER_REQUIRED_FIELDS.get(record_type)
        if required is None or not required.issubset(record):
            raise ValueError(f"paired dominance-cost probe ledger contract is invalid: {record_type}")
        allowed = {"record_type", *required}
        if record_type == "architecture_breadth_era_state":
            allowed |= {"raw_mean_bps", "failed_thresholds" if record.get("status") == "support_fail" else "estimate"}
        if set(record) != allowed:
            raise ValueError(f"paired dominance-cost probe ledger schema is not exact: {record_type}")
        records_by_type[str(record_type)].append(record)
        if record_type == "sample_summary":
            _validate_sample_summary(record["sample"])
        if record_type == "support_attrition_summary":
            _validate_support_attrition(record["support_attrition"], report["sample"], canonical_perimeter=canonical_perimeter)
        if record_type == "matched_year_change_summary":
            _validate_matched_year_change(record["matched_year_change"])
        if record_type == "pooled_model":
            if record["model"] not in POOLED_MODEL_NAMES or record["status"] != record["estimate"].get("status") or record["covariance"] != record["estimate"].get("covariance"):
                raise ValueError("paired dominance-cost pooled-model record is inconsistent")
            _validate_fit_payload(record["estimate"], expected_support={field: report["sample"][field] for field in SUPPORT_FIELDS})
        if record_type == "comparator_summary":
            if record["comparator"] not in COMPARATOR_SYMBOLS:
                raise ValueError("paired dominance-cost comparator-summary identity is invalid")
            _validate_support_payload(record["support"], name="comparator summary")
            _validate_support_payload(record["reference_support"], name="comparator reference summary")
            if any(record["reference_support"][field] > record["support"][field] for field in SUPPORT_FIELDS) or not _finite_number(record["reference_raw_mean_bps"]):
                raise ValueError("paired dominance-cost comparator reference mean is invalid")
        if record_type == "main_level_support":
            _validate_support_payload({field: record[field] for field in SUPPORT_FIELDS}, name="level support")
        if record_type == "comparator_model":
            if record.get("status") not in FIT_STATUSES or record["status"] != record["estimate"].get("status") or record["covariance"] != record["estimate"].get("covariance"):
                raise ValueError("paired dominance-cost comparator-model status is invalid")
            _validate_support_payload(record["support"], name="comparator model support")
            _validate_fit_payload(record["estimate"], expected_support=record["support"])
        if record_type == "architecture_breadth_era_state":
            status = str(record.get("status"))
            if status not in FIT_STATUSES | {"support_fail"}:
                raise ValueError("paired dominance-cost state status is invalid")
            if status == "support_fail" and not isinstance(record.get("failed_thresholds"), list):
                raise ValueError("paired dominance-cost failed state lacks threshold evidence")
            if status in FIT_STATUSES and not isinstance(record.get("estimate"), Mapping):
                raise ValueError("paired dominance-cost fitted state lacks estimate evidence")
            state_support = {field: record[field] for field in SUPPORT_FIELDS}
            _validate_support_payload(state_support, name="state support")
            _validate_support_payload(record["reference_support"], name="state reference support")
            if record["raw_mean_bps"] is not None and not _finite_number(record["raw_mean_bps"]):
                raise ValueError("paired dominance-cost state raw mean is invalid")
            if (record["n"] == 0) != (record["raw_mean_bps"] is None):
                raise ValueError("paired dominance-cost state raw mean disagrees with support")
            expected_failures = [
                threshold
                for threshold, observed in (
                    ("observations", record["n"]),
                    ("dates", record["dates"]),
                    ("endpoint_pairs", record["endpoint_pairs"]),
                    ("reference_observations", record["reference_support"]["n"]),
                    ("reference_dates", record["reference_support"]["dates"]),
                    ("reference_endpoint_pairs", record["reference_support"]["endpoint_pairs"]),
                )
                if observed < thresholds[threshold]
            ]
            if status == "support_fail" and record["failed_thresholds"] != expected_failures:
                raise ValueError("paired dominance-cost state threshold evidence disagrees")
            if status in FIT_STATUSES and expected_failures:
                raise ValueError("paired dominance-cost fitted state fails a support threshold")
            if status in FIT_STATUSES:
                _validate_fit_payload(record["estimate"], expected_support=state_support)
                if record["estimate"]["status"] != status:
                    raise ValueError("paired dominance-cost state and fitted status disagree")
            state_statuses.append(status)
        if record_type in {"tail_deletion", "endpoint_deletion", "leave_one_year_out"}:
            estimate = record.get("estimate")
            if not isinstance(estimate, Mapping) or estimate.get("status") not in FIT_STATUSES:
                raise ValueError("paired dominance-cost influence estimate is invalid")
            _validate_fit_payload(estimate)
        if record_type == "endpoint_deletion":
            deleted_ids = record["deleted_endpoint_pair_ids"]
            if not isinstance(deleted_ids, list) or deleted_ids != sorted(set(deleted_ids)) or any(not _plain_integer(value, minimum=1) for value in deleted_ids) or record["deleted_endpoint_pair_count"] != len(deleted_ids) or record["deleted_set_sha256"] != canonical_json_sha256(deleted_ids):
                raise ValueError("paired dominance-cost endpoint deletion evidence is invalid")
        if record_type == "common_support_sensitivity":
            comparators = record["comparators"]
            estimates = record["estimates"]
            if not isinstance(comparators, list) or not 2 <= len(comparators) <= len(COMPARATOR_SYMBOLS) or comparators != [value for value in COMPARATOR_SYMBOLS if value in comparators] or not isinstance(estimates, Mapping) or set(estimates) != set(comparators) or any(not isinstance(value, Mapping) or value.get("status") != "pass" for value in estimates.values()):
                raise ValueError("paired dominance-cost common-support evidence is invalid")
            common_support = record["support"]
            if not isinstance(common_support, Mapping) or set(common_support) != {"attempts_per_comparator", "dates", "endpoint_pairs", "observed_superset_masks"} or not all(_plain_integer(common_support[field], minimum=1) for field in ("attempts_per_comparator", "dates", "endpoint_pairs")) or not isinstance(common_support["observed_superset_masks"], list):
                raise ValueError("paired dominance-cost common-support schema is invalid")
            for estimate in estimates.values():
                _validate_fit_payload(estimate, expected_support={"n": common_support["attempts_per_comparator"], "dates": common_support["dates"], "endpoint_pairs": common_support["endpoint_pairs"]}, require_pass=True)
            ladder_specs = [(name, cluster_mode) for name, _blocks, cluster_mode in COMMON_SUPPORT_MODEL_LADDER]
            selected_spec = (record["selected_model"], record["selected_cluster_mode"])
            rejected_models = record["rejected_models"]
            if selected_spec not in ladder_specs or not isinstance(rejected_models, list) or [(item.get("model"), item.get("cluster_mode")) for item in rejected_models if isinstance(item, Mapping)] != ladder_specs[: ladder_specs.index(selected_spec)]:
                raise ValueError("paired dominance-cost common-support model ladder is invalid")
            for item in rejected_models:
                if not isinstance(item, Mapping) or set(item) != {"model", "cluster_mode", "statuses"} or not isinstance(item.get("statuses"), Mapping) or set(item["statuses"]) != set(comparators):
                    raise ValueError("paired dominance-cost common-support rejection evidence is invalid")
                statuses = item["statuses"].values()
                if any(status not in FIT_STATUSES for status in statuses) or all(status == "pass" for status in statuses):
                    raise ValueError("paired dominance-cost common-support rejection status is invalid")
    identities = [json.dumps(_ledger_identity(record), sort_keys=True) for record in ledger]
    if len(identities) != len(set(identities)):
        raise ValueError("paired dominance-cost probe ledger contains duplicate identities")
    expected_level = {
        json.dumps(["main_level_support", comparator, field, level], sort_keys=True)
        for comparator in COMPARATOR_SYMBOLS
        for field, levels in {
            "trade_size_usd": LEVELS["trade_size_usd"],
            "architecture": LEVELS["architecture"],
            "available_candidate_count": LEVELS["available_candidate_count"],
            "routing_era": LEVELS["routing_era"],
            "reserve_hour_utc": tuple(range(24)),
        }.items()
        for level in levels
    }
    expected_models = {json.dumps(["comparator_model", comparator, model], sort_keys=True) for comparator in COMPARATOR_SYMBOLS for model in COMPARATOR_MODEL_NAMES}
    expected_pooled = {json.dumps(["pooled_model", model], sort_keys=True) for model in POOLED_MODEL_NAMES}
    expected_comparator_summaries = {json.dumps(["comparator_summary", comparator], sort_keys=True) for comparator in COMPARATOR_SYMBOLS}
    expected_states = {json.dumps(["architecture_breadth_era_state", comparator, architecture, breadth, era], sort_keys=True) for comparator, architecture, breadth, era in product(COMPARATOR_SYMBOLS, LEVELS["architecture"], LEVELS["available_candidate_count"], LEVELS["routing_era"])}
    expected_tail = {json.dumps(["tail_deletion", comparator, fraction], sort_keys=True) for comparator in COMPARATOR_SYMBOLS for fraction in TAIL_FRACTIONS}
    expected_endpoint = {json.dumps(["endpoint_deletion", comparator, rule], sort_keys=True) for comparator in COMPARATOR_SYMBOLS for rule in ENDPOINT_DELETION_RULES}
    years_by_comparator = report["sample"].get("observed_years_by_comparator")
    if not isinstance(years_by_comparator, Mapping) or set(years_by_comparator) != set(COMPARATOR_SYMBOLS):
        raise ValueError("paired dominance-cost observed-year contract is invalid")
    expected_loyo = {json.dumps(["leave_one_year_out", comparator, int(year)], sort_keys=True) for comparator in COMPARATOR_SYMBOLS for year in years_by_comparator[comparator]}
    expected_grids = {
        "sample_summary": {json.dumps(["sample_summary"], sort_keys=True)},
        "support_attrition_summary": {json.dumps(["support_attrition_summary"], sort_keys=True)},
        "matched_year_change_summary": {json.dumps(["matched_year_change_summary"], sort_keys=True)},
        "pooled_model": expected_pooled,
        "comparator_summary": expected_comparator_summaries,
        "main_level_support": expected_level,
        "comparator_model": expected_models,
        "architecture_breadth_era_state": expected_states,
        "tail_deletion": expected_tail,
        "endpoint_deletion": expected_endpoint,
        "leave_one_year_out": expected_loyo,
    }
    for record_type, expected in expected_grids.items():
        actual = {json.dumps(_ledger_identity(record), sort_keys=True) for record in records_by_type[record_type]}
        if actual != expected:
            raise ValueError(f"paired dominance-cost ledger coverage is incomplete: {record_type}")
    comparator_summary_by_symbol = {record["comparator"]: record for record in records_by_type["comparator_summary"]}
    for comparator in COMPARATOR_SYMBOLS:
        base_support = comparator_summary_by_symbol[comparator]["support"]
        for field in ("trade_size_usd", "architecture", "available_candidate_count", "routing_era", "reserve_hour_utc"):
            cells = [record for record in records_by_type["main_level_support"] if record["comparator"] == comparator and record["field"] == field]
            if sum(int(record["n"]) for record in cells) != base_support["n"] or any(record["dates"] > base_support["dates"] or record["endpoint_pairs"] > base_support["endpoint_pairs"] for record in cells):
                raise ValueError("paired dominance-cost level-support partition disagrees with comparator support")
        state_cells = [record for record in records_by_type["architecture_breadth_era_state"] if record["comparator_symbol"] == comparator]
        if sum(int(record["n"]) for record in state_cells) != base_support["n"]:
            raise ValueError("paired dominance-cost state partition disagrees with comparator support")
        for record in records_by_type["tail_deletion"]:
            if record["comparator"] == comparator and (not _finite_number(record["lower_bps"]) or not _finite_number(record["upper_bps"]) or record["lower_bps"] > record["upper_bps"] or record["estimate"]["n"] > base_support["n"]):
                raise ValueError("paired dominance-cost tail-deletion evidence is invalid")
        for record in records_by_type["endpoint_deletion"]:
            if record["comparator"] == comparator and (not _plain_integer(record["deleted_n"], minimum=1) or record["estimate"]["n"] + record["deleted_n"] != base_support["n"]):
                raise ValueError("paired dominance-cost endpoint-deletion support disagrees")
        for record in records_by_type["leave_one_year_out"]:
            if record["comparator"] == comparator and record["estimate"]["n"] >= base_support["n"]:
                raise ValueError("paired dominance-cost leave-one-year-out support disagrees")
    mask_attempts = report["sample"].get("common_support_mask_attempts")
    if not isinstance(mask_attempts, Mapping):
        raise ValueError("paired dominance-cost common-support mask summary is invalid")
    parsed_mask_attempts = {int(mask): int(count) for mask, count in mask_attempts.items()}
    if report["sample"].get("all_four_common_attempts") != parsed_mask_attempts.get(sum(COMPARATOR_MASKS.values()), 0):
        raise ValueError("paired dominance-cost all-four support summary disagrees with mask evidence")
    expected_common: dict[str, tuple[int, list[int]]] = {}
    for size in range(2, len(COMPARATOR_SYMBOLS) + 1):
        for comparators in combinations(COMPARATOR_SYMBOLS, size):
            required_mask = sum(COMPARATOR_MASKS[comparator] for comparator in comparators)
            supersets = sorted(mask for mask, count in parsed_mask_attempts.items() if count > 0 and mask & required_mask == required_mask)
            attempts = sum(parsed_mask_attempts[mask] for mask in supersets)
            if attempts:
                expected_common[json.dumps(["common_support_sensitivity", *comparators], sort_keys=True)] = (attempts, supersets)
    actual_common = {json.dumps(_ledger_identity(record), sort_keys=True): record for record in records_by_type["common_support_sensitivity"]}
    if set(actual_common) != set(expected_common):
        raise ValueError("paired dominance-cost ledger coverage is incomplete: common_support_sensitivity")
    for identity, (attempts, supersets) in expected_common.items():
        support_record = actual_common[identity]["support"]
        if not isinstance(support_record, Mapping) or support_record.get("attempts_per_comparator") != attempts or support_record.get("observed_superset_masks") != supersets:
            raise ValueError("paired dominance-cost common-support counts disagree with mask evidence")
    for comparator in COMPARATOR_SYMBOLS:
        section = report["comparator_models"].get(comparator)
        if not isinstance(section, Mapping) or set(section) != {"support", "reference_support", "reference_raw_mean_bps", "models"} or set(section.get("models", {})) != set(COMPARATOR_MODEL_NAMES):
            raise ValueError("paired dominance-cost comparator report coverage is incomplete")
        summary_record = next(record for record in records_by_type["comparator_summary"] if record["comparator"] == comparator)
        if {key: section[key] for key in ("support", "reference_support", "reference_raw_mean_bps")} != {key: summary_record[key] for key in ("support", "reference_support", "reference_raw_mean_bps")}:
            raise ValueError("paired dominance-cost report and comparator-summary ledger disagree")
        if section["support"] != {field: report["sample"]["comparators"][comparator][field] for field in SUPPORT_FIELDS}:
            raise ValueError("paired dominance-cost report comparator support disagrees with the sample")
        for model_name in COMPARATOR_MODEL_NAMES:
            record = next(record for record in records_by_type["comparator_model"] if record["comparator"] == comparator and record["model"] == model_name)
            if record["estimate"] != section["models"][model_name]:
                raise ValueError("paired dominance-cost report and model ledger disagree")
    pooled_projection = {record["model"]: record["estimate"] for record in records_by_type["pooled_model"]}
    if pooled_projection != report["pooled_models"]:
        raise ValueError("paired dominance-cost report and pooled-model ledger disagree")
    if records_by_type["sample_summary"][0]["sample"] != report["sample"]:
        raise ValueError("paired dominance-cost report and sample-summary ledger disagree")
    if records_by_type["support_attrition_summary"][0]["support_attrition"] != report["support_attrition"]:
        raise ValueError("paired dominance-cost report and support-attrition ledger disagree")
    if records_by_type["matched_year_change_summary"][0]["matched_year_change"] != report["matched_year_change"]:
        raise ValueError("paired dominance-cost report and matched-year ledger disagree")
    common_projection = [{"comparators": record["comparators"], "support_mask": record["support_mask"], "support": record["support"], "selected_model": record["selected_model"], "selected_cluster_mode": record["selected_cluster_mode"], "rejected_models": record["rejected_models"]} for record in records_by_type["common_support_sensitivity"]]
    if common_projection != report["common_support_sets"]:
        raise ValueError("paired dominance-cost report and common-support ledger disagree")
    if report["ledger_manifest"] != _ledger_manifest(ledger):
        raise ValueError("paired dominance-cost report and ledger manifest disagree")
    reported_counts = {str(key): int(value) for key, value in report["state_admissibility_counts"].items()}
    actual_counts = pd.Series(state_statuses).value_counts().sort_index().to_dict()
    if reported_counts != actual_counts:
        raise ValueError("paired dominance-cost state counts disagree with the ledger")


def publish_probe(report: Mapping[str, object], ledger: list[Mapping[str, object]], output_root: Path) -> dict[str, object]:
    """Publish deterministic report and complete ledger, then select them marker-last."""

    output_root = Path(output_root)
    if not any("provisional" in part.lower() for part in output_root.resolve().parts):
        raise ValueError("paired dominance-cost probe output must remain in a provisional namespace")
    _validate_publish_payload(report, ledger)
    result_sha256 = str(report["result_sha256"])
    report_without_hash = {key: value for key, value in report.items() if key != "result_sha256"}
    expected_result_sha256 = canonical_json_sha256({"report": report_without_hash, "ledger": ledger})
    if result_sha256 != expected_result_sha256:
        raise ValueError("paired dominance-cost probe result hash disagrees with its payload")
    generation = output_root / "generations" / result_sha256
    report_bytes = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    ledger_bytes = b"".join((json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode() for record in ledger)
    payloads = {"report.json": report_bytes, "admissibility.jsonl": ledger_bytes}
    pointer_path = output_root / "current.json"
    with serialized_output_install(pointer_path):
        generation.mkdir(parents=True, exist_ok=True)
        for filename, payload in payloads.items():
            target = generation / filename
            if target.exists() and target.read_bytes() != payload:
                raise RuntimeError(f"existing provisional probe generation disagrees: {filename}")
            if not target.exists():
                with atomic_output(target) as temporary:
                    temporary.write_bytes(payload)
        pointer = {
            "schema_version": PROBE_SCHEMA_VERSION,
            "kind": "provisional_dominance_cost_pair_probe",
            "result_sha256": result_sha256,
            "files": {filename: file_sha256(generation / filename) for filename in sorted(payloads)},
        }
        with atomic_output(pointer_path) as temporary:
            temporary.write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pointer

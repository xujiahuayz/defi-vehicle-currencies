#!/usr/bin/env python3
"""Run the provisional ETH-move route-reallocation experiment.

Daily moves come from a retained, independently corroborated off-chain source.
There is no locally validated independent hourly ETH series, so this owner does
not estimate an hourly price-dose response.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
from typing import Iterator, Mapping, Sequence

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from ddvc.analysis.stress_reallocation_e0 import (
    CALENDAR_PROTOCOL_REGIMES,
    StressDesign,
    compare_daily_reference_sources,
    conditional_role_composition,
    decompose_event,
    direction_comparability_diagnostic,
    exact_hourly_choices,
    fit_direction_fixed_effects,
    fixed_support_panel,
    prepare_etherscan_daily_reference,
    select_reference_events,
    summarize_event_estimates,
)
from ddvc.artifact_release import (
    bind_file_lineage,
    current_file_lineage,
    file_sha256,
    file_stat_identity,
)
from ddvc.endpoint_candidate_composition import (
    ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES,
    ROUTE_INPUT_COLUMNS,
)
from ddvc.endpoint_candidate_composition_release import (
    EndpointCandidateCompositionRelease,
    current_endpoint_candidate_composition_release,
)
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.provenance import current_artifacts, sidecar_path, stamp
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL, unified_path, unified_quality_path
from ddvc.tables import read_exhibit, write_exhibit, write_panel


OUTPUT_ROOT = REPO_ROOT / "output" / "provisional"
SUMMARY = OUTPUT_ROOT / "stress_reallocation_e0.jsonl"
EVENT_OUTPUT = OUTPUT_ROOT / "stress_reallocation_e0_events.parquet"
HOURLY_OUTPUT = OUTPUT_ROOT / "stress_reallocation_e0_hourly.parquet"
SELECTION_EXCLUSIONS = OUTPUT_ROOT / "stress_reallocation_e0_event_exclusions.jsonl"
SOURCE_AUDIT = OUTPUT_ROOT / "stress_reallocation_e0_source_audit.jsonl"
MANIFEST = OUTPUT_ROOT / "stress_reallocation_e0_manifest.json"

COMPOSITION_POINTER = (
    DATA_DIR / "processed" / "endpoint_candidate_composition_release" / "current.json"
)
SCRIPT_VERSION = "stress_reallocation_e0.v4"
SUMMARIZE_ONLY_MODE = "package_replay_not_raw_input_rebuild"
CODE_SOURCES = sorted(
    {
        "scripts/run_stress_reallocation_e0.py",
        "src/ddvc/analysis/stress_reallocation_e0.py",
        "src/ddvc/analysis/regression.py",
        "src/ddvc/artifact_release.py",
        "src/ddvc/endpoint_candidate_composition_release.py",
        "src/ddvc/reconstruct.py",
        *ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES,
    }
)


def resolve_price_inputs(
    price_source: Path | None,
    comparator: Path | None,
    comparator_raw: Path | None,
) -> tuple[Path, Path, Path]:
    """Resolve explicit portable price inputs or fail before starting a run."""

    values = {
        "--price-source": price_source,
        "--price-comparator": comparator,
        "--price-comparator-raw": comparator_raw,
    }
    missing = [option for option, value in values.items() if value is None]
    if missing:
        raise ValueError(
            "stress E0 has no machine-specific price defaults; provide explicit "
            + ", ".join(missing)
        )
    resolved = tuple(Path(value).resolve() for value in values.values() if value is not None)
    absent = [str(path) for path in resolved if not path.is_file()]
    if absent:
        raise FileNotFoundError(
            "stress E0 explicit price input is missing: " + ", ".join(absent)
        )
    assert len(resolved) == 3
    return resolved


@contextmanager
def current_stress_files(paths: Sequence[Path]) -> Iterator[tuple[Path, ...]]:
    """Continuously lease unstamped direct files through their complete use."""

    selected = tuple(dict.fromkeys(Path(path) for path in paths))
    lease = bind_file_lineage(selected)
    with current_file_lineage(lease):
        yield selected


@contextmanager
def current_stress_composition_release(
    pointer_path: Path = COMPOSITION_POINTER,
) -> Iterator[EndpointCandidateCompositionRelease]:
    """Lease the canonical typed release with its current semantic receipt."""

    with current_endpoint_candidate_composition_release(pointer_path) as release:
        yield release


def _record_path(path: Path) -> str:
    resolved = path.resolve()
    return (
        str(resolved.relative_to(REPO_ROOT))
        if resolved.is_relative_to(REPO_ROOT)
        else str(resolved)
    )


def _hash_record(path: Path, *, role: str) -> dict[str, object]:
    return {
        "role": role,
        "path": _record_path(path),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _resolve_record_path(record: dict[str, object]) -> Path:
    path = Path(str(record["path"]))
    return path if path.is_absolute() else REPO_ROOT / path


def _strict_json_load(path: Path) -> dict[str, object]:
    """Read an object while rejecting JavaScript non-finite number extensions."""

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant is forbidden: {value}")

    payload = json.loads(
        path.read_text(encoding="utf-8"), parse_constant=reject_constant
    )
    if not isinstance(payload, dict):
        raise ValueError(f"stress E0 JSON object expected: {path}")
    return payload


def _json_compatible(value: object) -> object:
    """Recursively replace missing/non-finite scalars with strict JSON null."""

    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, np.generic):
        return _json_compatible(value.item())
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if value is pd.NA or value is pd.NaT or value is None:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _strict_json_bytes(value: Mapping[str, object]) -> bytes:
    sanitized = _json_compatible(value)
    return (
        json.dumps(
            sanitized,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def verify_hash_records(records: list[dict[str, object]]) -> None:
    """Fail closed when any bound source, route byte, marker, or code changes."""

    for record in records:
        path = _resolve_record_path(record)
        if (
            not path.is_file()
            or path.stat().st_size != int(record["bytes"])
            or file_sha256(path) != record["sha256"]
        ):
            raise RuntimeError(
                f"stress E0 bound {record.get('role', 'file')} changed: {path}"
            )


def _bind_route_days(days: list[str]) -> tuple[list[dict[str, object]], pd.DataFrame]:
    """Bind selected local route partitions and their exact release markers."""

    before = file_stat_identity(UNIFIED_QUALITY_PANEL)
    ledger_sha = file_sha256(UNIFIED_QUALITY_PANEL)
    quality = pd.read_parquet(UNIFIED_QUALITY_PANEL)
    if (
        before != file_stat_identity(UNIFIED_QUALITY_PANEL)
        or ledger_sha != file_sha256(UNIFIED_QUALITY_PANEL)
    ):
        raise RuntimeError("route-quality ledger mutated during stress binding")
    quality["day"] = (
        quality["day"].astype(str).str.replace("-", "", regex=False).str.zfill(8)
    )
    if quality["day"].duplicated().any():
        raise RuntimeError("route-quality ledger duplicates a calendar day")
    indexed = quality.set_index("day")
    missing = sorted(set(days) - set(indexed.index))
    if missing:
        raise RuntimeError(f"route-quality ledger omits stress days: {missing[:3]}")

    records: list[dict[str, object]] = [
        {
            "role": "route_quality_ledger",
            "path": _record_path(UNIFIED_QUALITY_PANEL),
            "bytes": UNIFIED_QUALITY_PANEL.stat().st_size,
            "sha256": ledger_sha,
        }
    ]
    for day in days:
        row = indexed.loc[day]
        if not bool(row["passed"]):
            raise RuntimeError(f"route-quality ledger did not pass stress day {day}")
        path = unified_path(day)
        marker_path = unified_quality_path(day)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        expected = {
            "rows": int(row["output_rows"]),
            "bytes": int(row["output_bytes"]),
            "sha256": str(row["output_sha256"]),
            "input_fingerprint": str(row["input_fingerprint"]),
        }
        marker_rows = marker.get("output_rows", marker.get("canonical_rows"))
        if not (
            str(marker.get("day")).replace("-", "") == day
            and int(marker_rows) == expected["rows"]
            and int(marker.get("output_bytes")) == expected["bytes"]
            and marker.get("output_sha256") == expected["sha256"]
            and marker.get("input_fingerprint") == expected["input_fingerprint"]
            and marker.get("passed") is True
        ):
            raise RuntimeError(f"route marker disagrees with ledger on {day}")
        if (
            path.stat().st_size != expected["bytes"]
            or file_sha256(path) != expected["sha256"]
        ):
            raise RuntimeError(f"route bytes disagree with ledger on {day}")
        records.extend(
            [
                {
                    "role": "route_partition",
                    "day": day,
                    "path": _record_path(path),
                    "rows": expected["rows"],
                    "bytes": expected["bytes"],
                    "sha256": expected["sha256"],
                    "input_fingerprint": expected["input_fingerprint"],
                },
                {
                    **_hash_record(marker_path, role="route_partition_marker"),
                    "day": day,
                },
            ]
        )
    return records, quality


def _composition_release_record(
    release: EndpointCandidateCompositionRelease,
) -> dict[str, object]:
    """Serialize only identities admitted by the canonical typed resolver."""

    bundle = release.bundle
    receipt = bundle.semantic_receipt
    if receipt is None or receipt.generation_id != release.generation_id:
        raise RuntimeError("stress E0 composition release lacks a current semantic receipt")
    return {
        **_hash_record(bundle.pointer_path, role="composition_release_pointer"),
        "generation_id": release.generation_id,
        "semantic_validator_fingerprint": receipt.validator_fingerprint,
        "artifact_sha256": dict(sorted(bundle.artifact_sha256.items())),
        "provenance_sha256": dict(sorted(bundle.provenance_sha256.items())),
    }


def _event_results(
    hourly: pd.DataFrame,
    roles: dict[tuple[str, str], dict[str, float]],
    design: StressDesign,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event, panel in hourly.groupby("event", sort=True):
        metadata = panel.iloc[0]
        for measure in ("route_count", "within_20pct_value_usd"):
            for threshold in design.all_support_thresholds:
                row = decompose_event(
                    panel, measure, minimum_pre_hours=threshold
                )
                row.update(
                    {
                        "event": event,
                        "event_type": metadata["event_type"],
                        "event_hour_utc": pd.to_datetime(
                            int(metadata["event_hour"]) * 3600,
                            unit="s",
                            utc=True,
                        ).isoformat(),
                        "daily_log_return": float(metadata["daily_log_return"]),
                        "shock_magnitude": abs(float(metadata["daily_log_return"])),
                        "status": "provisional_e0",
                        "claim_gate": "red",
                        "promotion_eligible": False,
                        "diagnostic_scope": (
                            "conditional_broader_route_composition"
                            if threshold == design.minimum_pre_hours
                            else "not_applicable_support_sensitivity"
                        ),
                    }
                )
                if threshold == design.minimum_pre_hours:
                    row.update(roles[(event, measure)])
                rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["event", "measure", "minimum_pre_hours"]
    ).reset_index(drop=True)


def _holm_adjust(p_values: pd.Series) -> pd.Series:
    """Holm-adjust one displayed family."""

    adjusted = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = p_values.dropna().sort_values()
    running = 0.0
    count = len(valid)
    for rank, (index, value) in enumerate(valid.items()):
        running = max(running, min(1.0, (count - rank) * float(value)))
        adjusted.loc[index] = running
    return adjusted


def _summary(
    event_results: pd.DataFrame,
    hourly: pd.DataFrame,
    design: StressDesign,
) -> pd.DataFrame:
    event_summary = summarize_event_estimates(
        event_results, repetitions=design.randomization_repetitions
    )
    comparability, matched_events = direction_comparability_diagnostic(hourly)
    fixed_effect_records: list[dict[str, object]] = []
    for threshold in design.all_support_thresholds:
        for measure in ("route_count", "within_20pct_value_usd"):
            fixed_effect_records.append(
                fit_direction_fixed_effects(
                    hourly,
                    measure,
                    minimum_pre_hours=threshold,
                    randomization_repetitions=design.randomization_repetitions,
                )
            )
    if bool(comparability["matching_eligible"]):
        matched = hourly.loc[hourly["event"].isin(matched_events)]
        for measure in ("route_count", "within_20pct_value_usd"):
            fixed_effect_records.append(
                fit_direction_fixed_effects(
                    matched,
                    measure,
                    minimum_pre_hours=design.minimum_pre_hours,
                    specification="regime_magnitude_matched",
                    randomization_repetitions=design.randomization_repetitions,
                )
            )
    fixed_effect_rows = pd.DataFrame(fixed_effect_records)
    fixed_effect_rows["wild_p_holm_exploratory_family"] = _holm_adjust(
        fixed_effect_rows["wild_sign_flip_p_value"]
    )
    fixed_effect_rows["multiplicity_scope"] = (
        "all displayed direction-FE rows: two measures x three pre-support "
        "thresholds plus two matched diagnostics when support permits"
    )
    results = pd.concat(
        [event_summary, fixed_effect_rows, pd.DataFrame([comparability])],
        ignore_index=True,
        sort=False,
    )
    results["status"] = "provisional_e0"
    results["claim_gate"] = "red"
    results["promotion_eligible"] = False
    results["exploratory_family"] = (
        "event means: two directions x two measures x four additive margins with "
        "Holm adjustment across the 16 primary tests; direction FE: Holm adjustment "
        "across every displayed measure-by-support and matched row"
    )
    results["interpretation_boundary"] = (
        "realised NATIVE intermediary-share composition around ex-post selected "
        "independent-price moves on fixed pre-supported exact two-leg native-versus-"
        "stable routes; no feasible-route set, router preference, or causal shock "
        "effect; direction matching minimizes disclosed magnitude imbalance within "
        "coarse calendar/protocol regime"
    )
    return results.sort_values(
        ["row_type", "event_type", "measure", "minimum_pre_hours", "estimand"],
        na_position="last",
    ).reset_index(drop=True)


def _source_audit_frame(
    primary: pd.DataFrame,
    source_agreement: dict[str, object],
    raw_comparator_binding: dict[str, object],
    price_source: Path,
    comparator: Path,
    comparator_raw: Path,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_id": "etherscan_etherprice_chart_daily",
                "source_url": "https://etherscan.io/chart/etherprice?output=csv",
                "retained_path": str(price_source.resolve()),
                "retained_sha256": file_sha256(price_source),
                "frequency": "daily",
                "observation_start": primary["observation_date"].min().strftime(
                    "%Y-%m-%d"
                ),
                "observation_end": primary["observation_date"].max().strftime(
                    "%Y-%m-%d"
                ),
                "positive_consecutive_days": len(primary),
                "availability_convention": (
                    "observation for UTC date d becomes available at 00:00 UTC on d+1"
                ),
                "availability_limitation": (
                    "retrospective chart; convention prevents same-day route outcomes "
                    "from determining event selection but does not establish real-time publication latency"
                ),
                "comparator_source": "CoinGecko retained daily ETH series",
                "comparator_path": str(comparator.resolve()),
                "comparator_sha256": file_sha256(comparator),
                "comparator_raw_path": str(comparator_raw.resolve()),
                "comparator_raw_sha256": file_sha256(comparator_raw),
                "independent_validation_scope": (
                    f"CoinGecko agreement covers only {source_agreement['overlap_start']} "
                    f"through {source_agreement['overlap_end']}; it does not independently "
                    "validate the full 2020--2026 event-selection history"
                ),
                **raw_comparator_binding,
                **source_agreement,
            }
        ]
    )


def verify_coingecko_raw_comparator(
    raw_path: Path, comparator_path: Path
) -> dict[str, object]:
    """Bind the raw CoinGecko payload and verify the retained derived rows."""

    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    prices = pd.DataFrame(payload.get("prices", []), columns=["ts", "raw_price"])
    market_caps = pd.DataFrame(
        payload.get("market_caps", []), columns=["ts", "raw_market_cap"]
    )
    if prices.empty or market_caps.empty:
        raise RuntimeError("raw CoinGecko ETH payload lacks prices or market caps")
    raw = prices.merge(market_caps, on="ts", how="outer").sort_values("ts")
    raw["date"] = (
        pd.to_datetime(raw["ts"], unit="ms", utc=True)
        .dt.tz_localize(None)
        .dt.floor("D")
    )
    raw = raw.groupby("date", as_index=False).first()
    comparator = pd.read_parquet(comparator_path).copy()
    comparator["date"] = pd.to_datetime(comparator["date"]).dt.normalize()
    joined = comparator.merge(raw, on="date", how="left", validate="one_to_one")
    if joined[["raw_price", "raw_market_cap"]].isna().any().any():
        raise RuntimeError("derived CoinGecko comparator is not covered by raw payload")
    price_gap = (
        joined["eth_price_usd"] - joined["raw_price"]
    ).abs().max()
    cap_gap = (
        joined["eth_market_cap_usd"] - joined["raw_market_cap"]
    ).abs().max()
    if float(price_gap) > 1e-10 or float(cap_gap) > 1e-4:
        raise RuntimeError("derived CoinGecko comparator disagrees with raw payload")
    return {
        "raw_payload_price_points": len(prices),
        "raw_payload_market_cap_points": len(market_caps),
        "raw_payload_utc_days": raw["date"].nunique(),
        "derived_rows_verified_against_raw": len(joined),
        "derived_start_verified_against_raw": joined["date"].min().strftime(
            "%Y-%m-%d"
        ),
        "derived_end_verified_against_raw": joined["date"].max().strftime(
            "%Y-%m-%d"
        ),
        "maximum_price_difference_from_raw": float(price_gap),
        "maximum_market_cap_difference_from_raw": float(cap_gap),
    }


def _serialize_event_selection(frame: pd.DataFrame) -> list[dict[str, object]]:
    records = frame.copy()
    for column in records.columns:
        if pd.api.types.is_datetime64_any_dtype(records[column]):
            records[column] = records[column].dt.strftime("%Y-%m-%d")
    return records.replace({np.nan: None, pd.NaT: None}).to_dict("records")


def write_selection_exclusions(
    exclusions: pd.DataFrame,
    *,
    provenance_inputs: Sequence[Path],
    notes: str,
) -> Path:
    """Write exclusions with price and route support inputs on one perimeter."""

    return write_exhibit(
        exclusions,
        SELECTION_EXCLUSIONS,
        code_sources=CODE_SOURCES,
        inputs=list(provenance_inputs),
        notes=notes,
    )


def _manifest_inputs(manifest: dict[str, object]) -> list[dict[str, object]]:
    return [
        *manifest["source_inputs"],
        manifest["composition_release"],
        *manifest["route_inputs"],
        *manifest["code_inputs"],
    ]


def _manifest_package_records(
    manifest: dict[str, object],
) -> list[dict[str, object]]:
    """Return the non-code package perimeter anchored by manifest provenance."""

    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise RuntimeError("stress E0 manifest lacks output identities")
    return [
        *manifest["source_inputs"],
        manifest["composition_release"],
        *manifest["route_inputs"],
        *outputs,
    ]


def _identity_map(records: Sequence[Mapping[str, object]]) -> dict[Path, tuple[int, str]]:
    identities: dict[Path, tuple[int, str]] = {}
    for record in records:
        path = _resolve_record_path(dict(record)).resolve()
        identity = (int(record["bytes"]), str(record["sha256"]))
        if path in identities:
            raise RuntimeError(f"stress E0 identity perimeter repeats a path: {path}")
        identities[path] = identity
    return identities


def _verify_manifest_provenance_binding(
    manifest: dict[str, object],
    *,
    manifest_path: Path,
) -> None:
    """Bind manifest declarations to its independently verified sidecar."""

    provenance = _strict_json_load(sidecar_path(manifest_path))
    if provenance.get("code_sources") != sorted(CODE_SOURCES):
        raise RuntimeError("stress E0 manifest provenance has the wrong code perimeter")
    code_records = manifest.get("code_inputs")
    if not isinstance(code_records, list):
        raise RuntimeError("stress E0 manifest lacks code identities")
    recorded_code = {
        _resolve_record_path(record).resolve() for record in code_records
    }
    expected_code = {(REPO_ROOT / path).resolve() for path in CODE_SOURCES}
    if recorded_code != expected_code:
        raise RuntimeError("stress E0 manifest code identities disagree with provenance")
    sidecar_inputs = provenance.get("inputs")
    if not isinstance(sidecar_inputs, list):
        raise RuntimeError("stress E0 manifest provenance lacks package inputs")
    anchored = _identity_map(sidecar_inputs)
    declared = _identity_map(_manifest_package_records(manifest))
    if anchored != declared:
        raise RuntimeError(
            "stress E0 manifest package identities disagree with detached provenance"
        )


@contextmanager
def current_stress_manifest(
    manifest_path: Path = MANIFEST,
) -> Iterator[dict[str, object]]:
    """Authenticate and lease the manifest, sidecar, code, inputs, and outputs."""

    with current_artifacts(
        [manifest_path], consumer="stress reallocation E0 package replay"
    ):
        manifest = _strict_json_load(manifest_path)
        _verify_manifest_provenance_binding(manifest, manifest_path=manifest_path)
        yield manifest


def verify_manifest_state(
    manifest: dict[str, object],
    *,
    composition_release: EndpointCandidateCompositionRelease | None = None,
) -> None:
    """Reopen all inputs and reject changed derived hourly or event bytes."""

    if composition_release is None:
        with current_stress_composition_release() as release:
            verify_manifest_state(manifest, composition_release=release)
        return
    verify_hash_records(_manifest_inputs(manifest))
    recorded_composition = manifest["composition_release"]
    if not isinstance(recorded_composition, dict):
        raise RuntimeError("stress E0 manifest has an invalid composition identity")
    if composition_release.generation_id != recorded_composition.get("generation_id"):
        raise RuntimeError("stress E0 composition generation changed")
    current_composition = _composition_release_record(composition_release)
    if recorded_composition != current_composition:
        raise RuntimeError("stress E0 composition release identity changed")
    output_records = manifest.get("outputs")
    if not isinstance(output_records, list):
        raise RuntimeError("stress E0 manifest lacks output identities")
    expected_outputs = {
        path.resolve()
        for path in (
            SUMMARY,
            EVENT_OUTPUT,
            HOURLY_OUTPUT,
            SELECTION_EXCLUSIONS,
            SOURCE_AUDIT,
        )
    }
    recorded_outputs = {
        _resolve_record_path(record).resolve() for record in output_records
    }
    if recorded_outputs != expected_outputs:
        raise RuntimeError("stress E0 manifest has an incomplete output perimeter")
    verify_hash_records(output_records)


def summarize_only_boundary_record() -> dict[str, object]:
    """Describe exactly what package replay verifies and what it does not rebuild."""

    return {
        "mode": SUMMARIZE_ONLY_MODE,
        "raw_input_rebuild": False,
        "replayed_from_hash_bound_outputs": [
            _record_path(HOURLY_OUTPUT),
            _record_path(EVENT_OUTPUT),
            _record_path(SUMMARY),
        ],
        "boundary": (
            "verifies the immutable saved package and recomputes event summaries; "
            "does not reconstruct hourly choices or event selection from raw inputs"
        ),
    }


def summarize_only() -> int:
    with current_stress_manifest() as manifest, current_stress_composition_release() as release:
        verify_manifest_state(manifest, composition_release=release)
        design = StressDesign(**manifest["design"])
        hourly = pd.read_parquet(HOURLY_OUTPUT)
        recorded_events = pd.read_parquet(EVENT_OUTPUT)
        role_columns = [
            "broad_intermediary_native_share_pre",
            "broad_intermediary_native_share_post",
            "broad_intermediary_native_share_change",
            "endpoint_native_share_pre",
            "endpoint_native_share_post",
            "endpoint_native_share_change",
            "intermediary_minus_endpoint_change",
        ]
        missing_roles = sorted(set(role_columns) - set(recorded_events.columns))
        if missing_roles:
            raise RuntimeError(
                "hash-bound stress event package lacks replay columns: "
                + ", ".join(missing_roles)
            )
        primary = recorded_events.loc[
            recorded_events["minimum_pre_hours"].eq(design.minimum_pre_hours)
        ]
        roles = {
            (row.event, row.measure): {
                column: getattr(row, column) for column in role_columns
            }
            for row in primary.itertuples(index=False)
        }
        recomputed_events = _event_results(hourly, roles, design)
        assert_frame_equal(
            recorded_events.reset_index(drop=True),
            recomputed_events.reset_index(drop=True),
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
        recomputed_summary = _summary(recomputed_events, hourly, design)
        recorded_summary = read_exhibit(SUMMARY)
        assert_frame_equal(
            recorded_summary.loc[:, recomputed_summary.columns].reset_index(drop=True),
            recomputed_summary.reset_index(drop=True),
            check_dtype=False,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
    print(json.dumps(summarize_only_boundary_record(), sort_keys=True))
    print(recomputed_summary.to_string(index=False))
    return 0


def _run_under_leases(
    design: StressDesign,
    *,
    price_source: Path,
    comparator: Path,
    comparator_raw: Path,
    stack: ExitStack,
    composition_release: EndpointCandidateCompositionRelease,
) -> int:
    primary = prepare_etherscan_daily_reference(pd.read_csv(price_source))
    agreement = compare_daily_reference_sources(
        primary, pd.read_parquet(comparator)
    )
    raw_comparator_binding = verify_coingecko_raw_comparator(
        comparator_raw, comparator
    )
    route_calendar = pd.read_parquet(UNIFIED_QUALITY_PANEL, columns=["day"])["day"]
    route_calendar = pd.to_datetime(
        route_calendar.astype(str).str.replace("-", "", regex=False),
        format="%Y%m%d",
        errors="raise",
    )
    sample_start = route_calendar.min()
    sample_end = min(
        primary["observation_date"].max(),
        route_calendar.max() - pd.Timedelta(days=1),
    )
    events, exclusions = select_reference_events(
        primary,
        design,
        sample_start=sample_start.strftime("%Y-%m-%d"),
        sample_end=sample_end.strftime("%Y-%m-%d"),
    )
    needed = sorted(
        {
            day.strftime("%Y%m%d")
            for date in events["observation_date"]
            for day in (date, date + pd.Timedelta(days=1))
        }
    )
    direct_route_inputs = [
        path
        for day in needed
        for path in (unified_path(day), unified_quality_path(day))
    ]
    stack.enter_context(current_stress_files(direct_route_inputs))
    route_records, _quality = _bind_route_days(needed)
    composition_record = _composition_release_record(composition_release)

    daily_choices: dict[str, pd.DataFrame] = {}
    for index, day in enumerate(needed, 1):
        legs = pd.read_parquet(unified_path(day), columns=ROUTE_INPUT_COLUMNS)
        daily_choices[day] = exact_hourly_choices(legs, day)
        print(f"stress reallocation [{index}/{len(needed)}] {day}", flush=True)
    verify_hash_records(route_records)

    panels: list[pd.DataFrame] = []
    roles: dict[tuple[str, str], dict[str, float]] = {}
    unsupported: list[dict[str, object]] = []
    for selected in events.itertuples(index=False):
        event_date = pd.Timestamp(selected.observation_date)
        event = event_date.strftime("%Y-%m-%d")
        days = [
            event_date.strftime("%Y%m%d"),
            (event_date + pd.Timedelta(days=1)).strftime("%Y%m%d"),
        ]
        choices = pd.concat([daily_choices[day] for day in days], ignore_index=True)
        panel = fixed_support_panel(
            choices,
            event=event,
            event_type=selected.event_type,
            event_hour=int(selected.event_hour),
            daily_log_return=float(selected.daily_log_return),
            design=design,
        )
        if panel.empty:
            unsupported.append(
                {
                    "observation_date": event_date,
                    "event_type": selected.event_type,
                    "daily_log_return": selected.daily_log_return,
                    "reason": "no_pre_supported_ordered_pairs",
                    "collision_reference_date": pd.NaT,
                    "calendar_distance_days": np.nan,
                    "collision_distance_rule_days": design.cluster_gap_days,
                    "selection_rule": "route_support_after_price_event_selection",
                }
            )
            continue
        panels.append(panel)
        for measure in ("route_count", "within_20pct_value_usd"):
            roles[(event, measure)] = conditional_role_composition(
                choices,
                event_hour=int(selected.event_hour),
                measure=measure,
                design=design,
            )
    if not panels:
        raise RuntimeError("no independently selected ETH event has route support")
    hourly = pd.concat(panels, ignore_index=True).sort_values(
        ["event", "pair", "hour", "candidate_type", "candidate_symbol"]
    ).reset_index(drop=True)
    event_results = _event_results(hourly, roles, design)
    results = _summary(event_results, hourly, design)
    if unsupported:
        exclusions = pd.concat([exclusions, pd.DataFrame(unsupported)], ignore_index=True)
    source_audit = _source_audit_frame(
        primary,
        agreement,
        raw_comparator_binding,
        price_source,
        comparator,
        comparator_raw,
    )

    source_records = [
        _hash_record(price_source, role="daily_eth_price_source"),
        _hash_record(comparator, role="daily_eth_price_comparator"),
        _hash_record(
            comparator_raw, role="daily_eth_price_comparator_raw_payload"
        ),
    ]
    code_records = [
        _hash_record(REPO_ROOT / path, role="code") for path in CODE_SOURCES
    ]
    provenance_inputs = [
        *(_resolve_record_path(record) for record in source_records),
        COMPOSITION_POINTER,
        *(_resolve_record_path(record) for record in route_records),
    ]
    notes = json.dumps(
        {
            "status": "provisional_e0",
            "claim_gate": "red",
            "promotion_eligible": False,
            "price_source": "independent daily; hourly dose-response retired",
            "route_release": "exact local selected partitions bound while full J0 gate is red",
        },
        sort_keys=True,
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_panel(
        hourly,
        HOURLY_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=provenance_inputs,
        notes=notes,
    )
    write_panel(
        event_results,
        EVENT_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=provenance_inputs,
        notes=notes,
    )
    write_exhibit(
        results,
        SUMMARY,
        code_sources=CODE_SOURCES,
        inputs=provenance_inputs,
        notes=notes,
    )
    write_selection_exclusions(
        exclusions,
        provenance_inputs=provenance_inputs,
        notes=notes,
    )
    write_exhibit(
        source_audit,
        SOURCE_AUDIT,
        code_sources=CODE_SOURCES,
        inputs=[price_source, comparator, comparator_raw],
        notes=notes,
    )

    manifest = {
        "package": "stress_reallocation_e0",
        "script_version": SCRIPT_VERSION,
        "status": "provisional_e0",
        "claim_gate": "red",
        "promotion_eligible": False,
        "summarize_only_mode": SUMMARIZE_ONLY_MODE,
        "summarize_only_raw_input_rebuild": False,
        "hourly_price_dose_response": "retired_no_validated_independent_hourly_source",
        "economic_unit": (
            "ordered source-destination pair with both native and stable intermediary "
            "use before an independently measured daily ETH move"
        ),
        "estimand": (
            "change in native intermediary share over 24 hours before versus after "
            "the daily price becomes available, decomposed into pair exit, continuing-pair "
            "activity reallocation, and continuing-pair intermediary substitution"
        ),
        "comparison": (
            "drawdowns and rallies selected by the identical threshold and direct "
            "magnitude-priority plus-or-minus-14-calendar-day spacing rule"
        ),
        "intermediary_share_definition": (
            "NATIVE intermediary routes divided by NATIVE-plus-stable intermediary "
            "routes within each ordered source-destination pair"
        ),
        "fixed_pair_population": (
            "exact two-leg native-versus-stable ordered pairs supported in the pre-event "
            "window; pairs appearing only after the event do not enter"
        ),
        "strict_value_measure": (
            "within_20pct_value_usd retains routes only when source, intermediary, and "
            "destination dollar values agree within 20 percent"
        ),
        "decomposition_order": (
            "sequential exact identity: pair exit, activity reweighting among surviving "
            "pairs, then within-pair intermediary substitution"
        ),
        "uncertainty_boundary": (
            "an imprecisely estimated average is not evidence of no effect; estimates, "
            "uncertainty, and multiplicity-adjusted inference are reported separately"
        ),
        "inference": (
            "event-level t, exact sign, wild sign-flip t, and Holm adjustment across "
            "the 16 primary exploratory tests; event-cluster score sign-flip and Holm "
            "adjustment across all displayed FE measure-by-support and matched diagnostics"
        ),
        "strongest_rival": (
            "selected market-wide events coincide with changing route opportunities and "
            "market composition; realised routes do not reveal feasible alternatives"
        ),
        "conditional_composition_diagnostic": (
            "broader intermediary-versus-endpoint changes are reported only as composition, "
            "not as fixed-pair role separation"
        ),
        "design": {
            **design.__dict__,
            "support_sensitivity_hours": list(design.support_sensitivity_hours),
        },
        "source_inputs": source_records,
        "source_agreement": agreement,
        "source_agreement_boundary": (
            f"CoinGecko validates Etherscan only from {agreement['overlap_start']} "
            f"through {agreement['overlap_end']}; earlier selected events are not "
            "covered by the independent comparator"
        ),
        "raw_comparator_binding": raw_comparator_binding,
        "calendar_protocol_regimes": [
            {
                "name": name,
                "start": start.strftime("%Y-%m-%d") if start is not None else None,
                "end_exclusive": end.strftime("%Y-%m-%d") if end is not None else None,
            }
            for name, start, end in CALENDAR_PROTOCOL_REGIMES
        ],
        "direction_comparability": direction_comparability_diagnostic(hourly)[0],
        "composition_release": composition_record,
        "route_release_status": "provisional_exact_local_subset_full_J0_gate_red",
        "route_inputs": route_records,
        "code_inputs": code_records,
        "selected_events": _serialize_event_selection(events),
        "selection_exclusions": _serialize_event_selection(exclusions),
        "outputs": [
            _hash_record(path, role="derived_output")
            for path in (
                SUMMARY,
                EVENT_OUTPUT,
                HOURLY_OUTPUT,
                SELECTION_EXCLUSIONS,
                SOURCE_AUDIT,
            )
        ],
    }
    sanitized_manifest = _json_compatible(manifest)
    if not isinstance(sanitized_manifest, dict):  # pragma: no cover - structural
        raise RuntimeError("stress E0 manifest sanitizer changed the object perimeter")
    manifest = sanitized_manifest
    temporary = MANIFEST.with_name(f".{MANIFEST.name}.tmp")
    temporary.write_bytes(_strict_json_bytes(manifest))
    temporary.replace(MANIFEST)
    stamp(
        MANIFEST,
        code_sources=CODE_SOURCES,
        inputs=[*provenance_inputs, SUMMARY, EVENT_OUTPUT, HOURLY_OUTPUT, SELECTION_EXCLUSIONS, SOURCE_AUDIT],
        notes=notes,
        script="scripts/run_stress_reallocation_e0.py",
    )
    verify_manifest_state(manifest, composition_release=composition_release)
    print(results.to_string(index=False))
    return 0


def run(
    design: StressDesign,
    *,
    price_source: Path,
    comparator: Path,
    comparator_raw: Path,
) -> int:
    """Run one package while every direct input remains continuously leased."""

    with ExitStack() as stack:
        stack.enter_context(
            current_stress_files(
                tuple(REPO_ROOT / relative for relative in CODE_SOURCES)
            )
        )
        stack.enter_context(
            current_stress_files((price_source, comparator, comparator_raw))
        )
        stack.enter_context(
            current_artifacts(
                [UNIFIED_QUALITY_PANEL],
                consumer="stress reallocation E0 route-quality ledger",
            )
        )
        composition_release = stack.enter_context(
            current_stress_composition_release()
        )
        return _run_under_leases(
            design,
            price_source=price_source,
            comparator=comparator,
            comparator_raw=comparator_raw,
            stack=stack,
            composition_release=composition_release,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-per-direction", type=int, default=20)
    parser.add_argument("--randomization-repetitions", type=int, default=49_999)
    parser.add_argument("--price-source", type=Path)
    parser.add_argument("--price-comparator", type=Path)
    parser.add_argument(
        "--price-comparator-raw",
        type=Path,
    )
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    if args.summarize_only:
        return summarize_only()
    try:
        price_source, comparator, comparator_raw = resolve_price_inputs(
            args.price_source,
            args.price_comparator,
            args.price_comparator_raw,
        )
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    design = StressDesign(
        event_count_per_direction=args.events_per_direction,
        randomization_repetitions=args.randomization_repetitions,
    )
    return run(
        design,
        price_source=price_source,
        comparator=comparator,
        comparator_raw=comparator_raw,
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Canonical external WETH/USD panel construction and release validation."""

from __future__ import annotations

import heapq
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ddvc.asset_types import WETH
from ddvc.fetch.coinbase_prices import (
    INTERVAL_SECONDS,
    MAX_CANDLES_PER_REQUEST,
    RAW_SCHEMA_VERSION,
    SAMPLE_END_UTC_EXCLUSIVE,
    SAMPLE_START_UTC,
    SOURCE_ID,
    AnnualEvidencePaths,
    CandleRequest,
    annual_evidence_paths,
    annual_perimeters,
    fetch_candle_request,
    fetch_raw_file,
    fetch_source_identity,
    iter_raw_records,
    plan_candle_requests,
    validate_response_body,
    validate_source_identity_body,
    validate_source_identity_file,
)
from ddvc.paths import REPO_ROOT
from ddvc.runtime import atomic_output
from ddvc.tables import write_panel_batches


PANEL_COLUMNS = [
    "bucket_start_utc",
    "bucket_end_utc",
    "available_at_utc",
    "weth_usd",
    "onchain_asset_address",
    "price_source",
    "validation_status",
    "raw_evidence_path",
    "raw_response_sha256",
]


def _portable_evidence_path(path: Path) -> str:
    resolved = path.resolve()
    root = REPO_ROOT.resolve()
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else str(path)


def _ordered_candle_streams(paths: list[Path], *, start_utc: int, end_utc_exclusive: int):
    """Merge exact candles by bucket, including nested retained gap requests."""

    def stream(path: Path):
        evidence_path = _portable_evidence_path(path)
        for record in iter_raw_records(path, require_sorted=True):
            request = record["request"]
            request_spec = CandleRequest(request["start_utc"], request["end_utc_exclusive"])
            rows = validate_response_body(record["response_body"], request_spec)
            for raw in sorted(rows, key=lambda row: row[0]):
                bucket_start = int(raw[0])
                if start_utc <= bucket_start < end_utc_exclusive:
                    yield bucket_start, evidence_path, str(record["response_sha256"]), raw

    return heapq.merge(*(stream(path) for path in paths))


def _bounded_gap_requests(start_utc: int, end_utc_exclusive: int):
    maximum_span = MAX_CANDLES_PER_REQUEST * INTERVAL_SECONDS
    cursor = start_utc
    while cursor < end_utc_exclusive:
        request_end = min(cursor + maximum_span, end_utc_exclusive)
        yield CandleRequest(cursor, request_end)
        cursor = request_end


def missing_candle_requests(paths: list[Path], *, start_utc: int, end_utc_exclusive: int):
    """Stream bounded requests for unresolved minutes without a sample-length set."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    cursor = perimeter.start_utc
    for bucket_start, _path, _digest, _raw in _ordered_candle_streams(paths, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive):
        if bucket_start < cursor:
            raise ValueError("external-price evidence duplicates or reorders a candle")
        if bucket_start > cursor:
            yield from _bounded_gap_requests(cursor, bucket_start)
        cursor = bucket_start + INTERVAL_SECONDS
    if cursor < perimeter.end_utc_exclusive:
        yield from _bounded_gap_requests(cursor, perimeter.end_utc_exclusive)


def gap_audit_record(base_path: Path, reconciliation_path: Path, *, start_utc: int, end_utc_exclusive: int) -> dict[str, object]:
    """Reopen first-pass and retained gap responses and report unresolved minutes."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    sentinel = object()
    base_missing = 0
    gap_request_count = 0
    base_gaps = missing_candle_requests([base_path], start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive)
    for expected, observed in itertools.zip_longest(base_gaps, iter_raw_records(reconciliation_path, require_sorted=True), fillvalue=sentinel):
        if expected is sentinel or observed is sentinel or expected.identity != observed["request_identity"]:
            raise ValueError("external-price gap evidence does not match the first-pass gaps")
        base_missing += (expected.end_utc_exclusive - expected.start_utc) // INTERVAL_SECONDS
        gap_request_count += 1
    unresolved = missing_candle_requests([base_path, reconciliation_path], start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive)
    unresolved_minutes = 0
    unresolved_request_count = 0
    for request in unresolved:
        unresolved_minutes += (request.end_utc_exclusive - request.start_utc) // INTERVAL_SECONDS
        unresolved_request_count += 1
    return {
        "schema_version": RAW_SCHEMA_VERSION,
        "source_id": SOURCE_ID,
        "start_utc": perimeter.start_utc,
        "end_utc_exclusive": perimeter.end_utc_exclusive,
        "first_pass_missing_minutes": base_missing,
        "gap_request_count": gap_request_count,
        "recovered_minutes": base_missing - unresolved_minutes,
        "unresolved_minutes": unresolved_minutes,
        "unresolved_request_count": unresolved_request_count,
        "gap_policy": "retained_exact_requery_no_fill",
    }


def write_gap_audit(path: Path, base_path: Path, reconciliation_path: Path, *, start_utc: int, end_utc_exclusive: int) -> Path:
    """Persist the exact gap-requery result as an immutable release input."""

    record = gap_audit_record(base_path, reconciliation_path, start_utc=start_utc, end_utc_exclusive=end_utc_exclusive)
    with atomic_output(path) as temporary:
        temporary.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_gap_audit(path: Path, base_path: Path, reconciliation_path: Path, *, start_utc: int, end_utc_exclusive: int) -> dict[str, object]:
    """Require the retained gap audit to reproduce exactly from both evidence passes."""

    recorded = json.loads(path.read_text(encoding="utf-8"))
    observed = gap_audit_record(base_path, reconciliation_path, start_utc=start_utc, end_utc_exclusive=end_utc_exclusive)
    if recorded != observed:
        raise ValueError("external-price retained gap audit is stale")
    return observed


def iter_panel_batches(paths: list[Path], *, start_utc: int, end_utc_exclusive: int, batch_rows: int = 100_000):
    """Yield bounded source-identified close batches without filling absent minutes."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    if batch_rows < 1:
        raise ValueError("external-price batch size must be positive")
    rows: list[dict[str, object]] = []
    previous_bucket: int | None = None
    for bucket_start, evidence_path, response_sha256, raw in _ordered_candle_streams(paths, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive):
        if previous_bucket is not None and bucket_start <= previous_bucket:
            raise ValueError("external-price evidence duplicates or reorders a candle")
        previous_bucket = bucket_start
        rows.append({"bucket_start_utc": bucket_start, "bucket_end_utc": bucket_start + INTERVAL_SECONDS, "available_at_utc": bucket_start + INTERVAL_SECONDS, "weth_usd": float(raw[4]), "onchain_asset_address": WETH, "price_source": SOURCE_ID, "validation_status": "valid", "raw_evidence_path": evidence_path, "raw_response_sha256": response_sha256})
        if len(rows) >= batch_rows:
            yield pd.DataFrame(rows, columns=PANEL_COLUMNS)
            rows = []
    if rows:
        yield pd.DataFrame(rows, columns=PANEL_COLUMNS)


def panel_from_raw_files(paths: list[Path], *, start_utc: int, end_utc_exclusive: int) -> pd.DataFrame:
    """Materialize a bounded panel in memory; production builds use streaming."""

    frames = list(iter_panel_batches(paths, start_utc=start_utc, end_utc_exclusive=end_utc_exclusive))
    if not frames:
        raise RuntimeError("external WETH/USD raw evidence contains no observations")
    return pd.concat(frames, ignore_index=True)


def _coverage_record(*, start_utc: int, end_utc_exclusive: int, observed: int, missing: int, first_missing: int | None, last_missing: int | None) -> dict[str, object]:
    expected = (end_utc_exclusive - start_utc) // INTERVAL_SECONDS
    return {"source_id": SOURCE_ID, "start_utc": start_utc, "end_utc_exclusive": end_utc_exclusive, "expected_minutes": expected, "observed_minutes": observed, "missing_minutes": missing, "coverage_share": observed / expected, "first_missing_utc": first_missing, "last_missing_utc": last_missing, "full_minute_lattice": missing == 0}


def write_panel_from_raw_files(paths: list[Path], output: Path, *, start_utc: int, end_utc_exclusive: int, code_sources: list[str] | None = None, inputs: list[str | Path] | None = None, provenance_notes: dict[str, object] | None = None, raw_root: Path | None = None) -> dict[str, object]:
    """Validate staged panel lineage before installing it with matching provenance."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    observed = missing = 0
    first_missing = last_missing = None
    cursor = perimeter.start_utc

    def audited_batches():
        nonlocal cursor, first_missing, last_missing, missing, observed
        for frame in iter_panel_batches(paths, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive):
            for value in frame["bucket_start_utc"].to_numpy(dtype="int64"):
                if value < cursor:
                    raise RuntimeError("external WETH/USD evidence is duplicated or out of order")
                if value > cursor:
                    missing += (value - cursor) // INTERVAL_SECONDS
                    first_missing = cursor if first_missing is None else first_missing
                    last_missing = value - INTERVAL_SECONDS
                cursor = value + INTERVAL_SECONDS
                observed += 1
            yield frame
        if cursor < perimeter.end_utc_exclusive:
            missing += (perimeter.end_utc_exclusive - cursor) // INTERVAL_SECONDS
            first_missing = cursor if first_missing is None else first_missing
            last_missing = perimeter.end_utc_exclusive - INTERVAL_SECONDS

    def coverage() -> dict[str, object]:
        return _coverage_record(start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive, observed=observed, missing=missing, first_missing=first_missing, last_missing=last_missing)

    def validate_staged(staged: Path) -> None:
        rows = (validate_external_weth_usd_content(staged, raw_root, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive)["rows"] if raw_root is not None else validate_panel_raw_lineage(staged, paths, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive))
        if rows != observed:
            raise ValueError("external WETH/USD staged row count differs from coverage audit")

    def notes() -> str:
        return json.dumps({**coverage(), **(provenance_notes or {})}, sort_keys=True)

    write_panel_batches(audited_batches(), output, code_sources=code_sources, inputs=inputs or paths, notes=notes, preinstall_validator=validate_staged)
    return coverage()


def coverage_summary(panel: pd.DataFrame, *, start_utc: int, end_utc_exclusive: int) -> dict[str, object]:
    """Return exact minute-lattice coverage without treating gaps as zero prices."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    expected = np.arange(perimeter.start_utc, perimeter.end_utc_exclusive, INTERVAL_SECONDS, dtype="int64")
    observed = panel["bucket_start_utc"].to_numpy(dtype="int64")
    missing = np.setdiff1d(expected, observed, assume_unique=True)
    return _coverage_record(start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive, observed=int(len(observed)), missing=int(len(missing)), first_missing=int(missing[0]) if len(missing) else None, last_missing=int(missing[-1]) if len(missing) else None)


def external_evidence_bundles(raw_root: Path, *, start_utc: int = SAMPLE_START_UTC, end_utc_exclusive: int = SAMPLE_END_UTC_EXCLUSIVE) -> tuple[Path, list[AnnualEvidencePaths]]:
    """Return the exact source identity and annual evidence bundles."""

    bundles = [annual_evidence_paths(raw_root, year) for _start, _end, year in annual_perimeters(start_utc, end_utc_exclusive)]
    return raw_root / "source_identity.json", bundles


def _lineage_identity(row: dict[str, object]) -> tuple[object, ...]:
    return (int(row["bucket_start_utc"]), int(row["bucket_end_utc"]), int(row["available_at_utc"]), float(row["weth_usd"]).hex(), str(row["onchain_asset_address"]), str(row["price_source"]), str(row["validation_status"]), str(row["raw_evidence_path"]), str(row["raw_response_sha256"]))


def validate_panel_raw_lineage(panel_path: Path, evidence_paths: list[Path], *, start_utc: int, end_utc_exclusive: int) -> int:
    """Compare staged or released panel rows with raw evidence without provenance."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    parquet = pq.ParquetFile(panel_path)
    missing_columns = sorted(set(PANEL_COLUMNS) - set(parquet.schema_arrow.names))
    if missing_columns:
        raise ValueError("external WETH/USD panel lacks release columns: " + ", ".join(missing_columns))

    def expected_rows():
        for frame in iter_panel_batches(evidence_paths, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive):
            yield from frame.to_dict("records")

    def actual_rows():
        for batch in parquet.iter_batches(columns=PANEL_COLUMNS, batch_size=100_000):
            yield from batch.to_pylist()

    sentinel = object()
    rows = 0
    for expected_row, actual_row in itertools.zip_longest(expected_rows(), actual_rows(), fillvalue=sentinel):
        if expected_row is sentinel or actual_row is sentinel:
            raise ValueError("external WETH/USD panel row perimeter differs from raw evidence")
        if _lineage_identity(expected_row) != _lineage_identity(actual_row):
            raise ValueError(f"external WETH/USD panel lineage differs at row {rows:,}")
        rows += 1
    return rows


def validate_external_weth_usd_content(panel_path: Path, raw_root: Path, *, start_utc: int = SAMPLE_START_UTC, end_utc_exclusive: int = SAMPLE_END_UTC_EXCLUSIVE) -> dict[str, object]:
    """Reopen source identity, audits, and raw lineage for staged or released bytes."""

    perimeter = CandleRequest(start_utc, end_utc_exclusive)
    identity_path, bundles = external_evidence_bundles(raw_root, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive)
    validate_source_identity_file(identity_path)
    evidence_paths: list[Path] = []
    audits: list[dict[str, object]] = []
    for (start, end, year), annual in zip(annual_perimeters(perimeter.start_utc, perimeter.end_utc_exclusive), bundles, strict=True):
        sentinel = object()
        for expected, observed in itertools.zip_longest(plan_candle_requests(start, end), iter_raw_records(annual.base, require_sorted=True), fillvalue=sentinel):
            if expected is sentinel or observed is sentinel or expected.identity != observed["request_identity"]:
                raise ValueError(f"external-price annual evidence perimeter differs for {year}")
        audits.append(validate_gap_audit(annual.audit, annual.base, annual.gaps, start_utc=start, end_utc_exclusive=end))
        evidence_paths.extend([annual.base, annual.gaps])
    rows = validate_panel_raw_lineage(panel_path, evidence_paths, start_utc=perimeter.start_utc, end_utc_exclusive=perimeter.end_utc_exclusive)
    unresolved = sum(int(audit["unresolved_minutes"]) for audit in audits)
    expected_minutes = (perimeter.end_utc_exclusive - perimeter.start_utc) // INTERVAL_SECONDS
    if rows + unresolved != expected_minutes:
        raise ValueError("external WETH/USD release coverage does not reconcile")
    return {"source_id": SOURCE_ID, "rows": rows, "expected_minutes": expected_minutes, "unresolved_minutes": unresolved, "coverage_share": rows / expected_minutes, "scope": "receipt_wei_to_usd_and_eth_usd_reference_only"}


def validate_external_weth_usd_release(panel_path: Path, raw_root: Path, *, start_utc: int = SAMPLE_START_UTC, end_utc_exclusive: int = SAMPLE_END_UTC_EXCLUSIVE) -> dict[str, object]:
    """Require current provenance and exact source lineage for the released panel."""

    from ddvc.provenance import require_current_artifacts

    require_current_artifacts([panel_path], consumer="external intraday WETH/USD release")
    return validate_external_weth_usd_content(panel_path, raw_root, start_utc=start_utc, end_utc_exclusive=end_utc_exclusive)

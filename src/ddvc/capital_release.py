"""Immutable marker-last release boundary for deposited-capital artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import json
from pathlib import Path
from typing import Mapping

import pyarrow.parquet as pq
import pyarrow as pa

from ddvc.artifact_release import ArtifactRelease, canonical_json_sha256, file_sha256, file_stat_identity, is_sha256, resolve_artifact_release
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.provenance import code_fingerprint
from ddvc.cp_state_stream import validate_certified_cp_stream_manifest


CAPITAL_RELEASE_POINTER = DATA_DIR / "processed" / "pool_capital_release" / "current.json"
CAPITAL_RELEASE_KIND = "pool_capital"
CAPITAL_RELEASE_SCHEMA_VERSION = 2
CAPITAL_RELEASE_FILENAMES = {
    "pool": "pool_capital_daily.parquet",
    "candidate": "pool_candidate_capital_daily.parquet",
    "rejection": "pool_capital_rejections.parquet",
    "overlap": "pool_capital_coverage.jsonl",
    "manifest": "pool_capital_generation.json",
}
CAPITAL_OVERLAP_ARTIFACT = "overlap"
CAPITAL_MANIFEST_ARTIFACT = "manifest"


def _resolve_record_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else REPO_ROOT / path


def record_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def exact_file_bindings(paths: tuple[Path, ...] | list[Path]) -> dict[str, str]:
    """Bind one nonempty, duplicate-free canonical scientific input set."""

    normalized = tuple(Path(path) for path in paths)
    if not normalized:
        raise ValueError("capital scientific input set must be nonempty")
    keys = tuple(record_path(path) for path in normalized)
    if len(keys) != len(set(keys)):
        raise ValueError("capital scientific input set contains duplicate paths")
    missing = [key for key, path in zip(keys, normalized, strict=True) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"capital scientific inputs are missing: {missing}")
    bindings: dict[str, str] = {}
    for key, path in zip(keys, normalized, strict=True):
        before = file_stat_identity(path)
        digest = file_sha256(path)
        if before != file_stat_identity(path):
            raise RuntimeError(f"capital scientific input mutated during hashing: {key}")
        bindings[key] = digest
    return bindings


def validate_exact_file_bindings(
    bindings: Mapping[str, str] | None,
    expected_paths: tuple[Path, ...] | list[Path],
) -> dict[str, str]:
    """Require the exact canonical path set and rehash every bound file."""

    if not bindings:
        raise ValueError("capital scientific input bindings are mandatory")
    expected = exact_file_bindings(expected_paths)
    observed = {str(path): str(digest) for path, digest in bindings.items()}
    if observed != expected:
        raise RuntimeError("capital scientific input bindings differ from the canonical set")
    return expected


@dataclass(frozen=True)
class CapitalRelease:
    """One resolved generation plus its internally consistent identity manifest."""

    bundle: ArtifactRelease
    manifest: Mapping[str, object]

    @property
    def generation_id(self) -> str:
        return self.bundle.generation_id

    @property
    def pointer_path(self) -> Path:
        return self.bundle.pointer_path

    @property
    def artifacts(self) -> Mapping[str, Path]:
        return self.bundle.artifacts

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        return self.bundle.artifact_paths

    @property
    def lineage_paths(self) -> tuple[Path, ...]:
        return self.bundle.lineage_paths


def validate_capital_generation_manifest(
    bundle: ArtifactRelease,
    manifest: Mapping[str, object],
    *,
    require_current_inputs: bool,
) -> None:
    """Validate identities that cannot be represented by a flat artifact pointer."""

    if (
        manifest.get("schema_version") != CAPITAL_RELEASE_SCHEMA_VERSION
        or manifest.get("kind") != CAPITAL_RELEASE_KIND
    ):
        raise ValueError("invalid capital generation manifest header")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(CAPITAL_RELEASE_FILENAMES) - {CAPITAL_MANIFEST_ARTIFACT}:
        raise ValueError("capital generation manifest has an invalid artifact perimeter")
    for name, record in artifacts.items():
        if (
            not isinstance(record, dict)
            or not is_sha256(record.get("sha256"))
            or file_sha256(bundle.artifacts[name]) != record["sha256"]
            or not isinstance(record.get("rows"), int)
            or int(record["rows"]) < 0
        ):
            raise ValueError(f"capital generation manifest artifact identity failed: {name}")
    shards = manifest.get("shards")
    if not isinstance(shards, list) or not shards:
        raise ValueError("capital generation manifest does not preserve shard identities")
    shard_ids: set[str] = set()
    for shard in shards:
        identity = shard.get("identity_sha256") if isinstance(shard, dict) else None
        shard_id = (shard.get("spec") or {}).get("shard_id") if isinstance(shard, dict) else None
        owned_days = (shard.get("spec") or {}).get("owned_days") if isinstance(shard, dict) else None
        support = shard.get("daily_support") if isinstance(shard, dict) else None
        shard_body = {key: value for key, value in shard.items() if key != "identity_sha256"} if isinstance(shard, dict) else {}
        support_valid = bool(
            isinstance(owned_days, list)
            and owned_days
            and all(isinstance(day, str) and day for day in owned_days)
            and len(owned_days) == len(set(owned_days))
            and isinstance(support, list)
            and all(isinstance(record, dict) for record in support)
            and [record.get("day") for record in support] == owned_days
            and all(
                record.get("status") in {"observed", "certified_empty", "certified_rows_none_admitted"}
                and isinstance(record.get("certified_source_rows"), int)
                and int(record["certified_source_rows"]) >= 0
                and isinstance(record.get("normalised_reserve_rows"), int)
                and int(record["normalised_reserve_rows"]) >= 0
                and record["certified_source_rows"] == record["normalised_reserve_rows"]
                and isinstance(record.get("pool_rows"), int)
                and int(record["pool_rows"]) >= 0
                and (record["status"] == "certified_empty")
                == (record["certified_source_rows"] == 0)
                and (record["status"] == "observed") == (record["pool_rows"] > 0)
                for record in support
            )
        )
        if not is_sha256(identity) or identity != canonical_json_sha256(shard_body) or not isinstance(shard_id, str) or not shard_id or shard_id in shard_ids or not support_valid:
            raise ValueError("capital generation manifest contains an invalid shard identity")
        shard_ids.add(shard_id)
    releases = manifest.get("certified_reserve_stream")
    if not isinstance(releases, dict) or set(releases) != {"uniswap_v2", "sushiswap_v2"}:
        raise ValueError("capital generation manifest has an invalid certified-reserve perimeter")
    for venue, record in releases.items():
        partitions = record.get("partitions") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or record.get("venue") != venue
            or record.get("authority_kind") != "local_certified_reserve_stream_v1"
            or not is_sha256(record.get("content_identity_sha256"))
            or not isinstance(record.get("certificate_path"), str)
            or not is_sha256(record.get("certificate_sha256"))
            or not isinstance(record.get("ledger_path"), str)
            or not is_sha256(record.get("ledger_sha256"))
            or not isinstance(partitions, list)
            or not partitions
            or any(
                not isinstance(partition, dict)
                or set(partition) != {"day", "expected_bytes", "expected_rows", "input_fingerprint"}
                or not isinstance(partition.get("day"), str)
                or not partition["day"]
                or not isinstance(partition.get("expected_bytes"), int)
                or int(partition["expected_bytes"]) < 0
                or not isinstance(partition.get("expected_rows"), int)
                or int(partition["expected_rows"]) < 0
                or not is_sha256(partition.get("input_fingerprint"))
                for partition in partitions
            )
            or [partition["day"] for partition in partitions]
            != sorted({partition["day"] for partition in partitions})
        ):
            raise ValueError("capital generation manifest has an invalid certified-reserve identity")
    expected_source_rows = {
        (venue, str(partition["day"])): int(partition["expected_rows"])
        for venue, release in releases.items()
        for partition in release["partitions"]
    }
    support_rows: dict[tuple[str, str], Mapping[str, object]] = {}
    for shard in shards:
        venue = str(shard["spec"]["venue"])
        for support_record in shard["daily_support"]:
            key = (venue, str(support_record["day"]))
            if key in support_rows:
                raise ValueError("capital generation support ledger contains a duplicate venue-day")
            support_rows[key] = support_record
    if set(support_rows) != set(expected_source_rows) or any(
        int(support_rows[key]["certified_source_rows"]) != expected
        for key, expected in expected_source_rows.items()
    ):
        raise ValueError("capital generation support ledger differs from certified source rows")
    observed_pool_rows: Counter[tuple[str, str]] = Counter()
    try:
        parquet = pq.ParquetFile(bundle.artifacts["pool"])
        for batch in parquet.iter_batches(columns=["venue", "day"], batch_size=250_000):
            venues = batch.column(0).to_pylist()
            days = batch.column(1).to_pylist()
            observed_pool_rows.update(zip(venues, days, strict=True))
    except (OSError, ValueError, pa.ArrowException) as error:
        raise ValueError("capital generation pool support cannot be read") from error
    expected_pool_rows = {
        key: int(record["pool_rows"])
        for key, record in support_rows.items()
        if int(record["pool_rows"]) > 0
    }
    if dict(observed_pool_rows) != expected_pool_rows:
        raise ValueError("capital generation support ledger differs from released pool rows")
    forecast = manifest.get("storage_forecast")
    forecast_fields = {
        "raw_input_bytes", "sampled_days", "sampled_bytes", "sampled_pool_days",
        "sampled_release_bytes", "projected_pool_days", "projected_release_bytes",
        "peak_workspace_bytes", "cardinality_margin", "fixed_bytes", "peak_multiplier",
        "free_space_reserve_bytes",
    }
    if (
        not isinstance(forecast, dict)
        or forecast.get("policy") != "stratified-exact-capital-output-calibration-v1"
        or not forecast_fields.issubset(forecast)
        or any(
            isinstance(forecast[field], bool)
            or not isinstance(forecast[field], (int, float))
            or float(forecast[field]) < 0
            for field in forecast_fields
        )
        or int(forecast["sampled_days"]) <= 0
        or int(forecast["sampled_pool_days"]) <= 0
        or int(forecast["sampled_release_bytes"]) <= 0
        or int(forecast["projected_pool_days"]) < int(forecast["sampled_pool_days"])
        or int(forecast["projected_release_bytes"]) < int(forecast["sampled_release_bytes"])
        or int(forecast["peak_workspace_bytes"]) < int(forecast["projected_release_bytes"])
    ):
        raise ValueError("capital generation storage calibration is invalid")
    scientific = manifest.get("scientific_inputs")
    if not isinstance(scientific, dict) or not scientific:
        raise ValueError("capital generation manifest lacks scientific input bindings")
    if any(not is_sha256(digest) for digest in scientific.values()):
        raise ValueError("capital generation manifest has an invalid scientific input digest")
    for shard in shards:
        venue = str((shard.get("spec") or {}).get("venue") or "")
        if (
            shard.get("scientific_input_sha256") != scientific
            or venue not in releases
            or shard.get("release_content_identity_sha256")
            != releases[venue]["content_identity_sha256"]
        ):
            raise ValueError("capital generation shard lineage differs from the release manifest")
    sources = manifest.get("code_sources")
    fingerprint = manifest.get("code_fingerprint")
    if (
        not isinstance(sources, list)
        or not sources
        or len(sources) != len(set(sources))
        or not is_sha256(fingerprint)
        or code_fingerprint([str(source) for source in sources]) != fingerprint
    ):
        raise ValueError("capital generation code identity is stale")
    if require_current_inputs:
        for path_text, digest in scientific.items():
            path = _resolve_record_path(path_text)
            if not path.is_file():
                raise ValueError(f"capital generation scientific input is stale: {path_text}")
            before = file_stat_identity(path)
            observed = file_sha256(path)
            if before != file_stat_identity(path) or observed != digest:
                raise ValueError(f"capital generation scientific input is stale: {path_text}")
        for venue, record in sorted(releases.items()):
            validate_certified_cp_stream_manifest(record, expected_venue=venue)


def resolve_capital_release(
    pointer_path: Path = CAPITAL_RELEASE_POINTER,
    *,
    require_current_inputs: bool = True,
) -> CapitalRelease:
    """Resolve and validate the one current capital generation."""

    bundle = resolve_artifact_release(
        pointer_path,
        kind=CAPITAL_RELEASE_KIND,
        schema_version=CAPITAL_RELEASE_SCHEMA_VERSION,
        filenames=CAPITAL_RELEASE_FILENAMES,
        require_current_provenance=True,
    )
    try:
        manifest = json.loads(bundle.artifacts[CAPITAL_MANIFEST_ARTIFACT].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("capital generation manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise ValueError("capital generation manifest is not a JSON object")
    validate_capital_generation_manifest(
        bundle,
        manifest,
        require_current_inputs=require_current_inputs,
    )
    return CapitalRelease(bundle, manifest)

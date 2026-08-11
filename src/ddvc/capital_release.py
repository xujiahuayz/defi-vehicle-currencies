"""Immutable marker-last release boundary for deposited-capital artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from ddvc.artifact_release import ArtifactRelease, canonical_json_sha256, file_sha256, file_stat_identity, is_sha256, resolve_artifact_release
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.provenance import code_fingerprint


CAPITAL_RELEASE_POINTER = DATA_DIR / "processed" / "pool_capital_release" / "current.json"
CAPITAL_RELEASE_KIND = "pool_capital"
CAPITAL_RELEASE_SCHEMA_VERSION = 1
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
        shard_body = {key: value for key, value in shard.items() if key != "identity_sha256"} if isinstance(shard, dict) else {}
        if not is_sha256(identity) or identity != canonical_json_sha256(shard_body) or not isinstance(shard_id, str) or not shard_id or shard_id in shard_ids:
            raise ValueError("capital generation manifest contains an invalid shard identity")
        shard_ids.add(shard_id)
    releases = manifest.get("released_state")
    if not isinstance(releases, dict) or set(releases) != {"uniswap_v2", "sushiswap_v2"}:
        raise ValueError("capital generation manifest has an invalid released-state perimeter")
    for record in releases.values():
        if (
            not isinstance(record, dict)
            or not is_sha256(record.get("content_identity_sha256"))
            or not is_sha256(record.get("ledger_sha256"))
            or int(record.get("partitions") or 0) <= 0
        ):
            raise ValueError("capital generation manifest has an invalid released-state identity")
    upstream = manifest.get("upstream_releases")
    if not isinstance(upstream, dict) or not is_sha256(upstream.get("v2_event_source_generation_id")):
        raise ValueError("capital generation manifest lacks the V2 event release identity")
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

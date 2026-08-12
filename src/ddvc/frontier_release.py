"""Canonical artifact-release adapter for the full-daily frontier bundle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path

from ddvc.artifact_release import (
    ArtifactRelease,
    current_artifact_release,
    is_sha256,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.paths import DATA_DIR


FRONTIER_RELEASE_SCHEMA_VERSION = 2
FRONTIER_RELEASE_KIND = "transaction_state_frontier_daily"
FRONTIER_RELEASE_ROOT = DATA_DIR / "processed" / "transaction_state_frontier_daily_release"
FRONTIER_RELEASE_MARKER = FRONTIER_RELEASE_ROOT / "current.json"
FRONTIER_RELEASE_FILENAMES = {
    "panel": "transaction_state_frontier_daily.parquet",
    "rejections": "transaction_state_frontier_daily_rejections.parquet",
    "support": "transaction_state_frontier_daily_support.parquet",
    "manifest": "transaction_state_frontier_daily_manifest.json",
}
FRONTIER_DATA_ARTIFACTS = ("panel", "rejections", "support")


@dataclass(frozen=True)
class FrontierRelease:
    """One generic artifact bundle with frontier-specific source identity."""

    bundle: ArtifactRelease
    source_identity_sha256: str

    @property
    def generation_id(self) -> str:
        return self.bundle.generation_id

    @property
    def marker_path(self) -> Path:
        return self.bundle.pointer_path

    @property
    def artifacts(self) -> Mapping[str, Path]:
        return {
            name: self.bundle.artifacts[name] for name in FRONTIER_DATA_ARTIFACTS
        }

    @property
    def lineage_paths(self) -> tuple[Path, ...]:
        return self.bundle.lineage_paths

    def assert_current(self) -> None:
        self.bundle.assert_current()


def _frontier_release(bundle: ArtifactRelease) -> FrontierRelease:
    try:
        manifest = json.loads(
            bundle.artifacts["manifest"].read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("daily frontier manifest is absent or invalid") from error
    source_identity = (
        manifest.get("source_identity_sha256")
        if isinstance(manifest, dict)
        else None
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != FRONTIER_RELEASE_SCHEMA_VERSION
        or manifest.get("kind") != FRONTIER_RELEASE_KIND
        or not is_sha256(source_identity)
    ):
        raise ValueError("daily frontier manifest has an invalid contract")
    return FrontierRelease(bundle, str(source_identity))


def publish_frontier_release(
    *,
    writers: Mapping[str, Callable[[Path], None]],
    row_counts: Mapping[str, int],
    code_sources: list[str],
    inputs: list[str | Path],
    notes: str,
    source_identity_sha256: str,
    validate_staged: Callable[[Mapping[str, Path]], None],
    marker_path: Path = FRONTIER_RELEASE_MARKER,
) -> FrontierRelease:
    """Publish all frontier members through the canonical marker-last owner."""

    if set(writers) != set(FRONTIER_DATA_ARTIFACTS):
        raise ValueError("daily frontier writers have an invalid perimeter")
    if set(row_counts) != set(FRONTIER_DATA_ARTIFACTS):
        raise ValueError("daily frontier row counts have an invalid perimeter")
    if not is_sha256(source_identity_sha256):
        raise ValueError("daily frontier source identity is not a SHA-256 digest")
    manifest = {
        "schema_version": FRONTIER_RELEASE_SCHEMA_VERSION,
        "kind": FRONTIER_RELEASE_KIND,
        "source_identity_sha256": source_identity_sha256,
    }

    def write_manifest(path: Path) -> None:
        path.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )

    def validate(paths: Mapping[str, Path]) -> None:
        validate_staged(paths)
        if json.loads(paths["manifest"].read_text(encoding="utf-8")) != manifest:
            raise ValueError("daily frontier source manifest changed during publication")

    bundle = publish_artifact_release(
        pointer_path=marker_path,
        kind=FRONTIER_RELEASE_KIND,
        schema_version=FRONTIER_RELEASE_SCHEMA_VERSION,
        filenames=FRONTIER_RELEASE_FILENAMES,
        writers={**writers, "manifest": write_manifest},
        row_counts={**row_counts, "manifest": 1},
        code_sources=code_sources,
        inputs=inputs,
        notes=notes,
        validate_staged=validate,
    )
    return _frontier_release(bundle)


def resolve_frontier_release(
    *,
    marker_path: Path = FRONTIER_RELEASE_MARKER,
    expected_source_identity_sha256: str | None = None,
) -> FrontierRelease:
    """Resolve the frontier through the canonical artifact-release reader."""

    release = _frontier_release(
        resolve_artifact_release(
            marker_path,
            kind=FRONTIER_RELEASE_KIND,
            schema_version=FRONTIER_RELEASE_SCHEMA_VERSION,
            filenames=FRONTIER_RELEASE_FILENAMES,
            require_current_provenance=True,
        )
    )
    if (
        expected_source_identity_sha256 is not None
        and release.source_identity_sha256 != expected_source_identity_sha256
    ):
        raise ValueError("daily frontier selects a different source generation")
    return release


@contextmanager
def current_frontier_release(release: FrontierRelease):
    """Lease one exact frontier generation through a complete consumption."""

    with current_artifact_release(release.bundle):
        yield release

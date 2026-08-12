"""Marker-last consistency contract for the three daily frontier outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ddvc.artifact_release import canonical_json_sha256, file_sha256, is_sha256
from ddvc.paths import DATA_DIR
from ddvc.provenance import sidecar_path, verify
from ddvc.runtime import atomic_output, serialized_output_install


FRONTIER_RELEASE_SCHEMA_VERSION = 1
FRONTIER_RELEASE_MARKER = (
    DATA_DIR / "processed" / "transaction_state_frontier_daily.release.json"
)
FRONTIER_RELEASE_ARTIFACTS = {
    "panel": DATA_DIR / "processed" / "transaction_state_frontier_daily.parquet",
    "rejections": DATA_DIR
    / "processed"
    / "transaction_state_frontier_daily_rejections.parquet",
    "support": DATA_DIR
    / "processed"
    / "transaction_state_frontier_daily_support.parquet",
}


@dataclass(frozen=True)
class FrontierRelease:
    generation_id: str
    source_identity_sha256: str
    marker_path: Path
    artifacts: Mapping[str, Path]

    @property
    def lineage_paths(self) -> tuple[Path, ...]:
        return (
            self.marker_path,
            *(path for name, path in sorted(self.artifacts.items())),
            *(sidecar_path(path) for name, path in sorted(self.artifacts.items())),
        )

    def assert_current(self) -> None:
        reopened = resolve_frontier_release(
            marker_path=self.marker_path,
            artifacts=self.artifacts,
            expected_source_identity_sha256=self.source_identity_sha256,
        )
        if reopened.generation_id != self.generation_id:
            raise ValueError("daily frontier generation changed during consumption")


def _release_record(
    artifacts: Mapping[str, Path], *, source_identity_sha256: str
) -> dict[str, object]:
    identities = {
        name: {
            "path": str(path),
            "sha256": file_sha256(path),
            "provenance_sha256": file_sha256(sidecar_path(path)),
        }
        for name, path in sorted(artifacts.items())
    }
    generation = canonical_json_sha256(
        {"artifacts": identities, "source_identity_sha256": source_identity_sha256}
    )
    return {
        "schema_version": FRONTIER_RELEASE_SCHEMA_VERSION,
        "kind": "transaction_state_frontier_daily",
        "generation_id": generation,
        "source_identity_sha256": source_identity_sha256,
        "artifacts": identities,
    }


def invalidate_frontier_release_marker(
    marker_path: Path = FRONTIER_RELEASE_MARKER,
) -> None:
    """Make an in-progress flat-output replacement unreadable as one release."""

    with serialized_output_install(marker_path):
        marker_path.unlink(missing_ok=True)


def publish_frontier_release_marker(
    artifacts: Mapping[str, Path] = FRONTIER_RELEASE_ARTIFACTS,
    *,
    marker_path: Path = FRONTIER_RELEASE_MARKER,
    source_identity_sha256: str,
) -> FrontierRelease:
    """Select one complete already-stamped output set with one final marker."""

    if set(artifacts) != set(FRONTIER_RELEASE_ARTIFACTS):
        raise ValueError("daily frontier release has an invalid artifact perimeter")
    if not is_sha256(source_identity_sha256):
        raise ValueError("daily frontier source identity is not a SHA-256 digest")
    with serialized_output_install(marker_path):
        marker_path.unlink(missing_ok=True)
        for path in artifacts.values():
            if not path.is_file() or verify(path).get("status") != "ok":
                raise ValueError(f"daily frontier artifact is absent or stale: {path}")
        record = _release_record(
            artifacts, source_identity_sha256=source_identity_sha256
        )
        with atomic_output(marker_path) as temporary:
            temporary.write_text(
                json.dumps(record, sort_keys=True) + "\n", encoding="utf-8"
            )
    return resolve_frontier_release(
        marker_path=marker_path,
        artifacts=artifacts,
        expected_source_identity_sha256=source_identity_sha256,
    )


def resolve_frontier_release(
    *,
    marker_path: Path = FRONTIER_RELEASE_MARKER,
    artifacts: Mapping[str, Path] = FRONTIER_RELEASE_ARTIFACTS,
    expected_source_identity_sha256: str | None = None,
) -> FrontierRelease:
    """Reopen all outputs and reject any split or stale generation."""

    try:
        record = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("daily frontier release marker is absent or invalid") from error
    artifact_record = record.get("artifacts") if isinstance(record, dict) else None
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != FRONTIER_RELEASE_SCHEMA_VERSION
        or record.get("kind") != "transaction_state_frontier_daily"
        or not isinstance(artifact_record, dict)
        or set(artifact_record) != set(FRONTIER_RELEASE_ARTIFACTS)
        or not is_sha256(record.get("source_identity_sha256"))
    ):
        raise ValueError("daily frontier release marker has an invalid contract")
    source_identity = str(record["source_identity_sha256"])
    if (
        expected_source_identity_sha256 is not None
        and source_identity != expected_source_identity_sha256
    ):
        raise ValueError("daily frontier release selects a different source generation")
    observed = _release_record(
        artifacts, source_identity_sha256=source_identity
    )
    if observed != record:
        raise ValueError("daily frontier outputs do not form the selected generation")
    for path in artifacts.values():
        if verify(path).get("status") != "ok":
            raise ValueError(f"daily frontier artifact provenance is stale: {path}")
    return FrontierRelease(
        str(record["generation_id"]),
        source_identity,
        marker_path,
        dict(artifacts),
    )

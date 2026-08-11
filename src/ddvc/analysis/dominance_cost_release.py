"""Canonical immutable release boundary for dominance-cost D3 artifacts."""

from __future__ import annotations

from pathlib import Path

from ddvc.artifact_release import ArtifactRelease, resolve_artifact_release
from ddvc.paths import REPO_ROOT


DOMINANCE_COST_RELEASE_RELATIVE = "data/processed/dominance_cost_pairwise_release/current.json"
DOMINANCE_COST_RELEASE = REPO_ROOT / DOMINANCE_COST_RELEASE_RELATIVE
DOMINANCE_COST_RELEASE_KIND = "dominance_cost_pairwise"
DOMINANCE_COST_RELEASE_SCHEMA_VERSION = 1
DOMINANCE_COST_RELEASE_FILENAMES = {
    "panel": "dominance_cost_pairwise.parquet",
    "support": "dominance_cost_pairwise_support.parquet",
}


def resolve_dominance_cost_release(
    pointer_path: Path = DOMINANCE_COST_RELEASE,
) -> ArtifactRelease:
    """Resolve the one current hash- and provenance-verified generation."""

    return resolve_artifact_release(
        pointer_path,
        kind=DOMINANCE_COST_RELEASE_KIND,
        schema_version=DOMINANCE_COST_RELEASE_SCHEMA_VERSION,
        filenames=DOMINANCE_COST_RELEASE_FILENAMES,
        require_current_provenance=True,
    )

"""Immutable release contract for exact endpoint-candidate composition tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

import pandas as pd

from ddvc.artifact_release import (
    ArtifactRelease,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.endpoint_candidate_composition import (
    CHOICE_COLUMNS,
    EXCLUSION_COLUMNS,
    PAIR_SUPPORT_COLUMNS,
    EndpointCandidateComposition,
    validate_endpoint_candidate_composition,
)
from ddvc.paths import DATA_DIR


ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE = (
    "data/processed/endpoint_candidate_composition_release/current.json"
)
ENDPOINT_CANDIDATE_COMPOSITION_RELEASE = (
    DATA_DIR / "processed" / "endpoint_candidate_composition_release" / "current.json"
)
ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND = "endpoint_candidate_composition"
ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION = 2
ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES = {
    "choices": "endpoint_candidate_choices.parquet",
    "pair_support": "endpoint_candidate_pair_support.parquet",
    "exclusions": "endpoint_candidate_exclusions.parquet",
}


@dataclass(frozen=True)
class EndpointCandidateCompositionRelease:
    """One selected and fully validated three-table composition generation."""

    bundle: ArtifactRelease

    @property
    def generation_id(self) -> str:
        return self.bundle.generation_id

    @property
    def pointer_path(self) -> Path:
        return self.bundle.pointer_path

    @property
    def artifacts(self) -> Mapping[str, Path]:
        return self.bundle.artifacts


def read_endpoint_candidate_composition(
    paths: Mapping[str, Path],
) -> EndpointCandidateComposition:
    """Read exactly the three registered Parquet members."""

    if set(paths) != set(ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES):
        raise ValueError("endpoint-candidate release has an invalid artifact perimeter")
    try:
        bundle = EndpointCandidateComposition(
            choices=pd.read_parquet(paths["choices"]),
            pair_support=pd.read_parquet(paths["pair_support"]),
            exclusions=pd.read_parquet(paths["exclusions"]),
        )
    except (OSError, ValueError) as error:
        raise ValueError("endpoint-candidate release contains unreadable Parquet") from error
    return bundle


def validate_endpoint_candidate_composition_paths(
    paths: Mapping[str, Path],
) -> dict[str, int]:
    """Reopen and fully validate schema, ordering, support, and accounting."""

    observed = read_endpoint_candidate_composition(paths)
    validated = validate_endpoint_candidate_composition(observed)
    for name in ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES:
        source = getattr(observed, name)
        canonical = getattr(validated, name)
        try:
            pd.testing.assert_frame_equal(source, canonical, check_like=False)
        except AssertionError as error:
            raise ValueError(
                f"endpoint-candidate {name} table is not in canonical validated order"
            ) from error
    return {
        "choices": len(validated.choices),
        "pair_support": len(validated.pair_support),
        "exclusions": len(validated.exclusions),
    }


def publish_endpoint_candidate_composition_release(
    *,
    writers: Mapping[str, Callable[[Path], None]],
    row_counts: Mapping[str, int],
    code_sources: list[str],
    inputs: list[str | Path],
    notes: str,
    preinstall_validator: Callable[[Path], object],
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
) -> EndpointCandidateCompositionRelease:
    """Publish the exact three-table bundle through one marker-last pointer."""

    expected = set(ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES)
    if set(writers) != expected or set(row_counts) != expected:
        raise ValueError("endpoint-candidate publication requires exactly three tables")

    def validate(paths: Mapping[str, Path]) -> None:
        observed = validate_endpoint_candidate_composition_paths(paths)
        declared = {name: int(row_counts[name]) for name in expected}
        if observed != declared:
            raise ValueError(
                "endpoint-candidate staged row counts disagree with publication metadata"
            )

    bundle = publish_artifact_release(
        pointer_path=pointer_path,
        kind=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
        schema_version=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
        filenames=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
        writers=writers,
        row_counts=row_counts,
        code_sources=code_sources,
        inputs=inputs,
        notes=notes,
        validate_staged=validate,
        preinstall_validator=preinstall_validator,
    )
    return EndpointCandidateCompositionRelease(bundle)


def resolve_endpoint_candidate_composition_release(
    pointer_path: Path = ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
) -> EndpointCandidateCompositionRelease:
    """Resolve one current generation and validate its complete accounting contract."""

    bundle = resolve_artifact_release(
        pointer_path,
        kind=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
        schema_version=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
        filenames=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
        require_current_provenance=True,
    )
    validate_endpoint_candidate_composition_paths(bundle.artifacts)
    return EndpointCandidateCompositionRelease(bundle)

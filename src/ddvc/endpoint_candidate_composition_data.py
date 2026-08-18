"""Direct paths for the four endpoint-candidate composition tables."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from ddvc.endpoint_candidate_composition import (
    CHOICE_COLUMNS,
    EXCLUSION_COLUMNS,
    PAIR_SUPPORT_COLUMNS,
    EndpointCandidateComposition,
    validate_endpoint_candidate_composition,
)
from ddvc.paths import DATA_DIR
from ddvc.workflow import current_inputs


ENDPOINT_CANDIDATE_COMPOSITION_PATHS = {
    "choices": DATA_DIR / "processed" / "endpoint_candidate_choices.parquet",
    "choice_audit": DATA_DIR / "processed" / "endpoint_candidate_choice_audit.parquet",
    "pair_support": DATA_DIR / "processed" / "endpoint_candidate_pair_support.parquet",
    "exclusions": DATA_DIR / "processed" / "endpoint_candidate_exclusions.parquet",
}


@dataclass(frozen=True)
class EndpointCandidateCompositionData:
    """The current direct four-table processed dataset."""

    artifacts: Mapping[str, Path]


def read_endpoint_candidate_composition(
    paths: Mapping[str, Path] = ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
) -> EndpointCandidateComposition:
    if set(paths) != set(ENDPOINT_CANDIDATE_COMPOSITION_PATHS):
        raise ValueError("endpoint-candidate data require exactly four tables")
    try:
        return EndpointCandidateComposition(
            choices=pd.read_parquet(paths["choices"]),
            choice_audit=pd.read_parquet(paths["choice_audit"]),
            pair_support=pd.read_parquet(paths["pair_support"]),
            exclusions=pd.read_parquet(paths["exclusions"]),
        )
    except (OSError, ValueError) as error:
        raise ValueError("endpoint-candidate data contain unreadable Parquet") from error


def validate_endpoint_candidate_composition_paths(
    paths: Mapping[str, Path] = ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
) -> dict[str, int]:
    observed = read_endpoint_candidate_composition(paths)
    validated = validate_endpoint_candidate_composition(observed)
    for name in ENDPOINT_CANDIDATE_COMPOSITION_PATHS:
        source = getattr(observed, name)
        canonical = getattr(validated, name)
        try:
            pd.testing.assert_frame_equal(source, canonical, check_like=False)
        except AssertionError as error:
            raise ValueError(f"endpoint-candidate {name} is not in canonical order") from error
    return {
        "choices": len(validated.choices),
        "choice_audit": len(validated.choice_audit),
        "pair_support": len(validated.pair_support),
        "exclusions": len(validated.exclusions),
    }


@contextmanager
def current_endpoint_candidate_composition(
    paths: Mapping[str, Path] = ENDPOINT_CANDIDATE_COMPOSITION_PATHS,
):
    """Lease the direct tables while a consumer reads them."""

    with current_inputs(paths.values(), consumer="endpoint-candidate composition"):
        yield EndpointCandidateCompositionData(dict(paths))

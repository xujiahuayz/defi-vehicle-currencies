"""Counterfactual publication policy over the generic journaled capability owner."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ddvc.journaled_capability import (
    JournaledCapabilityRecoveryRequired,
    current_publication,
    publication_capability,
    register_publication_capability as _register_publication_capability,
    require_active_publication,
    require_current_publication,
    validate_publication_capability,
)
from ddvc.paths import DATA_DIR


PublicationRecoveryRequired = JournaledCapabilityRecoveryRequired


def publication_marker_path(capability_id: str) -> Path:
    """Return the counterfactual policy's canonical marker location."""

    slug = "".join(
        character if character.isalnum() else "-" for character in capability_id
    ).strip("-")
    suffix = hashlib.sha256(capability_id.encode()).hexdigest()[:12]
    return (
        DATA_DIR
        / "processed"
        / "counterfactual_publications"
        / f"{slug}-{suffix}.json"
    )


def register_publication_capability(
    capability_id: str,
    outputs,
    *,
    marker_path: Path | None = None,
) -> None:
    """Register a fixed counterfactual output perimeter and canonical marker."""

    _register_publication_capability(
        capability_id,
        outputs,
        marker_path=marker_path or publication_marker_path(capability_id),
    )


__all__ = [
    "PublicationRecoveryRequired",
    "current_publication",
    "publication_capability",
    "publication_marker_path",
    "register_publication_capability",
    "require_active_publication",
    "require_current_publication",
    "validate_publication_capability",
]

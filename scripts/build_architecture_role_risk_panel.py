#!/usr/bin/env python3
"""Build the weekly observed-support vehicle-role panel from one exact release.

This command first verifies the published byte size of all four endpoint-release
members.  It does not open any Parquet member while a transfer is partial.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ddvc.analysis.vehicle_role_risk import (
    assert_endpoint_release_sizes_complete,
    build_vehicle_role_risk_panel_from_release,
)
from ddvc.artifact_release import SemanticValidationReceipt
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    ENDPOINT_CANDIDATE_COMPOSITION_VALIDATOR_SOURCES,
    current_endpoint_candidate_composition_release,
    endpoint_candidate_composition_validator_fingerprint,
)
from ddvc.paths import DATA_DIR
from ddvc.tables import write_panel


OUTPUT = (
    DATA_DIR / "processed" / "endpoint_observed_vehicle_role_risk_weekly.parquet"
)
CODE_SOURCES = [
    "scripts/build_architecture_role_risk_panel.py",
    "src/ddvc/analysis/vehicle_role_risk.py",
    *ENDPOINT_CANDIDATE_COMPOSITION_VALIDATOR_SOURCES,
]


def run(*, pointer_path: Path, output_path: Path) -> Path:
    # The size gate prevents the canonical resolver from hashing/opening a member
    # that is still transferring.  The resolver then performs the SHA checks once.
    complete = assert_endpoint_release_sizes_complete(pointer_path)
    receipt = SemanticValidationReceipt(
        complete.generation_id,
        endpoint_candidate_composition_validator_fingerprint(),
    )
    with current_endpoint_candidate_composition_release(
        pointer_path,
        expected_semantic_receipt=receipt,
    ) as release:
        if release.generation_id != complete.generation_id:
            raise RuntimeError("endpoint release changed after completeness preflight")
        panel = build_vehicle_role_risk_panel_from_release(release.artifacts)
        return write_panel(
            panel,
            output_path,
            code_sources=CODE_SOURCES,
            inputs=list(release.bundle.lineage_paths),
            notes=(
                "pair x stable/native candidate from its first-observed week through "
                "later active pair-weeks; zeros are post-first-use realised non-use, "
                "not economically feasible alternatives; pair_observed_days records "
                "the release's sampled-date cadence within each calendar week; "
                f"endpoint generation={release.generation_id}"
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-pointer",
        type=Path,
        default=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = run(pointer_path=args.release_pointer, output_path=args.output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

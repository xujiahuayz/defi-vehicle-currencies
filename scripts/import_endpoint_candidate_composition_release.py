#!/usr/bin/env python3
"""Import one immutable endpoint-composition release from a durable host."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath

from ddvc.artifact_import import SSHReleaseSource, TransferPolicy, import_release
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
    current_endpoint_candidate_composition_release,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resume and verify one exact remote endpoint-composition generation, "
            "then publish its original pointer bytes last."
        )
    )
    parser.add_argument("--host", required=True)
    parser.add_argument(
        "--remote-repo-root",
        required=True,
        type=PurePosixPath,
        help="absolute project repository path on the remote host",
    )
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=1)
    parser.add_argument("--connect-timeout", type=int, default=10)
    parser.add_argument("--idle-timeout", type=int, default=60)
    parser.add_argument("--hard-attempt-timeout", type=int, default=600)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--initial-backoff", type=float, default=2.0)
    parser.add_argument("--maximum-backoff", type=float, default=30.0)
    parser.add_argument(
        "--status",
        type=Path,
        default=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE.parent / "import-status.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pointer_relative = PurePosixPath(
        ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE
    )
    policy = TransferPolicy(
        connect_timeout_seconds=args.connect_timeout,
        idle_timeout_seconds=args.idle_timeout,
        hard_attempt_timeout_seconds=args.hard_attempt_timeout,
        max_attempts=args.max_attempts,
        initial_backoff_seconds=args.initial_backoff,
        maximum_backoff_seconds=args.maximum_backoff,
    )
    source = SSHReleaseSource(
        host=args.host,
        remote_repo_root=args.remote_repo_root,
        pointer_repo_relative=pointer_relative,
        policy=policy,
    )
    imported = import_release(
        source=source,
        local_pointer=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE,
        pointer_repo_relative=pointer_relative,
        kind=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
        schema_version=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
        filenames=ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
        lease_factory=current_endpoint_candidate_composition_release,
        status_path=args.status,
        jobs=args.jobs,
        policy=policy,
    )
    print(f"imported endpoint-candidate generation {imported.generation_id}")


if __name__ == "__main__":
    main()

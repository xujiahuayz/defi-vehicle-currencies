"""Shared real local-generation certification for raw test partitions."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ddvc.raw_certification import (
    RawPartition,
    local_scan_certificate_path,
    scan_installed_generation,
    write_local_scan_certificate,
)


def install_local_raw_certificate(
    raw_root: Path,
    source: str,
    streams: Iterable[str],
    day: str,
) -> Path:
    """Scan and certify the exact provider files used by one test fixture."""

    if raw_root.name not in {"thegraph", "dune"} or raw_root.parent.name != "raw":
        raise ValueError("raw test root must end in raw/thegraph or raw/dune")
    data_root = raw_root.parents[1]
    partitions = tuple(
        RawPartition(source, stream, day) for stream in sorted(set(streams))
    )
    rows = scan_installed_generation(
        data_root,
        data_root / "processed" / "raw_generation" / ".test-scan" / source,
        workers=1,
        partitions=partitions,
    )
    failures = [row for row in rows if row.get("local_pass") is not True]
    if failures:
        raise AssertionError(
            f"raw fixture cannot be certified: {failures[0]['source']}/"
            f"{failures[0]['stream']}/{failures[0]['day']} "
            f"errors={failures[0].get('errors')}"
        )
    output = local_scan_certificate_path(source, data_root=data_root)
    write_local_scan_certificate(
        output,
        rows,
        expected_partitions=partitions,
    )
    return output

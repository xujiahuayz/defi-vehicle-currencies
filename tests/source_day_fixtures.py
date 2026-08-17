"""Shared source-day metadata for canonical raw-reader tests."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable
from pathlib import Path


def install_source_day_metadata(
    raw_root: Path,
    source: str,
    streams: Iterable[str],
    day: str,
) -> Path:
    """Write the ordinary provider metadata used by one test source-day."""

    if raw_root.name not in {"thegraph", "dune"} or raw_root.parent.name != "raw":
        raise ValueError("raw test root must end in raw/thegraph or raw/dune")
    directory = raw_root / source
    records: dict[str, dict[str, object]] = {}
    for stream in sorted(set(streams)):
        path = directory / f"{source}_{stream}_{day}.jsonl.gz"
        if not path.is_file():
            raise FileNotFoundError(path)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = sum(1 for line in handle if line.strip())
        records[stream] = {"path": str(path), "rows": rows}
    marker = directory / f"{source}_meta_{day}.json"
    marker.write_text(
        json.dumps(
            {
                "source": source,
                "day": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                "streams": records,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return marker

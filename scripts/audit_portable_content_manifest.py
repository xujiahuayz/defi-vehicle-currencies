#!/usr/bin/env python3
"""Print a format-aware content manifest for a cross-host file perimeter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddvc.provenance import portable_content_manifest, portable_manifest_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--pattern",
        action="append",
        required=True,
        help="root-relative glob; repeat to define the exact admitted perimeter",
    )
    args = parser.parse_args()
    entries = portable_content_manifest(args.root, patterns=args.pattern)
    print(
        json.dumps(
            {
                "files": len(entries),
                "portable_manifest_sha256": portable_manifest_sha256(entries),
                "entries": entries,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

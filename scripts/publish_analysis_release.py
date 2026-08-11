#!/usr/bin/env python3
"""Publish the D3 analysis release after reopening every active claim input."""

from __future__ import annotations

import argparse
import json

from ddvc.analysis_release import publish_analysis_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specification-lock", default="docs/specification-lock.json")
    parser.add_argument("--pointer", default="data/processed/d3_analysis_release/current.json")
    args = parser.parse_args()
    release = publish_analysis_release(
        specification_path=args.specification_lock,
        pointer_path=args.pointer,
    )
    print(
        json.dumps(
            {
                "generation": release.generation,
                "certificate": release.certificate_path.relative_to(release.root).as_posix(),
                "claim_inputs": release.certificate["claim_input_count"],
                "status": release.certificate["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

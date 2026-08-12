#!/usr/bin/env python3
"""Build exact selections for every newly admitted Graph collection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddvc.fetch.acquisition import GRAPH_NEW_MANIFEST, GRAPH_NEW_STREAM_INVENTORY
from ddvc.fetch.schema_admission import build_new_stream_field_manifest
from ddvc.runtime import atomic_output


DEFAULT_INVENTORY = GRAPH_NEW_STREAM_INVENTORY
DEFAULT_OUTPUT = GRAPH_NEW_MANIFEST


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    manifest = build_new_stream_field_manifest(inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(args.output) as temporary:
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

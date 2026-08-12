#!/usr/bin/env python3
"""Build compact proof that current Graph consumers need no incremental fetch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ddvc.fetch.thin_consumer_audit import publish_thin_consumer_audit
from ddvc.paths import PRIMARY_REPO_ROOT, REPO_ROOT


DEFAULT_DATA_ROOT = PRIMARY_REPO_ROOT / "data"
DEFAULT_CERTIFICATE_ROOT = DEFAULT_DATA_ROOT / "processed" / "graph_thin_consumer_audit" / "source_markers"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "graph-thin-consumer-audit.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--certificate-root", type=Path, default=DEFAULT_CERTIFICATE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = publish_thin_consumer_audit(
        args.output,
        data_root=args.data_root,
        certificate_root=args.certificate_root,
    )
    print(json.dumps({"consumers": len(payload["consumers"]), "source_markers": len(payload["source_release_markers"]), "authorized_streams": payload["authorized_graph_acquisition"]["stream_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run or close D3-bound open-minded E0 exploration."""

from __future__ import annotations

import argparse
import json

from ddvc.exploration import close_exploration, execute_exploration_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="execute and append every fitted family")
    run.add_argument("--plan", required=True)
    run.add_argument("--d3-certificate", required=True)
    run.add_argument("--ledger", default="docs/model-ledger.json")
    close = subparsers.add_parser("close", help="require exact triage and publish E0")
    close.add_argument("--triage", required=True)
    close.add_argument("--d3-certificate", required=True)
    close.add_argument("--ledger", default="docs/model-ledger.json")
    close.add_argument("--pointer", default="data/processed/e0_exploration_release/current.json")
    args = parser.parse_args()
    if args.command == "run":
        run_ids = execute_exploration_plan(
            args.plan,
            d3_certificate_path=args.d3_certificate,
            ledger_path=args.ledger,
        )
        print(json.dumps({"status": "in_progress", "executed_run_ids": run_ids}, sort_keys=True))
        return 0
    release = close_exploration(
        args.triage,
        d3_certificate_path=args.d3_certificate,
        ledger_path=args.ledger,
        pointer_path=args.pointer,
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "generation": release.generation,
                "exploratory_runs": len(release.certificate["exploratory_run_ids"]),
                "certificate": release.certificate_path.relative_to(release.root).as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

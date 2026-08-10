#!/usr/bin/env python3
"""Fetch exact annual Coinbase evidence and materialize the canonical intraday WETH/USD panel without filling missing minutes."""

from __future__ import annotations

import argparse
import json

from ddvc.external_prices import (
    missing_candle_requests,
    validate_external_weth_usd_release,
    write_gap_audit,
    write_panel_from_raw_files,
)
from ddvc.fetch.coinbase_prices import (
    SAMPLE_END_UTC_EXCLUSIVE,
    SAMPLE_START_UTC,
    annual_evidence_paths,
    annual_perimeters,
    fetch_raw_file,
    fetch_source_identity,
    iter_raw_records,
    plan_candle_requests,
)
from ddvc.paths import (
    EXTERNAL_WETH_USD_INTRADAY_PANEL,
    EXTERNAL_WETH_USD_RAW_ROOT,
    EXTERNAL_WETH_USD_SOURCE_LOCK,
)
from ddvc.runtime import exclusive_job


CODE_SOURCES = [
    "scripts/build_external_weth_usd_intraday.py",
    "src/ddvc/external_prices.py",
    "src/ddvc/fetch/coinbase_prices.py",
    "src/ddvc/fetch/raw.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/http.py",
    "src/ddvc/paths.py",
    "src/ddvc/provenance.py",
    "src/ddvc/runtime.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "build"))
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    perimeters = list(annual_perimeters(SAMPLE_START_UTC, SAMPLE_END_UTC_EXCLUSIVE))
    planned = sum(
        len(plan_candle_requests(start, end)) for start, end, _ in perimeters
    )
    if args.command == "plan":
        print(
            json.dumps(
                {
                    "start_utc": SAMPLE_START_UTC,
                    "end_utc_exclusive": SAMPLE_END_UTC_EXCLUSIVE,
                    "annual_files": len(perimeters),
                    "requests": planned,
                },
                indent=2,
            )
        )
        return 0

    with exclusive_job(EXTERNAL_WETH_USD_SOURCE_LOCK, job="external WETH/USD panel"):
        identity_path = fetch_source_identity(EXTERNAL_WETH_USD_RAW_ROOT / "source_identity.json")
        raw_paths = []
        audit_paths = []
        for start, end, year in perimeters:
            evidence = annual_evidence_paths(EXTERNAL_WETH_USD_RAW_ROOT, year)
            requests = plan_candle_requests(start, end)
            base_path = fetch_raw_file(evidence.base, requests, workers=args.workers)
            gap_path = fetch_raw_file(
                evidence.gaps,
                missing_candle_requests(
                    [base_path], start_utc=start, end_utc_exclusive=end
                ),
                workers=args.workers,
            )
            audit_path = write_gap_audit(
                evidence.audit,
                base_path,
                gap_path,
                start_utc=start,
                end_utc_exclusive=end,
            )
            raw_paths.extend([base_path, gap_path])
            audit_paths.append(audit_path)
            gap_request_count = sum(1 for _record in iter_raw_records(gap_path))
            print(
                f"raw {year}: {len(requests):,} first-pass requests; "
                f"gap requery={gap_request_count:,}",
                flush=True,
            )
        coverage = write_panel_from_raw_files(
            raw_paths,
            EXTERNAL_WETH_USD_INTRADAY_PANEL,
            start_utc=SAMPLE_START_UTC,
            end_utc_exclusive=SAMPLE_END_UTC_EXCLUSIVE,
            code_sources=CODE_SOURCES,
            inputs=[identity_path, *raw_paths, *audit_paths],
            provenance_notes={
                "scope": "receipt_wei_to_usd_and_eth_usd_reference_only",
                "all_in_bps_scope": "withheld_without_transaction_time_endpoint_usd",
                "pool_lvr_scope": "withheld_without_exact_second_asset_usd_path",
            },
            raw_root=EXTERNAL_WETH_USD_RAW_ROOT,
        )
        release = validate_external_weth_usd_release(
            EXTERNAL_WETH_USD_INTRADAY_PANEL,
            EXTERNAL_WETH_USD_RAW_ROOT,
        )
        print(json.dumps({**coverage, "release": release}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compare sampled Fluid route labels with exact receipt events and transfers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ddvc.analysis.fluid_route_label_validation import (
    FLUID_SWAP_TOPIC,
    load_fluid_receipt,
    load_pool_constants,
    validate_fluid_leg,
    validation_summary,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.runtime import atomic_output


DEFAULT_SAMPLE = DATA_DIR / "interim" / "fluid_route_label_validation_sample.parquet"
DEFAULT_CACHE = DATA_DIR / "raw" / "ethereum" / "fluid_route_validation" / "receipts"
DEFAULT_POOL_CACHE = (
    DATA_DIR / "raw" / "ethereum" / "fluid_route_validation" / "pool_constants"
)
DEFAULT_OUTPUT = OUTPUT_DIR / "exhibits" / "fluid_route_label_validation.jsonl"


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return json.loads(
        frame.to_json(orient="records", double_precision=15)
    )


def _write_jsonl(records: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(output) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")


def run(
    *,
    sample: Path,
    cache: Path,
    pool_cache: Path,
    output: Path,
) -> pd.DataFrame:
    legs = pd.read_parquet(sample)
    results: list[dict[str, object]] = []
    receipts: dict[tuple[str, int], dict | None] = {}
    pool_blocks = (
        legs.groupby("pool", sort=True)["block_number"].min().astype(int).to_dict()
    )
    pool_constants = {
        str(pool): load_pool_constants(
            pool_cache,
            str(pool),
            block_number=int(block_number),
            require_evidence=True,
        )
        for pool, block_number in pool_blocks.items()
    }
    for leg in legs.to_dict("records"):
        tx_hash = str(leg["tx_hash"]).lower()
        block_number = int(leg["block_number"])
        key = (tx_hash, block_number)
        if key not in receipts:
            receipts[key] = load_fluid_receipt(
                cache,
                tx_hash,
                expected_block=block_number,
                require_evidence=True,
            )
        results.append(
            validate_fluid_leg(
                leg,
                receipts[key],
                pool_constants.get(str(leg["pool"])),
            )
        )
    result_frame = pd.DataFrame(results)
    estimates = validation_summary(result_frame)
    sample_support = (
        legs.groupby(["half_year", "venue_scope"], as_index=False, sort=True)
        .agg(
            population_components=("population_components_in_stratum", "max"),
            population_value_usd=("population_value_usd_in_stratum", "max"),
            sampled_components=("tx_hash", "nunique"),
            sampled_fluid_legs=("log_index", "size"),
        )
    )
    sample_support.insert(0, "record_type", "sample_support")
    support = pd.DataFrame(
        [
            {
                "record_type": "support",
                "sample_design": (
                    "within each half-year: 20 highest-value and 10 rank-spread "
                    "cross-venue components; 10 highest-value and 5 rank-spread "
                    "Fluid-only components; at most one component per transaction"
                ),
                "eligible_population": (
                    "coherent, unambiguous route components containing at least one "
                    "Fluid leg, 2024-10-29 through 2026-06-30"
                ),
                "event_definition": "Swap(bool,uint256,uint256,address)",
                "event_topic": FLUID_SWAP_TOPIC,
                "confirmation_definition": (
                    "the receipt log at the reported event index is emitted by the "
                    "reported Fluid pool; the event direction maps the pool's on-chain "
                    "token0 and token1 identities to the labelled sold and bought "
                    "tokens; Fluid's native-ETH sentinel and WETH are one economic "
                    "asset; and both event amounts reproduce the reported quantities"
                ),
                "precision_denominator": (
                    "legs with the exact Fluid swap event and an evidence-backed "
                    "on-chain pool constants call"
                ),
                "coverage_definition": (
                    "pool-identity-testable legs divided by sampled Fluid legs"
                ),
                "receipt_source": (
                    "eth_getTransactionReceipt with complete logs and historical "
                    "constantsView eth_call"
                ),
                "transfer_note": (
                    "exact ERC-20 Transfer amounts are reported separately because "
                    "Fluid's central liquidity layer can net or combine settlement flows"
                ),
                "wrapped_native_note": (
                    "literal native-ETH pool sides are counted separately and then "
                    "mapped to WETH for the paper's economic-asset route identity"
                ),
                "event_abi_source": (
                    "https://github.com/Instadapp/fluid-contracts-public/blob/main/"
                    "contracts/protocols/dex/poolT1/coreModule/events.sol"
                ),
                "pool_identity_abi_source": (
                    "https://github.com/Instadapp/fluid-contracts-public/blob/main/"
                    "contracts/protocols/dex/interfaces/iDexT1.sol"
                ),
                "calldata_used": False,
            }
        ]
    )
    details = result_frame.copy()
    details.insert(0, "record_type", "leg_check")
    records = [
        *_records(support),
        *_records(sample_support),
        *_records(estimates),
        *_records(details),
    ]
    frame = pd.DataFrame(records)
    _write_jsonl(records, output)
    overall = estimates.loc[estimates["scope"].eq("overall")].iloc[0]
    print(
        f"wrote {int(overall['sampled_fluid_legs']):,} Fluid-leg checks to {output}; "
        f"pool-identity coverage {overall['pool_identity_coverage']:.1%}, "
        f"precision {overall['testable_label_precision']:.1%}"
    )
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--pool-cache", type=Path, default=DEFAULT_POOL_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(
        sample=args.sample,
        cache=args.cache,
        pool_cache=args.pool_cache,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

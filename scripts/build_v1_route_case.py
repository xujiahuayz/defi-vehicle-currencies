#!/usr/bin/env python3
"""Register one verified Uniswap V1 forced route as the deck's authentic trace.

Why this exists. The admitted V1 report (`docs/finding-v1-forced-vehicle.md`,
section 1) verifies the forced-route signature in aggregate: a token-to-token
trade under the V1 mandate materialises as two subgraph rows sharing one
transaction hash, one selling a token for ETH on exchange A and one spending
ETH on a token at exchange B, and the two legs must report the same ETH amount
because the same ETH physically flows between the exchanges. The deck's
appendix frame A6 states that signature but, until this producer existed,
illustrated it with a symbolic glyph. This script selects one real mandate-era
transaction under a deterministic rule, verifies the signature on that
transaction, and emits the registered case manifest plus the presentation
macros the frame consumes, so the trace on the slide is authentic evidence
rather than an illustration.

Selection rule, stated exactly so it cannot be quietly cherry-picked. Scan
every raw V1 swap day strictly before the Uniswap v2 launch (2020-05-05), the
period in which a token-to-token trade had no direct-pool alternative. Keep
transactions with exactly two exchange rows, one carrying a single
ethPurchase event and no tokenPurchase events (token sold for ETH) and one
carrying a single tokenPurchase event and no ethPurchase events (ETH spent on
a token), both ETH legs positive and equal within relative tolerance 1e-9.
Among those, register the transaction with the largest routed ETH amount. The
manifest records the count surviving each filter stage so the rule's bite is
inspectable.

Token identity. The V1 raw fetch carries no token addresses (resolution rate
0%; see the admitted report, section 1), so the manifest identifies the two
exchange contracts and quantities only. The registered case's token
identities are externally verified against the public transaction record and
recorded in the admitted report, not manufactured here.

Reads   data/raw/thegraph/uniswap_v1/uniswap_v1_swaps_YYYYMMDD.jsonl.gz
Writes  output/exhibits/v1_route_case.json
        output/exhibits/v1_route_case_deck_values.tex

Run     ./scripts/run scripts/build_v1_route_case.py [--workers N]
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import stamp
from ddvc.runtime import atomic_output

V1_RAW = REPO_ROOT / "data" / "raw" / "thegraph" / "uniswap_v1"
CASE_MANIFEST = OUTPUT_DIR / "exhibits" / "v1_route_case.json"
DECK_VALUES = OUTPUT_DIR / "exhibits" / "v1_route_case_deck_values.tex"
CODE_SOURCES = ["scripts/build_v1_route_case.py"]

# The V1 mandate ends the day Uniswap v2 went live: from that day a
# token-to-token trade could have a direct pool, so a routed trade is no
# longer architecture-imposed. Strictly-before keeps the perimeter unambiguous.
MANDATE_END = "20200505"
# The routed ETH is identical on both legs by construction, so anything above
# float rounding is a different object (two unrelated bundled swaps).
EXACT_TOL = 1e-9

SCHEMA_VERSION = "dvc-v1-route-case-v1"
SELECTION_RULE = (
    "largest routed ETH among mandate-era transactions with exactly two "
    "exchange rows, one single-event leg in each direction, positive ETH "
    "legs, and relative ETH-leg gap below 1e-9"
)


def _day(path: Path) -> str:
    return path.name.split("_")[-1].split(".")[0]


def _f(x: object) -> float:
    try:
        return float(x)  # noqa: TRY300
    except (TypeError, ValueError):
        return 0.0


def classify_transaction(tx_hash: str, legs: list[dict]) -> dict | None:
    """Return the verified forced-route record for one transaction, or None.

    A qualifying transaction has exactly two exchange rows: one selling a
    token for ETH (a single ethPurchase event, no tokenPurchase events) and
    one spending that ETH on a token (a single tokenPurchase event, no
    ethPurchase events), with positive, exactly matching ETH amounts.
    """

    if len(legs) != 2:
        return None
    sells = [
        r
        for r in legs
        if (r.get("ethPurchaseEvents") or []) and not (r.get("tokenPurchaseEvents") or [])
    ]
    buys = [
        r
        for r in legs
        if (r.get("tokenPurchaseEvents") or []) and not (r.get("ethPurchaseEvents") or [])
    ]
    if len(sells) != 1 or len(buys) != 1:
        return None
    sell_events = sells[0]["ethPurchaseEvents"]
    buy_events = buys[0]["tokenPurchaseEvents"]
    if len(sell_events) != 1 or len(buy_events) != 1:
        return None
    sell_eth = _f(sell_events[0].get("ethAmount"))
    buy_eth = _f(buy_events[0].get("ethAmount"))
    if sell_eth <= 0 or buy_eth <= 0:
        return None
    gap = abs(sell_eth - buy_eth) / max(sell_eth, buy_eth)
    record = {
        "tx_hash": tx_hash,
        "block": int(sells[0].get("block") or 0),
        "timestamp_utc": int(sells[0].get("timestamp") or 0),
        "eth_routed": 0.5 * (sell_eth + buy_eth),
        "leg_relative_gap": gap,
        "eth_leg_strings_equal": (
            str(sell_events[0].get("ethAmount")) == str(buy_events[0].get("ethAmount"))
        ),
        "legs": [
            {
                "step": 1,
                "role": "token_to_eth",
                "exchange": str(sells[0].get("exchangeAddress")),
                "token_amount": str(sell_events[0].get("tokenAmount")),
                "eth_amount": str(sell_events[0].get("ethAmount")),
                "fee_eth": str(sells[0].get("fee")),
            },
            {
                "step": 2,
                "role": "eth_to_token",
                "exchange": str(buys[0].get("exchangeAddress")),
                "eth_amount": str(buy_events[0].get("ethAmount")),
                "token_amount": str(buy_events[0].get("tokenAmount")),
                "fee_eth": str(buys[0].get("fee")),
            },
        ],
    }
    return record


def scan_day(path: Path) -> dict:
    """One raw day: filter-stage counts plus the largest exact-leg candidate."""

    with gzip.open(path, "rt") as fh:
        rows = [json.loads(line) for line in fh]
    by_tx: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tx[str(r.get("id", "")).split("-")[0]].append(r)
    clean = 0
    exact = 0
    best: dict | None = None
    for tx_hash, legs in by_tx.items():
        record = classify_transaction(tx_hash, legs)
        if record is None:
            continue
        clean += 1
        if record["leg_relative_gap"] >= EXACT_TOL:
            continue
        exact += 1
        if best is None or record["eth_routed"] > best["eth_routed"]:
            best = record
    return {
        "date": _day(path),
        "transactions": len(by_tx),
        "clean_two_row_candidates": clean,
        "exact_leg_candidates": exact,
        "best": best,
    }


def select_case(day_results: list[dict]) -> tuple[dict, dict]:
    """Fold per-day scans into the registered case and its stage counts."""

    counts = {
        "files_scanned": len(day_results),
        "transactions_scanned": sum(r["transactions"] for r in day_results),
        "clean_two_row_candidates": sum(
            r["clean_two_row_candidates"] for r in day_results
        ),
        "exact_leg_candidates": sum(r["exact_leg_candidates"] for r in day_results),
    }
    candidates = [r["best"] for r in day_results if r["best"] is not None]
    if not candidates:
        raise ValueError("no exact-leg forced route found in the mandate era")
    case = max(candidates, key=lambda c: c["eth_routed"])
    return case, counts


def verify_case(case: dict) -> dict:
    """Re-state the checks the registered case passed, as explicit fields."""

    legs = case["legs"]
    checks = {
        "two_rows_one_transaction": len(legs) == 2,
        "opposite_directions": {legs[0]["role"], legs[1]["role"]}
        == {"token_to_eth", "eth_to_token"},
        "distinct_exchanges": legs[0]["exchange"] != legs[1]["exchange"],
        "one_event_per_leg": True,
        "eth_leg_relative_gap_below_tolerance": case["leg_relative_gap"] < EXACT_TOL,
        "eth_leg_strings_equal": bool(case["eth_leg_strings_equal"]),
    }
    if not all(checks.values()):
        failed = ", ".join(k for k, v in checks.items() if not v)
        raise ValueError(f"registered case fails verification: {failed}")
    return checks


def build_manifest(case: dict, counts: dict) -> dict:
    moment = datetime.fromtimestamp(case["timestamp_utc"], tz=timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "selection": {
            "perimeter": (
                "uniswap_v1 raw swap days strictly before 2020-05-05, the "
                "period in which the protocol supplied no direct token-to-token pool"
            ),
            "rule": SELECTION_RULE,
            **counts,
        },
        "tx_hash": case["tx_hash"],
        "block": case["block"],
        "timestamp_utc": case["timestamp_utc"],
        "timestamp_iso": moment.isoformat(),
        "date": moment.strftime("%Y-%m-%d"),
        "eth_routed": case["eth_routed"],
        "leg_relative_gap": case["leg_relative_gap"],
        "legs": case["legs"],
        "verification": verify_case(case),
        "token_identity_note": (
            "V1 subgraph records identify exchange contracts, not tokens "
            "(direct resolution rate 0%). The registered case's token "
            "identities are externally verified against the public "
            "transaction record in docs/finding-v1-forced-vehicle.md, "
            "section 1."
        ),
    }


def _group(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", "{,}")


def _group_int(value: int) -> str:
    return f"{value:,}".replace(",", "{,}")


def _short(address_or_hash: str, head: int = 6, tail: int = 4) -> str:
    body = address_or_hash[2:]
    return f"0x{body[:head]}\\ldots {body[-tail:]}"


def render_v1_route_case_deck_values(manifest: dict) -> str:
    """Presentation macros; evidence identity stays in source comments."""

    sell, buy = manifest["legs"]
    if (sell["role"], buy["role"]) != ("token_to_eth", "eth_to_token"):
        raise ValueError("registered case legs are not ordered sell-then-buy")
    moment = datetime.fromtimestamp(manifest["timestamp_utc"], tz=timezone.utc)
    day = moment.strftime("%-d %B %Y")
    lines = [
        "% Generated by scripts/build_v1_route_case.py; do not edit.",
        f"\\newcommand{{\\VOneCaseDate}}{{{day}}}",
        f"\\newcommand{{\\VOneCaseBlock}}{{{_group_int(manifest['block'])}}}",
        f"\\newcommand{{\\VOneCaseEth}}{{{_group(float(sell['eth_amount']))}}}",
        f"\\newcommand{{\\VOneCaseTokenIn}}{{{_group(float(sell['token_amount']), 0)}}}",
        f"\\newcommand{{\\VOneCaseTokenOut}}{{{_group(float(buy['token_amount']))}}}",
        f"\\newcommand{{\\VOneCaseSellExchange}}{{{_short(sell['exchange'])}}}",
        f"\\newcommand{{\\VOneCaseBuyExchange}}{{{_short(buy['exchange'])}}}",
        f"\\newcommand{{\\VOneCaseTx}}{{{manifest['tx_hash']}}}",
        f"\\newcommand{{\\VOneCaseTxShort}}{{{_short(manifest['tx_hash'], 8, 8)}}}",
        (
            "\\newcommand{\\VOneCaseExactCount}"
            f"{{{_group_int(manifest['selection']['exact_leg_candidates'])}}}"
        ),
    ]
    return "\n".join(lines) + "\n"


def run(*, workers: int) -> int:
    files = sorted(
        f
        for f in V1_RAW.glob("uniswap_v1_swaps_*.jsonl.gz")
        if _day(f) < MANDATE_END
    )
    if not files:
        raise FileNotFoundError(f"no mandate-era V1 swap files under {V1_RAW}")
    with ProcessPoolExecutor(workers) as pool:
        day_results = list(pool.map(scan_day, files, chunksize=8))
    case, counts = select_case(day_results)
    manifest = build_manifest(case, counts)
    rendered = render_v1_route_case_deck_values(manifest)

    with atomic_output(CASE_MANIFEST) as temporary:
        temporary.write_text(
            json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    stamp(
        CASE_MANIFEST,
        code_sources=CODE_SOURCES,
        inputs=[V1_RAW],
        notes=(
            "Registered authentic V1 forced-route case selected under the "
            "manifest's deterministic rule; token identities are externally "
            "verified in the admitted V1 report."
        ),
    )
    print(f"wrote {CASE_MANIFEST}")

    with atomic_output(DECK_VALUES) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    stamp(
        DECK_VALUES,
        code_sources=CODE_SOURCES,
        inputs=[CASE_MANIFEST],
        notes=(
            "Presentation macros for the registered V1 forced-route case; "
            "evidence identity stays in deck source comments."
        ),
    )
    print(f"wrote {DECK_VALUES}")
    print(
        json.dumps(
            {
                "tx_hash": manifest["tx_hash"],
                "date": manifest["date"],
                "eth_routed": manifest["eth_routed"],
                **manifest["selection"],
            },
            indent=1,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    return run(workers=args.workers)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build canonical token-level stablecoin supply histories.

Reads retained DeFiLlama catalog and detail payloads, matches records to the
repository's canonical Ethereum token addresses, and keeps both worldwide and
Ethereum circulating amounts.  Same-symbol records do not enter unless their
source address resolves to the canonical Ethereum contract.

Writes
  data/processed/stablecoin_supply_daily.parquet
  output/exhibits/stablecoin_supply_support.jsonl

Run
  ./scripts/run scripts/process/build_stablecoin_supply.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import NON_USD_STABLE, STABLE
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit, write_panel


RAW_DIR = DATA_DIR / "raw" / "external" / "defillama" / "stablecoins"
DETAIL_DIR = RAW_DIR / "details"
PANEL_OUTPUT = DATA_DIR / "processed" / "stablecoin_supply_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits" / "stablecoin_supply_support.jsonl"

MAJOR_SYMBOLS = frozenset({"USDC", "USDT", "DAI"})
ADDRESS_PATTERN = re.compile(r"0x[0-9a-f]{40}")
CODE_SOURCES = ["scripts/process/build_stablecoin_supply.py"]


def source_ethereum_address(value: object) -> str | None:
    """Return a bare Ethereum-shaped address, allowing a source chain prefix."""

    if not isinstance(value, str):
        return None
    suffix = value.strip().casefold().rsplit(":", 1)[-1]
    return suffix if ADDRESS_PATTERN.fullmatch(suffix) else None


def load_detail_payloads(detail_dir: Path) -> list[dict[str, object]]:
    if not detail_dir.is_dir():
        raise FileNotFoundError(detail_dir)
    details: list[dict[str, object]] = []
    for path in sorted(detail_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"stablecoin detail is not an object: {path}")
        details.append(payload)
    if not details:
        raise ValueError("no retained DeFiLlama stablecoin details")
    return details


def select_canonical_details(
    details: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    """Match source records to canonical USD-stable contracts."""

    selected: dict[str, dict[str, object]] = {}
    support: list[dict[str, object]] = []
    for address, symbol in STABLE.items():
        if symbol in NON_USD_STABLE:
            continue
        matches = [
            detail
            for detail in details
            if str(detail.get("symbol", "")).casefold() == symbol.casefold()
            and source_ethereum_address(detail.get("address")) == address.casefold()
            and detail.get("pegType") == "peggedUSD"
            and isinstance(
                (detail.get("chainBalances") or {}).get("Ethereum"), dict
            )
        ]
        if len(matches) > 1:
            raise ValueError(f"multiple exact DeFiLlama matches for {symbol}")
        if matches:
            selected[address.casefold()] = matches[0]
            support.append(
                {
                    "record_type": "stablecoin_supply_mapping",
                    "token_address": address.casefold(),
                    "token_symbol": symbol,
                    "source_id": str(matches[0].get("id")),
                    "source_name": str(matches[0].get("name")),
                    "peg_mechanism": str(matches[0].get("pegMechanism")),
                    "mapping_status": "exact_canonical_address",
                }
            )
        else:
            support.append(
                {
                    "record_type": "stablecoin_supply_mapping",
                    "token_address": address.casefold(),
                    "token_symbol": symbol,
                    "source_id": None,
                    "source_name": None,
                    "peg_mechanism": None,
                    "mapping_status": "no_exact_source_record",
                }
            )
    available_major = {
        str(detail.get("symbol")) for detail in selected.values()
    } & MAJOR_SYMBOLS
    if available_major != MAJOR_SYMBOLS:
        missing = sorted(MAJOR_SYMBOLS - available_major)
        raise ValueError(f"major stablecoin supply mappings are missing: {missing}")
    return selected, support


def _circulating_value(record: dict[str, object]) -> float:
    circulating = record.get("circulating")
    if not isinstance(circulating, dict):
        return float("nan")
    value = circulating.get("peggedUSD")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if np.isfinite(number) and number >= 0 else float("nan")


def _series_frame(records: object, value_name: str) -> pd.DataFrame:
    if not isinstance(records, list):
        return pd.DataFrame(columns=["date", value_name])
    rows: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            timestamp = int(record.get("date"))
        except (TypeError, ValueError):
            continue
        value = _circulating_value(record)
        if not np.isfinite(value):
            continue
        rows.append(
            {
                "date": pd.to_datetime(timestamp, unit="s", utc=True).tz_localize(None),
                value_name: value,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["date", value_name])
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    if frame.duplicated("date").any():
        raise ValueError(f"source supply series has duplicate dates: {value_name}")
    return frame.sort_values("date").reset_index(drop=True)


def parse_detail_supply(
    detail: dict[str, object],
    *,
    token_address: str,
    token_symbol: str,
) -> pd.DataFrame:
    """Align worldwide and Ethereum circulating amounts for one token."""

    global_frame = _series_frame(detail.get("tokens"), "global_circulating")
    ethereum = (detail.get("chainBalances") or {}).get("Ethereum") or {}
    ethereum_frame = _series_frame(
        ethereum.get("tokens"), "ethereum_circulating"
    )
    frame = global_frame.merge(ethereum_frame, on="date", how="outer")
    if frame.empty:
        raise ValueError(f"stablecoin supply series is empty: {token_symbol}")
    frame = frame.sort_values("date").reset_index(drop=True)
    frame.insert(1, "token_address", token_address.casefold())
    frame.insert(2, "token_symbol", token_symbol)
    frame.insert(3, "stablecoin_name", str(detail.get("name")))
    frame.insert(4, "source_id", str(detail.get("id")))
    frame.insert(5, "peg_mechanism", str(detail.get("pegMechanism")))
    frame["supply_source"] = "defillama_stablecoins_api"
    return frame


def build_supply_panel(
    details: list[dict[str, object]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected, support_rows = select_canonical_details(details)
    frames: list[pd.DataFrame] = []
    symbol_by_address = {address.casefold(): symbol for address, symbol in STABLE.items()}
    for address, detail in selected.items():
        frames.append(
            parse_detail_supply(
                detail,
                token_address=address,
                token_symbol=symbol_by_address[address],
            )
        )
    panel = pd.concat(frames, ignore_index=True).sort_values(
        ["token_address", "date"]
    )
    if panel.duplicated(["token_address", "date"]).any():
        raise ValueError("processed stablecoin-supply panel has duplicate token-days")
    if (panel[["global_circulating", "ethereum_circulating"]].dropna() < 0).any().any():
        raise ValueError("processed stablecoin-supply panel has negative circulation")

    support = pd.DataFrame(support_rows)
    observed = (
        panel.groupby(["token_address", "token_symbol"], as_index=False)
        .agg(
            first_date=("date", "min"),
            last_date=("date", "max"),
            source_days=("date", "size"),
            global_days=("global_circulating", "count"),
            ethereum_days=("ethereum_circulating", "count"),
        )
        .assign(record_type="stablecoin_supply_coverage")
    )
    support = pd.concat([support, observed], ignore_index=True, sort=False)
    return panel.reset_index(drop=True), support.reset_index(drop=True)


def run(
    *,
    detail_dir: Path = DETAIL_DIR,
    panel_output: Path = PANEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    details = load_detail_payloads(detail_dir)
    panel, support = build_supply_panel(details)
    inputs = [str(path) for path in sorted(detail_dir.glob("*.json"))]
    write_panel(
        panel,
        panel_output,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="Daily worldwide and Ethereum stablecoin circulation matched to canonical token contracts.",
    )
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=inputs)
    print(
        f"wrote {len(panel):,} token-days for "
        f"{panel['token_address'].nunique():,} stablecoin contracts"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detail-dir", type=Path, default=DETAIL_DIR)
    parser.add_argument("--panel-output", type=Path, default=PANEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        detail_dir=args.detail_dir,
        panel_output=args.panel_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

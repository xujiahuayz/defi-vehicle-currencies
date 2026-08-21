#!/usr/bin/env python3
"""Build canonical token-level stablecoin supply histories.

Reads the retained DeFiLlama catalog, fetch manifest, and detail payloads;
matches records to the repository's canonical Ethereum token addresses; and
keeps both asset-wide and Ethereum-chain circulating amounts.  Same-symbol
records do not enter unless an Ethereum-specific source address resolves to the
canonical contract.

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
CATALOG_INPUT = RAW_DIR / "catalog.json"
MANIFEST_INPUT = RAW_DIR / "manifest.json"
PANEL_OUTPUT = DATA_DIR / "processed" / "stablecoin_supply_daily.parquet"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits" / "stablecoin_supply_support.jsonl"

MAJOR_SYMBOLS = frozenset({"USDC", "USDT", "DAI"})
ADDRESS_PATTERN = re.compile(r"0x[0-9a-f]{40}")
CODE_SOURCES = ["scripts/process/build_stablecoin_supply.py"]


def source_ethereum_address(value: object) -> str | None:
    """Return an address only when the source identifies it as Ethereum.

    DeFiLlama uses an unprefixed address for Ethereum and ``ethereum:`` when a
    prefix is explicit.  A different chain prefix is never stripped: the same
    hexadecimal address can exist on several EVM chains.
    """

    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if ":" not in normalized:
        return normalized if ADDRESS_PATTERN.fullmatch(normalized) else None
    prefix, suffix = normalized.split(":", 1)
    if prefix != "ethereum":
        return None
    return suffix if ADDRESS_PATTERN.fullmatch(suffix) else None


def source_ethereum_address_sources(detail: dict[str, object]) -> dict[str, str]:
    """Return Ethereum addresses and the source field that establishes each."""

    addresses: dict[str, str] = {}
    primary = source_ethereum_address(detail.get("address"))
    if primary is not None:
        raw_primary = str(detail.get("address", "")).strip().casefold()
        addresses[primary] = (
            "ethereum_prefixed_primary_address"
            if raw_primary.startswith("ethereum:")
            else "unprefixed_primary_address_defillama_ethereum_convention"
        )
    ethereum_config = (
        (((detail.get("chainConfig") or {}).get("chains") or {}).get("ethereum"))
        or {}
    )
    issued = ethereum_config.get("issued")
    if isinstance(issued, list):
        for value in issued:
            if isinstance(value, str):
                normalized = value.strip().casefold()
                if ADDRESS_PATTERN.fullmatch(normalized):
                    addresses[normalized] = "ethereum_chain_config"
    return addresses


def source_ethereum_addresses(detail: dict[str, object]) -> frozenset[str]:
    """Return exact Ethereum addresses declared by one source record."""

    return frozenset(source_ethereum_address_sources(detail))


def load_detail_payloads(
    detail_dir: Path,
    *,
    catalog_path: Path = CATALOG_INPUT,
    manifest_path: Path = MANIFEST_INPUT,
) -> tuple[list[dict[str, object]], list[Path]]:
    """Load only detail IDs declared by the matching catalog manifest."""

    if not detail_dir.is_dir():
        raise FileNotFoundError(detail_dir)
    for path in (catalog_path, manifest_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(manifest, dict):
        raise ValueError("stablecoin catalog and manifest must be objects")
    catalog_assets = catalog.get("peggedAssets")
    manifest_ids = manifest.get("detail_ids")
    if not isinstance(catalog_assets, list) or not isinstance(manifest_ids, list):
        raise ValueError("stablecoin catalog or manifest has an invalid schema")
    identifiers = [str(value).strip() for value in manifest_ids]
    if not identifiers or any(not value for value in identifiers):
        raise ValueError("stablecoin manifest has no valid detail IDs")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("stablecoin manifest has duplicate detail IDs")
    catalog_by_id = {
        str(asset.get("id", "")).strip(): asset
        for asset in catalog_assets
        if isinstance(asset, dict) and str(asset.get("id", "")).strip()
    }
    details: list[dict[str, object]] = []
    paths: list[Path] = []
    for identifier in identifiers:
        catalog_asset = catalog_by_id.get(identifier)
        if catalog_asset is None:
            raise ValueError(f"manifest detail ID is absent from catalog: {identifier}")
        path = detail_dir / f"{identifier}.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or str(payload.get("id", "")).strip() != identifier
            or str(payload.get("symbol", "")).casefold()
            != str(catalog_asset.get("symbol", "")).casefold()
        ):
            raise ValueError(f"stablecoin detail does not match catalog: {path}")
        details.append(payload)
        paths.append(path)
    return details, paths


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
            and address.casefold() in source_ethereum_addresses(detail)
            and detail.get("pegType") == "peggedUSD"
            and isinstance(
                (detail.get("chainBalances") or {}).get("Ethereum"), dict
            )
        ]
        if len(matches) > 1:
            raise ValueError(f"multiple exact DeFiLlama matches for {symbol}")
        if matches:
            address_source = source_ethereum_address_sources(matches[0])[
                address.casefold()
            ]
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
                    "mapping_method": address_source,
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
                    "mapping_method": None,
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
    """Align asset-wide and Ethereum-chain circulating amounts for one token."""

    asset_wide_frame = _series_frame(
        detail.get("tokens"), "asset_wide_circulating"
    )
    ethereum = (detail.get("chainBalances") or {}).get("Ethereum") or {}
    ethereum_frame = _series_frame(
        ethereum.get("tokens"), "ethereum_circulating"
    )
    frame = asset_wide_frame.merge(ethereum_frame, on="date", how="outer")
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
    if (
        panel[["asset_wide_circulating", "ethereum_circulating"]].dropna() < 0
    ).any().any():
        raise ValueError("processed stablecoin-supply panel has negative circulation")

    support = pd.DataFrame(support_rows)
    observed = (
        panel.groupby(["token_address", "token_symbol"], as_index=False)
        .agg(
            first_date=("date", "min"),
            last_date=("date", "max"),
            source_days=("date", "size"),
            asset_wide_days=("asset_wide_circulating", "count"),
            ethereum_days=("ethereum_circulating", "count"),
        )
        .assign(record_type="stablecoin_supply_coverage")
    )
    support = pd.concat([support, observed], ignore_index=True, sort=False)
    return panel.reset_index(drop=True), support.reset_index(drop=True)


def run(
    *,
    detail_dir: Path = DETAIL_DIR,
    catalog_path: Path = CATALOG_INPUT,
    manifest_path: Path = MANIFEST_INPUT,
    panel_output: Path = PANEL_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    details, detail_paths = load_detail_payloads(
        detail_dir,
        catalog_path=catalog_path,
        manifest_path=manifest_path,
    )
    panel, support = build_supply_panel(details)
    inputs = [str(catalog_path), str(manifest_path), *(str(path) for path in detail_paths)]
    write_panel(
        panel,
        panel_output,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes=(
            "Daily asset-wide and Ethereum-chain stablecoin circulation matched "
            "to canonical Ethereum token contracts."
        ),
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
    parser.add_argument("--catalog", type=Path, default=CATALOG_INPUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_INPUT)
    parser.add_argument("--panel-output", type=Path, default=PANEL_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        detail_dir=args.detail_dir,
        catalog_path=args.catalog,
        manifest_path=args.manifest,
        panel_output=args.panel_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

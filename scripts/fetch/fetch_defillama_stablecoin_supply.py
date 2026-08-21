#!/usr/bin/env python3
"""Retain DeFiLlama's token-level stablecoin circulation histories.

Writes
  data/raw/external/defillama/stablecoins/catalog.json
  data/raw/external/defillama/stablecoins/manifest.json
  data/raw/external/defillama/stablecoins/details/<id>.json

The catalog identifies plausible records by symbol.  Detail payloads are then
retained for every plausible record so the processor can match the canonical
Ethereum token address and reject same-symbol coins on other chains.  This
program only acquires source records; it does not select an analysis sample.

Run
  ./scripts/run scripts/fetch/fetch_defillama_stablecoin_supply.py
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from ddvc.asset_types import NON_USD_STABLE, STABLE
from ddvc.paths import DATA_DIR
from ddvc.runtime import atomic_output


BASE_URL = "https://stablecoins.llama.fi"
CATALOG_URL = f"{BASE_URL}/stablecoins?includePrices=true"
RAW_DIR = DATA_DIR / "raw" / "external" / "defillama" / "stablecoins"
CATALOG_OUTPUT = RAW_DIR / "catalog.json"
MANIFEST_OUTPUT = RAW_DIR / "manifest.json"
DETAIL_DIR = RAW_DIR / "details"
USER_AGENT = "ddvc-research/1.0"


def fetch_json(url: str, *, timeout: int = 60) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def canonical_usd_symbols() -> frozenset[str]:
    return frozenset(
        symbol.casefold()
        for symbol in STABLE.values()
        if symbol not in NON_USD_STABLE
    )


def candidate_detail_ids(
    catalog: dict[str, object],
    *,
    symbols: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Return every source ID sharing a canonical USD-stable symbol."""

    selected_symbols = (
        canonical_usd_symbols()
        if symbols is None
        else frozenset(str(symbol).casefold() for symbol in symbols)
    )
    assets = catalog.get("peggedAssets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("DeFiLlama stablecoin catalog lacks peggedAssets")
    selected: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        symbol = str(asset.get("symbol", "")).casefold()
        identifier = str(asset.get("id", "")).strip()
        if symbol in selected_symbols and identifier:
            selected.add(identifier)
    if not selected:
        raise ValueError("DeFiLlama catalog has no canonical stablecoin symbols")
    return tuple(sorted(selected, key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value)))


def write_json(payload: object, path: Path) -> None:
    with atomic_output(path) as temporary:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    catalog = fetch_json(CATALOG_URL)
    if not isinstance(catalog, dict):
        raise ValueError("DeFiLlama stablecoin catalog is not an object")
    identifiers = candidate_detail_ids(catalog)
    details: list[tuple[str, object]] = []
    for identifier in identifiers:
        payload = fetch_json(f"{BASE_URL}/stablecoin/{identifier}")
        if not isinstance(payload, dict) or str(payload.get("id")) != identifier:
            raise ValueError(f"DeFiLlama stablecoin detail {identifier} is malformed")
        details.append((identifier, payload))

    # Publish only after every requested detail has arrived and validated.
    write_json(catalog, CATALOG_OUTPUT)
    for identifier, payload in details:
        write_json(payload, DETAIL_DIR / f"{identifier}.json")
    # Write the manifest last.  The processor reads only these IDs, so detail
    # files retained from an earlier catalog cannot enter a later build.
    write_json(
        {
            "schema_version": 1,
            "catalog_url": CATALOG_URL,
            "detail_ids": list(identifiers),
            "canonical_symbols": sorted(canonical_usd_symbols()),
        },
        MANIFEST_OUTPUT,
    )
    print(
        f"retained DeFiLlama stablecoin catalog and {len(details):,} "
        f"same-symbol detail records under {RAW_DIR}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

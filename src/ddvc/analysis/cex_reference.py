"""Address-resolved positive CEX-reference support from a published source package."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pandas as pd


WETH_WITHOUT_PREFIX = "c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
AUTHOR_EXCLUDED_TICKERS = frozenset({"BONDETH", "PROSETH"})
EXPECTED_PUBLISHED_PAIRS = 43
PACKAGE_FILES = {
    "symbols": "CodePackage/sym.csv",
    "exchange_info": "CodePackage/dfBinanceInfo_122022.csv",
    "observations": "CodePackage/binance2.csv",
}


def _address(value: object) -> str:
    address = str(value).strip().lower().removeprefix("0x")
    if len(address) != 40 or any(character not in "0123456789abcdef" for character in address):
        raise ValueError(f"invalid Ethereum token address in CEX support source: {value!r}")
    return f"0x{address}"


def _non_weth_address(row: pd.Series) -> str:
    token0 = str(row["token0"]).strip().lower().removeprefix("0x")
    token1 = str(row["token1"]).strip().lower().removeprefix("0x")
    if (token0 == WETH_WITHOUT_PREFIX) == (token1 == WETH_WITHOUT_PREFIX):
        raise ValueError(
            f"published CEX comparison pair {row['ticker']!r} does not contain exactly one WETH leg"
        )
    return _address(token1 if token0 == WETH_WITHOUT_PREFIX else token0)


def build_cex_reference_support(package: Path) -> pd.DataFrame:
    """Reproduce the paper's 43 exact-address Uniswap--Binance matches.

    Presence establishes positive CEX reference-price support only. The sampled
    first and last observations conservatively bound a period in which the pair
    was observed; absence from this selected package never establishes that a
    token was unlisted.
    """

    with ZipFile(package) as archive:
        symbols = pd.read_csv(archive.open(PACKAGE_FILES["symbols"]))
        exchange_info = pd.read_csv(archive.open(PACKAGE_FILES["exchange_info"]))
        observations = pd.read_csv(
            archive.open(PACKAGE_FILES["observations"]),
            usecols=["symbol", "startDate"],
        )

    required_symbols = {
        "ticker", "token", "token0", "token1", "exchange", "creationdate",
        "ethreserve", "volume", "nrow", "daysoperation",
    }
    missing = required_symbols - set(symbols.columns)
    if missing:
        raise ValueError(f"published symbol crosswalk lacks columns: {sorted(missing)}")
    required_info = {"symbol", "baseAsset", "quoteAsset"}
    missing = required_info - set(exchange_info.columns)
    if missing:
        raise ValueError(f"published exchange snapshot lacks columns: {sorted(missing)}")

    selected = symbols[
        pd.to_numeric(symbols["ethreserve"], errors="coerce").gt(10)
        & pd.to_numeric(symbols["volume"], errors="coerce").gt(10)
    ].copy()
    selected["observations_per_day"] = (
        pd.to_numeric(selected["nrow"], errors="raise")
        / pd.to_numeric(selected["daysoperation"], errors="raise")
    )
    selected = selected.sort_values(
        ["ticker", "observations_per_day", "exchange"],
        ascending=[True, False, True],
        kind="stable",
    ).drop_duplicates("ticker", keep="first")
    selected = selected[~selected["ticker"].isin(AUTHOR_EXCLUDED_TICKERS)]

    identities = exchange_info[["symbol", "baseAsset", "quoteAsset"]].drop_duplicates()
    ambiguous = identities.groupby("symbol").size()
    ambiguous = ambiguous[ambiguous.ne(1)]
    if not ambiguous.empty:
        raise ValueError(
            f"published exchange snapshot has ambiguous symbol identities: {ambiguous.index[:3].tolist()}"
        )

    observations["startDate"] = pd.to_datetime(observations["startDate"], errors="raise")
    observed = observations.groupby("symbol", as_index=False).agg(
        binance_sample_first_at=("startDate", "min"),
        binance_sample_last_at=("startDate", "max"),
        binance_sample_rows=("startDate", "size"),
    )
    result = (
        selected.merge(identities, left_on="ticker", right_on="symbol", validate="one_to_one")
        .merge(observed, left_on="ticker", right_on="symbol", validate="one_to_one")
    )
    result["token_address"] = result.apply(_non_weth_address, axis=1)
    result["dex_pool"] = result["exchange"].map(_address)
    result["source_dex_creation_at"] = pd.to_datetime(result["creationdate"], errors="raise")
    result["support_definition"] = "positive_observed_uniswap_binance_reference_support"
    result["source_publication"] = "Lehar and Parlour (2025), Journal of Finance"

    output = result.rename(
        columns={
            "token": "token_symbol",
            "ticker": "binance_symbol",
            "baseAsset": "binance_base_asset",
            "quoteAsset": "binance_quote_asset",
            "ethreserve": "source_eth_reserve",
            "volume": "source_eth_volume",
        }
    )[
        [
            "token_address",
            "token_symbol",
            "dex_pool",
            "binance_symbol",
            "binance_base_asset",
            "binance_quote_asset",
            "source_dex_creation_at",
            "binance_sample_first_at",
            "binance_sample_last_at",
            "binance_sample_rows",
            "source_eth_reserve",
            "source_eth_volume",
            "support_definition",
            "source_publication",
        ]
    ].sort_values("token_address", kind="stable").reset_index(drop=True)

    if len(output) != EXPECTED_PUBLISHED_PAIRS:
        raise ValueError(
            f"published CEX support perimeter changed: {len(output)} rows, "
            f"expected {EXPECTED_PUBLISHED_PAIRS}"
        )
    if output["token_address"].duplicated().any() or output["binance_symbol"].duplicated().any():
        raise ValueError("published CEX support perimeter is not one token per Binance pair")
    if (output["binance_sample_first_at"] > output["binance_sample_last_at"]).any():
        raise ValueError("published CEX support observation bounds are reversed")
    return output

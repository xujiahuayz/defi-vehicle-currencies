from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from ddvc.analysis import cex_reference


WETH = cex_reference.WETH_WITHOUT_PREFIX


def write_package(path: Path, *, invalid_pair: bool = False) -> None:
    symbols = pd.DataFrame(
        [
            {
                "ticker": "GOODETH", "token": "GOOD", "token0": "1" * 40,
                "token1": WETH, "exchange": "a" * 40, "creationdate": "2020-01-01",
                "ethreserve": 20, "volume": 20, "nrow": 200, "daysoperation": 10,
            },
            {
                "ticker": "GOODETH", "token": "DECOY", "token0": "2" * 40,
                "token1": WETH, "exchange": "b" * 40, "creationdate": "2020-01-02",
                "ethreserve": 20, "volume": 20, "nrow": 10, "daysoperation": 10,
            },
            {
                "ticker": "LOWETH", "token": "LOW", "token0": "3" * 40,
                "token1": WETH, "exchange": "c" * 40, "creationdate": "2020-01-03",
                "ethreserve": 9, "volume": 20, "nrow": 100, "daysoperation": 10,
            },
            {
                "ticker": "PROSETH", "token": "PROS", "token0": "4" * 40,
                "token1": WETH, "exchange": "d" * 40, "creationdate": "2020-01-04",
                "ethreserve": 20, "volume": 20, "nrow": 100, "daysoperation": 10,
            },
        ]
    )
    if invalid_pair:
        symbols.loc[symbols["ticker"].eq("GOODETH"), "token1"] = "5" * 40
    exchange_info = pd.DataFrame(
        [
            {"symbol": "GOODETH", "baseAsset": "GOOD", "quoteAsset": "ETH"},
            {"symbol": "LOWETH", "baseAsset": "LOW", "quoteAsset": "ETH"},
            {"symbol": "PROSETH", "baseAsset": "PROS", "quoteAsset": "ETH"},
        ]
    )
    observations = pd.DataFrame(
        [
            {"symbol": "GOODETH", "startDate": "2020-02-01"},
            {"symbol": "GOODETH", "startDate": "2020-03-01"},
            {"symbol": "LOWETH", "startDate": "2020-02-01"},
            {"symbol": "PROSETH", "startDate": "2020-02-01"},
        ]
    )
    with ZipFile(path, "w") as archive:
        for name, frame in (
            (cex_reference.PACKAGE_FILES["symbols"], symbols),
            (cex_reference.PACKAGE_FILES["exchange_info"], exchange_info),
            (cex_reference.PACKAGE_FILES["observations"], observations),
        ):
            archive.writestr(name, frame.to_csv(index=False))


def test_cex_reference_is_positive_support_with_exact_address_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "source.zip"
    write_package(package)
    monkeypatch.setattr(cex_reference, "EXPECTED_PUBLISHED_PAIRS", 1)

    result = cex_reference.build_cex_reference_support(package)

    assert result["token_address"].tolist() == ["0x" + "1" * 40]
    assert result["binance_symbol"].tolist() == ["GOODETH"]
    assert result["binance_sample_rows"].tolist() == [2]
    assert result["binance_sample_first_at"].tolist() == [pd.Timestamp("2020-02-01")]
    assert result["binance_sample_last_at"].tolist() == [pd.Timestamp("2020-03-01")]
    assert set(result["support_definition"]) == {
        "positive_observed_uniswap_binance_reference_support"
    }


def test_cex_reference_rejects_a_pair_without_exactly_one_weth_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "source.zip"
    write_package(package, invalid_pair=True)
    monkeypatch.setattr(cex_reference, "EXPECTED_PUBLISHED_PAIRS", 1)

    with pytest.raises(ValueError, match="exactly one WETH leg"):
        cex_reference.build_cex_reference_support(package)

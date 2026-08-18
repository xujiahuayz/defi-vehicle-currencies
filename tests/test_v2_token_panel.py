from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts.process import build_v2_token_panel as builder
from scripts.process.build_v2_token_panel import one_swaps_day, token_decimals


def canonical_state() -> pd.DataFrame:
    common = {
        "token0": "0x0",
        "token1": "0x1",
        "symbol0": "ZERO",
        "symbol1": "ONE",
        "decimals0": 6,
        "decimals1": 18,
    }
    return pd.DataFrame(
        [
            {
                **common,
                "record_type": "swap",
                "amount0_delta": "-2",
                "amount1_delta": "1",
                "value_usd": "100",
            },
            {
                **common,
                "record_type": "swap",
                "amount0_delta": "-4",
                "amount1_delta": "2",
                "value_usd": "200",
            },
            {
                **common,
                "record_type": "swap",
                "amount0_delta": "-1",
                "amount1_delta": "0.5",
                "value_usd": "10",
            },
            {
                **common,
                "record_type": "snapshot",
                "amount0_delta": None,
                "amount1_delta": None,
                "value_usd": "0",
            },
        ]
    )


class Release:
    def read_day(self, day: str) -> pd.DataFrame:
        assert day == "20250101"
        return canonical_state()


def test_price_and_pair_panels_consume_canonical_state() -> None:

    result = one_swaps_day("20250101", Release())

    assert result is not None
    assert result["n_swaps"] == 3
    assert result["price_obs_dropped_small"] == 1
    prices = {row["token"]: row["price_usd"] for row in result["_px"]}
    assert prices == {"0x0": pytest.approx(50.0), "0x1": pytest.approx(100.0)}
    assert result["_pairs"][0]["n_swaps"] == 3


def test_decimals_cover_tokens_in_small_swaps_too() -> None:
    result = one_swaps_day("20250101", Release())
    assert result is not None
    decimals = token_decimals(pd.DataFrame(result["_px"]))
    assert dict(zip(decimals["token"], decimals["decimals"], strict=True)) == {
        "0x0": 6,
        "0x1": 18,
    }


def test_decimals_conflict_is_a_hard_failure() -> None:
    token_days = pd.DataFrame(
        {
            "token": ["0x0", "0x0"],
            "decimals": [6, 18],
            "symbol": ["ZERO", "ZERO"],
        }
    )
    with pytest.raises(RuntimeError, match="disagrees on decimals"):
        token_decimals(token_days)


def test_input_mutation_during_v2_publication_preserves_prior_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "released-state.parquet"
    source.write_bytes(b"released")
    outputs = [tmp_path / name for name in ("price.parquet", "decimals.parquet", "pairs.parquet")]
    for output in outputs:
        pd.DataFrame({"prior": [1]}).to_parquet(output, index=False)
    prior = [output.read_bytes() for output in outputs]

    class MutatedDuringStamp:
        def __call__(self, _staged_path: Path) -> None:
            raise RuntimeError("state input changed during publication")

    monkeypatch.setattr(builder, "OUT_PRICE", outputs[0])
    monkeypatch.setattr(builder, "OUT_DEC", outputs[1])
    monkeypatch.setattr(builder, "OUT_PAIR", outputs[2])
    monkeypatch.setattr(builder, "validate_before_install", lambda *_releases: MutatedDuringStamp())
    release = SimpleNamespace(
        input_paths=(source,),
        label="a" * 64,
    )

    with pytest.raises(RuntimeError, match="changed during publication"):
        builder._publish_panels(
            pd.DataFrame({"value": [2]}),
            pd.DataFrame({"value": [2]}),
            pd.DataFrame({"value": [2]}),
            release,
        )

    assert [output.read_bytes() for output in outputs] == prior


def test_v2_publication_reuses_canonical_panel_lifecycle() -> None:
    source = Path(builder.__file__).read_text(encoding="utf-8")
    assert source.count("write_panel(") == 1
    assert "preinstall_validator=validator" in source

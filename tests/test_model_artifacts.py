from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.model_artifacts import (
    attach_spec_ids,
    model_artifact_context,
    require_released_model_inputs,
)


def test_direct_model_inputs_must_exist_and_remain_stable(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pd.DataFrame({"value": [1]}).to_parquet(source, index=False)
    context = model_artifact_context(root=tmp_path)

    with require_released_model_inputs(
        context,
        [source],
        root=tmp_path,
        consumer="direct model input test",
    ) as inputs:
        assert list(inputs) == [source]

    missing = tmp_path / "missing.parquet"
    with pytest.raises(FileNotFoundError, match="missing input"):
        with require_released_model_inputs(
            context,
            [missing],
            root=tmp_path,
            consumer="direct model input test",
        ):
            pass


def test_direct_model_input_replacement_during_read_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    pd.DataFrame({"value": [1]}).to_parquet(source, index=False)
    context = model_artifact_context(root=tmp_path)

    with pytest.raises(RuntimeError, match="changed while being read"):
        with require_released_model_inputs(
            context,
            [source],
            root=tmp_path,
            consumer="direct model input test",
        ):
            pd.DataFrame({"value": [2, 3]}).to_parquet(source, index=False)


def test_spec_ids_are_readable_and_unique_to_substantive_fields() -> None:
    frame = pd.DataFrame(
        {
            "direction": ["route_to_capital", "capital_to_route"],
            "horizon": [7, 7],
        }
    )
    identified = attach_spec_ids(
        frame,
        prefix="liquidity capital",
        columns=("direction", "horizon"),
    )
    assert identified["spec_id"].tolist() == [
        "liquidity-capital.route-to-capital.7",
        "liquidity-capital.capital-to-route.7",
    ]

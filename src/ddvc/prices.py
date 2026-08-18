"""Canonical token-price estimates used by route and liquidity analyses."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ddvc.paths import TOKEN_PRICE_DAILY_PANEL
from ddvc.workflow import current_inputs

PRICE_COLUMNS = [
    "token_in",
    "token_out",
    "token_in_sym",
    "token_out_sym",
    "amount_in",
    "amount_out",
    "amount_usd",
]
MIN_PRICE_OBSERVATIONS = 3
PRICE_CONSENSUS_FACTOR = 5.0
PRICE_CONSENSUS_SHARE = 0.75
PRICE_PANEL_COLUMNS = [
    "token",
    "symbol",
    "price_usd",
    "n_observations",
    "n_consensus",
    "consensus_share",
    "gross_weight_usd",
    "consensus_weight_usd",
    "price_source",
    "validation_status",
]
CANONICAL_TOKEN_PRICE_COLUMNS = ["day", *PRICE_PANEL_COLUMNS]
def load_canonical_token_prices(
    path: str | Path = TOKEN_PRICE_DAILY_PANEL,
    *,
    columns: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Read the direct address-day price panel and enforce its value contract."""

    source = Path(path)
    selected = tuple(CANONICAL_TOKEN_PRICE_COLUMNS if columns is None else columns)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("canonical token-price columns must be nonempty and unique")
    unknown = sorted(set(selected) - set(CANONICAL_TOKEN_PRICE_COLUMNS))
    if unknown:
        raise ValueError(f"canonical token-price columns are unknown: {unknown}")
    with current_inputs(
        [source], consumer="canonical address-day token prices"
    ):
        if tuple(pq.ParquetFile(source).schema_arrow.names) != tuple(CANONICAL_TOKEN_PRICE_COLUMNS):
            raise ValueError("canonical token-price panel schema is stale")
        validation_columns = list(CANONICAL_TOKEN_PRICE_COLUMNS)
        frame = pd.read_parquet(source, columns=validation_columns)
    if frame.empty or frame.duplicated(["day", "token"]).any():
        raise ValueError("canonical token-price panel is empty or duplicated")
    day = frame["day"].astype(str)
    token = frame["token"].astype(str)
    numeric = frame[
        [
            "price_usd",
            "n_observations",
            "n_consensus",
            "consensus_share",
            "gross_weight_usd",
            "consensus_weight_usd",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    invalid = (
        ~day.str.fullmatch(r"\d{8}")
        | token.eq("")
        | token.ne(token.str.lower())
        | ~np.isfinite(numeric["price_usd"])
        | numeric["price_usd"].le(0)
        | numeric["n_observations"].lt(3)
        | numeric["n_consensus"].lt(3)
        | numeric["consensus_share"].lt(0.75)
        | numeric["consensus_share"].gt(1)
        | numeric["gross_weight_usd"].le(0)
        | numeric["consensus_weight_usd"].le(0)
        | numeric["consensus_weight_usd"].gt(
            numeric["gross_weight_usd"]
            + np.maximum(1e-6, numeric["gross_weight_usd"] * 1e-12)
        )
        | frame["price_source"].ne("canonical_repriced_route_legs")
        | frame["validation_status"].ne("minimum_observations_and_price_consensus_passed")
    )
    if invalid.any():
        raise ValueError("canonical token-price panel violates its identity, support, or value contract")
    return frame.loc[:, list(selected)].copy()


def day_price_frame(legs: pd.DataFrame) -> pd.DataFrame:
    """Return auditable consensus-screened day prices by token address."""

    missing = sorted(set(PRICE_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"day prices are missing columns: {', '.join(missing)}")
    rows = []
    for side in ("in", "out"):
        amount = pd.to_numeric(legs[f"amount_{side}"], errors="coerce").replace(0, np.nan)
        value = pd.to_numeric(legs["amount_usd"], errors="coerce")
        rows.append(
            pd.DataFrame(
                {
                    "token": legs[f"token_{side}"].astype(str).str.lower(),
                    "symbol": legs[f"token_{side}_sym"],
                    "price": value / amount,
                    "weight": value,
                }
            )
        )
    data = pd.concat(rows, ignore_index=True)
    data = data[
        np.isfinite(data["price"])
        & data["price"].gt(0)
        & data["price"].lt(1_000_000)
        & np.isfinite(data["weight"])
        & data["weight"].gt(0)
    ]
    prices: list[dict[str, object]] = []
    for token, group in data.groupby("token"):
        if len(group) < MIN_PRICE_OBSERVATIONS:
            continue
        ordinary_median = float(group["price"].median())
        consensus = group["price"].between(
            ordinary_median / PRICE_CONSENSUS_FACTOR,
            ordinary_median * PRICE_CONSENSUS_FACTOR,
            inclusive="both",
        )
        if (
            int(consensus.sum()) < MIN_PRICE_OBSERVATIONS
            or float(consensus.mean()) < PRICE_CONSENSUS_SHARE
        ):
            continue
        ordered = group[consensus].sort_values("price")
        weights = ordered["weight"].clip(lower=1e-9).to_numpy()
        cumulative = np.cumsum(weights) / weights.sum()
        price = float(ordered["price"].to_numpy()[np.searchsorted(cumulative, 0.5)])
        mode = ordered["symbol"].mode()
        symbol = str(mode.iloc[0]) if not mode.empty else str(token)[:8]
        prices.append(
            {
                "token": str(token),
                "symbol": symbol,
                "price_usd": price,
                "n_observations": int(len(group)),
                "n_consensus": int(consensus.sum()),
                "consensus_share": float(consensus.mean()),
                "gross_weight_usd": float(group["weight"].sum()),
                "consensus_weight_usd": float(ordered["weight"].sum()),
                "price_source": "canonical_repriced_route_legs",
                "validation_status": "minimum_observations_and_price_consensus_passed",
            }
        )
    return pd.DataFrame(prices, columns=PRICE_PANEL_COLUMNS)


def day_prices(legs: pd.DataFrame) -> dict[str, tuple[str, float]]:
    """Return consensus-screened, volume-weighted day prices by token address."""

    frame = day_price_frame(legs)
    return {
        str(row.token): (str(row.symbol), float(row.price_usd))
        for row in frame.itertuples(index=False)
    }

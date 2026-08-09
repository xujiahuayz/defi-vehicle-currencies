"""Canonical token-price estimates used by route and liquidity analyses."""

from __future__ import annotations

import numpy as np
import pandas as pd

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

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
MAX_INTRADAY_MARK_LAG_SECONDS = 300


def attach_strictly_prior_weth_usd(
    targets: pd.DataFrame,
    marks: pd.DataFrame,
    *,
    max_lag_seconds: int = MAX_INTRADAY_MARK_LAG_SECONDS,
) -> pd.DataFrame:
    """Attach one independently observed WETH/USD mark strictly before each target."""
    target_required = {"timestamp_utc"}
    mark_required = (
        "available_at_utc",
        "weth_usd",
        "price_source",
        "validation_status",
    )
    target_missing = sorted(target_required - set(targets.columns))
    mark_missing = sorted(set(mark_required) - set(marks.columns))
    if target_missing:
        raise ValueError(f"price-mark targets lack columns: {target_missing}")
    if mark_missing:
        raise ValueError(f"intraday WETH/USD marks lack columns: {mark_missing}")
    if max_lag_seconds < 1:
        raise ValueError("maximum intraday price-mark lag must be positive")

    right = marks[list(mark_required)].copy()
    right["available_at_utc"] = pd.to_numeric(
        right["available_at_utc"], errors="raise"
    ).astype("int64")
    right["weth_usd"] = pd.to_numeric(right["weth_usd"], errors="coerce")
    if right["available_at_utc"].duplicated().any():
        raise ValueError("intraday WETH/USD marks contain duplicate availability times")
    if not right["validation_status"].eq("valid").all():
        raise ValueError("intraday WETH/USD marks contain unreleased observations")
    if right["price_source"].astype(str).str.strip().eq("").any():
        raise ValueError("intraday WETH/USD marks contain an empty price source")
    if (~np.isfinite(right["weth_usd"]) | right["weth_usd"].le(0)).any():
        raise ValueError("intraday WETH/USD marks contain invalid prices")
    right = right.rename(
        columns={
            "available_at_utc": "eth_usd_mark_available_at_utc",
            "weth_usd": "eth_usd",
            "price_source": "eth_usd_price_source",
            "validation_status": "eth_usd_validation_status",
        }
    ).sort_values("eth_usd_mark_available_at_utc")

    left = targets.copy()
    left["timestamp_utc"] = pd.to_numeric(
        left["timestamp_utc"], errors="raise"
    ).astype("int64")
    left["_price_mark_row_order"] = np.arange(len(left))
    joined = pd.merge_asof(
        left.sort_values("timestamp_utc"),
        right,
        left_on="timestamp_utc",
        right_on="eth_usd_mark_available_at_utc",
        direction="backward",
        allow_exact_matches=False,
    )
    joined["eth_usd_mark_lag_seconds"] = (
        joined["timestamp_utc"] - joined["eth_usd_mark_available_at_utc"]
    )
    supported = (
        joined["eth_usd"].notna()
        & joined["eth_usd_mark_lag_seconds"].gt(0)
        & joined["eth_usd_mark_lag_seconds"].le(max_lag_seconds)
    )
    if not supported.all():
        raise RuntimeError(
            "intraday WETH/USD support changed the target perimeter: "
            f"{int((~supported).sum()):,} of {len(joined):,} targets lack a valid "
            f"strictly prior mark within {max_lag_seconds} seconds"
        )
    return (
        joined.sort_values("_price_mark_row_order")
        .drop(columns="_price_mark_row_order")
        .reset_index(drop=True)
    )


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

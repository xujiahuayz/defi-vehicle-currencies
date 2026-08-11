"""Canonical token-price estimates used by route and liquidity analyses."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ddvc.fetch.coinbase_prices import SOURCE_ID as EXTERNAL_WETH_USD_SOURCE_ID
from ddvc.artifact_release import file_sha256, file_stat_identity
from ddvc.paths import TOKEN_PRICE_DAILY_PANEL
from ddvc.provenance import require_current_artifacts, sidecar_path

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
MAX_INTRADAY_MARK_LAG_SECONDS = 60
INTRADAY_WETH_USD_MARK_COLUMNS = [
    "bucket_start_utc",
    "bucket_end_utc",
    "available_at_utc",
    "weth_usd",
    "price_source",
    "validation_status",
]


def load_canonical_token_prices(
    path: str | Path = TOKEN_PRICE_DAILY_PANEL,
    *,
    columns: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Reopen the provenance-current address-day price owner and its value contract."""

    source = Path(path)
    sidecar = sidecar_path(source)
    require_current_artifacts([source], consumer="canonical address-day token prices")
    before_identity = (file_stat_identity(source), file_stat_identity(sidecar))
    before_sha256 = (file_sha256(source), file_sha256(sidecar))
    require_current_artifacts([source], consumer="canonical address-day token prices")
    if before_identity != (file_stat_identity(source), file_stat_identity(sidecar)) or before_sha256 != (file_sha256(source), file_sha256(sidecar)):
        raise RuntimeError(f"canonical token-price provenance changed during admission: {source}")
    content_sha256 = before_sha256[0]
    selected = tuple(CANONICAL_TOKEN_PRICE_COLUMNS if columns is None else columns)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("canonical token-price columns must be nonempty and unique")
    unknown = sorted(set(selected) - set(CANONICAL_TOKEN_PRICE_COLUMNS))
    if unknown:
        raise ValueError(f"canonical token-price columns are unknown: {unknown}")
    if tuple(pq.ParquetFile(source).schema_arrow.names) != tuple(CANONICAL_TOKEN_PRICE_COLUMNS):
        raise ValueError("canonical token-price panel schema is stale")
    validation_columns = list(CANONICAL_TOKEN_PRICE_COLUMNS)
    frame = pd.read_parquet(source, columns=validation_columns)
    if before_identity != (file_stat_identity(source), file_stat_identity(sidecar)) or before_sha256 != (file_sha256(source), file_sha256(sidecar)):
        raise RuntimeError(f"canonical token-price panel or provenance mutated during read: {source}")
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
    selected_frame = frame.loc[:, list(selected)].copy()
    selected_frame.attrs["content_sha256"] = content_sha256
    return selected_frame


def load_intraday_weth_usd_marks(
    source,
    targets: pd.DataFrame,
    *,
    max_lag_seconds: int = MAX_INTRADAY_MARK_LAG_SECONDS,
    timestamp_column: str = "timestamp_utc",
) -> pd.DataFrame:
    """Read only the Parquet interval capable of supporting the target clock."""

    if isinstance(source, pd.DataFrame):
        return source.copy()
    if timestamp_column not in targets:
        raise ValueError(f"price-mark targets lack column: {timestamp_column}")
    timestamp = pd.to_numeric(targets[timestamp_column], errors="raise").astype("int64")
    if timestamp.empty:
        return pd.DataFrame(columns=INTRADAY_WETH_USD_MARK_COLUMNS)
    return pd.read_parquet(
        source,
        columns=INTRADAY_WETH_USD_MARK_COLUMNS,
        filters=[
            ("available_at_utc", ">=", int(timestamp.min()) - max_lag_seconds),
            ("available_at_utc", "<", int(timestamp.max())),
        ],
    )


def attach_strictly_prior_weth_usd(
    targets: pd.DataFrame,
    marks: pd.DataFrame,
    *,
    max_lag_seconds: int = MAX_INTRADAY_MARK_LAG_SECONDS,
    timestamp_column: str = "timestamp_utc",
) -> pd.DataFrame:
    """Attach one independently observed WETH/USD mark strictly before each target."""
    target_required = {timestamp_column}
    mark_required = INTRADAY_WETH_USD_MARK_COLUMNS
    target_missing = sorted(target_required - set(targets.columns))
    mark_missing = sorted(set(mark_required) - set(marks.columns))
    if target_missing:
        raise ValueError(f"price-mark targets lack columns: {target_missing}")
    if mark_missing:
        raise ValueError(f"intraday WETH/USD marks lack columns: {mark_missing}")
    if max_lag_seconds < 1:
        raise ValueError("maximum intraday price-mark lag must be positive")

    right = marks[mark_required].copy()
    for column in ("bucket_start_utc", "bucket_end_utc", "available_at_utc"):
        right[column] = pd.to_numeric(right[column], errors="raise").astype("int64")
    right["weth_usd"] = pd.to_numeric(right["weth_usd"], errors="coerce")
    if right["available_at_utc"].duplicated().any():
        raise ValueError("intraday WETH/USD marks contain duplicate availability times")
    if not (
        right["bucket_end_utc"].eq(right["available_at_utc"])
        & right["bucket_end_utc"].sub(right["bucket_start_utc"]).eq(60)
    ).all():
        raise ValueError("intraday WETH/USD marks have an invalid availability clock")
    if not right["validation_status"].eq("valid").all():
        raise ValueError("intraday WETH/USD marks contain unreleased observations")
    if not right["price_source"].eq(EXTERNAL_WETH_USD_SOURCE_ID).all():
        raise ValueError("intraday WETH/USD marks do not use the canonical external source")
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
    left[timestamp_column] = pd.to_numeric(
        left[timestamp_column], errors="raise"
    ).astype("int64")
    left["_price_mark_row_order"] = np.arange(len(left))
    joined = pd.merge_asof(
        left.sort_values(timestamp_column),
        right,
        left_on=timestamp_column,
        right_on="eth_usd_mark_available_at_utc",
        direction="backward",
        allow_exact_matches=False,
    )
    joined["eth_usd_mark_lag_seconds"] = (
        joined[timestamp_column] - joined["eth_usd_mark_available_at_utc"]
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

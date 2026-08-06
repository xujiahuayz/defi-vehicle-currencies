"""Causally ordered marginal-price states for block-timing diagnostics."""

from __future__ import annotations

import bisect
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path

Q96 = 1 << 96
SwapState = tuple[int, int, int, int, float]


def load_v3_swap_day(
    path: Path,
) -> tuple[dict[str, tuple[str, str]], dict[str, list[SwapState]]]:
    """Load token identities and post-swap states in block-log order."""
    tokens: dict[str, tuple[str, str]] = {}
    series: dict[str, list[SwapState]] = defaultdict(list)
    if not path.exists():
        return tokens, series
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            pool = row.get("pool") or {}
            pool_id = str(pool.get("id") or "").lower()
            token0 = str((pool.get("token0") or {}).get("id") or "").lower()
            token1 = str((pool.get("token1") or {}).get("id") or "").lower()
            try:
                block = int((row.get("transaction") or {}).get("blockNumber") or 0)
                log_index = int(row.get("logIndex") or 0)
                timestamp = int(row.get("timestamp") or 0)
                sqrt_price_x96 = int(row.get("sqrtPriceX96") or 0)
            except (TypeError, ValueError):
                continue
            if not (
                pool_id
                and token0
                and token1
                and block
                and timestamp
                and sqrt_price_x96 > 0
            ):
                continue
            tokens[pool_id] = (token0, token1)
            series[pool_id].append(
                (
                    block,
                    log_index,
                    timestamp,
                    timestamp // 3600,
                    2.0 * math.log(sqrt_price_x96 / Q96),
                )
            )
    for pool_id in series:
        series[pool_id].sort()
    return tokens, series


class PoolView:
    """Strict pre-event state and end-of-hour state for one pool."""

    def __init__(self, sequence: list[SwapState]) -> None:
        self.orders = [
            (block, log_index)
            for block, log_index, _timestamp, _hour, _price in sequence
        ]
        self.logp = [price for _block, _log, _timestamp, _hour, price in sequence]
        self.by_hour: dict[int, float] = {}
        self.hour_end_ts: dict[int, int] = {}
        for _block, _log, timestamp, hour, price in sequence:
            self.by_hour[hour] = price
            self.hour_end_ts[hour] = timestamp

    def before(self, block: int, log_index: int) -> float | None:
        """Return the last post-swap state strictly before the target event."""
        index = bisect.bisect_left(self.orders, (block, log_index)) - 1
        return self.logp[index] if index >= 0 else None

    def at_hour(self, hour: int) -> float | None:
        return self.by_hour.get(hour)


def oriented(
    log_price: float,
    token0: str,
    token1: str,
    token_in: str,
    token_out: str,
) -> float | None:
    """Orient log token1/token0 as log output units per input unit."""
    if token0 == token_in and token1 == token_out:
        return log_price
    if token0 == token_out and token1 == token_in:
        return -log_price
    return None

"""Causal classification, valuation, and candidate allocation for V3 LP flows."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.pricing.v3pools import (
    derive_fee_tier,
    record_token_decimals,
    resolve_decimals,
    tick_spacing_for_fee,
)


MAX_EVENT_VALUE_USD = 1_000_000_000.0
NEAR_RANGE_SPACINGS = 20
Q96 = 1 << 96
ANCHOR_PRIORITY = {"USDC": 0, "USDT": 1, "DAI": 2, "WETH": 3, "WBTC": 4}


@dataclass(frozen=True)
class PriorTickState:
    pool: str
    token0: str
    token1: str
    symbol0: str
    symbol1: str
    tick: int
    sqrt_price_x96: int | None
    decimals0: int | None
    decimals1: int | None
    tick_spacing: int
    timestamp: int
    block_number: int
    log_index: int


def _integer(value: object) -> int | None:
    try:
        return None if pd.isna(value) else int(value)
    except (TypeError, ValueError):
        return None


def _nonnegative_value(value: object) -> float | None:
    try:
        result = abs(float(value))
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) and result >= 0 else None


def _field(record: object, name: str) -> object:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


class CausalRangeClassifier:
    """Carry only the latest prior swap tick across exact chain-ordered events."""

    def __init__(self, token_decimals: dict[str, int] | None = None) -> None:
        self.latest: dict[str, PriorTickState] = {}
        self.token_decimals = {
            str(token).lower(): int(decimals)
            for token, decimals in (token_decimals or {}).items()
        }
        self.swap_samples: dict[str, list[dict[str, object]]] = {}

    def _observe_swap(self, record: object) -> None:
        pool = str(_field(record, "pool") or "").lower()
        tick = _integer(_field(record, "tick"))
        timestamp = _integer(_field(record, "timestamp"))
        block = _integer(_field(record, "block_number"))
        log_index = _integer(_field(record, "log_index"))
        fee = _integer(_field(record, "fee_pips"))
        token0 = str(_field(record, "token0") or "").lower()
        token1 = str(_field(record, "token1") or "").lower()
        sqrt_price_x96 = _integer(_field(record, "sqrt_price_x96"))
        decimals0 = _integer(_field(record, "decimals0"))
        decimals1 = _integer(_field(record, "decimals1"))
        if decimals0 is not None:
            record_token_decimals(self.token_decimals, token0, decimals0)
        if decimals1 is not None:
            record_token_decimals(self.token_decimals, token1, decimals1)
        if decimals0 is None:
            decimals0 = self.token_decimals.get(token0)
        if decimals1 is None:
            decimals1 = self.token_decimals.get(token1)
        samples = self.swap_samples.setdefault(pool, [])
        if len(samples) < 12:
            samples.append(
                {
                    "sqrtPriceX96": sqrt_price_x96,
                    "amount0": _field(record, "amount0"),
                    "amount1": _field(record, "amount1"),
                }
            )
        if decimals0 is None or decimals1 is None:
            resolved = resolve_decimals(
                token0,
                token1,
                samples,
                known_decimals=self.token_decimals,
            )
            if resolved is not None:
                decimals0, decimals1 = resolved
                record_token_decimals(self.token_decimals, token0, decimals0)
                record_token_decimals(self.token_decimals, token1, decimals1)
        if fee is None:
            fee = derive_fee_tier(pool, token0, token1)
        if None in (tick, timestamp, block, log_index, fee) or not pool or not token0 or not token1:
            return
        try:
            spacing = tick_spacing_for_fee(int(fee))
        except (TypeError, ValueError):
            return
        current = PriorTickState(
            pool=pool,
            token0=token0,
            token1=token1,
            symbol0=str(_field(record, "symbol0") or ""),
            symbol1=str(_field(record, "symbol1") or ""),
            tick=int(tick),
            sqrt_price_x96=sqrt_price_x96 if sqrt_price_x96 and sqrt_price_x96 > 0 else None,
            decimals0=decimals0,
            decimals1=decimals1,
            tick_spacing=spacing,
            timestamp=int(timestamp),
            block_number=int(block),
            log_index=int(log_index),
        )
        prior = self.latest.get(pool)
        if prior is not None and (current.block_number, current.log_index) <= (
            prior.block_number,
            prior.log_index,
        ):
            raise ValueError(f"noncausal swap order for pool {pool}")
        self.latest[pool] = current

    @staticmethod
    def _price(prices: dict[str, object], token: str) -> float | None:
        raw = prices.get(token)
        if isinstance(raw, tuple):
            raw = raw[1]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if np.isfinite(value) and value > 0 else None

    def _event_value(
        self,
        state: PriorTickState,
        amount0: float,
        amount1: float,
        prices: dict[str, object],
    ) -> tuple[dict[str, object] | None, str | None]:
        if (
            state.sqrt_price_x96 is None
            or state.decimals0 is None
            or state.decimals1 is None
        ):
            return None, "missing_exact_tick_valuation_state"
        anchors = []
        for index, (token, symbol) in enumerate(
            ((state.token0, state.symbol0), (state.token1, state.symbol1))
        ):
            candidate = VEHICLE_CANDIDATES.get(token)
            price = self._price(prices, token)
            if candidate is not None and price is not None:
                anchors.append((ANCHOR_PRIORITY[candidate], index, token, candidate, price))
        if not anchors:
            return None, "missing_candidate_day_price_anchor"
        _priority, anchor_index, anchor_token, anchor_symbol, anchor_price = min(anchors)
        try:
            log_ratio = (
                2.0 * math.log(state.sqrt_price_x96 / Q96)
                + (state.decimals0 - state.decimals1) * math.log(10.0)
            )
            if anchor_index == 0:
                price0 = anchor_price
                price1 = math.exp(math.log(anchor_price) - log_ratio)
            else:
                price1 = anchor_price
                price0 = math.exp(math.log(anchor_price) + log_ratio)
            event_value = amount0 * price0 + amount1 * price1
        except (OverflowError, ValueError, ZeroDivisionError):
            return None, "invalid_tick_implied_event_value"
        event_value = _nonnegative_value(event_value)
        if event_value is None or not 0 < event_value <= MAX_EVENT_VALUE_USD:
            return None, "missing_or_implausible_event_value_usd"
        external0 = self._price(prices, state.token0)
        external1 = self._price(prices, state.token1)
        reference_gap = None
        if external0 is not None and external1 is not None:
            reference_gap = 10_000.0 * (
                math.log(external0 / external1) - log_ratio
            )
        return {
            "amount0": amount0,
            "amount1": amount1,
            "price0_usd": price0,
            "price1_usd": price1,
            "price_anchor_token": anchor_token,
            "price_anchor_symbol": anchor_symbol,
            "price_anchor_usd": anchor_price,
            "external_pool_price_gap_bps": reference_gap,
            "event_value_usd": event_value,
            "event_value_source": "candidate_day_price_anchor_plus_exact_prior_v3_sqrt_price",
        }, None

    def _classify_liquidity(
        self,
        day: str,
        record: object,
        prices: dict[str, object],
    ) -> tuple[dict | None, dict | None]:
        identity = {
            "venue": "uniswap_v3",
            "day": day,
            "event_id": _field(record, "event_id"),
            "tx_hash": _field(record, "tx_hash"),
            "block_number": _integer(_field(record, "block_number")),
            "log_index": _integer(_field(record, "log_index")),
            "timestamp": _integer(_field(record, "timestamp")),
            "pool": str(_field(record, "pool") or "").lower(),
            "source_stream": _field(record, "source_stream"),
        }
        pool = identity["pool"]
        state = self.latest.get(pool)
        if state is None:
            return None, {**identity, "failure_reason": "no_prior_swap_tick"}
        lower = _integer(_field(record, "tick_lower"))
        upper = _integer(_field(record, "tick_upper"))
        amount = _integer(_field(record, "liquidity_delta"))
        amount0 = _nonnegative_value(_field(record, "amount0"))
        amount1 = _nonnegative_value(_field(record, "amount1"))
        if lower is None or upper is None or lower >= upper:
            return None, {**identity, "failure_reason": "invalid_tick_range"}
        if amount is None:
            return None, {**identity, "failure_reason": "missing_liquidity_delta"}
        if amount == 0:
            reason = (
                "zero_liquidity_burn_no_capital_flow"
                if identity["source_stream"] == "burns"
                else "zero_liquidity_delta"
            )
            return None, {**identity, "failure_reason": reason}
        if amount0 is None or amount1 is None or amount0 + amount1 <= 0:
            return None, {**identity, "failure_reason": "invalid_token_amounts"}
        timestamp = identity["timestamp"]
        age = None if timestamp is None else timestamp - state.timestamp
        if age is None or age < 0:
            return None, {**identity, "failure_reason": "noncausal_tick_timestamp"}
        width_spacings = (upper - lower) / state.tick_spacing
        active = lower <= state.tick < upper
        sign = 1 if amount > 0 else -1
        valuation, valuation_failure = self._event_value(
            state, amount0, amount1, prices
        )
        if valuation is None:
            return None, {**identity, "failure_reason": valuation_failure}
        return {
            **identity,
            "pool_family": _field(record, "pool_family"),
            "invariant_family": _field(record, "invariant_family"),
            "state_generation": _field(record, "state_generation"),
            "token0": state.token0,
            "token1": state.token1,
            "symbol0": state.symbol0,
            "symbol1": state.symbol1,
            "decimals0": state.decimals0,
            "decimals1": state.decimals1,
            "event_sign": sign,
            **valuation,
            "signed_event_value_usd": sign * float(valuation["event_value_usd"]),
            "tick_before": state.tick,
            "sqrt_price_x96_before": str(state.sqrt_price_x96),
            "tick_state_timestamp": state.timestamp,
            "tick_state_age_seconds": age,
            "tick_lower": lower,
            "tick_upper": upper,
            "tick_spacing": state.tick_spacing,
            "range_width_spacings": width_spacings,
            "range_active_before": active,
            "range_near_active_before": active and width_spacings <= NEAR_RANGE_SPACINGS,
            "validation_status": "causal_prior_tick_exact_identity_candidate_price_anchored",
        }, None

    def classify_day(
        self,
        day: str,
        state: pd.DataFrame,
        prices: dict[str, object],
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Classify liquidity events at the latest strictly prior observed swap tick."""

        events: list[dict] = []
        rejections: list[dict] = []
        blocks = state["block_number"].to_numpy(dtype=np.int64, na_value=-1)
        logs = state["log_index"].to_numpy(dtype=np.int64, na_value=-1)
        if len(state) > 1 and np.any(
            (blocks[1:] < blocks[:-1])
            | ((blocks[1:] == blocks[:-1]) & (logs[1:] < logs[:-1]))
        ):
            raise ValueError(f"canonical V3 state is not in causal order: {day}")
        for record in state.itertuples(index=False):
            record_type = str(_field(record, "record_type") or "")
            if record_type == "swap":
                self._observe_swap(record)
            elif record_type == "liquidity":
                accepted, rejected = self._classify_liquidity(day, record, prices)
                if accepted is not None:
                    events.append(accepted)
                if rejected is not None:
                    rejections.append(rejected)
        return pd.DataFrame(events), pd.DataFrame(rejections)


def allocate_candidate_event_values(
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Allocate each event once across its exact candidate-token sides."""

    if events.empty:
        return pd.DataFrame(), pd.DataFrame()
    required = {"token0", "token1", "event_value_usd", "event_sign"}
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"LP events lack candidate-allocation columns: {missing}")
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for record in events.to_dict("records"):
        matches = {
            str(token).lower(): VEHICLE_CANDIDATES[str(token).lower()]
            for token in (record["token0"], record["token1"])
            if str(token).lower() in VEHICLE_CANDIDATES
        }
        if not matches:
            rejected.append({**record, "candidate": None, "failure_reason": "no_candidate_pool_side"})
            continue
        weight = 1.0 / len(matches)
        for address, candidate in matches.items():
            value = float(record["event_value_usd"]) * weight
            accepted.append(
                {
                    **record,
                    "candidate": candidate,
                    "candidate_address": address,
                    "allocation_weight": weight,
                    "allocated_event_value_usd": value,
                    "signed_allocated_event_value_usd": float(record["event_sign"]) * value,
                    "flow_normalization_status": "dollar_flow_no_capital_stock_denominator",
                }
            )
    return pd.DataFrame(accepted), pd.DataFrame(rejected)


def aggregate_daily_liquidity_flow(
    events: pd.DataFrame,
    candidate_days: pd.DataFrame,
) -> pd.DataFrame:
    """Build candidate-day dollar flows and within-flow shares without a stock proxy."""

    keys = ["day", "candidate"]
    if candidate_days.duplicated(keys).any():
        raise ValueError("candidate-day flow perimeter must be unique")
    events = events.copy()
    events["active_signed"] = events["signed_allocated_event_value_usd"].where(
        events["range_active_before"], 0.0
    )
    events["near_signed"] = events["signed_allocated_event_value_usd"].where(
        events["range_near_active_before"], 0.0
    )
    events["near_gross"] = events["allocated_event_value_usd"].where(
        events["range_near_active_before"], 0.0
    )
    numerators = events.groupby(keys, as_index=False).agg(
        gross_liquidity_flow_usd=("allocated_event_value_usd", "sum"),
        net_liquidity_flow_usd=("signed_allocated_event_value_usd", "sum"),
        active_net_liquidity_flow_usd=("active_signed", "sum"),
        near_net_liquidity_flow_usd=("near_signed", "sum"),
        near_gross_liquidity_flow_usd=("near_gross", "sum"),
        event_count=("event_id", "size"),
    )
    return finalize_daily_liquidity_flow(numerators, candidate_days)


def finalize_daily_liquidity_flow(
    numerators: pd.DataFrame,
    candidate_days: pd.DataFrame,
) -> pd.DataFrame:
    """Complete pre-aggregated candidate-day flows on the declared calendar."""

    keys = ["day", "candidate"]
    if candidate_days.duplicated(keys).any():
        raise ValueError("candidate-day flow perimeter must be unique")
    if numerators.duplicated(keys).any():
        raise ValueError("candidate-day flow numerators must be unique")
    panel = candidate_days.merge(numerators, on=keys, how="left")
    numerator_columns = [
        "gross_liquidity_flow_usd",
        "net_liquidity_flow_usd",
        "active_net_liquidity_flow_usd",
        "near_net_liquidity_flow_usd",
        "near_gross_liquidity_flow_usd",
        "event_count",
    ]
    panel[numerator_columns] = panel[numerator_columns].fillna(0.0)
    gross = pd.to_numeric(panel["gross_liquidity_flow_usd"], errors="raise")
    day_gross = panel.groupby("day")["gross_liquidity_flow_usd"].transform("sum")
    positive_gross = gross.gt(0)
    positive_day = day_gross.gt(0)
    panel["has_liquidity_flow"] = positive_gross
    panel["gross_candidate_flow_share"] = np.where(
        positive_day, gross / day_gross, np.nan
    )
    for numerator, output in (
        ("net_liquidity_flow_usd", "net_flow_pressure"),
        ("active_net_liquidity_flow_usd", "active_net_flow_pressure"),
        ("near_net_liquidity_flow_usd", "near_net_flow_pressure"),
        ("near_gross_liquidity_flow_usd", "near_gross_flow_share"),
    ):
        panel[output] = np.where(
            positive_gross,
            pd.to_numeric(panel[numerator], errors="raise") / gross,
            np.nan,
        )
    panel["flow_normalization_status"] = "dollar_flow_and_within_flow_shares_no_capital_stock"
    return panel

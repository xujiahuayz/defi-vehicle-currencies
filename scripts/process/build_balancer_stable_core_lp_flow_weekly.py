#!/usr/bin/env python3
"""Build Balancer LP join/exit flows for stable cores and stable spokes.

Reads:
  data/raw/thegraph/balancer/balancer_joins_exits_*.jsonl.gz
  data/raw/thegraph/balancer/balancer_daily_*.jsonl.gz
  data/processed/token_price_daily.parquet

Writes:
  data/processed/balancer_stable_core_lp_flow_weekly.parquet
  output/exhibits/balancer_stable_core_lp_flow_weekly_support.jsonl

The core definition is deliberately narrow: every token address in the pool
must be directly classified as a USD stablecoin by the canonical taxonomy.
The comparison sample contains two-token spokes with exactly one such
stablecoin and one non-stable token.  Pools containing their own Balancer pool
token, a non-USD stablecoin, multiple non-stable assets, or an unclassified
claim presented as a stablecoin are never treated as stable cores.

Join and exit values are reconstructed from the event's token amounts and the
validated address-day price panel.  The subgraph's ``valueUSD`` field is kept
only as an audit value.  Event counts remain observed when a token price is
missing, while dollar-flow fields are explicitly labelled as priced flow.

Balancer's daily stream reports a current USD liquidity stock and cumulative
swap volume.  Consecutive Sunday snapshots therefore identify prior-week
reported TVL and volume without assigning missing dates to zero.  Weeks without
two exact Sunday endpoints retain the LP events but cannot enter normalized
analysis.  This is reported as a state-support boundary, not repaired from the
join/exit flow.  ``sender`` is counted only as a transaction address and is not
treated as the beneficial owner of supplied capital.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import STABLE
from ddvc.capital_validation import USD_STABLE_TOKENS
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit
from scripts.process.build_v2_lp_flow_pool_daily import validated_event_prices


RAW_DIR = REPO_ROOT / "data/raw/thegraph/balancer"
OUTPUT = DATA_DIR / "processed/balancer_stable_core_lp_flow_weekly.parquet"
SUPPORT_OUTPUT = (
    OUTPUT_DIR / "exhibits/balancer_stable_core_lp_flow_weekly_support.jsonl"
)
SAMPLE_END_EXCLUSIVE = pd.Timestamp("2026-07-01")
MAX_EVENT_FLOW_USD = 10_000_000_000.0
SUNDAY = 6

USD_STABLES = frozenset(str(token).lower() for token in USD_STABLE_TOKENS)
STABLE_SYMBOLS = {
    str(address).lower(): str(symbol)
    for address, symbol in STABLE.items()
    if str(address).lower() in USD_STABLES
}

CODE_SOURCES = [
    "scripts/process/build_balancer_stable_core_lp_flow_weekly.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/capital_validation.py",
]
INPUTS = [
    "data/raw/thegraph/balancer",
    "data/processed/token_price_daily.parquet",
]


@dataclass(frozen=True)
class StablePoolIdentity:
    pool: str
    token_addresses: tuple[str, ...]
    token_symbols: tuple[str, ...]
    pool_class: str

    @property
    def address_key(self) -> str:
        return ",".join(self.token_addresses)

    @property
    def symbol_key(self) -> str:
        return ",".join(self.token_symbols)


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _nonnegative_float(value: object) -> float | None:
    parsed = _decimal(value)
    if parsed is None or parsed < 0:
        return None
    result = float(parsed)
    return result if np.isfinite(result) else None


def _event_date(row: dict[str, object]) -> pd.Timestamp | None:
    try:
        timestamp = int(row.get("timestamp") or 0)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return pd.Timestamp(datetime.fromtimestamp(timestamp, tz=timezone.utc).date())


def _week_start(day: pd.Timestamp) -> pd.Timestamp:
    return day - pd.Timedelta(days=int(day.weekday()))


def classify_stable_core_or_spoke_pool(
    row: dict[str, object],
) -> tuple[StablePoolIdentity | None, str | None]:
    """Admit exact stable cores and unambiguous two-token stable spokes."""

    pool_data = row.get("pool") or {}
    if not isinstance(pool_data, dict):
        return None, "missing_pool_identity"
    pool = str(pool_data.get("id") or "").lower()
    raw_tokens = pool_data.get("tokensList") or []
    if not pool or not isinstance(raw_tokens, list):
        return None, "missing_pool_identity"
    tokens = tuple(str(token or "").lower() for token in raw_tokens)
    if len(tokens) < 2 or any(not token for token in tokens):
        return None, "fewer_than_two_valid_tokens"
    if len(set(tokens)) != len(tokens):
        return None, "duplicate_token_identity"
    pool_token = pool[:42] if pool.startswith("0x") and len(pool) >= 42 else ""
    if pool_token and pool_token in tokens:
        return None, "contains_balancer_pool_token"
    all_stables = frozenset(str(address).lower() for address in STABLE)
    if any(token in all_stables and token not in USD_STABLES for token in tokens):
        return None, "contains_non_usd_stablecoin"
    stable_count = sum(token in USD_STABLES for token in tokens)
    if stable_count == len(tokens):
        pool_class = "stable_core"
    elif len(tokens) == 2 and stable_count == 1:
        pool_class = "stable_spoke"
    else:
        return None, "outside_exact_core_or_two_token_spoke"
    symbols = tuple(STABLE_SYMBOLS.get(token, token) for token in tokens)
    return StablePoolIdentity(pool, tokens, symbols, pool_class), None


def _event_value(
    *,
    row: dict[str, object],
    identity: StablePoolIdentity,
    day: pd.Timestamp,
    prices: dict[tuple[str, str], float],
    max_event_flow_usd: float,
) -> tuple[float | None, str]:
    amounts = row.get("amounts") or []
    if not isinstance(amounts, list) or len(amounts) != len(identity.token_addresses):
        return None, "invalid_amount_vector"
    parsed = [_decimal(amount) for amount in amounts]
    if any(amount is None or amount < 0 for amount in parsed):
        return None, "invalid_amount_vector"
    day_key = day.strftime("%Y%m%d")
    event_prices = [prices.get((day_key, token)) for token in identity.token_addresses]
    if any(price is None or not np.isfinite(price) or price <= 0 for price in event_prices):
        return None, "missing_validated_token_price"
    value = float(
        sum(
            amount * Decimal(str(price))
            for amount, price in zip(parsed, event_prices, strict=True)
            if amount is not None
        )
    )
    if not np.isfinite(value) or value < 0:
        return None, "invalid_reconstructed_value"
    if value > max_event_flow_usd:
        return None, "above_event_value_bound"
    return value, "fully_priced"


def load_balancer_stable_core_events(
    *,
    raw_dir: Path = RAW_DIR,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    price_lookup: dict[tuple[str, str], float] | None = None,
    sample_end_exclusive: pd.Timestamp = SAMPLE_END_EXCLUSIVE,
    max_event_flow_usd: float = MAX_EVENT_FLOW_USD,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Read exact core/spoke events and return rows plus pool identities."""

    files = sorted(raw_dir.glob("balancer_joins_exits_*.jsonl.gz"))
    if not files:
        raise ValueError("no Balancer join/exit files found")
    if max_event_flow_usd <= 0:
        raise ValueError("maximum event flow must be positive")
    prices = price_lookup if price_lookup is not None else validated_event_prices(price_path)
    exclusion = Counter()
    value_status = Counter()
    event_rows: list[dict[str, object]] = []
    registry: dict[str, StablePoolIdentity] = {}
    seen_events: set[str] = set()
    duplicate_events = 0
    raw_rows = 0
    after_sample_rows = 0

    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_rows += 1
                row = json.loads(line)
                day = _event_date(row)
                if day is None:
                    exclusion["missing_event_timestamp"] += 1
                    continue
                if day >= sample_end_exclusive:
                    after_sample_rows += 1
                    continue
                event_type = str(row.get("type") or "").strip().lower()
                if event_type not in {"join", "exit"}:
                    exclusion["invalid_event_type"] += 1
                    continue
                identity, reason = classify_stable_core_or_spoke_pool(row)
                if identity is None:
                    exclusion[str(reason)] += 1
                    continue
                prior = registry.get(identity.pool)
                if prior is not None and (
                    prior.token_addresses != identity.token_addresses
                    or prior.pool_class != identity.pool_class
                ):
                    raise ValueError(
                        f"Balancer pool {identity.pool} has conflicting token identities"
                    )
                registry[identity.pool] = identity
                event_id = str(row.get("id") or "").lower()
                transaction = str(row.get("tx") or "").lower()
                unique_key = event_id or f"{path.name}:{raw_rows}"
                if unique_key in seen_events:
                    duplicate_events += 1
                    continue
                seen_events.add(unique_key)
                priced_value, status = _event_value(
                    row=row,
                    identity=identity,
                    day=day,
                    prices=prices,
                    max_event_flow_usd=max_event_flow_usd,
                )
                value_status[status] += 1
                reported_value = _nonnegative_float(row.get("valueUSD"))
                sender = str(row.get("sender") or "").lower()
                event_rows.append(
                    {
                        "event_date": day,
                        "week_start": _week_start(day),
                        "pool": identity.pool,
                        "token_addresses": identity.address_key,
                        "token_symbols": identity.symbol_key,
                        "token_count": len(identity.token_addresses),
                        "pool_class": identity.pool_class,
                        "event_id": event_id,
                        "transaction": transaction,
                        "sender_address": sender,
                        "event_type": event_type,
                        "priced_flow_usd": priced_value,
                        "flow_value_status": status,
                        "reported_value_usd": reported_value,
                    }
                )

    if not event_rows:
        raise ValueError("no exact USD-stable Balancer join/exit events found")
    events = pd.DataFrame(event_rows).sort_values(
        ["event_date", "pool", "transaction", "event_id"]
    )
    registry_frame = pd.DataFrame(
        [
            {
                "pool": identity.pool,
                "token_addresses": identity.address_key,
                "token_symbols": identity.symbol_key,
                "token_count": len(identity.token_addresses),
                "pool_class": identity.pool_class,
            }
            for identity in registry.values()
        ]
    ).sort_values("pool")
    support: dict[str, object] = {
        "join_exit_files": len(files),
        "raw_join_exit_rows": raw_rows,
        "after_sample_rows": after_sample_rows,
        "duplicate_event_rows": duplicate_events,
        "stable_core_or_spoke_events": int(len(events)),
        "stable_core_or_spoke_pools": int(len(registry_frame)),
        "stable_core_events": int(events["pool_class"].eq("stable_core").sum()),
        "stable_spoke_events": int(events["pool_class"].eq("stable_spoke").sum()),
        "stable_core_pools": int(
            registry_frame["pool_class"].eq("stable_core").sum()
        ),
        "stable_spoke_pools": int(
            registry_frame["pool_class"].eq("stable_spoke").sum()
        ),
        "pool_rule": (
            "core: every direct tokensList address is a canonical USD stablecoin; "
            "spoke: exactly one canonical USD stablecoin and one non-stable token; "
            "BPT-containing and non-USD-stable pools excluded"
        ),
        "dollar_flow_rule": (
            "sum event token amounts times validated canonical address-day prices; "
            "raw valueUSD retained only for audit"
        ),
        "sender_identity_rule": (
            "sender is an observed transaction address and is not a beneficial-owner identity"
        ),
    }
    support.update({f"excluded_{key}": int(value) for key, value in exclusion.items()})
    support.update({f"value_{key}_events": int(value) for key, value in value_status.items()})
    return events.reset_index(drop=True), registry_frame.reset_index(drop=True), support


def aggregate_balancer_stable_core_events(events: pd.DataFrame) -> pd.DataFrame:
    """Aggregate exact events to pool-week while preserving value coverage."""

    required = {
        "week_start",
        "pool",
        "pool_class",
        "token_addresses",
        "token_symbols",
        "token_count",
        "event_id",
        "transaction",
        "sender_address",
        "event_type",
        "priced_flow_usd",
        "flow_value_status",
        "reported_value_usd",
    }
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"Balancer stable-core event frame lacks columns: {missing}")
    rows: list[dict[str, object]] = []
    keys = [
        "week_start",
        "pool",
        "pool_class",
        "token_addresses",
        "token_symbols",
        "token_count",
    ]
    for key, group in events.groupby(keys, sort=True, dropna=False):
        event_type = group["event_type"].astype(str)
        priced = group["flow_value_status"].eq("fully_priced")
        joins = event_type.eq("join")
        exits = event_type.eq("exit")
        values = pd.to_numeric(group["priced_flow_usd"], errors="coerce")
        reported = pd.to_numeric(group["reported_value_usd"], errors="coerce")

        def _sum(mask: pd.Series, series: pd.Series) -> float:
            return float(series.loc[mask].fillna(0.0).sum())

        event_count = int(len(group))
        priced_event_count = int(priced.sum())
        rows.append(
            {
                "week_start": key[0],
                "pool": key[1],
                "pool_class": key[2],
                "token_addresses": key[3],
                "token_symbols": key[4],
                "token_count": int(key[5]),
                "join_event_count": int(joins.sum()),
                "exit_event_count": int(exits.sum()),
                "event_count": event_count,
                "join_transaction_count": int(
                    group.loc[joins, "transaction"].replace("", np.nan).nunique()
                ),
                "exit_transaction_count": int(
                    group.loc[exits, "transaction"].replace("", np.nan).nunique()
                ),
                "distinct_sender_address_count": int(
                    group["sender_address"].replace("", np.nan).nunique()
                ),
                "priced_join_event_count": int((priced & joins).sum()),
                "priced_exit_event_count": int((priced & exits).sum()),
                "priced_event_count": priced_event_count,
                "priced_join_flow_usd": _sum(priced & joins, values),
                "priced_exit_flow_usd": _sum(priced & exits, values),
                "priced_gross_flow_usd": _sum(priced, values),
                "priced_net_join_flow_usd": _sum(priced & joins, values)
                - _sum(priced & exits, values),
                "reported_gross_flow_usd": _sum(reported.notna(), reported),
                "reported_value_event_count": int(reported.notna().sum()),
                "flow_value_complete": priced_event_count == event_count,
            }
        )
    return pd.DataFrame(rows).sort_values(["week_start", "pool"]).reset_index(drop=True)


def _file_day(path: Path, prefix: str) -> pd.Timestamp | None:
    match = re.fullmatch(rf"{re.escape(prefix)}_(\d{{8}})\.jsonl\.gz", path.name)
    if match is None:
        return None
    try:
        return pd.Timestamp(datetime.strptime(match.group(1), "%Y%m%d").date())
    except ValueError:
        return None


def load_balancer_stable_core_lagged_state(
    *,
    raw_dir: Path,
    registry: pd.DataFrame,
    sample_end_exclusive: pd.Timestamp = SAMPLE_END_EXCLUSIVE,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Recover prior-week volume and reported TVL from consecutive Sundays."""

    files = sorted(raw_dir.glob("balancer_daily_*.jsonl.gz"))
    sunday_files = [
        (path, day)
        for path in files
        if (day := _file_day(path, "balancer_daily")) is not None
        and day.weekday() == SUNDAY
        and day < sample_end_exclusive
    ]
    pools = set(registry["pool"].astype(str).str.lower())
    raw_rows = 0
    stable_rows = 0
    invalid_rows = 0
    records: list[dict[str, object]] = []
    for path, day in sunday_files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw_rows += 1
                row = json.loads(line)
                pool_data = row.get("pool") or {}
                pool = str(
                    (
                        pool_data.get("id")
                        if isinstance(pool_data, dict)
                        else pool_data
                    )
                    or ""
                ).lower()
                if pool not in pools:
                    continue
                stable_rows += 1
                cumulative_volume = _nonnegative_float(row.get("swapVolume"))
                reported_tvl = _nonnegative_float(row.get("liquidity"))
                if cumulative_volume is None or reported_tvl is None or reported_tvl <= 0:
                    invalid_rows += 1
                records.append(
                    {
                        "snapshot_date": day,
                        "pool": pool,
                        "cumulative_volume_usd": cumulative_volume,
                        "reported_tvl_usd": reported_tvl,
                    }
                )
    if not records:
        return pd.DataFrame(), {
            "daily_files": len(files),
            "sunday_daily_files": len(sunday_files),
            "raw_sunday_daily_rows": raw_rows,
            "stable_pool_sunday_rows": stable_rows,
            "invalid_stable_pool_sunday_rows": invalid_rows,
            "state_normalization_status": (
                "withheld_no_exact_stable_pool_consecutive_sunday_state"
            ),
            "state_quantity": (
                "join/exit events do not identify a capital stock; no TVL normalization"
            ),
        }
    snapshots = pd.DataFrame(records)
    duplicate = snapshots.duplicated(["snapshot_date", "pool"], keep=False)
    inconsistent = 0
    if duplicate.any():
        for _, group in snapshots.loc[duplicate].groupby(
            ["snapshot_date", "pool"], sort=False
        ):
            if group[["cumulative_volume_usd", "reported_tvl_usd"]].nunique().max() > 1:
                inconsistent += 1
    if inconsistent:
        raise ValueError(
            f"Balancer daily state has {inconsistent} conflicting pool-Sunday rows"
        )
    snapshots = snapshots.drop_duplicates(["snapshot_date", "pool"], keep="last")
    snapshots = snapshots.sort_values(["pool", "snapshot_date"]).reset_index(drop=True)
    snapshots["previous_snapshot_date"] = snapshots.groupby("pool", sort=False)[
        "snapshot_date"
    ].shift(1)
    snapshots["previous_cumulative_volume_usd"] = snapshots.groupby(
        "pool", sort=False
    )["cumulative_volume_usd"].shift(1)
    snapshots["snapshot_gap_days"] = (
        snapshots["snapshot_date"] - snapshots["previous_snapshot_date"]
    ).dt.days
    snapshots["lagged_volume_usd"] = (
        snapshots["cumulative_volume_usd"]
        - snapshots["previous_cumulative_volume_usd"]
    )
    snapshots["lagged_state_complete"] = (
        snapshots["snapshot_gap_days"].eq(7)
        & snapshots["reported_tvl_usd"].gt(0)
        & snapshots["lagged_volume_usd"].ge(0)
        & np.isfinite(snapshots["lagged_volume_usd"])
    )
    negative_resets = int(snapshots["lagged_volume_usd"].lt(0).fillna(False).sum())
    snapshots.loc[~snapshots["lagged_state_complete"], "lagged_volume_usd"] = np.nan
    snapshots["week_start"] = snapshots["snapshot_date"] + pd.Timedelta(days=1)
    result = snapshots[
        [
            "week_start",
            "pool",
            "snapshot_date",
            "reported_tvl_usd",
            "lagged_volume_usd",
            "lagged_state_complete",
        ]
    ].rename(columns={"reported_tvl_usd": "lagged_reported_tvl_usd"})
    support = {
        "daily_files": len(files),
        "sunday_daily_files": len(sunday_files),
        "raw_sunday_daily_rows": raw_rows,
        "stable_pool_sunday_rows": stable_rows,
        "invalid_stable_pool_sunday_rows": invalid_rows,
        "negative_cumulative_volume_resets": negative_resets,
        "lagged_state_complete_pool_weeks": int(result["lagged_state_complete"].sum()),
        "state_normalization_status": (
            "available_on_exact_consecutive_sunday_snapshots"
            if result["lagged_state_complete"].any()
            else "withheld_no_exact_stable_pool_consecutive_sunday_state"
        ),
        "state_quantity": (
            "prior-Sunday subgraph-reported liquidity and the exact change in "
            "cumulative swapVolume between consecutive Sundays; not independently "
            "reconstructed capital"
        ),
    }
    return result.reset_index(drop=True), support


def complete_pool_week_calendar(
    flows: pd.DataFrame,
    state: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    """Merge state and events, retaining state weeks with zero LP events."""

    if state.empty:
        result = flows.copy()
        result["snapshot_date"] = pd.NaT
        result["lagged_reported_tvl_usd"] = np.nan
        result["lagged_volume_usd"] = np.nan
        result["lagged_state_complete"] = False
        return result.sort_values(["week_start", "pool"]).reset_index(drop=True)
    identity = registry.set_index("pool")
    result = state.merge(
        flows,
        on=["week_start", "pool"],
        how="outer",
        validate="one_to_one",
        indicator="_merge",
    )
    for column in ("pool_class", "token_addresses", "token_symbols", "token_count"):
        result[column] = result[column].fillna(result["pool"].map(identity[column]))
    count_columns = [
        "join_event_count",
        "exit_event_count",
        "event_count",
        "join_transaction_count",
        "exit_transaction_count",
        "distinct_sender_address_count",
        "priced_join_event_count",
        "priced_exit_event_count",
        "priced_event_count",
        "reported_value_event_count",
    ]
    flow_columns = [
        "priced_join_flow_usd",
        "priced_exit_flow_usd",
        "priced_gross_flow_usd",
        "priced_net_join_flow_usd",
        "reported_gross_flow_usd",
    ]
    state_only = result["_merge"].eq("left_only")
    result.loc[state_only, count_columns] = 0
    result.loc[state_only, flow_columns] = 0.0
    result.loc[state_only, "flow_value_complete"] = True
    for column in count_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype(int)
    for column in flow_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)
    result["flow_value_complete"] = result["flow_value_complete"].fillna(False).astype(bool)
    result["lagged_state_complete"] = result["lagged_state_complete"].fillna(False).astype(bool)
    return result.drop(columns="_merge").sort_values(
        ["week_start", "pool"]
    ).reset_index(drop=True)


def validate_balancer_stable_core_panel(frame: pd.DataFrame) -> None:
    required = {
        "week_start",
        "pool",
        "pool_class",
        "token_addresses",
        "token_symbols",
        "token_count",
        "join_event_count",
        "exit_event_count",
        "event_count",
        "priced_gross_flow_usd",
        "flow_value_complete",
        "lagged_reported_tvl_usd",
        "lagged_volume_usd",
        "lagged_state_complete",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Balancer stable-core pool-week panel lacks columns: {missing}")
    if frame.empty:
        raise ValueError("Balancer stable-core pool-week panel is empty")
    if frame.duplicated(["week_start", "pool"]).any():
        raise ValueError("Balancer stable-core panel has duplicate pool-weeks")
    tokens = frame["token_addresses"].map(lambda values: str(values).split(","))
    stable_counts = tokens.map(lambda values: sum(token in USD_STABLES for token in values))
    valid_core = frame["pool_class"].eq("stable_core") & stable_counts.eq(
        frame["token_count"]
    )
    valid_spoke = (
        frame["pool_class"].eq("stable_spoke")
        & frame["token_count"].eq(2)
        & stable_counts.eq(1)
    )
    if not (valid_core | valid_spoke).all():
        raise ValueError("Balancer stable-core/spoke panel violates its pool definition")
    for column in ("event_count", "priced_gross_flow_usd"):
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any() or values.lt(0).any():
            raise ValueError(f"Balancer stable-core panel has invalid {column}")


def run(
    *,
    raw_dir: Path = RAW_DIR,
    price_path: Path = TOKEN_PRICE_DAILY_PANEL,
    output_path: Path = OUTPUT,
    support_path: Path = SUPPORT_OUTPUT,
    sample_end_exclusive: pd.Timestamp = SAMPLE_END_EXCLUSIVE,
    max_event_flow_usd: float = MAX_EVENT_FLOW_USD,
) -> int:
    events, registry, event_support = load_balancer_stable_core_events(
        raw_dir=raw_dir,
        price_path=price_path,
        sample_end_exclusive=sample_end_exclusive,
        max_event_flow_usd=max_event_flow_usd,
    )
    flows = aggregate_balancer_stable_core_events(events)
    state, state_support = load_balancer_stable_core_lagged_state(
        raw_dir=raw_dir,
        registry=registry,
        sample_end_exclusive=sample_end_exclusive,
    )
    panel = complete_pool_week_calendar(flows, state, registry)
    validate_balancer_stable_core_panel(panel)
    support = {
        "record_type": "balancer_stable_core_lp_flow_weekly_support",
        **event_support,
        **state_support,
        "pool_week_rows": int(len(panel)),
        "active_pool_weeks": int(panel["event_count"].gt(0).sum()),
        "fully_priced_events": int(panel["priced_event_count"].sum()),
        "observed_events": int(panel["event_count"].sum()),
        "fully_priced_event_share": float(
            panel["priced_event_count"].sum() / panel["event_count"].sum()
        ),
    }
    with atomic_output(output_path) as temporary:
        panel.to_parquet(temporary, index=False)
    write_exhibit(
        pd.DataFrame([support]),
        support_path,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(panel):,} Balancer stable-core/spoke pool-weeks "
        f"across {panel['pool'].nunique():,} pools to {output_path}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--price", type=Path, default=TOKEN_PRICE_DAILY_PANEL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument(
        "--sample-end-exclusive",
        type=pd.Timestamp,
        default=SAMPLE_END_EXCLUSIVE,
    )
    parser.add_argument(
        "--max-event-flow-usd",
        type=float,
        default=MAX_EVENT_FLOW_USD,
    )
    args = parser.parse_args()
    return run(
        raw_dir=args.raw_dir,
        price_path=args.price,
        output_path=args.output,
        support_path=args.support,
        sample_end_exclusive=args.sample_end_exclusive,
        max_event_flow_usd=args.max_event_flow_usd,
    )


if __name__ == "__main__":
    raise SystemExit(main())

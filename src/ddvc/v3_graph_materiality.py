"""Reusable materiality diagnostics for Graph omissions in exact V3 state."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

import duckdb
import pandas as pd

from ddvc.artifact_release import file_stat_identity
from ddvc.asset_types import CURRENCY_TYPES, asset_type
from ddvc.data_release import ReleasedPartitionSet
from ddvc.fetch.pool_daily import (
    UNISWAP_V3_STATIC_FIELDS,
    UNISWAP_V3_STATIC_QUERY_CONTRACT,
    UNISWAP_V3_STATIC_VALIDATION,
    pool_identity_values,
)
from ddvc.pricing.v3pools import derive_fee_tier
from ddvc.prices import load_canonical_token_prices
from ddvc.quoter import canonical_json_sha256
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.transaction_targets import EXACT_VENUES
from ddvc.v3_inventory import EVENT_TOPICS, decode_inventory_log


GRAPH_STATIC_FIELDS = UNISWAP_V3_STATIC_FIELDS
GRAPH_STATIC_VALIDATION = UNISWAP_V3_STATIC_VALIDATION


def graph_pool_snapshot(
    path: Path,
    metadata_path: Path,
    *,
    certified_upper_block: int,
) -> tuple[set[str], dict[str, object]]:
    """Read and bind the auxiliary Graph static snapshot in one logical pass."""

    path_identity = file_stat_identity(path)
    metadata_identity = file_stat_identity(metadata_path)
    container_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata_sha256 = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    pools: set[str] = set()
    logical = hashlib.sha256()
    rows = 0
    with gzip.open(path, "rb") as handle:
        for raw_line in handle:
            logical.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Graph static snapshot is malformed: {path}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Graph static snapshot row is not an object: {path}")
            resolved = pool_identity_values(row)
            if resolved is None:
                raise ValueError(f"Graph static snapshot row lacks exact ordered identities: {path}")
            pool, identity = resolved
            if not re.fullmatch(r"0x[0-9a-f]{40}", pool):
                raise ValueError(f"Graph static snapshot contains an invalid pool ID: {pool}")
            if pool in pools:
                raise ValueError(f"Graph static snapshot contains a duplicate pool ID: {pool}")
            try:
                fee = int(row.get("feeTier") or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Graph static snapshot contains an invalid fee tier: {pool}") from exc
            if derive_fee_tier(pool, identity.token0_address, identity.token1_address) != fee:
                raise ValueError(f"Graph static snapshot fails canonical CREATE2 identity: {pool}")
            rows += 1
            pools.add(pool)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        path_identity != file_stat_identity(path)
        or metadata_identity != file_stat_identity(metadata_path)
        or hashlib.sha256(path.read_bytes()).hexdigest() != container_sha256
        or hashlib.sha256(metadata_path.read_bytes()).hexdigest() != metadata_sha256
    ):
        raise RuntimeError("Graph static snapshot generation mutated during validation")
    sample_day = path.name.removesuffix(".jsonl.gz").rsplit("_", 1)[-1]
    if (
        not isinstance(metadata, dict)
        or metadata.get("source") != "uniswap_v3"
        or metadata.get("entity") != "pools"
        or str(metadata.get("sample_day")) != sample_day
        or len(sample_day) != 8
        or not sample_day.isdigit()
        or not 0 < int(metadata.get("historical_block", -1)) <= certified_upper_block
        or int(metadata.get("rows", -1)) != rows
        or metadata.get("container_sha256") != container_sha256
        or metadata.get("logical_content_sha256") != logical.hexdigest()
        or metadata.get("fields") != GRAPH_STATIC_FIELDS
        or metadata.get("validation") != GRAPH_STATIC_VALIDATION
        or metadata.get("query_contract") != {
            **UNISWAP_V3_STATIC_QUERY_CONTRACT,
            "historical_block": int(metadata.get("historical_block", -1)),
        }
        or int(metadata.get("sample_identity_gaps_resolved", -1))
        != int(metadata.get("sample_pools_needing_identity", -2))
        or not pools
    ):
        raise ValueError("Graph static snapshot metadata is stale or outside the certified factory perimeter")
    return pools, {
        "policy": "graph-static-snapshot-logical-content-v1",
        "path": path.as_posix(),
        "metadata_path": metadata_path.as_posix(),
        "container_sha256": container_sha256,
        "metadata_sha256": metadata_sha256,
        "logical_content_sha256": logical.hexdigest(),
        "rows": rows,
        "distinct_pool_ids": len(pools),
        "sample_day": sample_day,
        "historical_block": int(metadata["historical_block"]),
        "certified_factory_upper_block": certified_upper_block,
    }


def share(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def register_installed_inventory_events(
    con: duckdb.DuckDBPyConnection,
    paths: Iterable[Path],
    binding: Mapping[str, object],
) -> tuple[Path, ...]:
    """Register exactly the ordered raw files admitted by the installed-generation API."""

    perimeter = tuple(Path(path) for path in paths)
    names = [path.name for path in perimeter]
    if (
        not perimeter
        or len(names) != len(set(names))
        or int(binding.get("chunk_count", -1)) != len(perimeter)
        or binding.get("listed_raw_paths_sha256") != canonical_json_sha256(names)
    ):
        raise ValueError("installed V3 inventory path perimeter disagrees with its binding")
    con.from_parquet([str(path) for path in perimeter], union_by_name=True).create_view(
        "installed_inventory_events"
    )
    return perimeter


def _exact_token_metadata(values: Mapping[str, int]) -> dict[str, int]:
    return {str(token).lower(): int(decimals) for token, decimals in values.items()}


def _daily_prices(path: Path) -> tuple[dict[tuple[str, str], float], str]:
    frame = load_canonical_token_prices(path, columns=("day", "token", "price_usd"))
    content_sha256 = str(frame.attrs["content_sha256"])
    frame["token"] = frame["token"].str.lower()
    return {
        (str(row.day), str(row.token)): float(row.price_usd)
        for row in frame.drop_duplicates(["day", "token"], keep="last").itertuples()
    }, content_sha256


def _raw_notional_usd(raw_amount: int, decimals: int, price_usd: float) -> float | None:
    try:
        value = Decimal(abs(raw_amount)) * Decimal(str(price_usd)) / (Decimal(10) ** decimals)
        result = float(value)
    except (InvalidOperation, OverflowError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def omitted_swap_economic_weight(
    con: duckdb.DuckDBPyConnection,
    *,
    token_decimals: Mapping[str, int],
    prices_path: Path,
) -> dict[str, object]:
    """Value exact missing-static swaps only where audited token-day inputs exist."""

    omitted = con.execute(
        """
        SELECT
            e.pool AS address,
            e.block_number,
            e.block_hash,
            e.transaction_hash,
            e.transaction_index,
            e.log_index,
            e.topics,
            e.data,
            e.removed,
            cast(c.day AS VARCHAR) AS day,
            r.token0,
            r.token1
        FROM exact_events e
        JOIN topics t ON e.topic=t.topic AND t.kind='swap'
        JOIN registry r USING(pool)
        ASOF JOIN calendar c ON e.block_number>=c.start_block
        WHERE NOT r.graph_present AND e.block_number<=c.day_end_block
        ORDER BY e.block_number, e.log_index
        """
    ).df()
    metadata = _exact_token_metadata(token_decimals)
    prices, prices_sha256 = _daily_prices(prices_path)
    rows: list[dict[str, object]] = []
    for source in omitted.to_dict("records"):
        source["topics"] = list(source["topics"])
        decoded = decode_inventory_log(source)
        day = str(source["day"]).replace("-", "")
        sides: list[float] = []
        for token, raw_amount in (
            (str(source["token0"]), int(decoded["amount0_delta_raw"])),
            (str(source["token1"]), int(decoded["amount1_delta_raw"])),
        ):
            token_metadata = metadata.get(token)
            price = prices.get((day, token))
            if token_metadata is None or price is None:
                continue
            notional = _raw_notional_usd(raw_amount, token_metadata, price)
            if notional is not None:
                sides.append(notional)
        rows.append(
            {
                "pool": str(source["address"]),
                "valued_sides": len(sides),
                "min_side_usd": min(sides) if sides else None,
                "max_side_usd": max(sides) if sides else None,
                "side_ratio": max(sides) / min(sides) if len(sides) == 2 and min(sides) > 0 else None,
            }
        )
    valued = [row for row in rows if row["valued_sides"]]
    both = [row for row in rows if row["valued_sides"] == 2]
    consistent = [row for row in both if row["side_ratio"] is not None and float(row["side_ratio"]) <= 2.0]
    ratios = pd.Series([row["side_ratio"] for row in both if row["side_ratio"] is not None], dtype="float64")
    by_pool = pd.DataFrame(
        rows,
        columns=["pool", "valued_sides", "min_side_usd", "max_side_usd", "side_ratio"],
    ).groupby("pool", as_index=False).agg(
        swaps=("pool", "size"),
        valued_swaps=("valued_sides", lambda values: int((values > 0).sum())),
        both_sides_valued=("valued_sides", lambda values: int((values == 2).sum())),
        priced_max_side_sensitivity_usd=("max_side_usd", "sum"),
    )
    by_pool = by_pool.sort_values(["swaps", "pool"], ascending=[False, True])
    return {
        "exact_omitted_swaps": len(rows),
        "valued_swaps": len(valued),
        "valued_swap_share": share(len(valued), len(rows)),
        "both_sides_valued_swaps": len(both),
        "both_sides_valued_share": share(len(both), len(rows)),
        "priced_max_side_sensitivity_usd": float(sum(float(row["max_side_usd"]) for row in valued)),
        "unvalued_swaps": len(rows) - len(valued),
        "two_side_consistent_within_2x_swaps": len(consistent),
        "two_side_consistent_within_2x_share": share(len(consistent), len(rows)),
        "two_side_consistent_midpoint_usd": float(sum((float(row["min_side_usd"]) + float(row["max_side_usd"])) / 2.0 for row in consistent)),
        "two_side_value_ratio_median": float(ratios.median()) if len(ratios) else None,
        "two_side_value_ratio_p95": float(ratios.quantile(0.95)) if len(ratios) else None,
        "top_omitted_pools": by_pool.head(20).to_dict("records"),
        "token_price_daily_sha256": prices_sha256,
        "interpretation": "The max-side total is only a sensitivity subtotal over swaps with at least one audited token-day price and non-conflicting exact decimals. It is neither a bound nor an admissible economic mass when the two priced sides disagree. The separately reported within-2x midpoint subset exposes that support limit.",
    }


def route_opportunity_exposure(
    route_release: ReleasedPartitionSet,
    *,
    pool: str,
    token0: str,
    token1: str,
    first_exposure_day: str,
    audit_days: list[str],
) -> dict[str, object]:
    """Bound where one defective pool could enter fixed-calendar route quotes."""

    token0, token1 = token0.lower(), token1.lower()
    token0_is_candidate = asset_type(token0) in CURRENCY_TYPES
    token1_is_candidate = asset_type(token1) in CURRENCY_TYPES
    candidate_endpoints = {*([token0] if token1_is_candidate else []), *([token1] if token0_is_candidate else [])}
    counters = {
        "exact_venue_two_leg_routes": 0,
        "pool_leg_opportunity_routes": 0,
        "direct_pool_pair_routes": 0,
        "audit_dates_with_pool_leg_opportunity": 0,
    }
    selected_days = [day for day in audit_days if day >= first_exposure_day]
    for day in selected_days:
        legs = route_release.read_day(day)
        routes = extract_linear_realised_routes(legs)
        exact = routes[routes["realised_hop1_source"].isin(EXACT_VENUES) & routes["realised_hop2_source"].isin(EXACT_VENUES)]
        direct = (exact["src"].eq(token0) & exact["tgt"].eq(token1)) | (exact["src"].eq(token1) & exact["tgt"].eq(token0))
        candidate = exact["src"].isin(candidate_endpoints) | exact["tgt"].isin(candidate_endpoints)
        exposed = direct | candidate
        counters["exact_venue_two_leg_routes"] += len(exact)
        counters["pool_leg_opportunity_routes"] += int(exposed.sum())
        counters["direct_pool_pair_routes"] += int(direct.sum())
        counters["audit_dates_with_pool_leg_opportunity"] += int(exposed.any())
    route_release.assert_current()
    return {
        "scope": "fixed_transaction_frontier_construction_audit_after_first_exact_swap",
        "pool": pool,
        "token0": token0,
        "token1": token1,
        "token0_is_route_candidate": token0_is_candidate,
        "token1_is_route_candidate": token1_is_candidate,
        "first_exposure_day": first_exposure_day,
        "audit_dates": len(selected_days),
        **counters,
        "pool_leg_opportunity_share": share(counters["pool_leg_opportunity_routes"], counters["exact_venue_two_leg_routes"]),
        "interpretation": "This is an exposure upper bound: a pool can enter a direct quote or a two-leg quote when its opposite token is an admitted route candidate. It does not say the pool wins the frontier or changes a headline estimate; the corrected-state frontier measures those effects.",
    }


def route_estimand_perturbation_bounds(
    route_release: ReleasedPartitionSet,
    *,
    pool_perimeter: Iterable[Mapping[str, object]],
    audit_days: Iterable[str],
) -> dict[str, object]:
    """Conservatively bound released route-share and cost estimands over every defective pool."""

    pools = [
        {
            "pool": str(row["pool"]).lower(),
            "token0": str(row["token0"]).lower(),
            "token1": str(row["token1"]).lower(),
            "first_exposure_day": str(row["first_exposure_day"]).replace("-", ""),
        }
        for row in pool_perimeter
    ]
    if not pools:
        return {
            "status": "pass_no_defective_state_pool",
            "defective_state_pools": 0,
            "vehicle_count_share_abs_change_upper_bound": 0.0,
            "vehicle_value_share_abs_change_upper_bound": 0.0,
            "value_weighted_route_cost_bps_reduction_upper_bound": 0.0,
        }
    totals = {
        "routes": 0,
        "value_usd": 0.0,
        "exposed_routes": 0,
        "exposed_value_usd": 0.0,
    }
    selected_days = sorted({str(day).replace("-", "") for day in audit_days})
    for day in selected_days:
        active = [pool for pool in pools if pool["first_exposure_day"] <= day]
        routes = extract_linear_realised_routes(route_release.read_day(day))
        exact = routes[
            routes["realised_hop1_source"].isin(EXACT_VENUES)
            & routes["realised_hop2_source"].isin(EXACT_VENUES)
        ].copy()
        if exact.empty:
            continue
        exact["input_usd"] = pd.to_numeric(exact["input_usd"], errors="coerce").fillna(0.0).clip(lower=0.0)
        exact["output_usd"] = pd.to_numeric(exact["output_usd"], errors="coerce").fillna(0.0).clip(lower=0.0)
        active_pairs = {frozenset((pool["token0"], pool["token1"])) for pool in active}
        candidate_links = {
            (endpoint, candidate)
            for pool in active
            for endpoint, candidate in (
                (pool["token0"], pool["token1"]),
                (pool["token1"], pool["token0"]),
            )
            if asset_type(candidate) in CURRENCY_TYPES
        }
        candidate_endpoints = {endpoint for endpoint, _candidate in candidate_links}
        exposed = exact.apply(
            lambda row: (
                frozenset((str(row["src"]), str(row["vehicle"]))) in active_pairs
                or frozenset((str(row["vehicle"]), str(row["tgt"]))) in active_pairs
                or frozenset((str(row["src"]), str(row["tgt"]))) in active_pairs
                or str(row["src"]) in candidate_endpoints
                or str(row["tgt"]) in candidate_endpoints
            ),
            axis=1,
        )
        input_value = exact["input_usd"]
        totals["routes"] += len(exact)
        totals["value_usd"] += float(input_value.sum())
        totals["exposed_routes"] += int(exposed.sum())
        totals["exposed_value_usd"] += float(input_value.loc[exposed].sum())
    route_release.assert_current()
    return {
        "status": "conservative_fixed-frontier_perturbation_bound",
        "defective_state_pools": len(pools),
        "audit_dates": len(selected_days),
        **totals,
        "vehicle_count_share_abs_change_upper_bound": share(totals["exposed_routes"], totals["routes"]),
        "vehicle_value_share_abs_change_upper_bound": share(totals["exposed_value_usd"], totals["value_usd"]),
        "value_weighted_route_cost_bps_reduction_upper_bound": None,
        "route_cost_bound_status": "requires_corrected_direct_and_candidate_quotes",
        "interpretation": "Every released exact-venue route whose realised hop, direct endpoint pair, or endpoint-candidate opportunity touches a defective pool is allowed to change vehicle identity. Its full input value may move vehicle share. Realised route loss cannot bound the omitted pool's direct-versus-indirect quoted-output advantage, so route-cost materiality remains uncleared until the corrected frontier is quoted.",
    }


def omitted_static_state_pool_perimeter(
    con: duckdb.DuckDBPyConnection,
    *,
    registry: pd.DataFrame,
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    """Return every Graph-absent pool from its first exact state-changing event."""

    omitted = registry.loc[
        ~registry["graph_present"], ["pool", "token0", "token1"]
    ].copy()
    if omitted.empty:
        return pd.DataFrame(
            columns=["pool", "token0", "token1", "first_exposure_day"]
        )
    con.register("omitted_static_pools", omitted)
    first_events = con.execute(
        """
        SELECT e.pool, min(e.block_number) AS first_exact_state_block
        FROM exact_events e
        JOIN topics t USING(topic)
        JOIN omitted_static_pools p USING(pool)
        WHERE t.kind IN ('mint', 'burn', 'swap')
        GROUP BY e.pool
        """
    ).df()
    if first_events.empty:
        return pd.DataFrame(
            columns=["pool", "token0", "token1", "first_exposure_day"]
        )
    bounded = calendar.sort_values("day_end_block").copy()
    day_ends = bounded["day_end_block"].astype("int64").tolist()
    days = bounded["day"].astype(str).str.replace("-", "").tolist()
    first_events["first_exposure_day"] = first_events[
        "first_exact_state_block"
    ].map(
        lambda block: days[
            min(bisect_left(day_ends, int(block)), len(days) - 1)
        ]
    )
    return first_events.merge(
        omitted,
        on="pool",
        how="left",
        validate="one_to_one",
    )[["pool", "token0", "token1", "first_exposure_day"]]


def event_coverage_clears_state_estimands(event_coverage: Mapping[str, object]) -> bool:
    """Whether Graph omissions leave every quote- and capital-changing event intact."""

    if "state_changing_event_defect_pools" not in event_coverage:
        raise ValueError(
            "Graph event coverage lacks state-changing defect status"
        )
    value = event_coverage["state_changing_event_defect_pools"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Graph state-changing defect count is invalid")
    return value == 0


def _sql_path_list(paths: list[Path]) -> str:
    if not paths:
        raise ValueError("Graph event coverage requires at least one provider file")
    return "[" + ",".join("'" + path.as_posix().replace("'", "''") + "'" for path in paths) + "]"


def graph_daily_provider_bound(
    con: duckdb.DuckDBPyConnection,
    *,
    certified_paths: Mapping[str, Path],
    days: Iterable[str],
    graph_pools: set[str],
) -> dict[str, object]:
    """Summarize only daily partitions admitted by the source-day perimeter."""

    normalized_days = [str(day).replace("-", "") for day in days]
    missing_days = [day for day in normalized_days if day not in certified_paths]
    if missing_days:
        raise ValueError(
            f"Graph daily provider bound lacks {len(missing_days)} certified days"
        )
    paths = [certified_paths[day] for day in normalized_days]
    graph_daily = con.execute(
        f"""
        SELECT lower(pool.id) AS pool,
               sum(try_cast(volumeUSD AS DOUBLE)) AS volume_usd,
               sum(try_cast(tvlUSD AS DOUBLE)) AS tvl_pool_day_usd,
               count(*) AS pool_days
        FROM read_json_auto({_sql_path_list(paths)}, format='newline_delimited', union_by_name=true)
        GROUP BY pool
        """
    ).df()
    graph_daily["graph_static_present"] = graph_daily["pool"].isin(graph_pools)
    missing_daily = graph_daily[~graph_daily["graph_static_present"]]
    return {
        "volume_usd": float(graph_daily["volume_usd"].sum()),
        "missing_static_volume_usd": float(missing_daily["volume_usd"].sum()),
        "missing_static_volume_share": share(
            missing_daily["volume_usd"].sum(), graph_daily["volume_usd"].sum()
        ),
        "tvl_pool_day_usd": float(graph_daily["tvl_pool_day_usd"].sum()),
        "missing_static_tvl_pool_day_usd": float(
            missing_daily["tvl_pool_day_usd"].sum()
        ),
        "missing_static_tvl_pool_day_share": share(
            missing_daily["tvl_pool_day_usd"].sum(),
            graph_daily["tvl_pool_day_usd"].sum(),
        ),
        "pool_days": int(graph_daily["pool_days"].sum()),
        "missing_static_pool_days": int(missing_daily["pool_days"].sum()),
        "missing_static_pools": int(missing_daily["pool"].nunique()),
    }


def graph_event_coverage_materiality(
    con: duckdb.DuckDBPyConnection,
    *,
    provider_paths: Mapping[str, Mapping[str, Path]],
    registry: pd.DataFrame,
    calendar: pd.DataFrame,
    audit_days: Iterable[str] = (),
) -> dict[str, object]:
    """Measure full-sample Graph count gaps without replacing the exact release gate."""

    exact_lower, exact_upper = con.execute("SELECT min(block_number), max(block_number) FROM exact_events").fetchone()
    exact_lower, exact_upper = int(exact_lower), int(exact_upper)
    eligible = registry[registry["graph_present"]][["pool", "vehicle_pair", "stable_pair"]].copy()
    con.register("eligible_graph_pools", eligible)
    bounded_calendar = calendar[calendar["start_block"].le(exact_upper) & calendar["day_end_block"].ge(exact_lower)].copy()
    bounded_calendar["month"] = bounded_calendar["day"].astype(str).str.replace("-", "").str[:6]
    con.register("v3_materiality_calendar", bounded_calendar)
    pool_frames: list[pd.DataFrame] = []
    stream_specs = (("swap", "swaps"), ("mint", "mints"), ("burn", "burns"))
    calendar_months = tuple(bounded_calendar.groupby("month", sort=True))
    for month_index, (month, month_calendar) in enumerate(calendar_months, start=1):
        lower = max(exact_lower, int(month_calendar["start_block"].min()))
        upper = min(exact_upper, int(month_calendar["day_end_block"].max()))
        days = month_calendar["day"].astype(str).str.replace("-", "").tolist()
        for kind, stream in stream_specs:
            certified_stream = provider_paths.get(stream)
            if certified_stream is None:
                raise ValueError(f"Graph event coverage lacks a certified {stream} stream")
            missing_days = [day for day in days if day not in certified_stream]
            if missing_days:
                raise ValueError(f"Graph event coverage month {month}/{stream} lacks {len(missing_days)} certified days")
            paths = [certified_stream[day] for day in days]
            frame = con.execute(
                f"""
                WITH exact_rows AS (
                    SELECT e.pool, lower(e.transaction_hash) AS tx_hash, e.block_number, e.log_index
                    FROM exact_events e JOIN eligible_graph_pools p USING(pool)
                    WHERE e.topic=? AND e.block_number BETWEEN ? AND ?
                ),
                provider_rows AS (
                    SELECT lower(g.pool.id) AS pool, lower(g.transaction.id) AS tx_hash,
                           cast(g.transaction.blockNumber AS BIGINT) AS block_number,
                           cast(g.logIndex AS BIGINT) AS log_index, cast(g.id AS VARCHAR) AS event_id
                    FROM read_json_auto({_sql_path_list(paths)}, format='newline_delimited', union_by_name=true) g
                    JOIN eligible_graph_pools p ON lower(g.pool.id)=p.pool
                    WHERE cast(g.transaction.blockNumber AS BIGINT) BETWEEN ? AND ?
                ),
                exact_groups AS (
                    SELECT pool, tx_hash, block_number, count(*) AS exact_rows FROM exact_rows GROUP BY ALL
                ),
                provider_groups AS (
                    SELECT pool, tx_hash, block_number, count(*) AS provider_rows, count(DISTINCT event_id) AS provider_entities
                    FROM provider_rows GROUP BY ALL
                ),
                structural AS (
                    SELECT coalesce(e.pool, p.pool) AS pool,
                           coalesce(e.block_number, p.block_number) AS block_number,
                           least(coalesce(e.exact_rows, 0), coalesce(p.provider_entities, 0)) AS structurally_matched_rows,
                           greatest(coalesce(e.exact_rows, 0)-coalesce(p.provider_entities, 0), 0) AS exact_only_rows,
                           greatest(coalesce(p.provider_entities, 0)-coalesce(e.exact_rows, 0), 0) AS provider_only_rows,
                           coalesce(e.exact_rows, 0) AS exact_rows, coalesce(p.provider_rows, 0) AS provider_rows,
                           coalesce(p.provider_rows-p.provider_entities, 0) AS duplicate_provider_entity_rows,
                           p.block_number AS provider_block
                    FROM exact_groups e FULL OUTER JOIN provider_groups p USING(pool, tx_hash, block_number)
                ),
                log_matches AS (
                    SELECT e.pool, count(*) AS exact_log_matches FROM exact_rows e
                    JOIN (SELECT DISTINCT pool, tx_hash, block_number, log_index FROM provider_rows) p
                    USING(pool, tx_hash, block_number, log_index) GROUP BY e.pool
                )
                SELECT s.pool, sum(s.exact_rows) AS exact_rows, sum(s.provider_rows) AS provider_rows,
                       sum(s.structurally_matched_rows) AS structurally_matched_rows,
                       sum(s.exact_only_rows) AS exact_only_rows, sum(s.provider_only_rows) AS provider_only_rows,
                       sum(s.duplicate_provider_entity_rows) AS duplicate_provider_entity_rows,
                       coalesce(max(l.exact_log_matches), 0) AS exact_log_matches,
                       min(s.block_number) FILTER (WHERE s.exact_only_rows>0) AS first_exact_only_block,
                       min(s.provider_block) AS first_provider_block
                FROM structural s LEFT JOIN log_matches l USING(pool) GROUP BY s.pool
                """,
                [EVENT_TOPICS[kind], lower, upper, lower, upper],
            ).df()
            frame["month"] = str(month)
            frame["kind"] = kind
            pool_frames.append(frame)
        print(f"COVERAGE: month={month}; months_complete={month_index:,}/{len(calendar_months):,}", flush=True)
    coverage = pd.concat(pool_frames, ignore_index=True).merge(eligible, on="pool", how="left", validate="many_to_one")
    count_columns = ["exact_rows", "provider_rows", "structurally_matched_rows", "exact_only_rows", "provider_only_rows", "duplicate_provider_entity_rows", "exact_log_matches"]
    for column in count_columns:
        coverage[column] = coverage[column].fillna(0).astype("int64")
    monthly = coverage.groupby(["month", "kind"], as_index=False)[count_columns].sum().sort_values(["month", "kind"])
    by_kind: dict[str, dict[str, object]] = {}
    for kind, frame in coverage.groupby("kind"):
        totals = frame[count_columns].sum()
        vehicle = frame[frame["vehicle_pair"]][count_columns].sum()
        stable = frame[frame["stable_pair"]][count_columns].sum()
        by_kind[str(kind)] = {
            **{column: int(totals[column]) for column in count_columns},
            "exact_only_share": share(totals["exact_only_rows"], totals["exact_rows"]),
            "provider_only_share": share(totals["provider_only_rows"], totals["provider_rows"]),
            "vehicle_exact_only_rows": int(vehicle["exact_only_rows"]),
            "vehicle_exact_only_share": share(vehicle["exact_only_rows"], vehicle["exact_rows"]),
            "stable_exact_only_rows": int(stable["exact_only_rows"]),
            "stable_exact_only_share": share(stable["exact_only_rows"], stable["exact_rows"]),
        }
    provider_first = coverage[coverage["kind"].eq("swap") & coverage["first_provider_block"].notna()].groupby("pool", as_index=False)["first_provider_block"].min()
    provider_first["first_provider_block"] = provider_first["first_provider_block"].astype("int64")
    con.register("first_provider_swap", provider_first)
    pre_provider = con.execute(
        """
        SELECT t.kind, p.vehicle_pair, p.stable_pair,
               count(*) FILTER (WHERE e.block_number<f.first_provider_block) AS events_before_first_provider_swap,
               count(DISTINCT e.pool) FILTER (WHERE e.block_number<f.first_provider_block) AS pools_before_first_provider_swap,
               count(*) FILTER (WHERE e.block_number=f.first_provider_block) AS events_on_first_provider_block
        FROM exact_events e JOIN topics t USING(topic) JOIN eligible_graph_pools p USING(pool) JOIN first_provider_swap f USING(pool)
        WHERE t.kind IN ('mint', 'swap') GROUP BY ALL ORDER BY ALL
        """
    ).df()
    no_provider = con.execute(
        """
        SELECT count(*) AS exact_swaps, count(DISTINCT e.pool) AS pools,
               count(*) FILTER (WHERE p.vehicle_pair) AS vehicle_exact_swaps,
               count(*) FILTER (WHERE p.stable_pair) AS stable_exact_swaps
        FROM exact_events e JOIN eligible_graph_pools p USING(pool) LEFT JOIN first_provider_swap f USING(pool)
        WHERE e.topic=? AND f.pool IS NULL
        """,
        [EVENT_TOPICS["swap"]],
    ).fetchone()
    first_mints = con.execute(
        """
        SELECT e.pool, min(e.block_number) AS first_mint_block, f.first_provider_block, p.vehicle_pair, p.stable_pair
        FROM exact_events e JOIN first_provider_swap f USING(pool) JOIN eligible_graph_pools p USING(pool)
        WHERE e.topic=? GROUP BY ALL HAVING min(e.block_number)<f.first_provider_block
        """,
        [EVENT_TOPICS["mint"]],
    ).df()
    day_ends = bounded_calendar["day_end_block"].astype("int64").tolist()
    day_values = pd.to_datetime(bounded_calendar["day"]).tolist()

    def block_day(block: int) -> pd.Timestamp:
        position = bisect_left(day_ends, int(block))
        return pd.Timestamp(day_values[min(position, len(day_values) - 1)])

    gaps = pd.Series([(block_day(int(row.first_provider_block)) - block_day(int(row.first_mint_block))).days for row in first_mints.itertuples()], dtype="int64")
    swap_pool_totals = (
        coverage[coverage["kind"].eq("swap")]
        .groupby("pool", as_index=False)[count_columns]
        .sum()
    )
    defective_swap_pools = swap_pool_totals.loc[
        swap_pool_totals["exact_only_rows"].gt(0)
    ].copy()
    top_missing_swaps = defective_swap_pools.sort_values(
        ["exact_only_rows", "pool"], ascending=[False, True]
    ).head(20)
    state_defects = (
        coverage.loc[coverage["exact_only_rows"].gt(0)]
        .pivot_table(
            index="pool",
            columns="kind",
            values="exact_only_rows",
            aggfunc="sum",
            fill_value=0,
        )
        .rename(
            columns={
                "swap": "exact_only_swap_rows",
                "mint": "exact_only_mint_rows",
                "burn": "exact_only_burn_rows",
            }
        )
        .reset_index()
    )
    for column in (
        "exact_only_swap_rows",
        "exact_only_mint_rows",
        "exact_only_burn_rows",
    ):
        if column not in state_defects:
            state_defects[column] = 0
        state_defects[column] = state_defects[column].astype("int64")
    first_defect_blocks = (
        coverage.loc[coverage["exact_only_rows"].gt(0)]
        .groupby("pool", as_index=False)["first_exact_only_block"]
        .min()
        .rename(columns={"first_exact_only_block": "first_defective_event_block"})
    )
    state_defects = state_defects.merge(
        first_defect_blocks,
        on="pool",
        how="left",
        validate="one_to_one",
    )
    state_defects["first_defective_event_block"] = state_defects[
        "first_defective_event_block"
    ].astype("int64")
    state_defects["first_exposure_day"] = state_defects[
        "first_defective_event_block"
    ].map(lambda block: block_day(int(block)).strftime("%Y%m%d"))
    state_defects["exact_only_liquidity_rows"] = (
        state_defects["exact_only_mint_rows"]
        + state_defects["exact_only_burn_rows"]
    )
    state_defects["exact_only_state_rows"] = (
        state_defects["exact_only_swap_rows"]
        + state_defects["exact_only_liquidity_rows"]
    )
    state_defects = state_defects.sort_values(
        ["exact_only_state_rows", "pool"], ascending=[False, True]
    )
    con.register(
        "exact_only_swap_pools", defective_swap_pools[["pool"]].copy()
    )
    top_swap_days = con.execute(
        """
        SELECT e.pool, cast(c.day AS VARCHAR) AS day, count(*) AS exact_swaps
        FROM exact_events e JOIN exact_only_swap_pools p USING(pool) JOIN topics t ON e.topic=t.topic AND t.kind='swap'
        ASOF JOIN v3_materiality_calendar c ON e.block_number>=c.start_block
        WHERE e.block_number<=c.day_end_block GROUP BY ALL ORDER BY e.pool, day
        """
    ).df()
    normalized_audit_days = {str(day).replace("-", "") for day in audit_days}
    if top_swap_days.empty:
        exposure = pd.DataFrame(columns=["pool", "first_exact_swap_day", "last_exact_swap_day", "exact_swap_days", "exact_swaps", "audit_dates_with_exact_swaps", "exact_swaps_on_audit_dates"])
    else:
        top_swap_days["day"] = top_swap_days["day"].str.replace("-", "")
        top_swap_days["audit_day"] = top_swap_days["day"].isin(normalized_audit_days)
        exposure = top_swap_days.groupby("pool", as_index=False).agg(
            first_exact_swap_day=("day", "min"),
            last_exact_swap_day=("day", "max"),
            exact_swap_days=("day", "nunique"),
            exact_swaps=("exact_swaps", "sum"),
            audit_dates_with_exact_swaps=("audit_day", "sum"),
            exact_swaps_on_audit_dates=("exact_swaps", lambda values: int(values[top_swap_days.loc[values.index, "audit_day"]].sum())),
        )
    defective_swap_pools = defective_swap_pools.merge(exposure, on="pool", how="left")
    for column in ("exact_swap_days", "exact_swaps", "audit_dates_with_exact_swaps", "exact_swaps_on_audit_dates"):
        defective_swap_pools[column] = defective_swap_pools[column].fillna(0).astype("int64")
    top_missing_swaps = defective_swap_pools.sort_values(
        ["exact_only_rows", "pool"], ascending=[False, True]
    ).head(20)
    return {
        "exact_block_perimeter": [exact_lower, exact_upper],
        "by_kind": by_kind,
        "computational_month_shards": monthly.to_dict("records"),
        "top_exact_only_swap_pools": top_missing_swaps.to_dict("records"),
        "exact_only_swap_pool_perimeter": defective_swap_pools.to_dict("records"),
        "top_exact_only_state_pools": state_defects.head(20).to_dict("records"),
        "exact_only_state_pool_perimeter": state_defects.to_dict("records"),
        "state_changing_event_defect_pools": int(len(state_defects)),
        "liquidity_event_defect_pools": int(
            state_defects["exact_only_liquidity_rows"].gt(0).sum()
        ),
        "pre_first_provider_swap": {
            "cells": pre_provider.to_dict("records"),
            "graph_present_pools_with_exact_swaps_but_no_provider_swap": int(no_provider[1]),
            "exact_swaps_in_graph_present_pools_with_no_provider_swap": int(no_provider[0]),
            "vehicle_exact_swaps_with_no_provider_swap": int(no_provider[2]),
            "stable_exact_swaps_with_no_provider_swap": int(no_provider[3]),
            "funded_pools_before_first_provider_swap": int(len(first_mints)),
            "funded_interval_days_median": float(gaps.median()) if len(gaps) else None,
            "funded_interval_days_p95": float(gaps.quantile(0.95)) if len(gaps) else None,
            "interpretation": "Strictly earlier blocks form the admitted pre-provider exposure. Same-block events are reported separately because provider log order is not used as exact authority. Factory creation remains only an outer bound; first exact Mint marks funded exposure.",
        },
        "interpretation": "Calendar months are bounded execution shards, not analysis horizons. Structural pool-transaction-block counts separate count omissions from provider log-index differences. Exact-log matches remain diagnostic; the fixed-calendar release audit is the authority for payload equivalence and corrected-state admissibility. Exact swap-day exposure for the top pools counts every exact swap, not only structurally exact-only rows.",
    }

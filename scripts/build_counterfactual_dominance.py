#!/usr/bin/env python3
"""Cost-dominance windows, measured against a same-state counterfactual.

The question the paper's inertia claim depends on: are there windows in which an
incumbent intermediary keeps carrying routed volume while a direct route would
have returned strictly more output at the same market state?

Why this design and not the previous one. Comparing realised trades across a day
fails, because intraday price movement swamps execution cost by roughly 34 to 1
(`docs/finding-cost-dominance-not-yet-established.md`). Here both routes are
priced against the *same* reconstructed pre-trade reserves, so price movement
cannot enter the comparison at all.

Method, per executed indirect (two-leg) route:
  1. reconstruct exact pre-trade reserves for every v2-family pool in that hour by
     unwinding the hour's swaps backward from the stored end-of-hour reserve
     (validated at median absolute error 0.0000%, 95.2% within 0.01%)
  2. replay fetched Uniswap v2 mints and burns in the same block-log timeline and
     keep only pool-hours whose full reserve continuity checks out; SushiSwap hours
     remain swap-only because their liquidity-event stream is unavailable
  3. read the realised output of the canonical two-leg route component
  4. quote the best available DIRECT pool for the same endpoints and input size at
     the same reserves
  5. write the gross same-state route panel before any gas-price dependency
  6. join the realised transaction's exact receipt gas price by transaction and
     block, then apply that common price to receipt-calibrated direct and indirect
     route-unit estimates

A cell is a cost-dominance window when the direct quote strictly exceeds the
intermediated quote, meaning the trade would have been better off going direct at
the moment it was made.

Bias directions:
  - venue coverage is v2-family only, so the best alternative is understated and
    dominance incidence is a LOWER bound
  - gross quotes omit gas and therefore favour the two-hop realised route; the
    gross dominance incidence is a LOWER bound on all-in dominance
  - the realised transaction's effective gas price includes its urgency bid; the
    same-block base-fee sensitivity is a separate registered estimate

Reads   the canonical constant-product market-state layer
Writes  data/processed/counterfactual_dominance_gross.parquet
        data/processed/counterfactual_dominance.parquet
        output/exhibits/counterfactual_dominance_summary.jsonl
        output/exhibits/counterfactual_dominance_support.jsonl
        output/exhibits/counterfactual_dominance_receipt_allocation_support.jsonl
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
from math import isfinite

import pandas as pd

from ddvc.analysis.regression import mean_clustered
from ddvc.asset_types import WETH, classify
from ddvc.data_release import ReleasedPartitionSet, release_preinstall_validator, require_node_d_release
from ddvc.cpquote import (
    Pool,
    all_in_direct_advantage_bps_from_units,
    cost_gap_bps,
    quote_one_hop,
)
from ddvc.counterfactual_publication import (
    publication_capability,
    publication_marker_path,
    register_publication_capability,
    require_current_publication,
    require_active_publication,
)
from ddvc.gas import load_route_transaction_gas
from ddvc.external_prices import validate_external_weth_usd_release
from ddvc.paths import (
    DATA_DIR,
    EXTERNAL_WETH_USD_INTRADAY_PANEL,
    EXTERNAL_WETH_USD_RAW_ROOT,
    OUTPUT_DIR,
    REPO_ROOT,
)
from ddvc.prices import (
    PRICE_COLUMNS,
    attach_strictly_prior_weth_usd,
    day_prices,
    load_intraday_weth_usd_marks,
)
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.pricing.v2_replay import V2_VENUES, load_v2_replay_day
from ddvc.provenance import require_current_artifacts, sidecar_path
from ddvc.route_gas import GAS_ESTIMATE_COLUMNS, estimate_route_gas
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.data_release import released_route_partitions, released_state_partitions
from ddvc.state_data import CP_COLUMNS, STATE_ROOT
from ddvc.tables import write_exhibit, write_panel

MARKET_STATE = STATE_ROOT
UNIFIED = DATA_DIR / "unified"
OUT_PARQUET = DATA_DIR / "processed" / "counterfactual_dominance.parquet"
GROSS_PARQUET = DATA_DIR / "processed" / "counterfactual_dominance_gross.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "counterfactual_dominance_summary.jsonl"
OUT_SUPPORT = OUTPUT_DIR / "exhibits" / "counterfactual_dominance_support.jsonl"
OUT_RECEIPT_ALLOCATION_SUPPORT = OUTPUT_DIR / "exhibits" / "counterfactual_dominance_receipt_allocation_support.jsonl"
LOCK = OUT_PARQUET.with_suffix(".lock")
TRANSACTION_GAS_PANEL = DATA_DIR / "processed" / "route_transaction_gas.parquet"
ROUTE_GAS_PANEL = DATA_DIR / "processed" / "route_gas_units.parquet"
CODE_SOURCES = [
    "scripts/build_counterfactual_dominance.py",
    "src/ddvc/calendar.py",
    "src/ddvc/cpquote.py",
    "src/ddvc/counterfactual_publication.py",
    "src/ddvc/journaled_capability.py",
    "src/ddvc/pricing/v2_replay.py",
    "src/ddvc/state_data.py",
    "src/ddvc/gas.py",
    "src/ddvc/external_prices.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/prices.py",
    "src/ddvc/paths.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_gas.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/runtime.py",
]

register_publication_capability(
    "counterfactual.gross",
    (
        GROSS_PARQUET,
        sidecar_path(GROSS_PARQUET),
        OUT_RECEIPT_ALLOCATION_SUPPORT,
        sidecar_path(OUT_RECEIPT_ALLOCATION_SUPPORT),
    ),
)
register_publication_capability(
    "counterfactual.final_panel",
    (OUT_PARQUET, sidecar_path(OUT_PARQUET)),
)
register_publication_capability(
    "counterfactual.final_exhibits",
    (OUT_EXHIBIT, sidecar_path(OUT_EXHIBIT), OUT_SUPPORT, sidecar_path(OUT_SUPPORT)),
)

VENUES = V2_VENUES
MIN_USD = 100.0            # below this, gas dominates and the comparison is moot


def target_price_usd(
    prices: dict[str, tuple[object, float]], token: str
) -> float | None:
    """A usable target-token price, or explicit unsupported state."""
    record = prices.get(token)
    if record is None:
        return None
    value = float(record[1])
    return value if isfinite(value) and value > 0 else None


def common_mark_direct_advantage_bps(
    direct_output: Decimal | float,
    realised_output: Decimal | float,
    *,
    output_price_usd: Decimal | float,
    input_notional_usd: Decimal | float,
) -> float | None:
    """Value a same-token route-output difference at one common mark."""
    values = tuple(
        Decimal(str(value))
        for value in (
            direct_output,
            realised_output,
            output_price_usd,
            input_notional_usd,
        )
    )
    if not all(value.is_finite() for value in values) or any(
        value <= 0 for value in values
    ):
        return None
    direct, realised, price, notional = values
    return float(Decimal(10_000) * (direct - realised) * price / notional)


def counterfactual_days(
    available: list[str], *, explicit: list[str] | None = None, limit: int | None = None
) -> list[str]:
    """Select the full daily calendar, or exact explicit validation days."""
    days = list(dict.fromkeys(explicit)) if explicit else sorted(set(available))
    return days[:limit] if limit is not None else days


def receipt_allocation_support(day: str, routes: pd.DataFrame, unified: pd.DataFrame) -> tuple[pd.Index, dict[str, object]]:
    """Quantify and identify routes whose whole-transaction receipt is not allocable."""

    declared_components = pd.to_numeric(unified["n_components"], errors="coerce")
    transaction_contract = unified.assign(_declared_components=declared_components).groupby("tx_hash", sort=False).agg(declared_min=("_declared_components", "min"), declared_max=("_declared_components", "max"), observed_components=("component_id", "nunique"))
    admitted_transactions = transaction_contract.index[transaction_contract["declared_min"].eq(1) & transaction_contract["declared_max"].eq(1) & transaction_contract["observed_components"].eq(1)]
    admitted = routes["tx_hash"].isin(admitted_transactions)
    if routes.loc[admitted, "tx_hash"].duplicated(keep=False).any():
        raise ValueError("one single-component transaction cannot own multiple gross route rows")
    notionals = pd.to_numeric(routes["input_usd"], errors="coerce").fillna(0.0)
    candidate_transactions = routes["tx_hash"].nunique()
    admitted_transactions_count = routes.loc[admitted, "tx_hash"].nunique()
    return admitted_transactions, {
        "scope": "daily",
        "date": pd.to_datetime(day, format="%Y%m%d"),
        "year": int(day[:4]),
        "receipt_allocation_estimand": "single_reconstructed_component_transactions_only",
        "candidate_transactions": int(candidate_transactions),
        "candidate_routes": int(len(routes)),
        "candidate_route_notional_usd": float(notionals.sum()),
        "admitted_transactions": int(admitted_transactions_count),
        "admitted_routes": int(admitted.sum()),
        "admitted_route_notional_usd": float(notionals[admitted].sum()),
        "excluded_multi_component_transactions": int(candidate_transactions - admitted_transactions_count),
        "excluded_multi_component_routes": int((~admitted).sum()),
        "excluded_multi_component_route_notional_usd": float(notionals[~admitted].sum()),
    }


def receipt_allocation_support_summary(daily: pd.DataFrame) -> pd.DataFrame:
    """Retain daily exclusions and add pooled and annual support-loss totals."""

    count_columns = ["candidate_transactions", "candidate_routes", "admitted_transactions", "admitted_routes", "excluded_multi_component_transactions", "excluded_multi_component_routes"]
    value_columns = ["candidate_route_notional_usd", "admitted_route_notional_usd", "excluded_multi_component_route_notional_usd"]
    rows = daily.to_dict("records")
    for scope, groups in (("pooled", [(None, daily)]), ("annual", daily.groupby("year", sort=True))):
        for year, group in groups:
            row = {"scope": scope, "date": None, "year": int(year) if year is not None else None, "receipt_allocation_estimand": "single_reconstructed_component_transactions_only"}
            row.update({column: int(group[column].sum()) for column in count_columns})
            row.update({column: float(group[column].sum()) for column in value_columns})
            row["excluded_multi_component_route_share"] = row["excluded_multi_component_routes"] / row["candidate_routes"] if row["candidate_routes"] else None
            row["excluded_multi_component_notional_share"] = row["excluded_multi_component_route_notional_usd"] / row["candidate_route_notional_usd"] if row["candidate_route_notional_usd"] else None
            rows.append(row)
    return pd.DataFrame(rows)


def gross_panel_inputs(
    route_release: ReleasedPartitionSet,
    state_releases: dict[str, ReleasedPartitionSet],
) -> list[Path]:
    """Declare the gross release inputs, including the allocation support-loss audit."""

    return [
        *route_release.provenance_inputs,
        *(path for release in state_releases.values() for path in release.provenance_inputs),
        OUT_RECEIPT_ALLOCATION_SUPPORT,
    ]


def _write_gross_release(
    frame: pd.DataFrame,
    *,
    route_release: ReleasedPartitionSet | None = None,
    state_releases: dict[str, ReleasedPartitionSet] | None = None,
) -> Path:
    """Publish gross routes only when every receipt has exactly one owning row."""

    required = {"tx", "receipt_allocation_scope"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("gross route release lacks receipt-ownership columns: " + ", ".join(missing))
    transactions = frame["tx"].astype(str).str.lower()
    if transactions.eq("").any() or transactions.duplicated(keep=False).any():
        raise ValueError("one transaction receipt cannot be allocated to multiple gross route rows")
    if not frame["receipt_allocation_scope"].eq("single_reconstructed_component_transaction").all():
        raise ValueError("gross route release violates the single-component receipt allocation contract")
    if route_release is None or state_releases is None:
        raise ValueError("gross route publication requires released route and state identities")
    require_active_publication("counterfactual.gross")
    write_panel(
        frame,
        GROSS_PARQUET,
        code_sources=CODE_SOURCES,
        inputs=gross_panel_inputs(route_release, state_releases),
        notes=f"gross V2-family exact-size direct counterfactual at strict pre-transaction block-log state for single-component transactions only, released before any gas-price dependency and bound to the receipt-allocation support-loss audit; route release {route_release.content_identity_sha256}; state releases {','.join(release.content_identity_sha256 for release in state_releases.values())}",
        preinstall_validator=release_preinstall_validator(
            route_release, *state_releases.values()
        ),
    )
    return GROSS_PARQUET


def _release_sources(
    route_release: ReleasedPartitionSet,
    state_releases: dict[str, ReleasedPartitionSet],
) -> list[Path]:
    return [
        path
        for release in (route_release, *state_releases.values())
        for path in release.provenance_inputs
    ]


def _assert_releases_current(
    route_release: ReleasedPartitionSet,
    state_releases: dict[str, ReleasedPartitionSet],
) -> None:
    release_preinstall_validator(
        route_release, *state_releases.values()
    )(Path("<publication-boundary>"))


@publication_capability(
    "counterfactual.gross",
    output_selector=lambda *_args, **_kwargs: (
        GROSS_PARQUET,
        sidecar_path(GROSS_PARQUET),
        OUT_RECEIPT_ALLOCATION_SUPPORT,
        sidecar_path(OUT_RECEIPT_ALLOCATION_SUPPORT),
    ),
    source_selector=lambda _frame, _support, route_release, state_releases: _release_sources(route_release, state_releases),
    assert_current=lambda _frame, _support, route_release, state_releases: _assert_releases_current(route_release, state_releases),
)
def build_gross_publication(
    frame: pd.DataFrame,
    allocation_support: pd.DataFrame,
    route_release: ReleasedPartitionSet,
    state_releases: dict[str, ReleasedPartitionSet],
) -> Path:
    """Publish the route-only support audit and full gross panel atomically."""

    require_active_publication("counterfactual.gross")
    write_exhibit(
        allocation_support,
        OUT_RECEIPT_ALLOCATION_SUPPORT,
        code_sources=CODE_SOURCES,
        inputs=list(route_release.provenance_inputs),
        notes=f"daily, annual and pooled support loss from excluding transactions with more than one reconstructed component because one whole-transaction receipt is not allocated across route rows; released-route identity {route_release.content_identity_sha256}",
        preinstall_validator=release_preinstall_validator(route_release),
    )
    return _write_gross_release(
        frame,
        route_release=route_release,
        state_releases=state_releases,
    )


FINAL_INPUTS = (
    GROSS_PARQUET,
    TRANSACTION_GAS_PANEL,
    ROUTE_GAS_PANEL,
    EXTERNAL_WETH_USD_INTRADAY_PANEL,
)


def _final_input_sources() -> tuple[Path, ...]:
    return (
        *FINAL_INPUTS,
        *(sidecar_path(path) for path in FINAL_INPUTS),
        publication_marker_path("counterfactual.gross"),
    )


def _assert_final_inputs_current(_staged_path: Path | None = None) -> None:
    require_current_publication(
        "counterfactual.gross",
        expected_outputs=(
            GROSS_PARQUET,
            sidecar_path(GROSS_PARQUET),
            OUT_RECEIPT_ALLOCATION_SUPPORT,
            sidecar_path(OUT_RECEIPT_ALLOCATION_SUPPORT),
        ),
    )
    require_current_artifacts(
        list(FINAL_INPUTS),
        consumer="gas-adjusted counterfactual-dominance panel",
    )
    validate_external_weth_usd_release(
        EXTERNAL_WETH_USD_INTRADAY_PANEL,
        EXTERNAL_WETH_USD_RAW_ROOT,
    )


@publication_capability(
    "counterfactual.final_panel",
    output_selector=lambda: (OUT_PARQUET, sidecar_path(OUT_PARQUET)),
    source_selector=lambda: _final_input_sources(),
    assert_current=lambda: _assert_final_inputs_current(),
)
def build_final_panel() -> pd.DataFrame:
    """Install the final panel under the exact current inputs it reads."""

    require_active_publication("counterfactual.final_panel")
    frame = add_topology_gas_adjustment(pd.read_parquet(GROSS_PARQUET))
    write_panel(
        frame,
        OUT_PARQUET,
        code_sources=CODE_SOURCES,
        inputs=list(_final_input_sources()),
        notes="V2-family exact-size direct counterfactual with exact block-header time, receipt execution plus blob gas fields, receipt-calibrated route gas units and an independent strictly prior intraday WETH/USD mark; canonical all-in bps withheld because endpoint notionals remain address-day priced, with explicitly named daily-denominator sensitivities retained",
        preinstall_validator=_assert_final_inputs_current,
    )
    return frame


def _assert_final_panel_current(_staged_path: Path | None = None) -> None:
    require_current_publication(
        "counterfactual.final_panel",
        expected_outputs=(OUT_PARQUET, sidecar_path(OUT_PARQUET)),
    )
    require_current_artifacts(
        [OUT_PARQUET], consumer="counterfactual-dominance exhibits"
    )


@publication_capability(
    "counterfactual.final_exhibits",
    output_selector=lambda: (
        OUT_EXHIBIT,
        sidecar_path(OUT_EXHIBIT),
        OUT_SUPPORT,
        sidecar_path(OUT_SUPPORT),
    ),
    source_selector=lambda: (
        OUT_PARQUET,
        sidecar_path(OUT_PARQUET),
        publication_marker_path("counterfactual.final_panel"),
    ),
    assert_current=lambda: _assert_final_panel_current(),
)
def build_final_exhibits() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Publish both exhibits from one exact installed panel."""

    require_active_publication("counterfactual.final_exhibits")
    frame = pd.read_parquet(OUT_PARQUET)
    annual = frame.groupby(
        [
            pd.Grouper(key="date", freq="YS"),
            "mid_type",
            "best_direct_outside_realised_venue_set",
        ]
    ).agg(
        routes=("gross_direct_advantage_bps", "size"),
        pct_dominated_gross=("direct_output_improvement_bps", lambda values: 100 * (values > 0).mean()),
        median_gross_direct_advantage_bps=("gross_direct_advantage_bps", "median"),
        median_direct_output_improvement_bps=("direct_output_improvement_bps", "median"),
        valuation_coherent_2x_routes=("valuation_coherent_2x", "sum"),
        pct_dominated_valuation_coherent_2x=("dominated_valuation_coherent_2x", lambda values: 100 * values.dropna().mean()),
        valuation_coherent_20pct_routes=("valuation_coherent_20pct", "sum"),
        pct_dominated_valuation_coherent_20pct=("dominated_valuation_coherent_20pct", lambda values: 100 * values.dropna().mean()),
        daily_denominator_sensitivity_gas_supported_routes=("daily_denominator_sensitivity_all_in_direct_advantage_bps", "count"),
        daily_denominator_sensitivity_pct_dominated_topology_gas_adjusted=("daily_denominator_sensitivity_all_in_direct_advantage_bps", lambda values: 100 * (values.dropna() > 0).mean()),
        daily_denominator_sensitivity_pct_dominated_gas_iqr_lower=("daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower", lambda values: 100 * (values.dropna() > 0).mean()),
        daily_denominator_sensitivity_pct_dominated_gas_iqr_upper=("daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper", lambda values: 100 * (values.dropna() > 0).mean()),
    ).reset_index()
    annual.insert(0, "scope", "annual_type_reach")
    summary = pd.concat(
        [dominance_level_summary(frame), annual], ignore_index=True, sort=False
    )
    inputs = [
        OUT_PARQUET,
        sidecar_path(OUT_PARQUET),
        publication_marker_path("counterfactual.final_panel"),
    ]
    write_exhibit(
        summary,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="pooled and annual exact-size V2-family direct counterfactual; pooled rows retain route and equal-date weighting, date-clustered uncertainty, dollar magnitude and strict valuation support; gas-adjusted bps are explicitly noncanonical daily-denominator sensitivities until transaction-time endpoint USD marks exist; annual rows split intermediary type and realised venue reach",
        preinstall_validator=_assert_final_panel_current,
    )
    support = state_support_summary(frame)
    write_exhibit(
        support,
        OUT_SUPPORT,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes="reserve-state support split; adjacent means all three prior observations are one hour back with no liquidity event, bridged advances a more distant observed state through all intervening raw events, and replayed includes at least one mint or burn",
        preinstall_validator=_assert_final_panel_current,
    )
    return frame, support


def one_day(
    day: str,
    route_release: ReleasedPartitionSet | None = None,
    state_releases: dict[str, ReleasedPartitionSet] | None = None,
) -> tuple[pd.DataFrame | None, dict[str, object] | None]:
    if route_release is None or state_releases is None:
        raise ValueError("counterfactual day construction requires released route and state partitions")
    previous_day = (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    state_frames = {
        (venue, selected_day): release.read_day(selected_day)
        for venue, release in state_releases.items()
        for selected_day in (previous_day, day)
        if selected_day in release.days
    }
    replay = load_v2_replay_day(
        MARKET_STATE,
        day,
        venues=VENUES,
        state_frames=state_frames,
    )
    unified = route_release.read_day(day)
    if not replay.pool_hour_events or not replay.swaps_by_pool_hour:
        return None, None
    prices = day_prices(unified[PRICE_COLUMNS])
    routes = extract_linear_realised_routes(unified)
    if routes.empty:
        return None, None
    routes = routes[
        routes["realised_hop1_source"].isin(VENUES)
        & routes["realised_hop2_source"].isin(VENUES)
    ].copy()
    if routes.empty:
        return None, None
    single_component_transactions, allocation_support = receipt_allocation_support(day, routes, unified)
    routes = routes[routes["tx_hash"].isin(single_component_transactions)].copy()
    if routes.empty:
        return None, allocation_support
    component_keys = ["tx_hash", "component_id"]
    eligible_keys = {
        (str(tx_hash).lower(), int(component_id))
        for tx_hash, component_id in zip(
            routes["tx_hash"], routes["component_id"], strict=True
        )
    }
    route_legs = unified[
        unified["route_class"].eq("coherent")
        & unified["source"].isin(VENUES)
    ].copy()
    route_legs = route_legs[
        [
            (str(tx_hash).lower(), int(component_id)) in eligible_keys
            for tx_hash, component_id in zip(
                route_legs["tx_hash"], route_legs["component_id"], strict=True
            )
        ]
    ]
    grouped_legs = {
        (str(key[0]).lower(), int(key[1])): group.sort_values(
            "log_index", kind="stable"
        )
        for key, group in route_legs.groupby(component_keys, sort=False)
    }

    rows = []
    for route in routes.to_dict("records"):
        tx = str(route["tx_hash"]).lower()
        component_key = (tx, int(route["component_id"]))
        legs = grouped_legs.get(component_key)
        if legs is None or len(legs) != 2:
            continue
        raw_legs = [
            replay.swaps_by_identity.get((str(source), tx, int(log_index)))
            for source, log_index in zip(
                legs["source"], legs["log_index"], strict=True
            )
        ]
        if any(leg is None for leg in raw_legs):
            continue
        l1, l2 = raw_legs
        assert l1 is not None and l2 is not None
        if any(
            (leg.venue, leg.pool, leg.hour) not in replay.pool_hour_events
            for leg in (l1, l2)
        ):
            continue
        if l1.order[0] != l2.order[0] or l1.hour != l2.hour:
            continue
        route_order = min(l1.order, l2.order)
        a_in = str(route["src"]).lower()
        mid1 = str(route["vehicle"]).lower()
        b_out = str(route["tgt"]).lower()
        amt_in = Decimal(str(route["realised_amount_in"]))
        out_amt = Decimal(str(route["realised_amount_out"]))
        usd = float(route["input_usd"])
        if usd < MIN_USD:
            continue

        # counterfactual: best DIRECT pool for the same endpoints at the same state.
        # Indexed by unordered pair, so this is a lookup instead of a scan.
        cands = replay.candidates(a_in, b_out)
        if not cands:
            continue                            # no direct pool existed: not a window
        best_direct = None
        best_direct_pool = None
        t_route = l1.timestamp
        route_hour = t_route - (t_route % 3600)
        for venue_d, pid_d in cands:
            mm = replay.meta[(venue_d, pid_d)]
            st = replay.state_before(venue_d, pid_d, route_hour, route_order)
            if st is None:
                continue
            q = quote_one_hop(
                Pool(pid_d, mm.token0, mm.token1, st[0], st[1], mm.venue),
                a_in,
                amt_in,
            )
            if q and (best_direct is None or q > best_direct):
                best_direct = q
                best_direct_pool = (venue_d, pid_d)
        if best_direct is None:
            continue
        assert best_direct_pool is not None

        sym, typ = classify(mid1)
        hop1_source = str(route["realised_hop1_source"])
        hop2_source = str(route["realised_hop2_source"])
        direct_source, direct_pool = best_direct_pool
        realised_venue_set = {hop1_source, hop2_source}
        target_price = target_price_usd(prices, b_out)
        if target_price is None:
            continue
        direct_output_usd = float(best_direct) * target_price
        realised_output_common_mark_usd = float(out_amt) * target_price
        realised_component_output_usd = float(route["output_usd"])
        gross_direct_advantage_bps = common_mark_direct_advantage_bps(
            best_direct,
            out_amt,
            output_price_usd=target_price,
            input_notional_usd=usd,
        )
        if gross_direct_advantage_bps is None:
            continue
        direct_output_improvement_bps = cost_gap_bps(best_direct, out_amt)
        eth_price = prices.get(WETH)
        hop1_support = replay.state_support[(l1.venue, l1.pool, l1.hour)]
        hop2_support = replay.state_support[(l2.venue, l2.pool, l2.hour)]
        direct_support = replay.state_support[(direct_source, direct_pool, route_hour)]
        rows.append({
            "date": pd.to_datetime(day, format="%Y%m%d"),
            "route_id": route["route_id"], "tx": tx,
            "component_id": int(route["component_id"]),
            "receipt_allocation_scope": "single_reconstructed_component_transaction",
            "block": route_order[0], "first_log_index": route_order[1],
            "token_in": a_in, "token_out": b_out, "mid": mid1,
            "mid_symbol": sym, "mid_type": typ, "usd": usd,
            "realised_out": float(out_amt), "direct_quote": float(best_direct),
            "realised_component_output_usd": realised_component_output_usd,
            "realised_output_common_mark_usd": realised_output_common_mark_usd,
            "direct_output_usd": direct_output_usd,
            "component_output_to_input_value_ratio": realised_component_output_usd / usd,
            "common_to_component_output_mark_ratio": (
                realised_output_common_mark_usd / realised_component_output_usd
                if realised_component_output_usd > 0
                else None
            ),
            "timestamp_utc": t_route,
            "eth_usd_daily_sensitivity": eth_price[1] if eth_price else None,
            "hop1_pool": l1.pool, "hop2_pool": l2.pool,
            "hop1_source": hop1_source, "hop2_source": hop2_source,
            "direct_pool": direct_pool, "direct_source": direct_source,
            "hop1_prior_state_gap_hours": hop1_support[0],
            "hop2_prior_state_gap_hours": hop2_support[0],
            "direct_prior_state_gap_hours": direct_support[0],
            "hop1_liquidity_events_replayed": hop1_support[1],
            "hop2_liquidity_events_replayed": hop2_support[1],
            "direct_liquidity_events_replayed": direct_support[1],
            "best_direct_outside_realised_venue_set": (
                direct_source not in realised_venue_set
            ),
            "gross_direct_advantage_bps": gross_direct_advantage_bps,
            "direct_output_improvement_bps": direct_output_improvement_bps,
        })
    return (pd.DataFrame(rows) if rows else None), allocation_support


def _one_day_payload(payload):
    return one_day(*payload)


def add_topology_gas_adjustment(
    frame: pd.DataFrame,
    gas_panel=TRANSACTION_GAS_PANEL,
    route_gas_panel=ROUTE_GAS_PANEL,
    intraday_price_panel=EXTERNAL_WETH_USD_INTRADAY_PANEL,
) -> pd.DataFrame:
    """Join exact receipt gas and expose daily-denominator bps as sensitivity only."""
    out = frame.copy()
    out = out.drop(
        columns=[
            "effective_gas_price_wei",
            "gas_used",
            "execution_gas_cost_wei",
            "blob_gas_used",
            "blob_gas_price_wei",
            "blob_gas_cost_wei",
            "receipt_total_gas_cost_wei",
            "receipt_gas_cost_scope",
            "off_receipt_payment_status",
            "block_timestamp_utc",
            "provider_route_timestamp_utc",
            "provider_block_timestamp_disagreement_seconds",
            "receipt_block_hash",
            "receipt_status",
            "gas_gwei",
            "gas_price_supported",
            "gas_price_support_reason",
            "base_fee_per_gas_wei",
            "base_fee_gwei",
            "base_fee_supported",
            "base_fee_support_reason",
            "eth_usd",
            "eth_usd_mark_available_at_utc",
            "eth_usd_mark_lag_seconds",
            "eth_usd_price_source",
            "eth_usd_validation_status",
            "execution_gas_cost_usd",
            "blob_gas_cost_usd",
            "receipt_total_gas_cost_usd",
        ],
        errors="ignore",
    )
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["year"] = out["date"].dt.year
    out["tx"] = out["tx"].astype(str).str.lower()
    out["block"] = pd.to_numeric(out["block"], errors="raise").astype("int64")
    out["provider_route_timestamp_utc"] = pd.to_numeric(
        out["timestamp_utc"], errors="raise"
    ).astype("int64")
    gas = load_route_transaction_gas(
        gas_panel, required_routes=out
    )[
        [
            "tx_hash",
            "block_number",
            "block_hash",
            "block_timestamp_utc",
            "status",
            "gas_used",
            "execution_gas_cost_wei",
            "blob_gas_used",
            "blob_gas_price_wei",
            "blob_gas_cost_wei",
            "receipt_total_gas_cost_wei",
            "receipt_gas_cost_scope",
            "off_receipt_payment_status",
            "effective_gas_price_wei",
            "gas_gwei",
            "gas_price_supported",
            "gas_price_support_reason",
            "base_fee_per_gas_wei",
            "base_fee_gwei",
            "base_fee_supported",
            "base_fee_support_reason",
        ]
    ].rename(
        columns={
            "tx_hash": "tx",
            "block_number": "block",
            "block_hash": "receipt_block_hash",
            "status": "receipt_status",
        }
    )
    out = out.merge(gas, on=["tx", "block"], how="left", validate="one_to_one")
    if out["gas_price_supported"].isna().any():
        raise RuntimeError("exact transaction gas join changed the route perimeter")
    out["provider_block_timestamp_disagreement_seconds"] = (
        out["provider_route_timestamp_utc"] - out["block_timestamp_utc"]
    )
    out["timestamp_utc"] = out["block_timestamp_utc"]
    marks = load_intraday_weth_usd_marks(intraday_price_panel, out)
    out = attach_strictly_prior_weth_usd(out, marks)

    def receipt_cost_usd(column: str) -> list[float | None]:
        values: list[float | None] = []
        for raw_cost, eth_usd in zip(out[column], out["eth_usd"], strict=True):
            if pd.isna(raw_cost) or pd.isna(eth_usd):
                values.append(None)
                continue
            values.append(
                float(
                    Decimal(str(raw_cost))
                    * Decimal(str(eth_usd))
                    / Decimal(10**18)
                )
            )
        return values

    out["execution_gas_cost_usd"] = receipt_cost_usd("execution_gas_cost_wei")
    out["blob_gas_cost_usd"] = receipt_cost_usd("blob_gas_cost_wei")
    out["receipt_total_gas_cost_usd"] = receipt_cost_usd(
        "receipt_total_gas_cost_wei"
    )
    receipt_panel = (
        route_gas_panel.copy()
        if isinstance(route_gas_panel, pd.DataFrame)
        else pd.read_parquet(route_gas_panel)
    )
    direct_requests = pd.DataFrame(
        {
            "year": out["year"],
            "legs": 1,
            "venue_sequence": out["direct_source"],
            "gas_vehicle": "direct",
            "mid_type": "direct",
        },
        index=out.index,
    )
    vehicle_requests = pd.DataFrame(
        {
            "year": out["year"],
            "legs": 2,
            "venue_sequence": out["hop1_source"] + ">" + out["hop2_source"],
            "gas_vehicle": out["mid"],
            "mid_type": out["mid_type"],
        },
        index=out.index,
    )
    for prefix, estimates in (
        ("direct", estimate_route_gas(direct_requests, receipt_panel)),
        ("vehicle", estimate_route_gas(vehicle_requests, receipt_panel)),
    ):
        out[[f"{prefix}_{column}" for column in GAS_ESTIMATE_COLUMNS]] = (
            estimates[GAS_ESTIMATE_COLUMNS]
        )

    def apply_units(
        direct_column: str,
        vehicle_column: str,
        price_column: str,
    ) -> list[float | None]:
        return [
            all_in_direct_advantage_bps_from_units(
                gross,
                direct_gas_units=direct_units,
                vehicle_gas_units=vehicle_units,
                notional_usd=notional,
                gas_price_gwei=gas_gwei,
                eth_usd=eth_usd,
            )
            if all(
                pd.notna(value)
                for value in (
                    direct_units,
                    vehicle_units,
                    gas_gwei,
                    eth_usd,
                )
            )
            else None
            for gross, direct_units, vehicle_units, notional, gas_gwei, eth_usd in zip(
                out["gross_direct_advantage_bps"],
                out[direct_column],
                out[vehicle_column],
                out["usd"],
                out[price_column],
                out["eth_usd"],
                strict=True,
            )
        ]

    prefix = "daily_denominator_sensitivity_"
    out[f"{prefix}all_in_direct_advantage_bps"] = apply_units(
        "direct_gas_units_median", "vehicle_gas_units_median", "gas_gwei"
    )
    out[f"{prefix}all_in_direct_advantage_bps_iqr_lower"] = apply_units(
        "direct_gas_units_p75", "vehicle_gas_units_p25", "gas_gwei"
    )
    out[f"{prefix}all_in_direct_advantage_bps_iqr_upper"] = apply_units(
        "direct_gas_units_p25", "vehicle_gas_units_p75", "gas_gwei"
    )
    out[f"{prefix}same_block_base_fee_direct_advantage_bps"] = apply_units(
        "direct_gas_units_median", "vehicle_gas_units_median", "base_fee_gwei"
    )
    out[f"{prefix}same_block_base_fee_direct_advantage_bps_iqr_lower"] = apply_units(
        "direct_gas_units_p75", "vehicle_gas_units_p25", "base_fee_gwei"
    )
    out[f"{prefix}same_block_base_fee_direct_advantage_bps_iqr_upper"] = apply_units(
        "direct_gas_units_p25", "vehicle_gas_units_p75", "base_fee_gwei"
    )
    out["canonical_all_in_bps_release_status"] = (
        "withheld_missing_transaction_time_endpoint_usd"
    )
    out["daily_denominator_sensitivity_status"] = (
        "noncanonical_address_day_output_mark_with_provider_route_notional"
    )
    return out


def classify_state_support(frame: pd.DataFrame) -> pd.Series:
    """Label whether three pre-trade states are adjacent, bridged, or replayed."""
    gap_columns = [
        "hop1_prior_state_gap_hours",
        "hop2_prior_state_gap_hours",
        "direct_prior_state_gap_hours",
    ]
    liquidity_columns = [
        "hop1_liquidity_events_replayed",
        "hop2_liquidity_events_replayed",
        "direct_liquidity_events_replayed",
    ]
    missing = sorted(set(gap_columns + liquidity_columns) - set(frame.columns))
    if missing:
        raise ValueError("state-support classification is missing " + ", ".join(missing))
    liquidity_replayed = frame[liquidity_columns].gt(0).any(axis=1)
    adjacent = frame[gap_columns].eq(1).all(axis=1) & ~liquidity_replayed
    labels = pd.Series("bridged_no_liquidity", index=frame.index, dtype="object")
    labels.loc[adjacent] = "adjacent_no_liquidity"
    labels.loc[liquidity_replayed] = "liquidity_replayed"
    return labels


def add_valuation_support(frame: pd.DataFrame) -> pd.DataFrame:
    """Require coherent route flows and a coherent common output-token mark."""
    out = frame.copy()
    route_ratio = out["component_output_to_input_value_ratio"]
    mark_ratio = out["common_to_component_output_mark_ratio"]
    for suffix, lower, upper in (("2x", 0.5, 2.0), ("20pct", 0.8, 1.2)):
        out[f"route_value_coherent_{suffix}"] = route_ratio.between(lower, upper)
        out[f"common_mark_coherent_{suffix}"] = mark_ratio.between(lower, upper)
        out[f"valuation_coherent_{suffix}"] = (
            out[f"route_value_coherent_{suffix}"]
            & out[f"common_mark_coherent_{suffix}"]
        )
    return out


def state_support_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Annual and pooled dominance diagnostics by reserve-state support class."""
    data = frame.copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    rows: list[dict[str, object]] = []

    def append(scope: str, year: int | None, support: str, group: pd.DataFrame) -> None:
        coherent = group[group["valuation_coherent_20pct"]]
        gas = group[
            group["daily_denominator_sensitivity_all_in_direct_advantage_bps"].notna()
        ]
        dominated = group[group["dominated_gross"]]
        rows.append(
            {
                "scope": scope,
                "year": year,
                "state_support": support,
                "routes": len(group),
                "pct_dominated_gross": 100 * float(group["dominated_gross"].mean()),
                "valuation_coherent_20pct_routes": len(coherent),
                "pct_dominated_valuation_coherent_20pct": (
                    100 * float(coherent["dominated_gross"].mean())
                    if len(coherent)
                    else None
                ),
                "daily_denominator_sensitivity_gas_supported_routes": len(gas),
                "daily_denominator_sensitivity_pct_dominated_topology_gas_adjusted": (
                    100
                    * float(
                        gas[
                            "daily_denominator_sensitivity_all_in_direct_advantage_bps"
                        ]
                        .gt(0)
                        .mean()
                    )
                    if len(gas)
                    else None
                ),
                "daily_denominator_sensitivity_pct_dominated_gas_iqr_lower": (
                    100
                    * float(
                        group[
                            "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower"
                        ]
                        .dropna()
                        .gt(0)
                        .mean()
                    )
                    if group[
                        "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower"
                    ]
                    .notna()
                    .any()
                    else None
                ),
                "daily_denominator_sensitivity_pct_dominated_gas_iqr_upper": (
                    100
                    * float(
                        group[
                            "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper"
                        ]
                        .dropna()
                        .gt(0)
                        .mean()
                    )
                    if group[
                        "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper"
                    ]
                    .notna()
                    .any()
                    else None
                ),
                "dominated_routes": len(dominated),
                "pct_dominated_outside_realised_venue_set": (
                    100
                    * float(
                        dominated["best_direct_outside_realised_venue_set"].mean()
                    )
                    if len(dominated)
                    else None
                ),
                "median_price_free_output_improvement_bps": float(
                    group["direct_output_improvement_bps"].median()
                ),
            }
        )

    for support, group in data.groupby("state_support", sort=True):
        append("pooled", None, str(support), group)
    for (year, support), group in data.groupby(["year", "state_support"], sort=True):
        append("annual", int(year), str(support), group)
    return pd.DataFrame(rows)


def dominance_level_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Pooled incidence, weighting sensitivity, uncertainty, and dollar magnitude."""
    definitions = {
        "gross_output": ("gross_direct_advantage_bps", "dominated_gross"),
        "daily_denominator_sensitivity_matched_gas_p25_bound": (
            "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower",
            None,
        ),
        "daily_denominator_sensitivity_matched_gas_median": (
            "daily_denominator_sensitivity_all_in_direct_advantage_bps",
            None,
        ),
        "daily_denominator_sensitivity_matched_gas_p75_bound": (
            "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper",
            None,
        ),
    }
    support_masks = {
        "all_routes": pd.Series(True, index=frame.index),
        "within_2x": frame["valuation_coherent_2x"].fillna(False),
        "within_20pct": frame["valuation_coherent_20pct"].fillna(False),
    }
    rows: list[dict[str, object]] = []
    for support, support_mask in support_masks.items():
        for economic_object, (advantage_column, indicator_column) in definitions.items():
            sample = frame.loc[support_mask & frame[advantage_column].notna()].copy()
            if sample.empty:
                continue
            dominated = (
                sample[indicator_column].astype(bool)
                if indicator_column is not None
                else sample[advantage_column].gt(0)
            )
            inference = mean_clustered(
                dominated.astype(float), pd.to_datetime(sample["date"])
            )
            savings = (
                sample[advantage_column].where(dominated, 0.0).clip(lower=0)
                * sample["usd"]
                / 10_000
            )
            dominated_savings = savings.loc[dominated]
            top_one_percent_count = max(1, (len(dominated_savings) + 99) // 100)
            aggregate_savings = float(savings.sum())
            rows.append(
                {
                    "scope": "pooled_level",
                    "weighting": "route",
                    "value_support": support,
                    "economic_object": economic_object,
                    "routes": len(sample),
                    "dates": pd.to_datetime(sample["date"]).nunique(),
                    "dominated_routes": int(dominated.sum()),
                    "pct_dominated": 100 * inference.estimate,
                    "date_clustered_standard_error_pp": 100 * inference.standard_error,
                    "confidence_interval_95_lower_pct": 100
                    * max(inference.confidence_interval_lower, 0.0),
                    "confidence_interval_95_upper_pct": 100
                    * min(inference.confidence_interval_upper, 1.0),
                    "median_advantage_bps_if_dominated": float(
                        sample.loc[dominated, advantage_column].median()
                    ),
                    "median_savings_usd_if_dominated": float(
                        dominated_savings.median()
                    ),
                    "aggregate_savings_usd_sampled_dates": aggregate_savings,
                    "top_1pct_savings_share_pct": (
                        100
                        * float(dominated_savings.nlargest(top_one_percent_count).sum())
                        / aggregate_savings
                        if aggregate_savings
                        else None
                    ),
                    "pct_dominated_routes_below_1000_usd_notional": (
                        100 * float(sample.loc[dominated, "usd"].lt(1_000).mean())
                        if dominated.any()
                        else None
                    ),
                }
            )
            daily_incidence = (
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(sample["date"]),
                        "dominated": dominated.to_numpy(dtype=float),
                    }
                )
                .groupby("date", sort=True)["dominated"]
                .mean()
            )
            rows.append(
                {
                    "scope": "pooled_level",
                    "weighting": "equal_date",
                    "value_support": support,
                    "economic_object": economic_object,
                    "routes": len(sample),
                    "dates": len(daily_incidence),
                    "dominated_routes": int(dominated.sum()),
                    "pct_dominated": 100 * float(daily_incidence.mean()),
                    "daily_incidence_p25_pct": 100 * float(daily_incidence.quantile(0.25)),
                    "daily_incidence_p50_pct": 100 * float(daily_incidence.quantile(0.50)),
                    "daily_incidence_p75_pct": 100 * float(daily_incidence.quantile(0.75)),
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--stage",
        choices=("gross", "final"),
        default="gross",
        help="build the gross route panel or attach exact transaction gas and exhibits",
    )
    ap.add_argument("--days", nargs="+", help="explicit YYYYMMDD days")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--panel-only", action="store_true")
    args = ap.parse_args()
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be positive")
    if args.stage == "final":
        if args.days is not None or args.limit is not None:
            ap.error("--days and --limit apply only to the gross diagnostic stage")
        df = build_final_panel()
        if args.panel_only:
            print(f"wrote analysis-ready panel {OUT_PARQUET.relative_to(REPO_ROOT)}")
            return 0
        df, support = build_final_exhibits()
    else:
        require_node_d_release(routes=True, market_state=True)
        state_releases = {
            venue: released_state_partitions("constant_product", venue, CP_COLUMNS)
            for venue in VENUES
        }
        route_release = released_route_partitions(
            [*LINEAR_ROUTE_COLUMNS, "n_components"]
        )
        available = list(state_releases["uniswap_v2"].days)
        days = counterfactual_days(available, explicit=args.days, limit=args.limit)
        print(f"quoting counterfactuals on {len(days)} day(s)", flush=True)

        parts = []
        allocation_support_rows = []
        comparable = 0
        payloads = []
        for day in days:
            previous_day = (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
            selected_state = {
                venue: release.select_days(selected_days)
                for venue, release in state_releases.items()
                if (selected_days := tuple(selected for selected in (previous_day, day) if selected in release.days))
            }
            payloads.append((day, route_release.select_days((day,)), selected_state))
        with interruptible_process_pool(bounded_workers(args.workers, maximum=8)) as pool:
            results = pool.map(_one_day_payload, payloads, chunksize=1)
            for index, (day, result) in enumerate(zip(days, results, strict=True), 1):
                result, allocation_support = result
                if allocation_support is not None:
                    allocation_support_rows.append(allocation_support)
                if result is not None and len(result):
                    parts.append(result)
                    comparable += len(result)
                if index % 25 == 0 or index == len(days):
                    print(
                        f"  [{index:,}/{len(days):,}] through {day}: "
                        f"{comparable:,} comparable two-leg routes",
                        flush=True,
                    )
        if args.days is None and args.limit is None:
            if not allocation_support_rows:
                raise RuntimeError("receipt-allocation support perimeter is empty")
            allocation_support = receipt_allocation_support_summary(pd.DataFrame(allocation_support_rows))
        if not parts:
            print("no comparable routes")
            return 1

        df = pd.concat(parts, ignore_index=True)
        df = df[df.direct_output_improvement_bps.notna()]
        df["dominated_gross"] = df["direct_output_improvement_bps"].gt(0)
        df = add_valuation_support(df)
        df["dominated_valuation_coherent_2x"] = df["dominated_gross"].where(
            df["valuation_coherent_2x"]
        )
        df["dominated_valuation_coherent_20pct"] = df["dominated_gross"].where(
            df["valuation_coherent_20pct"]
        )
        df["state_support"] = classify_state_support(df)
        if args.days is not None or args.limit is not None:
            print(
                f"bounded counterfactual diagnostic complete on {len(days):,} day(s); "
                "canonical outputs unchanged"
            )
            return 0
        build_gross_publication(
            df,
            allocation_support,
            route_release,
            state_releases,
        )
        print(f"wrote gross route panel {GROSS_PARQUET.relative_to(REPO_ROOT)}")
        return 0

    print(f"\ncomparable intermediated routes with a direct alternative: {len(df):,}")
    print(f"date range: {df.date.min().date()} to {df.date.max().date()}")
    dom = df[df.direct_output_improvement_bps > 0]
    print(f"\nroutes where DIRECT would have returned more (gross of gas): "
          f"{len(dom):,} ({100*len(dom)/len(df):.1f}%)")
    print(f"  median advantage among those: "
          f"{dom.gross_direct_advantage_bps.median():.1f} bps of notional")
    print(f"  median advantage over all routes: "
          f"{df.gross_direct_advantage_bps.median():.1f} bps of notional")
    print(
        "  median price-free output improvement over all routes: "
        f"{df.direct_output_improvement_bps.median():.1f} bps of realised output"
    )
    for label, column in (
        ("within 2x", "valuation_coherent_2x"),
        ("within 20%", "valuation_coherent_20pct"),
    ):
        supported = df[df[column]]
        print(
            f"  valuation-coherence sensitivity ({label}): {len(supported):,} routes, "
            f"{100 * supported.dominated_gross.mean():.1f}% dominated"
        )
    outside = dom[dom["best_direct_outside_realised_venue_set"]]
    outside_share = 100 * len(outside) / len(dom) if len(dom) else float("nan")
    print(
        "  dominated via a best direct pool outside the realised venue set: "
        f"{len(outside):,} ({outside_share:.1f}% of dominated routes)"
    )
    sensitivity_column = "daily_denominator_sensitivity_all_in_direct_advantage_bps"
    gas_supported = df[df[sensitivity_column].notna()]
    if len(gas_supported):
        all_in_dominated = gas_supported[sensitivity_column].gt(0)
        lower = gas_supported[
            "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_lower"
        ].gt(0)
        upper = gas_supported[
            "daily_denominator_sensitivity_all_in_direct_advantage_bps_iqr_upper"
        ].gt(0)
        print(
            "  noncanonical daily-denominator sensitivity, receipt-calibrated gas: "
            f"{100*all_in_dominated.mean():.1f}% "
            f"(IQR sensitivity {100*lower.mean():.1f}% to {100*upper.mean():.1f}%; "
            f"{len(gas_supported):,} routes)"
        )
        for prefix in ("direct", "vehicle"):
            support = gas_supported[f"{prefix}_gas_support_level"].value_counts()
            print(
                f"    {prefix} gas support: "
                + ", ".join(f"{level}={count:,}" for level, count in support.items())
            )
    print("\nby intermediary type:")
    for t, s in df.groupby("mid_type"):
        d = s[s.direct_output_improvement_bps > 0]
        print(f"  {t:<14} routes {len(s):7,}  dominated {100*len(d)/len(s):5.1f}%"
              f"  median advantage "
              f"{d.gross_direct_advantage_bps.median() if len(d) else float('nan'):8.1f} bps")
    print("\nby size bin:")
    df["bin"] = pd.cut(
        df.usd,
        [100, 1e3, 1e4, 1e5, 1e12],
        labels=["100-1k", "1k-10k", "10k-100k", ">100k"],
        include_lowest=True,
    )
    for b, s in df.groupby("bin", observed=True):
        d = s[s.direct_output_improvement_bps > 0]
        print(f"  {b:>9}  routes {len(s):7,}  dominated {100*len(d)/len(s):5.1f}%"
              f"  median advantage "
              f"{d.gross_direct_advantage_bps.median() if len(d) else float('nan'):8.1f} bps")
    print("\nby reserve-state support:")
    print(
        support.loc[
            support["scope"].eq("pooled"),
            [
                "state_support",
                "routes",
                "pct_dominated_gross",
                "pct_dominated_valuation_coherent_20pct",
                "daily_denominator_sensitivity_pct_dominated_topology_gas_adjusted",
                "daily_denominator_sensitivity_pct_dominated_gas_iqr_lower",
                "daily_denominator_sensitivity_pct_dominated_gas_iqr_upper",
            ],
        ].round(2).to_string(index=False)
    )
    print(
        f"\nwrote {OUT_PARQUET.relative_to(REPO_ROOT)}, "
        f"{OUT_EXHIBIT.relative_to(REPO_ROOT)}, and "
        f"{OUT_SUPPORT.relative_to(REPO_ROOT)}"
    )
    print("\nBIAS DIRECTIONS: v2-family venue coverage understates the best direct "
          "alternative, and omitting gas favours the two-hop vehicle route. Both "
          "make gross direct-dominance incidence a LOWER bound. Receipt gas includes "
          "router overhead beyond AMM execution, so the labelled fallback hierarchy "
          "and IQR sensitivity remain part of the estimand.")
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="counterfactual-dominance panel"):
        raise SystemExit(main())

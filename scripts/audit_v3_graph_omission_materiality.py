#!/usr/bin/env python3
"""Quantify whether factory pools omitted by the V3 Graph can affect paper claims."""

from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import asdict
import json
from pathlib import Path

import duckdb
import pandas as pd

from ddvc import asset_types as asset_types_module
from ddvc import data_release as data_release_module
from ddvc import ethereum_logs as ethereum_logs_module
from ddvc.fetch import pool_daily as pool_daily_module
from ddvc import prices as prices_module
from ddvc import realised as realised_module
from ddvc import raw_certification as raw_certification_module
from ddvc import release_calendar as release_calendar_module
from ddvc import token_decimals as token_decimals_module
from ddvc import transaction_targets as transaction_targets_module
from ddvc import v3_event_completeness as event_completeness_module
from ddvc import v3_graph_materiality as graph_materiality_module
from ddvc import v3_inventory as v3_inventory_module
from ddvc import v3_inventory_assembly as v3_inventory_assembly_module
from ddvc import v3_inventory_calendar as v3_inventory_calendar_module
from ddvc import v3_pool_registry as v3_pool_registry_module
from ddvc.asset_types import STABLE, VEHICLE_CANDIDATES
from ddvc.artifact_release import file_stat_identity
from ddvc.ethereum_logs import file_sha256
from ddvc.fetch import raw as fetch_raw_module
from ddvc.fetch.raw import write_json
from ddvc.raw_certification import load_certified_partition_ledger
from ddvc.data_release import released_route_partitions, require_v2_event_source_release
from ddvc.fetch.pool_daily import POOL_IDENTITY_STATIC_SNAPSHOTS
from ddvc.fetch.sources import get_source
from ddvc.paths import TOKEN_PRICE_DAILY_PANEL, V2_AUDITED_TOKEN_DECIMALS_REGISTRY
from ddvc.provenance import require_current_artifacts
from ddvc.quoter import canonical_json_sha256
from ddvc.realised import LINEAR_ROUTE_COLUMNS
from ddvc.release_calendar import select_transaction_frontier_audit_days
from ddvc.token_decimals import token_decimals_registry_sha256, validate_token_decimals_registry
from ddvc.v3_graph_materiality import (
    graph_daily_provider_bound,
    graph_event_coverage_materiality,
    event_coverage_clears_state_estimands,
    omitted_static_state_pool_perimeter,
    graph_pool_snapshot,
    omitted_swap_economic_weight,
    register_installed_inventory_events,
    route_opportunity_exposure,
    route_estimand_perturbation_bounds,
    share,
)
from ddvc.v3_inventory import EVENT_TOPICS
from ddvc.v3_inventory_assembly import load_certified_inventory_generation
from ddvc.v3_inventory_calendar import CALENDAR, load_day_calendar
from ddvc.v3_pool_registry import V3_POOL_REGISTRY, V3_POOL_REGISTRY_CERTIFICATE, load_certified_frozen_upper, load_registry


CODE_SOURCES = {
    "scripts/audit_v3_graph_omission_materiality.py": Path(__file__),
    "src/ddvc/asset_types.py": Path(asset_types_module.__file__),
    "src/ddvc/data_release.py": Path(data_release_module.__file__),
    "src/ddvc/ethereum_logs.py": Path(ethereum_logs_module.__file__),
    "src/ddvc/fetch/raw.py": Path(fetch_raw_module.__file__),
    "src/ddvc/fetch/pool_daily.py": Path(pool_daily_module.__file__),
    "src/ddvc/prices.py": Path(prices_module.__file__),
    "src/ddvc/realised.py": Path(realised_module.__file__),
    "src/ddvc/raw_certification.py": Path(raw_certification_module.__file__),
    "src/ddvc/release_calendar.py": Path(release_calendar_module.__file__),
    "src/ddvc/token_decimals.py": Path(token_decimals_module.__file__),
    "src/ddvc/transaction_targets.py": Path(transaction_targets_module.__file__),
    "src/ddvc/v3_event_completeness.py": Path(event_completeness_module.__file__),
    "src/ddvc/v3_graph_materiality.py": Path(graph_materiality_module.__file__),
    "src/ddvc/v3_inventory.py": Path(v3_inventory_module.__file__),
    "src/ddvc/v3_inventory_assembly.py": Path(v3_inventory_assembly_module.__file__),
    "src/ddvc/v3_inventory_calendar.py": Path(v3_inventory_calendar_module.__file__),
    "src/ddvc/v3_pool_registry.py": Path(v3_pool_registry_module.__file__),
}
MAX_MATERIAL_SHARE_CHANGE = 0.01
MAX_MATERIAL_ROUTE_COST_BPS = 1.0


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--data-root", type=Path, default=Path("data"))
    cli.add_argument("--output", type=Path)
    cli.add_argument("--threads", type=int, default=8)
    cli.add_argument("--raw-certificate", type=Path)
    args = cli.parse_args()
    root = args.data_root
    factory_root = root / "raw" / "ethereum" / "uniswap_v3_pool_registry"
    inventory_root = root / "raw" / "ethereum" / "uniswap_v3_inventory_events"
    registry_path = factory_root / V3_POOL_REGISTRY.name
    registry_certificate_path = factory_root / V3_POOL_REGISTRY_CERTIFICATE.name
    graph_static_path = root / "raw" / "thegraph" / "uniswap_v3" / POOL_IDENTITY_STATIC_SNAPSHOTS["uniswap_v3"]
    graph_static_metadata_path = graph_static_path.with_name(
        graph_static_path.name.removesuffix(".jsonl.gz") + ".meta.json"
    )
    calendar_path = root / "processed" / "v3_inventory_day_calendar.parquet"
    decimals_path = root / "processed" / V2_AUDITED_TOKEN_DECIMALS_REGISTRY.name
    prices_path = root / "processed" / TOKEN_PRICE_DAILY_PANEL.name
    raw_certificate = args.raw_certificate or (
        root
        / "processed"
        / "raw_generation"
        / "uniswap_v3_local_certificate.json"
    )

    frozen_upper, factory_certificate = load_certified_frozen_upper(root=factory_root)
    exact_paths, exact_manifest, exact_generation_binding = load_certified_inventory_generation(
        inventory_root,
        frozen_upper=frozen_upper,
        factory_certificate=factory_certificate,
    )
    registry_all = pd.DataFrame(
        [asdict(pool) for pool in load_registry(registry_path, registry_certificate_path, analysis_only=False)]
    )
    registry_all = registry_all.assign(
        pool=registry_all["pool"].str.lower(),
        token0=registry_all["token0"].str.lower(),
        token1=registry_all["token1"].str.lower(),
    )
    if calendar_path.resolve() != CALENDAR.resolve():
        raise ValueError("V3 omission materiality requires the canonical inventory calendar")
    calendar_days, calendar_end_blocks = load_day_calendar()
    if len(calendar_days) != len(set(calendar_days)):
        raise RuntimeError("canonical V3 inventory calendar contains duplicate days")
    calendar = pd.DataFrame(
        {"day": calendar_days, "day_end_block": calendar_end_blocks}
    )
    calendar["start_block"] = (
        calendar["day_end_block"]
        .shift(fill_value=int(registry_all["creation_block"].min()) - 1)
        .astype("int64")
        + 1
    )
    sample_lower = int(calendar["start_block"].min())
    sample_upper = int(calendar["day_end_block"].max())
    if sample_upper > int(frozen_upper["block_number"]):
        raise RuntimeError("canonical V3 inventory calendar exceeds the certified frozen upper block")
    registry = registry_all[registry_all["creation_block"].le(sample_upper)].copy()
    graph_pools, graph_static_binding = graph_pool_snapshot(
        graph_static_path,
        graph_static_metadata_path,
        certified_upper_block=int(frozen_upper["block_number"]),
    )
    graph_static_binding["path"] = str(graph_static_path.relative_to(root))
    graph_static_binding["metadata_path"] = str(
        graph_static_metadata_path.relative_to(root)
    )
    vehicle_tokens, stable_tokens = set(VEHICLE_CANDIDATES), set(STABLE)
    registry["graph_present"] = registry["pool"].isin(graph_pools)
    registry["vehicle_pair"] = registry["token0"].isin(vehicle_tokens) | registry["token1"].isin(vehicle_tokens)
    registry["stable_pair"] = registry["token0"].isin(stable_tokens) | registry["token1"].isin(stable_tokens)
    require_v2_event_source_release()
    require_current_artifacts([decimals_path], consumer="V3 omission materiality token decimals")
    decimals_state = file_stat_identity(decimals_path)
    decimals_file_sha256 = file_sha256(decimals_path)
    token_decimals, token_decimals_registry = validate_token_decimals_registry(decimals_path)
    if decimals_state != file_stat_identity(decimals_path) or file_sha256(decimals_path) != decimals_file_sha256:
        raise RuntimeError("audited token-decimals registry mutated during validation")
    exact_tokens = set(token_decimals)
    registry["exact_metadata"] = registry["token0"].isin(exact_tokens) & registry["token1"].isin(exact_tokens)
    con = duckdb.connect()
    con.execute(f"SET threads={max(1, args.threads)}")
    con.execute("SET preserve_insertion_order=false")
    con.register("registry", registry)
    con.register("calendar", calendar)
    topic_rows = pd.DataFrame([{"topic": topic, "kind": kind} for kind, topic in EVENT_TOPICS.items()])
    con.register("topics", topic_rows)
    register_installed_inventory_events(con, exact_paths, exact_generation_binding)
    con.execute(
        f"""
        CREATE TEMP TABLE exact_events AS
        SELECT *, lower(address) AS pool, topics[1] AS topic
        FROM installed_inventory_events
        WHERE block_number BETWEEN {sample_lower} AND {sample_upper}
        """
    )
    _verified_paths, _verified_manifest, verified_generation_binding = load_certified_inventory_generation(
        inventory_root,
        frozen_upper=frozen_upper,
        factory_certificate=factory_certificate,
    )
    if (
        tuple(_verified_paths) != tuple(exact_paths)
        or _verified_manifest != exact_manifest
        or verified_generation_binding != exact_generation_binding
    ):
        raise RuntimeError("installed V3 inventory generation changed during materialization")
    try:
        raw_certificate_identity = str(
            raw_certificate.resolve().relative_to(root.resolve())
        )
    except ValueError as exc:
        raise ValueError("raw certificate must live below the selected data root") from exc
    certified_rows, raw_generation_binding = load_certified_partition_ledger(
        raw_certificate,
        data_root=root,
    )
    raw_generation_binding["certificate_path"] = raw_certificate_identity
    provider_paths: dict[str, dict[str, Path]] = {}
    for item in certified_rows:
        if item["source"] != "uniswap_v3":
            raise ValueError("V3 materiality certificate contains another source")
        stream = str(item["stream"])
        day = str(item["day"])
        provider_paths.setdefault(stream, {})[day] = root / str(item["path"])
    required_streams = {"swaps", "mints", "burns", "daily"}
    if set(provider_paths) != required_streams:
        raise ValueError(
            "V3 materiality certificate must contain exactly swaps, mints, burns, and daily"
        )
    print("AUDIT: exact missing-pool event counts", flush=True)
    summary = con.execute("SELECT t.kind, r.graph_present, r.vehicle_pair, r.stable_pair, r.exact_metadata, count(*) AS events, count(DISTINCT e.pool) AS pools FROM exact_events e JOIN registry r USING(pool) JOIN topics t USING(topic) GROUP BY ALL ORDER BY t.kind, r.graph_present, r.vehicle_pair, r.stable_pair, r.exact_metadata").df()
    by_kind: dict[str, dict[str, object]] = {}
    for kind, group in summary.groupby("kind"):
        total = int(group["events"].sum())
        omitted = int(group.loc[~group["graph_present"], "events"].sum())
        vehicle_total = int(group.loc[group["vehicle_pair"], "events"].sum())
        vehicle_omitted = int(group.loc[group["vehicle_pair"] & ~group["graph_present"], "events"].sum())
        stable_total = int(group.loc[group["stable_pair"], "events"].sum())
        stable_omitted = int(group.loc[group["stable_pair"] & ~group["graph_present"], "events"].sum())
        exact_metadata_total = int(group.loc[group["exact_metadata"], "events"].sum())
        exact_metadata_omitted = int(group.loc[group["exact_metadata"] & ~group["graph_present"], "events"].sum())
        by_kind[str(kind)] = {"events": total, "omitted_events": omitted, "omitted_share": share(omitted, total), "vehicle_pair_events": vehicle_total, "omitted_vehicle_pair_events": vehicle_omitted, "omitted_vehicle_pair_share": share(vehicle_omitted, vehicle_total), "stable_pair_events": stable_total, "omitted_stable_pair_events": stable_omitted, "omitted_stable_pair_share": share(stable_omitted, stable_total), "exact_metadata_events": exact_metadata_total, "exact_metadata_share": share(exact_metadata_total, total), "omitted_exact_metadata_events": exact_metadata_omitted, "omitted_exact_metadata_share": share(exact_metadata_omitted, omitted)}

    monthly = con.execute("SELECT substr(cast(c.day AS VARCHAR), 1, 6) AS month, r.graph_present, count(*) AS swaps FROM exact_events e JOIN topics t ON e.topic=t.topic AND t.kind='swap' JOIN registry r USING(pool) ASOF JOIN calendar c ON e.block_number>=c.start_block WHERE e.block_number<=c.day_end_block GROUP BY month, r.graph_present ORDER BY month, r.graph_present").df()
    monthly_pivot = monthly.pivot(index="month", columns="graph_present", values="swaps").fillna(0)
    monthly_pivot["omitted_share"] = monthly_pivot.get(False, 0) / monthly_pivot.sum(axis=1)
    peak_month = str(monthly_pivot["omitted_share"].idxmax()) if len(monthly_pivot) else None

    headline_days = {"20230601", "20230602", "20230603", "20230604"}
    headline_calendar = calendar[calendar["day"].astype(str).str.replace("-", "").isin(headline_days)]
    con.register("headline_calendar", headline_calendar)
    headline = con.execute("SELECT r.graph_present, r.vehicle_pair, r.stable_pair, count(*) AS swaps, count(DISTINCT e.pool) AS pools FROM exact_events e JOIN topics t ON e.topic=t.topic AND t.kind='swap' JOIN registry r USING(pool) ASOF JOIN headline_calendar c ON e.block_number>=c.start_block WHERE e.block_number<=c.day_end_block GROUP BY r.graph_present, r.vehicle_pair, r.stable_pair").df()

    pool_swaps = con.execute("SELECT e.pool, r.token0, r.token1, r.vehicle_pair, r.stable_pair, min(e.block_number) AS first_exact_swap_block, count(*) AS swaps FROM exact_events e JOIN topics t ON e.topic=t.topic AND t.kind='swap' JOIN registry r USING(pool) WHERE NOT r.graph_present GROUP BY ALL ORDER BY swaps DESC").df()
    omitted_swap_total = int(pool_swaps["swaps"].sum())
    top10 = int(pool_swaps.head(10)["swaps"].sum())
    hhi = float(((pool_swaps["swaps"] / omitted_swap_total) ** 2).sum()) if omitted_swap_total else None
    print("AUDIT: exact omitted-swap economic weight", flush=True)
    exact_economic_weight = omitted_swap_economic_weight(
        con,
        token_decimals=token_decimals,
        prices_path=prices_path,
    )
    route_release = released_route_partitions(LINEAR_ROUTE_COLUMNS, nonempty=True)
    v3_genesis = get_source("uniswap_v3").genesis.strftime("%Y%m%d")
    audit_days = [
        day
        for day in select_transaction_frontier_audit_days(list(route_release.days))
        if day >= v3_genesis
    ]
    if not audit_days:
        raise RuntimeError("released nonempty route calendar has no V3 audit dates")
    print("AUDIT: within-Graph event coverage and pre-provider exposure", flush=True)
    event_coverage = graph_event_coverage_materiality(
        con,
        provider_paths=provider_paths,
        registry=registry,
        calendar=calendar,
        audit_days=audit_days,
    )
    if event_coverage["top_exact_only_state_pools"]:
        dominant = event_coverage["top_exact_only_state_pools"][0]
        dominant_registry = registry.loc[
            registry["pool"].eq(dominant["pool"])
        ].iloc[0]
        print("AUDIT: dominant within-Graph pool route exposure", flush=True)
        route_exposure = route_opportunity_exposure(
            route_release,
            pool=str(dominant["pool"]),
            token0=str(dominant_registry["token0"]),
            token1=str(dominant_registry["token1"]),
            first_exposure_day=str(dominant["first_exposure_day"]),
            audit_days=audit_days,
        )
    else:
        route_exposure = {"status": "pass_no_exact_only_state_pool"}

    exact_lower, exact_upper = con.execute(
        "SELECT min(block_number), max(block_number) FROM exact_events"
    ).fetchone()
    daily_days = calendar.loc[
        calendar["start_block"].le(int(exact_upper))
        & calendar["day_end_block"].ge(int(exact_lower)),
        "day",
    ].astype(str).tolist()
    daily_result = graph_daily_provider_bound(
        con,
        certified_paths=provider_paths["daily"],
        days=daily_days,
        graph_pools=graph_pools,
    )
    calendar_ends = calendar["day_end_block"].astype("int64").tolist()
    calendar_labels = calendar["day"].astype(str).str.replace("-", "").tolist()
    pool_swaps["first_exact_swap_day"] = pool_swaps["first_exact_swap_block"].map(
        lambda block: calendar_labels[min(bisect_left(calendar_ends, int(block)), len(calendar_labels) - 1)]
    )
    within_graph_perimeter = pd.DataFrame(
        event_coverage["exact_only_state_pool_perimeter"],
        columns=["pool", "first_exposure_day"],
    )
    if not within_graph_perimeter.empty:
        within_graph_perimeter = within_graph_perimeter.merge(
            registry[["pool", "token0", "token1"]],
            on="pool",
            how="left",
            validate="one_to_one",
        )
    omitted_state_perimeter = omitted_static_state_pool_perimeter(
        con,
        registry=registry,
        calendar=calendar,
    )
    defective_pool_perimeter = pd.concat(
        [
            omitted_state_perimeter,
            within_graph_perimeter[["pool", "token0", "token1", "first_exposure_day"]],
        ],
        ignore_index=True,
    ).sort_values(["pool", "first_exposure_day"]).drop_duplicates("pool")
    estimand_bounds = route_estimand_perturbation_bounds(
        route_release,
        pool_perimeter=defective_pool_perimeter.to_dict("records"),
        audit_days=audit_days,
    )
    omitted_priced_mass = float(exact_economic_weight["priced_max_side_sensitivity_usd"])
    observed_provider_mass = float(daily_result["volume_usd"])
    economic_mass_denominator = observed_provider_mass + omitted_priced_mass
    economic_mass_bound = {
        "provider_observed_volume_usd": observed_provider_mass,
        "priced_omitted_max_side_sensitivity_usd": omitted_priced_mass,
        "combined_priced_mass_denominator_usd": economic_mass_denominator,
        "priced_omitted_mass_share": share(omitted_priced_mass, economic_mass_denominator),
        "priced_omitted_swap_support_share": exact_economic_weight["valued_swap_share"],
        "status": "sensitivity_only" if exact_economic_weight["unvalued_swaps"] else "fully_priced_bound",
    }
    claim_materiality = {
        "decision_thresholds": {
            "economic_mass_share": MAX_MATERIAL_SHARE_CHANGE,
            "vehicle_share_abs_change": MAX_MATERIAL_SHARE_CHANGE,
            "value_weighted_route_cost_bps": MAX_MATERIAL_ROUTE_COST_BPS,
            "capital_share": MAX_MATERIAL_SHARE_CHANGE,
        },
        "economic_mass": economic_mass_bound,
        "vehicle_share_and_route_cost": estimand_bounds,
        "capital": {
            "provider_missing_static_tvl_pool_day_share": daily_result["missing_static_tvl_pool_day_share"],
            "state_changing_event_defect_pools": event_coverage["state_changing_event_defect_pools"],
            "liquidity_event_defect_pools": event_coverage["liquidity_event_defect_pools"],
            "status": "requires_corrected_factory-perimeter_capital_state" if len(defective_pool_perimeter) else "provider_daily_bound_only",
        },
        "clears_paper_estimands": bool(
            economic_mass_bound["status"] == "fully_priced_bound"
            and economic_mass_bound["priced_omitted_mass_share"] is not None
            and float(economic_mass_bound["priced_omitted_mass_share"]) <= MAX_MATERIAL_SHARE_CHANGE
            and estimand_bounds["vehicle_count_share_abs_change_upper_bound"] is not None
            and float(estimand_bounds["vehicle_count_share_abs_change_upper_bound"]) <= MAX_MATERIAL_SHARE_CHANGE
            and estimand_bounds["vehicle_value_share_abs_change_upper_bound"] is not None
            and float(estimand_bounds["vehicle_value_share_abs_change_upper_bound"]) <= MAX_MATERIAL_SHARE_CHANGE
            and estimand_bounds["value_weighted_route_cost_bps_reduction_upper_bound"] is not None
            and float(estimand_bounds["value_weighted_route_cost_bps_reduction_upper_bound"]) <= MAX_MATERIAL_ROUTE_COST_BPS
            and event_coverage_clears_state_estimands(event_coverage)
            and not len(defective_pool_perimeter)
            and daily_result["missing_static_tvl_pool_day_share"] is not None
            and float(daily_result["missing_static_tvl_pool_day_share"]) <= MAX_MATERIAL_SHARE_CHANGE
        ),
    }
    recertified_rows, recertified_binding = load_certified_partition_ledger(
        raw_certificate,
        data_root=root,
    )
    recertified_binding["certificate_path"] = raw_certificate_identity
    if recertified_rows != certified_rows or recertified_binding != raw_generation_binding:
        raise RuntimeError("Graph provider generation changed during long-run materiality reads")
    route_release.assert_current()

    omitted_registry = registry[~registry["graph_present"]]
    result = {
        "audit_script_sha256": file_sha256(Path(__file__)),
        "code_sha256": {
            name: file_sha256(path)
            for name, path in sorted(CODE_SOURCES.items())
        },
        "exact_installed_generation_binding": exact_generation_binding,
        "exact_ordered_manifest_semantic_sha256": canonical_json_sha256(exact_manifest),
        "exact_ordered_raw_path_count": len(exact_paths),
        "token_decimals_registry_rows": len(token_decimals_registry),
        "token_decimals_registry_file_sha256": decimals_file_sha256,
        "token_decimals_registry_semantic_sha256": token_decimals_registry_sha256(token_decimals_registry),
        "released_route_content_identity_sha256": route_release.content_identity_sha256,
        "graph_raw_generation_binding": raw_generation_binding,
        "graph_static_snapshot_binding": graph_static_binding,
        "v3_research_calendar_days": [str(calendar["day"].iloc[0]), str(calendar["day"].iloc[-1])],
        "v3_research_block_perimeter": [sample_lower, sample_upper],
        "factory_pools": int(len(registry)),
        "graph_static_pools": int(registry["graph_present"].sum()),
        "omitted_factory_pools": int(len(omitted_registry)),
        "omitted_factory_pool_share": share(len(omitted_registry), len(registry)),
        "omitted_vehicle_pools": int(omitted_registry["vehicle_pair"].sum()),
        "omitted_stable_pools": int(omitted_registry["stable_pair"].sum()),
        "omitted_exact_metadata_pools": int(omitted_registry["exact_metadata"].sum()),
        "exact_events_by_kind": by_kind,
        "omitted_swap_peak_month": peak_month,
        "omitted_swap_peak_month_share": float(monthly_pivot.loc[peak_month, "omitted_share"]) if peak_month is not None else None,
        "omitted_swap_top10_share": share(top10, omitted_swap_total),
        "omitted_swap_pool_hhi": hhi,
        "legacy_20230601_20230604_exact_swaps": headline.to_dict("records"),
        "top_omitted_swap_pools": pool_swaps.head(20).to_dict("records"),
        "exact_omitted_swap_economic_weight": exact_economic_weight,
        "graph_event_coverage": event_coverage,
        "dominant_within_graph_pool_route_exposure": route_exposure,
        "graph_daily_provider_bound": daily_result,
        "paper_estimand_materiality": claim_materiality,
        "interpretation": "The four June 2023 dates are retained only as a legacy audit intersection, not current headline dates. Graph daily USD/TVL describes only provider-observed rows; exact omitted-pool USD volume and TVL require audited token metadata/prices and physical-inventory state. Missing-pool results do not certify within-Graph event completeness or pre-first-provider-swap state.",
    }
    if not claim_materiality["clears_paper_estimands"]:
        print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
        raise RuntimeError("V3 Graph omission materiality does not clear every paper estimand")
    if args.output is not None:
        write_json(args.output, result)
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Bound the economic exposure of unresolved exact V2 token-decimals anchors.

This audit never resolves or fetches token metadata.  It treats every route that
touches an unresolved token as deleted, then measures the largest possible
change to the released route graph and to the prespecified vehicle candidates.
The exact-event counts cover the already-installed anchor-selection chunks; they
are not represented as a full event-source release.

Writes  output/exhibits/v2_token_anchor_materiality.jsonl
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

from ddvc.asset_types import VEHICLE_CANDIDATES, asset_type
from ddvc.data_release import require_route_release
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.quoter import canonical_json_sha256
from ddvc.route_roles import (
    component_eligibility,
    component_value_support,
    role_token_values,
)
from ddvc.tables import write_exhibit
from ddvc.token_decimals import (
    MAX_TOKEN_DECIMALS,
    TokenDecimalsAnchor,
    token_decimals_anchor_sha256,
)
from ddvc.v2_event_contract import V2_EVENT_BY_TOPIC


UNRESOLVED = DATA_DIR / "raw" / "ethereum" / "token_decimals" / "v2_unresolved_tokens.json"
ANCHORS = DATA_DIR / "raw" / "ethereum" / "token_decimals" / "v2_selected_anchors.json"
VEHICLE_PANEL = DATA_DIR / "processed" / "vehicle_excess_use_daily.parquet"
ROUTE_PANEL = DATA_DIR / "processed" / "cross_venue_routing_daily.parquet"
ARCHITECTURE_ROUTES = DATA_DIR / "empirical" / "v4_settlement_route_units.parquet"
OUT = OUTPUT_DIR / "exhibits" / "v2_token_anchor_materiality.jsonl"
V2_VENUES = ("uniswap_v2", "sushiswap_v2")
ROTATION_MATERIAL_USD = 1e8
CODE_SOURCES = [
    "scripts/audit_v2_token_anchor_materiality.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/data_release.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/token_decimals.py",
    "src/ddvc/v2_event_contract.py",
]


def _quoted(values: list[str]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in values)


def validate_unresolved_perimeter() -> tuple[dict, dict, list[str]]:
    """Reopen the durable failure set and bind it to its selected anchors."""

    manifest = json.loads(ANCHORS.read_text(encoding="utf-8"))
    ledger = json.loads(UNRESOLVED.read_text(encoding="utf-8"))
    if (
        manifest.get("kind") != "v2_token_decimals_selected_anchors"
        or manifest.get("status") != "complete"
        or manifest.get("anchors_sha256") != ledger.get("anchors_sha256")
        or ledger.get("kind") != "unresolved_token_decimals"
        or ledger.get("status") != "complete"
        or ledger.get("selected_anchor_manifest", {}).get("sha256")
        != hashlib.sha256(ANCHORS.read_bytes()).hexdigest()
        or ledger.get("unresolved_sha256") != canonical_json_sha256(ledger.get("unresolved"))
    ):
        raise ValueError("unresolved token-decimals perimeter is stale or internally inconsistent")
    anchors = {row["token"]: row for row in manifest["anchors"]}
    unresolved = ledger["unresolved"]
    tokens = sorted(row["token"] for row in unresolved)
    if (
        len(tokens) != int(ledger.get("unresolved_count", -1))
        or len(set(tokens)) != len(tokens)
        or any(row["anchor"] != anchors.get(row["token"]) for row in unresolved)
    ):
        raise ValueError("unresolved token-decimals rows disagree with selected anchors")
    for row in unresolved:
        anchor = TokenDecimalsAnchor(**row["anchor"])
        if row.get("anchor_identity_sha256") != token_decimals_anchor_sha256(anchor):
            raise ValueError("unresolved token-decimals anchor digest disagrees")
    if int(ledger.get("anchor_count", -1)) != int(manifest.get("anchor_count", -2)):
        raise ValueError("unresolved token-decimals anchor count disagrees")
    return manifest, ledger, tokens


def validate_selected_lineage(manifest: dict) -> dict[str, list[Path]]:
    """Revalidate only the exact Parquet perimeters consumed by this audit."""

    selected: dict[str, list[Path]] = {"exact": []}
    selected.update({venue: [] for venue in V2_VENUES})
    expected_hashes: dict[Path, str] = {}
    for record in manifest["lineage_inputs"]:
        relative = Path(record["path"])
        if relative.suffix != ".parquet":
            continue
        key = None
        if "v2_core_event_source/global_50_block_chunks" in relative.as_posix():
            key = "exact"
        else:
            for venue in V2_VENUES:
                if f"v2_factory_pair_registry/{venue}/leaves" in relative.as_posix():
                    key = venue
                    break
        if key is None:
            continue
        path = REPO_ROOT / relative
        selected[key].append(path)
        expected_hashes[path] = record["sha256"]
    if any(not paths for paths in selected.values()):
        raise ValueError("selected-anchor lineage lacks an exact consumed perimeter")
    for key, paths in selected.items():
        if len(paths) != len(set(paths)):
            raise ValueError(f"selected-anchor lineage duplicates {key} inputs")
        for path in paths:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hashes[path]:
                raise ValueError(f"selected-anchor lineage changed: {path.relative_to(REPO_ROOT)}")
        selected[key] = sorted(paths)
    return selected


def decimals_scale_record(observations: list[object]) -> dict[str, object]:
    """Return the project's fail-closed 0..36 quantity-scale envelope."""

    reported = sorted(
        {int(value) for value in observations if value not in (None, "") and str(value).isdigit()}
    )
    return {
        "provider_decimals": reported,
        "exact_decimals_min": 0,
        "exact_decimals_max": MAX_TOKEN_DECIMALS,
        "max_upward_scale_exponent": max(reported) if reported else None,
        "max_downward_scale_exponent": MAX_TOKEN_DECIMALS - min(reported) if reported else None,
        "unreported_raw_quantity_exponent_width": MAX_TOKEN_DECIMALS if not reported else None,
    }


def factory_pairs(
    con: duckdb.DuckDBPyConnection,
    tokens: list[str],
    lineage: dict[str, list[Path]],
) -> pd.DataFrame:
    rows = []
    token_sql = _quoted(tokens)
    for venue in V2_VENUES:
        view = f"selected_{venue}_factory"
        con.from_parquet([str(path) for path in lineage[venue]], union_by_name=True).create_view(view)
        frame = con.sql(
            f"""
            WITH registry AS (
              SELECT block_number,
                     '0x'||right(topics[2],40) AS token0,
                     '0x'||right(topics[3],40) AS token1,
                     '0x'||substr(data,27,40) AS pool
              FROM {view}
            )
            SELECT *, CASE WHEN token0 IN ({token_sql}) THEN token0 ELSE token1 END AS affected_token
            FROM registry
            WHERE token0 IN ({token_sql}) OR token1 IN ({token_sql})
            """
        ).df()
        frame.insert(0, "venue", venue)
        rows.append(frame)
    out = pd.concat(rows, ignore_index=True).sort_values(["venue", "affected_token", "block_number"])
    if out.empty or out.affected_token.nunique() != len(tokens) or out.pool.duplicated().any():
        raise ValueError("factory registry does not identify a unique affected-pool perimeter")
    return out


def exact_event_exposure(
    con: duckdb.DuckDBPyConnection,
    pools: pd.DataFrame,
    lineage: dict[str, list[Path]],
) -> pd.DataFrame:
    con.register("affected_pools", pools[["venue", "pool", "affected_token"]])
    con.from_parquet([str(path) for path in lineage["exact"]], union_by_name=True).create_view(
        "selected_exact_events"
    )
    out = con.sql(
        f"""
        SELECT p.venue, p.affected_token, e.address AS pool, e.topics[1] AS topic,
               count(*) AS events, count(DISTINCT transaction_hash) AS transactions,
               min(block_number) AS min_block, max(block_number) AS max_block
        FROM selected_exact_events e
        JOIN affected_pools p ON e.address=p.pool
        GROUP BY ALL
        ORDER BY p.venue, p.affected_token, e.address, e.topics[1]
        """
    ).df()
    out["event_type"] = out.topic.map(V2_EVENT_BY_TOPIC)
    if out.event_type.isna().any():
        raise ValueError("affected exact-event perimeter contains an unknown topic")
    return out.drop(columns="topic")


def route_exposure(con: duckdb.DuckDBPyConnection, tokens: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    token_sql = _quoted(tokens)
    route_glob = (DATA_DIR / "unified" / "*.parquet").as_posix()
    con.execute(
        f"""
        CREATE TEMP TABLE affected_route_keys AS
        SELECT DISTINCT tx_hash, component_id
        FROM read_parquet('{route_glob}')
        WHERE route_class IN ('single','coherent')
          AND (token_in IN ({token_sql}) OR token_out IN ({token_sql}))
        """
    )
    legs = con.sql(
        f"""
        SELECT u.tx_hash, u.component_id, u.source, u.amount_usd, u.token_in,
               u.token_out, u.log_index, u.timestamp_utc
        FROM read_parquet('{route_glob}') u
        JOIN affected_route_keys k USING(tx_hash, component_id)
        WHERE route_class IN ('single','coherent')
        """
    ).df()
    keys = ["tx_hash", "component_id"]
    legs = legs.sort_values(keys + ["log_index"], kind="stable")
    eligibility = component_eligibility(legs, keys=keys)
    support = component_value_support(legs, keys=keys, token_roles=eligibility.token_roles)
    affected_roles = eligibility.token_roles[eligibility.token_roles.token.isin(tokens)]
    routes = legs.groupby(keys, as_index=False).agg(
        timestamp_utc=("timestamp_utc", "min"),
        legs=("source", "size"),
        venues=("source", "nunique"),
        venue_set=("source", lambda values: "+".join(sorted(set(values)))),
    )
    routes = routes.merge(support, on=keys, how="left").merge(
        affected_roles.groupby(keys, as_index=False).agg(
            affected_tokens=("token", "nunique"),
            affected_roles=("role", lambda values: "+".join(sorted(set(values)))),
        ),
        on=keys,
        how="left",
    )
    routes["year"] = pd.to_datetime(routes.timestamp_utc, unit="s", utc=True).dt.year
    routes["strict_usd"] = routes.amount_usd.where(routes.within_20pct, 0.0)
    intermediaries = role_token_values(
        legs, "intermediate", keys=keys, token_roles=eligibility.token_roles
    ).merge(support[keys + ["within_20pct"]], on=keys, how="left")
    candidates = intermediaries[
        intermediaries.token.isin(VEHICLE_CANDIDATES) & intermediaries.within_20pct.fillna(False)
    ].copy()
    affected_legs = int(
        (legs.token_in.isin(tokens) | legs.token_out.isin(tokens)).sum()
    )
    return routes, candidates, affected_legs


def _records() -> pd.DataFrame:
    manifest, ledger, tokens = validate_unresolved_perimeter()
    lineage = validate_selected_lineage(manifest)
    require_route_release()
    con = duckdb.connect()
    con.execute("SET threads=8")
    pools = factory_pairs(con, tokens, lineage)
    events = exact_event_exposure(con, pools, lineage)
    routes, candidate_intermediaries, affected_legs = route_exposure(con, tokens)

    vehicle = con.sql(
        f"""
        SELECT token, any_value(symbol) AS symbol, any_value(asset_type) AS asset_type,
               max(intermediate_usd) AS max_daily_intermediate_usd,
               sum(intermediate_routes_within_20pct) AS strict_intermediary_routes,
               sum(intermediate_usd_within_20pct) AS strict_intermediary_usd
        FROM read_parquet('{VEHICLE_PANEL.as_posix()}')
        WHERE token IN ({_quoted(tokens)})
        GROUP BY token
        """
    ).df()
    architecture = con.sql(
        f"""
        SELECT count(*) AS rows, coalesce(sum(route_usd),0) AS route_usd
        FROM read_parquet('{ARCHITECTURE_ROUTES.as_posix()}')
        WHERE src IN ({_quoted(tokens)}) OR sink IN ({_quoted(tokens)})
           OR vehicle_id IN ({_quoted(tokens)})
        """
    ).df().iloc[0]
    route_totals = con.sql(
        f"""SELECT sum(routes) AS routes, sum(intermediated_routes) AS intermediated_routes,
                   sum(total_usd) AS total_usd
            FROM read_parquet('{ROUTE_PANEL.as_posix()}')"""
    ).df().iloc[0]
    vehicle_totals = con.sql(
        f"""SELECT sum(intermediate_routes_within_20pct) AS routes,
                   sum(intermediate_usd_within_20pct) AS usd
            FROM read_parquet('{VEHICLE_PANEL.as_posix()}')"""
    ).df().iloc[0]
    con.close()

    candidate_summary = candidate_intermediaries.agg(
        routes=("tx_hash", "size"), usd=("amount_usd", "sum")
    )
    strict_route_usd = float(routes.strict_usd.sum())
    records: list[dict[str, object]] = [{
        "record_type": "summary",
        "decision": "bounded_exclusion_clears_fixed_cell_vehicle_rotation_not_exact_d2_registry",
        "unresolved_tokens": len(tokens),
        "failure_classifications": sorted({row["classification"] for row in ledger["unresolved"]}),
        "anchor_venues": {
            str(venue): int(count)
            for venue, count in pd.Series(
                [row["anchor"]["venue"] for row in ledger["unresolved"]]
            ).value_counts().items()
        },
        "factory_pairs_excluded": int(len(pools)),
        "installed_exact_candidate_events_excluded": int(events.events.sum()),
        "installed_exact_candidate_event_transactions": int(events.transactions.sum()),
        "selected_exact_chunk_files": len(lineage["exact"]),
        "released_route_legs_touching_tokens": affected_legs,
        "released_routes_deleted_worst_case": int(len(routes)),
        "released_route_count_share": float(len(routes) / route_totals.routes),
        "strict_route_usd_deleted_worst_case": strict_route_usd,
        "strict_route_usd_share_of_all_released_route_usd": float(strict_route_usd / route_totals.total_usd),
        "candidate_intermediary_routes_deleted_worst_case": int(candidate_summary.loc["routes", "tx_hash"]),
        "candidate_intermediary_route_share": float(candidate_summary.loc["routes", "tx_hash"] / vehicle_totals.routes),
        "candidate_intermediary_usd_deleted_worst_case": float(candidate_summary.loc["usd", "amount_usd"]),
        "candidate_intermediary_usd_share": float(candidate_summary.loc["usd", "amount_usd"] / vehicle_totals.usd),
        "affected_tokens_above_rotation_materiality_threshold": int((vehicle.max_daily_intermediate_usd > ROTATION_MATERIAL_USD).sum()),
        "affected_tokens_outside_residual_other_type": sum(
            asset_type(token) != "other" for token in tokens
        ),
        "v4_fixed_cell_architecture_rows": int(architecture["rows"]),
        "v4_fixed_cell_architecture_usd": float(architecture["route_usd"]),
        "decimals_policy_min": 0,
        "decimals_policy_max": MAX_TOKEN_DECIMALS,
        "exclusion_contract": "future exact V2 event/state generations omit these tokens and every factory pair containing them until exact historical decimals evidence exists; current certified releases are not rewritten",
    }]

    observations = manifest["provider_observations"]
    anchors = {row["token"]: row for row in manifest["anchors"]}
    pool_counts = pools.groupby("affected_token").size()
    vehicle_by_token = vehicle.set_index("token")
    for token in tokens:
        row = vehicle_by_token.loc[token] if token in vehicle_by_token.index else None
        records.append({
            "record_type": "token",
            "token": token,
            "anchor_venue": anchors[token]["venue"],
            "anchor_pool": anchors[token]["pool"],
            "anchor_block": int(anchors[token]["block_number"]),
            "anchor_event_type": anchors[token]["event_type"],
            "factory_pairs": int(pool_counts.get(token, 0)),
            "asset_type": asset_type(token),
            "max_daily_intermediary_usd": 0.0 if row is None else float(row.max_daily_intermediate_usd),
            "strict_intermediary_routes": 0 if row is None else int(row.strict_intermediary_routes),
            "strict_intermediary_usd": 0.0 if row is None else float(row.strict_intermediary_usd),
            **decimals_scale_record(observations.get(token, [])),
        })

    for year, group in routes.groupby("year", sort=True):
        records.append({
            "record_type": "route_year",
            "year": int(year),
            "routes": int(len(group)),
            "strict_routes": int(group.within_20pct.sum()),
            "route_usd": float(group.amount_usd.sum()),
            "strict_route_usd": float(group.strict_usd.sum()),
        })
    for venue, group in routes.groupby("venue_set", sort=True):
        records.append({
            "record_type": "route_venue_set",
            "venue_set": venue,
            "routes": int(len(group)),
            "strict_routes": int(group.within_20pct.sum()),
            "strict_route_usd": float(group.strict_usd.sum()),
        })
    for (venue, kind), group in events.groupby(["venue", "event_type"], sort=True):
        records.append({
            "record_type": "installed_exact_event_kind",
            "venue": venue,
            "event_type": kind,
            "pools": int(group.pool.nunique()),
            "events": int(group.events.sum()),
            "transactions": int(group.transactions.sum()),
        })
    for row in pools.itertuples(index=False):
        matching = events[events.pool.eq(row.pool)]
        records.append({
            "record_type": "factory_pair",
            "venue": row.venue,
            "affected_token": row.affected_token,
            "pool": row.pool,
            "paired_token": row.token1 if row.token0 == row.affected_token else row.token0,
            "creation_block": int(row.block_number),
            "installed_exact_candidate_events": int(matching.events.sum()),
        })
    for token, group in candidate_intermediaries.groupby("token", sort=True):
        records.append({
            "record_type": "candidate_intermediary_deletion",
            "candidate_token": token,
            "candidate_symbol": VEHICLE_CANDIDATES[token],
            "strict_routes": int(len(group)),
            "strict_intermediary_usd": float(group.amount_usd.sum()),
        })
    key_fields = {
        "summary": (),
        "token": ("token",),
        "route_year": ("year",),
        "route_venue_set": ("venue_set",),
        "installed_exact_event_kind": ("venue", "event_type"),
        "factory_pair": ("venue", "affected_token", "pool"),
        "candidate_intermediary_deletion": ("candidate_symbol", "candidate_token"),
    }
    compact = []
    for record in records:
        payload = dict(record)
        record_type = str(payload.pop("record_type"))
        fields = key_fields[record_type]
        key = "|".join(str(payload.pop(field)) for field in fields) if fields else "all"
        compact.append({"record_type": record_type, "key": key, "metrics": payload})
    return pd.DataFrame(compact)


def main() -> int:
    frame = _records()
    write_exhibit(
        frame,
        OUT,
        code_sources=CODE_SOURCES,
        inputs=[ANCHORS, UNRESOLVED, VEHICLE_PANEL, ROUTE_PANEL, ARCHITECTURE_ROUTES],
        notes="read-only deletion bound for unresolved exact V2 token-decimals anchors; no provider acquisition and no certified release rewrite",
    )
    print(
        json.dumps(
            frame.loc[frame.record_type.eq("summary"), "metrics"].iloc[0],
            default=str,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

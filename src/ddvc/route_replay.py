"""Build one authentic route trace for the paper and deck."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ddvc.asset_types import canonical_token
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.runtime import atomic_output

SCHEMA_VERSION = "dvc-route-replay-v1"


def _label(symbol: object, address: object) -> str:
    value = str(symbol or "").strip()
    if value and value.lower() not in {"nan", "none"}:
        return value
    token = canonical_token(address) or str(address)
    return f"{token[:6]}…{token[-4:]}" if len(token) > 12 else token


def _finite(value: object, name: str) -> float:
    number = float(value)
    if not pd.notna(number):
        raise ValueError(f"route replay {name} is not finite")
    return number


def build_route_replay_manifest(
    legs: pd.DataFrame,
    *,
    day: str,
    tx_hash: str,
    component_id: int,
) -> dict[str, object]:
    """Describe an exact two-leg route without rendering workflow metadata."""

    missing = sorted(set(LINEAR_ROUTE_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"route replay input is missing columns: {', '.join(missing)}")
    if not str(day).isdigit() or len(str(day)) != 8:
        raise ValueError("route replay day must be YYYYMMDD")
    transaction = str(tx_hash).lower()
    selected = legs[
        legs["tx_hash"].astype(str).str.lower().eq(transaction)
        & pd.to_numeric(legs["component_id"], errors="coerce").eq(int(component_id))
    ].copy()
    if selected.empty:
        raise ValueError("route replay transaction component is absent")

    routes = extract_linear_realised_routes(selected)
    if len(routes) != 1:
        raise ValueError("route replay requires exactly one coherent two-leg vehicle route")
    route = routes.iloc[0]
    source = canonical_token(route["src"])
    vehicle = canonical_token(route["vehicle"])
    target = canonical_token(route["tgt"])
    ordered: list[pd.Series] = []
    for token_in, token_out in ((source, vehicle), (vehicle, target)):
        candidates = selected[
            selected["token_in"].map(canonical_token).eq(token_in)
            & selected["token_out"].map(canonical_token).eq(token_out)
        ]
        if len(candidates) != 1:
            raise ValueError("route replay legs do not form one linear source-vehicle-target path")
        ordered.append(candidates.iloc[0])

    first, second = ordered
    timestamp = int(route["timestamp_utc"])
    return {
        "schema_version": SCHEMA_VERSION,
        "day": str(day),
        "timestamp_utc": timestamp,
        "timestamp_iso": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
        "tx_hash": transaction,
        "component_id": int(component_id),
        "route": {
            "source": _label(first["token_in_sym"], first["token_in"]),
            "vehicle": _label(first["token_out_sym"], first["token_out"]),
            "target": _label(second["token_out_sym"], second["token_out"]),
            "input_amount": _finite(first["amount_in"], "input amount"),
            "output_amount": _finite(second["amount_out"], "output amount"),
            "value_usd": _finite(route["usd"], "value"),
            "endpoint_value_ratio": _finite(route["endpoint_value_ratio"], "endpoint value ratio"),
            "venues": [str(first["source"]), str(second["source"])],
            "legs": [
                {
                    "step": 1,
                    "log_index": int(first["log_index"]),
                    "venue": str(first["source"]),
                    "token_in": _label(first["token_in_sym"], first["token_in"]),
                    "token_out": _label(first["token_out_sym"], first["token_out"]),
                    "amount_in": _finite(first["amount_in"], "hop-one input"),
                    "amount_out": _finite(first["amount_out"], "hop-one output"),
                },
                {
                    "step": 2,
                    "log_index": int(second["log_index"]),
                    "venue": str(second["source"]),
                    "token_in": _label(second["token_in_sym"], second["token_in"]),
                    "token_out": _label(second["token_out_sym"], second["token_out"]),
                    "amount_in": _finite(second["amount_in"], "hop-two input"),
                    "amount_out": _finite(second["amount_out"], "hop-two output"),
                },
            ],
        },
    }


def _validated_route(
    manifest: dict[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("route replay manifest schema is unsupported")
    route = manifest.get("route")
    if not isinstance(route, dict) or not isinstance(route.get("legs"), list) or len(route["legs"]) != 2:
        raise ValueError("route replay manifest must contain two legs")
    legs = route["legs"]
    if not all(isinstance(leg, dict) for leg in legs):
        raise ValueError("route replay legs must be objects")
    return route, legs


def render_route_replay_deck_values(manifest: dict[str, object]) -> str:
    """Bind slide labels to the admitted route manifest."""

    route, legs = _validated_route(manifest)
    first, second = legs

    def amount(value: object) -> str:
        return f"{float(value):,.0f}"

    return "\n".join(
        [
            "% Generated by scripts/plot/build_route_replay.py; do not edit.",
            f"\\newcommand{{\\RouteReplayInputAmount}}{{{amount(first['amount_in'])}}}",
            f"\\newcommand{{\\RouteReplayVehicleAmount}}{{{amount(first['amount_out'])}}}",
            f"\\newcommand{{\\RouteReplayOutputAmount}}{{{amount(second['amount_out'])}}}",
            f"\\newcommand{{\\RouteReplayValue}}{{{amount(route['value_usd'])}}}",
            "",
        ]
    )


def write_route_replay_outputs(
    manifest: dict[str, object], *, manifest_path: Path, tex_path: Path
) -> tuple[Path, Path]:
    """Atomically install the manifest and its deck binding."""

    with atomic_output(manifest_path) as temporary:
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with atomic_output(tex_path) as temporary:
        temporary.write_text(render_route_replay_deck_values(manifest), encoding="utf-8")
    return manifest_path, tex_path


def manifest_from_partition(
    path: Path, *, day: str, tx_hash: str, component_id: int
) -> dict[str, object]:
    """Read one route partition into the replay."""

    legs = pd.read_parquet(path, columns=LINEAR_ROUTE_COLUMNS)
    return build_route_replay_manifest(
        legs,
        day=day,
        tx_hash=tx_hash,
        component_id=component_id,
    )

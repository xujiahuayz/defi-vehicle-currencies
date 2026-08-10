"""Marker-last, lineage-bound cache bundles for route-cost day shards."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from ddvc.route_cost import QUOTE_CELL_KEYS
from ddvc.runtime import atomic_output


ROUTE_DAY_CACHE_SCHEMA_VERSION = 1
STATE_CUT_SEMANTICS = "released_canonical_end_of_utc_hour_v1"


def marker_path(path: Path) -> Path:
    return path.with_suffix(".complete.json")


def manifest_path(cache_root: Path) -> Path:
    return cache_root / "ordered_shards.complete.json"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_sha256(frame: pd.DataFrame) -> str:
    schema = [(str(column), str(dtype)) for column, dtype in frame.dtypes.items()]
    return hashlib.sha256(
        json.dumps(schema, separators=(",", ":")).encode()
    ).hexdigest()


def _key_sha256(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"").hexdigest()
    missing = sorted(set(QUOTE_CELL_KEYS) - set(frame.columns))
    if missing:
        raise ValueError(f"route day cache lacks quote-cell keys: {missing}")
    keys = frame.loc[:, list(QUOTE_CELL_KEYS)].sort_values(
        list(QUOTE_CELL_KEYS), kind="stable"
    )
    if keys.duplicated().any():
        raise ValueError("route day cache contains duplicate quote cells")
    values = pd.util.hash_pandas_object(keys, index=False).values
    return hashlib.sha256(values.tobytes()).hexdigest()


def _day_bounds(frame: pd.DataFrame, identity: dict[str, object]) -> dict[str, object]:
    if frame.empty:
        return {"date_min": None, "date_max": None, "hour_min": None, "hour_max": None}
    if "date" not in frame or "reserve_hour_utc" not in frame:
        raise ValueError("nonempty route day cache lacks date/hour state cuts")
    dates = frame["date"].astype(str).str.replace("-", "", regex=False)
    expected = str(identity.get("day") or "")
    if set(dates) != {expected}:
        raise ValueError(f"route day cache row date disagrees with identity: {expected}")
    hours = pd.to_numeric(frame["reserve_hour_utc"], errors="raise").astype(int)
    if not hours.between(0, 23).all():
        raise ValueError("route day cache has a state cut outside UTC hours 0--23")
    return {
        "date_min": expected,
        "date_max": expected,
        "hour_min": int(hours.min()),
        "hour_max": int(hours.max()),
    }


def write_day_cache(
    frame: pd.DataFrame,
    path: Path,
    *,
    identity: dict[str, object],
) -> None:
    """Write data atomically, then publish its completion marker last."""

    _key_sha256(frame)
    bounds = _day_bounds(frame, identity)
    with atomic_output(path) as temporary:
        frame.to_parquet(temporary, index=False)
    stat = path.stat()
    marker = {
        "schema_version": ROUTE_DAY_CACHE_SCHEMA_VERSION,
        "status": "complete",
        "state_cut_semantics": STATE_CUT_SEMANTICS,
        "identity": identity,
        "rows": len(frame),
        "content_bytes": stat.st_size,
        "content_sha256": _file_sha256(path),
        "schema_sha256": _schema_sha256(frame),
        "quote_key_sha256": _key_sha256(frame),
        **bounds,
    }
    with atomic_output(marker_path(path)) as temporary:
        temporary.write_text(
            json.dumps(marker, allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def day_cache_is_current(path: Path, *, identity: dict[str, object]) -> bool:
    """Verify the complete bundle; a bare or mutated parquet is never reusable."""

    marker = marker_path(path)
    if not path.is_file() or not marker.is_file():
        return False
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
        if (
            record.get("schema_version") != ROUTE_DAY_CACHE_SCHEMA_VERSION
            or record.get("status") != "complete"
            or record.get("state_cut_semantics") != STATE_CUT_SEMANTICS
            or record.get("identity") != identity
            or int(record.get("content_bytes", -1)) != path.stat().st_size
            or record.get("content_sha256") != _file_sha256(path)
        ):
            return False
        frame = pd.read_parquet(path)
        bounds = _day_bounds(frame, identity)
        return bool(
            int(record.get("rows", -1)) == len(frame)
            and record.get("schema_sha256") == _schema_sha256(frame)
            and record.get("quote_key_sha256") == _key_sha256(frame)
            and all(record.get(key) == value for key, value in bounds.items())
        )
    except Exception:
        return False


def write_ordered_shard_manifest(
    paths: list[Path],
    *,
    identities: list[dict[str, object]],
    output: Path,
) -> None:
    """Validate every shard and publish one ordered, complete perimeter."""

    if len(paths) != len(identities) or not paths:
        raise ValueError("ordered route shard manifest requires one identity per shard")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("route shard manifest paths are not strictly ordered and unique")
    scope = identities[0].get("scope")
    dependency = identities[0].get("quote_dependency_fingerprint")
    if any(
        identity.get("scope") != scope
        or identity.get("quote_dependency_fingerprint") != dependency
        for identity in identities
    ):
        raise ValueError("route shard manifest mixes scope or lineage generations")
    shards: list[dict[str, object]] = []
    for path, identity in zip(paths, identities, strict=True):
        if not day_cache_is_current(path, identity=identity):
            raise ValueError(f"route day cache is missing, stale, or mutated: {path}")
        if str(identity.get("day")) != path.stem:
            raise ValueError(f"route day cache identity/path mismatch: {path}")
        marker = json.loads(marker_path(path).read_text(encoding="utf-8"))
        shards.append(
            {
                "day": identity.get("day"),
                "path": path.name,
                "rows": marker["rows"],
                "content_bytes": marker["content_bytes"],
                "content_sha256": marker["content_sha256"],
                "schema_sha256": marker["schema_sha256"],
                "quote_key_sha256": marker["quote_key_sha256"],
                "date_min": marker["date_min"],
                "date_max": marker["date_max"],
                "hour_min": marker["hour_min"],
                "hour_max": marker["hour_max"],
                "marker_sha256": _file_sha256(marker_path(path)),
            }
        )
    manifest_sha256 = hashlib.sha256(
        json.dumps(shards, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    record = {
        "schema_version": ROUTE_DAY_CACHE_SCHEMA_VERSION,
        "status": "complete",
        "state_cut_semantics": STATE_CUT_SEMANTICS,
        "scope_identity": scope,
        "quote_dependency_fingerprint": dependency,
        "shard_count": len(shards),
        "manifest_sha256": manifest_sha256,
        "shards": shards,
    }
    with atomic_output(output) as temporary:
        temporary.write_text(
            json.dumps(record, allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

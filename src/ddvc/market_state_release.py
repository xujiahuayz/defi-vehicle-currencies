"""Family-specific market-state manifests on the canonical artifact-release owner."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

import pandas as pd

from ddvc.artifact_release import (
    canonical_json_sha256,
    file_sha256,
    is_sha256,
    publish_artifact_release,
    resolve_artifact_release,
)
from ddvc.paths import DATA_DIR
from ddvc.state_data import (
    FAMILY_PRODUCER_FINGERPRINTS,
    FAMILY_STREAMS,
    SCHEMA_VERSION,
    STATE_ENGINE,
    STATE_ROOT,
    state_partition_path,
    state_quality_path,
)


RELEASE_SCHEMA_VERSION = 1
RELEASE_KIND = "canonical_market_state_family"
RELEASE_FILENAMES = {"manifest": "manifest.json"}
MARKET_STATE_ROOT = DATA_DIR / "processed" / "market_state"
RELEASE_ROOT = MARKET_STATE_ROOT / "releases"
PINS_PATH = MARKET_STATE_ROOT / "pins.json"
CODE_SOURCES = [
    "src/ddvc/artifact_release.py",
    "src/ddvc/market_state_release.py",
    "src/ddvc/state_data.py",
]


@dataclass(frozen=True)
class MarketStateReleaseEntry:
    family: str
    venue: str
    day: str
    panel_relative: str
    marker_relative: str
    input_fingerprint: str
    producer_fingerprint: str
    output_bytes: int
    output_sha256: str
    marker_sha256: str
    panel_stat_identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class MarketStateFamilyRelease:
    family: str
    generation_id: str
    engine: str
    producer_fingerprint: str
    ledger_sha256: str
    state_root: Path
    pointer_path: Path
    manifest_path: Path
    entries: Mapping[tuple[str, str], MarketStateReleaseEntry]


def family_pointer_path(family: str, *, root: Path = RELEASE_ROOT) -> Path:
    if family not in FAMILY_STREAMS:
        raise ValueError(f"unsupported market-state family: {family}")
    return root / family / "current.json"


def panel_content_identity(path: Path) -> tuple[int, int, int, int]:
    """Return a cheap local content identity stable across hardlink creation."""

    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def release_entry_is_current(
    entry: MarketStateReleaseEntry,
    *,
    panel: Path,
    marker: Path,
) -> bool:
    """Validate a released partition cheaply, hashing only after a local transfer."""

    if not panel.is_file() or not marker.is_file() or file_sha256(marker) != entry.marker_sha256:
        return False
    before = panel_content_identity(panel)
    if before[2] != entry.output_bytes:
        return False
    if before == entry.panel_stat_identity:
        return before == panel_content_identity(panel)
    digest = file_sha256(panel)
    return before == panel_content_identity(panel) and digest == entry.output_sha256


def _entry_identity(entry: MarketStateReleaseEntry) -> dict[str, object]:
    return {
        "family": entry.family,
        "venue": entry.venue,
        "day": entry.day,
        "panel_relative": entry.panel_relative,
        "marker_relative": entry.marker_relative,
        "input_fingerprint": entry.input_fingerprint,
        "producer_fingerprint": entry.producer_fingerprint,
        "output_bytes": entry.output_bytes,
        "output_sha256": entry.output_sha256,
        "marker_sha256": entry.marker_sha256,
    }


def _release_identity(
    family: str,
    entries: list[MarketStateReleaseEntry],
    *,
    engine: str,
    producer_fingerprint: str,
) -> dict[str, object]:
    return {
        "state_schema_version": SCHEMA_VERSION,
        "engine": engine,
        "family": family,
        "producer_fingerprint": producer_fingerprint,
        "entries": [_entry_identity(entry) for entry in entries],
    }


def _quality_entries(
    quality: pd.DataFrame,
    *,
    family: str,
    state_root: Path,
) -> list[MarketStateReleaseEntry]:
    selected = quality.loc[quality["family"].astype(str).eq(family)].sort_values(
        ["venue", "day"], kind="stable"
    )
    if selected.empty or selected.duplicated(["venue", "day"]).any():
        raise ValueError(f"market-state {family} release perimeter is empty or duplicated")
    producer = FAMILY_PRODUCER_FINGERPRINTS[family]
    entries: list[MarketStateReleaseEntry] = []
    for row in selected.itertuples(index=False):
        venue, day = str(row.venue), str(row.day).zfill(8)
        panel = state_partition_path(family, venue, day, root=state_root)
        marker = state_quality_path(family, venue, day, root=state_root)
        if not panel.is_file() or not marker.is_file():
            raise FileNotFoundError(f"market-state release input missing: {family}/{venue}/{day}")
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if (
            payload.get("family") != family
            or payload.get("venue") != venue
            or str(payload.get("day")).zfill(8) != day
            or payload.get("passed") is not True
            or payload.get("producer_fingerprint") != producer
            or payload.get("input_fingerprint") != row.input_fingerprint
            or int(payload.get("output_bytes", -1)) != int(row.output_bytes)
            or payload.get("output_sha256") != row.output_sha256
            or panel.stat().st_size != int(row.output_bytes)
        ):
            raise ValueError(f"market-state release marker mismatch: {family}/{venue}/{day}")
        entries.append(
            MarketStateReleaseEntry(
                family=family,
                venue=venue,
                day=day,
                panel_relative=panel.relative_to(state_root).as_posix(),
                marker_relative=marker.relative_to(state_root).as_posix(),
                input_fingerprint=str(row.input_fingerprint),
                producer_fingerprint=producer,
                output_bytes=int(row.output_bytes),
                output_sha256=str(row.output_sha256),
                marker_sha256=file_sha256(marker),
                panel_stat_identity=panel_content_identity(panel),
            )
        )
    return entries


def _manifest_payload(
    quality: pd.DataFrame,
    *,
    family: str,
    state_root: Path,
    ledger_path: Path,
) -> dict[str, object]:
    entries = _quality_entries(quality, family=family, state_root=state_root)
    identity = _release_identity(
        family,
        entries,
        engine=STATE_ENGINE,
        producer_fingerprint=FAMILY_PRODUCER_FINGERPRINTS[family],
    )
    return {
        **identity,
        "identity_sha256": canonical_json_sha256(identity),
        "state_root": state_root.name,
        "ledger_sha256": file_sha256(ledger_path),
        "local_panel_stat_identities": {
            f"{entry.venue}/{entry.day}": list(entry.panel_stat_identity)
            for entry in entries
        },
    }


def _validate_manifest(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    identity = {
        "state_schema_version": payload.get("state_schema_version"),
        "engine": payload.get("engine"),
        "family": payload.get("family"),
        "producer_fingerprint": payload.get("producer_fingerprint"),
        "entries": entries,
    }
    if (
        payload.get("state_schema_version") != SCHEMA_VERSION
        or payload.get("family") not in FAMILY_STREAMS
        or not is_sha256(payload.get("producer_fingerprint"))
        or not is_sha256(payload.get("ledger_sha256"))
        or not isinstance(entries, list)
        or payload.get("identity_sha256") != canonical_json_sha256(identity)
        or not isinstance(payload.get("local_panel_stat_identities"), dict)
    ):
        raise ValueError("invalid market-state family manifest")


def publish_market_state_family_release(
    quality: pd.DataFrame,
    *,
    family: str,
    ledger_path: Path,
    state_root: Path = STATE_ROOT,
    pointer_path: Path | None = None,
) -> MarketStateFamilyRelease:
    """Publish one small manifest through the shared marker-last release owner."""

    pointer = pointer_path or family_pointer_path(family)
    payload = _manifest_payload(
        quality,
        family=family,
        state_root=state_root,
        ledger_path=ledger_path,
    )

    def write_manifest(path: Path) -> None:
        path.write_text(
            json.dumps(payload, allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    publish_artifact_release(
        pointer_path=pointer,
        kind=RELEASE_KIND,
        schema_version=RELEASE_SCHEMA_VERSION,
        filenames=RELEASE_FILENAMES,
        writers={"manifest": write_manifest},
        row_counts={"manifest": len(payload["entries"])},
        code_sources=CODE_SOURCES,
        inputs=[ledger_path],
        notes=f"complete {family} market-state manifest for {state_root.name}",
        validate_staged=lambda paths: _validate_manifest(paths["manifest"]),
    )
    return resolve_market_state_family_release(family, pointer_path=pointer)


def resolve_market_state_family_release(
    family: str,
    *,
    pointer_path: Path | None = None,
    required: bool = True,
) -> MarketStateFamilyRelease | None:
    """Resolve one family through the shared artifact-release contract."""

    pointer = pointer_path or family_pointer_path(family)
    if not pointer.is_file():
        if required:
            raise FileNotFoundError(f"market-state {family} current pointer missing: {pointer}")
        return None
    release = resolve_artifact_release(
        pointer,
        kind=RELEASE_KIND,
        schema_version=RELEASE_SCHEMA_VERSION,
        filenames=RELEASE_FILENAMES,
        require_current_provenance=False,
    )
    manifest = release.artifacts["manifest"]
    _validate_manifest(manifest)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("family") != family:
        raise ValueError(f"market-state pointer selects a different family: {family}")
    root_name = payload.get("state_root")
    if not isinstance(root_name, str) or not root_name.startswith("engine_") or Path(root_name).name != root_name:
        raise ValueError(f"invalid market-state root in {family} manifest")
    stats = payload["local_panel_stat_identities"]
    entries: dict[tuple[str, str], MarketStateReleaseEntry] = {}
    for raw in payload["entries"]:
        venue, day = str(raw.get("venue")), str(raw.get("day")).zfill(8)
        stat = stats.get(f"{venue}/{day}")
        if not isinstance(stat, list) or len(stat) != 4:
            raise ValueError(f"market-state {family} local stat identity is invalid")
        entry = MarketStateReleaseEntry(
            **raw,
            panel_stat_identity=tuple(int(value) for value in stat),
        )
        if entry.family != family or (venue, day) in entries:
            raise ValueError(f"market-state {family} manifest contains an invalid entry")
        entries[(venue, day)] = entry
    return MarketStateFamilyRelease(
        family=family,
        generation_id=release.generation_id,
        engine=str(payload["engine"]),
        producer_fingerprint=str(payload["producer_fingerprint"]),
        ledger_sha256=str(payload["ledger_sha256"]),
        state_root=pointer.parents[2] / root_name,
        pointer_path=pointer,
        manifest_path=manifest,
        entries=entries,
    )


def pinned_engine_names(path: Path = PINS_PATH) -> set[str]:
    if not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("engines") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise ValueError("market-state pins must contain an engines list")
    names = {str(value) for value in values}
    if any(not name.startswith("engine_") or Path(name).name != name for name in names):
        raise ValueError("market-state pins contain an invalid engine name")
    return names


def market_state_gc_candidates(
    *,
    root: Path = MARKET_STATE_ROOT,
    target_root: Path = STATE_ROOT,
    pins_path: Path = PINS_PATH,
) -> tuple[Path, ...]:
    """Plan exact unreferenced engine directories without deleting anything."""

    retained = {target_root.name, *pinned_engine_names(pins_path)}
    release_root = root / "releases"
    for family in FAMILY_STREAMS:
        release = resolve_market_state_family_release(
            family,
            pointer_path=family_pointer_path(family, root=release_root),
            required=False,
        )
        if release is not None:
            retained.add(release.state_root.name)
    return tuple(
        path
        for path in sorted(root.glob("engine_*"))
        if path.is_dir() and not path.is_symlink() and path.name not in retained
    )

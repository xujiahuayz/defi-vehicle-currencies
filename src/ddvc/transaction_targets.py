"""Certified target-route ledgers for transaction-state frontier scoring.

The full daily ledger is provider-derived. Its construction is admissible only after the current audit calendar has matched every admitted route leg to independently retained Ethereum ``eth_getLogs`` and block-header evidence. The release schema keeps that sampled validation distinct from full-history receipt or chain-log anchoring.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd
import pyarrow.parquet as pq

from ddvc.amounts import human_to_raw
from ddvc.artifact_release import publish_artifact_release, resolve_artifact_release
from ddvc.asset_types import asset_type, canonical_token
from ddvc.ethereum_logs import (
    RAW_LOG_SCHEMA,
    file_sha256,
    validate_anchored_log_evidence,
    validate_canonical_log_records,
)
from ddvc.paths import DATA_DIR, REPO_ROOT
from ddvc.provenance import code_fingerprint
from ddvc.realised import LINEAR_REALISED_ROUTE_OUTPUT_COLUMNS, LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.runtime import atomic_output, serialized_output_install, serialized_read_installs
from ddvc.source_records import timestamp_value, transaction_id, v4_quote_status
from ddvc.v2_event_completeness import decode_v2_log
from ddvc.v3_inventory import decode_inventory_log
from ddvc.v4_contract import UNISWAP_V4_POOL_MANAGER_ADDRESS, UNISWAP_V4_SWAP_TOPIC, decode_v4_state_event_identity


TARGET_RELEASE_SCHEMA_VERSION = 1
TARGET_DAY_SCHEMA_VERSION = 1
TARGET_RELEASE_ROOT = DATA_DIR / "empirical" / "transaction_target_release"
TARGET_SCOPES = ("audit", "daily")
EXACT_VENUES = ("uniswap_v2", "sushiswap_v2", "uniswap_v3", "uniswap_v4")
TARGET_RELEASE_MANIFEST_FILENAME = "manifest.json"
VALIDATION_ALPHA = 0.05
VALIDATION_CAVEAT = (
    "The one-sided mismatch bound is conditional on route-leg exchangeability. The current audit calendar does not bound a failure confined to an unsampled day."
)
TARGET_LEDGER_EXTRA_COLUMNS = [
    "day",
    "target_order_block",
    "target_order_log_index",
    "target_timestamp",
    "realised_leg1_output",
    "realised_leg2_input",
    "target_admitted",
    "target_structural_rejection",
    "vehicle_type",
    *(
        f"{prefix}_{field}"
        for prefix in ("leg1", "leg2")
        for field in (
            "venue",
            "pool",
            "block_number",
            "log_index",
            "token_in_raw",
            "token_out_raw",
            "amount_in_raw",
            "amount_out_raw",
        )
    ),
]
TARGET_LEDGER_COLUMNS = list(dict.fromkeys([*LINEAR_REALISED_ROUTE_OUTPUT_COLUMNS, *TARGET_LEDGER_EXTRA_COLUMNS]))


class TargetEvidenceError(RuntimeError):
    """A target cannot be reconciled to its released provider or chain evidence."""


@dataclass(frozen=True)
class ProviderSwapEvent:
    venue: str
    tx_hash: str
    block_number: int
    log_index: int
    timestamp: int
    pool: str
    token0: str
    token1: str
    decimals0: int
    decimals1: int
    amount0_raw: int
    amount1_raw: int
    quote_supported: bool
    quote_unsupported_reason: str | None = None


@dataclass(frozen=True)
class ChainSwapEvent:
    venue: str
    tx_hash: str
    block_number: int
    log_index: int
    pool: str
    amount0_raw: int
    amount1_raw: int
    block_timestamp: int
    block_hash: str | None = None


@dataclass(frozen=True)
class TargetRelease:
    scope: str
    generation: str
    pointer_path: Path
    manifest_path: Path
    day_markers: tuple[Path, ...]
    calendar: tuple[str, ...]
    validation: Mapping[str, object]

    @property
    def content_identity_sha256(self) -> str:
        """Bind a long-running consumer to one exact resolved release."""

        return _json_sha256(
            {
                "scope": self.scope,
                "generation": self.generation,
                "calendar": self.calendar,
                "pointer_sha256": _sha256(self.pointer_path),
                "manifest_sha256": _sha256(self.manifest_path),
            }
        )

    def assert_current(self) -> None:
        """Reopen every day lineage and reject source drift since resolution."""

        reopened = resolve_target_release(
            self.scope,
            expected_days=self.calendar,
            root=self.pointer_path.parents[2],
        )
        if (
            reopened.generation != self.generation
            or reopened.content_identity_sha256 != self.content_identity_sha256
        ):
            raise TargetEvidenceError(
                f"{self.scope} transaction-target release changed during consumption"
            )

    @property
    def lineage_paths(self) -> tuple[Path, ...]:
        return (
            self.pointer_path,
            self.manifest_path,
            self.day_markers[0].parents[1],
            *self.day_markers,
        )


@contextmanager
def current_target_release(release: TargetRelease):
    """Lease one complete transaction-target generation during consumption."""

    with serialized_read_installs(release.lineage_paths):
        release.assert_current()
        yield release
        release.assert_current()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _normalise_day(day: object) -> str:
    value = str(day).replace("-", "")
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"invalid target-ledger day: {day}")
    return value


def _require_scope(scope: str) -> str:
    if scope not in TARGET_SCOPES:
        raise ValueError(f"invalid target release scope: {scope}")
    return scope


def _target_release_kind(scope: str) -> str:
    return f"transaction_target_{_require_scope(scope)}"


def target_current_pointer(scope: str, *, root: Path = TARGET_RELEASE_ROOT) -> Path:
    return root / "releases" / _require_scope(scope) / "current.json"


def target_generation_root(
    generation: str, *, root: Path = TARGET_RELEASE_ROOT
) -> Path:
    if len(generation) != 64 or any(c not in "0123456789abcdef" for c in generation):
        raise ValueError("target release generation must be a sha256 digest")
    return root / "day_generations" / generation


def one_sided_zero_failure_upper_bound(
    trials: int, *, alpha: float = VALIDATION_ALPHA
) -> float:
    """Exact Clopper-Pearson upper mismatch bound after zero failures."""

    if trials < 1:
        raise ValueError("zero-failure mismatch bound requires positive trials")
    if not 0 < alpha < 1:
        raise ValueError("validation alpha must lie strictly between zero and one")
    return 1.0 - alpha ** (1.0 / trials)


def calendar_sha256(days: Iterable[str]) -> str:
    normalized = [_normalise_day(day) for day in days]
    if not normalized or normalized != sorted(set(normalized)):
        raise ValueError("release calendar must be nonempty, unique, and sorted")
    return _json_sha256(normalized)


def validation_contract(
    *,
    verified_legs: int,
    evidence_failures: int,
    audit_calendar: Iterable[str],
    full_calendar: Iterable[str],
) -> dict[str, object]:
    if verified_legs < 0 or evidence_failures < 0 or evidence_failures > verified_legs:
        raise ValueError("invalid chain-log validation counts")
    audit_days = tuple(_normalise_day(day) for day in audit_calendar)
    full_days = tuple(_normalise_day(day) for day in full_calendar)
    audit_hash = calendar_sha256(audit_days)
    full_hash = calendar_sha256(full_days)
    if not set(audit_days).issubset(full_days):
        raise ValueError("audit calendar is not a subset of the full release calendar")
    upper = (
        one_sided_zero_failure_upper_bound(verified_legs)
        if verified_legs and evidence_failures == 0
        else None
    )
    return {
        "evidence_kind": "exact_eth_getLogs_fixed_calendar_census",
        "validation_dates": len(audit_days),
        "validation_calendar_sha256": audit_hash,
        "full_daily_dates": len(full_days),
        "full_daily_calendar_sha256": full_hash,
        "day_coverage_share": len(audit_days) / len(full_days),
        "verified_legs": verified_legs,
        "evidence_failures": evidence_failures,
        "one_sided_confidence_level": 1.0 - VALIDATION_ALPHA,
        "per_leg_mismatch_upper_bound": upper,
        "bound_condition": "zero observed mismatches" if upper is not None else None,
        "exchangeability_caveat": VALIDATION_CAVEAT,
        "full_history_chain_log_anchored": False,
        "full_daily_target_kind": "provider_derived_conditioned_on_fixed_calendar_chain_log_validation",
    }


def daily_validation_contract(
    audit_release: TargetRelease,
    *,
    full_calendar: Iterable[str],
) -> dict[str, object]:
    if audit_release.scope != "audit":
        raise ValueError("daily target validation requires the current audit release")
    full_days = tuple(_normalise_day(day) for day in full_calendar)
    full_hash = calendar_sha256(full_days)
    observed = dict(audit_release.validation)
    if (
        int(observed.get("evidence_failures", -1)) != 0
        or int(observed.get("validation_dates", -1)) != len(audit_release.calendar)
        or observed.get("validation_calendar_sha256") != calendar_sha256(audit_release.calendar)
        or int(observed.get("full_daily_dates", -1)) != len(full_days)
        or observed.get("full_daily_calendar_sha256") != full_hash
        or bool(observed.get("full_history_chain_log_anchored"))
    ):
        raise TargetEvidenceError("audit validation does not identify the current full calendar")
    return observed


def strict_route_order(events: Iterable[ProviderSwapEvent]) -> tuple[int, int]:
    selected = tuple(events)
    if len(selected) != 2:
        raise ValueError("an exact target route must contain two provider events")
    blocks = {event.block_number for event in selected}
    if len(blocks) != 1:
        raise ValueError("target route legs disagree on transaction block")
    if len({event.log_index for event in selected}) != 2:
        raise ValueError("target route legs have duplicate log order")
    return min((event.block_number, event.log_index) for event in selected)


def _exact_raw(value: object, decimals: int, *, label: str) -> int:
    converted = human_to_raw(value, decimals)
    if converted is None:
        raise TargetEvidenceError(f"{label} is not an exact base-unit amount")
    return int(converted)


def provider_event_from_v2(event: object) -> ProviderSwapEvent:
    row = getattr(event, "row")
    return ProviderSwapEvent(
        venue=str(getattr(event, "venue")),
        tx_hash=str(getattr(event, "tx_hash")).lower(),
        block_number=int(getattr(event, "order")[0]),
        log_index=int(getattr(event, "log_index")),
        timestamp=int(getattr(event, "timestamp")),
        pool=str(getattr(event, "pool")).lower(),
        token0=str(row.get("token0_raw") or "").lower(),
        token1=str(row.get("token1_raw") or "").lower(),
        decimals0=int(row["decimals0"]),
        decimals1=int(row["decimals1"]),
        amount0_raw=_exact_raw(row["amount0_delta"], int(row["decimals0"]), label="V2 amount0"),
        amount1_raw=_exact_raw(row["amount1_delta"], int(row["decimals1"]), label="V2 amount1"),
        quote_supported=True,
    )


def provider_event_from_tick(
    event: object,
    *,
    v4_quarantined_pools: set[str] | frozenset[str] | None = None,
) -> ProviderSwapEvent:
    row = getattr(event, "row")
    pool = row.get("pool") or {}
    token0 = pool.get("token0") or {}
    token1 = pool.get("token1") or {}
    venue = str(getattr(event, "venue"))
    amount0 = row.get("amount0")
    amount1 = row.get("amount1")
    decimals0 = int(token0["decimals"])
    decimals1 = int(token1["decimals"])
    pool_id = str(pool.get("id") or "").lower()
    if venue == "uniswap_v4" and v4_quarantined_pools is None:
        raise ValueError("V4 target admission requires the canonical static-quarantine set")
    status = v4_quote_status(row) if venue == "uniswap_v4" else "vanilla_static_fee"
    quarantined = venue == "uniswap_v4" and pool_id in (v4_quarantined_pools or set())
    quote_supported = venue != "uniswap_v4" or (status == "vanilla_static_fee" and not quarantined)
    unsupported_reason = None
    if quarantined:
        unsupported_reason = "v4_static_quarantine"
    elif not quote_supported:
        unsupported_reason = f"v4_{status}"
    return ProviderSwapEvent(
        venue=venue,
        tx_hash=str(transaction_id(row) or "").lower(),
        block_number=int(getattr(event, "order")[0]),
        log_index=int(getattr(event, "order")[1]),
        timestamp=int(timestamp_value(row) or 0),
        pool=pool_id,
        token0=str(token0.get("id") or "").lower(),
        token1=str(token1.get("id") or "").lower(),
        decimals0=decimals0,
        decimals1=decimals1,
        amount0_raw=_exact_raw(amount0, decimals0, label=f"{venue} amount0"),
        amount1_raw=_exact_raw(amount1, decimals1, label=f"{venue} amount1"),
        quote_supported=quote_supported,
        quote_unsupported_reason=unsupported_reason,
    )


def provider_event_key(event: ProviderSwapEvent) -> tuple[str, str, int]:
    return event.venue, event.tx_hash, event.log_index


def chain_event_key(event: ChainSwapEvent) -> tuple[str, str, int]:
    return event.venue, event.tx_hash, event.log_index


def _raw_log_context(record: Mapping[str, object]) -> dict[str, object]:
    return {
        "address": record["address"],
        "blockNumber": record["block_number"],
        "blockHash": record.get("block_hash"),
        "transactionHash": record["transaction_hash"],
        "transactionIndex": record.get("transaction_index", 0),
        "logIndex": record["log_index"],
        "topics": record["topics"],
        "data": record["data"],
        "removed": record.get("removed", False),
    }


def _block_timestamp(
    record: Mapping[str, object], block_timestamps: Mapping[int, int]
) -> int:
    block = int(record["block_number"])
    try:
        timestamp = int(block_timestamps[block])
    except (KeyError, TypeError, ValueError) as error:
        raise TargetEvidenceError(f"chain evidence lacks a certified timestamp for block {block}") from error
    if timestamp <= 0:
        raise TargetEvidenceError(f"chain evidence has an invalid timestamp for block {block}")
    return timestamp


def decode_v2_chain_swap(
    venue: str,
    record: Mapping[str, object],
    *,
    block_timestamps: Mapping[int, int],
) -> ChainSwapEvent:
    key, amounts = decode_v2_log(venue, _raw_log_context(record))
    event_venue, event_type, block, tx_hash, log_index, pool = key
    if event_type != "swap":
        raise ValueError("target evidence is not a V2 swap log")
    return ChainSwapEvent(
        event_venue,
        tx_hash,
        block,
        log_index,
        pool,
        int(amounts.amount0_delta_raw),
        int(amounts.amount1_delta_raw),
        _block_timestamp(record, block_timestamps),
        str(record.get("block_hash") or "").lower() or None,
    )


def decode_v3_chain_swap(
    record: Mapping[str, object], *, block_timestamps: Mapping[int, int]
) -> ChainSwapEvent:
    decoded = decode_inventory_log(_raw_log_context(record))
    if decoded["event_type"] != "swap":
        raise ValueError("target evidence is not a V3 swap log")
    return ChainSwapEvent(
        "uniswap_v3",
        str(decoded["tx_hash"]),
        int(decoded["block_number"]),
        int(decoded["log_index"]),
        str(decoded["pool"]),
        int(decoded["amount0_delta_raw"]),
        int(decoded["amount1_delta_raw"]),
        _block_timestamp(record, block_timestamps),
        str(record.get("block_hash") or "").lower() or None,
    )


def decode_v4_chain_swap(
    record: Mapping[str, object], *, block_timestamps: Mapping[int, int]
) -> ChainSwapEvent:
    decoded = decode_v4_state_event_identity(dict(record), "swap")
    return ChainSwapEvent(
        "uniswap_v4",
        str(record.get("transaction_hash") or "").lower(),
        int(record["block_number"]),
        int(record["log_index"]),
        str(decoded["pool"]),
        int(decoded["amount0"]),
        int(decoded["amount1"]),
        _block_timestamp(record, block_timestamps),
        str(record.get("block_hash") or "").lower() or None,
    )


def validate_provider_chain_match(
    provider: ProviderSwapEvent, chain: ChainSwapEvent
) -> None:
    expected = (
        provider.venue,
        provider.tx_hash,
        provider.block_number,
        provider.log_index,
        provider.pool,
        provider.amount0_raw,
        provider.amount1_raw,
        provider.timestamp,
    )
    observed = (
        chain.venue,
        chain.tx_hash,
        chain.block_number,
        chain.log_index,
        chain.pool,
        chain.amount0_raw,
        chain.amount1_raw,
        chain.block_timestamp,
    )
    if observed != expected:
        raise TargetEvidenceError(
            "provider swap differs from independently retained chain log: "
            f"expected={expected}, observed={observed}"
        )


def _provider_direction(event: ProviderSwapEvent) -> tuple[str, str, int, int]:
    if event.amount0_raw > 0 and event.amount1_raw < 0:
        return event.token0, event.token1, event.amount0_raw, -event.amount1_raw
    if event.amount1_raw > 0 and event.amount0_raw < 0:
        return event.token1, event.token0, event.amount1_raw, -event.amount0_raw
    raise TargetEvidenceError("provider swap does not contain one positive input and one negative output")


def validate_leg_provider_match(leg: object, event: ProviderSwapEvent) -> None:
    tx_hash = str(getattr(leg, "tx_hash")).lower()
    venue = str(getattr(leg, "source"))
    try:
        log_index = int(getattr(leg, "log_index"))
    except (TypeError, ValueError) as error:
        raise TargetEvidenceError("target leg lacks an exact log index") from error
    token_in, token_out, amount_in_raw, amount_out_raw = _provider_direction(event)
    expected_in = canonical_token(token_in)
    expected_out = canonical_token(token_out)
    observed_in = canonical_token(str(getattr(leg, "token_in")))
    observed_out = canonical_token(str(getattr(leg, "token_out")))
    identity = (venue, tx_hash, log_index, observed_in, observed_out)
    expected_identity = (
        event.venue,
        event.tx_hash,
        event.log_index,
        expected_in,
        expected_out,
    )
    if identity != expected_identity:
        raise TargetEvidenceError(
            f"target leg differs from provider state: expected={expected_identity}, observed={identity}"
        )
    decimals_in = event.decimals0 if token_in == event.token0 else event.decimals1
    decimals_out = event.decimals0 if token_out == event.token0 else event.decimals1
    observed_amounts = (
        _exact_raw(getattr(leg, "amount_in"), decimals_in, label="target amount_in"),
        _exact_raw(getattr(leg, "amount_out"), decimals_out, label="target amount_out"),
    )
    if observed_amounts != (amount_in_raw, amount_out_raw):
        raise TargetEvidenceError(
            "target leg amounts differ from exact provider state: "
            f"expected={(amount_in_raw, amount_out_raw)}, observed={observed_amounts}"
        )


def _event_fields(prefix: str, event: ProviderSwapEvent) -> dict[str, object]:
    token_in, token_out, amount_in_raw, amount_out_raw = _provider_direction(event)
    return {
        f"{prefix}_venue": event.venue,
        f"{prefix}_pool": event.pool,
        f"{prefix}_block_number": event.block_number,
        f"{prefix}_log_index": event.log_index,
        f"{prefix}_token_in_raw": token_in,
        f"{prefix}_token_out_raw": token_out,
        f"{prefix}_amount_in_raw": str(amount_in_raw),
        f"{prefix}_amount_out_raw": str(amount_out_raw),
    }


def exact_target_leg_identities(
    legs: pd.DataFrame,
) -> set[tuple[str, str, int]]:
    missing = sorted(set(LINEAR_ROUTE_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError("target-ledger legs are missing columns: " + ", ".join(missing))
    all_routes = extract_linear_realised_routes(legs)
    exact_routes = all_routes[
        all_routes["realised_hop1_source"].isin(EXACT_VENUES)
        & all_routes["realised_hop2_source"].isin(EXACT_VENUES)
    ]
    route_keys = {
        (str(tx).lower(), int(component))
        for tx, component in zip(exact_routes["tx_hash"], exact_routes["component_id"], strict=True)
    }
    coherent = legs[legs["route_class"].eq("coherent") & legs["source"].isin(EXACT_VENUES)]
    identities = {
        (str(row.source), str(row.tx_hash).lower(), int(row.log_index))
        for row in coherent.itertuples(index=False)
        if (str(row.tx_hash).lower(), int(row.component_id)) in route_keys
    }
    if len(identities) != 2 * len(exact_routes):
        raise TargetEvidenceError("exact target routes do not have two unique provider leg identities")
    return identities


def build_provider_target_ledger(
    day: str,
    legs: pd.DataFrame,
    *,
    v2_events: Mapping[tuple[str, str, int], ProviderSwapEvent],
    tick_events: Mapping[tuple[str, str, int], ProviderSwapEvent],
    chain_events: Mapping[tuple[str, str, int], ChainSwapEvent] | None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Construct one bounded day and optionally census every leg against chain logs."""

    day = _normalise_day(day)
    exact_identities = exact_target_leg_identities(legs)
    all_routes = extract_linear_realised_routes(legs)
    exact_routes = all_routes[
        all_routes["realised_hop1_source"].isin(EXACT_VENUES)
        & all_routes["realised_hop2_source"].isin(EXACT_VENUES)
    ].copy()
    route_keys = {
        (str(tx).lower(), int(component))
        for tx, component in zip(
            exact_routes["tx_hash"], exact_routes["component_id"], strict=True
        )
    }
    coherent = legs[
        legs["route_class"].eq("coherent") & legs["source"].isin(EXACT_VENUES)
    ].copy()
    route_mask = pd.Series(
        [
            (str(source), str(tx).lower(), int(log_index)) in exact_identities
            for source, tx, log_index in zip(coherent["source"], coherent["tx_hash"], coherent["log_index"], strict=True)
        ],
        index=coherent.index,
        dtype=bool,
    )
    coherent = coherent.loc[route_mask].copy()
    grouped = {
        (str(key[0]).lower(), int(key[1])): group.sort_values("log_index", kind="stable")
        for key, group in coherent.groupby(["tx_hash", "component_id"], sort=False)
    }
    rows: list[dict[str, object]] = []
    verified_legs = 0
    unsupported_v4 = 0
    for route in exact_routes.to_dict("records"):
        tx_hash = str(route["tx_hash"]).lower()
        component = int(route["component_id"])
        selected = grouped.get((tx_hash, component))
        if selected is None or len(selected) != 2:
            raise TargetEvidenceError(
                f"exact target route lacks two ordered provider legs: {route['route_id']}"
            )
        provider_events: list[ProviderSwapEvent] = []
        for leg in selected.itertuples(index=False):
            try:
                log_index = int(leg.log_index)
            except (TypeError, ValueError) as error:
                raise TargetEvidenceError(
                    f"target route leg lacks log order: {route['route_id']}"
                ) from error
            key = (str(leg.source), tx_hash, log_index)
            event = (v2_events if str(leg.source) in {"uniswap_v2", "sushiswap_v2"} else tick_events).get(key)
            if event is None:
                raise TargetEvidenceError(f"provider state lacks target swap identity: {key}")
            validate_leg_provider_match(leg, event)
            if chain_events is not None and event.quote_supported:
                chain = chain_events.get(key)
                if chain is None:
                    raise TargetEvidenceError(f"chain evidence lacks target swap identity: {key}")
                validate_provider_chain_match(event, chain)
                verified_legs += 1
            provider_events.append(event)
        order = strict_route_order(provider_events)
        if any(event.tx_hash != tx_hash or event.block_number != order[0] for event in provider_events):
            raise TargetEvidenceError(f"route component order disagrees with transaction identity: {route['route_id']}")
        admitted = all(event.quote_supported for event in provider_events)
        reason = None
        if not admitted:
            reasons = sorted(
                {
                    event.quote_unsupported_reason or "unsupported_provider_state"
                    for event in provider_events
                    if not event.quote_supported
                }
            )
            reason = "|".join(reasons)
            unsupported_v4 += int(any(reason.startswith("v4_") for reason in reasons))
        first_leg, second_leg = tuple(selected.itertuples(index=False))
        first_event, second_event = provider_events
        rows.append(
            {
                **route,
                "day": day,
                "tx_hash": tx_hash,
                "target_order_block": order[0],
                "target_order_log_index": order[1],
                "target_timestamp": min(event.timestamp for event in provider_events),
                "realised_leg1_output": first_leg.amount_out,
                "realised_leg2_input": second_leg.amount_in,
                "target_admitted": admitted,
                "target_structural_rejection": reason,
                "vehicle_type": asset_type(str(route["vehicle"])),
                **_event_fields("leg1", first_event),
                **_event_fields("leg2", second_event),
            }
        )
    frame = pd.DataFrame(rows, columns=TARGET_LEDGER_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["target_order_block", "target_order_log_index", "route_id"],
            kind="stable",
        ).reset_index(drop=True)
        if frame["route_id"].duplicated().any():
            raise TargetEvidenceError("target ledger contains duplicate route ids")
    support = {
        "day": day,
        "all_exact_two_leg_routes": int(len(all_routes)),
        "exact_venue_two_leg_routes": int(len(exact_routes)),
        "provider_mapped_routes": int(len(frame)),
        "admitted_provider_targets": int(frame["target_admitted"].sum()) if not frame.empty else 0,
        "structurally_unsupported_targets": int((~frame["target_admitted"]).sum()) if not frame.empty else 0,
        "unsupported_v4_semantics_routes": unsupported_v4,
        "verified_chain_log_legs": verified_legs,
        "evidence_failures": 0,
        "evidence_scope": "fixed_calendar_chain_log_census" if chain_events is not None else "provider_derived",
    }
    if len(frame) != len(exact_routes):
        raise AssertionError("provider target ledger changed the exact-route population")
    return frame, support


def _parquet_schema_sha256(path: Path) -> str:
    return hashlib.sha256(str(pq.read_schema(path)).encode()).hexdigest()


def _json_record(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _validated_lineage(lineage: Mapping[str, str]) -> dict[str, str]:
    expected = {str(name): str(digest) for name, digest in sorted(lineage.items(), key=lambda item: str(item[0]))}
    for name, digest in expected.items():
        source = Path(name)
        source = source if source.is_absolute() else REPO_ROOT / source
        if not source.is_file() or _sha256(source) != digest:
            raise TargetEvidenceError(f"requested target day lineage is absent or stale: {name}")
    return expected


def _require_existing_day_matches(record: Mapping[str, object], frame: pd.DataFrame, support: Mapping[str, object], lineage: Mapping[str, str], marker: Path) -> None:
    shard = marker.parents[1] / str(record["shard"])
    try:
        pd.testing.assert_frame_equal(pd.read_parquet(shard).reset_index(drop=True), frame.reset_index(drop=True), check_dtype=True, check_like=False)
    except AssertionError as error:
        raise TargetEvidenceError(f"existing target day differs from the requested frame: {marker}") from error
    if record.get("support") != support:
        raise TargetEvidenceError(f"existing target day differs from the requested support: {marker}")
    if record.get("lineage") != lineage:
        raise TargetEvidenceError(f"existing target day differs from the requested lineage: {marker}")


def write_target_day(
    directory: Path,
    day: str,
    frame: pd.DataFrame,
    support: Mapping[str, object],
    *,
    scope: str,
    generation: str,
    lineage: Mapping[str, str],
) -> Path:
    """Install one immutable content-addressed shard, then its fixed day marker."""

    day = _normalise_day(day)
    _require_scope(scope)
    if str(support.get("day")) != day or int(support.get("provider_mapped_routes", -1)) != len(frame):
        raise ValueError("target day support does not reconcile to its shard")
    if "route_id" not in frame or frame["route_id"].duplicated().any():
        raise ValueError("target day frame must contain unique route ids")
    if scope == "audit" and int(support.get("evidence_failures", -1)) != 0:
        raise TargetEvidenceError("audit target day contains chain-evidence failures")
    marker = directory / "days" / f"{day}.json"
    expected_support = _json_record(dict(support))
    if not isinstance(expected_support, dict):
        raise AssertionError("target support normalization did not produce a record")
    with serialized_output_install(marker):
        expected_lineage = _validated_lineage(lineage)
        if marker.exists():
            record = validate_target_day(marker, scope=scope, generation=generation)
            _require_existing_day_matches(record, frame, expected_support, expected_lineage, marker)
            return marker
        staging = directory / "staging" / f"{day}.parquet"
        staging.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(staging) as temporary:
            frame.to_parquet(temporary, index=False)
        digest = _sha256(staging)
        shard = directory / "shards" / day / f"{digest}.parquet"
        shard.parent.mkdir(parents=True, exist_ok=True)
        if shard.exists():
            if _sha256(shard) != digest:
                raise TargetEvidenceError(f"content-addressed target collision: {shard}")
            staging.unlink()
        else:
            staging.replace(shard)
        body = {
            "schema_version": TARGET_DAY_SCHEMA_VERSION,
            "status": "complete",
            "scope": scope,
            "generation": generation,
            "day": day,
            "rows": len(frame),
            "route_key_count": int(frame["route_id"].nunique()) if not frame.empty else 0,
            "shard": str(shard.relative_to(directory)),
            "shard_sha256": digest,
            "schema_sha256": _parquet_schema_sha256(shard),
            "support": expected_support,
            "lineage": expected_lineage,
        }
        marker.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(marker) as temporary:
            temporary.write_text(json.dumps(body, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        record = validate_target_day(marker, scope=scope, generation=generation)
        _require_existing_day_matches(record, frame, expected_support, expected_lineage, marker)
    return marker


def validate_target_day(marker: Path, *, scope: str, generation: str) -> dict[str, object]:
    record = json.loads(marker.read_text(encoding="utf-8"))
    if (
        int(record.get("schema_version", -1)) != TARGET_DAY_SCHEMA_VERSION
        or record.get("status") != "complete"
        or record.get("scope") != _require_scope(scope)
        or record.get("generation") != generation
        or marker.stem != record.get("day")
    ):
        raise TargetEvidenceError(f"target day marker has stale identity: {marker}")
    shard = marker.parents[1] / str(record.get("shard") or "")
    if not shard.is_file() or _sha256(shard) != record.get("shard_sha256"):
        raise TargetEvidenceError(f"target day shard is absent or mutated: {marker}")
    if _parquet_schema_sha256(shard) != record.get("schema_sha256"):
        raise TargetEvidenceError(f"target day shard schema drifted: {marker}")
    frame = pd.read_parquet(shard, columns=["route_id"])
    if len(frame) != int(record.get("rows", -1)) or frame["route_id"].duplicated().any():
        raise TargetEvidenceError(f"target day route-key contract failed: {marker}")
    if frame["route_id"].nunique() != int(record.get("route_key_count", -1)):
        raise TargetEvidenceError(f"target day route-key count drifted: {marker}")
    support = record.get("support")
    if not isinstance(support, dict) or int(support.get("provider_mapped_routes", -1)) != len(frame):
        raise TargetEvidenceError(f"target day support drifted: {marker}")
    if scope == "audit" and int(support.get("evidence_failures", -1)) != 0:
        raise TargetEvidenceError(f"target audit day contains evidence failures: {marker}")
    lineage = record.get("lineage")
    if not isinstance(lineage, dict):
        raise TargetEvidenceError(f"target day lineage is absent: {marker}")
    for name, digest in lineage.items():
        source = Path(str(name))
        source = source if source.is_absolute() else REPO_ROOT / source
        if not source.is_file() or _sha256(source) != digest:
            raise TargetEvidenceError(f"target day lineage is absent or stale: {name}")
    return record


def read_target_day(release: TargetRelease, day: str) -> tuple[pd.DataFrame, dict[str, object]]:
    normalized = _normalise_day(day)
    try:
        marker = release.day_markers[release.calendar.index(normalized)]
    except ValueError as error:
        raise FileNotFoundError(f"target release lacks day {normalized}") from error
    record = validate_target_day(marker, scope=release.scope, generation=release.generation)
    shard = marker.parents[1] / str(record["shard"])
    return pd.read_parquet(shard), dict(record["support"])


def publish_target_release(
    directory: Path,
    day_markers: Iterable[Path],
    *,
    scope: str,
    generation: str,
    validation: Mapping[str, object],
    full_calendar: Iterable[str],
    code_sources: list[str],
    inputs: list[Path],
    root: Path = TARGET_RELEASE_ROOT,
) -> TargetRelease:
    scope = _require_scope(scope)
    expected_directory = target_generation_root(generation, root=root)
    if directory.resolve() != expected_directory.resolve():
        raise ValueError("target day generation is outside the requested release root")
    markers = tuple(sorted(day_markers, key=lambda path: path.stem))
    if not markers:
        raise ValueError("target release requires at least one day marker")
    records = [validate_target_day(path, scope=scope, generation=generation) for path in markers]
    calendar = [str(record["day"]) for record in records]
    if calendar != sorted(set(calendar)):
        raise TargetEvidenceError("target release calendar is not unique and ordered")
    if scope == "audit":
        verified = sum(int(record["support"]["verified_chain_log_legs"]) for record in records)
        failures = sum(int(record["support"]["evidence_failures"]) for record in records)
        expected_validation = validation_contract(
            verified_legs=verified,
            evidence_failures=failures,
            audit_calendar=calendar,
            full_calendar=full_calendar,
        )
        if dict(validation) != expected_validation:
            raise TargetEvidenceError("audit release validation statistics do not reconcile")
    else:
        daily_calendar = tuple(_normalise_day(day) for day in full_calendar)
        if calendar != list(daily_calendar):
            raise TargetEvidenceError("daily target release differs from the current full calendar")
        if (
            bool(validation.get("full_history_chain_log_anchored"))
            or int(validation.get("full_daily_dates", -1)) != len(calendar)
            or validation.get("full_daily_calendar_sha256") != calendar_sha256(calendar)
        ):
            raise TargetEvidenceError("provider-derived daily release overclaims or misstates its calendar")
    missing_inputs = [str(path) for path in inputs if not path.is_file()]
    if missing_inputs:
        raise FileNotFoundError(f"target release inputs are absent: {missing_inputs}")
    body = {
        "schema_version": TARGET_RELEASE_SCHEMA_VERSION,
        "status": "complete",
        "scope": scope,
        "generation": generation,
        "calendar": calendar,
        "days": [
            {
                "day": record["day"],
                "marker": str(marker.relative_to(directory)),
                "marker_sha256": _sha256(marker),
                "rows": record["rows"],
            }
            for marker, record in zip(markers, records, strict=True)
        ],
        "validation": dict(validation),
        "code_fingerprint": code_fingerprint(code_sources),
        "input_lineage": {str(path): _sha256(path) for path in sorted(inputs, key=str)},
    }
    root_digest = _json_sha256(body)
    manifest_record = {**body, "root_sha256": root_digest}

    def write_manifest(path: Path) -> None:
        path.write_text(json.dumps(manifest_record, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

    def validate_manifest(paths: Mapping[str, Path]) -> None:
        observed = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        if observed != manifest_record:
            raise TargetEvidenceError("transaction-target release manifest changed during publication")

    publish_artifact_release(
        pointer_path=target_current_pointer(scope, root=root),
        kind=_target_release_kind(scope),
        schema_version=TARGET_RELEASE_SCHEMA_VERSION,
        filenames={"manifest": TARGET_RELEASE_MANIFEST_FILENAME},
        writers={"manifest": write_manifest},
        row_counts={"manifest": sum(int(record["rows"]) for record in records)},
        code_sources=code_sources,
        inputs=[*inputs, *markers],
        notes=f"{scope} transaction target release with immutable day shards",
        validate_staged=validate_manifest,
    )
    return resolve_target_release(scope, expected_days=calendar, root=root)


def resolve_target_release(
    scope: str,
    *,
    expected_days: Iterable[str] | None = None,
    root: Path = TARGET_RELEASE_ROOT,
) -> TargetRelease:
    scope = _require_scope(scope)
    pointer = target_current_pointer(scope, root=root)
    if not pointer.is_file():
        raise FileNotFoundError(f"missing {scope} transaction-target current pointer")
    try:
        selected = resolve_artifact_release(pointer, kind=_target_release_kind(scope), schema_version=TARGET_RELEASE_SCHEMA_VERSION, filenames={"manifest": TARGET_RELEASE_MANIFEST_FILENAME}, require_current_provenance=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise TargetEvidenceError(f"{scope} transaction-target pointer is stale") from error
    manifest = selected.artifacts["manifest"]
    record = json.loads(manifest.read_text(encoding="utf-8"))
    generation = str(record.get("generation") or "")
    body = {key: value for key, value in record.items() if key != "root_sha256"}
    if (
        int(record.get("schema_version", -1)) != TARGET_RELEASE_SCHEMA_VERSION
        or record.get("status") != "complete"
        or record.get("scope") != scope
        or _json_sha256(body) != record.get("root_sha256")
    ):
        raise TargetEvidenceError(f"{scope} transaction-target manifest is stale")
    calendar = tuple(str(day) for day in record.get("calendar") or [])
    if calendar != tuple(sorted(set(calendar))):
        raise TargetEvidenceError(f"{scope} transaction-target calendar is malformed")
    if expected_days is not None:
        expected = tuple(sorted(_normalise_day(day) for day in expected_days))
        if calendar != expected:
            raise TargetEvidenceError(f"{scope} transaction-target calendar differs from the requested release")
    entries = record.get("days")
    if not isinstance(entries, list) or len(entries) != len(calendar):
        raise TargetEvidenceError(f"{scope} transaction-target day manifest is malformed")
    directory = target_generation_root(generation, root=root)
    if not directory.is_dir():
        raise TargetEvidenceError(f"{scope} transaction-target day generation is absent")
    markers: list[Path] = []
    for day, entry in zip(calendar, entries, strict=True):
        marker = directory / str(entry.get("marker") or "")
        if entry.get("day") != day or not marker.is_file() or _sha256(marker) != entry.get("marker_sha256"):
            raise TargetEvidenceError(f"{scope} transaction-target day marker drifted: {day}")
        validate_target_day(marker, scope=scope, generation=generation)
        markers.append(marker)
    validation = record.get("validation")
    if not isinstance(validation, dict):
        raise TargetEvidenceError(f"{scope} transaction-target validation contract is absent")
    if scope == "audit" and (
        int(validation.get("evidence_failures", -1)) != 0
        or bool(validation.get("full_history_chain_log_anchored"))
        or int(validation.get("validation_dates", -1)) != len(calendar)
        or validation.get("validation_calendar_sha256") != calendar_sha256(calendar)
        or int(validation.get("full_daily_dates", -1)) < len(calendar)
    ):
        raise TargetEvidenceError("audit transaction-target validation contract is false")
    if scope == "audit":
        expected_share = len(calendar) / int(validation["full_daily_dates"])
        if float(validation.get("day_coverage_share", -1.0)) != expected_share:
            raise TargetEvidenceError("audit transaction-target day coverage is stale")
    if scope == "daily" and (
        bool(validation.get("full_history_chain_log_anchored"))
        or int(validation.get("full_daily_dates", -1)) != len(calendar)
        or validation.get("full_daily_calendar_sha256") != calendar_sha256(calendar)
    ):
        raise TargetEvidenceError("daily provider target release overclaims or misstates chain-log coverage")
    return TargetRelease(
        scope,
        generation,
        pointer,
        manifest,
        tuple(markers),
        calendar,
        validation,
    )


def validate_v4_exact_log_chunk(
    raw_path: Path,
    marker_path: Path,
    *,
    start_block: int,
    end_block: int,
    frozen_upper: Mapping[str, object],
) -> list[dict[str, object]]:
    """Reopen one PoolManager-only exact-log chunk and its transport evidence."""

    if not raw_path.is_file() or not marker_path.is_file():
        raise FileNotFoundError(f"incomplete V4 target-log chunk: {start_block}:{end_block}")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    records = pq.read_table(raw_path).to_pylist()
    validate_canonical_log_records(
        records,
        start_block=start_block,
        end_block=end_block,
        topics=[UNISWAP_V4_SWAP_TOPIC],
        address=UNISWAP_V4_POOL_MANAGER_ADDRESS,
    )
    validate_anchored_log_evidence(marker, records, dict(frozen_upper))
    if (
        marker.get("status") != "complete"
        or marker.get("kind") != "uniswap_v4_poolmanager_target_swaps"
        or int(marker.get("start_block", -1)) != start_block
        or int(marker.get("end_block", -1)) != end_block
        or marker.get("address_filter") != UNISWAP_V4_POOL_MANAGER_ADDRESS
        or marker.get("event_topics") != [UNISWAP_V4_SWAP_TOPIC]
        or marker.get("raw_sha256") != file_sha256(raw_path)
        or pq.read_schema(raw_path) != RAW_LOG_SCHEMA
    ):
        raise TargetEvidenceError("V4 target-log marker is stale")
    return records

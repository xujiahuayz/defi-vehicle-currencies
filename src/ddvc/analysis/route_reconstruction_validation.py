"""Exact-chain correction-ledger consequences for reconstructed routes.

The canonical route panel is built from provider swap rows.  For venue-days
with full-day Ethereum-log reconciliation, this module reruns the identical
route engine after applying the independently verified correction ledger.  It
keeps the exercise deliberately bounded: the results validate the audited
venue-days and do not stand in for transaction-trace validation of the full
sample.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from functools import cache
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.vehicle_rotation_composition import vehicle_rotation_composition
from ddvc.asset_types import asset_type
from ddvc.endpoint_candidate_composition import (
    EndpointCandidateComposition,
    endpoint_candidate_composition_for_day,
)
from ddvc.graph_event_order import (
    CORE_STREAMS,
    correction_root_for_graph,
    file_sha256,
    load_event_order_corrections,
    load_event_order_metadata,
)
from ddvc.reconstruct import (
    DEX_FAMILY,
    NORMALISERS,
    load_legs,
    read_unified_quality,
    reconstruct_day_with_quality,
)
from ddvc.route_roles import component_eligibility
from ddvc.source_records import block_value, transaction_id
from ddvc.v2_event_contract import V2_RECONCILIATION_SCOPE


AUDITED_VENUES = ("uniswap_v2", "sushiswap_v2", "uniswap_v3")
FULL_DAY_SCOPES = {
    "uniswap_v2": V2_RECONCILIATION_SCOPE,
    "sushiswap_v2": V2_RECONCILIATION_SCOPE,
    "uniswap_v3": "full_utc_day_analysis_cutoff_factory_pool_perimeter",
}
EVENT_RELEASES = {
    "v2_core_event_source_release": "v2_event_source_release",
    "v3_core_event_source_release": "v3_event_source_release",
}
DECOMPOSITION_COMPONENTS = (
    "total_change",
    "within_common",
    "common_pair_reweighting",
    "common_support_mass",
    "exclusive_pair_contribution",
)


def _release_certificate(data_root: Path, release: str) -> dict[str, object]:
    """Open the certificate named by one current event-source release."""

    root = data_root / "processed" / release
    pointer_path = root / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    generation_id = str(pointer.get("generation_id") or "")
    certificate_record = (pointer.get("artifacts") or {}).get("certificate") or {}
    filename = str(certificate_record.get("filename") or "")
    expected_sha256 = str(certificate_record.get("sha256") or "")
    certificate_path = root / "generations" / generation_id / filename
    if (
        pointer.get("schema_version") != 1
        or pointer.get("kind") != EVENT_RELEASES[release]
        or len(generation_id) != 64
        or not filename
        or len(expected_sha256) != 64
        or not certificate_path.is_file()
        or file_sha256(certificate_path) != expected_sha256
    ):
        raise ValueError(f"invalid current event-source release: {release}")
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    if certificate.get("status") != "pass":
        raise ValueError(f"incomplete current event-source release: {release}")
    return certificate


@cache
def _released_generation_index(
    data_root_text: str,
) -> dict[str, dict[str, str]]:
    """Map venue-days to correction generations bound by current releases."""

    data_root = Path(data_root_text)
    index: dict[str, dict[str, str]] = {venue: {} for venue in AUDITED_VENUES}
    v2 = _release_certificate(data_root, "v2_core_event_source_release")
    v2_generations = v2.get("correction_generations") or {}
    if not isinstance(v2_generations, dict):
        raise ValueError("invalid V2 correction-generation release index")
    for key, record in v2_generations.items():
        try:
            venue, day = str(key).split("/", 1)
            generation_id = str(record["generation_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid V2 correction-generation release row") from error
        if (
            venue not in {"uniswap_v2", "sushiswap_v2"}
            or len(day) != 8
            or not day.isdigit()
            or len(generation_id) != 64
            or day in index[venue]
        ):
            raise ValueError("invalid V2 correction-generation release row")
        index[venue][day] = generation_id

    v3 = _release_certificate(data_root, "v3_core_event_source_release")
    v3_generations = v3.get("correction_generations") or {}
    if not isinstance(v3_generations, dict):
        raise ValueError("invalid V3 correction-generation release index")
    for day, record in v3_generations.items():
        day = str(day)
        try:
            generation_id = str(record["generation_id"])
        except (KeyError, TypeError) as error:
            raise ValueError("invalid V3 correction-generation release row") from error
        if (
            len(day) != 8
            or not day.isdigit()
            or len(generation_id) != 64
            or day in index["uniswap_v3"]
        ):
            raise ValueError("invalid V3 correction-generation release row")
        index["uniswap_v3"][day] = generation_id
    if any(not index[venue] for venue in AUDITED_VENUES):
        raise ValueError("current event-source releases have incomplete venue coverage")
    return index


def released_audit_generations(raw_root: Path) -> dict[str, dict[str, str]]:
    """Return a copy of the current release-bound correction index."""

    data_root = raw_root.parent.parent.resolve()
    return {
        venue: dict(days)
        for venue, days in _released_generation_index(str(data_root)).items()
    }


def _package(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[Path, Path, dict[str, object]] | None:
    """Return one release-bound full-day correction package, when present."""

    released_generation = released_audit_generations(raw_root)[venue].get(day)
    if released_generation is None:
        return None

    package = load_event_order_metadata(raw_root, venue, day)
    if package is None:
        raise RuntimeError(f"released correction package is absent: {venue}/{day}")
    _actions, _metadata, description = package
    if (
        description.get("scope") != FULL_DAY_SCOPES[venue]
        or description.get("generation_id") != released_generation
    ):
        raise ValueError(f"released correction package is stale: {venue}/{day}")
    return package


def full_day_audit_days(raw_root: Path) -> dict[str, tuple[str, ...]]:
    """Resolve full-day correction coverage from current certified releases."""

    released = released_audit_generations(raw_root)
    output: dict[str, tuple[str, ...]] = {}
    for venue in AUDITED_VENUES:
        days = []
        for day in sorted(released[venue]):
            if _package(raw_root, venue, day) is None:
                raise RuntimeError(f"released correction package is absent: {venue}/{day}")
            days.append(day)
        output[venue] = tuple(days)
    return output


def _auxiliary_full_day_packages(raw_root: Path) -> list[tuple[str, str]]:
    """List full-scope pointers that are outside the current releases."""

    released = released_audit_generations(raw_root)
    correction_root = correction_root_for_graph(raw_root)
    auxiliary: list[tuple[str, str]] = []
    for venue in AUDITED_VENUES:
        for pointer in sorted((correction_root / venue).glob("*.current.json")):
            day = pointer.name.split(".", 1)[0]
            if day in released[venue]:
                continue
            package = load_event_order_metadata(raw_root, venue, day)
            if package is not None and package[2].get("scope") == FULL_DAY_SCOPES[venue]:
                auxiliary.append((venue, day))
    return auxiliary


def summarize_release_boundary(data_root: Path) -> dict[str, object]:
    """Quantify auxiliary corrections excluded by the release gate.

    A historical auxiliary package can cover a narrower pool perimeter even
    when its scope label matches a later release.  We keep those packages out
    and count any corrected log positions that would collide with another
    provider-ordered route leg.
    """

    raw_root = data_root / "raw" / "thegraph"
    packages = _auxiliary_full_day_packages(raw_root)
    actions_by_day: dict[str, list[dict]] = defaultdict(list)
    action_venue_days = 0
    for venue, day in packages:
        actions = [
            row
            for row in correction_action_rows_unreleased(raw_root, venue, day)
            if row.get("stream") == "swaps"
        ]
        if actions:
            action_venue_days += 1
            actions_by_day[day].extend(actions)

    touched_transactions: set[tuple[str, str]] = set()
    conflict_transactions: set[tuple[str, str]] = set()
    conflict_route_legs = 0
    conflict_routes = 0
    for day, actions in sorted(actions_by_day.items()):
        iso_day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        frame = pd.read_parquet(data_root / "unified" / f"{day}.parquet")
        action_by_provider_key: dict[tuple[str, str, int], dict] = {}
        supplements: list[dict] = []
        for action in actions:
            tx = str(action.get("tx_hash") or "").lower()
            venue = str(action.get("venue") or "")
            touched_transactions.add((iso_day, tx))
            if action.get("action") == "supplement":
                supplements.append(action)
                continue
            provider_log = int(action.get("provider_log_index", -1))
            key = (tx, venue, provider_log)
            if key in action_by_provider_key:
                raise ValueError(f"duplicate auxiliary swap action: {day}/{key}")
            action_by_provider_key[key] = action

        final_keys: dict[tuple[str, int], list[bool]] = defaultdict(list)
        for row in frame.itertuples(index=False):
            tx = str(row.tx_hash)
            action = action_by_provider_key.get(
                (tx, str(row.source), int(row.log_index))
            )
            if action is not None and action.get("action") == "exclusion":
                continue
            log_index = int(
                action.get("chain_log_index")
                if action is not None
                else row.log_index
            )
            final_keys[(tx, log_index)].append(action is not None)
        for action in supplements:
            final_keys[
                (
                    str(action.get("tx_hash") or "").lower(),
                    int(action["chain_log_index"]),
                )
            ].append(True)
        day_conflicts = {
            tx
            for (tx, _log_index), action_flags in final_keys.items()
            if len(action_flags) > 1 and any(action_flags)
        }
        conflict_transactions.update((iso_day, tx) for tx in day_conflicts)
        affected_frame = frame[frame["tx_hash"].isin(day_conflicts)]
        conflict_route_legs += len(affected_frame)
        conflict_routes += affected_frame[["tx_hash", "component_id"]].drop_duplicates().shape[0]
    return {
        "auxiliary_full_scope_venue_days": len(packages),
        "auxiliary_swap_action_venue_days": action_venue_days,
        "auxiliary_swap_actions": sum(len(rows) for rows in actions_by_day.values()),
        "auxiliary_action_transactions": len(touched_transactions),
        "auxiliary_key_conflict_transactions": len(conflict_transactions),
        "auxiliary_key_conflict_route_legs": conflict_route_legs,
        "auxiliary_key_conflict_routes": conflict_routes,
    }


def correction_action_rows(raw_root: Path, venue: str, day: str) -> list[dict]:
    """Read actions only after the package passes the full-day metadata gate."""

    package = _package(raw_root, venue, day)
    if package is None:
        return []
    return _read_action_rows(package[0])


def _read_action_rows(action_path: Path) -> list[dict]:
    """Read one already validated correction action file."""

    with gzip.open(action_path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def correction_action_rows_unreleased(
    raw_root: Path,
    venue: str,
    day: str,
) -> list[dict]:
    """Read one auxiliary full-scope package for boundary accounting only."""

    package = load_event_order_metadata(raw_root, venue, day)
    if package is None or package[2].get("scope") != FULL_DAY_SCOPES[venue]:
        return []
    action_path, _metadata_path, _metadata = package
    return _read_action_rows(action_path)


def _provider_rows(path: Path) -> Iterable[dict]:
    if not path.is_file():
        return
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _normalise_corrected_swaps(
    venue: str,
    rows: Iterable[dict | None],
    *,
    counters: dict[str, int] | None,
) -> list[dict]:
    """Apply the canonical identity/order gates to corrected provider-shaped rows."""

    family = DEX_FAMILY[venue]
    normaliser = NORMALISERS[family]
    legs: list[dict] = []
    for row in rows:
        if row is None:
            continue
        leg = normaliser(row)
        if not (
            leg
            and leg["tx"]
            and leg["tin"]
            and leg["tout"]
            and leg["tin_id"]
            and leg["tout_id"]
            and leg["pool"]
        ):
            if counters is not None:
                counters["missing_identity"] += 1
            continue
        if leg["block"] <= 0 or leg["ts"] <= 0 or leg["log"] < 0:
            if counters is not None:
                counters["missing_order"] += 1
            continue
        leg["tx"] = str(leg["tx"]).lower()
        leg["tin_id"] = str(leg["tin_id"]).lower()
        leg["tout_id"] = str(leg["tout_id"]).lower()
        leg["dex"] = venue
        legs.append(leg)
        if counters is not None:
            counters["normalised_rows"] += 1
    return legs


def load_exact_chain_corrected_legs(
    venue: str,
    day: str,
    *,
    data_root: Path | None = None,
    counters: dict[str, int] | None = None,
) -> list[dict]:
    """Load route legs after full-day exact-chain corrections where available.

    The signature matches :func:`ddvc.reconstruct.load_legs`, allowing the
    canonical reconstruction engine to be reused without a second route
    algorithm.
    """

    if data_root is None or venue not in AUDITED_VENUES:
        return load_legs(venue, day, data_root=data_root, counters=counters)
    stamp = day.replace("-", "")
    raw_root = data_root / "raw" / "thegraph"
    if _package(raw_root, venue, stamp) is None:
        return load_legs(venue, day, data_root=data_root, counters=counters)
    actions = correction_action_rows(raw_root, venue, stamp)
    if not any(row.get("stream") == "swaps" for row in actions):
        return load_legs(venue, day, data_root=data_root, counters=counters)

    corrections, _inputs = load_event_order_corrections(raw_root, venue, stamp)
    if corrections is None:
        raise RuntimeError(f"full-day correction package did not load: {venue}/{stamp}")
    corrected_swaps: Iterable[dict | None] | None = None
    for stream in CORE_STREAMS:
        path = raw_root / venue / f"{venue}_{stream}_{stamp}.jsonl.gz"

        def rows_with_count() -> Iterable[dict]:
            for row in _provider_rows(path):
                if counters is not None and stream == "swaps":
                    counters["raw_rows"] += 1
                yield row

        reconciled = corrections.reconciled_rows(venue, stream, rows_with_count())
        if stream == "swaps":
            corrected_swaps = list(reconciled)
        else:
            for _row in reconciled:
                pass
    corrections.require_fully_applied()
    if corrected_swaps is None:
        raise RuntimeError(f"swap stream was not reconciled: {venue}/{stamp}")
    return _normalise_corrected_swaps(
        venue,
        corrected_swaps,
        counters=counters,
    )


def swap_action_transactions(raw_root: Path, day: str) -> set[str]:
    """Transactions touched by any full-day swap correction on one date."""

    return {
        str(row.get("tx_hash") or "").lower()
        for venue in AUDITED_VENUES
        for row in correction_action_rows(raw_root, venue, day)
        if row.get("stream") == "swaps" and row.get("tx_hash")
    }


def _component_signatures(frame: pd.DataFrame) -> dict[str, dict[str, tuple]]:
    """Summarize each transaction without relying on unstable component numbers."""

    dimensions: dict[str, dict[str, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    if frame.empty:
        return {}
    eligibility = component_eligibility(frame)
    keys = ["tx_hash", "component_id"]
    legs = frame.groupby(keys, as_index=False).agg(leg_count=("log_index", "size"))
    intermediaries = eligibility.token_roles[
        eligibility.token_roles["role"].eq("intermediate")
    ]
    intermediary_groups = {
        key: tuple(sorted(group["token"].astype(str)))
        for key, group in intermediaries.groupby(keys, sort=False)
    }
    endpoint_rows = eligibility.eligible.merge(legs, on=keys, how="left")
    for row in endpoint_rows.itertuples(index=False):
        key = (str(row.tx_hash), int(row.component_id))
        tokens = intermediary_groups.get(key, ())
        tx = str(row.tx_hash)
        dimensions[tx]["endpoint_pair"].append((str(row.src), str(row.tgt)))
        dimensions[tx]["intermediary_identity"].append(tokens)
        dimensions[tx]["vehicle_class"].append(
            tuple(sorted(asset_type(token) for token in tokens))
        )
        dimensions[tx]["leg_count"].append(int(row.leg_count))
    return {
        tx: {name: tuple(sorted(values)) for name, values in values_by_name.items()}
        for tx, values_by_name in dimensions.items()
    }


def transaction_signatures(
    frame: pd.DataFrame,
    day: str,
) -> dict[str, dict[str, tuple]]:
    """Return endpoint, vehicle, leg-count, and exact-two-leg assignments."""

    signatures = _component_signatures(frame)
    choices = endpoint_candidate_composition_for_day(
        frame, day.replace("-", "")
    ).choice_audit
    exact: dict[str, list[tuple]] = defaultdict(list)
    if not choices.empty:
        for row in choices.itertuples(index=False):
            exact[str(row.tx_hash)].append(
                (
                    str(row.src),
                    str(row.tgt),
                    str(row.candidate_address),
                    str(row.candidate_type),
                    str(row.integration_scope),
                )
            )
    for tx in set(signatures) | set(exact):
        signatures.setdefault(tx, {})["exact_two_leg_inclusion"] = tuple(
            sorted(exact.get(tx, []))
        )
    return signatures


def compare_transaction_assignments(
    raw: pd.DataFrame,
    corrected: pd.DataFrame,
    *,
    day: str,
    affected_transactions: set[str],
) -> list[dict[str, object]]:
    """Compare route assignments only where a swap action can change them."""

    dimensions = (
        "endpoint_pair",
        "intermediary_identity",
        "vehicle_class",
        "leg_count",
        "exact_two_leg_inclusion",
    )
    raw_subset = raw[raw["tx_hash"].isin(affected_transactions)].copy()
    corrected_subset = corrected[
        corrected["tx_hash"].isin(affected_transactions)
    ].copy()
    linked = set(raw_subset["tx_hash"].astype(str)) | set(
        corrected_subset["tx_hash"].astype(str)
    )
    raw_signatures = transaction_signatures(raw_subset, day)
    corrected_signatures = transaction_signatures(corrected_subset, day)
    rows = []
    for dimension in dimensions:
        unchanged = sum(
            raw_signatures.get(tx, {}).get(dimension, ())
            == corrected_signatures.get(tx, {}).get(dimension, ())
            for tx in linked
        )
        rows.append(
            {
                "dimension": dimension,
                "affected_transactions": len(affected_transactions),
                "linked_transactions": len(linked),
                "unchanged_transactions": unchanged,
                "changed_transactions": len(linked) - unchanged,
                "unchanged_share": unchanged / len(linked) if linked else np.nan,
            }
        )
    return rows


def choice_mass(
    bundle: EndpointCandidateComposition | pd.DataFrame,
) -> dict[str, float]:
    """Native/stable route and supported-value mass for one daily bundle."""

    choices = bundle if isinstance(bundle, pd.DataFrame) else bundle.choices
    selected = choices[choices["candidate_type"].isin(("native", "stable"))]
    return {
        "route_count_total": float(selected["route_count"].sum()),
        "route_count_stable": float(
            selected.loc[selected["candidate_type"].eq("stable"), "route_count"].sum()
        ),
        "within_20pct_value_usd_total": float(
            selected["within_20pct_value_usd"].sum()
        ),
        "within_20pct_value_usd_stable": float(
            selected.loc[
                selected["candidate_type"].eq("stable"),
                "within_20pct_value_usd",
            ].sum()
        ),
    }


def stable_share_rows(
    raw_masses: Iterable[dict[str, float]],
    corrected_masses: Iterable[dict[str, float]],
    *,
    dates: int,
) -> list[dict[str, object]]:
    """Aggregate stable shares on the exact reconstructed validation dates."""

    raw = pd.DataFrame(raw_masses).sum(numeric_only=True)
    corrected = pd.DataFrame(corrected_masses).sum(numeric_only=True)
    rows = []
    for metric, prefix in (
        ("route_count", "route_count"),
        ("within_20pct_value_usd", "within_20pct_value_usd"),
    ):
        raw_total = float(raw[f"{prefix}_total"])
        corrected_total = float(corrected[f"{prefix}_total"])
        raw_share = float(raw[f"{prefix}_stable"]) / raw_total
        corrected_share = float(corrected[f"{prefix}_stable"]) / corrected_total
        rows.append(
            {
                "metric": metric,
                "dates": dates,
                "raw_mass": raw_total,
                "corrected_mass": corrected_total,
                "raw_stable_share": raw_share,
                "corrected_stable_share": corrected_share,
                "difference_pp": 100.0 * (corrected_share - raw_share),
            }
        )
    return rows


def summarize_event_reconciliation(raw_root: Path) -> list[dict[str, object]]:
    """Summarize swap precision and recall from full-day correction packages."""

    coverage = full_day_audit_days(raw_root)
    rows: list[dict[str, object]] = []
    for venue in AUDITED_VENUES:
        provider_swaps = 0
        action_counts = defaultdict(int)
        for day in coverage[venue]:
            # This call verifies every declared provider, chain, timestamp,
            # receipt, and registry input before its action counts enter the
            # appendix result.
            corrections, _inputs = load_event_order_corrections(
                raw_root, venue, day
            )
            if corrections is None:
                raise RuntimeError(f"full-day package failed to load: {venue}/{day}")
            swap_path = raw_root / venue / f"{venue}_swaps_{day}.jsonl.gz"
            provider_swaps += sum(1 for _row in _provider_rows(swap_path))
            for action in correction_action_rows(raw_root, venue, day):
                if action.get("stream") == "swaps":
                    action_counts[str(action.get("action"))] += 1
        false_provider = int(action_counts["exclusion"])
        missed_provider = int(action_counts["supplement"])
        true_provider = provider_swaps - false_provider
        rows.append(
            {
                "venue": venue,
                "audited_days": len(coverage[venue]),
                "provider_swaps": provider_swaps,
                "corrected_provider_swaps": int(action_counts["correction"]),
                "provider_only_swaps": false_provider,
                "chain_only_swaps": missed_provider,
                "precision": true_provider / provider_swaps,
                "recall": true_provider / (true_provider + missed_provider),
            }
        )
    return rows


def validate_route_day(
    data_root_text: str,
    day: str,
) -> dict[str, object]:
    """Rerun one affected date and return compact route consequences."""

    data_root = Path(data_root_text)
    raw_root = data_root / "raw" / "thegraph"
    affected = swap_action_transactions(raw_root, day.replace("-", ""))
    if not affected:
        raise ValueError(f"route validation date has no swap actions: {day}")
    dexes = list(DEX_FAMILY)
    unified_root = data_root / "unified"
    raw_quality = read_unified_quality(
        day,
        dexes,
        data_root=data_root,
        unified_root=unified_root,
    )
    if raw_quality is None:
        raise ValueError(f"canonical provider-row route day is stale: {day}")
    raw = pd.read_parquet(unified_root / f"{day.replace('-', '')}.parquet")
    corrected, corrected_quality = reconstruct_day_with_quality(
        day,
        dexes,
        data_root=data_root,
        leg_loader=load_exact_chain_corrected_legs,
    )
    if not raw_quality["passed"] or not corrected_quality["passed"]:
        raise ValueError(
            f"route reconstruction quality failed on {day}: "
            f"raw={raw_quality}; corrected={corrected_quality}"
        )
    stamp = day.replace("-", "")
    choices_path = data_root / "processed" / "endpoint_candidate_choices.parquet"
    raw_choices = pd.read_parquet(
        choices_path,
        filters=[("date", "==", pd.Timestamp(day))],
    )
    if raw_choices.empty:
        raise ValueError(f"released provider-row choices are empty: {day}")
    corrected_bundle = endpoint_candidate_composition_for_day(corrected, stamp)
    assignments = compare_transaction_assignments(
        raw,
        corrected,
        day=day,
        affected_transactions=affected,
    )
    retain_choices = day[:4] in {"2024", "2026"} and day[5:7] <= "06"
    return {
        "day": day,
        "assignments": assignments,
        "raw_mass": choice_mass(raw_choices),
        "corrected_mass": choice_mass(corrected_bundle),
        "raw_choices": raw_choices if retain_choices else None,
        "corrected_choices": corrected_bundle.choices if retain_choices else None,
        "raw_rows": len(raw),
        "corrected_rows": len(corrected),
        "affected_transactions": len(affected),
    }


def decomposition_consequence_rows(
    raw_choices: pd.DataFrame,
    corrected_choices: pd.DataFrame,
) -> list[dict[str, object]]:
    """Compare the sampled 2024--2026 decomposition before and after correction."""

    raw = vehicle_rotation_composition(
        raw_choices,
        reporting_scopes=("pooled",),
    )[1]
    corrected = vehicle_rotation_composition(
        corrected_choices,
        reporting_scopes=("pooled",),
    )[1]
    rows: list[dict[str, object]] = []
    for metric in ("count_share", "strict_intermediation_value_share"):
        raw_row = raw[
            raw["metric"].eq(metric) & raw["reporting_scope"].eq("pooled")
        ].iloc[0]
        corrected_row = corrected[
            corrected["metric"].eq(metric)
            & corrected["reporting_scope"].eq("pooled")
        ].iloc[0]
        for component in DECOMPOSITION_COMPONENTS:
            raw_pp = 100.0 * float(raw_row[component])
            corrected_pp = 100.0 * float(corrected_row[component])
            rows.append(
                {
                    "metric": metric,
                    "component": component,
                    "common_month_days": int(raw_row["common_month_days"]),
                    "raw_pp": raw_pp,
                    "corrected_pp": corrected_pp,
                    "difference_pp": corrected_pp - raw_pp,
                }
            )
    return rows

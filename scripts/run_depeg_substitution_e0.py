#!/usr/bin/env python3
"""Run the provisional count-only UST and USDC substitution experiment.

This owner consumes only the released directed-route layer.  Its outputs remain
under ``output/provisional`` and cannot enter the paper or deck while the claim
gate is red.  The package never reads token amounts or dollar values.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd

from ddvc.analysis.depeg_substitution_e0 import (
    CLAIM_GATE,
    EVENTS,
    HOURLY_COLUMNS,
    INPUT_COLUMNS,
    PROMOTION_ELIGIBLE,
    STATUS,
    aggregate_hourly_routes,
    extract_count_routes,
    required_days,
    run_event_family,
)
from ddvc.artifact_release import canonical_json_sha256, file_sha256, file_stat_identity
from ddvc.data_release import (
    ReleasedPartition,
    ReleasedPartitionSet,
    release_preinstall_validator,
    released_route_partitions,
)
from ddvc.paths import REPO_ROOT
from ddvc.provenance import current_artifacts
from ddvc.reconstruct import UNIFIED_COLUMNS, UNIFIED_QUALITY_PANEL, unified_path, unified_quality_path
from ddvc.tables import read_exhibit, write_exhibit, write_panel


OUTPUT_ROOT = REPO_ROOT / "output" / "provisional"
SUMMARY = OUTPUT_ROOT / "depeg_substitution_e0.jsonl"
PANEL = OUTPUT_ROOT / "depeg_substitution_e0_hourly.parquet"
MANIFEST = OUTPUT_ROOT / "depeg_substitution_e0_manifest.jsonl"
INPUT_RECEIPT = OUTPUT_ROOT / "depeg_substitution_e0_input_receipt.jsonl"
SCRIPT_VERSION = "depeg_substitution_e0.v4"
CODE_SOURCES = [
    "scripts/run_depeg_substitution_e0.py",
    "src/ddvc/analysis/depeg_substitution_e0.py",
    "src/ddvc/artifact_release.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/data_release.py",
    "src/ddvc/paths.py",
    "src/ddvc/provenance.py",
    "src/ddvc/reconstruct/__init__.py",
    "src/ddvc/route_roles.py",
]


def _record_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def input_receipt_frame(
    release: ReleasedPartitionSet,
    *,
    input_release_status: str,
) -> pd.DataFrame:
    """Materialize the exact ledger, partition, and marker identities consumed."""

    return pd.DataFrame(
        [
            {
                "receipt_version": "depeg-substitution-e0-input-receipt-v1",
                "input_release_status": input_release_status,
                "input_identity_sha256": release.content_identity_sha256,
                "release_kind": release.kind,
                "selected_columns": "|".join(release.columns),
                "release_ledger_path": _record_path(release.ledger_path),
                "release_ledger_sha256": release.ledger_sha256,
                "partition_count": len(release.partitions),
                "partition_index": index,
                "day": partition.day,
                "partition_path": _record_path(partition.path),
                "partition_rows": partition.expected_rows,
                "partition_bytes": partition.expected_bytes,
                "partition_sha256": partition.expected_sha256,
                "marker_path": _record_path(partition.marker_path),
                "marker_sha256": partition.marker_sha256,
                "input_fingerprint": partition.input_fingerprint,
            }
            for index, partition in enumerate(release.partitions)
        ]
    )


def verify_input_receipt(receipt: pd.DataFrame, release: ReleasedPartitionSet) -> None:
    """Reject any receipt, partition, marker, or release-ledger identity drift."""

    release.assert_current()
    expected = input_receipt_frame(
        release,
        input_release_status=str(receipt.iloc[0]["input_release_status"]) if not receipt.empty else "",
    )
    if receipt.empty or set(receipt.columns) != set(expected.columns):
        raise RuntimeError("depeg E0 input receipt schema changed")
    receipt = receipt.loc[:, list(expected.columns)]
    receipt = receipt.copy()
    receipt["day"] = receipt["day"].astype(str).str.zfill(8)
    observed = receipt.reset_index(drop=True).astype(object).where(pd.notna(receipt), None)
    wanted = expected.reset_index(drop=True).astype(object).where(pd.notna(expected), None)
    if observed.to_dict("records") != wanted.to_dict("records"):
        raise RuntimeError("depeg E0 input receipt disagrees with the bound release")


@dataclass(frozen=True)
class ReceiptPreinstallValidator:
    """Recheck the release and the installed receipt before installing an output."""

    release: ReleasedPartitionSet
    receipt_path: Path
    receipt_sha256: str

    def __call__(self, _staged_path: Path) -> None:
        self.release.assert_current()
        if not self.receipt_path.is_file() or file_sha256(self.receipt_path) != self.receipt_sha256:
            raise RuntimeError("depeg E0 input receipt changed before output installation")
        verify_input_receipt(pd.read_json(self.receipt_path, lines=True), self.release)

    def validate_prepared_stamp(self, prepared_stamp: bytes) -> bytes:
        return release_preinstall_validator(self.release).validate_prepared_stamp(prepared_stamp)


def bind_provisional_local_route_subset(
    days: tuple[str, ...], columns: list[str] = INPUT_COLUMNS
) -> ReleasedPartitionSet:
    """Bind exact local route bytes without claiming the stale J0 ledger is current.

    This exists only for the red-gate E0 lane.  It verifies the selected ledger
    rows, day markers, partition sizes, and SHA-256 values and stamps that exact
    identity.  It does not repair or promote the upstream route release.
    """

    unknown = sorted(set(columns) - set(UNIFIED_COLUMNS))
    if unknown:
        raise ValueError(f"provisional route columns are outside the canonical schema: {unknown}")
    before = file_stat_identity(UNIFIED_QUALITY_PANEL)
    ledger_sha256 = file_sha256(UNIFIED_QUALITY_PANEL)
    quality = pd.read_parquet(UNIFIED_QUALITY_PANEL)
    if before != file_stat_identity(UNIFIED_QUALITY_PANEL) or ledger_sha256 != file_sha256(UNIFIED_QUALITY_PANEL):
        raise RuntimeError("provisional route ledger mutated during binding")
    quality["day"] = quality["day"].astype(str).str.replace("-", "", regex=False).str.zfill(8)
    if quality["day"].duplicated().any():
        raise RuntimeError("provisional route ledger has duplicate days")
    indexed = quality.set_index("day")
    missing = sorted(set(days) - set(indexed.index))
    if missing:
        raise RuntimeError(f"provisional route ledger omits registered days: {missing[:3]}")

    partitions: list[ReleasedPartition] = []
    for day in days:
        row = indexed.loc[day]
        if not bool(row["passed"]):
            raise RuntimeError(f"provisional route ledger day did not pass: {day}")
        path = unified_path(day)
        marker_path = unified_quality_path(day)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        expected_rows = int(row["output_rows"])
        expected_bytes = int(row["output_bytes"])
        expected_sha256 = str(row["output_sha256"])
        input_fingerprint = str(row["input_fingerprint"])
        marker_rows = marker.get("output_rows", marker.get("canonical_rows"))
        if not (
            str(marker.get("day")).replace("-", "") == day
            and int(marker_rows) == expected_rows
            and int(marker.get("output_bytes")) == expected_bytes
            and marker.get("output_sha256") == expected_sha256
            and marker.get("input_fingerprint") == input_fingerprint
            and marker.get("passed") is True
        ):
            raise RuntimeError(f"provisional route marker disagrees with ledger: {day}")
        partition = ReleasedPartition(
            day=day,
            path=path,
            marker_path=marker_path,
            expected_rows=expected_rows,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            marker_sha256=file_sha256(marker_path),
            input_fingerprint=input_fingerprint,
        )
        partition.assert_current()
        partitions.append(partition)
    identity = canonical_json_sha256(
        {
            "policy": "provisional-local-route-subset-v1",
            "status": "stale_local_bytes_explicitly_bound",
            "columns": columns,
            "ledger_sha256": ledger_sha256,
            "partitions": [
                {
                    "day": partition.day,
                    "rows": partition.expected_rows,
                    "bytes": partition.expected_bytes,
                    "sha256": partition.expected_sha256,
                    "marker_sha256": partition.marker_sha256,
                    "input_fingerprint": partition.input_fingerprint,
                }
                for partition in partitions
            ],
        }
    )
    return ReleasedPartitionSet(
        kind="route",
        columns=tuple(columns),
        ledger_path=UNIFIED_QUALITY_PANEL,
        ledger_sha256=ledger_sha256,
        partitions=tuple(partitions),
        content_identity_sha256=identity,
        provenance_inputs=(
            UNIFIED_QUALITY_PANEL,
            *(path for partition in partitions for path in (partition.path, partition.marker_path)),
        ),
    )


def reduce_release(release: ReleasedPartitionSet) -> tuple[pd.DataFrame, dict[str, int]]:
    """Read one released day at a time and retain only hourly route counts."""

    frames: list[pd.DataFrame] = []
    diagnostics = {
        "source_rows": 0,
        "exact_two_leg_routes": 0,
        "provider_coordinate_collision_components_excluded": 0,
    }
    for index, day in enumerate(release.days, 1):
        legs = release.read_day(day)
        diagnostics["source_rows"] += len(legs)
        routes = extract_count_routes(legs)
        diagnostics["exact_two_leg_routes"] += len(routes)
        diagnostics["provider_coordinate_collision_components_excluded"] += int(
            routes.attrs.get("provider_coordinate_collision_components_excluded", 0)
        )
        hourly = aggregate_hourly_routes(routes)
        if not hourly.empty:
            frames.append(hourly)
        if index % 25 == 0 or index == len(release.days):
            print(f"  reduced {index:,}/{len(release.days):,} released days", flush=True)
    if not frames:
        return aggregate_hourly_routes(extract_count_routes(pd.DataFrame(columns=INPUT_COLUMNS))), diagnostics
    return pd.concat(frames, ignore_index=True), diagnostics


def build_package(
    hourly_routes: pd.DataFrame,
    *,
    input_identity_sha256: str,
    release_ledger_sha256: str,
    selected_days: tuple[str, ...],
    diagnostics: dict[str, int],
    input_release_status: str = "current_released_route_subset",
    input_receipt_path: str = "",
    input_receipt_sha256: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return the generated panel, summary records, and one-row manifest."""

    panels: list[pd.DataFrame] = []
    records: list[dict[str, object]] = []
    for event in EVENTS:
        panel, event_records = run_event_family(hourly_routes, event)
        panels.append(panel)
        records.extend(event_records)
    panel = (
        pd.concat(panels, ignore_index=True)
        if panels
        else pd.DataFrame(columns=HOURLY_COLUMNS)
    )
    for record in records:
        record["input_identity_sha256"] = input_identity_sha256
        record["release_ledger_sha256"] = release_ledger_sha256
        record["script_version"] = SCRIPT_VERSION
        record["input_release_status"] = input_release_status
        record["input_receipt_path"] = input_receipt_path
        record["input_receipt_sha256"] = input_receipt_sha256
    summary = pd.DataFrame(records)
    manifest_record = {
        "package": "depeg_substitution_e0",
        "script_version": SCRIPT_VERSION,
        "status": STATUS,
        "claim_gate": CLAIM_GATE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "allowed_claim": (
            "descriptive route composition and within-pair intermediary-use changes "
            "around two stablecoin stress dates on pre-fixed ordered-pair support"
        ),
        "forbidden_claims": (
            "causal event attribution; token-unit or value outcomes; paper or deck promotion"
        ),
        "episode_pooling": "forbidden; TerraUSD and USDC are reported separately",
        "economic_unit": "one exact two-leg route with one intermediary",
        "denominator": (
            "all target and non-target intermediary routes on ordered pairs with "
            "pre-event target and non-target support; pairs with no post-window "
            "routes retained"
        ),
        "share_estimands": (
            "pooled route-weighted composition; order-invariant Shapley attribution "
            "to continuing-pair share changes, no post-window route activity, and "
            "pair-activity weights; both sequential orderings retained as diagnostics"
        ),
        "decomposition_attribution": (
            "zero-post-share Shapley primary; carry-forward-pre-share Shapley "
            "sensitivity; both have exact residual accounting"
        ),
        "inference": "none; separate single-event descriptive anatomy",
        "time_grain": "UTC hour",
        "main_windows": (
            "TerraUSD: 72-hour process window; USDC: 24-hour acute window from "
            "Circle's confirmation that initiated SVB wires had not cleared"
        ),
        "sensitivities": (
            "common 24-hour cross-episode comparison on four same-hour prior weeks, "
            "reported pooled and week by week; eight-week matched sensitivity; "
            "168-hour windows; Terra event time minus/plus 24 hours; USDC "
            "Circle quantified-exposure and Federal Reserve depositor-access markers; "
            "USDC 72-hour "
            "adjustment/recovery window; USDC minimum pre-support, largest-pre-pair "
            "leave-out and pair-concentration diagnostics"
        ),
        "timing_comparison_design": (
            "two pre-event and two post-event-recovery disjoint timing comparisons "
            "outside all focal windows, on frozen focal-event pair support; raw "
            "comparisons only, with no rank or reference distribution"
        ),
        "usdc_primary_baseline": (
            "pooled 24-hour windows exactly 7, 14, 21 and 28 days before the "
            "wire-clearance confirmation anchor; each frozen-population week also "
            "reports actual pre-comparator support"
        ),
        "adjacent_usdc_baseline": "retained only as contaminated descriptive comparison",
        "baseline_event_policy": (
            "prespecified windows are never excluded after inspection; overlaps with "
            "all registered interventions are flagged separately in pre and post windows"
        ),
        "usdc_168h_context": (
            "descriptive and contaminated: baseline overlaps Circle's wire-clearance "
            "confirmation; post overlaps Circle's quantified-exposure statement and "
            "the Federal Reserve depositor-access announcement"
        ),
        "usdc_72h_context": (
            "descriptive adjustment/recovery only; spans multiple contemporaneous interventions"
        ),
        "usdc_hour_boundary": (
            "23:00--00:00 UTC containing Circle's 23:50:35.386 wire-clearance "
            "confirmation is excluded; "
            "post begins 2023-03-11 00:00 UTC"
        ),
        "ust_primary_anchor": (
            "2022-05-07 around 05:00 UTC first disclosed 45m UST Anchor withdrawal; "
            "containing hour excluded; LiuMakarovSchoar2023Terra"
        ),
        "ust_anchor_alternatives": (
            "2022-05-07 21:44 UTC TFL 150m UST-3Crv removal, LiuMakarovSchoar2023Terra; "
            "2022-05-08 daily first-run-day convention, AnaduEtAl2023StablecoinRuns"
        ),
        "comparator": "all non-target intermediaries; DAI leave-out reported separately",
        "dai_leaveout_conventions": (
            "fixed focal population and support requalified after DAI removal"
        ),
        "terra_scientific_role": (
            "appendix anomaly only; exact pair and route support with wrapper, "
            "plus/minus 24-hour, minimum-support, and largest-pair diagnostics; no inference"
        ),
        "terra_identity": (
            "Shuttle and Wormhole UST collapse before topology; canonical self-edges "
            "drop; wrapper identity remains in the hourly panel"
        ),
        "value_fields_consumed": False,
        "input_identity_sha256": input_identity_sha256,
        "input_release_status": input_release_status,
        "release_ledger_sha256": release_ledger_sha256,
        "input_receipt_path": input_receipt_path,
        "input_receipt_sha256": input_receipt_sha256,
        "selected_days": len(selected_days),
        "first_selected_day": selected_days[0],
        "last_selected_day": selected_days[-1],
        "selected_days_sha256": canonical_json_sha256(list(selected_days)),
        **diagnostics,
        "summary_rows": len(summary),
        "hourly_panel_rows": len(panel),
    }
    return panel, summary, pd.DataFrame([manifest_record])


def verify_saved_package_frames(
    panel: pd.DataFrame,
    summary: pd.DataFrame,
    manifest: pd.DataFrame,
    *,
    input_identity_sha256: str,
    input_receipt_sha256: str,
) -> None:
    """Replay primary count totals from saved outputs without rebuilding raw routes."""

    if len(manifest) != 1:
        raise RuntimeError("depeg E0 manifest is not one row")
    manifest_row = manifest.iloc[0]
    if (
        manifest_row["claim_gate"] != CLAIM_GATE
        or bool(manifest_row["promotion_eligible"])
        or manifest_row["status"] != STATUS
    ):
        raise RuntimeError("depeg E0 saved package lost its red provisional boundary")
    if manifest_row["input_identity_sha256"] != input_identity_sha256:
        raise RuntimeError("depeg E0 saved package changed input identity")
    if manifest_row["input_receipt_sha256"] != input_receipt_sha256:
        raise RuntimeError("depeg E0 saved package changed input receipt identity")
    if not summary["claim_gate"].eq(CLAIM_GATE).all() or summary[
        "promotion_eligible"
    ].any():
        raise RuntimeError("depeg E0 saved summaries lost their red gate")
    for event in EVENTS:
        selected = summary[
            summary["event"].eq(event.name)
            & summary["record_type"].eq("event_contrast")
        ]
        if len(selected) != 1:
            raise RuntimeError(f"depeg E0 saved package lacks one primary row: {event.name}")
        row = selected.iloc[0]
        event_panel = panel[panel["event"].eq(event.name)]
        replay = {
            "supported_ordered_pairs": event_panel[["src", "tgt"]]
            .drop_duplicates()
            .shape[0],
            "pre_target_routes": int(
                event_panel.loc[event_panel["period"].eq("pre"), "target_routes"].sum()
            ),
            "post_target_routes": int(
                event_panel.loc[event_panel["period"].eq("post"), "target_routes"].sum()
            ),
            "pre_all_routes": int(
                event_panel.loc[event_panel["period"].eq("pre"), "all_routes"].sum()
            ),
            "post_all_routes": int(
                event_panel.loc[event_panel["period"].eq("post"), "all_routes"].sum()
            ),
        }
        for column, expected in replay.items():
            if int(row[column]) != expected:
                raise RuntimeError(
                    f"depeg E0 saved primary summary disagrees with panel: "
                    f"{event.name} {column}"
                )


def summarize_only() -> int:
    """Verify and replay the saved package without reconstructing raw routes."""

    release = bind_provisional_local_route_subset(required_days())
    receipt = read_exhibit(INPUT_RECEIPT)
    verify_input_receipt(receipt, release)
    receipt_sha256 = file_sha256(INPUT_RECEIPT)
    with current_artifacts(
        [INPUT_RECEIPT, PANEL, SUMMARY, MANIFEST],
        consumer="depeg substitution E0 summarize-only replay",
    ):
        panel = pd.read_parquet(PANEL)
        summary = read_exhibit(SUMMARY)
        manifest = read_exhibit(MANIFEST)
        verify_saved_package_frames(
            panel,
            summary,
            manifest,
            input_identity_sha256=release.content_identity_sha256,
            input_receipt_sha256=receipt_sha256,
        )
    primary = summary[summary["record_type"].eq("event_contrast")][
        [
            "event",
            "supported_ordered_pairs",
            "pre_target_routes",
            "post_target_routes",
            "pre_all_routes",
            "post_all_routes",
            "pooled_route_share_change_pp",
        ]
    ]
    print(
        json.dumps(
            {
                "mode": "summarize_only",
                "raw_input_rebuild": False,
                "input_identity_sha256": release.content_identity_sha256,
                "partition_count": len(release.partitions),
                "claim_gate": CLAIM_GATE,
                "promotion_eligible": PROMOTION_ELIGIBLE,
            },
            sort_keys=True,
        )
    )
    print(primary.to_string(index=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="build and validate in memory without installing provisional outputs",
    )
    parser.add_argument(
        "--allow-stale-local-route-release",
        action="store_true",
        help=(
            "when the canonical J0 gate is red, bind exact selected local route bytes "
            "as stale/provisional input; never promotes them"
        ),
    )
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()

    if args.summarize_only:
        return summarize_only()

    days = required_days()
    print("binding the current released route ledger", flush=True)
    input_release_status = "current_released_route_subset"
    try:
        full_release = released_route_partitions(INPUT_COLUMNS, nonempty=False)
        release = full_release.select_days(days)
    except RuntimeError:
        if not args.allow_stale_local_route_release:
            raise
        print(
            "canonical J0 gate is red; binding exact selected local bytes as "
            "stale/provisional input",
            flush=True,
        )
        release = bind_provisional_local_route_subset(days)
        input_release_status = "stale_local_bytes_explicitly_bound"
    print(
        f"count-only E0 perimeter: {len(release.days):,} days; "
        f"identity={release.content_identity_sha256[:12]}",
        flush=True,
    )
    if len(release.partitions) != 184:
        raise RuntimeError(
            f"depeg E0 perimeter changed: expected exactly 184 partitions, got {len(release.partitions)}"
        )
    receipt = input_receipt_frame(
        release, input_release_status=input_release_status
    )
    if args.validate_only:
        verify_input_receipt(receipt, release)
        receipt_sha256 = canonical_json_sha256(receipt.to_dict("records"))
    else:
        write_exhibit(
            receipt,
            INPUT_RECEIPT,
            code_sources=CODE_SOURCES,
            inputs=[release.ledger_path],
            notes=(
                f"{SCRIPT_VERSION}; exact 184-partition and marker receipt; "
                f"released input identity {release.content_identity_sha256}"
            ),
            preinstall_validator=release_preinstall_validator(release),
        )
        verify_input_receipt(pd.read_json(INPUT_RECEIPT, lines=True), release)
        receipt_sha256 = file_sha256(INPUT_RECEIPT)
    hourly_routes, diagnostics = reduce_release(release)
    panel, summary, manifest = build_package(
        hourly_routes,
        input_identity_sha256=release.content_identity_sha256,
        release_ledger_sha256=release.ledger_sha256,
        selected_days=release.days,
        diagnostics=diagnostics,
        input_release_status=input_release_status,
        input_receipt_path=_record_path(INPUT_RECEIPT),
        input_receipt_sha256=receipt_sha256,
    )
    if summary.empty or not {event.name for event in EVENTS}.issubset(set(summary["event"])):
        raise RuntimeError("depeg substitution produced no event summaries")
    if not summary["status"].eq(STATUS).all() or summary["promotion_eligible"].any():
        raise RuntimeError("depeg substitution lost its provisional boundary")
    if args.validate_only:
        print(
            f"validated {len(summary):,} summary rows and {len(panel):,} pair-hour rows; "
            "outputs unchanged"
        )
        return 0

    validator = ReceiptPreinstallValidator(release, INPUT_RECEIPT, receipt_sha256)
    inputs = [release.ledger_path, INPUT_RECEIPT]
    notes = (
        f"{SCRIPT_VERSION}; {STATUS}; claim gate {CLAIM_GATE}; non-promotable; "
        "count-only exact two-leg route substitution; no causal attribution; "
        f"released input identity {release.content_identity_sha256}"
    )
    write_panel(
        panel,
        PANEL,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes=notes,
        preinstall_validator=validator,
    )
    write_exhibit(
        summary,
        SUMMARY,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes=notes,
        preinstall_validator=validator,
    )
    write_exhibit(
        manifest,
        MANIFEST,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes=notes,
        preinstall_validator=validator,
    )
    print(
        json.dumps(
            {
                "status": STATUS,
                "promotion_eligible": PROMOTION_ELIGIBLE,
                "input_identity_sha256": release.content_identity_sha256,
                "summary": str(SUMMARY.relative_to(REPO_ROOT)),
                "panel": str(PANEL.relative_to(REPO_ROOT)),
                "manifest": str(MANIFEST.relative_to(REPO_ROOT)),
                "input_receipt": str(INPUT_RECEIPT.relative_to(REPO_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

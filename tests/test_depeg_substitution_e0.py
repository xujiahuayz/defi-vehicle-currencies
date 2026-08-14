from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.analysis.depeg_substitution_e0 import (
    DAI,
    EVENTS,
    INPUT_COLUMNS,
    TERRA_UST,
    UST_ALTERNATIVE_ANCHORS,
    USDC,
    UST_SHUTTLE,
    UST_WORMHOLE,
    EventSpec,
    TimingAssignment,
    aggregate_hourly_routes,
    disjoint_timing_diagnostics,
    event_hourly_panel,
    extract_count_routes,
    largest_pre_activity_pair,
    pairs_with_minimum_pre_support,
    required_days,
    run_event_family,
    timing_assignments,
    validate_timing_assignments,
)
from ddvc.artifact_release import canonical_json_sha256, file_sha256
from ddvc.data_release import ReleasedPartition, ReleasedPartitionSet
from scripts.run_depeg_substitution_e0 import (
    build_package,
    input_receipt_frame,
    verify_saved_package_frames,
    verify_input_receipt,
)


SRC = "0x1111111111111111111111111111111111111111"
TGT = "0x2222222222222222222222222222222222222222"
OTHER = "0x3333333333333333333333333333333333333333"


def leg(
    tx_hash: str,
    log_index: int,
    token_in: str,
    token_out: str,
    *,
    timestamp: int = 1_700_000_000,
    component_id: int = 0,
    source: str = "curve",
    route_class: str = "coherent",
) -> dict[str, object]:
    return {
        "tx_hash": tx_hash,
        "component_id": component_id,
        "source": source,
        "token_in": token_in,
        "token_out": token_out,
        "log_index": log_index,
        "route_class": route_class,
        "timestamp_utc": timestamp,
    }


def hourly_row(
    hour: pd.Timestamp,
    src: str,
    tgt: str,
    vehicle: str,
    routes: int,
    representation: str = "not_applicable",
) -> dict[str, object]:
    return {
        "hour_utc": hour,
        "src": src,
        "tgt": tgt,
        "vehicle": vehicle,
        "ust_representation": representation,
        "routes": routes,
    }


def test_ust_wrappers_collapse_before_topology_and_self_edges_drop() -> None:
    rows = [
        leg("mixed", 0, SRC, UST_SHUTTLE),
        leg("mixed", 1, UST_WORMHOLE, TGT),
        leg("self", 0, UST_SHUTTLE, UST_WORMHOLE),
    ]
    routes = extract_count_routes(pd.DataFrame(rows))
    assert len(routes) == 1
    route = routes.iloc[0]
    assert route["tx_hash"] == "mixed"
    assert route["vehicle"] == TERRA_UST
    assert route["ust_representation"] == "mixed_wrappers"
    assert route["src"] == SRC
    assert route["tgt"] == TGT


@pytest.mark.parametrize(
    ("wrapper", "expected"),
    [(UST_SHUTTLE, "shuttle"), (UST_WORMHOLE, "wormhole")],
)
def test_ust_representation_is_retained(wrapper: str, expected: str) -> None:
    routes = extract_count_routes(
        pd.DataFrame([leg(expected, 0, SRC, wrapper), leg(expected, 1, wrapper, TGT)])
    )
    assert routes.iloc[0]["vehicle"] == TERRA_UST
    assert routes.iloc[0]["ust_representation"] == expected


def test_extractor_is_exact_two_leg_and_count_only() -> None:
    rows = [
        leg("two", 0, SRC, OTHER),
        leg("two", 1, OTHER, TGT),
        leg("three", 0, SRC, OTHER),
        leg("three", 1, OTHER, USDC),
        leg("three", 2, USDC, TGT),
    ]
    frame = pd.DataFrame(rows)
    frame["amount_in"] = [10**30] * len(frame)
    frame["amount_out"] = [1] * len(frame)
    frame["amount_usd"] = [float("nan")] * len(frame)
    routes = extract_count_routes(frame)
    assert routes["tx_hash"].tolist() == ["two"]
    assert not {"amount_in", "amount_out", "amount_usd"}.intersection(routes.columns)


def test_mixed_route_classes_do_not_become_clean_after_row_filtering() -> None:
    routes = extract_count_routes(
        pd.DataFrame(
            [
                leg("mixed-class", 0, SRC, OTHER),
                leg("mixed-class", 1, OTHER, TGT),
                leg("mixed-class", 2, SRC, TGT, route_class="tricky_bridged"),
            ]
        )
    )
    assert routes.empty


def test_provider_coordinate_collisions_are_quarantined() -> None:
    rows = [
        leg("bad", 0, SRC, OTHER, source="curve"),
        leg("bad", 0, SRC, OTHER, source="balancer"),
        leg("bad", 1, OTHER, TGT),
        leg("good", 2, SRC, OTHER),
        leg("good", 3, OTHER, TGT),
    ]
    routes = extract_count_routes(pd.DataFrame(rows))
    assert routes["tx_hash"].tolist() == ["good"]
    assert routes.attrs["provider_coordinate_collision_components_excluded"] == 1


def test_fixed_pair_support_is_pre_only_and_retains_pair_without_post_routes() -> None:
    anchor = pd.Timestamp("2024-01-08T00:00:00Z")
    event = EventSpec("test", "USDC", USDC, anchor, 2)
    rows = [
        hourly_row(anchor - pd.Timedelta(hours=2), SRC, TGT, USDC, 2),
        hourly_row(anchor - pd.Timedelta(hours=1), SRC, TGT, OTHER, 2),
        hourly_row(anchor, SRC, TGT, OTHER, 4),
        # No pre-event comparison route: excluded.
        hourly_row(anchor - pd.Timedelta(hours=1), "c", "d", USDC, 2),
        hourly_row(anchor, "c", "d", OTHER, 2),
        # Both pre-event routes but no post-event activity: retained as a full exit.
        hourly_row(anchor - pd.Timedelta(hours=1), "e", "f", USDC, 1),
        hourly_row(anchor - pd.Timedelta(hours=1), "e", "f", OTHER, 1),
    ]
    panel, summary = event_hourly_panel(pd.DataFrame(rows), event, window_hours=2)
    assert summary["supported_ordered_pairs"] == 2
    assert len(panel) == 8
    assert summary["pre_target_routes"] == 3
    assert summary["pre_all_routes"] == 6
    assert summary["post_target_routes"] == 0
    assert summary["post_all_routes"] == 4
    assert summary["pooled_route_share_change_pp"] == pytest.approx(-50.0)
    assert summary["continuing_pair_equal_mean_share_change_pp"] == pytest.approx(-50.0)
    assert summary["shapley_continuing_pair_share_change_pp"] == pytest.approx(-125 / 3)
    assert summary["shapley_no_post_route_activity_pp"] == pytest.approx(-25 / 3)
    assert summary["shapley_pair_activity_weight_change_pp"] == pytest.approx(0.0)
    assert summary["ordered_pairs_with_no_post_window_routes"] == 1
    assert summary["ordered_pairs_with_no_post_target_routes"] == 2


def test_hour_of_week_baseline_uses_prior_week_not_immediate_preperiod() -> None:
    anchor = pd.Timestamp("2024-01-08T00:00:00Z")
    event = EventSpec("matched", "USDC", USDC, anchor, 2, baseline_lag_weeks=(1,))
    rows = [
        hourly_row(anchor - pd.Timedelta(weeks=1), SRC, TGT, USDC, 1),
        hourly_row(anchor - pd.Timedelta(weeks=1) + pd.Timedelta(hours=1), SRC, TGT, OTHER, 1),
        # This immediate-pre spike is outside the registered baseline.
        hourly_row(anchor - pd.Timedelta(hours=1), SRC, TGT, USDC, 100),
        hourly_row(anchor, SRC, TGT, USDC, 3),
        hourly_row(anchor + pd.Timedelta(hours=1), SRC, TGT, OTHER, 1),
    ]
    _panel, summary = event_hourly_panel(pd.DataFrame(rows), event, window_hours=2)
    assert summary["pre_target_routes"] == 1
    assert summary["pre_all_routes"] == 2
    assert summary["post_target_routes"] == 3
    assert summary["post_all_routes"] == 4
    assert summary["pooled_route_share_change_pp"] == pytest.approx(25.0)


def test_four_week_baseline_pools_prespecified_windows_and_normalizes_counts() -> None:
    anchor = pd.Timestamp("2024-01-29T00:00:00Z")
    event = EventSpec(
        "pooled", "USDC", USDC, anchor, 1, baseline_lag_weeks=(1, 2, 3, 4)
    )
    rows = []
    for lag, target, comparison in ((1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4)):
        hour = anchor - pd.Timedelta(weeks=lag)
        rows.extend(
            [
                hourly_row(hour, SRC, TGT, USDC, target),
                hourly_row(hour, SRC, TGT, OTHER, comparison),
            ]
        )
    rows.extend(
        [
            hourly_row(anchor, SRC, TGT, USDC, 5),
            hourly_row(anchor, SRC, TGT, OTHER, 5),
        ]
    )
    panel, summary = event_hourly_panel(pd.DataFrame(rows), event, window_hours=1)
    assert len(panel) == 5
    assert summary["baseline_windows"] == 4
    assert summary["pre_target_routes"] == 10
    assert summary["pre_target_routes_per_pair_hour"] == pytest.approx(2.5)
    assert summary["post_target_routes_per_pair_hour"] == pytest.approx(5.0)
    assert summary["target_route_count_change_vs_mean_baseline"] == pytest.approx(2.5)
    assert summary["pooled_route_share_change_pp"] == pytest.approx(0.0)


def test_pooled_change_exactly_decomposes_with_order_invariant_shapley_attribution() -> None:
    anchor = pd.Timestamp("2024-01-08T00:00:00Z")
    event = EventSpec("decomposition", "USDC", USDC, anchor, 1)
    rows = [
        hourly_row(anchor - pd.Timedelta(hours=1), "a", "b", USDC, 9),
        hourly_row(anchor - pd.Timedelta(hours=1), "a", "b", OTHER, 1),
        hourly_row(anchor - pd.Timedelta(hours=1), "c", "d", USDC, 1),
        hourly_row(anchor - pd.Timedelta(hours=1), "c", "d", OTHER, 9),
        hourly_row(anchor, "a", "b", USDC, 8),
        hourly_row(anchor, "a", "b", OTHER, 2),
        # c--d has no post-event activity: it is an extensive-margin exit.
    ]
    _panel, summary = event_hourly_panel(pd.DataFrame(rows), event)
    assert summary["pre_pooled_route_share"] == pytest.approx(0.5)
    assert summary["post_pooled_route_share"] == pytest.approx(0.8)
    assert summary["ordered_pairs_with_post_window_routes"] == 1
    assert summary["ordered_pairs_with_no_post_window_routes"] == 1
    assert summary["continuing_pair_equal_mean_share_change_pp"] == pytest.approx(-10.0)
    assert summary["shapley_continuing_pair_share_change_pp"] == pytest.approx(-7.5)
    assert summary["shapley_no_post_route_activity_pp"] == pytest.approx(-2.5)
    assert summary["shapley_pair_activity_weight_change_pp"] == pytest.approx(40.0)
    assert summary["shapley_decomposition_residual_pp"] == pytest.approx(0.0, abs=1e-12)
    assert summary["inactive_pair_primary_convention"] == "zero_post_share"
    assert summary["inactive_pair_sensitivity_convention"] == "carry_forward_pre_share"
    assert summary["inactive_pair_accounting_is_convention_dependent"] is True
    assert summary["carry_forward_shapley_pair_share_change_pp"] == pytest.approx(-7.5)
    assert summary["carry_forward_shapley_pair_activity_weight_change_pp"] == pytest.approx(37.5)
    assert summary["carry_forward_shapley_decomposition_residual_pp"] == pytest.approx(
        0.0, abs=1e-12
    )
    assert summary["share_first_continuing_pair_share_change_pp"] == pytest.approx(-5.0)
    assert summary["share_first_no_post_route_activity_pp"] == pytest.approx(-5.0)
    assert summary["share_first_pair_activity_weight_change_pp"] == pytest.approx(40.0)
    assert summary["weight_first_pair_activity_weight_change_pp"] == pytest.approx(40.0)
    assert summary["weight_first_total_pair_share_change_pp"] == pytest.approx(-10.0)
    assert summary["pre_top1_pair_all_route_share"] == pytest.approx(0.5)
    assert summary["post_top1_pair_all_route_share"] == pytest.approx(1.0)
    assert summary["post_top1_pair_target_route_share"] == pytest.approx(1.0)
    assert summary["post_top_pair_src"] == "a"
    assert summary["post_top_pair_tgt"] == "b"
    assert summary["post_top_pair_all_routes"] == 10
    assert summary["post_top_pair_target_routes"] == 8
    assert "pre_weight_standardized_share_change_pp" not in summary


def test_minimum_pre_support_uses_only_focal_pre_counts() -> None:
    anchor = pd.Timestamp("2024-01-08T00:00:00Z")
    event = EventSpec("support", "USDC", USDC, anchor, 1)
    rows = [
        hourly_row(anchor - pd.Timedelta(hours=1), "a", "b", USDC, 10),
        hourly_row(anchor - pd.Timedelta(hours=1), "a", "b", OTHER, 8),
        hourly_row(anchor, "a", "b", USDC, 1),
        hourly_row(anchor - pd.Timedelta(hours=1), "c", "d", USDC, 4),
        hourly_row(anchor - pd.Timedelta(hours=1), "c", "d", OTHER, 20),
        hourly_row(anchor, "c", "d", USDC, 100),
    ]
    panel, _summary = event_hourly_panel(pd.DataFrame(rows), event)
    assert pairs_with_minimum_pre_support(
        panel,
        minimum_target_routes=5,
        minimum_comparison_routes=5,
    ) == (("a", "b"),)
    with pytest.raises(ValueError, match="positive"):
        pairs_with_minimum_pre_support(
            panel,
            minimum_target_routes=0,
            minimum_comparison_routes=1,
        )


def test_largest_pre_activity_pair_is_selected_without_post_information() -> None:
    anchor = pd.Timestamp("2024-01-08T00:00:00Z")
    event = EventSpec("influence", "USDC", USDC, anchor, 1)
    rows = [
        hourly_row(anchor - pd.Timedelta(hours=1), "a", "b", USDC, 6),
        hourly_row(anchor - pd.Timedelta(hours=1), "a", "b", OTHER, 4),
        hourly_row(anchor, "a", "b", USDC, 1),
        hourly_row(anchor - pd.Timedelta(hours=1), "c", "d", USDC, 2),
        hourly_row(anchor - pd.Timedelta(hours=1), "c", "d", OTHER, 2),
        hourly_row(anchor, "c", "d", USDC, 10_000),
    ]
    panel, _summary = event_hourly_panel(pd.DataFrame(rows), event)
    assert largest_pre_activity_pair(panel) == ("a", "b")
    assert largest_pre_activity_pair(panel.iloc[0:0]) is None


def test_wrapper_restriction_changes_sample_without_reclassifying_other_routes() -> None:
    anchor = pd.Timestamp("2022-05-09T00:00:00Z")
    event = EventSpec("ust", "UST", TERRA_UST, anchor, 2)
    rows = [
        hourly_row(anchor - pd.Timedelta(hours=1), SRC, TGT, TERRA_UST, 2, "shuttle"),
        hourly_row(anchor - pd.Timedelta(hours=1), SRC, TGT, TERRA_UST, 3, "wormhole"),
        hourly_row(anchor - pd.Timedelta(hours=1), SRC, TGT, OTHER, 5),
        hourly_row(anchor, SRC, TGT, TERRA_UST, 1, "shuttle"),
        hourly_row(anchor, SRC, TGT, OTHER, 4),
    ]
    combined, combined_summary = event_hourly_panel(pd.DataFrame(rows), event, window_hours=2)
    _shuttle, shuttle_summary = event_hourly_panel(
        pd.DataFrame(rows), event, window_hours=2, representation_scope="shuttle_only"
    )
    assert combined_summary["pre_target_routes"] == 5
    assert shuttle_summary["pre_target_routes"] == 2
    assert combined["ust_wormhole_routes"].sum() == 3
    assert shuttle_summary["pre_ust_wormhole_routes"] == 0


@pytest.mark.parametrize(
    ("event", "shift"),
    [
        *((event, 0) for event in (EVENTS[0], *UST_ALTERNATIVE_ANCHORS)),
        (EVENTS[0], -24),
        (EVENTS[0], 24),
    ],
)
def test_terra_windows_exclude_the_containing_event_hour(
    event: EventSpec, shift: int
) -> None:
    containing = event.containing_hour + pd.Timedelta(hours=shift)
    post = event.analysis_hour + pd.Timedelta(hours=shift)
    rows = [
        hourly_row(containing - pd.Timedelta(hours=1), SRC, TGT, TERRA_UST, 1, "shuttle"),
        hourly_row(containing - pd.Timedelta(hours=1), SRC, TGT, OTHER, 1),
        hourly_row(containing, SRC, TGT, TERRA_UST, 100, "shuttle"),
        hourly_row(containing, SRC, TGT, OTHER, 100),
        hourly_row(post, SRC, TGT, TERRA_UST, 2, "shuttle"),
        hourly_row(post, SRC, TGT, OTHER, 2),
    ]
    panel, summary = event_hourly_panel(
        pd.DataFrame(rows), event, window_hours=1, event_shift_hours=shift
    )
    assert set(panel["hour_utc"]) == {containing - pd.Timedelta(hours=1), post}
    assert containing not in set(panel["hour_utc"])
    assert summary["pre_target_routes"] == 1
    assert summary["post_target_routes"] == 2
    assert summary["excluded_partial_hour_start_utc"] == containing.isoformat()


def test_timing_assignments_are_disjoint_from_focal_design_and_each_other() -> None:
    event = next(item for item in EVENTS if item.target_symbol == "USDC")
    assignments = timing_assignments(event)
    assert len(assignments) == 4
    validate_timing_assignments(event, assignments)
    assert all(item.pre_start.dayofweek == event.analysis_hour.dayofweek for item in assignments)
    assert sum(item.post_start < event.analysis_hour for item in assignments) == 2


def test_timing_collision_detection_never_exempts_same_named_focal_event() -> None:
    event = next(item for item in EVENTS if item.target_symbol == "USDC")
    colliding = (
        TimingAssignment(
            "same_event_name_is_irrelevant",
            event.analysis_hour - pd.Timedelta(weeks=1),
            event.analysis_hour,
            24,
        ),
    )
    with pytest.raises(ValueError, match="collision"):
        validate_timing_assignments(event, colliding)


def test_disjoint_timing_comparisons_reuse_focal_population_without_rank_or_p_value() -> None:
    anchor = pd.Timestamp("2024-02-01T00:00:00Z")
    event = EventSpec("timing", "USDC", USDC, anchor, 1)
    fixed_pairs = (("a", "b"), ("c", "d"))
    rows = []
    for assignment in timing_assignments(event, window_hours=1):
        rows.extend(
            [
                hourly_row(assignment.pre_start, "a", "b", USDC, 1),
                hourly_row(assignment.pre_start, "a", "b", OTHER, 1),
                hourly_row(assignment.post_start, "a", "b", OTHER, 1),
            ]
        )
    observed = {
        "pooled_route_share_change_pp": -25.0,
        "shapley_continuing_pair_share_change_pp": -10.0,
        "shapley_no_post_route_activity_pp": -5.0,
        "shapley_pair_activity_weight_change_pp": -10.0,
    }
    assignments, diagnostic = disjoint_timing_diagnostics(
        pd.DataFrame(rows), event, observed, fixed_pairs, window_hours=1
    )
    assert {record["supported_ordered_pairs"] for record in assignments} == {2}
    assert {record["record_type"] for record in assignments} == {"disjoint_timing_comparison"}
    assert {record["comparison_phase"] for record in assignments} == {
        "pre_event",
        "post_event_recovery",
    }
    assert diagnostic["frozen_ordered_pairs"] == 2
    assert diagnostic["timing_comparisons"] == 4
    assert diagnostic["pre_event_comparisons"] == 2
    assert diagnostic["post_event_recovery_comparisons"] == 2
    assert "rank_denominator" not in diagnostic
    assert "two_sided_rank" not in diagnostic
    assert "no rank" in diagnostic["interpretation"]


def test_usdc_primary_and_marker_sensitivities_do_not_pool_events() -> None:
    event = next(item for item in EVENTS if item.target_symbol == "USDC")
    empty = pd.DataFrame(
        columns=["hour_utc", "src", "tgt", "vehicle", "ust_representation", "routes"]
    )
    panel, records = run_event_family(empty, event)
    main = next(record for record in records if record["record_type"] == "event_contrast")
    markers = [record for record in records if record["record_type"] == "event_marker_sensitivity"]
    weeks = [record for record in records if record["record_type"] == "matched_baseline_week"]
    recovery = next(record for record in records if record["record_type"] == "adjustment_recovery_window")
    contaminated = next(
        record for record in records if record["record_type"] == "contaminated_window_sensitivity"
    )
    assert panel["window_hours"].drop_duplicates().tolist() == []
    assert main["window_hours"] == 24
    assert main["source_event_time_utc"].startswith("2023-03-10T23:50:35.386")
    assert main["analysis_anchor_hour_utc"].startswith("2023-03-11T00:00:00")
    assert main["containing_anchor_hour_excluded"] is True
    assert "wires initiated" in main["anchor_definition"]
    assert "first disclosed" not in main["anchor_definition"]
    assert main["baseline"] == "pooled same UTC hours at week lags 1,2,3,4"
    assert recovery["window_hours"] == 72
    assert contaminated["window_hours"] == 168
    assert "wire-clearance confirmation" in contaminated["baseline_contamination"]
    assert "quantified-exposure" in contaminated["baseline_contamination"]
    assert "Federal Reserve depositor-access" in contaminated["baseline_contamination"]
    assert "usdc_svb_wire_clearance_confirmation" in contaminated[
        "registered_intervention_pre_window_overlap"
    ]
    assert "usdc_circle_quantified_svb_exposure" in contaminated[
        "registered_intervention_post_window_overlap"
    ]
    assert "usdc_federal_reserve_depositor_access_announcement" in contaminated[
        "registered_intervention_post_window_overlap"
    ]
    assert {record["matched_week_lag"] for record in weeks} == {1, 2, 3, 4}
    assert any(record["record_type"] == "eight_week_matched_sensitivity" for record in records)
    assert any(record["record_type"] == "adjacent_pre_contaminated_descriptive" for record in records)
    dai = next(
        record
        for record in records
        if record["record_type"] == "leave_dai_out_fixed_population_sensitivity"
    )
    dai_requalified = next(
        record
        for record in records
        if record["record_type"]
        == "leave_dai_out_requalified_support_sensitivity"
    )
    assert dai["comparator_exclusions"] == DAI
    assert "not treated as an unaffected control" in dai["interpretation"]
    assert "requalified" in dai_requalified["interpretation"]
    assert {record["event_marker"] for record in markers} == {
        "circle_quantified_svb_exposure",
        "federal_reserve_depositor_access_announcement",
    }
    assert {
        record["event_marker"]: (record["event_source_id"], record["event_source_url"])
        for record in markers
    } == {
        "circle_quantified_svb_exposure": (
            "CircleStatus1634391505988206592",
            "https://x.com/circle/status/1634391505988206592",
        ),
        "federal_reserve_depositor_access_announcement": (
            "FederalReserve2023JointStatementSVBSignature",
            "https://www.federalreserve.gov/newsevents/pressreleases/monetary20230312b.htm",
        ),
    }
    assert {record["event"] for record in records} == {event.name}
    assert all(record["inference"].startswith("none") for record in records)
    assert all(
        record["frozen_population_ordered_pairs"] == 0
        and record["pre_comparator_supported_ordered_pairs"] == 0
        and "frozen focal-event" in record["population_diagnostic"]
        for record in weeks
    )


def test_dai_leaveout_keeps_focal_pairs_and_removes_dai_only_from_comparator() -> None:
    anchor = pd.Timestamp("2024-01-08T00:00:00Z")
    event = EventSpec("dai", "USDC", USDC, anchor, 1)
    rows = [
        hourly_row(anchor - pd.Timedelta(hours=1), SRC, TGT, USDC, 3),
        hourly_row(anchor - pd.Timedelta(hours=1), SRC, TGT, DAI, 2),
        hourly_row(anchor, SRC, TGT, USDC, 1),
        hourly_row(anchor, SRC, TGT, DAI, 4),
    ]
    frame = pd.DataFrame(rows)
    main_panel, main = event_hourly_panel(frame, event)
    pairs = tuple(main_panel[["src", "tgt"]].drop_duplicates().itertuples(index=False, name=None))
    _leaveout_panel, leaveout = event_hourly_panel(
        frame,
        event,
        fixed_pairs=pairs,
        comparator_exclusions=frozenset({DAI}),
    )
    _requalified_panel, requalified = event_hourly_panel(
        frame,
        event,
        comparator_exclusions=frozenset({DAI}),
    )
    assert main["supported_ordered_pairs"] == leaveout["supported_ordered_pairs"] == 1
    assert leaveout["pre_target_routes"] == main["pre_target_routes"] == 3
    assert leaveout["pre_comparator_zero_pairs_after_exclusion"] == 1
    assert leaveout["pre_all_routes"] == 3
    assert requalified["supported_ordered_pairs"] == 0
    assert leaveout["pair_population"] == "frozen from focal event pre-support"
    assert requalified["pair_population"] == (
        "fixed from focal pre-event target and non-target activity"
    )


def test_terra_is_an_appendix_anomaly_with_bounded_fragility_diagnostics() -> None:
    event = next(item for item in EVENTS if item.target_symbol == "UST")
    pre = event.containing_hour - pd.Timedelta(hours=1)
    post = event.analysis_hour
    rows = [
        hourly_row(pre, "a", "b", TERRA_UST, 2, "shuttle"),
        hourly_row(pre, "a", "b", OTHER, 2),
        hourly_row(pre, "c", "d", TERRA_UST, 1, "wormhole"),
        hourly_row(pre, "c", "d", OTHER, 1),
        hourly_row(post, "a", "b", TERRA_UST, 1, "shuttle"),
        hourly_row(post, "a", "b", OTHER, 1),
        hourly_row(post, "c", "d", TERRA_UST, 2, "wormhole"),
        hourly_row(post, "c", "d", OTHER, 2),
    ]
    _panel, records = run_event_family(pd.DataFrame(rows), event)
    anomaly = next(
        record for record in records if record["record_type"] == "appendix_anomaly_summary"
    )
    assert anomaly["diagnostic_class"] == "appendix_anomaly"
    assert anomaly["scientific_role"] == "appendix_only_diagnostic"
    assert anomaly["supported_ordered_pairs"] == 2
    assert anomaly["pre_target_routes"] == 3
    assert anomaly["post_target_routes"] == 3
    assert anomaly["pre_ust_shuttle_routes"] == 2
    assert anomaly["pre_ust_wormhole_routes"] == 1
    assert anomaly["minimum_support_diagnostics_run"] == 1
    assert anomaly["largest_pair_leaveout_run"] is True
    assert anomaly["inference"].startswith("none")
    terra_dai = next(
        record
        for record in records
        if record["record_type"] == "leave_dai_out_fixed_population_sensitivity"
    )
    assert "does not classify DAI as exposed to the Terra event" in terra_dai[
        "interpretation"
    ]


def test_ust_anchor_is_literature_bound_and_named_alternatives_are_reported() -> None:
    event = next(item for item in EVENTS if item.target_symbol == "UST")
    assert event.event_time == pd.Timestamp("2022-05-07T05:00:00Z")
    assert event.analysis_hour == pd.Timestamp("2022-05-07T06:00:00Z")
    assert event.anchor_citation == "LiuMakarovSchoar2023Terra"
    empty = pd.DataFrame(
        columns=["hour_utc", "src", "tgt", "vehicle", "ust_representation", "routes"]
    )
    _panel, records = run_event_family(empty, event)
    alternatives = [
        record for record in records if record["record_type"] == "event_anchor_alternative"
    ]
    assert {record["event"] for record in alternatives} == {
        "terra_tfl_liquidity_removal",
        "terra_first_run_day",
    }
    daily = next(record for record in alternatives if record["event"] == "terra_first_run_day")
    assert daily["anchor_citation"] == "AnaduEtAl2023StablecoinRuns"
    assert daily["event_source_url"].startswith("https://www.bostonfed.org/")
    assert "not the first on-chain sign" in daily["anchor_definition"]
    assert all(record["scientific_role"] == "appendix_only_diagnostic" for record in records)


def test_required_days_are_the_exact_registered_184_partition_perimeter() -> None:
    days = required_days()
    assert len(days) == len(set(days)) == 184
    assert days[0] == "20220312"
    assert days[-1] == "20230415"
    for event in EVENTS:
        assert event.analysis_hour.strftime("%Y%m%d") in days


def _fake_release(tmp_path: Path) -> ReleasedPartitionSet:
    ledger = tmp_path / "ledger.parquet"
    partition_path = tmp_path / "20230101.parquet"
    marker_path = tmp_path / "20230101.json"
    ledger.write_bytes(b"ledger")
    partition_path.write_bytes(b"partition")
    marker_path.write_text('{"passed": true}\n', encoding="utf-8")
    partition = ReleasedPartition(
        day="20230101",
        path=partition_path,
        marker_path=marker_path,
        expected_rows=7,
        expected_bytes=partition_path.stat().st_size,
        expected_sha256=file_sha256(partition_path),
        marker_sha256=file_sha256(marker_path),
        input_fingerprint="input-fingerprint",
    )
    return ReleasedPartitionSet(
        kind="route",
        columns=tuple(INPUT_COLUMNS),
        ledger_path=ledger,
        ledger_sha256=file_sha256(ledger),
        partitions=(partition,),
        content_identity_sha256=canonical_json_sha256({"fixture": True}),
        provenance_inputs=(ledger, partition_path, marker_path),
    )


def test_input_receipt_binds_marker_source_identity_and_partition_tampering(tmp_path: Path) -> None:
    release = _fake_release(tmp_path)
    receipt = input_receipt_frame(
        release, input_release_status="fixture_release"
    )
    verify_input_receipt(receipt, release)
    assert receipt.iloc[0]["marker_sha256"] == file_sha256(release.partitions[0].marker_path)
    assert receipt.iloc[0]["partition_sha256"] == file_sha256(release.partitions[0].path)
    release.partitions[0].path.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="partition"):
        verify_input_receipt(receipt, release)


def test_input_receipt_rejects_marker_and_receipt_identity_tampering(tmp_path: Path) -> None:
    release = _fake_release(tmp_path)
    receipt = input_receipt_frame(release, input_release_status="fixture_release")
    changed = receipt.copy()
    changed.loc[0, "marker_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="receipt disagrees"):
        verify_input_receipt(changed, release)
    release.partitions[0].marker_path.write_text('{"passed": false}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="marker"):
        verify_input_receipt(receipt, release)


def test_package_stamps_exact_identity_and_is_non_promotable() -> None:
    empty = pd.DataFrame(
        columns=["hour_utc", "src", "tgt", "vehicle", "ust_representation", "routes"]
    )
    panel, summary, manifest = build_package(
        empty,
        input_identity_sha256="a" * 64,
        release_ledger_sha256="b" * 64,
        selected_days=("20220101", "20220102"),
        diagnostics={
            "source_rows": 0,
            "exact_two_leg_routes": 0,
            "provider_coordinate_collision_components_excluded": 0,
        },
    )
    assert not {"amount_in", "amount_out", "amount_usd"}.intersection(panel.columns)
    assert summary["input_identity_sha256"].eq("a" * 64).all()
    assert summary["status"].eq("provisional_diagnostic_only").all()
    assert not summary["promotion_eligible"].any()
    assert manifest.iloc[0]["claim_gate"] == "red"
    assert manifest.iloc[0]["value_fields_consumed"] == False  # noqa: E712
    assert manifest.iloc[0]["episode_pooling"].startswith("forbidden")
    assert manifest.iloc[0]["inference"].startswith("none")
    assert "Shapley" in manifest.iloc[0]["decomposition_attribution"]
    assert "no rank" in manifest.iloc[0]["timing_comparison_design"]
    assert "7, 14, 21 and 28" in manifest.iloc[0]["usdc_primary_baseline"]
    verify_saved_package_frames(
        panel,
        summary,
        manifest,
        input_identity_sha256="a" * 64,
        input_receipt_sha256="",
    )
    tampered = summary.copy()
    primary_index = tampered.index[tampered["record_type"].eq("event_contrast")][0]
    tampered.loc[primary_index, "pre_target_routes"] = 1
    with pytest.raises(RuntimeError, match="disagrees with panel"):
        verify_saved_package_frames(
            panel,
            tampered,
            manifest,
            input_identity_sha256="a" * 64,
            input_receipt_sha256="",
        )

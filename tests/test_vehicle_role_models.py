from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ddvc.artifact_release import file_sha256
from ddvc.asset_types import NATIVE, STABLE
from ddvc.model_artifacts import ModelArtifactContext
from ddvc.paths import REPO_ROOT
from ddvc.provenance import sidecar_path, stamp
import scripts.build_architecture_role_risk_panel as role_builder
import scripts.run_architecture_state_transitions as architecture_transitions
import scripts.run_vehicle_role_models as role_models
from scripts.run_vehicle_role_models import (
    _spell_table,
    _finite_inference,
    build_transition_risk,
    fit_discrete_logit,
    fit_ppml_utilisation,
    fit_stratified_cox_sensitivity,
    prepare_candidate_panel,
    summarize_transition_support,
)


def test_model_inference_fails_closed_on_nonfinite_standard_error() -> None:
    row = pd.Series({"Estimate": 0.1, "Std. Error": float("nan"), "Pr(>|t|)": 0.5})
    try:
        _finite_inference(row, model_name="synthetic logit")
    except ValueError as exc:
        assert "unidentified or numerically unstable" in str(exc)
    else:
        raise AssertionError("non-finite inference was admitted")


def source_panel(*, pair_count: int = 4) -> pd.DataFrame:
    native = next(iter(NATIVE))
    stable = next(iter(STABLE))
    rows = []
    for pair_index in range(pair_count):
        native_pattern = (
            [1, 1, 0, 0, 1, 1]
            if pair_index % 2 == 0
            else [1, 1, 1, 1, 0, 0]
        )
        stable_pattern = (
            [1, 1, 1, 1, 0, 0]
            if pair_index % 2 == 0
            else [1, 1, 0, 0, 1, 1]
        )
        for candidate, symbol, pattern in (
            (native, "ETH/WETH", native_pattern),
            (stable, "USDC", stable_pattern),
        ):
            for week, used in zip(
                pd.date_range("2025-01-06", periods=6, freq="7D"),
                pattern,
                strict=True,
            ):
                rows.append(
                    {
                        "week": week,
                        "src": f"s{pair_index}",
                        "sink": f"t{pair_index}",
                        "vehicle": symbol,
                        "vehicle_id": candidate,
                        "candidate_type": "native" if candidate == native else "stable",
                        "total_routes": 5 * used,
                        "pair_observed_days": 1,
                    }
                )
    return pd.DataFrame(rows)


def test_prepare_candidate_panel_preserves_explicit_zero_rows() -> None:
    panel = prepare_candidate_panel(source_panel())
    assert len(panel) == 48
    assert panel["total_routes"].eq(0).sum() == 16
    assert set(panel["candidate_type"]) == {"stable", "native"}


def test_transition_risk_uses_only_consecutive_pair_active_weeks() -> None:
    risk = build_transition_risk(source_panel())
    assert len(risk) == 48
    assert risk["transition_observed"].sum() == 40
    assert risk["reentry_event"].sum() == 4
    assert risk["substitution_exit_event"].sum() == 8
    assert risk["selected_stable_native_primary_route_cessation_event"].sum() == 0
    assert risk["continuing_use_event"].sum() == 20
    assert risk["duration_weeks"].min() == 1


def test_pair_stratified_cox_uses_the_same_spells() -> None:
    risk = build_transition_risk(source_panel())
    result = fit_stratified_cox_sensitivity(risk, "substitution_exit")
    assert result["method"] == "cox_breslow_pair_stratified_cause_specific_sensitivity"
    assert result["events"] == 8
    assert result["observations"] > result["events"]


def test_selected_route_cessation_is_counted_once_per_at_risk_pair_week() -> None:
    # Two previously used candidates cease together in the selected route family.
    last_two = pd.date_range("2025-02-17", periods=2, freq="7D")
    extra = []
    native = next(iter(NATIVE))
    stable = next(iter(STABLE))
    for candidate, symbol, pattern in (
        (native, "ETH/WETH", (5, 0)),
        (stable, "USDC", (5, 0)),
    ):
        for week, routes in zip(last_two, pattern, strict=True):
            extra.append(
                {
                    "week": week,
                    "src": "role-pair",
                    "sink": "role-target",
                    "vehicle": symbol,
                    "vehicle_id": candidate,
                    "candidate_type": "native" if candidate == native else "stable",
                    "total_routes": routes,
                    "pair_observed_days": 1,
                }
            )
    source = pd.DataFrame(extra)
    panel = prepare_candidate_panel(source)
    risk = build_transition_risk(source)
    role_rows = risk[
        risk["src"].eq("role-pair") & risk["week"].eq(last_two[0])
    ]
    assert len(role_rows) == 2
    assert role_rows.loc[
        role_rows["used"].eq(1),
        "selected_stable_native_primary_route_cessation_event",
    ].eq(1).all()
    support = summarize_transition_support(source, panel, risk).iloc[0]
    assert support[
        "selected_stable_native_primary_route_cessation_event_pair_weeks"
    ] == 1
    assert support[
        "selected_stable_native_primary_route_cessation_risk_pair_weeks"
    ] == 1
    assert support["substitution_exit_risk_rows"] == 2
    combined = pd.concat([source_panel(), source], ignore_index=True)
    cox = fit_stratified_cox_sensitivity(
        build_transition_risk(combined), "substitution_exit"
    )
    assert cox["competing_selected_route_cessation_spells"] == 2
    assert cox["right_censored_spells"] >= 2


def test_candidate_models_reject_pair_level_selected_route_cessation() -> None:
    risk = build_transition_risk(source_panel())
    try:
        fit_discrete_logit(risk, "selected_stable_native_primary_route_cessation")
    except ValueError as exc:
        assert "unknown vehicle-role transition" in str(exc)
    else:
        raise AssertionError("pair-level cessation was admitted as a candidate logit")
    try:
        fit_stratified_cox_sensitivity(
            risk, "selected_stable_native_primary_route_cessation"
        )
    except ValueError as exc:
        assert "candidate-level Cox" in str(exc)
    else:
        raise AssertionError("pair-level cessation was admitted as a candidate hazard")


def test_terminal_one_and_three_week_spells_are_right_censored() -> None:
    native = next(iter(NATIVE))
    stable = next(iter(STABLE))
    rows = []
    for pair, candidate, candidate_type, weeks in (
        ("one", native, "native", 1),
        ("three", stable, "stable", 3),
    ):
        for week in pd.date_range("2025-01-06", periods=weeks, freq="7D"):
            rows.append(
                {
                    "week": week,
                    "src": pair,
                    "sink": "target",
                    "vehicle": candidate_type,
                    "vehicle_id": candidate,
                    "candidate_type": candidate_type,
                    "total_routes": 5,
                    "pair_observed_days": 1,
                }
            )
    spells = _spell_table(build_transition_risk(pd.DataFrame(rows)), "substitution_exit")
    assert sorted(spells["duration"].tolist()) == [1, 3]
    assert spells["event"].eq(0).all()
    assert spells["ends_without_observed_next"].eq(1).all()


def test_source_schema_requires_candidate_type_and_observed_day_cadence() -> None:
    source = source_panel().drop(columns="candidate_type")
    with pytest.raises(ValueError, match="candidate_type"):
        prepare_candidate_panel(source)


def test_observed_day_cadence_must_be_integer() -> None:
    source = source_panel()
    source["pair_observed_days"] = source["pair_observed_days"].astype(float)
    source.loc[source.index[0], "pair_observed_days"] = 1.5
    with pytest.raises(ValueError, match="observed-day cadence"):
        prepare_candidate_panel(source)


def test_logit_reports_exact_post_drop_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    risk = build_transition_risk(source_panel(pair_count=30))
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, data: pd.DataFrame):
            self._data = data.iloc[10:].copy()
            self._N = len(self._data)
            self.n_separation_na = 4

        def tidy(self) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "Estimate": [0.2],
                    "Std. Error": [0.1],
                    "Pr(>|t|)": [0.05],
                },
                index=["stable_candidate"],
            )

    def fake_feglm(_formula, *, data, **kwargs):
        captured["vcov"] = kwargs["vcov"]
        return FakeModel(data)

    import pyfixest as pf

    monkeypatch.setattr(pf, "feglm", fake_feglm)
    result = fit_discrete_logit(risk, "substitution_exit")
    assert result["observations"] == result["input_observations"] - 10
    assert result["dropped_observations"] == 10
    assert result["separation_dropped_observations"] == 4
    assert result["singleton_dropped_observations"] == 6
    assert result["events"] == int(
        FakeModel(
            risk[risk["used"].eq(1) & risk["transition_observed"]].reset_index()
        )._data["substitution_exit_event"].sum()
    )
    assert captured["vcov"] == {"CRV1": "owner + week_id"}


def test_real_pyfixest_logit_reports_fitted_row_identities() -> None:
    rng = np.random.default_rng(71023)
    rows: list[dict[str, object]] = []
    for pair_index in range(30):
        pair = f"s{pair_index}|t{pair_index}"
        for week_index in range(24):
            week_id = f"2025-{week_index + 1:02d}-01"
            outcomes = rng.binomial(
                1, [0.25, 0.25, 0.25, 0.40, 0.40, 0.40]
            )
            if outcomes.sum() == 0:
                outcomes[0] = 1
            elif outcomes.sum() == len(outcomes):
                outcomes[0] = 0
            for candidate_index, outcome in enumerate(outcomes):
                duration = int(rng.integers(1, 11))
                rows.append(
                    {
                        "used": 1,
                        "transition_observed": True,
                        "substitution_exit_event": int(outcome),
                        "stable_candidate": int(candidate_index >= 3),
                        "duration_2": int(duration == 2),
                        "duration_3_4": int(3 <= duration <= 4),
                        "duration_5_8": int(5 <= duration <= 8),
                        "duration_9_plus": int(duration >= 9),
                        "pair_week": f"{pair}|{week_id}",
                        "owner": f"{pair}|candidate-{candidate_index}",
                        "week_id": week_id,
                        "pair": pair,
                    }
                )
    risk = pd.DataFrame(rows)
    result = fit_discrete_logit(risk, "substitution_exit")
    assert result["observations"] == len(risk)
    assert result["events"] == int(risk["substitution_exit_event"].sum())
    assert result["pair_candidate_clusters"] == risk["owner"].nunique()
    assert result["calendar_week_clusters"] == risk["week_id"].nunique()


def test_ppml_reports_actual_pair_and_week_cluster_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = source_panel()
    second = first.copy()
    second["week"] = second["week"] + pd.DateOffset(years=1)
    panel = prepare_candidate_panel(pd.concat([first, second], ignore_index=True))
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, data: pd.DataFrame):
            self._data = data.copy()
            self._N = len(data)
            self.n_separation_na = 0

        def tidy(self) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "Estimate": [0.2],
                    "Std. Error": [0.1],
                    "Pr(>|t|)": [0.05],
                },
                index=["stable_x_2026"],
            )

    def fake_fepois(_formula, *, data, **kwargs):
        captured["vcov"] = kwargs["vcov"]
        return FakeModel(data)

    import pyfixest as pf

    monkeypatch.setattr(pf, "fepois", fake_fepois)
    result = fit_ppml_utilisation(panel)
    assert result["ordered_pair_clusters"] == panel["pair"].nunique()
    assert result["calendar_week_clusters"] == panel["week_id"].nunique()
    assert "owner_clusters" not in result
    assert captured["vcov"] == {"CRV1": "pair + week_id"}


def test_generic_and_architecture_panel_paths_are_distinct() -> None:
    assert role_builder.OUTPUT.name == "endpoint_observed_vehicle_role_risk_weekly.parquet"
    assert (
        architecture_transitions.ROLE_PANEL.name
        == "architecture_v3_v4_role_risk_weekly.parquet"
    )


def test_runner_holds_source_and_written_risk_leases_through_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer_path = tmp_path / "release" / "current.json"
    lineage = (pointer_path, tmp_path / "member.parquet")
    risk_path = tmp_path / "risk.parquet"
    result_path = tmp_path / "result.jsonl"
    support_path = tmp_path / "support.jsonl"
    events: list[str] = []
    context = SimpleNamespace(d3_certificate_path=tmp_path / "certificate.json")
    release = SimpleNamespace(
        artifacts={"choices": lineage[1]},
        bundle=SimpleNamespace(lineage_paths=lineage),
    )

    monkeypatch.setattr(
        role_models,
        "model_artifact_context",
        lambda **_kwargs: events.append("context") or context,
    )

    monkeypatch.setattr(
        role_models,
        "_d3_endpoint_release_record",
        lambda _context, path, **_kwargs: (
            events.append("d3_record") or ({}, object())
        ),
    )
    monkeypatch.setattr(
        role_models,
        "_assert_endpoint_release_matches_d3",
        lambda *_args, **_kwargs: events.append("identity"),
    )
    monkeypatch.setattr(
        role_models,
        "assert_model_artifact_certificate_identity",
        lambda _context, path: events.append("certificate_identity")
        if path == context.d3_certificate_path
        else pytest.fail("wrong D3 certificate lease"),
    )

    @contextmanager
    def source_lease(path, **_kwargs):
        assert path == pointer_path
        events.append("typed_enter")
        try:
            yield release
        finally:
            events.append("typed_exit")

    @contextmanager
    def artifact_lease(inputs, **_kwargs):
        assert inputs == [risk_path]
        events.append("risk_enter")
        try:
            yield (risk_path,)
        finally:
            events.append("risk_exit")

    monkeypatch.setattr(
        role_models, "current_endpoint_candidate_composition_release", source_lease
    )
    monkeypatch.setattr(role_models, "current_artifacts", artifact_lease)

    @contextmanager
    def certificate_lease(inputs, **_kwargs):
        assert inputs == (context.d3_certificate_path,)
        events.append("certificate_enter")
        try:
            yield
        finally:
            events.append("certificate_exit")

    monkeypatch.setattr(role_models, "serialized_read_installs", certificate_lease)
    monkeypatch.setattr(
        role_models,
        "build_vehicle_role_risk_panel_from_release",
        lambda artifacts: events.append("build") or source_panel(),
    )
    monkeypatch.setattr(
        role_models,
        "fit_ppml_utilisation",
        lambda _panel: {
            "method": "ppml_post_first_use_realised_utilisation",
            "transition": "post_first_use_stable_relative_use_in_2026",
        },
    )
    monkeypatch.setattr(
        role_models,
        "fit_discrete_logit",
        lambda _risk, transition: {
            "method": "discrete_time_logit",
            "transition": transition,
        },
    )
    monkeypatch.setattr(
        role_models,
        "fit_stratified_cox_sensitivity",
        lambda _risk, transition: {
            "method": "cox_breslow_pair_stratified_cause_specific_sensitivity",
            "transition": transition,
        },
    )
    monkeypatch.setattr(
        role_models,
        "summarize_transition_support",
        lambda *_args: pd.DataFrame({"rows": [1]}),
    )

    def write_panel(_frame, path, **_kwargs):
        assert path == risk_path
        events.append("risk_write")
        return path

    def write_exhibit(_frame, path, *, inputs, **_kwargs):
        assert inputs == [*lineage, risk_path]
        events.append("result_write" if path == result_path else "support_write")
        return path

    monkeypatch.setattr(role_models, "write_model_panel", write_panel)
    monkeypatch.setattr(role_models, "write_model_exhibit", write_exhibit)
    role_models.run(
        pointer_path=pointer_path,
        risk_path=risk_path,
        result_path=result_path,
        support_path=support_path,
        root=tmp_path,
        environment={},
    )
    assert events == [
        "context",
        "certificate_enter",
        "certificate_identity",
        "d3_record",
        "typed_enter",
        "identity",
        "build",
        "risk_write",
        "risk_enter",
        "result_write",
        "support_write",
        "risk_exit",
        "typed_exit",
        "certificate_exit",
    ]


def test_runner_rejects_certificate_rebuild_between_context_and_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    certificate = tmp_path / "certificate.json"
    certificate.write_text('{"generation":"first"}\n', encoding="utf-8")
    stamp(
        certificate,
        code_sources=["tests/test_vehicle_role_models.py"],
        inputs=[],
    )
    provenance = sidecar_path(certificate)
    context = ModelArtifactContext(
        d3_generation="a" * 64,
        d3_certificate_relative="certificate.json",
        d3_certificate_path=certificate,
        d3_certificate_bytes=certificate.stat().st_size,
        d3_certificate_sha256=file_sha256(certificate),
        d3_certificate_provenance_path=provenance,
        d3_certificate_provenance_sha256=file_sha256(provenance),
        d3_input_relatives=frozenset(),
        d3_input_records={},
    )
    certificate.write_text('{"generation":"second"}\n', encoding="utf-8")
    stamp(
        certificate,
        code_sources=["tests/test_vehicle_role_models.py"],
        inputs=[],
    )
    monkeypatch.setattr(role_models, "model_artifact_context", lambda **_kwargs: context)
    monkeypatch.setattr(
        role_models,
        "_d3_endpoint_release_record",
        lambda *_args, **_kwargs: pytest.fail(
            "D3 endpoint record was read after certificate identity changed"
        ),
    )
    with pytest.raises(ValueError, match="changed between verification and lease"):
        role_models.run(
            pointer_path=tmp_path / "release.json",
            root=tmp_path,
            environment={},
        )


def _synthetic_context(root: Path, members: set[str]) -> ModelArtifactContext:
    return ModelArtifactContext(
        d3_generation="a" * 64,
        d3_certificate_relative="certificate.json",
        d3_certificate_path=root / "certificate.json",
        d3_certificate_bytes=0,
        d3_certificate_sha256="b" * 64,
        d3_certificate_provenance_path=root / "certificate.json.prov.json",
        d3_certificate_provenance_sha256="c" * 64,
        d3_input_relatives=frozenset(members),
        d3_input_records={},
    )


def test_d3_nonmember_fails_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "outside.json"
    context = _synthetic_context(tmp_path, set())
    monkeypatch.setattr(role_models, "model_artifact_context", lambda **_kwargs: context)

    @contextmanager
    def certificate_lease(inputs, **_kwargs):
        assert inputs == (context.d3_certificate_path,)
        yield

    monkeypatch.setattr(role_models, "serialized_read_installs", certificate_lease)
    monkeypatch.setattr(
        role_models,
        "assert_model_artifact_certificate_identity",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        role_models,
        "current_endpoint_candidate_composition_release",
        lambda *_args, **_kwargs: pytest.fail("source was read before D3 admission"),
    )
    with pytest.raises(ValueError, match="outside the bound D3 release"):
        role_models.run(pointer_path=source, root=tmp_path, environment={})


def test_role_builder_is_support_only_not_a_d3_input_or_stage() -> None:
    specification = json.loads(
        (REPO_ROOT / "docs/specification-lock.json").read_text(encoding="utf-8")
    )
    inputs = {
        value
        for claim in specification["claims"]
        for value in claim.get("inputs", [])
    }
    assert "data/processed/endpoint_observed_vehicle_role_risk_weekly.parquet" not in inputs
    registry = (REPO_ROOT / "src/ddvc/d3_stage_registry.py").read_text(encoding="utf-8")
    assert "build_architecture_role_risk_panel.py" not in registry

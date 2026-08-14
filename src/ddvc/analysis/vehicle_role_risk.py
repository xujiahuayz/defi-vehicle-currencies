"""Observed-support risk sets for realised vehicle-role models.

The candidate set is deliberately narrow: for an ordered source-destination
pair, a stable/native intermediary enters when it is first realised.  Crossing
that candidate with later active pair-weeks creates genuine zero-use
observations after first use.  Formation before first use remains unobserved.
The construction does not create or impute an economically feasible route
opportunity set.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from ddvc.artifact_release import file_sha256, is_sha256
from ddvc.asset_types import classify
from ddvc.endpoint_candidate_composition import CHOICE_KEYS, PAIR_KEYS
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND,
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION,
)
from ddvc.provenance import sidecar_path


PANEL_KEYS = ["week", "src", "sink", "vehicle_id"]
OWNER_KEYS = ["src", "sink", "vehicle_id"]
PAIR_WEEK_KEYS = ["week", "src", "sink"]
CANDIDATE_SET_DEFINITION = (
    "stable_or_native_candidate_from_first_realised_week_through_"
    "later_active_ordered_pair_weeks"
)
OPPORTUNITY_SET_STATUS = "economic_route_feasibility_not_observed_or_imputed"


@dataclass(frozen=True)
class CompleteEndpointRelease:
    """Exact member paths admitted by a two-phase size-then-hash check."""

    generation_id: str
    pointer_path: Path
    artifacts: Mapping[str, Path]
    expected_bytes: Mapping[str, int]


def _pointer_record(pointer_path: Path) -> dict[str, object]:
    try:
        record = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("endpoint release pointer is missing or invalid") from error
    if not isinstance(record, dict):
        raise ValueError("endpoint release pointer is not a JSON object")
    if record.get("kind") != ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_KIND:
        raise ValueError("endpoint release pointer has the wrong kind")
    if (
        record.get("schema_version")
        != ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_SCHEMA_VERSION
    ):
        raise ValueError("endpoint release pointer has the wrong schema version")
    generation = record.get("generation_id")
    if not is_sha256(generation):
        raise ValueError("endpoint release pointer has an invalid generation identity")
    return record


def assert_endpoint_release_sizes_complete(pointer_path: Path) -> CompleteEndpointRelease:
    """Fail before reading any release member unless every member has final size.

    The first phase reads only the small pointer and provenance records, then
    checks all four member sizes with ``stat``.  Artifact hashing begins only
    after every size agrees.  A partially transferred Parquet file is therefore
    never opened, even if another member has already reached its final size.
    """

    pointer_path = Path(pointer_path)
    pointer = _pointer_record(pointer_path)
    generation = str(pointer["generation_id"])
    raw_artifacts = pointer.get("artifacts")
    if not isinstance(raw_artifacts, dict) or set(raw_artifacts) != set(
        ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES
    ):
        raise ValueError(
            "endpoint release pointer does not name the exact four-member perimeter"
        )

    generation_dir = pointer_path.parent / "generations" / generation
    paths: dict[str, Path] = {}
    expected_bytes: dict[str, int] = {}
    for name, expected_filename in (
        ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES.items()
    ):
        raw = raw_artifacts[name]
        if not isinstance(raw, dict) or raw.get("filename") != expected_filename:
            raise ValueError(f"endpoint release pointer has an invalid filename: {name}")
        expected_hash = raw.get("sha256")
        expected_provenance_hash = raw.get("provenance_sha256")
        if not is_sha256(expected_hash) or not is_sha256(expected_provenance_hash):
            raise ValueError(f"endpoint release pointer has an invalid digest: {name}")
        artifact = generation_dir / expected_filename
        provenance_path = sidecar_path(artifact)
        if not provenance_path.is_file():
            raise FileNotFoundError(f"endpoint release provenance is missing: {name}")
        if file_sha256(provenance_path) != expected_provenance_hash:
            raise ValueError(f"endpoint release provenance digest disagrees: {name}")
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"endpoint release provenance is invalid: {name}") from error
        size = provenance.get("artefact_bytes")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"endpoint release provenance lacks exact bytes: {name}")
        if provenance.get("artefact_sha256") not in {None, expected_hash}:
            raise ValueError(f"endpoint release provenance identifies different bytes: {name}")
        paths[name] = artifact
        expected_bytes[name] = size

    # Phase one: do not hash or open any member until every stat size agrees.
    for name, artifact in paths.items():
        try:
            observed_size = artifact.stat().st_size
        except FileNotFoundError as error:
            raise FileNotFoundError(f"endpoint release member is missing: {name}") from error
        if observed_size != expected_bytes[name]:
            raise RuntimeError(
                "endpoint release is incomplete; no member was read: "
                f"{name} has {observed_size} of {expected_bytes[name]} bytes"
            )

    return CompleteEndpointRelease(generation, pointer_path, paths, expected_bytes)


def assert_complete_endpoint_release(pointer_path: Path) -> CompleteEndpointRelease:
    """Admit exact member hashes only after the all-member size preflight."""

    complete = assert_endpoint_release_sizes_complete(pointer_path)
    pointer = _pointer_record(complete.pointer_path)
    raw_artifacts = pointer["artifacts"]
    assert isinstance(raw_artifacts, dict)
    # Phase two: all members have their published length, so content hashing is safe.
    expected_hashes = {
        name: str(raw_artifacts[name]["sha256"])
        for name in ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES
    }
    for name, artifact in complete.artifacts.items():
        if file_sha256(artifact) != expected_hashes[name]:
            raise ValueError(f"endpoint release member digest disagrees: {name}")
    return complete


def _normalise_dates(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    output = frame.copy()
    values = pd.to_datetime(output["date"], errors="raise", utc=True)
    output["date"] = values.dt.tz_localize(None).dt.normalize()
    output["week"] = output["date"] - pd.to_timedelta(output["date"].dt.weekday, unit="D")
    if output["week"].isna().any():
        raise ValueError(f"{label} contains a missing calendar date")
    return output


def _candidate_metadata(choices: pd.DataFrame) -> pd.DataFrame:
    keys = ["src", "tgt", "candidate_address"]
    for column in ("candidate_type", "candidate_symbol"):
        conflicts = choices.groupby(keys, observed=True)[column].nunique(dropna=True)
        if conflicts.gt(1).any():
            raise ValueError(f"endpoint choices assign conflicting {column} metadata")
    return (
        choices.groupby(keys, observed=True, as_index=False)
        .agg(
            vehicle=("candidate_symbol", "first"),
            candidate_type=("candidate_type", "first"),
            candidate_first_observed_date=("date", "min"),
            candidate_last_observed_date=("date", "max"),
        )
    )


def add_transition_taxonomy(panel: pd.DataFrame) -> pd.DataFrame:
    """Attach mutually exclusive next-week outcomes without bridging gaps."""

    required = {*PANEL_KEYS, "used", "selected_pair_routes"}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"vehicle-role panel lacks transition columns: {missing}")
    if panel.duplicated(PANEL_KEYS).any():
        raise ValueError("vehicle-role panel repeats a pair-candidate-week")
    data = panel.sort_values([*OWNER_KEYS, "week"], kind="stable").reset_index(drop=True)
    grouped = data.groupby(OWNER_KEYS, observed=True, sort=False)
    data["previous_week"] = grouped["week"].shift()
    data["previous_used"] = grouped["used"].shift().astype("Int8")
    data["next_week"] = grouped["week"].shift(-1)
    data["next_used"] = grouped["used"].shift(-1).astype("Int8")
    data["consecutive_previous"] = data["week"].sub(data["previous_week"]).dt.days.eq(7)
    data["consecutive_next"] = data["next_week"].sub(data["week"]).dt.days.eq(7)
    data["transition_observed"] = data["consecutive_next"]
    data["prior_use_observed"] = grouped["used"].cumsum().sub(data["used"]).gt(0)

    next_pair_routes = grouped["selected_pair_routes"].shift(-1)
    data["next_selected_pair_routes"] = next_pair_routes.where(data["consecutive_next"])
    observed = data["consecutive_next"]
    current_used = data["used"].eq(1)
    next_used = data["next_used"].eq(1)
    loss = observed & current_used & ~next_used
    outcomes = {
        "reentry_event": observed & ~current_used & next_used & data["prior_use_observed"],
        "continuing_use_event": observed & current_used & next_used,
        "substitution_exit_event": loss & data["next_selected_pair_routes"].gt(0),
        "selected_stable_native_primary_route_cessation_event": (
            loss & data["next_selected_pair_routes"].eq(0)
        ),
        "continuing_nonuse_event": observed & ~current_used & ~next_used,
    }
    for column, values in outcomes.items():
        data[column] = values.astype("Int8").where(observed, pd.NA)

    labels = np.select(
        [
            outcomes["reentry_event"],
            outcomes["continuing_use_event"],
            outcomes["substitution_exit_event"],
            outcomes["selected_stable_native_primary_route_cessation_event"],
            outcomes["continuing_nonuse_event"],
        ],
        [
            "reentry_after_prior_realised_use",
            "continuing_use",
            "substitution_exit",
            "selected_stable_native_primary_route_cessation",
            "continuing_nonuse",
        ],
        default="not_observed_across_consecutive_calendar_weeks",
    )
    data["transition_kind"] = labels
    return data


def build_vehicle_role_risk_panel(
    choices: pd.DataFrame,
    pair_support: pd.DataFrame,
) -> pd.DataFrame:
    """Construct the explicit pair-candidate-week observed-support risk set."""

    choice_required = {
        *CHOICE_KEYS,
        "candidate_symbol",
        "candidate_type",
        "route_count",
    }
    support_required = {*PAIR_KEYS, "market_route_count", "primary_choice_route_count"}
    missing_choices = sorted(choice_required - set(choices.columns))
    missing_support = sorted(support_required - set(pair_support.columns))
    if missing_choices:
        raise ValueError(f"endpoint choices lack columns: {missing_choices}")
    if missing_support:
        raise ValueError(f"endpoint pair support lacks columns: {missing_support}")
    if choices.duplicated(CHOICE_KEYS).any():
        raise ValueError("endpoint choices repeat a registered choice key")
    if pair_support.duplicated(PAIR_KEYS).any():
        raise ValueError("endpoint pair support repeats a pair-date key")

    selected = _normalise_dates(choices, label="endpoint choices")
    support = _normalise_dates(pair_support, label="endpoint pair support")
    canonical_type = selected["candidate_address"].map(lambda value: classify(value)[1])
    supplied_type = selected["candidate_type"].astype(str).str.lower()
    mismatch = supplied_type.ne(canonical_type)
    if mismatch.any():
        examples = selected.loc[
            mismatch, ["candidate_address", "candidate_type"]
        ].head(3).to_dict("records")
        raise ValueError(
            "endpoint candidate_type metadata disagrees with canonical classification: "
            f"{examples}"
        )
    selected["candidate_type"] = canonical_type
    selected = selected[selected["candidate_type"].isin(("stable", "native"))].copy()
    if selected.empty:
        raise ValueError("endpoint choices contain no realised stable/native candidate")
    for frame, columns, label in (
        (selected, ("route_count",), "endpoint choices"),
        (
            support,
            ("market_route_count", "primary_choice_route_count"),
            "endpoint pair support",
        ),
    ):
        for column in columns:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
            if frame[column].lt(0).any() or not np.isfinite(frame[column]).all():
                raise ValueError(f"{label} contains an invalid {column}")
    if selected["route_count"].le(0).any():
        raise ValueError("endpoint choices contain a non-positive realised route count")
    if support["market_route_count"].le(0).any():
        raise ValueError("endpoint pair support contains a non-positive active-pair count")

    realised_by_day = (
        selected.groupby(PAIR_KEYS, observed=True, as_index=False)["route_count"]
        .sum()
        .rename(columns={"route_count": "choice_route_count"})
    )
    accounting = support[[*PAIR_KEYS, "primary_choice_route_count"]].merge(
        realised_by_day,
        on=PAIR_KEYS,
        how="outer",
        indicator=True,
        validate="one_to_one",
    )
    if accounting["_merge"].eq("right_only").any():
        raise ValueError("endpoint choices include a pair-date outside observed pair support")
    accounting["choice_route_count"] = accounting["choice_route_count"].fillna(0)
    if not accounting["choice_route_count"].eq(
        accounting["primary_choice_route_count"]
    ).all():
        raise ValueError("endpoint choices do not reconcile to primary pair-support counts")

    metadata = _candidate_metadata(selected)
    pair_weeks = (
        support.groupby(["week", "src", "tgt"], observed=True, as_index=False)
        .agg(
            pair_market_routes=("market_route_count", "sum"),
            pair_primary_choice_routes=("primary_choice_route_count", "sum"),
            pair_observed_days=("date", "nunique"),
            pair_week_first_date=("date", "min"),
            pair_week_last_date=("date", "max"),
        )
    )
    pair_windows = (
        pair_weeks.groupby(["src", "tgt"], observed=True, as_index=False)
        .agg(
            pair_first_supported_week=("week", "min"),
            pair_last_supported_week=("week", "max"),
        )
    )
    candidate_weeks = (
        selected.groupby(
            ["week", "src", "tgt", "candidate_address"],
            observed=True,
            as_index=False,
        )
        .agg(total_routes=("route_count", "sum"))
    )
    grid = pair_weeks.merge(
        metadata,
        on=["src", "tgt"],
        how="inner",
        validate="many_to_many",
    )
    grid = grid.merge(
        pair_windows,
        on=["src", "tgt"],
        how="left",
        validate="many_to_one",
    )
    grid["candidate_first_observed_week"] = (
        grid["candidate_first_observed_date"]
        - pd.to_timedelta(grid["candidate_first_observed_date"].dt.weekday, unit="D")
    )
    grid = grid[
        grid["week"].ge(grid["candidate_first_observed_week"])
    ].copy()
    grid = grid.merge(
        candidate_weeks,
        on=["week", "src", "tgt", "candidate_address"],
        how="left",
        validate="one_to_one",
    )
    grid["total_routes"] = grid["total_routes"].fillna(0).astype("int64")
    grid = grid.rename(columns={"tgt": "sink", "candidate_address": "vehicle_id"})
    grid["used"] = grid["total_routes"].gt(0).astype("int8")
    grid["selected_pair_routes"] = grid.groupby(
        PAIR_WEEK_KEYS, observed=True
    )["total_routes"].transform("sum")
    grid["observed_support_status"] = np.where(
        grid["used"].eq(1), "realised_use", "observed_pair_week_zero_use"
    )
    grid["candidate_set_definition"] = CANDIDATE_SET_DEFINITION
    grid["opportunity_set_status"] = OPPORTUNITY_SET_STATUS
    if grid.duplicated(PANEL_KEYS).any():
        raise ValueError("vehicle-role risk construction repeats a pair-candidate-week")
    return add_transition_taxonomy(grid)


def build_vehicle_role_risk_panel_from_release(
    artifacts: Mapping[str, Path],
) -> pd.DataFrame:
    """Build the risk panel from the canonical endpoint release perimeter."""

    required = set(ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_FILENAMES)
    if set(artifacts) != required:
        raise ValueError("endpoint release has an invalid artifact perimeter")
    choices = pd.read_parquet(
        artifacts["choices"],
        columns=[
            "date",
            "src",
            "tgt",
            "candidate_address",
            "integration_scope",
            "venue_sequence",
            "candidate_symbol",
            "candidate_type",
            "route_count",
        ],
    )
    pair_support = pd.read_parquet(
        artifacts["pair_support"],
        columns=[
            "date",
            "src",
            "tgt",
            "market_route_count",
            "primary_choice_route_count",
        ],
    )
    return build_vehicle_role_risk_panel(choices, pair_support)

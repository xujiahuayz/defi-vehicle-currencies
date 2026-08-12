"""Exact two-leg stable/native vehicle choice with explicit exclusions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

from ddvc.asset_types import backing, canonical_token, classify
from ddvc.fetch.sources import DEX_SOURCES
from ddvc.realised import ROUTE_COLUMNS as REALISED_ROUTE_COLUMNS, extract_realised_routes
from ddvc.route_roles import component_eligibility


ENDPOINT_CANDIDATE_COMPOSITION_SCIENTIFIC_SOURCES = (
    "src/ddvc/asset_types.py",
    "src/ddvc/endpoint_candidate_composition.py",
    "src/ddvc/fetch/sources.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_roles.py",
)
ROUTE_KEYS = ["tx_hash", "component_id"]
PAIR_KEYS = ["date", "src", "tgt"]
CHOICE_KEYS = [
    *PAIR_KEYS,
    "candidate_address",
    "integration_scope",
    "venue_sequence",
]
ROUTE_INPUT_COLUMNS = list(dict.fromkeys(REALISED_ROUTE_COLUMNS))
MAGNITUDE_COLUMNS = [
    "route_count",
    "raw_value_supported_routes",
    "raw_value_usd",
    "within_2x_routes",
    "within_2x_value_usd",
    "within_20pct_routes",
    "within_20pct_value_usd",
]
MAGNITUDE_COUNT_COLUMNS = [
    "route_count",
    "raw_value_supported_routes",
    "within_2x_routes",
    "within_20pct_routes",
]
MAGNITUDE_VALUE_COLUMNS = [
    "raw_value_usd",
    "within_2x_value_usd",
    "within_20pct_value_usd",
]
CHOICE_COLUMNS = [
    *CHOICE_KEYS,
    "candidate_symbol",
    "candidate_type",
    "backing_regime",
    "hop1_venue",
    "hop2_venue",
    "protocol_sequence",
    *MAGNITUDE_COLUMNS,
]
CHOICE_AUDIT_KEYS = ["date", "tx_hash", "component_id"]
CHOICE_AUDIT_INTEGER_COLUMNS = ["component_id"]
CHOICE_AUDIT_COLUMNS = [
    *CHOICE_AUDIT_KEYS,
    *CHOICE_KEYS[1:],
    "candidate_symbol",
    "candidate_type",
    "backing_regime",
    "hop1_venue",
    "hop2_venue",
    "protocol_sequence",
    *MAGNITUDE_COLUMNS,
]
PAIR_SUPPORT_COLUMNS = [
    *PAIR_KEYS,
    "day_source_component_count",
    "day_accounted_component_count",
    "day_unpaired_exclusion_component_count",
    "day_event_collision_component_count",
    "day_event_collision_value_missing_component_count",
    "day_event_collision_observed_abs_leg_value_usd_upper_bound",
    "market_route_count",
    "source_pair_component_count",
    "event_collision_component_count",
    "event_collision_value_missing_component_count",
    "event_collision_observed_abs_leg_value_usd_upper_bound",
    "primary_choice_route_count",
    "native_choice_route_count",
    "stable_choice_route_count",
    "native_within_20pct_routes",
    "stable_within_20pct_routes",
    "native_within_20pct_value_usd",
    "stable_within_20pct_value_usd",
    "primary_choice_transaction_count",
    "primary_choice_multi_component_transaction_count",
    "primary_choice_component_excess_count",
    "duplicate_choice_transaction_candidate_count",
    "direct_route_count",
    "direct_split_route_count",
    "other_candidate_route_count",
    "multiple_intermediary_route_count",
    "split_or_join_route_count",
    "nonsequential_two_leg_route_count",
    "pair_first_supported_date",
    "pair_last_supported_date",
    "pair_entry_on_day",
    "pair_last_observed_on_day",
    "pair_support_reason",
]
PAIR_SUPPORT_COUNT_COLUMNS = [
    column
    for column in PAIR_SUPPORT_COLUMNS
    if column.endswith("_count") or column.endswith("_routes")
]
PAIR_SUPPORT_VALUE_COLUMNS = [
    "day_event_collision_observed_abs_leg_value_usd_upper_bound",
    "event_collision_observed_abs_leg_value_usd_upper_bound",
    "native_within_20pct_value_usd",
    "stable_within_20pct_value_usd",
]
EXCLUSION_KEYS = [
    "date",
    "exclusion_reason",
    "src",
    "tgt",
    "candidate_address",
    "candidate_type",
    "audit_tx_hash",
    "audit_component_id",
]
COLLISION_AUDIT_COLUMNS = [
    "collision_event_coordinate_count",
    "collision_row_count",
    "collision_source_count",
    "collision_sources",
    "component_venues",
    "collision_log_indices",
    "collision_first_timestamp_utc",
    "collision_last_timestamp_utc",
    "collision_value_missing_leg_count",
    "collision_observed_abs_leg_value_usd_upper_bound",
]
COLLISION_AUDIT_INTEGER_COLUMNS = [
    "audit_component_id",
    "collision_event_coordinate_count",
    "collision_row_count",
    "collision_source_count",
    "collision_first_timestamp_utc",
    "collision_last_timestamp_utc",
    "collision_value_missing_leg_count",
]
COLLISION_AUDIT_VALUE_COLUMNS = [
    "collision_observed_abs_leg_value_usd_upper_bound"
]
EXCLUSION_COLUMNS = [*EXCLUSION_KEYS, *MAGNITUDE_COLUMNS, *COLLISION_AUDIT_COLUMNS]
INCLUDED = "included_primary_vehicle_choice"
EVENT_COLLISION = "provider_event_coordinate_collision"
PAIR_REASONS = (
    INCLUDED,
    "direct_route",
    "direct_split",
    "other_candidate",
    "multiple_intermediaries",
    "split_or_join",
    "nonsequential_two_leg",
)
EXCLUSION_REASONS = frozenset(
    {
        "direct_route",
        "direct_split",
        "other_candidate",
        "multiple_intermediaries",
        "split_or_join",
        "round_trip",
        "cyclic_route",
        "ambiguous_route_class",
        "nonsequential_two_leg",
        EVENT_COLLISION,
    }
)
PAIR_REASON_COLUMNS = {
    INCLUDED: "primary_choice_route_count",
    "direct_route": "direct_route_count",
    "direct_split": "direct_split_route_count",
    "other_candidate": "other_candidate_route_count",
    "multiple_intermediaries": "multiple_intermediary_route_count",
    "split_or_join": "split_or_join_route_count",
    "nonsequential_two_leg": "nonsequential_two_leg_route_count",
}
PRIMARY_TYPES = frozenset({"native", "stable"})
CLEAN_ROUTE_CLASSES = frozenset({"single", "coherent"})
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_VERSION_SUFFIX = re.compile(r"_v[0-9]+$")


@dataclass(frozen=True)
class EndpointCandidateComposition:
    """Primary choice cells, keyed audit, support, and exclusive exclusions."""

    choices: pd.DataFrame
    choice_audit: pd.DataFrame
    pair_support: pd.DataFrame
    exclusions: pd.DataFrame


def _empty_bundle() -> EndpointCandidateComposition:
    return EndpointCandidateComposition(
        pd.DataFrame(columns=CHOICE_COLUMNS),
        pd.DataFrame(columns=CHOICE_AUDIT_COLUMNS),
        pd.DataFrame(columns=PAIR_SUPPORT_COLUMNS),
        pd.DataFrame(columns=EXCLUSION_COLUMNS),
    )


def _canonical_address(value: object, *, field: str) -> str:
    address = canonical_token(value)
    if address is None or _ADDRESS.fullmatch(address) is None:
        raise ValueError(f"vehicle choice has invalid {field} address: {value!r}")
    return address


def _protocol_family(venue: str) -> str:
    if venue not in DEX_SOURCES:
        raise ValueError(f"vehicle choice has unknown venue: {venue!r}")
    return _VERSION_SUFFIX.sub("", venue)


def _sum_supported(values: pd.Series, support: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    return float(numeric.where(support, 0.0).sum())


def _summarize(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*keys, *MAGNITUDE_COLUMNS])
    grouped = frame.groupby(keys, as_index=False, sort=True, dropna=False)
    return grouped.agg(
        route_count=("tx_hash", "size"),
        raw_value_supported_routes=("raw_value_supported", "sum"),
        raw_value_usd=("candidate_value_usd", lambda values: _sum_supported(values, pd.to_numeric(values, errors="coerce").gt(0))),
        within_2x_routes=("within_2x", "sum"),
        within_2x_value_usd=("candidate_value_usd", lambda values: _sum_supported(values, frame.loc[values.index, "within_2x"])),
        within_20pct_routes=("within_20pct", "sum"),
        within_20pct_value_usd=("candidate_value_usd", lambda values: _sum_supported(values, frame.loc[values.index, "within_20pct"])),
    )


def _joined_unique(values: pd.Series) -> str:
    return ">".join(sorted({str(value) for value in values if str(value)}))


def _joined_tokens(values: pd.Series) -> str:
    return ">".join(
        sorted(
            {
                token
                for value in values
                for token in str(value).split(">")
                if token
            }
        )
    )


def _collision_metadata(rows: pd.DataFrame) -> pd.DataFrame:
    """Describe components touched by non-commensurate cross-provider coordinates."""

    identity = ["tx_hash", "log_index"]
    same_source = rows.duplicated(["source", *identity], keep=False)
    if same_source.any():
        sample = rows.loc[same_source, ["source", *identity]].iloc[0].to_dict()
        raise ValueError(f"vehicle choice contains duplicate event identity within source: {sample}")
    cross_source = rows.groupby(identity, sort=False)["source"].transform("nunique").gt(1)
    if not cross_source.any():
        return pd.DataFrame(columns=[*ROUTE_KEYS, *COLLISION_AUDIT_COLUMNS])

    collision_rows = rows.loc[cross_source].copy()
    event_sources = (
        collision_rows.groupby(identity, as_index=False, sort=True)["source"]
        .agg(_joined_unique)
        .rename(columns={"source": "event_sources"})
    )
    collision_rows = collision_rows.merge(
        event_sources,
        on=identity,
        how="left",
        validate="many_to_one",
    )
    component_keys = collision_rows[ROUTE_KEYS].drop_duplicates()
    affected = rows.merge(component_keys, on=ROUTE_KEYS, how="inner", validate="many_to_many")
    component_values = pd.to_numeric(affected["amount_usd"], errors="coerce").abs()
    affected = affected.assign(
        _observed_abs_value=component_values.fillna(0.0),
        _missing_value=component_values.isna(),
    )
    component = affected.groupby(ROUTE_KEYS, as_index=False, sort=True).agg(
        component_venues=("source", _joined_unique),
        collision_first_timestamp_utc=("timestamp_utc", "min"),
        collision_last_timestamp_utc=("timestamp_utc", "max"),
        collision_value_missing_leg_count=("_missing_value", "sum"),
        collision_observed_abs_leg_value_usd_upper_bound=("_observed_abs_value", "sum"),
    )
    event = collision_rows.groupby(ROUTE_KEYS, as_index=False, sort=True).agg(
        collision_event_coordinate_count=("log_index", "nunique"),
        collision_row_count=("log_index", "size"),
        collision_sources=("event_sources", _joined_tokens),
        collision_log_indices=("log_index", lambda values: ">".join(str(int(value)) for value in sorted(set(values)))),
    )
    event["collision_source_count"] = event["collision_sources"].map(
        lambda value: len(str(value).split(">")) if value else 0
    )
    return component.merge(event, on=ROUTE_KEYS, how="inner", validate="one_to_one")[
        [*ROUTE_KEYS, *COLLISION_AUDIT_COLUMNS]
    ]


def _component_frame(legs: pd.DataFrame, day: str) -> pd.DataFrame:
    missing = sorted(set(ROUTE_INPUT_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"vehicle choice is missing columns: {', '.join(missing)}")
    rows = legs[ROUTE_INPUT_COLUMNS].copy()
    if rows.empty:
        return pd.DataFrame()
    rows["tx_hash"] = rows["tx_hash"].astype(str).str.lower()
    rows["component_id"] = pd.to_numeric(rows["component_id"], errors="raise").astype("int64")
    rows["token_in"] = rows["token_in"].map(lambda value: _canonical_address(value, field="token_in"))
    rows["token_out"] = rows["token_out"].map(lambda value: _canonical_address(value, field="token_out"))
    rows["source"] = rows["source"].map(str)
    for venue in rows["source"].unique():
        _protocol_family(venue)
    rows["amount_usd"] = pd.to_numeric(rows["amount_usd"], errors="coerce")
    rows["log_index"] = pd.to_numeric(rows["log_index"], errors="raise").astype("int64")
    rows["timestamp_utc"] = pd.to_numeric(rows["timestamp_utc"], errors="raise")
    if rows["timestamp_utc"].isna().any():
        raise ValueError("vehicle choice contains a missing transaction timestamp")
    expected_day = pd.to_datetime(day, format="%Y%m%d", errors="raise", utc=True)
    observed_days = pd.to_datetime(
        rows["timestamp_utc"], unit="s", errors="raise", utc=True
    ).dt.normalize()
    if not observed_days.eq(expected_day).all():
        raise ValueError("vehicle choice transaction timestamp falls outside supplied UTC day")
    collision_metadata = _collision_metadata(rows)
    rows = rows.sort_values([*ROUTE_KEYS, "log_index"], kind="stable")
    route_classes = rows.groupby(ROUTE_KEYS)["route_class"].nunique(dropna=False)
    if route_classes.gt(1).any():
        raise ValueError("vehicle choice component mixes route classes")

    first = rows.drop_duplicates(ROUTE_KEYS, keep="first").rename(
        columns={
            "token_in": "first_token_in",
            "token_out": "first_token_out",
        }
    )
    last = rows.drop_duplicates(ROUTE_KEYS, keep="last").rename(
        columns={
            "token_in": "last_token_in",
            "token_out": "last_token_out",
        }
    )
    components = rows.groupby(ROUTE_KEYS, as_index=False, sort=True).agg(
        legs=("log_index", "size"),
        route_class=("route_class", "first"),
    ).merge(
        first[ROUTE_KEYS + ["first_token_in", "first_token_out"]],
        on=ROUTE_KEYS,
        how="left",
        validate="one_to_one",
    ).merge(
        last[ROUTE_KEYS + ["last_token_in", "last_token_out"]],
        on=ROUTE_KEYS,
        how="left",
        validate="one_to_one",
    )
    components["selection_reason"] = "ambiguous_route_class"
    components["src"] = ""
    components["tgt"] = ""
    components["candidate_address"] = ""
    components["candidate_symbol"] = ""
    components["candidate_type"] = "none"
    components["hop1_venue"] = ""
    components["hop2_venue"] = ""
    components["candidate_value_usd"] = np.nan
    components["within_2x"] = False
    components["within_20pct"] = False
    components = components.merge(
        collision_metadata,
        on=ROUTE_KEYS,
        how="left",
        validate="one_to_one",
    )
    for column in (
        "collision_event_coordinate_count",
        "collision_row_count",
        "collision_source_count",
        "collision_first_timestamp_utc",
        "collision_last_timestamp_utc",
        "collision_value_missing_leg_count",
    ):
        components[column] = components[column].fillna(0).astype("int64")
    components["collision_observed_abs_leg_value_usd_upper_bound"] = components[
        "collision_observed_abs_leg_value_usd_upper_bound"
    ].fillna(0.0)
    for column in ("collision_sources", "component_venues", "collision_log_indices"):
        components[column] = components[column].fillna("")

    clean = rows[rows["route_class"].isin(CLEAN_ROUTE_CLASSES)].copy()
    if not clean.empty:
        eligibility = component_eligibility(clean, keys=ROUTE_KEYS)
        cyclic_keys = set(eligibility.cyclic.itertuples(index=False, name=None))
        ambiguous_keys = set(eligibility.ambiguous.itertuples(index=False, name=None))
        eligible = eligibility.eligible[ROUTE_KEYS + ["src", "tgt"]].copy()
        eligible_keys = set(eligible[ROUTE_KEYS].itertuples(index=False, name=None))
        keys = list(components[ROUTE_KEYS].itertuples(index=False, name=None))
        cyclic_mask = pd.Series([key in cyclic_keys for key in keys], index=components.index)
        round_trip = cyclic_mask & components["first_token_in"].eq(components["last_token_out"])
        components.loc[cyclic_mask, "selection_reason"] = "cyclic_route"
        components.loc[round_trip, "selection_reason"] = "round_trip"
        components.loc[[key in ambiguous_keys for key in keys], "selection_reason"] = "split_or_join"

        components = components.merge(eligible, on=ROUTE_KEYS, how="left", suffixes=("", "_eligible"), validate="one_to_one")
        for endpoint in ("src", "tgt"):
            components[endpoint] = components[f"{endpoint}_eligible"].fillna(components[endpoint])
            components = components.drop(columns=f"{endpoint}_eligible")

        realised = extract_realised_routes(
            rows[REALISED_ROUTE_COLUMNS],
            require_positive_value=False,
        )
        realised_identity = realised.groupby(ROUTE_KEYS, as_index=False).agg(
            intermediary_count=("vehicle", "nunique"),
            candidate_address_observed=("vehicle", "first"),
        )
        components = components.merge(realised_identity, on=ROUTE_KEYS, how="left", validate="one_to_one")
        components["intermediary_count"] = components["intermediary_count"].fillna(0).astype("int64")
        components["candidate_address"] = components["candidate_address_observed"].fillna(components["candidate_address"])
        components = components.drop(columns="candidate_address_observed")

        path_identity = components[
            ROUTE_KEYS + ["src", "tgt", "candidate_address"]
        ]
        path_legs = clean.merge(
            path_identity,
            on=ROUTE_KEYS,
            how="left",
            validate="many_to_one",
        )
        path_legs["route_hop"] = np.select(
            [
                path_legs["token_in"].eq(path_legs["src"])
                & path_legs["token_out"].eq(path_legs["candidate_address"]),
                path_legs["token_in"].eq(path_legs["candidate_address"])
                & path_legs["token_out"].eq(path_legs["tgt"]),
            ],
            [1, 2],
            default=0,
        )
        route_hops = path_legs[path_legs["route_hop"].isin((1, 2))].pivot_table(
            index=ROUTE_KEYS,
            columns="route_hop",
            values="source",
            aggfunc=lambda values: "|".join(values.astype(str)),
        ).reset_index().rename(columns={1: "hop1_venue_observed", 2: "hop2_venue_observed"})
        for column in ("hop1_venue_observed", "hop2_venue_observed"):
            if column not in route_hops:
                route_hops[column] = ""
        components = components.merge(
            route_hops,
            on=ROUTE_KEYS,
            how="left",
            validate="one_to_one",
        )
        components["hop1_venue"] = components["hop1_venue_observed"].fillna(components["hop1_venue"])
        components["hop2_venue"] = components["hop2_venue_observed"].fillna(components["hop2_venue"])
        components = components.drop(columns=["hop1_venue_observed", "hop2_venue_observed"])

        candidate_values = realised.rename(
            columns={
                "vehicle": "candidate_address",
                "usd": "candidate_value_usd_observed",
            }
        )
        components = components.merge(
            candidate_values[
                ROUTE_KEYS
                + [
                    "candidate_address",
                    "candidate_value_usd_observed",
                    "within_2x",
                    "within_20pct",
                ]
            ],
            on=ROUTE_KEYS + ["candidate_address"],
            how="left",
            suffixes=("", "_observed"),
            validate="one_to_one",
        )
        for support in ("within_2x", "within_20pct"):
            observed = f"{support}_observed"
            components[support] = components[observed].fillna(components[support]).astype(bool)
            components = components.drop(columns=observed)
        components["candidate_value_usd"] = components["candidate_value_usd_observed"].fillna(components["candidate_value_usd"])
        components = components.drop(columns="candidate_value_usd_observed")

        keys = list(components[ROUTE_KEYS].itertuples(index=False, name=None))
        eligible_mask = pd.Series([key in eligible_keys for key in keys], index=components.index)
        no_intermediary = eligible_mask & components["intermediary_count"].eq(0)
        components.loc[no_intermediary & components["legs"].eq(1), "selection_reason"] = "direct_route"
        components.loc[no_intermediary & components["legs"].gt(1), "selection_reason"] = "direct_split"
        components.loc[eligible_mask & components["intermediary_count"].gt(1), "selection_reason"] = "multiple_intermediaries"
        single_intermediary = eligible_mask & components["intermediary_count"].eq(1)
        components.loc[single_intermediary & components["legs"].ne(2), "selection_reason"] = "split_or_join"
        exact_two = single_intermediary & components["legs"].eq(2)
        route_order_supported = (
            components["hop1_venue"].isin(DEX_SOURCES)
            & components["hop2_venue"].isin(DEX_SOURCES)
            & ~components["hop1_venue"].str.contains("|", regex=False)
            & ~components["hop2_venue"].str.contains("|", regex=False)
        )
        components.loc[exact_two & ~route_order_supported, "selection_reason"] = "nonsequential_two_leg"
        candidate_metadata = components["candidate_address"].map(classify)
        components["candidate_symbol"] = candidate_metadata.map(lambda value: value[0] or "")
        components["candidate_type"] = candidate_metadata.map(lambda value: value[1])
        other_candidate = exact_two & route_order_supported & ~components["candidate_type"].isin(PRIMARY_TYPES)
        components.loc[other_candidate, "selection_reason"] = "other_candidate"
        included = exact_two & route_order_supported & components["candidate_type"].isin(PRIMARY_TYPES)
        components.loc[included, "selection_reason"] = INCLUDED

    components.loc[
        components["collision_event_coordinate_count"].gt(0), "selection_reason"
    ] = EVENT_COLLISION

    components.insert(0, "date", pd.to_datetime(day, format="%Y%m%d", errors="raise"))
    components["raw_value_supported"] = pd.to_numeric(components["candidate_value_usd"], errors="coerce").gt(0)
    components["within_2x"] &= components["raw_value_supported"]
    components["within_20pct"] &= components["within_2x"]
    return components


def _pair_support_table(
    components: pd.DataFrame,
    choice_audit: pd.DataFrame,
) -> pd.DataFrame:
    eligible = components[components["selection_reason"].isin(PAIR_REASONS)].copy()
    if eligible.empty:
        return pd.DataFrame(columns=PAIR_SUPPORT_COLUMNS)

    pair_support = (
        eligible.groupby(PAIR_KEYS, as_index=False, sort=True)
        .size()
        .rename(columns={"size": "market_route_count"})
    )
    counts = eligible.pivot_table(
        index=PAIR_KEYS,
        columns="selection_reason",
        values="tx_hash",
        aggfunc="size",
        fill_value=0,
    ).reset_index()
    pair_support = pair_support.merge(
        counts.rename(columns=PAIR_REASON_COLUMNS),
        on=PAIR_KEYS,
        how="left",
        validate="one_to_one",
    )
    for column in PAIR_REASON_COLUMNS.values():
        if column not in pair_support:
            pair_support[column] = 0
        pair_support[column] = pair_support[column].fillna(0).astype("int64")

    included = components[components["selection_reason"].eq(INCLUDED)].copy()
    if included.empty:
        choice_support = pd.DataFrame(columns=PAIR_KEYS)
    else:
        choice_support = included.groupby(PAIR_KEYS, as_index=False, sort=True).agg(
            native_choice_route_count=("candidate_type", lambda values: int(values.eq("native").sum())),
            stable_choice_route_count=("candidate_type", lambda values: int(values.eq("stable").sum())),
            native_within_20pct_routes=("within_20pct", lambda values: int((values & included.loc[values.index, "candidate_type"].eq("native")).sum())),
            stable_within_20pct_routes=("within_20pct", lambda values: int((values & included.loc[values.index, "candidate_type"].eq("stable")).sum())),
            native_within_20pct_value_usd=("candidate_value_usd", lambda values: _sum_supported(values, included.loc[values.index, "within_20pct"] & included.loc[values.index, "candidate_type"].eq("native"))),
            stable_within_20pct_value_usd=("candidate_value_usd", lambda values: _sum_supported(values, included.loc[values.index, "within_20pct"] & included.loc[values.index, "candidate_type"].eq("stable"))),
            primary_choice_transaction_count=("tx_hash", "nunique"),
        )
        tx_multiplicity = (
            choice_audit.groupby([*PAIR_KEYS, "tx_hash"], as_index=False, sort=True)
            .size()
            .rename(columns={"size": "component_count"})
        )
        multiplicity = tx_multiplicity.groupby(PAIR_KEYS, as_index=False, sort=True).agg(
            primary_choice_multi_component_transaction_count=("component_count", lambda values: int(values.gt(1).sum())),
            primary_choice_component_excess_count=("component_count", lambda values: int((values - 1).sum())),
        )
        duplicate_choice = (
            choice_audit.groupby([*PAIR_KEYS, "tx_hash", "candidate_address"], as_index=False, sort=True)
            .size()
            .assign(duplicate_count=lambda frame: (frame["size"] - 1).clip(lower=0))
            .groupby(PAIR_KEYS, as_index=False, sort=True)["duplicate_count"]
            .sum()
            .rename(columns={"duplicate_count": "duplicate_choice_transaction_candidate_count"})
        )
        choice_support = choice_support.merge(multiplicity, on=PAIR_KEYS, how="left", validate="one_to_one").merge(
            duplicate_choice,
            on=PAIR_KEYS,
            how="left",
            validate="one_to_one",
        )
    pair_support = pair_support.merge(
        choice_support,
        on=PAIR_KEYS,
        how="left",
        validate="one_to_one",
    )

    collisions = components[
        components["selection_reason"].eq(EVENT_COLLISION)
        & components["src"].ne("")
        & components["tgt"].ne("")
    ]
    if collisions.empty:
        collision_support = pd.DataFrame(columns=PAIR_KEYS)
    else:
        collision_support = collisions.groupby(PAIR_KEYS, as_index=False, sort=True).agg(
            event_collision_component_count=("tx_hash", "size"),
            event_collision_value_missing_component_count=("collision_value_missing_leg_count", lambda values: int(values.gt(0).sum())),
            event_collision_observed_abs_leg_value_usd_upper_bound=("collision_observed_abs_leg_value_usd_upper_bound", "sum"),
        )
    pair_support = pair_support.merge(
        collision_support,
        on=PAIR_KEYS,
        how="left",
        validate="one_to_one",
    )

    integer_diagnostics = [
        "event_collision_component_count",
        "event_collision_value_missing_component_count",
        "native_choice_route_count",
        "stable_choice_route_count",
        "native_within_20pct_routes",
        "stable_within_20pct_routes",
        "primary_choice_transaction_count",
        "primary_choice_multi_component_transaction_count",
        "primary_choice_component_excess_count",
        "duplicate_choice_transaction_candidate_count",
    ]
    for column in integer_diagnostics:
        if column not in pair_support:
            pair_support[column] = 0
        pair_support[column] = pair_support[column].fillna(0).astype("int64")
    for column in (
        "event_collision_observed_abs_leg_value_usd_upper_bound",
        "native_within_20pct_value_usd",
        "stable_within_20pct_value_usd",
    ):
        if column not in pair_support:
            pair_support[column] = 0.0
        pair_support[column] = pair_support[column].fillna(0.0).astype("float64")
    pair_support["source_pair_component_count"] = (
        pair_support["market_route_count"]
        + pair_support["event_collision_component_count"]
    )

    collision_mask = components["selection_reason"].eq(EVENT_COLLISION)
    paired_exclusion = components["selection_reason"].isin(PAIR_REASONS) | (
        collision_mask & components["src"].ne("") & components["tgt"].ne("")
    )
    day_source = len(components)
    day_collision = int(collision_mask.sum())
    pair_support["day_source_component_count"] = day_source
    pair_support["day_accounted_component_count"] = day_source
    pair_support["day_unpaired_exclusion_component_count"] = int((~paired_exclusion).sum())
    pair_support["day_event_collision_component_count"] = day_collision
    pair_support["day_event_collision_value_missing_component_count"] = int(
        (collision_mask & components["collision_value_missing_leg_count"].gt(0)).sum()
    )
    pair_support["day_event_collision_observed_abs_leg_value_usd_upper_bound"] = float(
        components.loc[
            collision_mask,
            "collision_observed_abs_leg_value_usd_upper_bound",
        ].sum()
    )
    pair_support["pair_first_supported_date"] = pair_support["date"]
    pair_support["pair_last_supported_date"] = pair_support["date"]
    pair_support["pair_entry_on_day"] = True
    pair_support["pair_last_observed_on_day"] = True
    pair_support["pair_support_reason"] = "observed_clean_endpoint_pair"
    return pair_support[PAIR_SUPPORT_COLUMNS]


def _exclusion_table(components: pd.DataFrame) -> pd.DataFrame:
    excluded = components[~components["selection_reason"].eq(INCLUDED)].copy()
    if excluded.empty:
        return pd.DataFrame(columns=EXCLUSION_COLUMNS)
    excluded["exclusion_reason"] = excluded["selection_reason"]
    collision = excluded["selection_reason"].eq(EVENT_COLLISION)
    excluded["audit_tx_hash"] = np.where(collision, excluded["tx_hash"], "")
    excluded["audit_component_id"] = np.where(collision, excluded["component_id"], -1).astype("int64")
    for column in COLLISION_AUDIT_COLUMNS:
        if column in ("collision_sources", "component_venues", "collision_log_indices"):
            excluded.loc[~collision, column] = ""
        else:
            excluded.loc[~collision, column] = 0
    summarized = _summarize(excluded, EXCLUSION_KEYS)
    audit = excluded.groupby(EXCLUSION_KEYS, as_index=False, sort=True, dropna=False).agg(
        collision_event_coordinate_count=("collision_event_coordinate_count", "max"),
        collision_row_count=("collision_row_count", "max"),
        collision_source_count=("collision_source_count", "max"),
        collision_sources=("collision_sources", _joined_tokens),
        component_venues=("component_venues", _joined_tokens),
        collision_log_indices=("collision_log_indices", _joined_tokens),
        collision_first_timestamp_utc=("collision_first_timestamp_utc", "max"),
        collision_last_timestamp_utc=("collision_last_timestamp_utc", "max"),
        collision_value_missing_leg_count=("collision_value_missing_leg_count", "max"),
        collision_observed_abs_leg_value_usd_upper_bound=("collision_observed_abs_leg_value_usd_upper_bound", "max"),
    )
    return summarized.merge(
        audit,
        on=EXCLUSION_KEYS,
        how="inner",
        validate="one_to_one",
    )[EXCLUSION_COLUMNS]


def endpoint_candidate_composition_for_day(legs: pd.DataFrame, day: str) -> EndpointCandidateComposition:
    """Build the exact-two-leg stable/native choice object for one UTC day."""
    components = _component_frame(legs, day)
    if components.empty:
        return _empty_bundle()
    included = components[components["selection_reason"].eq(INCLUDED)].copy()
    if included.empty:
        choices = pd.DataFrame(columns=CHOICE_COLUMNS)
        choice_audit = pd.DataFrame(columns=CHOICE_AUDIT_COLUMNS)
    else:
        included["integration_scope"] = np.where(included["hop1_venue"].eq(included["hop2_venue"]), "single_venue", "cross_venue")
        included["venue_sequence"] = included["hop1_venue"] + ">" + included["hop2_venue"]
        included["protocol_sequence"] = included["hop1_venue"].map(_protocol_family) + ">" + included["hop2_venue"].map(_protocol_family)
        included["backing_regime"] = [backing(address, date) for address, date in zip(included["candidate_address"], included["date"], strict=True)]
        identity = [*CHOICE_KEYS, "candidate_symbol", "candidate_type", "backing_regime", "hop1_venue", "hop2_venue", "protocol_sequence"]
        choices = _summarize(included, identity)[CHOICE_COLUMNS]
        audit_identity = [
            "date",
            "tx_hash",
            "component_id",
            *CHOICE_KEYS[1:],
            "candidate_symbol",
            "candidate_type",
            "backing_regime",
            "hop1_venue",
            "hop2_venue",
            "protocol_sequence",
        ]
        choice_audit = _summarize(included, audit_identity)[CHOICE_AUDIT_COLUMNS]

    pair_support = _pair_support_table(components, choice_audit)
    exclusions = _exclusion_table(components)
    return validate_endpoint_candidate_composition(
        EndpointCandidateComposition(choices, choice_audit, pair_support, exclusions)
    )


def finalize_endpoint_candidate_composition(daily: Iterable[EndpointCandidateComposition]) -> EndpointCandidateComposition:
    """Combine deterministic daily bundles and add sample-relative pair support."""
    bundles = list(daily)
    if not bundles:
        return _empty_bundle()
    choices = pd.concat([bundle.choices for bundle in bundles], ignore_index=True)
    choice_audit = pd.concat([bundle.choice_audit for bundle in bundles], ignore_index=True)
    pair_support = pd.concat([bundle.pair_support for bundle in bundles], ignore_index=True)
    exclusions = pd.concat([bundle.exclusions for bundle in bundles], ignore_index=True)
    if not pair_support.empty:
        dates = pair_support.groupby(["src", "tgt"], sort=False)["date"]
        pair_support["pair_first_supported_date"] = dates.transform("min")
        pair_support["pair_last_supported_date"] = dates.transform("max")
        pair_support["pair_entry_on_day"] = pair_support["date"].eq(pair_support["pair_first_supported_date"])
        pair_support["pair_last_observed_on_day"] = pair_support["date"].eq(pair_support["pair_last_supported_date"])
    return validate_endpoint_candidate_composition(
        EndpointCandidateComposition(choices, choice_audit, pair_support, exclusions)
    )


def _require_schema(frame: pd.DataFrame, columns: list[str], label: str) -> pd.DataFrame:
    missing = [column for column in columns if column not in frame.columns]
    extra = [column for column in frame.columns if column not in columns]
    if missing or extra:
        raise ValueError(f"{label} schema mismatch: missing={missing}; extra={extra}")
    return frame[columns].copy()


def _validate_magnitudes(frame: pd.DataFrame, *, label: str) -> None:
    if frame.empty:
        return
    for column in MAGNITUDE_COLUMNS:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype="float64")).all() or numeric.lt(0).any():
            raise ValueError(f"{label} contains invalid {column}")
    counts = frame[MAGNITUDE_COUNT_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if not counts.eq(np.floor(counts)).all().all():
        raise ValueError(f"{label} contains non-integer route counts")
    if not (counts["route_count"].ge(counts["raw_value_supported_routes"]) & counts["raw_value_supported_routes"].ge(counts["within_2x_routes"]) & counts["within_2x_routes"].ge(counts["within_20pct_routes"])).all():
        raise ValueError(f"{label} value-support counts are not nested")
    values = frame[MAGNITUDE_VALUE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if not (
        values["raw_value_usd"].ge(values["within_2x_value_usd"])
        & values["within_2x_value_usd"].ge(values["within_20pct_value_usd"])
    ).all():
        raise ValueError(f"{label} value-support magnitudes are not nested")
    count_value_pairs = (
        ("raw_value_supported_routes", "raw_value_usd"),
        ("within_2x_routes", "within_2x_value_usd"),
        ("within_20pct_routes", "within_20pct_value_usd"),
    )
    for count_column, value_column in count_value_pairs:
        if not counts[count_column].eq(0).eq(values[value_column].eq(0)).all():
            raise ValueError(
                f"{label} has value without supported routes or supported routes without value"
            )


def validate_endpoint_candidate_composition(bundle: EndpointCandidateComposition) -> EndpointCandidateComposition:
    """Validate deterministic identities, accounting, and nested value support."""
    choices = _require_schema(bundle.choices, CHOICE_COLUMNS, "vehicle choices")
    choice_audit = _require_schema(
        bundle.choice_audit,
        CHOICE_AUDIT_COLUMNS,
        "vehicle choice audit",
    )
    pair_support = _require_schema(bundle.pair_support, PAIR_SUPPORT_COLUMNS, "vehicle pair support")
    exclusions = _require_schema(bundle.exclusions, EXCLUSION_COLUMNS, "vehicle exclusions")
    _validate_magnitudes(choices, label="vehicle choices")
    _validate_magnitudes(choice_audit, label="vehicle choice audit")
    _validate_magnitudes(exclusions, label="vehicle exclusions")
    if not exclusions.empty and not exclusions["exclusion_reason"].isin(EXCLUSION_REASONS).all():
        raise ValueError("vehicle exclusions contain an unknown reason")
    if not exclusions.empty and exclusions.duplicated(EXCLUSION_KEYS).any():
        raise ValueError("vehicle exclusions contain duplicate composition keys")
    if not exclusions.empty:
        collision = exclusions["exclusion_reason"].eq(EVENT_COLLISION)
        collision_rows = exclusions[collision]
        ordinary = exclusions[~collision]
        if not ordinary.empty and (
            ordinary["audit_tx_hash"].ne("").any()
            or ordinary["audit_component_id"].ne(-1).any()
            or ordinary[COLLISION_AUDIT_COLUMNS].drop(
                columns=["collision_sources", "component_venues", "collision_log_indices"]
            ).apply(pd.to_numeric, errors="coerce").ne(0).any().any()
            or ordinary[["collision_sources", "component_venues", "collision_log_indices"]].ne("").any().any()
        ):
            raise ValueError("ordinary vehicle exclusions contain collision audit state")
        if not collision_rows.empty:
            numeric_audit = collision_rows[
                [
                    "collision_event_coordinate_count",
                    "collision_row_count",
                    "collision_source_count",
                    "collision_first_timestamp_utc",
                    "collision_last_timestamp_utc",
                    "collision_value_missing_leg_count",
                    "collision_observed_abs_leg_value_usd_upper_bound",
                ]
            ].apply(pd.to_numeric, errors="coerce")
            if (
                collision_rows["audit_tx_hash"].eq("").any()
                or collision_rows["audit_component_id"].lt(0).any()
                or collision_rows["route_count"].ne(1).any()
                or numeric_audit[["collision_event_coordinate_count", "collision_row_count", "collision_source_count"]].le(0).any().any()
                or numeric_audit["collision_first_timestamp_utc"].le(0).any()
                or numeric_audit["collision_last_timestamp_utc"].lt(numeric_audit["collision_first_timestamp_utc"]).any()
                or collision_rows[["collision_sources", "component_venues", "collision_log_indices"]].eq("").any().any()
            ):
                raise ValueError("vehicle collision exclusions lack component-keyed audit evidence")
    if not choices.empty:
        if choices.duplicated(CHOICE_KEYS).any():
            raise ValueError("vehicle choices contain duplicate composition keys")
        if not choices["candidate_address"].map(lambda value: bool(_ADDRESS.fullmatch(str(value)))).all():
            raise ValueError("vehicle choices contain invalid candidate identity")
        metadata = choices["candidate_address"].map(classify)
        if not choices["candidate_symbol"].eq(metadata.map(lambda value: value[0] or "")).all() or not choices["candidate_type"].eq(metadata.map(lambda value: value[1])).all() or not choices["candidate_type"].isin(PRIMARY_TYPES).all():
            raise ValueError("vehicle choices disagree with canonical candidate identity")
        expected_venue = choices["hop1_venue"] + ">" + choices["hop2_venue"]
        expected_protocol = choices["hop1_venue"].map(_protocol_family) + ">" + choices["hop2_venue"].map(_protocol_family)
        expected_scope = np.where(choices["hop1_venue"].eq(choices["hop2_venue"]), "single_venue", "cross_venue")
        if not choices["venue_sequence"].eq(expected_venue).all() or not choices["protocol_sequence"].eq(expected_protocol).all() or not choices["integration_scope"].eq(expected_scope).all():
            raise ValueError("vehicle choices contain inconsistent ordered venue identities")
        expected_backing = pd.Series([backing(address, date) for address, date in zip(choices["candidate_address"], choices["date"], strict=True)], index=choices.index)
        if not choices["backing_regime"].eq(expected_backing).all():
            raise ValueError("vehicle choices disagree with dated backing identity")
    if not choice_audit.empty:
        if choice_audit.duplicated(CHOICE_AUDIT_KEYS).any():
            raise ValueError("vehicle choice audit contains duplicate component keys")
        if not choice_audit["route_count"].eq(1).all():
            raise ValueError("vehicle choice audit contains non-unit components")
        observed_choices = (
            choice_audit.groupby(
                [
                    *CHOICE_KEYS,
                    "candidate_symbol",
                    "candidate_type",
                    "backing_regime",
                    "hop1_venue",
                    "hop2_venue",
                    "protocol_sequence",
                ],
                as_index=False,
                sort=True,
            )[MAGNITUDE_COLUMNS]
            .sum()
            .sort_values(CHOICE_KEYS, kind="stable")
            .reset_index(drop=True)[CHOICE_COLUMNS]
        )
        try:
            pd.testing.assert_frame_equal(
                choices.sort_values(CHOICE_KEYS, kind="stable").reset_index(drop=True),
                observed_choices,
                check_dtype=False,
            )
        except AssertionError as error:
            raise ValueError("vehicle choices disagree with component-keyed audit") from error
    elif not choices.empty:
        raise ValueError("vehicle choices lack component-keyed audit")
    if not pair_support.empty:
        if pair_support.duplicated(PAIR_KEYS).any() or not pair_support["market_route_count"].gt(0).all():
            raise ValueError("vehicle pair support has invalid keys or support")
        reason_columns = list(PAIR_REASON_COLUMNS.values())
        if not pair_support[reason_columns].sum(axis=1).eq(pair_support["market_route_count"]).all():
            raise ValueError("vehicle pair support does not reconcile route classifications")
        observed = choices.groupby(PAIR_KEYS, as_index=False)["route_count"].sum().rename(columns={"route_count": "observed_primary"}) if not choices.empty else pd.DataFrame(columns=[*PAIR_KEYS, "observed_primary"])
        reconciled = pair_support.merge(observed, on=PAIR_KEYS, how="left", validate="one_to_one")
        if not reconciled["primary_choice_route_count"].eq(reconciled["observed_primary"].fillna(0)).all():
            raise ValueError("vehicle choice cells disagree with pair support")
        numeric_support = pair_support[PAIR_SUPPORT_COUNT_COLUMNS].apply(pd.to_numeric, errors="coerce")
        if (
            not np.isfinite(numeric_support.to_numpy(dtype="float64")).all()
            or numeric_support.lt(0).any().any()
            or not numeric_support.eq(np.floor(numeric_support)).all().all()
        ):
            raise ValueError("vehicle pair support contains invalid diagnostic counts")
        if not pair_support["native_choice_route_count"].add(
            pair_support["stable_choice_route_count"]
        ).eq(pair_support["primary_choice_route_count"]).all():
            raise ValueError("vehicle pair support does not reconcile native and stable choices")
        type_observed = (
            choices.groupby([*PAIR_KEYS, "candidate_type"], as_index=False, sort=True)
            .agg(
                route_count=("route_count", "sum"),
                within_20pct_routes=("within_20pct_routes", "sum"),
                within_20pct_value_usd=("within_20pct_value_usd", "sum"),
            )
            if not choices.empty
            else pd.DataFrame(
                columns=[
                    *PAIR_KEYS,
                    "candidate_type",
                    "route_count",
                    "within_20pct_routes",
                    "within_20pct_value_usd",
                ]
            )
        )
        type_reconciled = pair_support.copy()
        for candidate_type in ("native", "stable"):
            observed_type = type_observed[
                type_observed["candidate_type"].eq(candidate_type)
            ][
                [
                    *PAIR_KEYS,
                    "route_count",
                    "within_20pct_routes",
                    "within_20pct_value_usd",
                ]
            ].rename(
                columns={
                    "route_count": f"observed_{candidate_type}_choice_route_count",
                    "within_20pct_routes": f"observed_{candidate_type}_within_20pct_routes",
                    "within_20pct_value_usd": f"observed_{candidate_type}_within_20pct_value_usd",
                }
            )
            type_reconciled = type_reconciled.merge(
                observed_type,
                on=PAIR_KEYS,
                how="left",
                validate="one_to_one",
            )
            for suffix in ("choice_route_count", "within_20pct_routes"):
                if not type_reconciled[f"{candidate_type}_{suffix}"].eq(
                    type_reconciled[f"observed_{candidate_type}_{suffix}"].fillna(0)
                ).all():
                    raise ValueError(
                        f"vehicle pair support disagrees with {candidate_type} choice counts"
                    )
            if not np.isclose(
                pd.to_numeric(
                    type_reconciled[f"{candidate_type}_within_20pct_value_usd"],
                    errors="raise",
                ).to_numpy(dtype="float64"),
                pd.to_numeric(
                    type_reconciled[f"observed_{candidate_type}_within_20pct_value_usd"],
                    errors="coerce",
                ).fillna(0).to_numpy(dtype="float64"),
                rtol=1e-12,
                atol=1e-8,
            ).all():
                raise ValueError(
                    f"vehicle pair support disagrees with {candidate_type} choice value"
                )
        if not (
            pair_support["native_within_20pct_routes"].le(pair_support["native_choice_route_count"])
            & pair_support["stable_within_20pct_routes"].le(pair_support["stable_choice_route_count"])
            & pair_support["primary_choice_transaction_count"].le(pair_support["primary_choice_route_count"])
            & pair_support["primary_choice_multi_component_transaction_count"].le(pair_support["primary_choice_transaction_count"])
            & pair_support["primary_choice_component_excess_count"].eq(
                pair_support["primary_choice_route_count"] - pair_support["primary_choice_transaction_count"]
            )
            & pair_support["duplicate_choice_transaction_candidate_count"].le(pair_support["primary_choice_component_excess_count"])
        ).all():
            raise ValueError("vehicle pair support contains inconsistent choice multiplicity")
        audit_transactions = (
            choice_audit.groupby([*PAIR_KEYS, "tx_hash"], as_index=False, sort=True)
            .size()
            .rename(columns={"size": "component_count"})
            if not choice_audit.empty
            else pd.DataFrame(columns=[*PAIR_KEYS, "tx_hash", "component_count"])
        )
        audit_multiplicity = (
            audit_transactions.groupby(PAIR_KEYS, as_index=False, sort=True).agg(
                observed_choice_transaction_count=("tx_hash", "nunique"),
                observed_multi_component_transaction_count=("component_count", lambda values: int(values.gt(1).sum())),
                observed_component_excess_count=("component_count", lambda values: int((values - 1).sum())),
            )
            if not audit_transactions.empty
            else pd.DataFrame(
                columns=[
                    *PAIR_KEYS,
                    "observed_choice_transaction_count",
                    "observed_multi_component_transaction_count",
                    "observed_component_excess_count",
                ]
            )
        )
        audit_duplicate_candidate = (
            choice_audit.groupby(
                [*PAIR_KEYS, "tx_hash", "candidate_address"],
                as_index=False,
                sort=True,
            )
            .size()
            .assign(duplicate_count=lambda frame: (frame["size"] - 1).clip(lower=0))
            .groupby(PAIR_KEYS, as_index=False, sort=True)["duplicate_count"]
            .sum()
            .rename(columns={"duplicate_count": "observed_duplicate_choice_count"})
            if not choice_audit.empty
            else pd.DataFrame(
                columns=[*PAIR_KEYS, "observed_duplicate_choice_count"]
            )
        )
        multiplicity_reconciled = pair_support.merge(
            audit_multiplicity,
            on=PAIR_KEYS,
            how="left",
            validate="one_to_one",
        ).merge(
            audit_duplicate_candidate,
            on=PAIR_KEYS,
            how="left",
            validate="one_to_one",
        )
        multiplicity_pairs = (
            ("primary_choice_transaction_count", "observed_choice_transaction_count"),
            (
                "primary_choice_multi_component_transaction_count",
                "observed_multi_component_transaction_count",
            ),
            (
                "primary_choice_component_excess_count",
                "observed_component_excess_count",
            ),
            (
                "duplicate_choice_transaction_candidate_count",
                "observed_duplicate_choice_count",
            ),
        )
        for published, observed_name in multiplicity_pairs:
            if not multiplicity_reconciled[published].eq(
                multiplicity_reconciled[observed_name].fillna(0)
            ).all():
                raise ValueError(
                    "vehicle pair support disagrees with component-keyed choice multiplicity"
                )
        if not pair_support["source_pair_component_count"].eq(
            pair_support["market_route_count"] + pair_support["event_collision_component_count"]
        ).all():
            raise ValueError("vehicle pair support does not reconcile source components")
        pair_collisions = exclusions[
            exclusions["exclusion_reason"].eq(EVENT_COLLISION)
            & exclusions["src"].ne("")
            & exclusions["tgt"].ne("")
        ]
        observed_collisions = (
            pair_collisions.groupby(PAIR_KEYS, as_index=False, sort=True).agg(
                observed_collision_component_count=("route_count", "sum"),
                observed_collision_value_missing_component_count=("collision_value_missing_leg_count", lambda values: int(values.gt(0).sum())),
                observed_collision_value_bound=("collision_observed_abs_leg_value_usd_upper_bound", "sum"),
            )
            if not pair_collisions.empty
            else pd.DataFrame(
                columns=[
                    *PAIR_KEYS,
                    "observed_collision_component_count",
                    "observed_collision_value_missing_component_count",
                    "observed_collision_value_bound",
                ]
            )
        )
        collision_pair_reconciled = pair_support.merge(
            observed_collisions,
            on=PAIR_KEYS,
            how="left",
            validate="one_to_one",
        )
        if (
            not collision_pair_reconciled["event_collision_component_count"].eq(
                collision_pair_reconciled["observed_collision_component_count"].fillna(0)
            ).all()
            or not collision_pair_reconciled["event_collision_value_missing_component_count"].eq(
                collision_pair_reconciled[
                    "observed_collision_value_missing_component_count"
                ].fillna(0)
            ).all()
            or not np.isclose(
                pd.to_numeric(
                    collision_pair_reconciled[
                        "event_collision_observed_abs_leg_value_usd_upper_bound"
                    ],
                    errors="raise",
                ).to_numpy(dtype="float64"),
                pd.to_numeric(
                    collision_pair_reconciled["observed_collision_value_bound"],
                    errors="coerce",
                ).fillna(0).to_numpy(dtype="float64"),
                rtol=1e-12,
                atol=1e-8,
            ).all()
        ):
            raise ValueError("vehicle pair support disagrees with collision exclusions")
        value_support = pair_support[PAIR_SUPPORT_VALUE_COLUMNS].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(value_support.to_numpy(dtype="float64")).all() or value_support.lt(0).any().any():
            raise ValueError("vehicle pair support contains invalid value bounds")
    pair_exclusions = exclusions[
        exclusions["exclusion_reason"].isin(set(PAIR_REASONS) - {INCLUDED})
    ]
    for reason, reason_column in PAIR_REASON_COLUMNS.items():
        if reason == INCLUDED:
            continue
        observed_reason = (
            pair_exclusions[pair_exclusions["exclusion_reason"].eq(reason)]
            .groupby(PAIR_KEYS, as_index=False)["route_count"]
            .sum()
            .rename(columns={"route_count": "observed_reason_count"})
        )
        if observed_reason.empty:
            if not pair_support[reason_column].fillna(0).eq(0).all():
                raise ValueError(
                    f"vehicle exclusions disagree with pair support for {reason}"
                )
            continue
        if pair_support.empty:
            raise ValueError(
                f"vehicle exclusions disagree with pair support for {reason}"
            )
        reason_reconciled = pair_support[PAIR_KEYS + [reason_column]].merge(
            observed_reason,
            on=PAIR_KEYS,
            how="outer",
            validate="one_to_one",
        )
        if not reason_reconciled[reason_column].fillna(0).eq(
            reason_reconciled["observed_reason_count"].fillna(0)
        ).all():
            raise ValueError(f"vehicle exclusions disagree with pair support for {reason}")
    total_choices = int(choices["route_count"].sum()) if not choices.empty else 0
    total_exclusions = int(exclusions["route_count"].sum()) if not exclusions.empty else 0
    if total_choices + total_exclusions <= 0 and (not choices.empty or not pair_support.empty or not exclusions.empty):
        raise ValueError("vehicle composition has nonempty frames but no accounted routes")
    if not pair_support.empty:
        accounted = pd.concat(
            [
                choices.groupby("date", as_index=False)["route_count"].sum()
                if not choices.empty
                else pd.DataFrame(columns=["date", "route_count"]),
                exclusions.groupby("date", as_index=False)["route_count"].sum()
                if not exclusions.empty
                else pd.DataFrame(columns=["date", "route_count"]),
            ],
            ignore_index=True,
        ).groupby("date", as_index=False)["route_count"].sum()
        daily = pair_support.groupby("date", as_index=False, sort=True).agg(
            day_source_component_count=("day_source_component_count", "first"),
            day_source_component_count_nunique=("day_source_component_count", "nunique"),
            day_accounted_component_count=("day_accounted_component_count", "first"),
            day_accounted_component_count_nunique=("day_accounted_component_count", "nunique"),
            day_event_collision_component_count=("day_event_collision_component_count", "first"),
            day_event_collision_component_count_nunique=("day_event_collision_component_count", "nunique"),
            day_unpaired_exclusion_component_count=("day_unpaired_exclusion_component_count", "first"),
            day_unpaired_exclusion_component_count_nunique=("day_unpaired_exclusion_component_count", "nunique"),
            day_event_collision_value_missing_component_count=("day_event_collision_value_missing_component_count", "first"),
            day_event_collision_value_missing_component_count_nunique=("day_event_collision_value_missing_component_count", "nunique"),
            day_event_collision_observed_abs_leg_value_usd_upper_bound=("day_event_collision_observed_abs_leg_value_usd_upper_bound", "first"),
            day_event_collision_value_nunique=("day_event_collision_observed_abs_leg_value_usd_upper_bound", "nunique"),
        ).merge(accounted, on="date", how="left", validate="one_to_one")
        if (
            daily.filter(like="nunique").ne(1).any().any()
            or not daily["day_source_component_count"].eq(daily["day_accounted_component_count"]).all()
            or not daily["day_accounted_component_count"].eq(daily["route_count"]).all()
        ):
            raise ValueError("vehicle daily source-component accounting does not reconcile")
        collision_daily = (
            exclusions[exclusions["exclusion_reason"].eq(EVENT_COLLISION)]
            .groupby("date", as_index=False, sort=True)
            .agg(
                observed_collision_count=("route_count", "sum"),
                observed_collision_value_missing_count=("collision_value_missing_leg_count", lambda values: int(values.gt(0).sum())),
                observed_collision_value=("collision_observed_abs_leg_value_usd_upper_bound", "sum"),
            )
        )
        collision_reconciled = daily.merge(
            collision_daily,
            on="date",
            how="left",
            validate="one_to_one",
        )
        if (
            not collision_reconciled["day_event_collision_component_count"].eq(
                collision_reconciled["observed_collision_count"].fillna(0)
            ).all()
            or not collision_reconciled[
                "day_event_collision_value_missing_component_count"
            ].eq(
                collision_reconciled[
                    "observed_collision_value_missing_count"
                ].fillna(0)
            ).all()
            or not np.isclose(
                pd.to_numeric(
                    collision_reconciled["day_event_collision_observed_abs_leg_value_usd_upper_bound"],
                    errors="raise",
                ).to_numpy(dtype="float64"),
                pd.to_numeric(
                    collision_reconciled["observed_collision_value"],
                    errors="coerce",
                ).fillna(0).to_numpy(dtype="float64"),
                rtol=1e-12,
                atol=1e-8,
            ).all()
        ):
            raise ValueError("vehicle collision exclusions disagree with daily support bounds")
        unpaired_exclusions = exclusions[
            ~exclusions["exclusion_reason"].isin(set(PAIR_REASONS) - {INCLUDED})
            & ~(
                exclusions["exclusion_reason"].eq(EVENT_COLLISION)
                & exclusions["src"].ne("")
                & exclusions["tgt"].ne("")
            )
        ]
        unpaired_daily = (
            unpaired_exclusions.groupby("date", as_index=False, sort=True)["route_count"]
            .sum()
            .rename(columns={"route_count": "observed_unpaired_count"})
        )
        unpaired_reconciled = daily.merge(
            unpaired_daily,
            on="date",
            how="left",
            validate="one_to_one",
        )
        if not unpaired_reconciled["day_unpaired_exclusion_component_count"].eq(
            unpaired_reconciled["observed_unpaired_count"].fillna(0)
        ).all():
            raise ValueError("vehicle unpaired exclusions disagree with daily support")
    return EndpointCandidateComposition(
        choices.sort_values(CHOICE_KEYS, kind="stable").reset_index(drop=True),
        choice_audit.sort_values(CHOICE_AUDIT_KEYS, kind="stable").reset_index(drop=True),
        pair_support.sort_values(PAIR_KEYS, kind="stable").reset_index(drop=True),
        exclusions.sort_values(EXCLUSION_KEYS, kind="stable").reset_index(drop=True),
    )

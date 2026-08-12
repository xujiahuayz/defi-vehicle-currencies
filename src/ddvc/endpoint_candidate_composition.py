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
PAIR_SUPPORT_COLUMNS = [
    *PAIR_KEYS,
    "market_route_count",
    "primary_choice_route_count",
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
EXCLUSION_KEYS = [
    "date",
    "exclusion_reason",
    "src",
    "tgt",
    "candidate_address",
    "candidate_type",
]
EXCLUSION_COLUMNS = [*EXCLUSION_KEYS, *MAGNITUDE_COLUMNS]
INCLUDED = "included_primary_vehicle_choice"
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
    """Primary choice cells, pair support, and mutually exclusive exclusions."""

    choices: pd.DataFrame
    pair_support: pd.DataFrame
    exclusions: pd.DataFrame


def _empty_bundle() -> EndpointCandidateComposition:
    return EndpointCandidateComposition(
        pd.DataFrame(columns=CHOICE_COLUMNS),
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


def _component_frame(legs: pd.DataFrame, day: str) -> pd.DataFrame:
    missing = sorted(set(ROUTE_INPUT_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"vehicle choice is missing columns: {', '.join(missing)}")
    duplicate_events = legs.duplicated(["tx_hash", "log_index"], keep=False)
    if duplicate_events.any():
        sample = legs.loc[duplicate_events, ["tx_hash", "log_index"]].iloc[0].to_dict()
        raise ValueError(f"vehicle choice contains duplicate event identity: {sample}")
    rows = legs[ROUTE_INPUT_COLUMNS].copy()
    if rows.empty:
        return pd.DataFrame()
    rows["token_in"] = rows["token_in"].map(lambda value: _canonical_address(value, field="token_in"))
    rows["token_out"] = rows["token_out"].map(lambda value: _canonical_address(value, field="token_out"))
    rows["source"] = rows["source"].map(str)
    for venue in rows["source"].unique():
        _protocol_family(venue)
    rows["amount_usd"] = pd.to_numeric(rows["amount_usd"], errors="coerce")
    rows["log_index"] = pd.to_numeric(rows["log_index"], errors="raise")
    rows["timestamp_utc"] = pd.to_numeric(rows["timestamp_utc"], errors="raise")
    if rows["timestamp_utc"].isna().any():
        raise ValueError("vehicle choice contains a missing transaction timestamp")
    expected_day = pd.to_datetime(day, format="%Y%m%d", errors="raise", utc=True)
    observed_days = pd.to_datetime(
        rows["timestamp_utc"], unit="s", errors="raise", utc=True
    ).dt.normalize()
    if not observed_days.eq(expected_day).all():
        raise ValueError("vehicle choice transaction timestamp falls outside supplied UTC day")
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

    components.insert(0, "date", pd.to_datetime(day, format="%Y%m%d", errors="raise"))
    components["raw_value_supported"] = pd.to_numeric(components["candidate_value_usd"], errors="coerce").gt(0)
    components["within_2x"] &= components["raw_value_supported"]
    components["within_20pct"] &= components["within_2x"]
    return components


def endpoint_candidate_composition_for_day(legs: pd.DataFrame, day: str) -> EndpointCandidateComposition:
    """Build the exact-two-leg stable/native choice object for one UTC day."""
    components = _component_frame(legs, day)
    if components.empty:
        return _empty_bundle()
    included = components[components["selection_reason"].eq(INCLUDED)].copy()
    if included.empty:
        choices = pd.DataFrame(columns=CHOICE_COLUMNS)
    else:
        included["integration_scope"] = np.where(included["hop1_venue"].eq(included["hop2_venue"]), "single_venue", "cross_venue")
        included["venue_sequence"] = included["hop1_venue"] + ">" + included["hop2_venue"]
        included["protocol_sequence"] = included["hop1_venue"].map(_protocol_family) + ">" + included["hop2_venue"].map(_protocol_family)
        included["backing_regime"] = [backing(address, date) for address, date in zip(included["candidate_address"], included["date"], strict=True)]
        identity = [*CHOICE_KEYS, "candidate_symbol", "candidate_type", "backing_regime", "hop1_venue", "hop2_venue", "protocol_sequence"]
        choices = _summarize(included, identity)[CHOICE_COLUMNS]

    eligible = components[components["selection_reason"].isin(PAIR_REASONS)].copy()
    if eligible.empty:
        pair_support = pd.DataFrame(columns=PAIR_SUPPORT_COLUMNS)
    else:
        pair_support = eligible.groupby(PAIR_KEYS, as_index=False, sort=True).size().rename(columns={"size": "market_route_count"})
        counts = eligible.pivot_table(index=PAIR_KEYS, columns="selection_reason", values="tx_hash", aggfunc="size", fill_value=0).reset_index()
        counts = counts.rename(columns=PAIR_REASON_COLUMNS)
        pair_support = pair_support.merge(counts, on=PAIR_KEYS, how="left", validate="one_to_one")
        for column in PAIR_REASON_COLUMNS.values():
            if column not in pair_support:
                pair_support[column] = 0
            pair_support[column] = pair_support[column].fillna(0).astype("int64")
        pair_support["pair_first_supported_date"] = pair_support["date"]
        pair_support["pair_last_supported_date"] = pair_support["date"]
        pair_support["pair_entry_on_day"] = True
        pair_support["pair_last_observed_on_day"] = True
        pair_support["pair_support_reason"] = "observed_clean_endpoint_pair"
        pair_support = pair_support[PAIR_SUPPORT_COLUMNS]

    excluded = components[~components["selection_reason"].eq(INCLUDED)].copy()
    excluded["exclusion_reason"] = excluded["selection_reason"]
    exclusions = _summarize(excluded, EXCLUSION_KEYS)[EXCLUSION_COLUMNS] if not excluded.empty else pd.DataFrame(columns=EXCLUSION_COLUMNS)
    return validate_endpoint_candidate_composition(EndpointCandidateComposition(choices, pair_support, exclusions))


def finalize_endpoint_candidate_composition(daily: Iterable[EndpointCandidateComposition]) -> EndpointCandidateComposition:
    """Combine deterministic daily bundles and add sample-relative pair support."""
    bundles = list(daily)
    if not bundles:
        return _empty_bundle()
    choices = pd.concat([bundle.choices for bundle in bundles], ignore_index=True)
    pair_support = pd.concat([bundle.pair_support for bundle in bundles], ignore_index=True)
    exclusions = pd.concat([bundle.exclusions for bundle in bundles], ignore_index=True)
    if not pair_support.empty:
        dates = pair_support.groupby(["src", "tgt"], sort=False)["date"]
        pair_support["pair_first_supported_date"] = dates.transform("min")
        pair_support["pair_last_supported_date"] = dates.transform("max")
        pair_support["pair_entry_on_day"] = pair_support["date"].eq(pair_support["pair_first_supported_date"])
        pair_support["pair_last_observed_on_day"] = pair_support["date"].eq(pair_support["pair_last_supported_date"])
    return validate_endpoint_candidate_composition(EndpointCandidateComposition(choices, pair_support, exclusions))


def _require_schema(frame: pd.DataFrame, columns: list[str], label: str) -> pd.DataFrame:
    missing = [column for column in columns if column not in frame.columns]
    extra = [column for column in frame.columns if column not in columns]
    if missing or extra:
        raise ValueError(f"{label} schema mismatch: missing={missing}; extra={extra}")
    return frame[columns].copy()


def _validate_magnitudes(frame: pd.DataFrame, *, label: str) -> None:
    if frame.empty:
        return
    count_columns = [
        "route_count",
        "raw_value_supported_routes",
        "within_2x_routes",
        "within_20pct_routes",
    ]
    value_columns = [
        "raw_value_usd",
        "within_2x_value_usd",
        "within_20pct_value_usd",
    ]
    for column in MAGNITUDE_COLUMNS:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype="float64")).all() or numeric.lt(0).any():
            raise ValueError(f"{label} contains invalid {column}")
    counts = frame[count_columns].apply(pd.to_numeric, errors="coerce")
    if not counts.eq(np.floor(counts)).all().all():
        raise ValueError(f"{label} contains non-integer route counts")
    if not (counts["route_count"].ge(counts["raw_value_supported_routes"]) & counts["raw_value_supported_routes"].ge(counts["within_2x_routes"]) & counts["within_2x_routes"].ge(counts["within_20pct_routes"])).all():
        raise ValueError(f"{label} value-support counts are not nested")
    values = frame[value_columns].apply(pd.to_numeric, errors="coerce")
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
    pair_support = _require_schema(bundle.pair_support, PAIR_SUPPORT_COLUMNS, "vehicle pair support")
    exclusions = _require_schema(bundle.exclusions, EXCLUSION_COLUMNS, "vehicle exclusions")
    _validate_magnitudes(choices, label="vehicle choices")
    _validate_magnitudes(exclusions, label="vehicle exclusions")
    if not exclusions.empty and not exclusions["exclusion_reason"].isin(EXCLUSION_REASONS).all():
        raise ValueError("vehicle exclusions contain an unknown reason")
    if not exclusions.empty and exclusions.duplicated(EXCLUSION_KEYS).any():
        raise ValueError("vehicle exclusions contain duplicate composition keys")
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
    return EndpointCandidateComposition(
        choices.sort_values(CHOICE_KEYS, kind="stable").reset_index(drop=True),
        pair_support.sort_values(PAIR_KEYS, kind="stable").reset_index(drop=True),
        exclusions.sort_values(EXCLUSION_KEYS, kind="stable").reset_index(drop=True),
    )

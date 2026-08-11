"""Released endpoint-pair vehicle composition with explicit support denominators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re

import numpy as np
import pandas as pd

from ddvc.asset_types import VEHICLE_CANDIDATES, canonical_token
from ddvc.route_roles import (
    component_eligibility,
    component_value_support,
    role_token_values,
)


ROUTE_KEYS = ["tx_hash", "component_id"]
PAIR_KEYS = ["src", "tgt"]
PANEL_KEYS = ["date", "src", "tgt", "candidate_address"]
STRICT_VALUE_SUPPORT = "within_20pct"
ROUTE_INPUT_COLUMNS = [
    "tx_hash",
    "component_id",
    "route_class",
    "token_in",
    "token_out",
    "tin_role",
    "tout_role",
    "amount_usd",
    "log_index",
]
PANEL_COLUMNS = [
    *PANEL_KEYS,
    "candidate_symbol",
    "count_numerator_routes",
    "count_denominator_routes",
    "count_share",
    "count_supported",
    "count_support_reason",
    "strict_value_numerator_routes",
    "strict_value_denominator_routes",
    "strict_value_numerator_usd",
    "strict_value_denominator_usd",
    "strict_value_share",
    "strict_value_supported",
    "strict_value_support_reason",
    "candidate_route_observed",
    "candidate_route_reason",
    "candidate_strict_value_observed",
    "candidate_strict_value_reason",
    "count_leader_address",
    "count_leader_reason",
    "candidate_is_unique_count_leader",
    "strict_value_leader_address",
    "strict_value_leader_reason",
    "candidate_is_unique_strict_value_leader",
    "pair_first_supported_date",
    "pair_last_supported_date",
    "pair_entry_on_day",
    "pair_last_observed_on_day",
    "pair_support_reason",
]
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_CANDIDATES = tuple(sorted(VEHICLE_CANDIDATES))


def _canonical_address(value: object, *, field: str) -> str:
    address = canonical_token(value)
    if address is None or _ADDRESS.fullmatch(address) is None:
        raise ValueError(f"route composition has invalid {field} address: {value!r}")
    return address


def _unique_leader(
    values: Mapping[str, float | int],
) -> tuple[str | None, str]:
    maximum = max(values.values(), default=0)
    if not np.isfinite(float(maximum)) or maximum <= 0:
        return None, "no_candidate_vehicle_route"
    leaders = sorted(address for address, value in values.items() if value == maximum)
    if len(leaders) != 1:
        return None, "tie"
    return leaders[0], "unique"


def _leader_fields(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    count_values = dict(
        zip(
            out["candidate_address"],
            out["count_numerator_routes"],
            strict=True,
        )
    )
    value_values = dict(
        zip(
            out["candidate_address"],
            out["strict_value_numerator_usd"],
            strict=True,
        )
    )
    count_leader, count_reason = _unique_leader(count_values)
    value_leader, value_reason = _unique_leader(value_values)
    out["count_leader_address"] = count_leader
    out["count_leader_reason"] = count_reason
    out["candidate_is_unique_count_leader"] = out["candidate_address"].eq(
        count_leader
    ) if count_leader is not None else False
    out["strict_value_leader_address"] = value_leader
    out["strict_value_leader_reason"] = value_reason
    out["candidate_is_unique_strict_value_leader"] = out[
        "candidate_address"
    ].eq(value_leader) if value_leader is not None else False
    return out


def endpoint_candidate_composition_for_day(
    legs: pd.DataFrame,
    day: str,
) -> pd.DataFrame:
    """Construct pair-candidate cells from one released route day.

    The count denominator is every topology-valid direct or indirect route for
    the ordered endpoint pair. A candidate numerator records intermediary
    involvement, so one route containing two canonical candidates enters both
    candidate numerators while entering the pair denominator once. This matches
    the token-level vehicle-extent contract. The value denominator is the same
    route universe restricted to source/intermediary/sink values agreeing within
    20 percent. A direct-only pair therefore produces supported zero numerators
    for every candidate instead of disappearing as if the pair were unobserved.
    """

    observed_date = pd.to_datetime(day, format="%Y%m%d", errors="raise")
    missing = sorted(set(ROUTE_INPUT_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"route composition is missing columns: {', '.join(missing)}")
    duplicate_events = legs.duplicated(["tx_hash", "log_index"], keep=False)
    if duplicate_events.any():
        sample = legs.loc[duplicate_events, ["tx_hash", "log_index"]].iloc[0].to_dict()
        raise ValueError(f"route composition contains duplicate event identity: {sample}")
    routes = legs.loc[
        legs["route_class"].isin(("single", "coherent")), ROUTE_INPUT_COLUMNS
    ].copy()
    if routes.empty:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    routes["token_in"] = routes["token_in"].map(
        lambda value: _canonical_address(value, field="token_in")
    )
    routes["token_out"] = routes["token_out"].map(
        lambda value: _canonical_address(value, field="token_out")
    )
    routes["amount_usd"] = pd.to_numeric(routes["amount_usd"], errors="coerce")

    eligibility = component_eligibility(routes, keys=ROUTE_KEYS)
    if eligibility.eligible.empty:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    clean = routes.merge(eligibility.eligible[ROUTE_KEYS], on=ROUTE_KEYS, how="inner")
    support = component_value_support(
        clean,
        keys=ROUTE_KEYS,
        token_roles=eligibility.token_roles,
    )
    components = eligibility.eligible[ROUTE_KEYS + PAIR_KEYS].merge(
        support[ROUTE_KEYS + ["amount_usd", STRICT_VALUE_SUPPORT]],
        on=ROUTE_KEYS,
        how="left",
        validate="one_to_one",
    )
    for endpoint in PAIR_KEYS:
        components[endpoint] = components[endpoint].map(
            lambda value: _canonical_address(value, field=endpoint)
        )
    components = components[components["src"].ne(components["tgt"])].copy()
    if components.empty:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    components["strict_value_usd"] = np.where(
        components[STRICT_VALUE_SUPPORT].fillna(False).astype(bool)
        & pd.to_numeric(components["amount_usd"], errors="coerce").gt(0),
        pd.to_numeric(components["amount_usd"], errors="coerce"),
        0.0,
    )
    components["strict_value_route"] = components["strict_value_usd"].gt(0)
    denominators = components.groupby(PAIR_KEYS, as_index=False, sort=True).agg(
        count_denominator_routes=("tx_hash", "size"),
        strict_value_denominator_routes=("strict_value_route", "sum"),
        strict_value_denominator_usd=("strict_value_usd", "sum"),
    )

    intermediates = role_token_values(
        clean,
        "intermediate",
        keys=ROUTE_KEYS,
        token_roles=eligibility.token_roles,
    ).rename(columns={"token": "candidate_address"})
    intermediates["candidate_address"] = intermediates["candidate_address"].map(
        lambda value: _canonical_address(value, field="candidate")
    )
    intermediates = intermediates[
        intermediates["candidate_address"].isin(_CANDIDATES)
    ].merge(
        components[
            ROUTE_KEYS
            + PAIR_KEYS
            + ["strict_value_route", "strict_value_usd"]
        ],
        on=ROUTE_KEYS,
        how="inner",
        validate="many_to_one",
    )
    if intermediates.empty:
        numerators = pd.DataFrame(
            columns=PAIR_KEYS
            + [
                "candidate_address",
                "count_numerator_routes",
                "strict_value_numerator_routes",
                "strict_value_numerator_usd",
            ]
        )
    else:
        numerators = intermediates.groupby(
            PAIR_KEYS + ["candidate_address"], as_index=False, sort=True
        ).agg(
            count_numerator_routes=("tx_hash", "size"),
            strict_value_numerator_routes=("strict_value_route", "sum"),
            strict_value_numerator_usd=("strict_value_usd", "sum"),
        )

    candidates = pd.DataFrame(
        {
            "candidate_address": _CANDIDATES,
            "candidate_symbol": [VEHICLE_CANDIDATES[address] for address in _CANDIDATES],
        }
    )
    panel = denominators.merge(candidates, how="cross").merge(
        numerators,
        on=PAIR_KEYS + ["candidate_address"],
        how="left",
        validate="one_to_one",
    )
    for column in (
        "count_numerator_routes",
        "strict_value_numerator_routes",
    ):
        panel[column] = panel[column].fillna(0).astype("int64")
    panel["strict_value_numerator_usd"] = panel[
        "strict_value_numerator_usd"
    ].fillna(0.0).astype(float)
    panel["count_denominator_routes"] = panel[
        "count_denominator_routes"
    ].astype("int64")
    panel["strict_value_denominator_routes"] = panel[
        "strict_value_denominator_routes"
    ].astype("int64")
    panel["count_share"] = (
        panel["count_numerator_routes"] / panel["count_denominator_routes"]
    )
    panel["count_supported"] = True
    panel["count_support_reason"] = "supported"
    panel["strict_value_supported"] = (
        panel["strict_value_denominator_routes"].gt(0)
        & panel["strict_value_denominator_usd"].gt(0)
    )
    panel["strict_value_share"] = np.where(
        panel["strict_value_supported"],
        panel["strict_value_numerator_usd"]
        / panel["strict_value_denominator_usd"],
        np.nan,
    )
    panel["strict_value_support_reason"] = np.where(
        panel["strict_value_supported"],
        "supported",
        "no_strict_value_routes_for_endpoint_pair",
    )
    panel["candidate_route_observed"] = panel["count_numerator_routes"].gt(0)
    candidate_is_endpoint = panel["candidate_address"].eq(panel["src"]) | panel[
        "candidate_address"
    ].eq(panel["tgt"])
    panel["candidate_route_reason"] = np.select(
        [candidate_is_endpoint, panel["candidate_route_observed"]],
        ["candidate_is_endpoint", "observed"],
        default="no_candidate_vehicle_route",
    )
    panel["candidate_strict_value_observed"] = panel[
        "strict_value_numerator_routes"
    ].gt(0)
    panel["candidate_strict_value_reason"] = np.select(
        [
            candidate_is_endpoint,
            ~panel["strict_value_supported"],
            panel["candidate_strict_value_observed"],
        ],
        ["candidate_is_endpoint", "pair_has_no_strict_value_support", "observed"],
        default="candidate_has_no_strict_value_route",
    )
    panel.insert(0, "date", observed_date)
    panel = pd.concat(
        [_leader_fields(group) for _, group in panel.groupby(PAIR_KEYS, sort=True)],
        ignore_index=True,
    )
    panel["pair_first_supported_date"] = observed_date
    panel["pair_last_supported_date"] = observed_date
    panel["pair_entry_on_day"] = True
    panel["pair_last_observed_on_day"] = True
    panel["pair_support_reason"] = "supported_route_pair"
    return validate_endpoint_candidate_composition(panel)


def finalize_endpoint_candidate_composition(
    daily_panels: Iterable[pd.DataFrame],
) -> pd.DataFrame:
    """Combine daily cells and add sample-relative pair entry/last-support fields."""

    nonempty = [panel for panel in daily_panels if not panel.empty]
    if not nonempty:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    panel = pd.concat(nonempty, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"], errors="raise")
    by_pair = panel.groupby(PAIR_KEYS, sort=False)["date"]
    panel["pair_first_supported_date"] = by_pair.transform("min")
    panel["pair_last_supported_date"] = by_pair.transform("max")
    panel["pair_entry_on_day"] = panel["date"].eq(panel["pair_first_supported_date"])
    panel["pair_last_observed_on_day"] = panel["date"].eq(
        panel["pair_last_supported_date"]
    )
    return validate_endpoint_candidate_composition(panel)


def validate_endpoint_candidate_composition(panel: pd.DataFrame) -> pd.DataFrame:
    """Validate and deterministically order the public panel contract."""

    missing = [column for column in PANEL_COLUMNS if column not in panel.columns]
    extra = [column for column in panel.columns if column not in PANEL_COLUMNS]
    if missing or extra:
        raise ValueError(
            f"endpoint-candidate composition schema mismatch: missing={missing}; extra={extra}"
        )
    out = panel[PANEL_COLUMNS].copy()
    if out.empty:
        return out
    out["date"] = pd.to_datetime(out["date"], errors="raise")
    duplicates = out.duplicated(PANEL_KEYS, keep=False)
    if duplicates.any():
        sample = out.loc[duplicates, PANEL_KEYS].iloc[0].to_dict()
        raise ValueError(f"duplicate endpoint-candidate composition key: {sample}")
    if not out["candidate_address"].isin(_CANDIDATES).all():
        raise ValueError("endpoint-candidate composition contains a noncanonical candidate")
    if not out["src"].map(lambda value: bool(_ADDRESS.fullmatch(str(value)))).all():
        raise ValueError("endpoint-candidate composition contains an invalid source address")
    if not out["tgt"].map(lambda value: bool(_ADDRESS.fullmatch(str(value)))).all():
        raise ValueError("endpoint-candidate composition contains an invalid target address")
    if out["src"].eq(out["tgt"]).any():
        raise ValueError("endpoint-candidate composition contains a round trip")
    if not out["candidate_symbol"].eq(
        out["candidate_address"].map(VEHICLE_CANDIDATES)
    ).all():
        raise ValueError("candidate symbols disagree with exact canonical addresses")
    numeric_columns = (
        "count_numerator_routes",
        "count_denominator_routes",
        "count_share",
        "strict_value_numerator_routes",
        "strict_value_denominator_routes",
        "strict_value_numerator_usd",
        "strict_value_denominator_usd",
    )
    if any(
        pd.to_numeric(out[column], errors="coerce").isna().any()
        or (pd.to_numeric(out[column], errors="coerce") < 0).any()
        for column in numeric_columns
    ):
        raise ValueError("endpoint-candidate composition contains invalid magnitudes")
    if not out["count_denominator_routes"].gt(0).all():
        raise ValueError("supported endpoint-pair cells require a positive count denominator")
    if (out["count_numerator_routes"] > out["count_denominator_routes"]).any():
        raise ValueError("candidate route numerator exceeds its endpoint-pair denominator")
    if (
        out["strict_value_numerator_routes"]
        > out["strict_value_denominator_routes"]
    ).any():
        raise ValueError("candidate strict-value routes exceed endpoint-pair support")
    if out.loc[~out["strict_value_supported"], "strict_value_share"].notna().any():
        raise ValueError("unsupported strict-value cells carry a share")
    expected_count_share = (
        out["count_numerator_routes"] / out["count_denominator_routes"]
    )
    if not np.allclose(out["count_share"], expected_count_share, rtol=0, atol=1e-14):
        raise ValueError("count shares disagree with their numerator and denominator")
    expected_value_support = (
        out["strict_value_denominator_routes"].gt(0)
        & out["strict_value_denominator_usd"].gt(0)
    )
    if not out["strict_value_supported"].eq(expected_value_support).all():
        raise ValueError("strict-value support disagrees with its denominator")
    supported = out["strict_value_supported"]
    expected_value_share = (
        out.loc[supported, "strict_value_numerator_usd"]
        / out.loc[supported, "strict_value_denominator_usd"]
    )
    if not np.allclose(
        out.loc[supported, "strict_value_share"],
        expected_value_share,
        rtol=0,
        atol=1e-14,
    ):
        raise ValueError("strict-value shares disagree with their numerator and denominator")
    if (out["strict_value_numerator_usd"] > out["strict_value_denominator_usd"]).any():
        raise ValueError("candidate strict value exceeds endpoint-pair support")
    repeated = out.groupby(["date", *PAIR_KEYS], sort=False)
    for column in (
        "count_denominator_routes",
        "strict_value_denominator_routes",
        "strict_value_denominator_usd",
        "strict_value_supported",
        "strict_value_support_reason",
    ):
        if not repeated[column].nunique(dropna=False).eq(1).all():
            raise ValueError(f"endpoint-pair denominator field is inconsistent: {column}")
    expected_rows = out.groupby(["date", *PAIR_KEYS]).size()
    if not expected_rows.eq(len(_CANDIDATES)).all():
        raise ValueError("endpoint-pair days do not contain the complete candidate set")
    return out.sort_values(PANEL_KEYS, kind="stable").reset_index(drop=True)

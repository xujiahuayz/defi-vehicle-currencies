"""Pool-level liquidity contributions with complete candidate-day support."""

from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

from ddvc.asset_types import VEHICLE_CANDIDATES, canonical_token
from ddvc.capital_contracts import VALID_CAPITAL_STATUSES, capital_supported
from ddvc.vehicle_extent import compute_vehicle_extent


V2_CAPITAL_FAMILY = "v2_family_deposited_capital_stock"
V3_FLOW_FAMILY = "uniswap_v3_lp_dollar_flow"
V2_QUANTITY_KIND = "deposited_capital"
V3_QUANTITY_KIND = "gross_and_signed_lp_dollar_flow"
V3_NORMALIZATION_STATUS = "dollar_flow_no_capital_stock_denominator"
CONTRIBUTION_KEYS = [
    "date",
    "measurement_family",
    "venue",
    "pool_address",
    "candidate_address",
]
SUPPORT_KEYS = ["date", "measurement_family", "candidate_address"]
CONTRIBUTION_COLUMNS = [
    *CONTRIBUTION_KEYS,
    "candidate_symbol",
    "quantity_kind",
    "gross_contribution_usd",
    "signed_contribution_usd",
    "contribution_event_count",
    "candidate_gross_denominator_usd",
    "all_candidate_gross_denominator_usd",
    "pool_share_within_candidate",
    "pool_candidate_share_of_day",
    "candidate_pool_count",
    "day_pool_count",
    "contribution_support_reason",
]
NORMALIZED_COLUMNS = CONTRIBUTION_KEYS + [
    "candidate_symbol",
    "quantity_kind",
    "gross_contribution_usd",
    "signed_contribution_usd",
    "contribution_event_count",
]
SUPPORT_COLUMNS = [
    *SUPPORT_KEYS,
    "candidate_symbol",
    "quantity_kind",
    "pool_day_supported",
    "candidate_pool_observed",
    "candidate_gross_contribution_usd",
    "candidate_signed_contribution_usd",
    "all_candidate_gross_denominator_usd",
    "candidate_quantity_share_of_day",
    "candidate_pool_count",
    "day_pool_count",
    "pool_support_reason",
    "route_day_supported",
    "route_candidate_observed",
    "route_count_numerator",
    "route_count_denominator",
    "strict_value_numerator_usd",
    "route_endpoint_supported",
    "route_support_reason",
]
_CANDIDATES = tuple(sorted(VEHICLE_CANDIDATES))
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


@dataclass(frozen=True)
class CandidatePoolContributionBundle:
    """Observed real-pool contributions plus a complete five-candidate support grid."""

    contributions: pd.DataFrame
    support: pd.DataFrame


def _exact_address(value: object, *, label: str, allow_zero: bool = True) -> str:
    address = str(value).lower() if isinstance(value, str) else ""
    if (
        _ADDRESS.fullmatch(address) is None
        or (not allow_zero and address == "0x" + "0" * 40)
    ):
        raise ValueError(f"candidate-pool contribution has invalid {label}: {value!r}")
    return address


def _route_token_address(value: object) -> str:
    address = canonical_token(value)
    if address is None or _ADDRESS.fullmatch(address) is None:
        raise ValueError(
            f"candidate-pool contribution has invalid route token address: {value!r}"
        )
    return address


def _candidate_dimension(date: pd.Timestamp, family: str, quantity_kind: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": date,
            "measurement_family": family,
            "candidate_address": _CANDIDATES,
            "candidate_symbol": [VEHICLE_CANDIDATES[address] for address in _CANDIDATES],
            "quantity_kind": quantity_kind,
        }
    )


def _empty_normalized() -> pd.DataFrame:
    return pd.DataFrame(columns=NORMALIZED_COLUMNS)


def _route_support(
    route_rows: pd.DataFrame,
    *,
    date: pd.Timestamp,
    route_day_supported: bool,
) -> pd.DataFrame:
    candidates = _candidate_dimension(date, "_route_support", "_route_support")
    candidates = candidates[["candidate_address", "candidate_symbol"]]
    if not route_day_supported:
        if not route_rows.empty:
            raise ValueError("unsupported route day cannot carry route rows")
        candidates["route_day_supported"] = False
        candidates["route_candidate_observed"] = False
        candidates["route_count_numerator"] = pd.NA
        candidates["route_count_denominator"] = pd.NA
        candidates["strict_value_numerator_usd"] = np.nan
        candidates["route_endpoint_supported"] = False
        candidates["route_support_reason"] = "unavailable"
        return candidates

    extent = compute_vehicle_extent(route_rows)
    route_count_denominator = (
        int(extent["routes_clean"].iloc[0]) if not extent.empty else 0
    )
    if extent.empty:
        observed = pd.DataFrame(
            columns=[
                "candidate_address",
                "route_count_numerator",
                "strict_value_numerator_usd",
                "route_endpoint_supported",
            ]
        )
    else:
        observed = extent.rename(columns={"token": "candidate_address"})
        observed["candidate_address"] = observed["candidate_address"].map(
            _route_token_address
        )
        observed = observed[observed["candidate_address"].isin(_CANDIDATES)].rename(
            columns={
                "intermediate_routes": "route_count_numerator",
                "intermediate_usd_within_20pct": "strict_value_numerator_usd",
                "endpoint_supported": "route_endpoint_supported",
            }
        )[
            [
                "candidate_address",
                "route_count_numerator",
                "strict_value_numerator_usd",
                "route_endpoint_supported",
            ]
        ]
        if observed["candidate_address"].duplicated().any():
            raise ValueError("vehicle extent contains duplicate candidate rows")
    support = candidates.merge(
        observed,
        on="candidate_address",
        how="left",
        validate="one_to_one",
    )
    support["route_day_supported"] = True
    support["route_candidate_observed"] = support["route_count_numerator"].fillna(0).gt(0)
    support["route_count_numerator"] = support["route_count_numerator"].fillna(0).astype("int64")
    support["route_count_denominator"] = route_count_denominator
    support["strict_value_numerator_usd"] = support[
        "strict_value_numerator_usd"
    ].fillna(0.0)
    support["route_endpoint_supported"] = support[
        "route_endpoint_supported"
    ].fillna(False).astype(bool)
    support["route_support_reason"] = np.select(
        [
            support["route_candidate_observed"],
            support["route_count_denominator"].eq(0),
        ],
        ["observed_candidate_intermediation", "supported_no_clean_routes"],
        default="supported_zero_intermediation",
    )
    return support


def _finalize_bundle(
    normalized: pd.DataFrame,
    route_rows: pd.DataFrame,
    *,
    date: pd.Timestamp,
    family: str,
    quantity_kind: str,
    pool_day_supported: bool,
    route_day_supported: bool,
) -> CandidatePoolContributionBundle:
    if not pool_day_supported and not normalized.empty:
        raise ValueError("unsupported pool day cannot carry pool contributions")
    candidates = _candidate_dimension(date, family, quantity_kind)
    route = _route_support(
        route_rows,
        date=date,
        route_day_supported=route_day_supported,
    ).drop(columns="candidate_symbol")
    if normalized.empty:
        contributions = pd.DataFrame(columns=CONTRIBUTION_COLUMNS)
        totals = pd.DataFrame(
            columns=[
                "candidate_address",
                "candidate_gross_contribution_usd",
                "candidate_signed_contribution_usd",
                "candidate_pool_count",
            ]
        )
        day_gross = 0.0
        day_pool_count = 0
    else:
        contributions = normalized.groupby(
            CONTRIBUTION_KEYS
            + ["candidate_symbol", "quantity_kind"],
            as_index=False,
            sort=True,
        ).agg(
            gross_contribution_usd=("gross_contribution_usd", "sum"),
            signed_contribution_usd=(
                "signed_contribution_usd",
                lambda values: values.sum(min_count=1),
            ),
            contribution_event_count=("contribution_event_count", "sum"),
        )
        totals = contributions.groupby("candidate_address", as_index=False).agg(
            candidate_gross_contribution_usd=("gross_contribution_usd", "sum"),
            candidate_signed_contribution_usd=(
                "signed_contribution_usd",
                lambda values: values.sum(min_count=1),
            ),
            candidate_pool_count=("pool_address", "size"),
        )
        day_gross = float(contributions["gross_contribution_usd"].sum())
        day_pool_count = int(
            contributions[["venue", "pool_address"]].drop_duplicates().shape[0]
        )
        contributions = contributions.merge(
            totals,
            on="candidate_address",
            how="left",
            validate="many_to_one",
        ).rename(
            columns={
                "candidate_gross_contribution_usd": "candidate_gross_denominator_usd"
            }
        )
        contributions["all_candidate_gross_denominator_usd"] = day_gross
        contributions["pool_share_within_candidate"] = (
            contributions["gross_contribution_usd"]
            / contributions["candidate_gross_denominator_usd"]
        )
        contributions["pool_candidate_share_of_day"] = (
            contributions["gross_contribution_usd"] / day_gross
        )
        contributions["day_pool_count"] = day_pool_count
        contributions["contribution_support_reason"] = (
            "observed_positive_pool_contribution"
        )
        contributions = contributions.drop(columns="candidate_signed_contribution_usd")
        contributions = contributions[CONTRIBUTION_COLUMNS]

    support = candidates.merge(
        totals,
        on="candidate_address",
        how="left",
        validate="one_to_one",
    ).merge(route, on="candidate_address", how="left", validate="one_to_one")
    support["pool_day_supported"] = bool(pool_day_supported)
    support["candidate_pool_observed"] = support[
        "candidate_gross_contribution_usd"
    ].fillna(0).gt(0)
    if pool_day_supported:
        support["candidate_gross_contribution_usd"] = support[
            "candidate_gross_contribution_usd"
        ].fillna(0.0)
        if family == V3_FLOW_FAMILY:
            support["candidate_signed_contribution_usd"] = support[
                "candidate_signed_contribution_usd"
            ].fillna(0.0)
        support["candidate_pool_count"] = support["candidate_pool_count"].fillna(0).astype("int64")
        support["all_candidate_gross_denominator_usd"] = day_gross
        support["day_pool_count"] = day_pool_count
    else:
        support["all_candidate_gross_denominator_usd"] = np.nan
        support["day_pool_count"] = pd.NA
    gross_numerator = pd.to_numeric(
        support["candidate_gross_contribution_usd"], errors="coerce"
    )
    gross_denominator = pd.to_numeric(
        support["all_candidate_gross_denominator_usd"], errors="coerce"
    )
    support["candidate_quantity_share_of_day"] = gross_numerator.div(
        gross_denominator.where(gross_denominator.gt(0))
    )
    support["pool_support_reason"] = np.select(
        [
            ~support["pool_day_supported"],
            support["candidate_pool_observed"],
        ],
        ["unavailable", "observed_candidate_pools"],
        default="supported_zero_pool_quantity",
    )
    support = support[SUPPORT_COLUMNS]
    return validate_candidate_pool_contribution_bundle(
        CandidatePoolContributionBundle(contributions, support)
    )


def candidate_pool_capital_contributions(
    pool_rows: pd.DataFrame,
    route_rows: pd.DataFrame,
    day: str,
    *,
    pool_day_supported: bool,
    route_day_supported: bool,
) -> CandidatePoolContributionBundle:
    """Preserve V2 pool capital allocated once across exact candidate sides."""

    date = pd.to_datetime(day, format="%Y%m%d", errors="raise")
    if pool_rows.empty:
        normalized = _empty_normalized()
    else:
        required = {
            "day",
            "venue",
            "pool",
            "candidate",
            "candidate_address",
            "allocation_weight",
            "candidate_capital_usd",
            "quantity_kind",
            "capital_validation_status",
        }
        missing = sorted(required - set(pool_rows.columns))
        if missing:
            raise ValueError(f"candidate-capital contribution lacks columns: {missing}")
        rows = pool_rows.copy()
        if not rows["day"].astype(str).str.zfill(8).eq(day).all():
            raise ValueError("candidate-capital contribution mixes calendar days")
        if rows.duplicated(["venue", "pool", "candidate_address"]).any():
            raise ValueError("duplicate pool-candidate capital contribution")
        rows["candidate_address"] = rows["candidate_address"].map(
            lambda value: _exact_address(value, label="candidate address")
        )
        rows["pool"] = rows["pool"].map(
            lambda value: _exact_address(
                value, label="pool address", allow_zero=False
            )
        )
        expected_symbols = rows["candidate_address"].map(VEHICLE_CANDIDATES)
        capital = pd.to_numeric(rows["candidate_capital_usd"], errors="coerce")
        weight = pd.to_numeric(rows["allocation_weight"], errors="coerce")
        if (
            expected_symbols.isna().any()
            or not rows["candidate"].eq(expected_symbols).all()
            or not rows["venue"].map(lambda venue: capital_supported(str(venue))).all()
            or not rows["quantity_kind"].eq(V2_QUANTITY_KIND).all()
            or not rows["capital_validation_status"].isin(VALID_CAPITAL_STATUSES).all()
            or not (np.isfinite(capital) & capital.gt(0)).all()
            or not (np.isfinite(weight) & weight.gt(0) & weight.le(1)).all()
        ):
            raise ValueError("candidate-capital contribution violates identity, quantity, or support")
        allocated_rows = rows.assign(
            _capital=capital,
            _weight=weight,
            _base_capital=capital / weight,
        )
        allocation = allocated_rows.groupby(
            ["venue", "pool"], sort=False
        ).agg(
            weight=("_weight", "sum"),
            allocated=("_capital", "sum"),
            base_min=("_base_capital", "min"),
            base_max=("_base_capital", "max"),
        )
        if (
            ~np.isclose(allocation["weight"], 1.0, rtol=0, atol=1e-12)
            | ~np.isclose(allocation["allocated"], allocation["base_max"], rtol=1e-10, atol=1e-8)
            | ~np.isclose(allocation["base_min"], allocation["base_max"], rtol=1e-10, atol=1e-8)
        ).any():
            raise ValueError("candidate-capital allocation does not conserve pool capital once")
        normalized = pd.DataFrame(
            {
                "date": date,
                "measurement_family": V2_CAPITAL_FAMILY,
                "venue": rows["venue"].astype(str),
                "pool_address": rows["pool"],
                "candidate_address": rows["candidate_address"],
                "candidate_symbol": rows["candidate"],
                "quantity_kind": V2_QUANTITY_KIND,
                "gross_contribution_usd": capital,
                "signed_contribution_usd": np.nan,
                "contribution_event_count": 1,
            }
        )
    return _finalize_bundle(
        normalized,
        route_rows,
        date=date,
        family=V2_CAPITAL_FAMILY,
        quantity_kind=V2_QUANTITY_KIND,
        pool_day_supported=pool_day_supported,
        route_day_supported=route_day_supported,
    )


def candidate_pool_flow_contributions(
    pool_rows: pd.DataFrame,
    route_rows: pd.DataFrame,
    day: str,
    *,
    pool_day_supported: bool,
    route_day_supported: bool,
) -> CandidatePoolContributionBundle:
    """Aggregate V3 gross and signed LP flow without a capital-stock denominator."""

    date = pd.to_datetime(day, format="%Y%m%d", errors="raise")
    if pool_rows.empty:
        normalized = _empty_normalized()
    else:
        required = {
            "day",
            "venue",
            "pool",
            "tx_hash",
            "log_index",
            "candidate",
            "candidate_address",
            "allocation_weight",
            "allocated_event_value_usd",
            "signed_allocated_event_value_usd",
            "event_value_usd",
            "event_sign",
            "flow_normalization_status",
        }
        missing = sorted(required - set(pool_rows.columns))
        if missing:
            raise ValueError(f"candidate-flow contribution lacks columns: {missing}")
        rows = pool_rows.copy()
        if not rows["day"].astype(str).str.zfill(8).eq(day).all():
            raise ValueError("candidate-flow contribution mixes calendar days")
        if rows.duplicated(["venue", "tx_hash", "log_index", "candidate_address"]).any():
            raise ValueError("duplicate event-candidate flow contribution")
        rows["candidate_address"] = rows["candidate_address"].map(
            lambda value: _exact_address(value, label="candidate address")
        )
        rows["pool"] = rows["pool"].map(
            lambda value: _exact_address(
                value, label="pool address", allow_zero=False
            )
        )
        expected_symbols = rows["candidate_address"].map(VEHICLE_CANDIDATES)
        gross = pd.to_numeric(rows["allocated_event_value_usd"], errors="coerce")
        signed = pd.to_numeric(rows["signed_allocated_event_value_usd"], errors="coerce")
        event_value = pd.to_numeric(rows["event_value_usd"], errors="coerce")
        event_sign = pd.to_numeric(rows["event_sign"], errors="coerce")
        weight = pd.to_numeric(rows["allocation_weight"], errors="coerce")
        if (
            expected_symbols.isna().any()
            or not rows["candidate"].eq(expected_symbols).all()
            or not rows["venue"].eq("uniswap_v3").all()
            or not rows["flow_normalization_status"].eq(V3_NORMALIZATION_STATUS).all()
            or not (np.isfinite(gross) & gross.gt(0)).all()
            or not np.isfinite(signed).all()
            or not (np.isfinite(event_value) & event_value.gt(0)).all()
            or not event_sign.isin((-1, 1)).all()
            or not (np.isfinite(weight) & weight.gt(0) & weight.le(1)).all()
            or not np.allclose(gross, event_value * weight, rtol=1e-10, atol=1e-8)
            or not np.allclose(signed, event_sign * gross, rtol=1e-10, atol=1e-8)
        ):
            raise ValueError("candidate-flow contribution violates identity, quantity, or support")
        allocated_events = rows.assign(
            _weight=weight,
            _gross=gross,
            _event_value=event_value,
        ).groupby(
            ["venue", "tx_hash", "log_index"], sort=False
        ).agg(
            weight=("_weight", "sum"),
            allocated=("_gross", "sum"),
            base_min=("_event_value", "min"),
            base_max=("_event_value", "max"),
        )
        if (
            ~np.isclose(allocated_events["weight"], 1.0, rtol=0, atol=1e-12)
            | ~np.isclose(
                allocated_events["allocated"],
                allocated_events["base_max"],
                rtol=1e-10,
                atol=1e-8,
            )
            | ~np.isclose(
                allocated_events["base_min"],
                allocated_events["base_max"],
                rtol=1e-10,
                atol=1e-8,
            )
        ).any():
            raise ValueError("candidate-flow allocation does not conserve each event once")
        normalized = pd.DataFrame(
            {
                "date": date,
                "measurement_family": V3_FLOW_FAMILY,
                "venue": rows["venue"].astype(str),
                "pool_address": rows["pool"],
                "candidate_address": rows["candidate_address"],
                "candidate_symbol": rows["candidate"],
                "quantity_kind": V3_QUANTITY_KIND,
                "gross_contribution_usd": gross,
                "signed_contribution_usd": signed,
                "contribution_event_count": 1,
            }
        )
    return _finalize_bundle(
        normalized,
        route_rows,
        date=date,
        family=V3_FLOW_FAMILY,
        quantity_kind=V3_QUANTITY_KIND,
        pool_day_supported=pool_day_supported,
        route_day_supported=route_day_supported,
    )


def validate_candidate_pool_contribution_bundle(
    bundle: CandidatePoolContributionBundle,
) -> CandidatePoolContributionBundle:
    """Enforce exact identities, conservation, support geometry, and stable order."""

    contributions = bundle.contributions.copy()
    support = bundle.support.copy()
    if list(contributions.columns) != CONTRIBUTION_COLUMNS:
        raise ValueError("candidate-pool contribution schema is stale")
    if list(support.columns) != SUPPORT_COLUMNS:
        raise ValueError("candidate-pool support schema is stale")
    if contributions.duplicated(CONTRIBUTION_KEYS).any():
        raise ValueError("duplicate candidate-pool-day contribution key")
    if support.empty or support.duplicated(SUPPORT_KEYS).any():
        raise ValueError("candidate-pool support is empty or has duplicate keys")
    if not support.groupby(["date", "measurement_family"])["candidate_address"].nunique().eq(len(_CANDIDATES)).all():
        raise ValueError("candidate-pool support does not contain all five candidates")
    if not support["candidate_address"].isin(_CANDIDATES).all():
        raise ValueError("candidate-pool support contains a noncanonical candidate")
    if not support["candidate_symbol"].eq(support["candidate_address"].map(VEHICLE_CANDIDATES)).all():
        raise ValueError("candidate-pool support symbols disagree with exact addresses")
    if not contributions.empty:
        if not contributions["candidate_address"].isin(_CANDIDATES).all():
            raise ValueError("candidate-pool contribution contains a noncanonical candidate")
        if not contributions["pool_address"].map(lambda value: bool(_ADDRESS.fullmatch(str(value)))).all():
            raise ValueError("candidate-pool contribution contains an invalid pool address")
        gross = pd.to_numeric(contributions["gross_contribution_usd"], errors="coerce")
        if not (np.isfinite(gross) & gross.gt(0)).all():
            raise ValueError("candidate-pool gross contributions must be finite positive")
        capital = contributions["measurement_family"].eq(V2_CAPITAL_FAMILY)
        flow = contributions["measurement_family"].eq(V3_FLOW_FAMILY)
        signed = pd.to_numeric(contributions["signed_contribution_usd"], errors="coerce")
        if (
            (~(capital | flow)).any()
            or contributions.loc[capital, "signed_contribution_usd"].notna().any()
            or not np.isfinite(signed.loc[flow]).all()
            or (signed.loc[flow].abs() > gross.loc[flow] + 1e-8).any()
        ):
            raise ValueError("candidate-pool quantities mix stock, gross flow, or signed flow")
        candidate_groups = ["date", "measurement_family", "candidate_address"]
        day_groups = ["date", "measurement_family"]
        expected_candidate_gross = contributions.groupby(candidate_groups)[
            "gross_contribution_usd"
        ].transform("sum")
        expected_day_gross = contributions.groupby(day_groups)[
            "gross_contribution_usd"
        ].transform("sum")
        expected_candidate_pools = contributions.groupby(candidate_groups)[
            "pool_address"
        ].transform("size")
        expected_day_pools = contributions.groupby(day_groups).apply(
            lambda rows: rows[["venue", "pool_address"]].drop_duplicates().shape[0],
            include_groups=False,
        )
        observed_day_pools = pd.MultiIndex.from_frame(
            contributions[day_groups]
        ).map(expected_day_pools)
        if (
            not np.allclose(
                contributions["candidate_gross_denominator_usd"],
                expected_candidate_gross,
                rtol=0,
                atol=1e-8,
            )
            or not np.allclose(
                contributions["all_candidate_gross_denominator_usd"],
                expected_day_gross,
                rtol=0,
                atol=1e-8,
            )
            or not contributions["candidate_pool_count"].eq(
                expected_candidate_pools
            ).all()
            or not contributions["day_pool_count"].eq(observed_day_pools).all()
            or not np.allclose(
                contributions["pool_share_within_candidate"],
                gross / expected_candidate_gross,
                rtol=0,
                atol=1e-12,
            )
            or not np.allclose(
                contributions["pool_candidate_share_of_day"],
                gross / expected_day_gross,
                rtol=0,
                atol=1e-12,
            )
        ):
            raise ValueError("candidate-pool denominators do not add up to contributions")
        within = contributions.groupby(
            ["date", "measurement_family", "candidate_address"]
        )["pool_share_within_candidate"].sum()
        overall = contributions.groupby(["date", "measurement_family"])[
            "pool_candidate_share_of_day"
        ].sum()
        if not np.allclose(within, 1.0, rtol=0, atol=1e-12) or not np.allclose(
            overall, 1.0, rtol=0, atol=1e-12
        ):
            raise ValueError("candidate-pool shares do not conserve their denominators")
    supported = support["pool_day_supported"]
    if support.loc[
        ~supported,
        [
            "candidate_gross_contribution_usd",
            "all_candidate_gross_denominator_usd",
            "candidate_quantity_share_of_day",
        ],
    ].notna().any().any():
        raise ValueError("unsupported pool days carry measured quantities")
    positive_day = supported & support["all_candidate_gross_denominator_usd"].gt(0)
    share_sums = support.loc[positive_day].groupby(
        ["date", "measurement_family"]
    )["candidate_quantity_share_of_day"].sum()
    if not np.allclose(
        share_sums,
        1.0,
        rtol=0,
        atol=1e-12,
    ):
        raise ValueError("candidate-day quantity shares do not sum to one")
    support_capital = support["measurement_family"].eq(V2_CAPITAL_FAMILY)
    support_flow = support["measurement_family"].eq(V3_FLOW_FAMILY)
    support_signed = pd.to_numeric(
        support["candidate_signed_contribution_usd"], errors="coerce"
    )
    if (
        (~(support_capital | support_flow)).any()
        or support.loc[support_capital, "candidate_signed_contribution_usd"].notna().any()
        or support.loc[support_flow & supported, "candidate_signed_contribution_usd"].isna().any()
        or (
            support_signed.loc[support_flow & supported].abs()
            > support.loc[support_flow & supported, "candidate_gross_contribution_usd"]
            + 1e-8
        ).any()
    ):
        raise ValueError("candidate-day support mixes stock, gross flow, or signed flow")
    supported_values = support.loc[supported].copy()
    candidate_gross = pd.to_numeric(
        supported_values["candidate_gross_contribution_usd"], errors="coerce"
    )
    if not (np.isfinite(candidate_gross) & candidate_gross.ge(0)).all():
        raise ValueError("supported candidate-day gross quantities must be finite nonnegative")
    supported_values["_candidate_gross"] = candidate_gross
    expected_support_day_gross = supported_values.groupby(
        ["date", "measurement_family"]
    )["_candidate_gross"].transform("sum")
    if not np.allclose(
        supported_values["all_candidate_gross_denominator_usd"],
        expected_support_day_gross,
        rtol=0,
        atol=1e-8,
    ):
        raise ValueError("candidate-day gross quantities do not add to their denominator")
    if not contributions.empty:
        expected = contributions.groupby(
            ["date", "measurement_family", "candidate_address"], as_index=False
        ).agg(
            gross=("gross_contribution_usd", "sum"),
            signed=("signed_contribution_usd", lambda values: values.sum(min_count=1)),
            pools=("pool_address", "size"),
        )
        observed = supported_values.merge(
            expected,
            on=["date", "measurement_family", "candidate_address"],
            how="left",
            validate="one_to_one",
        )
        expected_gross = observed["gross"].fillna(0.0)
        expected_pools = observed["pools"].fillna(0).astype("int64")
        if (
            not np.allclose(
                observed["candidate_gross_contribution_usd"],
                expected_gross,
                rtol=0,
                atol=1e-8,
            )
            or not observed["candidate_pool_count"].eq(expected_pools).all()
        ):
            raise ValueError("candidate-day support disagrees with pool contributions")
    contributions = contributions.sort_values(CONTRIBUTION_KEYS, kind="stable").reset_index(drop=True)
    support = support.sort_values(SUPPORT_KEYS, kind="stable").reset_index(drop=True)
    return CandidatePoolContributionBundle(contributions, support)

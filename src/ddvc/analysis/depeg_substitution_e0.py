"""Count-only E0 tests of intermediary substitution around stablecoin stress.

The economic unit is an exact two-leg route with one intermediary.  The design
holds the ordered source--destination pair fixed and requires the stressed asset
and at least one other intermediary to be observed before the event.  It is a
descriptive event comparison, not a causal design.

TerraUSD's Shuttle and Wormhole representations are collapsed before route
topology is computed.  The original representation remains attached to each
route so the combined result can be compared with wrapper-restricted samples.
Token amounts and dollar values are deliberately outside this module's schema.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
from typing import Iterable

import numpy as np
import pandas as pd

from ddvc.asset_types import STABLE, canonical_token
from ddvc.route_roles import component_eligibility


UST_SHUTTLE = "0xa47c8bf37f92abed4a126bda807a7b7498661acd"
UST_WORMHOLE = "0xa693b19d2931d498c5b318df961919bb4aee87a5"
UST_REPRESENTATIONS = frozenset({UST_SHUTTLE, UST_WORMHOLE})
TERRA_UST = "terra_ust"
USDC = next(address for address, symbol in STABLE.items() if symbol == "USDC")
DAI = next(address for address, symbol in STABLE.items() if symbol == "DAI")

ROUTE_KEYS = ["tx_hash", "component_id"]
INPUT_COLUMNS = [
    "tx_hash",
    "component_id",
    "source",
    "token_in",
    "token_out",
    "log_index",
    "route_class",
    "timestamp_utc",
]
ROUTE_COLUMNS = [
    *ROUTE_KEYS,
    "timestamp_utc",
    "hour_utc",
    "src",
    "tgt",
    "vehicle",
    "ust_representation",
]
HOURLY_COLUMNS = [
    "event",
    "target_symbol",
    "representation_scope",
    "window_hours",
    "event_shift_hours",
    "hour_utc",
    "period",
    "src",
    "tgt",
    "target_routes",
    "comparison_routes",
    "all_routes",
    "target_share",
    "ust_shuttle_routes",
    "ust_wormhole_routes",
    "ust_mixed_wrapper_routes",
]

STATUS = "provisional_diagnostic_only"
CLAIM_GATE = "red"
PROMOTION_ELIGIBLE = False


@dataclass(frozen=True)
class EventSpec:
    name: str
    target_symbol: str
    target_address: str
    event_time: pd.Timestamp
    primary_window_hours: int
    baseline_lag_weeks: tuple[int, ...] = ()
    anchor_definition: str = "registered event timestamp"
    anchor_citation: str = ""
    timestamp_precision: str = "exact"
    exclude_anchor_hour: bool = False

    def __post_init__(self) -> None:
        timestamp = pd.Timestamp(self.event_time)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        if self.primary_window_hours < 1:
            raise ValueError("primary event window must be positive")
        if any(lag < 1 for lag in self.baseline_lag_weeks):
            raise ValueError("matched baseline lags must be positive weeks")
        if len(self.baseline_lag_weeks) != len(set(self.baseline_lag_weeks)):
            raise ValueError("matched baseline lags must be unique")
        object.__setattr__(self, "event_time", timestamp)

    @property
    def analysis_hour(self) -> pd.Timestamp:
        """First complete UTC hour after the source event timestamp."""

        floored = self.event_time.floor("h")
        if self.exclude_anchor_hour:
            return floored + pd.Timedelta(hours=1)
        return floored if self.event_time == floored else self.event_time.ceil("h")

    @property
    def containing_hour(self) -> pd.Timestamp:
        """UTC hour containing the cited event timestamp."""

        return self.event_time.floor("h")


EVENTS = (
    EventSpec(
        "terra_ust_stress",
        "UST",
        TERRA_UST,
        pd.Timestamp("2022-05-07T05:00:00Z"),
        72,
        (),
        "first disclosed large Anchor withdrawal; Wallet A withdrew 45m UST around 05:00 UTC",
        "LiuMakarovSchoar2023Terra",
        "hour_approximate",
        True,
    ),
    EventSpec(
        "usdc_svb_wire_clearance_confirmation",
        "USDC",
        USDC,
        pd.Timestamp("2023-03-10T23:50:35.386Z"),
        24,
        (1, 2, 3, 4),
        "Circle confirmed that wires initiated to transfer balances from SVB had not cleared",
        "CircleStatus1634341007306248199",
        "millisecond_timestamp",
        True,
    ),
)

UST_ALTERNATIVE_ANCHORS = (
    EventSpec(
        "terra_tfl_liquidity_removal",
        "UST",
        TERRA_UST,
        pd.Timestamp("2022-05-07T21:44:00Z"),
        72,
        (),
        "TFL removed 150m UST from UST-3Crv and selling intensified",
        "LiuMakarovSchoar2023Terra",
        "minute_timestamp",
        True,
    ),
    EventSpec(
        "terra_first_run_day",
        "UST",
        TERRA_UST,
        pd.Timestamp("2022-05-08T00:00:00Z"),
        72,
        (),
        "daily first-day-of-run convention; not the first on-chain sign",
        "AnaduEtAl2023StablecoinRuns",
        "daily_convention",
        True,
    ),
)

USDC_EVENT_MARKERS = (
    (
        "circle_quantified_svb_exposure",
        pd.Timestamp("2023-03-11T03:11:15.210Z"),
        "Circle quantified the reserve balance remaining at SVB",
        "CircleStatus1634391505988206592",
        "https://x.com/circle/status/1634391505988206592",
    ),
    (
        "federal_reserve_depositor_access_announcement",
        pd.Timestamp("2023-03-12T22:15:00Z"),
        "Federal Reserve, Treasury, and FDIC announced that SVB depositors would have access to all funds",
        "FederalReserve2023JointStatementSVBSignature",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20230312b.htm",
    ),
)

EVENT_SOURCES = {
    "terra_ust_stress": (
        "LiuMakarovSchoar2023Terra",
        "https://www.nber.org/papers/w31160",
    ),
    "terra_tfl_liquidity_removal": (
        "LiuMakarovSchoar2023Terra",
        "https://www.nber.org/papers/w31160",
    ),
    "terra_first_run_day": (
        "AnaduEtAl2023StablecoinRuns",
        "https://www.bostonfed.org/publications/supervisory-research-and-analysis-notes/2023/runs-and-flights-to-safety-are-stablecoins-the-new-money-market-funds.aspx",
    ),
    "usdc_svb_wire_clearance_confirmation": (
        "CircleStatus1634341007306248199",
        "https://x.com/circle/status/1634341007306248199",
    ),
}

REGISTERED_MAJOR_EVENTS = {
    "terra_ust_stress": pd.Timestamp("2022-05-07T05:00:00Z"),
    "usdc_svb_wire_clearance_confirmation": pd.Timestamp(
        "2023-03-10T23:50:35.386Z"
    ),
    "usdc_circle_quantified_svb_exposure": pd.Timestamp(
        "2023-03-11T03:11:15.210Z"
    ),
    "usdc_federal_reserve_depositor_access_announcement": pd.Timestamp(
        "2023-03-12T22:15:00Z"
    ),
}


@dataclass(frozen=True)
class TimingAssignment:
    """One disjoint timing comparison outside the focal design."""

    label: str
    pre_start: pd.Timestamp
    post_start: pd.Timestamp
    window_hours: int

    @property
    def intervals(self) -> tuple[tuple[pd.Timestamp, pd.Timestamp], ...]:
        width = pd.Timedelta(hours=self.window_hours)
        return ((self.pre_start, self.pre_start + width), (self.post_start, self.post_start + width))


def intervals_overlap(
    left: tuple[pd.Timestamp, pd.Timestamp],
    right: tuple[pd.Timestamp, pd.Timestamp],
) -> bool:
    """Return whether two half-open time intervals overlap."""

    return left[0] < right[1] and right[0] < left[1]


def focal_intervals(event: EventSpec, window_hours: int | None = None) -> tuple[tuple[pd.Timestamp, pd.Timestamp], ...]:
    """All pre and post intervals occupied by the registered focal design."""

    width_hours = event.primary_window_hours if window_hours is None else window_hours
    width = pd.Timedelta(hours=width_hours)
    anchor = event.analysis_hour
    pre_end = event.containing_hour if event.exclude_anchor_hour else anchor
    pre = (
        tuple((anchor - pd.Timedelta(weeks=lag), anchor - pd.Timedelta(weeks=lag) + width) for lag in event.baseline_lag_weeks)
        if event.baseline_lag_weeks
        else ((pre_end - width, pre_end),)
    )
    return (*pre, (anchor, anchor + width))


def validate_timing_assignments(
    event: EventSpec,
    assignments: tuple[TimingAssignment, ...],
    *,
    focal_window_hours: int | None = None,
) -> None:
    """Reject any focal/comparison or comparison/comparison window collision."""

    occupied = list(focal_intervals(event, focal_window_hours))
    labels = [f"focal_{index}" for index in range(len(occupied))]
    for assignment in assignments:
        if assignment.window_hours < 1 or assignment.post_start <= assignment.pre_start:
            raise ValueError(f"invalid timing assignment: {assignment.label}")
        for interval_name, interval in zip(("pre", "post"), assignment.intervals, strict=True):
            for prior_label, prior in zip(labels, occupied, strict=True):
                if intervals_overlap(interval, prior):
                    raise ValueError(
                        f"timing window collision: {assignment.label}_{interval_name} overlaps {prior_label}"
                    )
            occupied.append(interval)
            labels.append(f"{assignment.label}_{interval_name}")


def _empty_routes() -> pd.DataFrame:
    return pd.DataFrame(columns=ROUTE_COLUMNS)


def _canonical_depeg_token(value: object) -> str:
    token = canonical_token(value)
    if token is None:
        return ""
    return TERRA_UST if token in UST_REPRESENTATIONS else token


def _ust_representation(values: Iterable[str]) -> str:
    wrappers = set(values) & UST_REPRESENTATIONS
    if wrappers == {UST_SHUTTLE}:
        return "shuttle"
    if wrappers == {UST_WORMHOLE}:
        return "wormhole"
    if wrappers == UST_REPRESENTATIONS:
        return "mixed_wrappers"
    return "not_applicable"


def extract_count_routes(legs: pd.DataFrame) -> pd.DataFrame:
    """Return exact two-leg intermediary routes without reading any value field."""

    missing = sorted(set(INPUT_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"depeg substitution input is missing columns: {', '.join(missing)}")
    if any(column in legs.columns for column in ("amount_in", "amount_out", "amount_usd")):
        # Callers may hold wider route frames, but the experiment must make the
        # count-only boundary visible by selecting the declared schema first.
        legs = legs[INPUT_COLUMNS]
    else:
        legs = legs.copy()
    if legs.empty:
        return _empty_routes()

    legs["tx_hash"] = legs["tx_hash"].astype(str).str.lower()
    legs["component_id"] = pd.to_numeric(legs["component_id"], errors="raise").astype("int64")
    legs["log_index"] = pd.to_numeric(legs["log_index"], errors="raise").astype("int64")
    legs["timestamp_utc"] = pd.to_numeric(legs["timestamp_utc"], errors="raise").astype("int64")
    if legs.duplicated(["source", "tx_hash", "log_index"], keep=False).any():
        sample = legs.loc[
            legs.duplicated(["source", "tx_hash", "log_index"], keep=False),
            ["source", "tx_hash", "log_index"],
        ].iloc[0].to_dict()
        raise ValueError(f"depeg substitution contains duplicate route-leg identity: {sample}")

    # A provider-coordinate collision is not two economic swaps.  Match the
    # existing endpoint-composition owner by quarantining every touched route
    # component rather than choosing a venue-specific payload here.
    source_counts = legs.groupby(["tx_hash", "log_index"])["source"].transform("nunique")
    collision_keys = legs.loc[source_counts.gt(1), ROUTE_KEYS].drop_duplicates()
    collision_components = len(collision_keys)
    if collision_components:
        legs = legs.merge(
            collision_keys.assign(_collision=True),
            on=ROUTE_KEYS,
            how="left",
            validate="many_to_one",
        )
        legs = legs.loc[legs["_collision"].isna()].drop(columns="_collision")

    clean_components = (
        legs.groupby(ROUTE_KEYS)["route_class"]
        .agg(lambda values: bool(values.eq("coherent").all()))
    )
    clean_keys = clean_components[clean_components].index.to_frame(index=False)
    legs = legs.merge(
        clean_keys, on=ROUTE_KEYS, how="inner", validate="many_to_one"
    )
    if legs.empty:
        return _empty_routes()
    raw_tokens = pd.concat(
        [
            legs[ROUTE_KEYS + ["token_in"]].rename(columns={"token_in": "token"}),
            legs[ROUTE_KEYS + ["token_out"]].rename(columns={"token_out": "token"}),
        ],
        ignore_index=True,
    )
    raw_tokens["token"] = raw_tokens["token"].map(
        lambda value: canonical_token(value) or ""
    )
    representations = raw_tokens.groupby(ROUTE_KEYS, as_index=False).agg(
        ust_representation=("token", _ust_representation)
    )

    # This order is the scientific contract: collapse equivalent UST bridge
    # instruments, then remove canonical self-edges, then infer topology.
    legs["token_in"] = legs["token_in"].map(_canonical_depeg_token)
    legs["token_out"] = legs["token_out"].map(_canonical_depeg_token)
    legs = legs[
        legs["token_in"].astype(bool)
        & legs["token_out"].astype(bool)
        & legs["token_in"].ne(legs["token_out"])
    ].copy()
    if legs.empty:
        return _empty_routes()
    legs = legs.sort_values([*ROUTE_KEYS, "log_index"], kind="stable")

    timestamps = legs.groupby(ROUTE_KEYS)["timestamp_utc"].nunique()
    if timestamps.gt(1).any():
        raise ValueError("one route component spans multiple transaction timestamps")
    components = legs.groupby(ROUTE_KEYS, as_index=False).agg(
        legs=("log_index", "size"),
        timestamp_utc=("timestamp_utc", "first"),
    )
    components = components[components["legs"].eq(2)].copy()
    if components.empty:
        return _empty_routes()

    scoped = legs.merge(components[ROUTE_KEYS], on=ROUTE_KEYS, how="inner", validate="many_to_one")
    eligibility = component_eligibility(scoped, keys=ROUTE_KEYS)
    roles = eligibility.token_roles
    vehicles = roles.loc[roles["role"].eq("intermediate")].rename(
        columns={"token": "vehicle"}
    )
    vehicle_counts = vehicles.groupby(ROUTE_KEYS)["vehicle"].transform("nunique")
    vehicles = vehicles.loc[vehicle_counts.eq(1), [*ROUTE_KEYS, "vehicle"]]
    if vehicles.empty:
        return _empty_routes()

    out = components.merge(
        eligibility.eligible[[*ROUTE_KEYS, "src", "tgt"]],
        on=ROUTE_KEYS,
        how="inner",
        validate="one_to_one",
    ).merge(
        vehicles,
        on=ROUTE_KEYS,
        how="inner",
        validate="one_to_one",
    ).merge(
        representations,
        on=ROUTE_KEYS,
        how="left",
        validate="one_to_one",
    )
    out = out[out["vehicle"].ne(out["src"]) & out["vehicle"].ne(out["tgt"])].copy()
    out["hour_utc"] = pd.to_datetime(
        out["timestamp_utc"], unit="s", utc=True
    ).dt.floor("h")
    result = out[ROUTE_COLUMNS].sort_values(
        ["hour_utc", *ROUTE_KEYS], kind="stable"
    ).reset_index(drop=True)
    result.attrs["provider_coordinate_collision_components_excluded"] = collision_components
    return result


def aggregate_hourly_routes(routes: pd.DataFrame) -> pd.DataFrame:
    """Aggregate route identities only after topology has fixed their roles."""

    missing = sorted(set(ROUTE_COLUMNS) - set(routes.columns))
    if missing:
        raise ValueError(f"count-route frame is missing columns: {', '.join(missing)}")
    if routes.empty:
        return pd.DataFrame(
            columns=["hour_utc", "src", "tgt", "vehicle", "ust_representation", "routes"]
        )
    return (
        routes.groupby(
            ["hour_utc", "src", "tgt", "vehicle", "ust_representation"],
            as_index=False,
            sort=True,
        )
        .size()
        .rename(columns={"size": "routes"})
    )


def _representation_sample(
    routes: pd.DataFrame, event: EventSpec, representation_scope: str
) -> pd.DataFrame:
    if event.target_address != TERRA_UST:
        if representation_scope != "combined":
            raise ValueError("wrapper robustness applies only to TerraUSD")
        return routes.copy()
    allowed = {
        "combined": {"shuttle", "wormhole", "mixed_wrappers"},
        "single_wrapper_only": {"shuttle", "wormhole"},
        "shuttle_only": {"shuttle"},
        "wormhole_only": {"wormhole"},
    }
    if representation_scope not in allowed:
        raise ValueError(f"unknown TerraUSD representation scope: {representation_scope}")
    keep = routes["vehicle"].ne(TERRA_UST) | routes["ust_representation"].isin(
        allowed[representation_scope]
    )
    return routes.loc[keep].copy()


def event_hourly_panel(
    hourly_routes: pd.DataFrame,
    event: EventSpec,
    *,
    window_hours: int | None = None,
    event_shift_hours: int = 0,
    representation_scope: str = "combined",
    baseline_lag_weeks: tuple[int, ...] | None = None,
    fixed_pairs: tuple[tuple[str, str], ...] | None = None,
    comparator_exclusions: frozenset[str] = frozenset(),
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build a balanced pair-hour panel on fixed pre-event comparison support."""

    if window_hours is None:
        window_hours = event.primary_window_hours
    if window_hours < 1:
        raise ValueError("event window must contain at least one hour")
    anchor = event.analysis_hour + pd.Timedelta(hours=event_shift_hours)
    selected_lags = (
        event.baseline_lag_weeks
        if baseline_lag_weeks is None
        else baseline_lag_weeks
    )
    if any(lag < 1 for lag in selected_lags) or len(selected_lags) != len(set(selected_lags)):
        raise ValueError("matched baseline lags must be unique positive weeks")
    post_start = anchor
    post_end = anchor + pd.Timedelta(hours=window_hours)
    if selected_lags:
        pre_windows = tuple(
            (
                anchor - pd.Timedelta(weeks=lag),
                anchor - pd.Timedelta(weeks=lag) + pd.Timedelta(hours=window_hours),
            )
            for lag in selected_lags
        )
    else:
        containing_hour = event.containing_hour + pd.Timedelta(
            hours=event_shift_hours
        )
        pre_end = containing_hour if event.exclude_anchor_hour else anchor
        pre_windows = ((pre_end - pd.Timedelta(hours=window_hours), pre_end),)
    pre_mask = pd.Series(False, index=hourly_routes.index)
    for pre_start, pre_end in pre_windows:
        pre_mask |= hourly_routes["hour_utc"].ge(pre_start) & hourly_routes["hour_utc"].lt(pre_end)
    post_mask = hourly_routes["hour_utc"].ge(post_start) & hourly_routes["hour_utc"].lt(post_end)
    sample = hourly_routes[pre_mask | post_mask].copy()
    sample = _representation_sample(sample, event, representation_scope)
    if comparator_exclusions:
        sample = sample[
            sample["vehicle"].eq(event.target_address)
            | ~sample["vehicle"].isin(comparator_exclusions)
        ].copy()
    sample["target"] = sample["vehicle"].eq(event.target_address)
    sample["period"] = np.where(sample["hour_utc"].lt(post_start), "pre", "post")

    pair_period = sample.groupby(["src", "tgt", "period"], as_index=False).agg(
        all_routes=("routes", "sum"),
        target_routes=("routes", lambda values: int(values[sample.loc[values.index, "target"]].sum())),
        comparison_routes=("routes", lambda values: int(values[~sample.loc[values.index, "target"]].sum())),
    )
    pre = pair_period[pair_period["period"].eq("pre")].set_index(["src", "tgt"])
    if fixed_pairs is None:
        supported = pre[
            pre["target_routes"].gt(0) & pre["comparison_routes"].gt(0)
        ].index
        pairs = list(supported)
        pair_population = "fixed from focal pre-event target and non-target activity"
    else:
        pairs = list(dict.fromkeys(fixed_pairs))
        pair_population = "frozen from focal event pre-support"

    hours = pd.DatetimeIndex([
        *(
            hour
            for pre_start, pre_end in pre_windows
            for hour in pd.date_range(pre_start, pre_end, freq="h", inclusive="left")
        ),
        *pd.date_range(post_start, post_end, freq="h", inclusive="left"),
    ])
    if not pairs:
        empty = pd.DataFrame(columns=HOURLY_COLUMNS)
        return empty, _summary_record(
            empty,
            event,
            anchor=anchor,
            window_hours=window_hours,
            event_shift_hours=event_shift_hours,
            representation_scope=representation_scope,
            supported_pairs=0,
            baseline_lag_weeks=selected_lags,
            comparator_exclusions=comparator_exclusions,
            pair_population=pair_population,
        )

    selected = sample.merge(
        pd.DataFrame(pairs, columns=["src", "tgt"]),
        on=["src", "tgt"],
        how="inner",
        validate="many_to_one",
    )
    selected["target_routes"] = selected["routes"].where(selected["target"], 0)
    selected["comparison_routes"] = selected["routes"].where(~selected["target"], 0)
    selected["ust_shuttle_routes"] = selected["routes"].where(
        selected["target"] & selected["ust_representation"].eq("shuttle"), 0
    )
    selected["ust_wormhole_routes"] = selected["routes"].where(
        selected["target"] & selected["ust_representation"].eq("wormhole"), 0
    )
    selected["ust_mixed_wrapper_routes"] = selected["routes"].where(
        selected["target"] & selected["ust_representation"].eq("mixed_wrappers"), 0
    )
    observed = selected.groupby(["hour_utc", "src", "tgt"], as_index=False).agg(
        target_routes=("target_routes", "sum"),
        comparison_routes=("comparison_routes", "sum"),
        ust_shuttle_routes=("ust_shuttle_routes", "sum"),
        ust_wormhole_routes=("ust_wormhole_routes", "sum"),
        ust_mixed_wrapper_routes=("ust_mixed_wrapper_routes", "sum"),
    )
    grid = pd.DataFrame(
        product(hours, pairs), columns=["hour_utc", "pair"]
    )
    grid[["src", "tgt"]] = pd.DataFrame(grid.pop("pair").tolist(), index=grid.index)
    panel = grid.merge(
        observed,
        on=["hour_utc", "src", "tgt"],
        how="left",
        validate="one_to_one",
    )
    count_columns = [
        "target_routes",
        "comparison_routes",
        "ust_shuttle_routes",
        "ust_wormhole_routes",
        "ust_mixed_wrapper_routes",
    ]
    panel[count_columns] = panel[
        count_columns
    ].fillna(0).astype("int64")
    panel["all_routes"] = panel["target_routes"] + panel["comparison_routes"]
    panel["target_share"] = panel["target_routes"].div(
        panel["all_routes"].where(panel["all_routes"].gt(0))
    )
    panel["period"] = np.where(panel["hour_utc"].lt(post_start), "pre", "post")
    panel.insert(0, "event_shift_hours", int(event_shift_hours))
    panel.insert(0, "window_hours", int(window_hours))
    panel.insert(0, "representation_scope", representation_scope)
    panel.insert(0, "target_symbol", event.target_symbol)
    panel.insert(0, "event", event.name)
    panel = panel[HOURLY_COLUMNS]
    return panel, _summary_record(
        panel,
        event,
        anchor=anchor,
        window_hours=window_hours,
        event_shift_hours=event_shift_hours,
        representation_scope=representation_scope,
        supported_pairs=len(pairs),
        baseline_lag_weeks=selected_lags,
        comparator_exclusions=comparator_exclusions,
        pair_population=pair_population,
    )


def pairs_with_minimum_pre_support(
    panel: pd.DataFrame,
    *,
    minimum_target_routes: int,
    minimum_comparison_routes: int,
) -> tuple[tuple[str, str], ...]:
    """Return focal pairs meeting declared pooled pre-window count floors."""

    if minimum_target_routes < 1 or minimum_comparison_routes < 1:
        raise ValueError("minimum pre-support route counts must be positive")
    if panel.empty:
        return ()
    required = {"period", "src", "tgt", "target_routes", "comparison_routes"}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"pre-support panel is missing columns: {', '.join(missing)}")
    pre = panel[panel["period"].eq("pre")]
    counts = pre.groupby(["src", "tgt"], as_index=False).agg(
        target_routes=("target_routes", "sum"),
        comparison_routes=("comparison_routes", "sum"),
    )
    selected = counts[
        counts["target_routes"].ge(minimum_target_routes)
        & counts["comparison_routes"].ge(minimum_comparison_routes)
    ]
    return tuple(selected[["src", "tgt"]].itertuples(index=False, name=None))


def largest_pre_activity_pair(panel: pd.DataFrame) -> tuple[str, str] | None:
    """Return the focal pair with the largest pooled pre-window route count."""

    if panel.empty:
        return None
    required = {"period", "src", "tgt", "all_routes"}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"pre-activity panel is missing columns: {', '.join(missing)}")
    pre = panel[panel["period"].eq("pre")]
    counts = pre.groupby(["src", "tgt"], as_index=False).agg(
        all_routes=("all_routes", "sum")
    )
    if counts.empty:
        return None
    top = counts.sort_values(
        ["all_routes", "src", "tgt"],
        ascending=[False, True, True],
        kind="stable",
    ).iloc[0]
    return str(top["src"]), str(top["tgt"])


def _summary_record(
    panel: pd.DataFrame,
    event: EventSpec,
    *,
    anchor: pd.Timestamp,
    window_hours: int,
    event_shift_hours: int,
    representation_scope: str,
    supported_pairs: int,
    baseline_lag_weeks: tuple[int, ...],
    comparator_exclusions: frozenset[str],
    pair_population: str,
) -> dict[str, object]:
    values: dict[str, dict[str, float | int | None]] = {}
    for period in ("pre", "post"):
        part = panel[panel["period"].eq(period)] if not panel.empty else panel
        target = int(part["target_routes"].sum()) if not part.empty else 0
        comparison = int(part["comparison_routes"].sum()) if not part.empty else 0
        total = target + comparison
        baseline_windows = len(baseline_lag_weeks) if period == "pre" and baseline_lag_weeks else 1
        values[period] = {
            "target_routes": target,
            "comparison_routes": comparison,
            "all_routes": total,
            "target_share": target / total if total else None,
            "target_routes_per_pair_hour": (
                target / (supported_pairs * window_hours * baseline_windows)
                if supported_pairs and window_hours
                else None
            ),
            "active_pair_hours": int(part["all_routes"].gt(0).sum()) if not part.empty else 0,
        }
    pre_share = values["pre"]["target_share"]
    post_share = values["post"]["target_share"]
    pre_rate = values["pre"]["target_routes_per_pair_hour"]
    post_rate = values["post"]["target_routes_per_pair_hour"]
    if panel.empty:
        continuing_equal_pre = continuing_equal_post = None
        shapley_continuing = shapley_no_post = shapley_activity = shapley_residual = None
        carry_shapley_share = carry_shapley_activity = carry_shapley_residual = None
        share_first_continuing = share_first_no_post = share_first_activity = None
        weight_first_activity = weight_first_total_share = None
        no_post_pairs = post_route_pairs = no_post_target_pairs = 0
        pre_target_supported_pairs = pre_comparator_supported_pairs = 0
        pre_joint_supported_pairs = 0
        pre_comparator_zero_pairs_after_exclusion = 0
        pre_top1_all_share = pre_top5_all_share = None
        post_top1_all_share = post_top5_all_share = None
        pre_top1_target_share = pre_top5_target_share = None
        post_top1_target_share = post_top5_target_share = None
        post_top_pair_src = post_top_pair_tgt = None
        post_top_pair_all_routes = post_top_pair_target_routes = 0
    else:
        pair_period = panel.groupby(["src", "tgt", "period"], as_index=False).agg(
            target_routes=("target_routes", "sum"),
            all_routes=("all_routes", "sum"),
        )
        pre_pairs = pair_period[pair_period["period"].eq("pre")][
            ["src", "tgt", "target_routes", "all_routes"]
        ].rename(
            columns={"target_routes": "target_pre", "all_routes": "all_pre"}
        )
        post_pairs = pair_period[pair_period["period"].eq("post")][
            ["src", "tgt", "target_routes", "all_routes"]
        ].rename(
            columns={"target_routes": "target_post", "all_routes": "all_post"}
        )
        pair = pre_pairs.merge(
            post_pairs,
            on=["src", "tgt"],
            how="outer",
            validate="one_to_one",
        ).fillna(0)
        pair["share_pre"] = pair["target_pre"].div(
            pair["all_pre"].where(pair["all_pre"].gt(0))
        ).fillna(0.0)
        # A pre-supported pair with no post-event route activity remains in the
        # fixed population.  Zero is the explicit route-use outcome; the
        # decomposition separately reports that the whole pair became inactive.
        pair["share_post_active"] = pair["target_post"].div(
            pair["all_post"].where(pair["all_post"].gt(0))
        )
        pair["share_post_zero"] = pair["share_post_active"].fillna(0.0)
        pair["pre_weight"] = (
            pair["all_pre"] / pair["all_pre"].sum()
            if pair["all_pre"].sum() > 0
            else 0.0
        )
        pair["post_weight"] = (
            pair["all_post"] / pair["all_post"].sum()
            if pair["all_post"].sum() > 0
            else 0.0
        )
        active = pair["all_post"].gt(0)
        post_route_pairs = int(active.sum())
        no_post_pairs = int((~active).sum())
        pre_target_supported_pairs = int(pair["target_pre"].gt(0).sum())
        pre_comparator_supported_pairs = int(
            (pair["all_pre"] - pair["target_pre"]).gt(0).sum()
        )
        pre_joint_supported_pairs = int(
            (
                pair["target_pre"].gt(0)
                & (pair["all_pre"] - pair["target_pre"]).gt(0)
            ).sum()
        )
        continuing_equal_pre = (
            float(pair.loc[active, "share_pre"].mean()) if active.any() else None
        )
        continuing_equal_post = (
            float(pair.loc[active, "share_post_active"].mean()) if active.any() else None
        )

        # First retain both sequential decompositions.  They are exact but
        # order-dependent, so neither is the reported attribution.
        pair["share_post_for_intensive"] = pair["share_post_active"].where(
            active, pair["share_pre"]
        )
        pair["share_post_with_no_routes"] = pair["share_post_zero"]
        pre_weight_intensive = float(
            (pair["pre_weight"] * pair["share_post_for_intensive"]).sum()
        )
        pre_weight_after_no_routes = float(
            (pair["pre_weight"] * pair["share_post_with_no_routes"]).sum()
        )
        share_first_continuing = (
            pre_weight_intensive - float(pre_share) if pre_share is not None else None
        )
        share_first_no_post = pre_weight_after_no_routes - pre_weight_intensive
        share_first_activity = (
            float(post_share) - pre_weight_after_no_routes if post_share is not None else None
        )

        weight_first_activity = float(
            ((pair["post_weight"] - pair["pre_weight"]) * pair["share_pre"]).sum()
        )
        weight_first_total_share = float(
            (pair["post_weight"] * (pair["share_post_zero"] - pair["share_pre"])).sum()
        )

        # The primary accounting is the Shapley average of the share-first and
        # activity-weight-first paths.  It is invariant to the ordering of the
        # two factors.  The share change is split additively into changes on
        # continuing pairs and the contribution from pre-supported pairs with
        # no routes in the post window.
        pair["continuing_share_delta"] = np.where(
            active,
            pair["share_post_zero"] - pair["share_pre"],
            0.0,
        )
        pair["no_post_route_delta"] = np.where(active, 0.0, -pair["share_pre"])
        pair["average_weight"] = 0.5 * (pair["pre_weight"] + pair["post_weight"])
        shapley_continuing = float(
            (pair["average_weight"] * pair["continuing_share_delta"]).sum()
        )
        shapley_no_post = float(
            (pair["average_weight"] * pair["no_post_route_delta"]).sum()
        )
        shapley_activity = float(
            (
                0.5
                * (pair["post_weight"] - pair["pre_weight"])
                * (pair["share_pre"] + pair["share_post_zero"])
            ).sum()
        )
        shapley_residual = (
            float(post_share)
            - float(pre_share)
            - shapley_continuing
            - shapley_no_post
            - shapley_activity
            if post_share is not None
            and pre_share is not None
            else None
        )

        # Sensitivity: an inactive pair retains its pre-window target share.
        # Its post weight is still zero, so this changes the attribution between
        # share and activity components, not the exact aggregate share change.
        pair["share_post_carry_forward"] = pair["share_post_active"].where(
            active, pair["share_pre"]
        )
        carry_shapley_share = float(
            (
                pair["average_weight"]
                * (pair["share_post_carry_forward"] - pair["share_pre"])
            ).sum()
        )
        carry_shapley_activity = float(
            (
                0.5
                * (pair["post_weight"] - pair["pre_weight"])
                * (pair["share_pre"] + pair["share_post_carry_forward"])
            ).sum()
        )
        carry_shapley_residual = (
            float(post_share)
            - float(pre_share)
            - carry_shapley_share
            - carry_shapley_activity
            if post_share is not None and pre_share is not None
            else None
        )
        no_post_target_pairs = int(
            (pair["target_pre"].gt(0) & pair["target_post"].eq(0)).sum()
        )
        pre_comparator_zero_pairs_after_exclusion = int(
            (pair["all_pre"] - pair["target_pre"]).eq(0).sum()
        )

        def top_share(column: str, count: int) -> float | None:
            total = float(pair[column].sum())
            return float(pair[column].nlargest(count).sum() / total) if total > 0 else None

        pre_top1_all_share = top_share("all_pre", 1)
        pre_top5_all_share = top_share("all_pre", 5)
        post_top1_all_share = top_share("all_post", 1)
        post_top5_all_share = top_share("all_post", 5)
        pre_top1_target_share = top_share("target_pre", 1)
        pre_top5_target_share = top_share("target_pre", 5)
        post_top1_target_share = top_share("target_post", 1)
        post_top5_target_share = top_share("target_post", 5)
        post_top = pair.sort_values(
            ["all_post", "target_post", "src", "tgt"],
            ascending=[False, False, True, True],
            kind="stable",
        ).iloc[0]
        post_top_pair_src = str(post_top["src"])
        post_top_pair_tgt = str(post_top["tgt"])
        post_top_pair_all_routes = int(post_top["all_post"])
        post_top_pair_target_routes = int(post_top["target_post"])
    immediate_pre_end = (
        event.containing_hour + pd.Timedelta(hours=event_shift_hours)
        if event.exclude_anchor_hour
        else anchor
    )
    pre_windows = (
        tuple(
            (
                anchor - pd.Timedelta(weeks=lag),
                anchor - pd.Timedelta(weeks=lag) + pd.Timedelta(hours=window_hours),
            )
            for lag in baseline_lag_weeks
        )
        if baseline_lag_weeks
        else (
            (
                immediate_pre_end - pd.Timedelta(hours=window_hours),
                immediate_pre_end,
            ),
        )
    )
    post_window = (anchor, anchor + pd.Timedelta(hours=window_hours))
    pre_overlap_names = sorted(
        name
        for name, timestamp in REGISTERED_MAJOR_EVENTS.items()
        if any(start <= timestamp < end for start, end in pre_windows)
    )
    post_overlap_names = sorted(
        name
        for name, timestamp in REGISTERED_MAJOR_EVENTS.items()
        if post_window[0] <= timestamp < post_window[1]
    )
    overlap_names = sorted(set(pre_overlap_names) | set(post_overlap_names))
    source_id, source_url = EVENT_SOURCES.get(event.name, (event.anchor_citation, ""))
    return {
        "record_type": "event_contrast",
        "status": STATUS,
        "claim_gate": CLAIM_GATE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "event": event.name,
        "target_symbol": event.target_symbol,
        "source_event_time_utc": event.event_time.isoformat(),
        "anchor_definition": event.anchor_definition,
        "anchor_citation": event.anchor_citation,
        "event_source_id": source_id,
        "event_source_url": source_url,
        "timestamp_precision": event.timestamp_precision,
        "analysis_anchor_hour_utc": anchor.isoformat(),
        "containing_anchor_hour_excluded": bool(
            event.analysis_hour > event.containing_hour
        ),
        "excluded_partial_hour_start_utc": (
            (
                event.containing_hour
                + pd.Timedelta(hours=event_shift_hours)
            ).isoformat()
            if event.analysis_hour > event.containing_hour
            else None
        ),
        "excluded_containing_hour_start_utc": (
            (
                event.containing_hour
                + pd.Timedelta(hours=event_shift_hours)
            ).isoformat()
            if event.analysis_hour > event.containing_hour
            else None
        ),
        "post_window_end_utc": (anchor + pd.Timedelta(hours=window_hours)).isoformat(),
        "baseline": (
            "pooled same UTC hours at week lags "
            + ",".join(str(lag) for lag in baseline_lag_weeks)
            if baseline_lag_weeks
            else (
                "UTC hours immediately preceding the excluded containing hour"
                if event.exclude_anchor_hour
                else "immediately preceding UTC hours"
            )
        ),
        "baseline_lag_weeks": "|".join(str(lag) for lag in baseline_lag_weeks),
        "baseline_windows": len(baseline_lag_weeks) if baseline_lag_weeks else 1,
        "registered_major_event_overlap": "|".join(overlap_names),
        "registered_intervention_pre_window_overlap": "|".join(
            pre_overlap_names
        ),
        "registered_intervention_post_window_overlap": "|".join(
            post_overlap_names
        ),
        "baseline_start_utc": min(start for start, _end in pre_windows).isoformat(),
        "window_hours": int(window_hours),
        "event_shift_hours": int(event_shift_hours),
        "representation_scope": representation_scope,
        "comparator": "all non-target intermediaries",
        "comparator_exclusions": "|".join(sorted(comparator_exclusions)),
        "pair_population": pair_population,
        "supported_ordered_pairs": int(supported_pairs),
        "pre_target_supported_ordered_pairs": pre_target_supported_pairs,
        "pre_comparator_supported_ordered_pairs": pre_comparator_supported_pairs,
        "pre_joint_supported_ordered_pairs": pre_joint_supported_pairs,
        "pre_target_routes": values["pre"]["target_routes"],
        "post_target_routes": values["post"]["target_routes"],
        "target_route_count_change_vs_mean_baseline": (
            float(values["post"]["target_routes"])
            - float(values["pre"]["target_routes"])
            / (len(baseline_lag_weeks) if baseline_lag_weeks else 1)
        ),
        "pre_all_routes": values["pre"]["all_routes"],
        "post_all_routes": values["post"]["all_routes"],
        "pre_pooled_route_share": pre_share,
        "post_pooled_route_share": post_share,
        "pooled_route_share_change_pp": (
            100 * (float(post_share) - float(pre_share))
            if pre_share is not None and post_share is not None
            else None
        ),
        "ordered_pairs_with_post_window_routes": post_route_pairs,
        "continuing_pair_pre_equal_mean_share": continuing_equal_pre,
        "continuing_pair_post_equal_mean_share": continuing_equal_post,
        "continuing_pair_equal_mean_share_change_pp": (
            100 * (float(continuing_equal_post) - float(continuing_equal_pre))
            if continuing_equal_pre is not None and continuing_equal_post is not None
            else None
        ),
        "decomposition_attribution": (
            "zero-post-share Shapley is primary; carry-forward-pre-share Shapley "
            "is a convention-dependent sensitivity; each has an exact residual"
        ),
        "shapley_continuing_pair_share_change_pp": (
            100 * float(shapley_continuing)
            if shapley_continuing is not None else None
        ),
        "shapley_no_post_route_activity_pp": (
            100 * float(shapley_no_post) if shapley_no_post is not None else None
        ),
        "shapley_pair_activity_weight_change_pp": (
            100 * float(shapley_activity) if shapley_activity is not None else None
        ),
        "shapley_decomposition_residual_pp": (
            100 * float(shapley_residual) if shapley_residual is not None else None
        ),
        "inactive_pair_primary_convention": "zero_post_share",
        "inactive_pair_sensitivity_convention": "carry_forward_pre_share",
        "inactive_pair_accounting_is_convention_dependent": bool(no_post_pairs),
        "carry_forward_shapley_pair_share_change_pp": (
            100 * float(carry_shapley_share)
            if carry_shapley_share is not None
            else None
        ),
        "carry_forward_shapley_pair_activity_weight_change_pp": (
            100 * float(carry_shapley_activity)
            if carry_shapley_activity is not None
            else None
        ),
        "carry_forward_shapley_decomposition_residual_pp": (
            100 * float(carry_shapley_residual)
            if carry_shapley_residual is not None
            else None
        ),
        "share_first_continuing_pair_share_change_pp": (
            100 * float(share_first_continuing)
            if share_first_continuing is not None else None
        ),
        "share_first_no_post_route_activity_pp": (
            100 * float(share_first_no_post)
            if share_first_no_post is not None else None
        ),
        "share_first_pair_activity_weight_change_pp": (
            100 * float(share_first_activity)
            if share_first_activity is not None else None
        ),
        "weight_first_pair_activity_weight_change_pp": (
            100 * float(weight_first_activity)
            if weight_first_activity is not None else None
        ),
        "weight_first_total_pair_share_change_pp": (
            100 * float(weight_first_total_share)
            if weight_first_total_share is not None else None
        ),
        "ordered_pairs_with_no_post_window_routes": no_post_pairs,
        "ordered_pairs_with_no_post_target_routes": no_post_target_pairs,
        "pre_comparator_zero_pairs_after_exclusion": pre_comparator_zero_pairs_after_exclusion,
        "pre_top1_pair_all_route_share": pre_top1_all_share,
        "pre_top5_pair_all_route_share": pre_top5_all_share,
        "post_top1_pair_all_route_share": post_top1_all_share,
        "post_top5_pair_all_route_share": post_top5_all_share,
        "pre_top1_pair_target_route_share": pre_top1_target_share,
        "pre_top5_pair_target_route_share": pre_top5_target_share,
        "post_top1_pair_target_route_share": post_top1_target_share,
        "post_top5_pair_target_route_share": post_top5_target_share,
        "post_top_pair_src": post_top_pair_src,
        "post_top_pair_tgt": post_top_pair_tgt,
        "post_top_pair_all_routes": post_top_pair_all_routes,
        "post_top_pair_target_routes": post_top_pair_target_routes,
        "pre_target_routes_per_pair_hour": pre_rate,
        "post_target_routes_per_pair_hour": post_rate,
        "target_routes_per_pair_hour_change": (
            float(post_rate) - float(pre_rate)
            if pre_rate is not None and post_rate is not None
            else None
        ),
        "pre_active_pair_hours": values["pre"]["active_pair_hours"],
        "post_active_pair_hours": values["post"]["active_pair_hours"],
        "pre_ust_shuttle_routes": (
            int(panel.loc[panel["period"].eq("pre"), "ust_shuttle_routes"].sum())
            if not panel.empty else 0
        ),
        "post_ust_shuttle_routes": (
            int(panel.loc[panel["period"].eq("post"), "ust_shuttle_routes"].sum())
            if not panel.empty else 0
        ),
        "pre_ust_wormhole_routes": (
            int(panel.loc[panel["period"].eq("pre"), "ust_wormhole_routes"].sum())
            if not panel.empty else 0
        ),
        "post_ust_wormhole_routes": (
            int(panel.loc[panel["period"].eq("post"), "ust_wormhole_routes"].sum())
            if not panel.empty else 0
        ),
        "pre_ust_mixed_wrapper_routes": (
            int(panel.loc[panel["period"].eq("pre"), "ust_mixed_wrapper_routes"].sum())
            if not panel.empty else 0
        ),
        "post_ust_mixed_wrapper_routes": (
            int(panel.loc[panel["period"].eq("post"), "ust_mixed_wrapper_routes"].sum())
            if not panel.empty else 0
        ),
        "interpretation": (
            "descriptive change on ordered trading pairs with pre-event target and "
            "comparison-route support; Shapley accounting separates continuing-pair "
            "share changes, no post-window route activity, and pair-activity weights"
        ),
        "inference": "none; single-event descriptive anatomy",
        "causal_claim_eligible": False,
    }


def timing_assignments(
    event: EventSpec,
    *,
    window_hours: int | None = None,
) -> tuple[TimingAssignment, ...]:
    """Return prespecified, mutually disjoint timing-comparison windows.

    The pre-event assignments diagnose ordinary timing variation.  The
    post-event assignments are recovery comparisons.  None supplies a
    randomization distribution.
    """

    width = event.primary_window_hours if window_hours is None else window_hours
    anchor = event.analysis_hour
    assignments = tuple(
        TimingAssignment(
            label=(
                f"pre_event_week_{pre:+d}_to_{post:+d}"
                if post < 0
                else f"post_event_recovery_week_{pre:+d}_to_{post:+d}"
            ),
            pre_start=anchor + pd.Timedelta(weeks=pre),
            post_start=anchor + pd.Timedelta(weeks=post),
            window_hours=width,
        )
        for pre, post in ((-8, -7), (-6, -5), (1, 2), (3, 4))
    )
    validate_timing_assignments(event, assignments, focal_window_hours=width)
    return assignments


def disjoint_timing_diagnostics(
    hourly_routes: pd.DataFrame,
    event: EventSpec,
    observed: dict[str, object],
    fixed_pairs: tuple[tuple[str, str], ...],
    *,
    window_hours: int | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Report raw fixed-population timing comparisons without inference."""

    selected_window = event.primary_window_hours if window_hours is None else window_hours
    records: list[dict[str, object]] = []
    assignments = timing_assignments(event, window_hours=selected_window)
    for assignment in assignments:
        shifted = replace(
            event,
            event_time=assignment.post_start,
            baseline_lag_weeks=(1,),
            anchor_definition="disjoint adjacent-week timing assignment",
            anchor_citation="",
            timestamp_precision="hour",
            exclude_anchor_hour=False,
        )
        _panel, summary = event_hourly_panel(
            hourly_routes,
            shifted,
            window_hours=selected_window,
            baseline_lag_weeks=(1,),
            fixed_pairs=fixed_pairs,
        )
        records.append(
            {
                "record_type": "disjoint_timing_comparison",
                "status": STATUS,
                "claim_gate": CLAIM_GATE,
                "promotion_eligible": PROMOTION_ELIGIBLE,
                "event": event.name,
                "target_symbol": event.target_symbol,
                "assignment": assignment.label,
                "comparison_phase": (
                    "pre_event"
                    if assignment.post_start < event.analysis_hour
                    else "post_event_recovery"
                ),
                "comparison_pre_start_utc": assignment.pre_start.isoformat(),
                "comparison_post_start_utc": assignment.post_start.isoformat(),
                "window_hours": int(selected_window),
                "supported_ordered_pairs": summary["supported_ordered_pairs"],
                "ordered_pairs_with_post_window_routes": summary[
                    "ordered_pairs_with_post_window_routes"
                ],
                "pooled_route_share_change_pp": summary["pooled_route_share_change_pp"],
                "continuing_pair_equal_mean_share_change_pp": summary[
                    "continuing_pair_equal_mean_share_change_pp"
                ],
                "shapley_continuing_pair_share_change_pp": summary[
                    "shapley_continuing_pair_share_change_pp"
                ],
                "shapley_no_post_route_activity_pp": summary[
                    "shapley_no_post_route_activity_pp"
                ],
                "shapley_pair_activity_weight_change_pp": summary[
                    "shapley_pair_activity_weight_change_pp"
                ],
                "registered_major_event_overlap": summary[
                    "registered_major_event_overlap"
                ],
                "registered_intervention_pre_window_overlap": summary[
                    "registered_intervention_pre_window_overlap"
                ],
                "registered_intervention_post_window_overlap": summary[
                    "registered_intervention_post_window_overlap"
                ],
                "inference": "none; raw disjoint timing comparison",
            }
        )
    diagnostic = {
        "record_type": "disjoint_timing_diagnostic",
        "status": STATUS,
        "claim_gate": CLAIM_GATE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "event": event.name,
        "target_symbol": event.target_symbol,
        "matching": "same UTC hour of week; adjacent-week pre/post within assignment",
        "pair_population": "frozen from focal event pre-support",
        "frozen_ordered_pairs": len(fixed_pairs),
        "window_hours": int(selected_window),
        "timing_comparisons": len(records),
        "pre_event_comparisons": sum(
            record["comparison_phase"] == "pre_event" for record in records
        ),
        "post_event_recovery_comparisons": sum(
            record["comparison_phase"] == "post_event_recovery" for record in records
        ),
        "focal_adjacent_pooled_route_share_change_pp": observed.get(
            "pooled_route_share_change_pp"
        ),
        "focal_adjacent_shapley_continuing_pair_share_change_pp": observed.get(
            "shapley_continuing_pair_share_change_pp"
        ),
        "focal_adjacent_shapley_no_post_route_activity_pp": observed.get(
            "shapley_no_post_route_activity_pp"
        ),
        "focal_adjacent_shapley_pair_activity_weight_change_pp": observed.get(
            "shapley_pair_activity_weight_change_pp"
        ),
        "inference": "none; four raw timing comparisons are not a reference distribution",
        "interpretation": (
            "raw timing comparisons on the fixed focal pair population; the two "
            "post-event assignments may contain adjustment or recovery; no rank, "
            "p-value, significance test, randomization distribution, or causal attribution"
        ),
    }
    return records, diagnostic


def run_event_family(
    hourly_routes: pd.DataFrame,
    event: EventSpec,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Run the main window, prespecified sensitivities, and timing comparisons."""

    panels: list[pd.DataFrame] = []
    records: list[dict[str, object]] = []
    main_panel, main = event_hourly_panel(
        hourly_routes, event, window_hours=event.primary_window_hours
    )
    focal_pairs = tuple(
        main_panel[["src", "tgt"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    panels.append(main_panel)
    records.append(main)

    minimum_support_floors = (5, 10) if event.target_address == USDC else (2,)
    for minimum_routes in minimum_support_floors:
        supported_pairs = pairs_with_minimum_pre_support(
            main_panel,
            minimum_target_routes=minimum_routes,
            minimum_comparison_routes=minimum_routes,
        )
        # A support diagnostic is informative only when it retains a nonempty,
        # strictly smaller subset of the focal population.
        if 0 < len(supported_pairs) < len(focal_pairs):
            _panel, support_summary = event_hourly_panel(
                hourly_routes,
                event,
                window_hours=event.primary_window_hours,
                fixed_pairs=supported_pairs,
            )
            support_summary["record_type"] = "minimum_pre_support_sensitivity"
            support_summary["minimum_pre_target_routes"] = minimum_routes
            support_summary["minimum_pre_comparison_routes"] = minimum_routes
            support_summary["interpretation"] = (
                "same focal windows after requiring at least "
                f"{minimum_routes} target and {minimum_routes} comparison "
                "routes in the pre-event window; descriptive support diagnostic only"
            )
            records.append(support_summary)

    if len(focal_pairs) >= 2:
        largest_pair = largest_pre_activity_pair(main_panel)
        if largest_pair is not None:
            leaveout_pairs = tuple(pair for pair in focal_pairs if pair != largest_pair)
            _panel, leaveout_summary = event_hourly_panel(
                hourly_routes,
                event,
                window_hours=event.primary_window_hours,
                fixed_pairs=leaveout_pairs,
            )
            leaveout_summary["record_type"] = "largest_pre_pair_leaveout_sensitivity"
            leaveout_summary["excluded_pair_src"] = largest_pair[0]
            leaveout_summary["excluded_pair_tgt"] = largest_pair[1]
            leaveout_summary["excluded_pair_selection"] = (
                "largest pooled pre-window all-route count on focal support"
            )
            leaveout_summary["interpretation"] = (
                "same focal windows after excluding the largest pair selected only "
                "from pre-window route activity; descriptive concentration diagnostic"
            )
            records.append(leaveout_summary)

    if event.name == "terra_ust_stress":
        for alternative in UST_ALTERNATIVE_ANCHORS:
            _panel, summary = event_hourly_panel(
                hourly_routes,
                alternative,
                window_hours=alternative.primary_window_hours,
            )
            summary["record_type"] = "event_anchor_alternative"
            summary["primary_event"] = event.name
            summary["comparison_population"] = "reselected for alternative event anchor"
            records.append(summary)

    sensitivity_windows = ((168,) if event.target_address == TERRA_UST else (72, 168))
    for hours in sensitivity_windows:
        _panel, summary = event_hourly_panel(
            hourly_routes, event, window_hours=hours, fixed_pairs=focal_pairs
        )
        summary["record_type"] = (
            "adjustment_recovery_window"
            if event.target_address == USDC and hours == 72
            else (
                "contaminated_window_sensitivity"
                if event.target_address == USDC and hours == 168
                else "window_sensitivity"
            )
        )
        if event.target_address == USDC and hours == 72:
            summary["concurrent_event_context"] = "multiple contemporaneous interventions"
            summary["interpretation"] = (
                "descriptive adjustment and recovery window spanning multiple "
                "concurrent interventions; not an acute-event estimate"
            )
        if event.target_address == USDC and hours == 168:
            summary["baseline_contamination"] = (
                "the week-lag-one baseline contains Circle's wire-clearance "
                "confirmation; the post window contains Circle's quantified-exposure "
                "statement and the Federal Reserve depositor-access announcement"
            )
            summary["interpretation"] = (
                "descriptive seven-day adjustment window spanning the registered "
                "confirmation, quantified-exposure, and depositor-access interventions; "
                "not a clean acute-event sensitivity"
            )
        records.append(summary)
    _panel, dai_leaveout = event_hourly_panel(
        hourly_routes,
        event,
        window_hours=event.primary_window_hours,
        fixed_pairs=focal_pairs,
        comparator_exclusions=frozenset({DAI}),
    )
    dai_leaveout["record_type"] = "leave_dai_out_fixed_population_sensitivity"
    if event.target_address == USDC:
        dai_context = (
            "DAI is removed because its contemporaneous price can mechanically reflect "
            "USDC reserve stress; it is not treated as an unaffected control"
        )
    else:
        dai_context = (
            "DAI is removed only to test whether a major non-UST intermediary drives "
            "the comparator; this does not classify DAI as exposed to the Terra event"
        )
    dai_leaveout["interpretation"] = (
        f"{dai_context}; fixed focal population; "
        f"{dai_leaveout['pre_comparator_zero_pairs_after_exclusion']} focal pairs "
        "have no remaining pre-window comparator routes"
    )
    records.append(dai_leaveout)
    _panel, dai_requalified = event_hourly_panel(
        hourly_routes,
        event,
        window_hours=event.primary_window_hours,
        comparator_exclusions=frozenset({DAI}),
    )
    dai_requalified["record_type"] = "leave_dai_out_requalified_support_sensitivity"
    dai_requalified["interpretation"] = (
        f"{dai_context}; pair support is requalified after removing DAI, so comparison "
        "with the fixed-population leave-out is convention-dependent"
    )
    records.append(dai_requalified)
    if event.target_address == TERRA_UST:
        _panel, matched = event_hourly_panel(
            hourly_routes,
            event,
            window_hours=24,
            baseline_lag_weeks=(1, 2, 3, 4),
            fixed_pairs=focal_pairs,
        )
        matched["record_type"] = "cross_episode_matched_24h"
        records.append(matched)
        for lag in (1, 2, 3, 4):
            _panel, weekly = event_hourly_panel(
                hourly_routes,
                event,
                window_hours=24,
                baseline_lag_weeks=(lag,),
                fixed_pairs=focal_pairs,
            )
            weekly["record_type"] = "matched_baseline_week"
            weekly["matched_week_lag"] = lag
            weekly["population_diagnostic"] = (
                "frozen focal-event pair population; actual weekly pre-comparator "
                "support reported separately"
            )
            weekly["frozen_population_ordered_pairs"] = len(focal_pairs)
            records.append(weekly)
        _panel, eight_week = event_hourly_panel(
            hourly_routes,
            event,
            window_hours=24,
            baseline_lag_weeks=tuple(range(1, 9)),
            fixed_pairs=focal_pairs,
        )
        eight_week["record_type"] = "eight_week_matched_sensitivity"
        records.append(eight_week)
    else:
        for lag in (1, 2, 3, 4):
            _panel, weekly = event_hourly_panel(
                hourly_routes,
                event,
                window_hours=24,
                baseline_lag_weeks=(lag,),
                fixed_pairs=focal_pairs,
            )
            weekly["record_type"] = "matched_baseline_week"
            weekly["matched_week_lag"] = lag
            weekly["population_diagnostic"] = (
                "frozen focal-event pair population; actual weekly pre-comparator "
                "support reported separately"
            )
            weekly["frozen_population_ordered_pairs"] = len(focal_pairs)
            records.append(weekly)
        _panel, eight_week = event_hourly_panel(
            hourly_routes,
            event,
            window_hours=24,
            baseline_lag_weeks=tuple(range(1, 9)),
            fixed_pairs=focal_pairs,
        )
        eight_week["record_type"] = "eight_week_matched_sensitivity"
        records.append(eight_week)
        _panel, adjacent = event_hourly_panel(
            hourly_routes,
            event,
            window_hours=24,
            baseline_lag_weeks=(),
            fixed_pairs=focal_pairs,
        )
        adjacent["record_type"] = "adjacent_pre_contaminated_descriptive"
        adjacent["interpretation"] = (
            "adjacent pre-event comparison retained as visibly contaminated; "
            "not the primary acute-window baseline"
        )
        records.append(adjacent)
    if event.target_address == TERRA_UST:
        for shift in (-24, 24):
            _panel, summary = event_hourly_panel(
                hourly_routes,
                event,
                window_hours=event.primary_window_hours,
                event_shift_hours=shift,
                fixed_pairs=focal_pairs,
            )
            summary["record_type"] = "event_time_sensitivity"
            records.append(summary)
    else:
        for (
            marker_name,
            marker_time,
            marker_definition,
            source_id,
            source_url,
        ) in USDC_EVENT_MARKERS:
            marker = replace(
                event,
                event_time=marker_time,
                anchor_definition=marker_definition,
                anchor_citation=source_id,
            )
            _panel, summary = event_hourly_panel(
                hourly_routes,
                marker,
                window_hours=event.primary_window_hours,
                fixed_pairs=focal_pairs,
            )
            summary["record_type"] = "event_marker_sensitivity"
            summary["event_marker"] = marker_name
            summary["event_source_id"] = source_id
            summary["event_source_url"] = source_url
            records.append(summary)
    if event.target_address == TERRA_UST:
        for scope in ("single_wrapper_only", "shuttle_only", "wormhole_only"):
            _panel, summary = event_hourly_panel(
                hourly_routes, event, representation_scope=scope, fixed_pairs=focal_pairs
            )
            summary["record_type"] = "wrapper_robustness"
            records.append(summary)
    timing_observed = main
    if event.target_address == USDC:
        _timing_panel, timing_observed = event_hourly_panel(
            hourly_routes,
            event,
            window_hours=event.primary_window_hours,
            baseline_lag_weeks=(),
            fixed_pairs=focal_pairs,
        )
    assignments, timing_diagnostic = disjoint_timing_diagnostics(
        hourly_routes, event, timing_observed, focal_pairs
    )
    records.extend(assignments)
    records.append(timing_diagnostic)
    if event.target_address == TERRA_UST:
        wrapper_records = {
            str(record.get("representation_scope")): record
            for record in records
            if record.get("record_type") == "wrapper_robustness"
        }
        shift_records = {
            int(record["event_shift_hours"]): record
            for record in records
            if record.get("record_type") == "event_time_sensitivity"
        }
        minimum_records = [
            record
            for record in records
            if record.get("record_type") == "minimum_pre_support_sensitivity"
        ]
        largest_record = next(
            (
                record
                for record in records
                if record.get("record_type")
                == "largest_pre_pair_leaveout_sensitivity"
            ),
            None,
        )
        records.append(
            {
                "record_type": "appendix_anomaly_summary",
                "status": STATUS,
                "claim_gate": CLAIM_GATE,
                "promotion_eligible": PROMOTION_ELIGIBLE,
                "event": event.name,
                "target_symbol": event.target_symbol,
                "diagnostic_class": "appendix_anomaly",
                "supported_ordered_pairs": main["supported_ordered_pairs"],
                "pre_target_routes": main["pre_target_routes"],
                "post_target_routes": main["post_target_routes"],
                "pre_all_routes": main["pre_all_routes"],
                "post_all_routes": main["post_all_routes"],
                "pre_ust_shuttle_routes": main["pre_ust_shuttle_routes"],
                "post_ust_shuttle_routes": main["post_ust_shuttle_routes"],
                "pre_ust_wormhole_routes": main["pre_ust_wormhole_routes"],
                "post_ust_wormhole_routes": main["post_ust_wormhole_routes"],
                "shuttle_only_route_share_change_pp": wrapper_records.get(
                    "shuttle_only", {}
                ).get("pooled_route_share_change_pp"),
                "wormhole_only_route_share_change_pp": wrapper_records.get(
                    "wormhole_only", {}
                ).get("pooled_route_share_change_pp"),
                "minus_24h_route_share_change_pp": shift_records.get(-24, {}).get(
                    "pooled_route_share_change_pp"
                ),
                "plus_24h_route_share_change_pp": shift_records.get(24, {}).get(
                    "pooled_route_share_change_pp"
                ),
                "minimum_support_diagnostics_run": len(minimum_records),
                "largest_pair_leaveout_run": largest_record is not None,
                "largest_pair_leaveout_route_share_change_pp": (
                    largest_record.get("pooled_route_share_change_pp")
                    if largest_record is not None
                    else None
                ),
                "interpretation": (
                    "appendix anomaly with exact route-count support; wrapper, timing, "
                    "minimum-support, and largest-pair diagnostics describe fragility "
                    "without supplying inference"
                ),
                "inference": "none; two-pair appendix anomaly",
                "causal_claim_eligible": False,
            }
        )
    for record in records:
        record["scientific_role"] = (
            "appendix_only_diagnostic"
            if event.target_address == TERRA_UST
            else "primary_e0_diagnostic"
        )
        if event.target_address == TERRA_UST:
            record["diagnostic_class"] = "appendix_anomaly"
    panel = pd.concat(panels, ignore_index=True) if panels else pd.DataFrame(columns=HOURLY_COLUMNS)
    return panel, records


def required_days(
    events: Iterable[EventSpec] = EVENTS,
    *,
    timing_radius_weeks: int = 4,
) -> tuple[str, ...]:
    """Calendar perimeter sufficient for all windows and timing comparisons."""

    days: set[str] = set()
    for event in events:
        maximum_baseline_weeks = 8
        timing_baseline_weeks = max(event.baseline_lag_weeks, default=0)
        lookback_weeks = max(
            maximum_baseline_weeks,
            timing_radius_weeks + timing_baseline_weeks,
        )
        start = event.analysis_hour - pd.Timedelta(weeks=lookback_weeks)
        end = event.analysis_hour + pd.Timedelta(weeks=timing_radius_weeks) + pd.Timedelta(days=7)
        days.update(pd.date_range(start.floor("D"), end.floor("D"), freq="D").strftime("%Y%m%d"))
    return tuple(sorted(days))

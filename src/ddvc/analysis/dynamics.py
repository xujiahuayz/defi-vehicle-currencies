"""Calendar-aligned dynamic variables for panel data."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


CANONICAL_RESPONSE_HORIZONS = (1, 7, 30, 120)
DAILY_VOLATILITY_WINDOW_DAYS = 30
DAILY_VOLATILITY_MIN_RETURNS = 20
WETH_DOWNSIDE_EVENT_THRESHOLD = 0.08
WEEK_ANCHOR_EPOCH = pd.Timestamp("1970-01-05")


def anchored_day_bin_start(
    dates: pd.Series,
    *,
    width_days: int = 7,
    anchor_offset_days: int = 0,
) -> pd.Series:
    """Map dates to fixed-width UTC bins under an explicit anchor offset."""

    if width_days < 1:
        raise ValueError("day-bin width must be positive")
    if not 0 <= anchor_offset_days < width_days:
        raise ValueError("day-bin anchor offset must lie inside the bin width")
    parsed = pd.to_datetime(dates, errors="coerce").dt.normalize()
    if parsed.isna().any():
        raise ValueError("day-bin dates must be valid")
    anchor = WEEK_ANCHOR_EPOCH + pd.Timedelta(days=anchor_offset_days)
    offsets = np.floor_divide((parsed - anchor).dt.days.to_numpy(), width_days)
    return pd.Series(
        anchor + pd.to_timedelta(offsets * width_days, unit="D"),
        index=dates.index,
        name="period_start",
    )


def aggregate_complete_day_bins(
    frame: pd.DataFrame,
    *,
    value_columns: Sequence[str],
    group_columns: Sequence[str],
    date_column: str = "date",
    width_days: int = 7,
    anchor_offset_days: int = 0,
) -> pd.DataFrame:
    """Sum raw quantities inside complete fixed-width bins contained in one year."""

    required = {date_column, *value_columns, *group_columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"day-bin input lacks columns: {missing}")
    if frame.empty:
        raise ValueError("day-bin input is empty")
    data = frame[[date_column, *group_columns, *value_columns]].copy()
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce").dt.normalize()
    if data[date_column].isna().any():
        raise ValueError("day-bin input contains invalid dates")
    if data.duplicated([date_column, *group_columns]).any():
        raise ValueError("day-bin input must be unique by date and group")
    for column in value_columns:
        values = pd.to_numeric(data[column], errors="coerce")
        if values.isna().any() or (~np.isfinite(values)).any() or values.lt(0).any():
            raise ValueError(f"day-bin value {column!r} must be finite and nonnegative")
        data[column] = values
    data["period_start"] = anchored_day_bin_start(
        data[date_column],
        width_days=width_days,
        anchor_offset_days=anchor_offset_days,
    )
    calendar = data[[date_column, "period_start"]].drop_duplicates()
    coverage = calendar.groupby("period_start", as_index=False).agg(
        days_observed=(date_column, "nunique"),
        first_date=(date_column, "min"),
        last_date=(date_column, "max"),
    )
    coverage["period_end"] = coverage["period_start"] + pd.to_timedelta(
        width_days - 1, unit="D"
    )
    complete = coverage[
        coverage["days_observed"].eq(width_days)
        & coverage["first_date"].eq(coverage["period_start"])
        & coverage["last_date"].eq(coverage["period_end"])
        & coverage["period_start"].dt.year.eq(coverage["period_end"].dt.year)
    ].copy()
    if complete.empty:
        return pd.DataFrame(
            columns=[
                "period_start",
                "period_end",
                "year",
                "days_observed",
                *group_columns,
                *value_columns,
            ]
        )
    data = data.merge(
        complete[["period_start"]],
        on="period_start",
        how="inner",
        validate="many_to_one",
    )
    result = data.groupby(["period_start", *group_columns], as_index=False)[
        list(value_columns)
    ].sum()
    result = result.merge(
        complete[["period_start", "period_end", "days_observed"]],
        on="period_start",
        how="left",
        validate="many_to_one",
    )
    result.insert(2, "year", result["period_start"].dt.year)
    return result[
        [
            "period_start",
            "period_end",
            "year",
            "days_observed",
            *group_columns,
            *value_columns,
        ]
    ]


def value_at_day_offset(
    panel: pd.DataFrame,
    value_column: str,
    day_offset: int,
    *,
    entity_columns: Sequence[str] = ("token",),
    date_column: str = "date",
) -> pd.Series:
    """Return each entity's value at exactly ``date + day_offset``.

    Missing calendar dates remain missing; they are never replaced by the next
    available row.
    """

    key_columns = [*entity_columns, date_column]
    if panel.duplicated(key_columns).any():
        raise ValueError(f"Panel must be unique on {key_columns!r}.")

    dates = pd.to_datetime(panel[date_column])
    lookup_index = pd.MultiIndex.from_arrays(
        [*(panel[column] for column in entity_columns), dates],
        names=key_columns,
    )
    lookup = pd.Series(panel[value_column].to_numpy(), index=lookup_index)
    target_index = pd.MultiIndex.from_arrays(
        [
            *(panel[column] for column in entity_columns),
            dates + pd.to_timedelta(day_offset, unit="D"),
        ],
        names=key_columns,
    )
    values = lookup.reindex(target_index).to_numpy()
    return pd.Series(values, index=panel.index, name=value_column)


def exact_daily_log_return(
    panel: pd.DataFrame,
    value_column: str,
    *,
    entity_columns: Sequence[str] = (),
    date_column: str = "date",
) -> pd.Series:
    """Return log changes only where the exact prior calendar day exists."""

    current = pd.to_numeric(panel[value_column], errors="coerce")
    previous = pd.to_numeric(
        value_at_day_offset(
            panel,
            value_column,
            -1,
            entity_columns=entity_columns,
            date_column=date_column,
        ),
        errors="coerce",
    )
    valid = current.gt(0) & previous.gt(0)
    return np.log(current / previous).where(valid).rename(value_column)


def daily_price_risk_features(
    panel: pd.DataFrame,
    value_column: str,
    *,
    entity_columns: Sequence[str] = (),
    date_column: str = "date",
) -> pd.DataFrame:
    """Compute one canonical exact-calendar daily price-risk policy.

    Missing calendar dates remain explicit inside every entity's history. The
    trailing volatility window includes the current return. The pre-shock
    volatility denominator ends one day earlier and is therefore distinct.
    """

    required = {*entity_columns, date_column, value_column}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"Daily price-risk input lacks columns: {missing}")
    if panel.empty:
        raise ValueError("Daily price-risk input is empty")
    keys = [*entity_columns, date_column]
    source = panel[keys + [value_column]].copy()
    source[date_column] = pd.to_datetime(source[date_column], errors="coerce").dt.normalize()
    if source[date_column].isna().any() or source.duplicated(keys).any():
        raise ValueError("Daily price-risk input has invalid or duplicate entity-dates")
    raw_values = source[value_column]
    values = pd.to_numeric(raw_values, errors="coerce")
    if (raw_values.notna() & values.isna()).any() or (
        values.notna() & (~np.isfinite(values) | values.le(0))
    ).any():
        raise ValueError("Daily price-risk input contains a nonpositive or nonfinite price")
    source[value_column] = values
    source["_row_order"] = np.arange(len(source))

    dates = pd.date_range(source[date_column].min(), source[date_column].max(), freq="D")
    if entity_columns:
        entities = source[list(entity_columns)].drop_duplicates()
        calendar = entities.merge(pd.DataFrame({date_column: dates}), how="cross")
    else:
        calendar = pd.DataFrame({date_column: dates})
    history = calendar.merge(
        source[keys + [value_column]], on=keys, how="left", validate="one_to_one"
    ).sort_values(keys)
    history["log_return"] = exact_daily_log_return(
        history,
        value_column,
        entity_columns=entity_columns,
        date_column=date_column,
    )

    if entity_columns:
        returns = history.groupby(list(entity_columns), sort=False)["log_return"]
        trailing_count = returns.transform(
            lambda series: series.rolling(
                DAILY_VOLATILITY_WINDOW_DAYS, min_periods=1
            ).count()
        )
        trailing_volatility = returns.transform(
            lambda series: series.rolling(
                DAILY_VOLATILITY_WINDOW_DAYS,
                min_periods=DAILY_VOLATILITY_MIN_RETURNS,
            ).std(ddof=1)
        )
        pre_shock_count = returns.transform(
            lambda series: series.shift(1)
            .rolling(DAILY_VOLATILITY_WINDOW_DAYS, min_periods=1)
            .count()
        )
        pre_shock_volatility = returns.transform(
            lambda series: series.shift(1)
            .rolling(
                DAILY_VOLATILITY_WINDOW_DAYS,
                min_periods=DAILY_VOLATILITY_MIN_RETURNS,
            )
            .std(ddof=1)
        )
    else:
        returns = history["log_return"]
        trailing_count = returns.rolling(
            DAILY_VOLATILITY_WINDOW_DAYS, min_periods=1
        ).count()
        trailing_volatility = returns.rolling(
            DAILY_VOLATILITY_WINDOW_DAYS,
            min_periods=DAILY_VOLATILITY_MIN_RETURNS,
        ).std(ddof=1)
        pre_shock_count = returns.shift(1).rolling(
            DAILY_VOLATILITY_WINDOW_DAYS, min_periods=1
        ).count()
        pre_shock_volatility = returns.shift(1).rolling(
            DAILY_VOLATILITY_WINDOW_DAYS,
            min_periods=DAILY_VOLATILITY_MIN_RETURNS,
        ).std(ddof=1)
    history["trailing_volatility_valid_returns"] = trailing_count.astype("int64")
    history["trailing_30d_volatility"] = trailing_volatility
    history["pre_shock_volatility_valid_returns"] = pre_shock_count.astype("int64")
    history["pre_shock_30d_volatility"] = pre_shock_volatility
    history["downside_stress"] = (-history["log_return"]).clip(lower=0)
    history["stress_event_8pct"] = (
        history["downside_stress"]
        .ge(WETH_DOWNSIDE_EVENT_THRESHOLD)
        .where(history["downside_stress"].notna())
        .astype("boolean")
    )
    valid_scale = history["pre_shock_30d_volatility"].gt(0)
    history["standardized_downside_stress"] = (
        history["downside_stress"] / history["pre_shock_30d_volatility"]
    ).where(valid_scale & history["log_return"].notna())
    feature_columns = [
        "log_return",
        "trailing_volatility_valid_returns",
        "trailing_30d_volatility",
        "pre_shock_volatility_valid_returns",
        "pre_shock_30d_volatility",
        "downside_stress",
        "stress_event_8pct",
        "standardized_downside_stress",
    ]
    return (
        source[keys + ["_row_order"]]
        .merge(history[keys + feature_columns], on=keys, how="left", validate="one_to_one")
        .sort_values("_row_order")
        .drop(columns="_row_order")
        .reset_index(drop=True)
    )

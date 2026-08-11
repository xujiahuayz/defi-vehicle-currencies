"""Calendar-aligned dynamic variables for panel data."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


CANONICAL_RESPONSE_HORIZONS = (1, 7, 30, 120)
DAILY_VOLATILITY_WINDOW_DAYS = 30
DAILY_VOLATILITY_MIN_RETURNS = 20
WETH_DOWNSIDE_EVENT_THRESHOLD = 0.08


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

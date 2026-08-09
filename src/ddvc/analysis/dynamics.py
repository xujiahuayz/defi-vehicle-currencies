"""Calendar-aligned dynamic variables for panel data."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


CANONICAL_RESPONSE_HORIZONS = (1, 7, 30, 120)


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

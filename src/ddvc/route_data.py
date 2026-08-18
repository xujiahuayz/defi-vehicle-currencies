"""Direct access to reconstructed daily route files."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq

from ddvc.paths import DATA_DIR


UNIFIED_ROUTE_ROOT = DATA_DIR / "unified"


def _file_state(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


@dataclass(frozen=True)
class RouteDataset:
    """One ordered set of ordinary daily Parquet files."""

    columns: tuple[str, ...]
    days: tuple[str, ...]
    paths: tuple[Path, ...]
    states: tuple[tuple[int, int], ...]

    @property
    def input_paths(self) -> tuple[Path, ...]:
        """Compatibility for writer APIs that now ignore build metadata."""

        return ()

    def _index(self, day: str) -> int:
        selected = str(day).replace("-", "")
        try:
            return self.days.index(selected)
        except ValueError as error:
            raise KeyError(f"day is outside the route dataset: {selected}") from error

    def read_day(self, day: str) -> pd.DataFrame:
        index = self._index(day)
        path = self.paths[index]
        before = _file_state(path)
        frame = pd.read_parquet(path, columns=list(self.columns))
        if _file_state(path) != before:
            raise RuntimeError(f"route file changed while being read: {path}")
        return frame

    def select_days(self, days: Iterable[str]) -> "RouteDataset":
        indices = tuple(self._index(day) for day in days)
        if not indices or len(indices) != len(set(indices)):
            raise ValueError("route-day selection must be nonempty and unique")
        return replace(
            self,
            days=tuple(self.days[index] for index in indices),
            paths=tuple(self.paths[index] for index in indices),
            states=tuple(self.states[index] for index in indices),
        )

    def assert_current(self) -> None:
        changed = [
            path
            for path, expected in zip(self.paths, self.states, strict=True)
            if not path.is_file() or _file_state(path) != expected
        ]
        if changed:
            raise RuntimeError(f"route file changed during processing: {changed[0]}")


def route_dataset(
    columns: Iterable[str],
    *,
    nonempty: bool = True,
    root: Path = UNIFIED_ROUTE_ROOT,
) -> RouteDataset:
    """Resolve the canonical `YYYYMMDD.parquet` route files directly."""

    selected_columns = tuple(dict.fromkeys(str(column) for column in columns))
    if not selected_columns:
        raise ValueError("route dataset requires at least one column")
    paths = tuple(
        sorted(
            path
            for path in root.glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].parquet")
            if path.is_file()
        )
    )
    if not paths:
        raise FileNotFoundError(f"no reconstructed route files under {root}")
    days = tuple(path.stem for path in paths)
    for path in paths:
        schema = pq.read_schema(path)
        missing = set(selected_columns) - set(schema.names)
        if missing:
            raise ValueError(f"route file {path.name} lacks columns: {sorted(missing)}")
        if nonempty and pq.ParquetFile(path).metadata.num_rows == 0:
            raise ValueError(f"route file is empty: {path}")
    return RouteDataset(
        columns=selected_columns,
        days=days,
        paths=paths,
        states=tuple(_file_state(path) for path in paths),
    )


def route_preinstall_validator(dataset: RouteDataset):
    """Return a small direct-input stability check for final output install."""

    def validate(_path: Path) -> None:
        dataset.assert_current()

    return validate

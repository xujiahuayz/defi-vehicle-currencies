"""Direct paths for processed constant-product deposited-capital data."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pyarrow.parquet as pq

from ddvc.paths import DATA_DIR
from ddvc.workflow import current_inputs


PROCESSED = DATA_DIR / "processed"
POOL_CAPITAL_DAILY = PROCESSED / "pool_capital_daily.parquet"
POOL_CANDIDATE_CAPITAL_DAILY = PROCESSED / "pool_candidate_capital_daily.parquet"
POOL_CAPITAL_REJECTIONS = PROCESSED / "pool_capital_rejections.parquet"
POOL_CAPITAL_COVERAGE = PROCESSED / "pool_capital_coverage.jsonl"

CAPITAL_DATA_PATHS = (
    POOL_CAPITAL_DAILY,
    POOL_CANDIDATE_CAPITAL_DAILY,
    POOL_CAPITAL_REJECTIONS,
    POOL_CAPITAL_COVERAGE,
)


def validate_capital_data(paths: tuple[Path, ...] = CAPITAL_DATA_PATHS) -> None:
    """Require the four direct outputs and readable Parquet payloads."""

    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "missing processed capital data: " + ", ".join(str(path) for path in missing)
        )
    for path in paths[:3]:
        pq.ParquetFile(path)


@contextmanager
def current_capital_data(
    paths: tuple[Path, ...] = CAPITAL_DATA_PATHS,
    *,
    consumer: str,
):
    """Keep direct capital inputs stable for one downstream read."""

    with current_inputs(paths, consumer=consumer) as selected:
        validate_capital_data(tuple(selected))
        yield selected

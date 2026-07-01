from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ddvc.fetch.raw import raw_path, where_for_entity
from ddvc.fetch.schemas import EntitySpec, get_schema
from ddvc.fetch.sources import get_source, iter_days, last_complete_month_exclusive


class FetchPlanningTests(unittest.TestCase):
    def test_last_complete_month_exclusive(self) -> None:
        self.assertEqual(last_complete_month_exclusive(dt.date(2026, 7, 1)), dt.date(2026, 7, 1))
        self.assertEqual(last_complete_month_exclusive(dt.date(2026, 7, 31)), dt.date(2026, 7, 1))

    def test_genesis_sources_cover_core_dexes(self) -> None:
        self.assertEqual(get_source("curve").genesis, dt.date(2020, 2, 11))
        self.assertEqual(get_source("uniswap_v2").genesis, dt.date(2020, 5, 11))
        self.assertEqual(get_source("uniswap_v3").genesis, dt.date(2021, 5, 5))
        self.assertEqual(get_source("uniswap_v4").genesis, dt.date(2025, 1, 24))

    def test_schema_overfetches_liquidity_streams(self) -> None:
        streams = {entity.stream for entity in get_schema("uniswap_v3").entities}
        self.assertLessEqual({"swaps", "daily", "mints", "burns"}, streams)
        streams = {entity.stream for entity in get_schema("uniswap_v4").entities}
        self.assertLessEqual({"swaps", "daily", "modify_liquidities"}, streams)

    def test_where_for_timestamp_and_date_entities(self) -> None:
        day = dt.date(2026, 6, 30)
        timestamp_entity = EntitySpec(stream="swaps", entity="swaps", fields="id")
        self.assertEqual(
            where_for_entity(timestamp_entity, day),
            {"timestamp_gte": "1782777600", "timestamp_lt": "1782864000"},
        )
        date_entity = EntitySpec(stream="daily", entity="poolDayDatas", fields="id", date_field="date")
        self.assertEqual(where_for_entity(date_entity, day), {"date": "1782777600"})

    def test_raw_path_is_partitioned_by_source_stream_and_year(self) -> None:
        path = raw_path("uniswap_v3", "swaps", dt.date(2026, 6, 30))
        self.assertTrue(
            path.as_posix().endswith(
                "data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_20260630.jsonl.gz"
            )
        )

    def test_iter_days_is_half_open(self) -> None:
        self.assertEqual(
            iter_days(dt.date(2026, 6, 29), dt.date(2026, 7, 1)),
            [dt.date(2026, 6, 29), dt.date(2026, 6, 30)],
        )

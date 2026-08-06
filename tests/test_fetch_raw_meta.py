from __future__ import annotations

import unittest

from ddvc.fetch.raw import merge_stream_metadata


class RawMetaMergeTests(unittest.TestCase):
    def test_partial_refresh_preserves_other_streams_and_recomputes_bounds(self) -> None:
        old = {
            "head_block_at_fetch": 100,
            "min_block": 10,
            "max_block": 20,
            "streams": {
                "daily": {
                    "status": "fetched",
                    "min_block": 10,
                    "max_block": 20,
                },
                "swaps": {
                    "status": "fetched",
                    "min_block": 11,
                    "max_block": 19,
                },
            },
        }
        fresh = {
            "head_block_at_fetch": 200,
            "min_block": 12,
            "max_block": 30,
            "streams": {
                "swaps": {
                    "status": "fetched",
                    "min_block": 12,
                    "max_block": 30,
                },
            },
        }
        got = merge_stream_metadata(old, fresh)
        self.assertEqual(set(got["streams"]), {"daily", "swaps"})
        self.assertEqual(got["streams"]["daily"]["max_block"], 20)
        self.assertEqual(got["streams"]["swaps"]["max_block"], 30)
        self.assertEqual(got["min_block"], 10)
        self.assertEqual(got["max_block"], 30)
        self.assertEqual(got["head_block_at_fetch"], 200)

    def test_skipped_stream_does_not_erase_prior_row_and_block_details(self) -> None:
        old = {
            "streams": {
                "swaps": {
                    "status": "fetched",
                    "rows": 17,
                    "min_block": 10,
                    "max_block": 20,
                }
            }
        }
        fresh = {
            "streams": {
                "swaps": {"status": "skipped", "path": "already-there.jsonl.gz"}
            }
        }
        got = merge_stream_metadata(old, fresh)
        self.assertEqual(got["streams"]["swaps"]["status"], "fetched")
        self.assertEqual(got["streams"]["swaps"]["rows"], 17)
        self.assertEqual(got["min_block"], 10)
        self.assertEqual(got["max_block"], 20)


if __name__ == "__main__":
    unittest.main()

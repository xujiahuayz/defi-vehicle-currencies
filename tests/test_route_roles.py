from __future__ import annotations

import unittest

import pandas as pd

from ddvc.route_roles import component_value_support


def leg(tx: str, index: int, token_in: str, token_out: str, usd: float) -> dict[str, object]:
    return {
        "tx_hash": tx,
        "component_id": 0,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": usd,
        "log_index": index,
    }


class RouteValueSupportTests(unittest.TestCase):
    def test_nested_support_checks_endpoints_and_every_intermediary(self) -> None:
        frame = pd.DataFrame(
            [
                leg("tight", 0, "a", "k", 100.0),
                leg("tight", 1, "k", "b", 90.0),
                leg("wide", 0, "a", "k", 100.0),
                leg("wide", 1, "k", "b", 60.0),
                leg("broken-mid", 0, "a", "k", 100.0),
                leg("broken-mid", 1, "k", "m", 1_000.0),
                leg("broken-mid", 2, "m", "b", 100.0),
            ]
        )
        support = component_value_support(frame).set_index("tx_hash")
        self.assertTrue(bool(support.loc["tight", "within_20pct"]))
        self.assertTrue(bool(support.loc["tight", "within_2x"]))
        self.assertFalse(bool(support.loc["wide", "within_20pct"]))
        self.assertTrue(bool(support.loc["wide", "within_2x"]))
        self.assertAlmostEqual(support.loc["broken-mid", "endpoint_value_ratio"], 1.0)
        self.assertFalse(bool(support.loc["broken-mid", "within_2x"]))

    def test_split_flow_is_summed_by_token_before_coherence_is_tested(self) -> None:
        frame = pd.DataFrame(
            [
                leg("split", 0, "a", "k", 60.0),
                leg("split", 1, "a", "k", 40.0),
                leg("split", 2, "k", "b", 95.0),
            ]
        )
        support = component_value_support(frame).iloc[0]
        self.assertEqual(support["source_usd"], 100.0)
        self.assertEqual(support["sink_usd"], 95.0)
        self.assertAlmostEqual(support["intermediate_ratio_min"], 95.0 / 100.0)
        self.assertTrue(bool(support["within_20pct"]))

    def test_zero_or_missing_intermediary_values_never_gain_support(self) -> None:
        rows = []
        for tx, unsupported in (("zero", 0.0), ("missing", float("nan"))):
            rows.extend(
                [
                    leg(tx, 0, "a", "k", unsupported),
                    leg(tx, 1, "k", "b", unsupported),
                    leg(tx, 2, "a", "m", 100.0),
                    leg(tx, 3, "m", "b", 100.0),
                ]
            )
        frame = pd.DataFrame(rows)
        support = component_value_support(frame).set_index("tx_hash")
        self.assertEqual(support.loc["zero", "endpoint_value_ratio"], 1.0)
        self.assertEqual(support.loc["missing", "endpoint_value_ratio"], 1.0)
        self.assertFalse(bool(support.loc["zero", "within_2x"]))
        self.assertFalse(bool(support.loc["missing", "within_2x"]))


if __name__ == "__main__":
    unittest.main()

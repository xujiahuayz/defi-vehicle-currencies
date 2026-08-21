from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from ddvc.analysis.route_reconstruction_validation import (
    _released_generation_index,
    compare_transaction_assignments,
    stable_share_rows,
    summarize_release_boundary,
    transaction_signatures,
)
from ddvc.reconstruct import UNIFIED_COLUMNS


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
TOKEN_A = "0x1111111111111111111111111111111111111111"
TOKEN_B = "0x2222222222222222222222222222222222222222"
TX = "0x" + "a" * 64


def two_leg_frame(intermediary: str) -> pd.DataFrame:
    rows = []
    for index, (token_in, token_out) in enumerate(
        ((TOKEN_A, intermediary), (intermediary, TOKEN_B))
    ):
        rows.append(
            {
                "tx_hash": TX,
                "log_index": index + 1,
                "source": "uniswap_v2",
                "token_in": token_in,
                "token_out": token_out,
                "token_in_sym": token_in[-4:],
                "token_out_sym": token_out[-4:],
                "amount_in": 100.0,
                "amount_out": 100.0,
                "amount_usd": 100.0,
                "component_id": 0,
                "n_components": 1,
                "route_class": "coherent",
                "ambiguous": False,
                "tin_role": "source" if index == 0 else "intermediate",
                "tout_role": "intermediate" if index == 0 else "sink",
                "timestamp_utc": 1_719_792_001,
            }
        )
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS)


class RouteReconstructionValidationTests(unittest.TestCase):
    def tearDown(self) -> None:
        _released_generation_index.cache_clear()

    def test_transaction_signature_uses_economic_assignments(self) -> None:
        signature = transaction_signatures(two_leg_frame(USDC), "2024-07-01")[TX]
        self.assertEqual(signature["endpoint_pair"], ((TOKEN_A, TOKEN_B),))
        self.assertEqual(signature["intermediary_identity"], ((USDC,),))
        self.assertEqual(signature["vehicle_class"], (("stable",),))
        self.assertEqual(signature["leg_count"], (2,))
        self.assertEqual(len(signature["exact_two_leg_inclusion"]), 1)

    def test_assignment_comparison_separates_endpoints_from_vehicle(self) -> None:
        rows = compare_transaction_assignments(
            two_leg_frame(USDC),
            two_leg_frame(WETH),
            day="2024-07-01",
            affected_transactions={TX},
        )
        result = {row["dimension"]: row for row in rows}
        self.assertEqual(result["endpoint_pair"]["changed_transactions"], 0)
        self.assertEqual(result["leg_count"]["changed_transactions"], 0)
        self.assertEqual(result["intermediary_identity"]["changed_transactions"], 1)
        self.assertEqual(result["vehicle_class"]["changed_transactions"], 1)
        self.assertEqual(result["exact_two_leg_inclusion"]["changed_transactions"], 1)

    def test_stable_share_rows_reconcile_mass_and_percentage_points(self) -> None:
        rows = stable_share_rows(
            [
                {
                    "route_count_total": 100.0,
                    "route_count_stable": 40.0,
                    "within_20pct_value_usd_total": 200.0,
                    "within_20pct_value_usd_stable": 100.0,
                }
            ],
            [
                {
                    "route_count_total": 100.0,
                    "route_count_stable": 41.0,
                    "within_20pct_value_usd_total": 200.0,
                    "within_20pct_value_usd_stable": 102.0,
                }
            ],
            dates=1,
        )
        result = {row["metric"]: row for row in rows}
        self.assertAlmostEqual(result["route_count"]["difference_pp"], 1.0)
        self.assertAlmostEqual(
            result["within_20pct_value_usd"]["difference_pp"], 1.0
        )

    def test_release_index_uses_certificate_bound_generations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            releases = {
                "v2_core_event_source_release": (
                    "v2_event_source_release",
                    {
                        "uniswap_v2/20240115": {
                            "generation_id": "1" * 64,
                        },
                        "sushiswap_v2/20240115": {
                            "generation_id": "2" * 64,
                        },
                    },
                ),
                "v3_core_event_source_release": (
                    "v3_event_source_release",
                    {"20240115": {"generation_id": "3" * 64}},
                ),
            }
            for name, (kind, generations) in releases.items():
                root = data_root / "processed" / name
                generation_id = "a" * 64
                generation = root / "generations" / generation_id
                generation.mkdir(parents=True)
                certificate = generation / "certificate.json"
                certificate.write_text(
                    json.dumps(
                        {
                            "status": "pass",
                            "correction_generations": generations,
                        }
                    ),
                    encoding="utf-8",
                )
                certificate_sha256 = hashlib.sha256(
                    certificate.read_bytes()
                ).hexdigest()
                (root / "current.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "kind": kind,
                            "generation_id": generation_id,
                            "artifacts": {
                                "certificate": {
                                    "filename": certificate.name,
                                    "sha256": certificate_sha256,
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            index = _released_generation_index(str(data_root))
            self.assertEqual(index["uniswap_v2"], {"20240115": "1" * 64})
            self.assertEqual(index["sushiswap_v2"], {"20240115": "2" * 64})
            self.assertEqual(index["uniswap_v3"], {"20240115": "3" * 64})

    def test_release_boundary_counts_corrected_log_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            unified = data_root / "unified"
            unified.mkdir(parents=True)
            two_leg_frame(USDC).to_parquet(unified / "20241025.parquet")
            action = {
                "action": "correction",
                "stream": "swaps",
                "venue": "uniswap_v2",
                "tx_hash": TX,
                "provider_log_index": 1,
                "chain_log_index": 2,
            }
            with (
                patch(
                    "ddvc.analysis.route_reconstruction_validation._auxiliary_full_day_packages",
                    return_value=[("uniswap_v2", "20241025")],
                ),
                patch(
                    "ddvc.analysis.route_reconstruction_validation.correction_action_rows_unreleased",
                    return_value=[action],
                ),
            ):
                result = summarize_release_boundary(data_root)
            self.assertEqual(result["auxiliary_full_scope_venue_days"], 1)
            self.assertEqual(result["auxiliary_action_transactions"], 1)
            self.assertEqual(result["auxiliary_key_conflict_transactions"], 1)
            self.assertEqual(result["auxiliary_key_conflict_route_legs"], 2)
            self.assertEqual(result["auxiliary_key_conflict_routes"], 1)


if __name__ == "__main__":
    unittest.main()

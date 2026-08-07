from __future__ import annotations

import unittest

from ddvc.pricing.v3pools import (
    ANCHOR_DECIMALS,
    DECIMAL_SAMPLE_SIZE,
    decimals_gap_from_swaps,
    record_token_decimals,
    resolve_decimals,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
TOKEN = "0x0000000000000000000000000000000000000001"


def swap(amount1: float) -> dict[str, object]:
    return {
        "sqrtPriceX96": str(1 << 96),
        "amount0": "1",
        "amount1": str(amount1),
    }


class V3PoolStaticTests(unittest.TestCase):
    def test_decimal_inference_waits_for_a_robust_pool_sample(self) -> None:
        samples = [swap(100.0), *(swap(1.0) for _ in range(DECIMAL_SAMPLE_SIZE - 1))]
        self.assertIsNone(resolve_decimals(TOKEN, WETH, samples[:-1]))
        self.assertEqual(resolve_decimals(TOKEN, WETH, samples), (18, 18))

    def test_decimal_inference_rejects_a_nonconsensus_sample(self) -> None:
        samples = [
            *(swap(1.0) for _ in range(4)),
            *(swap(10.0) for _ in range(4)),
            *(swap(0.1) for _ in range(4)),
        ]
        self.assertIsNone(decimals_gap_from_swaps(samples))

    def test_known_decimals_still_require_pool_price_corroboration(self) -> None:
        known = {TOKEN: 18}
        wrong = [swap(100.0) for _ in range(DECIMAL_SAMPLE_SIZE)]
        right = [swap(1.0) for _ in range(DECIMAL_SAMPLE_SIZE)]
        self.assertIsNone(
            resolve_decimals(TOKEN, WETH, wrong, known_decimals=known)
        )
        self.assertEqual(
            resolve_decimals(TOKEN, WETH, right, known_decimals=known),
            (18, 18),
        )

    def test_address_registry_rejects_cross_pool_decimal_conflicts(self) -> None:
        known: dict[str, int] = {}
        record_token_decimals(known, TOKEN, 18)
        with self.assertRaisesRegex(ValueError, "conflicting token decimals"):
            record_token_decimals(known, TOKEN, 20)

    def test_anchor_registry_cannot_be_overridden(self) -> None:
        self.assertEqual(ANCHOR_DECIMALS[WETH], 18)
        with self.assertRaisesRegex(ValueError, "conflicting token decimals"):
            record_token_decimals({}, WETH, 8)


if __name__ == "__main__":
    unittest.main()

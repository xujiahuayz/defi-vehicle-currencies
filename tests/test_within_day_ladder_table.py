from __future__ import annotations

import unittest

from scripts.tabulate.render_within_day_ladder import (
    SPECIFICATIONS,
    render_within_day_ladder,
)


class WithinDayLadderTableTests(unittest.TestCase):
    def test_renderer_uses_models_as_columns_and_reports_fit(self) -> None:
        rows = []
        terms_by_spec = {
            "L1 pooled type dummies": ("native", "stable"),
            "L2 + date FE": ("native", "stable"),
            "L3 + date FE + own demand share": ("native", "stable", "demand"),
            "L4 two-way token + date FE": ("demand",),
        }
        for spec, _label in SPECIFICATIONS:
            for term in terms_by_spec[spec]:
                rows.append(
                    {
                        "spec": spec,
                        "sample": "all_endpoint_supported",
                        "term": term,
                        "beta": 1.25,
                        "se": 0.25,
                        "p": 0.001,
                        "n": 1000,
                        "dates": 100,
                        "tokens": 40,
                        "r_squared": 0.2,
                    }
                )
        rendered = render_within_day_ladder(rows)
        self.assertIn("Intermediary episode share (pp)", rendered)
        self.assertIn("Own endpoint-demand share", rendered)
        self.assertIn("$R^2$", rendered)
        self.assertIn("Date fixed effects & No & Yes & Yes & Yes", rendered)
        self.assertIn("$+1.25^{***}$", rendered)


if __name__ == "__main__":
    unittest.main()

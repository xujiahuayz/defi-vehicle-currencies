"""The paper must LOOK like the venue's papers, measured against them and not asserted.

Java's objection, and the measurement confirms it: the draft read as a process document.
Prose style was gated from the first commit, so the voice rules held, while the apparatus
was gated nowhere and was therefore never built. Against 14 published papers the draft
carried zero tables, zero figures, zero displayed equations, zero citations, zero notation
and no appendix, at 24 pages against a median of 55.

A referee judges a paper's shape before reading a sentence of it. Continuous prose with
nothing to look at, nothing defined in symbols and nobody cited reads as a memo whatever
the sentences say, so these are not decoration and they are not preferences.

Thresholds are empirical quantiles of the exemplars, recomputed by
`scripts/measure_venue_optics.py`, and this test asserts against the exhibit that script
writes. Floors sit at the first quartile and not the median, since the point is to catch
absence and gross shortfall and not to force a paper to the middle of a distribution.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPTICS = ROOT / "output" / "exhibits" / "venue_optics.jsonl"

# Features on which a count of zero is a structural absence, because the overwhelming
# majority of the sampled published papers carry them.
MUST_EXIST = ("tables", "figures", "equations", "citations", "appendix")


class VenueOpticsTests(unittest.TestCase):
    def setUp(self) -> None:
        if not OPTICS.exists():
            self.skipTest(f"{OPTICS.name} absent; run scripts/measure_venue_optics.py")
        self.rows = {r["feature"]: r for r in
                     (json.loads(l) for l in OPTICS.read_text().splitlines() if l.strip())}

    def test_no_structural_feature_is_absent(self) -> None:
        absent = [f for f in MUST_EXIST
                  if f in self.rows and self.rows[f]["draft"] == 0]
        self.assertEqual(absent, [], f"absent from the paper entirely: {absent}")

    def test_length_reaches_the_first_quartile(self) -> None:
        for f in ("pages", "words"):
            if f not in self.rows:
                continue
            r = self.rows[f]
            with self.subTest(feature=f):
                self.assertGreaterEqual(
                    r["draft"], r["exemplar_p25"],
                    f"{f}: {r['draft']} against a first quartile of {r['exemplar_p25']} "
                    f"and a median of {r['exemplar_median']} in the exemplars")

    def test_exhibit_counts_reach_the_first_quartile(self) -> None:
        for f in ("tables", "figures", "citations"):
            if f not in self.rows:
                continue
            r = self.rows[f]
            with self.subTest(feature=f):
                self.assertGreaterEqual(
                    r["draft"], r["exemplar_p25"],
                    f"{f}: {r['draft']} against a first quartile of {r['exemplar_p25']}")


if __name__ == "__main__":
    unittest.main()

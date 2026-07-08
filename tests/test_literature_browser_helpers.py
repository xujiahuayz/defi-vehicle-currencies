from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_fetcher():
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_literature_browser.py"
    spec = importlib.util.spec_from_file_location("fetch_literature_browser", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LiteratureBrowserHelperTests(unittest.TestCase):
    def test_sciencedirect_pdfft_normalizes_to_article_page(self) -> None:
        fetcher = load_fetcher()
        url = "https://www.sciencedirect.com/science/article/pii/S0304405X17302337/pdfft"
        self.assertEqual(
            fetcher.sciencedirect_article_url(url),
            "https://www.sciencedirect.com/science/article/pii/S0304405X17302337",
        )

    def test_openathens_sciencedirect_pdfft_stays_openathens_wrapped(self) -> None:
        fetcher = load_fetcher()
        url = (
            "https://go.openathens.net/redirector/ucl.ac.uk?"
            "url=https%3A%2F%2Fwww.sciencedirect.com%2Fscience%2Farticle%2Fpii%2F"
            "S0304405X17302337%2Fpdfft"
        )
        self.assertEqual(
            fetcher.sciencedirect_article_url(url),
            "https://go.openathens.net/redirector/ucl.ac.uk?url="
            "https%3A%2F%2Fwww.sciencedirect.com%2Fscience%2Farticle%2Fpii%2FS0304405X17302337",
        )

    def test_non_sciencedirect_url_is_not_normalized(self) -> None:
        fetcher = load_fetcher()
        self.assertIsNone(fetcher.sciencedirect_article_url("https://doi.org/10.1016/j.jfineco.2017.09.001"))


if __name__ == "__main__":
    unittest.main()

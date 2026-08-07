from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_browser_fetch_always_removes_response_listener(self) -> None:
        fetcher = load_fetcher()

        class Page:
            def __init__(self) -> None:
                self.listener = None

            def on(self, event, listener) -> None:
                self.listener = (event, listener)

            def remove_listener(self, event, listener) -> None:
                self.asserted_removal = (event, listener)

        page = Page()
        with patch.object(fetcher, "_browser_fetch_pdf", side_effect=RuntimeError("stop")):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                fetcher.browser_fetch_pdf(page, "https://example.com", 1, None, None)
        self.assertEqual(page.listener, page.asserted_removal)

    def test_source_worker_result_requires_complete_pdf_handoff(self) -> None:
        fetcher = load_fetcher()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            payload = root / "payload.pdf"
            result.write_text(json.dumps({"detail": "download", "has_data": True}), encoding="utf-8")
            payload.write_bytes(b"not a PDF")
            self.assertEqual(
                fetcher.read_source_worker_result(result, payload),
                (None, "source worker returned a non-PDF payload"),
            )

    def test_deadline_salvages_pdf_written_before_cleanup_hang(self) -> None:
        fetcher = load_fetcher()

        class Process:
            pid = 987654
            exitcode = None

            def __init__(self, *, args, **_kwargs) -> None:
                self.args = args
                self.alive = True

            def start(self) -> None:
                Path(self.args[0]).write_text(
                    json.dumps({"detail": "download complete", "has_data": True}),
                    encoding="utf-8",
                )
                Path(self.args[1]).write_bytes(b"%PDF-1.7\ncomplete")

            def join(self, _timeout=None) -> None:
                return None

            def is_alive(self) -> bool:
                return self.alive

            def terminate(self) -> None:
                self.alive = False

            def kill(self) -> None:
                self.alive = False

        class Context:
            def Process(self, **kwargs):
                return Process(**kwargs)

        with (
            patch.object(fetcher.multiprocessing, "get_context", return_value=Context()),
            patch.object(fetcher.os, "killpg", side_effect=ProcessLookupError),
        ):
            data, detail = fetcher.browser_fetch_with_deadline(
                profile=Path("profile"),
                url="https://example.com/paper",
                timeout_ms=10,
                source_timeout_ms=10,
                username=None,
                password=None,
                headless=True,
                channel="",
            )
        self.assertEqual(data, b"%PDF-1.7\ncomplete")
        self.assertIn("worker cleanup exceeded 10ms", detail)


if __name__ == "__main__":
    unittest.main()

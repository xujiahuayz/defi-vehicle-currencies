from __future__ import annotations

import fcntl
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ddvc.literature_sources as literature_sources
from ddvc.literature_sources import (
    Entry,
    existing_files_for_key,
    file_version,
    install_pdf,
    partition_existing_by_identity,
    pdf_identity_verdict,
    preferred_existing_file,
    remove_weaker_versions,
    source_identity_verdict,
    source_keys_lock,
    write_manifest_records,
)


def load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_fetcher():
    return load_script("fetch_literature_browser")


class LiteratureBrowserHelperTests(unittest.TestCase):
    def test_direct_download_prefers_bounded_curl_payload(self) -> None:
        direct = load_script("fetch_literature")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "paper.pdf"
            with (
                patch.object(direct, "download_with_curl", return_value=b"%PDF-1.7\ncomplete"),
                patch.object(direct.urllib.request, "urlopen") as urlopen,
                patch.object(direct, "install_pdf", return_value="installed") as install,
            ):
                self.assertEqual(
                    direct.download("https://example.com/paper.pdf", target, {}, False),
                    (True, "installed"),
                )
            urlopen.assert_not_called()
            install.assert_called_once_with(target, b"%PDF-1.7\ncomplete", False, entry=None)

    def test_source_identity_rejects_wrong_pdf_with_valid_magic(self) -> None:
        entry = Entry(
            key="KiyotakiWright1989MoneyMedium",
            kind="article",
            fields={
                "title": "On Money as a Medium of Exchange",
                "author": "Nobuhiro Kiyotaki and Randall Wright",
            },
        )
        self.assertEqual(
            source_identity_verdict(
                entry,
                "2026 CATALOG Returning to Chicago: Renaissance Quarterly",
            )[0],
            False,
        )
        self.assertEqual(
            source_identity_verdict(
                entry,
                "On Money as a Medium of Exchange by Nobuhiro Kiyotaki and Randall Wright",
            )[0],
            True,
        )

    def test_source_identity_requires_complete_bibliography_byline(self) -> None:
        entry = Entry(
            key="Protocol",
            kind="techreport",
            fields={
                "title": "A Concentrated Liquidity Protocol",
                "author": "Alice Adams and Bob Brown and Carol Chen",
            },
        )
        title = "A Concentrated Liquidity Protocol"
        self.assertFalse(
            source_identity_verdict(
                entry,
                f"{title}\nAlice Adams",
                byline_text="Alice Adams",
            )[0]
        )
        self.assertTrue(
            source_identity_verdict(
                entry,
                f"{title}\nAlice Adams, Bob Brown, and Carol Chen",
                byline_text="Alice Adams, Bob Brown, and Carol Chen",
            )[0]
        )

    def test_source_identity_normalizes_diacritics_in_byline(self) -> None:
        entry = Entry(
            key="Paper",
            kind="article",
            fields={
                "title": "Over-the-Counter Markets",
                "author": "Duffie, Darrell and Garleanu, Nicolae and Pedersen, Lasse",
            },
        )
        passed, detail = source_identity_verdict(
            entry,
            "Over-the-Counter Markets",
            byline_text="Darrell Duffie, Nicolae Gârleanu, and Lasse Pedersen",
        )
        self.assertTrue(passed, detail)

    def test_partition_existing_quarantines_identity_mismatch(self) -> None:
        entry = Entry("Paper", "article", {"title": "Market Liquidity", "author": "Ada Smith"})
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.pdf"
            invalid = Path(directory) / "invalid.pdf"
            valid.write_bytes(b"%PDF-valid")
            invalid.write_bytes(b"%PDF-invalid")
            with patch(
                "ddvc.literature_sources.pdf_identity_verdict",
                side_effect=[(True, "matched"), (False, "wrong title")],
            ):
                accepted, rejected = partition_existing_by_identity([valid, invalid], entry)
        self.assertEqual(accepted, [valid])
        self.assertEqual(rejected, [(invalid, "wrong title")])

    def test_incremental_direct_reader_enforces_total_deadline(self) -> None:
        direct = load_script("fetch_literature")

        class Response:
            def read1(self, _size):
                return b"x"

        with patch.object(direct.time, "monotonic", side_effect=[0.0, 0.1, 1.1]):
            with self.assertRaisesRegex(TimeoutError, "exceeded 1s"):
                direct.read_response_with_deadline(Response(), timeout_seconds=1)

    def test_wiley_supplement_request_uses_article_referrer(self) -> None:
        direct = load_script("fetch_literature")
        url = (
            "https://onlinelibrary.wiley.com/action/downloadSupplement?"
            "doi=10.1111%2Fjofi.12903&file=jofi12903-sup-0001-InternetAppendix.pdf"
        )
        headers = direct.headers_for(url, {}, {})
        self.assertEqual(headers["Referer"], "https://onlinelibrary.wiley.com/doi/10.1111/jofi.12903")

    def test_version_parser_ignores_version_words_inside_title_slug(self) -> None:
        path = Path("2022-PaperAppendix-supplement-working-paper-with-online-appendix.pdf")
        self.assertEqual(file_version(path), "supplement")

    def test_selective_manifests_merge_by_exact_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "download-manifest.json"
            write_manifest_records(manifest, [{"key": "PaperA", "status": "ok"}], merge=True)
            installed = write_manifest_records(manifest, [{"key": "PaperB", "status": "miss"}], merge=True)
            self.assertEqual([record["key"] for record in installed], ["PaperA", "PaperB"])
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), installed)

    def test_selective_manifest_replaces_only_its_owned_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "download-manifest.json"
            write_manifest_records(
                manifest,
                [{"key": "PaperA", "status": "miss"}, {"key": "PaperB", "status": "ok"}],
                merge=False,
            )
            installed = write_manifest_records(manifest, [{"key": "PaperA", "status": "ok"}], merge=True)
            self.assertEqual(
                installed,
                [{"key": "PaperA", "status": "ok"}, {"key": "PaperB", "status": "ok"}],
            )

    def test_source_key_lock_excludes_an_overlapping_fetch_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            with patch.object(literature_sources, "SHARED_RUNTIME_DIR", runtime):
                with source_keys_lock(["PaperA"]):
                    [lock_path] = list(runtime.glob("literature-source-*.lock"))
                    with lock_path.open("a+", encoding="utf-8") as competing:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(
                                competing.fileno(),
                                fcntl.LOCK_EX | fcntl.LOCK_NB,
                            )
                with lock_path.open("a+", encoding="utf-8") as after_release:
                    fcntl.flock(
                        after_release.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                    fcntl.flock(after_release.fileno(), fcntl.LOCK_UN)

    def test_browser_binary_route_has_unambiguous_precedence(self) -> None:
        fetcher = load_fetcher()
        self.assertEqual(fetcher.browser_executable_options("chrome", ""), {"channel": "chrome"})
        self.assertEqual(fetcher.browser_executable_options("", "/Applications/Brave"), {"executable_path": "/Applications/Brave"})
        with self.assertRaisesRegex(ValueError, "either"):
            fetcher.browser_executable_options("chrome", "/Applications/Brave")

    def test_existing_source_match_does_not_confuse_main_and_companion_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            papers = Path(directory)
            main = papers / "2021-Paper-main-title.pdf"
            appendix = papers / "2021-PaperAppendix-supplement-online-appendix.pdf"
            main.write_bytes(b"%PDF-1.7\nmain")
            appendix.write_bytes(b"%PDF-1.7\nappendix")
            self.assertEqual(existing_files_for_key(papers, "Paper"), [main])
            self.assertEqual(existing_files_for_key(papers, "PaperAppendix"), [appendix])

    def test_public_published_source_is_not_openathens_wrapped(self) -> None:
        for name in ("fetch_literature", "fetch_literature_browser"):
            with self.subTest(name=name):
                fetcher = load_script(name)
                source = fetcher.Source(
                    url="https://authors.example/published.pdf",
                    version="published",
                    access="public",
                    label="author copy",
                )
                self.assertEqual(fetcher.with_openathens([source], "ucl.ac.uk"), [source])

    def test_authenticated_published_source_gets_openathens_fallback(self) -> None:
        direct = load_script("fetch_literature")
        browser = load_script("fetch_literature_browser")
        self.assertIs(direct.with_openathens, browser.with_openathens)
        source = direct.Source(
            url="https://publisher.example/published.pdf",
            version="published",
            access="authenticated",
            label="publisher copy",
        )
        expanded = direct.with_openathens([source], "ucl.ac.uk")
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0].access, "institutional")
        self.assertEqual(expanded[1], source)

    def test_direct_and_browser_fetchers_share_install_and_naming_policy(self) -> None:
        direct = load_script("fetch_literature")
        browser = load_script("fetch_literature_browser")
        self.assertIs(direct.install_pdf, browser.install_pdf)
        self.assertIs(direct.safe_filename, browser.safe_filename)
        self.assertIs(direct.parse_bibtex, browser.parse_bibtex)
        self.assertIs(direct.load_source_registry, browser.load_source_registry)
        self.assertIs(direct.default_sources_from_bib, browser.default_sources_from_bib)
        self.assertIs(direct.ordered_sources, browser.ordered_sources)
        self.assertIs(direct.partition_existing_by_identity, browser.partition_existing_by_identity)
        self.assertIs(direct.remove_local_and_mirrored, browser.remove_local_and_mirrored)

    def test_fetchers_reject_unadmitted_source_before_transport_setup(self) -> None:
        bibliography = """@article{Candidate,
  author = {Ada Smith},
  title = {A Candidate Paper},
  year = {2026}
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bib = root / "sources.bib"
            source_map = root / "sources.json"
            admission = root / "admission.json"
            bib.write_text(bibliography, encoding="utf-8")
            source_map.write_text('{"sources": {}}', encoding="utf-8")
            admission.write_text('{"schema_version": 1, "decisions": {}}', encoding="utf-8")
            for script_name in ("fetch_literature", "fetch_literature_browser"):
                with self.subTest(script=script_name):
                    fetcher = load_script(script_name)
                    arguments = [
                        script_name,
                        "--bib",
                        str(bib),
                        "--sources",
                        str(source_map),
                        "--admission",
                        str(admission),
                        "--key",
                        "Candidate",
                    ]
                    with patch.object(sys, "argv", arguments):
                        if script_name == "fetch_literature_browser":
                            with patch.object(fetcher, "import_playwright") as transport:
                                with self.assertRaisesRegex(ValueError, "source admission failed"):
                                    fetcher.main()
                                transport.assert_not_called()
                        else:
                            with patch.object(fetcher, "fetch_all") as transport:
                                with self.assertRaisesRegex(ValueError, "source admission failed"):
                                    fetcher.main()
                                transport.assert_not_called()

    def test_install_rejects_identity_mismatch_before_writing(self) -> None:
        entry = Entry("Paper", "article", {"title": "Market Liquidity", "author": "Ada Smith"})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "paper.pdf"
            with patch(
                "ddvc.literature_sources.pdf_identity_verdict",
                return_value=(False, "title=0/2; author=none"),
            ):
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    install_pdf(target, b"%PDF-wrong", False, entry=entry)
            self.assertFalse(target.exists())

    def test_pdf_install_mirrors_to_primary_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            primary = root / "primary"
            target = worktree / "literature" / "papers" / "paper.pdf"
            target.parent.mkdir(parents=True)
            detail = install_pdf(
                target,
                b"%PDF-1.7\ncomplete",
                False,
                repo_root=worktree,
                primary_root=primary,
            )
            mirror = primary / "literature" / "papers" / "paper.pdf"
            self.assertEqual(detail, "17 bytes")
            self.assertEqual(target.read_bytes(), mirror.read_bytes())

    def test_published_install_retires_weaker_versions_in_both_checkouts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            primary = root / "primary"
            papers = worktree / "literature" / "papers"
            primary_papers = primary / "literature" / "papers"
            papers.mkdir(parents=True)
            primary_papers.mkdir(parents=True)
            weak = papers / "2020-Key-working-paper-title.pdf"
            mirror = primary_papers / weak.name
            published = papers / "2022-Key-title.pdf"
            weak.write_bytes(b"%PDF-1.7\nweak")
            mirror.write_bytes(weak.read_bytes())
            published.write_bytes(b"%PDF-1.7\npublished")
            self.assertEqual(preferred_existing_file([weak, published]), published)
            removed = remove_weaker_versions(
                [weak, published],
                "published",
                published,
                repo_root=worktree,
                primary_root=primary,
            )
            self.assertEqual(set(removed), {weak, mirror})
            self.assertFalse(weak.exists())
            self.assertFalse(mirror.exists())
            self.assertTrue(published.exists())

    def test_download_reader_waits_for_and_validates_pdf(self) -> None:
        fetcher = load_fetcher()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.pdf"
            path.write_bytes(b"%PDF-1.7\ncomplete")

            class Download:
                def path(self):
                    return path

            self.assertEqual(fetcher.pdf_from_download(Download()), path.read_bytes())

    def test_sciencedirect_click_captures_completed_download(self) -> None:
        fetcher = load_fetcher()
        payload = b"%PDF-1.7\ncomplete"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.pdf"
            path.write_bytes(payload)

            class Download:
                url = "https://pdf.sciencedirectassets.com/paper.pdf"

                def path(self):
                    return path

            class DownloadInfo:
                value = Download()

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            class Button:
                def count(self):
                    return 1

                def is_visible(self, timeout=None):
                    return True

                def click(self, timeout=None):
                    return None

            class Locator:
                first = Button()

            class Page:
                url = "https://www.sciencedirect.com/science/article/pii/example"

                def on(self, *_args):
                    return None

                def remove_listener(self, *_args):
                    return None

                def locator(self, _selector):
                    return Locator()

                def expect_download(self, timeout=None):
                    return DownloadInfo()

            data, detail = fetcher.sciencedirect_pdf_from_page(Page(), 100)
        self.assertEqual(data, payload)
        self.assertIn("sciencedirect-download", detail)

    def test_sciencedirect_security_page_is_an_explicit_block(self) -> None:
        fetcher = load_fetcher()

        class Body:
            def inner_text(self, timeout=None):
                return "Security verification"

        class Page:
            url = "https://pdf.sciencedirectassets.com/issue/main.pdf?token=redacted"

            def locator(self, _selector):
                return Body()

        self.assertEqual(
            fetcher.access_block_detail(Page()),
            "sciencedirect-security-verification",
        )

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

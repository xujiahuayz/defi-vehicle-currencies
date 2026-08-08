#!/usr/bin/env python3
"""Fetch literature PDFs through an authenticated browser profile.

This is the reproducible route for institutional sources whose PDF URLs cannot
be replayed with urllib/cookie headers. It reads the same committed BibTeX and
source map as scripts/fetch_literature.py, uses a gitignored persistent browser
profile for OpenAthens/UCL login state, and writes PDFs plus a manifest under
literature/papers/.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import multiprocessing
import os
import re
import signal
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

from ddvc.literature_sources import (  # noqa: E402
    Entry,
    Source,
    default_sources_from_bib,
    existing_files_for_key,
    file_version,
    install_pdf,
    is_pdf,
    load_source_registry,
    mirror_validated_pdf,
    openathens_url,
    ordered_sources,
    parse_bibtex,
    preferred_existing_file,
    remove_weaker_versions,
    safe_filename,
    should_replace_existing,
    source_keys_lock,
    write_manifest_records,
    with_openathens,
)
from ddvc.paths import (  # noqa: E402
    LITERATURE_BIB,
    LITERATURE_DIR,
    LITERATURE_DOWNLOAD_MANIFEST,
    LITERATURE_PAPERS_DIR,
    LITERATURE_PDF_SOURCES,
    REPO_ROOT,
)
from ddvc.runtime import atomic_output


PROFILE_DIR = LITERATURE_DIR / "auth" / "browser-profile"


def import_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run: python3 -m pip install '.[auth]' "
            "&& python3 -m playwright install chromium"
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def pdf_from_response(response: Any) -> bytes | None:
    try:
        data = response.body()
    except Exception:
        return None
    return data if is_pdf(data) else None


def pdf_from_download(download: Any) -> bytes | None:
    """Wait for a browser download to finish, then return only a complete PDF."""
    try:
        path = download.path()
        data = Path(path).read_bytes() if path else b""
    except Exception:
        return None
    return data if is_pdf(data) else None


def goto_page(page: Any, url: str, timeout_ms: int) -> Any | None:
    response = page.goto(url, wait_until="commit", timeout=timeout_ms)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 8000))
    except Exception:
        pass
    return response


def visible_text(page: Any, timeout_ms: int = 3000) -> str:
    try:
        return page.locator("body").inner_text(timeout=timeout_ms)
    except Exception:
        return ""


def access_block_detail(page: Any) -> str | None:
    text = visible_text(page)
    if "Access Check" in text and "reCAPTCHA" in text and "jstor.org" in page.url:
        return "jstor-access-check-recaptcha"
    if "Sign in to your account" in text and "login.microsoftonline.com" in page.url:
        return "ucl-login-required"
    if "request access" in text.lower() and "informs.org" in page.url:
        return "publisher-request-access"
    parsed = urllib.parse.urlparse(page.url)
    if (
        parsed.netloc == "pdf.sciencedirectassets.com"
        and "security verification" in text.lower()
    ):
        return "sciencedirect-security-verification"
    return None


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def jstor_stable_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc.endswith("jstor.org"):
        return None
    match = re.search(r"/stable/(?:pdf/)?([^/?#]+)", parsed.path)
    if not match:
        return None
    stable_id = match.group(1)
    if stable_id.endswith(".pdf"):
        stable_id = stable_id[:-4]
    return stable_id or None


def jstor_article_url(url: str) -> str | None:
    stable_id = jstor_stable_id(url)
    if not stable_id:
        return None
    return f"https://www.jstor.org/stable/{stable_id}"


def jstor_pdf_urls(url: str) -> list[str]:
    stable_id = jstor_stable_id(url)
    if not stable_id:
        return []
    return [
        f"https://www.jstor.org/stable/pdf/{stable_id}.pdf",
        f"https://www.jstor.org/stable/pdf/{stable_id}.pdf?download=true",
    ]


def sciencedirect_article_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc == "go.openathens.net":
        target = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        article = sciencedirect_article_url(target)
        if article:
            match = re.search(r"/redirector/([^/?#]+)", parsed.path)
            domain = match.group(1) if match else ""
            return openathens_url(article, domain) if domain else article
        return None
    if not parsed.netloc.endswith("sciencedirect.com"):
        return None
    match = re.search(r"/science/article/pii/([^/?#]+)", parsed.path)
    if not match:
        return None
    return f"https://www.sciencedirect.com/science/article/pii/{match.group(1)}"


def is_sciencedirect_page(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.endswith("sciencedirect.com")


def page_pdf_links(page: Any) -> list[str]:
    try:
        raw_links = page.evaluate(
            """() => Array.from(document.querySelectorAll('a,meta,iframe,embed,object'))
                .map((x) => x.href || x.src || x.data || x.content || x.getAttribute('href') || x.getAttribute('src') || '')
                .filter((href) => href && /pdf|epdf|viewcontent/i.test(href))"""
        )
    except Exception:
        return []
    links: list[str] = []
    for raw in raw_links:
        link = str(raw)
        if link.startswith("/"):
            from urllib.parse import urljoin

            link = urljoin(page.url, link)
        if link.startswith("http") and link not in links:
            links.append(link)
    return dedupe(links)


def ebsco_pdf_from_page(page: Any, timeout_ms: int) -> tuple[bytes | None, str | None]:
    if "research.ebsco.com" not in page.url:
        return None, None

    button = page.locator("button:has-text('Access now (PDF)')").first
    try:
        if button.count() and button.is_visible(timeout=2000):
            button.click(timeout=5000)
            page.wait_for_url(re.compile(r".*/viewer/pdf/.*"), timeout=timeout_ms)
    except Exception:
        pass

    match = re.search(r"/c/([^/]+)/viewer/pdf/([^/?#]+)", page.url)
    if not match:
        return None, None

    profile_id, record_id = match.groups()
    link_url = (
        f"https://research.ebsco.com/linkprocessor/v2-pdf-full-text?"
        f"recordId={urllib.parse.quote(record_id)}"
        f"&sourceRecordId={urllib.parse.quote(record_id)}"
        f"&restriction=&profileIdentifier={urllib.parse.quote(profile_id)}"
        f"&intent=view&type=pdfLink&lang=en"
    )
    try:
        link_response = page.context.request.get(link_url, timeout=timeout_ms)
        link_data = link_response.json()
        pdf_url = str(link_data.get("url", ""))
        if not pdf_url:
            return None, f"ebsco-linkprocessor-no-url {link_response.status}"
        pdf_response = page.context.request.get(pdf_url, headers={"Accept": "application/pdf,*/*"}, timeout=timeout_ms)
        data = pdf_response.body()
    except Exception as exc:  # noqa: BLE001
        return None, f"ebsco-pdf {type(exc).__name__}: {exc}"
    if is_pdf(data):
        return data, f"ebsco-pdf {pdf_response.url}"
    return None, f"ebsco-pdf status={pdf_response.status} not-pdf"


def sciencedirect_pdf_from_page(page: Any, timeout_ms: int) -> tuple[bytes | None, str | None]:
    if not is_sciencedirect_page(page.url):
        return None, None

    responses: list[Any] = []

    def remember_response(response: Any) -> None:
        responses.append(response)

    page.on("response", remember_response)
    selectors = [
        "a:has-text('Download PDF')",
        "button:has-text('Download PDF')",
        "a[aria-label*='Download PDF']",
        "a[href*='/pdfft']",
        "a[href*='pdf']",
    ]
    try:
        button = first_visible(page, selectors)
        if button:
            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    button.click(timeout=5000)
                download = download_info.value
                data = pdf_from_download(download)
                if data:
                    return data, f"sciencedirect-download {download.url}"
            except Exception:
                page.wait_for_timeout(min(timeout_ms, 8000))
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            page.remove_listener("response", remember_response)

    for response in reversed(responses):
        url = getattr(response, "url", "")
        if "sciencedirectassets.com" not in url and "/pdfft" not in url and "pdf" not in url.lower():
            continue
        data = pdf_from_response(response)
        if data:
            return data, f"sciencedirect-response {url}"

    links = page_pdf_links(page)
    for link in links:
        if "sciencedirect.com" not in link and "sciencedirectassets.com" not in link:
            continue
        try:
            response = page.context.request.get(link, headers={"Accept": "application/pdf,*/*"}, timeout=timeout_ms)
            data = response.body()
        except Exception as exc:  # noqa: BLE001
            detail = f"sciencedirect-link {type(exc).__name__}: {exc}"
            continue
        if is_pdf(data):
            return data, f"sciencedirect-link {response.url}"
        detail = f"sciencedirect-link status={response.status} not-pdf"
    return None, locals().get("detail", "sciencedirect-no-pdf")


def first_visible(page: Any, selectors: list[str]) -> Any | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None


def complete_microsoft_login(page: Any, username: str | None, password: str | None) -> bool:
    """Complete the common Microsoft Entra login screens when credentials are supplied."""
    if not username or not password:
        return False
    progressed = False
    for _ in range(6):
        email = first_visible(page, ["input[type='email']", "input[name='loginfmt']", "#i0116"])
        if email:
            email.fill(username)
            button = first_visible(page, ["input[type='submit']", "button[type='submit']", "#idSIButton9"])
            if button:
                button.click()
                page.wait_for_timeout(2000)
                progressed = True
                continue

        passwd = first_visible(page, ["input[type='password']", "input[name='passwd']", "#i0118"])
        if passwd:
            passwd.fill(password)
            button = first_visible(page, ["input[type='submit']", "button[type='submit']", "#idSIButton9"])
            if button:
                button.click()
                page.wait_for_timeout(3000)
                progressed = True
                continue

        stay_signed_in = first_visible(page, ["#idSIButton9", "input[type='submit']", "button[type='submit']"])
        if stay_signed_in and "login.microsoftonline.com" in page.url:
            stay_signed_in.click()
            page.wait_for_timeout(2000)
            progressed = True
            continue
        break
    return progressed


def accept_consent_if_present(page: Any) -> bool:
    progressed = False
    selectors = [
        "button:has-text('Accept')",
        "button:has-text('I accept')",
        "button:has-text('Agree')",
        "input[type='submit'][value*='Accept']",
        "input[type='submit'][value*='I accept']",
        "input[type='submit'][value*='Agree']",
        "a:has-text('Accept')",
        "a:has-text('I accept')",
        "a:has-text('Agree')",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible(timeout=1000):
                locator.click()
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                return True
        except Exception:
            continue

    if "jstor.org/tc/accept" in page.url:
        try:
            progressed = bool(
                page.evaluate(
                    """() => {
                        const submit = document.querySelector("button[type=submit], input[type=submit]");
                        if (submit) {
                            submit.click();
                            return true;
                        }
                        const form = document.querySelector("form");
                        if (form) {
                            form.submit();
                            return true;
                        }
                        return false;
                    }"""
                )
            )
        except Exception:
            progressed = False
        if progressed:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
    return progressed


def browser_fetch_pdf(
    page: Any,
    url: str,
    timeout_ms: int,
    username: str | None,
    password: str | None,
) -> tuple[bytes | None, str]:
    responses: list[Any] = []

    def remember_response(response: Any) -> None:
        responses.append(response)

    page.on("response", remember_response)
    try:
        return _browser_fetch_pdf(
            page,
            url,
            timeout_ms,
            username,
            password,
            responses,
        )
    finally:
        with contextlib.suppress(Exception):
            page.remove_listener("response", remember_response)


def _browser_fetch_pdf(
    page: Any,
    url: str,
    timeout_ms: int,
    username: str | None,
    password: str | None,
    responses: list[Any],
) -> tuple[bytes | None, str]:
    navigation_url = jstor_article_url(url) or sciencedirect_article_url(url) or url
    try:
        with page.expect_download(timeout=5000) as download_info:
            response = goto_page(page, navigation_url, timeout_ms)
        download = download_info.value
        data = pdf_from_download(download)
        if data:
            return data, f"download {download.url}"
    except Exception as exc:  # noqa: BLE001 - caller records exact failure.
        if "Timeout" in type(exc).__name__:
            try:
                response = goto_page(page, navigation_url, timeout_ms)
            except Exception as goto_exc:  # noqa: BLE001 - caller records exact failure.
                return None, f"goto {type(goto_exc).__name__}: {goto_exc}"
        elif "Download is starting" in str(exc):
            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    goto_page(page, navigation_url, timeout_ms)
                download = download_info.value
                data = pdf_from_download(download)
                if data:
                    return data, f"download {download.url}"
            except Exception as download_exc:  # noqa: BLE001
                return None, f"download {type(download_exc).__name__}: {download_exc}"
            return None, f"download not-pdf: {exc}"
        else:
            return None, f"goto {type(exc).__name__}: {exc}"

    if complete_microsoft_login(page, username, password):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 8000))
        except Exception:
            pass
    for _ in range(3):
        if not accept_consent_if_present(page):
            break

    block = access_block_detail(page)
    if block:
        return None, f"{block}; final={page.url}"

    ebsco_data, ebsco_detail = ebsco_pdf_from_page(page, timeout_ms)
    if ebsco_data:
        return ebsco_data, ebsco_detail or f"ebsco-pdf {page.url}"

    sciencedirect_data, sciencedirect_detail = sciencedirect_pdf_from_page(page, timeout_ms)
    if sciencedirect_data:
        return sciencedirect_data, sciencedirect_detail or f"sciencedirect-pdf {page.url}"
    block = access_block_detail(page)
    if block:
        return None, f"{block}; final={page.url}"

    candidates = [response, *reversed(responses)]
    for candidate in candidates:
        if candidate is None:
            continue
        data = pdf_from_response(candidate)
        if data:
            return data, f"response {candidate.url}"

    page.wait_for_timeout(2500)
    final_url = page.url

    request_headers = {"Accept": "application/pdf,*/*"}
    candidate_urls = dedupe(
        [
            *jstor_pdf_urls(final_url),
            *jstor_pdf_urls(url),
            final_url,
            url,
            *page_pdf_links(page),
        ]
    )
    for candidate_url in candidate_urls:
        try:
            api_response = page.context.request.get(candidate_url, headers=request_headers, timeout=timeout_ms)
            data = api_response.body()
        except Exception as exc:  # noqa: BLE001
            detail = f"context-request {type(exc).__name__}: {exc}"
        else:
            if is_pdf(data):
                return data, f"context-request {api_response.url}"
            detail = f"context-request status={api_response.status} not-pdf"

    try:
        encoded = page.evaluate(
            """async () => {
                const response = await fetch(window.location.href, {headers: {Accept: 'application/pdf,*/*'}});
                const buffer = await response.arrayBuffer();
                let binary = '';
                const bytes = new Uint8Array(buffer);
                for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
                return btoa(binary);
            }"""
        )
        data = base64.b64decode(encoded)
    except Exception as exc:  # noqa: BLE001
        return None, f"{detail}; browser-fetch {type(exc).__name__}: {exc}; final={final_url}"
    if is_pdf(data):
        return data, f"browser-fetch {final_url}"
    return None, f"{detail}; browser-fetch not-pdf; final={final_url}"


def browser_executable_options(channel: str, executable_path: str) -> dict[str, str]:
    """Select one explicit browser binary route without ambiguous precedence."""
    if channel and executable_path:
        raise ValueError("use either --channel or --executable-path, not both")
    if executable_path:
        return {"executable_path": executable_path}
    return {"channel": channel} if channel else {}


def _source_worker(
    result_path_text: str,
    data_path_text: str,
    log_path_text: str,
    profile_text: str,
    url: str,
    timeout_ms: int,
    username: str | None,
    password: str | None,
    headless: bool,
    channel: str,
    executable_path: str = "",
) -> None:
    """Run one browser source in an independently killable process."""
    if hasattr(os, "setsid"):
        os.setsid()
    with Path(log_path_text).open("a", encoding="utf-8") as log_handle:
        os.dup2(log_handle.fileno(), 1)
        os.dup2(log_handle.fileno(), 2)
        result_path = Path(result_path_text)
        data_path = Path(data_path_text)
        try:
            sync_playwright, _ = import_playwright()
            with sync_playwright() as playwright:
                kwargs: dict[str, Any] = {
                    "user_data_dir": profile_text,
                    "headless": headless,
                    "accept_downloads": True,
                    "viewport": {"width": 1400, "height": 1000},
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                kwargs.update(browser_executable_options(channel, executable_path))
                context = playwright.chromium.launch_persistent_context(**kwargs)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    data, detail = browser_fetch_pdf(
                        page,
                        url,
                        timeout_ms,
                        username,
                        password,
                    )
                    if data:
                        with atomic_output(data_path) as temporary:
                            temporary.write_bytes(data)
                    result = {"detail": detail, "has_data": bool(data)}
                    with atomic_output(result_path) as temporary:
                        temporary.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
                finally:
                    context.close()
        except BaseException as exc:  # noqa: BLE001 - returned to the supervising process.
            if not result_path.exists():
                result = {"detail": f"worker {type(exc).__name__}: {exc}", "has_data": False}
                with atomic_output(result_path) as temporary:
                    temporary.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")


def read_source_worker_result(
    result_path: Path,
    data_path: Path,
) -> tuple[bytes | None, str] | None:
    """Read a complete worker handoff; incomplete writes never become results."""
    if not result_path.exists():
        return None
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"invalid source-worker result: {type(exc).__name__}: {exc}"
    detail = str(result.get("detail") or "worker returned no PDF")
    if not bool(result.get("has_data")):
        return None, detail
    try:
        data = data_path.read_bytes()
    except OSError as exc:
        return None, f"source worker reported PDF without payload: {type(exc).__name__}: {exc}"
    if not is_pdf(data):
        return None, "source worker returned a non-PDF payload"
    return data, detail


def browser_fetch_with_deadline(
    *,
    profile: Path,
    url: str,
    timeout_ms: int,
    source_timeout_ms: int,
    username: str | None,
    password: str | None,
    headless: bool,
    channel: str,
    executable_path: str = "",
) -> tuple[bytes | None, str]:
    """Fetch one source behind an operating-system-enforced deadline."""
    process_context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="literature-source-") as directory:
        root = Path(directory)
        result_path = root / "result.json"
        data_path = root / "payload.pdf"
        log_path = root / "worker.log"
        process = process_context.Process(
            target=_source_worker,
            args=(
                str(result_path),
                str(data_path),
                str(log_path),
                str(profile),
                url,
                timeout_ms,
                username,
                password,
                headless,
                channel,
                executable_path,
            ),
        )
        process.start()
        process.join(None if source_timeout_ms <= 0 else source_timeout_ms / 1000)
        timed_out = process.is_alive()
        if timed_out:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (AttributeError, ProcessLookupError, PermissionError):
                process.terminate()
            process.join(5)
            if process.is_alive():
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (AttributeError, ProcessLookupError, PermissionError):
                    process.kill()
                process.join()
        worker_result = read_source_worker_result(result_path, data_path)
        if worker_result is not None:
            data, detail = worker_result
            if data is not None and timed_out:
                return data, f"{detail}; worker cleanup exceeded {source_timeout_ms}ms and was terminated"
            if not timed_out:
                return data, detail
        if timed_out:
            return None, f"source exceeded {source_timeout_ms}ms and worker was terminated"
        if worker_result is None:
            worker_log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            tail = worker_log[-1000:].strip()
            detail = f"source worker exited {process.exitcode} without a result"
            return None, f"{detail}; log={tail}" if tail else detail
        return worker_result


def attempt_record(source: Source, detail: str, *, ok: bool = False) -> dict[str, Any]:
    return {
        "ok": ok,
        "detail": detail,
        "url": source.url,
        "version": source.version,
        "access": source.access,
        "label": source.label,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bib", type=Path, default=LITERATURE_BIB)
    parser.add_argument("--sources", type=Path, default=LITERATURE_PDF_SOURCES)
    parser.add_argument("--out", type=Path, default=LITERATURE_PAPERS_DIR)
    parser.add_argument("--manifest", type=Path, default=LITERATURE_DOWNLOAD_MANIFEST.with_name("browser-download-manifest.json"))
    parser.add_argument("--profile", type=Path, default=PROFILE_DIR)
    parser.add_argument("--prefer", choices=["published", "working"], default="published")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--key", action="append", help="Fetch only this BibTeX key; repeatable.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--channel", default="", help="Browser channel, e.g. chrome. Empty uses bundled Chromium.")
    parser.add_argument("--executable-path", default="", help="Explicit Chromium-family browser binary, e.g. Brave; mutually exclusive with --channel.")
    parser.add_argument("--timeout-ms", type=int, default=90000)
    parser.add_argument("--source-timeout-ms", type=int, default=120000)
    parser.add_argument("--username-env", default="UCL_USER")
    parser.add_argument("--password-env", default="UCL_PW")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    username = os.environ.get(args.username_env)
    password = os.environ.get(args.password_env)

    import_playwright()
    entries = parse_bibtex(args.bib)
    openathens_domain, source_map = load_source_registry(args.sources)
    keys = list(entries)
    if args.key:
        wanted = set(args.key)
        keys = [key for key in keys if key in wanted]
    if args.limit:
        keys = keys[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    args.profile.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    with source_keys_lock(keys):
        for key in keys:
            entry = entries[key]
            committed = source_map.get(key, [])
            sources = [
                *ordered_sources(with_openathens(committed, openathens_domain), args.prefer),
                *(
                    []
                    if committed
                    else ordered_sources(with_openathens(default_sources_from_bib(entry), openathens_domain), args.prefer)
                ),
            ]
            attempts: list[dict[str, Any]] = []
            for index, source in enumerate(sources, start=1):
                target = args.out / safe_filename(
                    entry.key,
                    entry.fields.get("year", "undated"),
                    entry.fields.get("title", entry.key),
                    source,
                )
                existing = existing_files_for_key(args.out, key)
                if existing and not should_replace_existing(existing, source, args.overwrite):
                    existing_file = preferred_existing_file(existing)
                    remove_weaker_versions(existing, file_version(existing_file), existing_file)
                    mirror_validated_pdf(existing_file)
                    print(f"ok {key}: {existing_file.relative_to(REPO_ROOT)} ({source.version}, existing)")
                    records.append(
                        {
                            "key": key,
                            "status": "ok",
                            "file": str(existing_file.relative_to(REPO_ROOT)),
                            "version": "existing",
                            "access": source.access,
                            "url": source.url,
                            "attempts": [attempt_record(source, "exists", ok=True)],
                        }
                    )
                    break
                print(f"try {key} [{index}/{len(sources)}] {source.version}: {source.url}", flush=True)
                data, detail = browser_fetch_with_deadline(
                    profile=args.profile,
                    url=source.url,
                    timeout_ms=args.timeout_ms,
                    source_timeout_ms=args.source_timeout_ms,
                    username=username,
                    password=password,
                    headless=args.headless,
                    channel=args.channel,
                    executable_path=args.executable_path,
                )
                if data:
                    saved = install_pdf(target, data, args.overwrite)
                    remove_weaker_versions(existing, source.version, target)
                    print(f"ok {key}: {target.relative_to(REPO_ROOT)} ({source.version}, {saved})")
                    records.append(
                        {
                            "key": key,
                            "status": "ok",
                            "file": str(target.relative_to(REPO_ROOT)),
                            "version": source.version,
                            "access": source.access,
                            "url": source.url,
                            "attempts": [*attempts, attempt_record(source, detail, ok=True)],
                        }
                    )
                    break
                attempts.append(attempt_record(source, detail))
                print(f"miss {key} [{index}/{len(sources)}] {source.version}: {detail}", flush=True)
                time.sleep(0.5)
            else:
                records.append({"key": key, "status": "miss", "attempts": attempts, "sources": [source.__dict__ for source in sources]})

        write_manifest_records(args.manifest, records, merge=bool(args.key or args.limit))
    ok_count = sum(1 for record in records if record["status"] == "ok")
    print(f"downloaded_or_present={ok_count} total_requested={len(keys)} manifest={args.manifest}")
    if args.strict and ok_count != len(keys):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

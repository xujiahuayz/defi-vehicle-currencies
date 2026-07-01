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
import os
import re
import signal
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_REPO_ROOT / "src"))

from ddvc.paths import (  # noqa: E402
    LITERATURE_BIB,
    LITERATURE_DIR,
    LITERATURE_DOWNLOAD_MANIFEST,
    LITERATURE_PAPERS_DIR,
    LITERATURE_PDF_SOURCES,
    REPO_ROOT,
)


PROFILE_DIR = LITERATURE_DIR / "auth" / "browser-profile"


class SourceTimeout(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    key: str
    kind: str
    fields: dict[str, str]


@dataclass(frozen=True)
class Source:
    url: str
    version: str
    access: str = "unknown"
    label: str = ""


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


def parse_bibtex(path: Path) -> dict[str, Entry]:
    text = path.read_text(encoding="utf-8")
    entries: dict[str, Entry] = {}
    for match in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)\n\}", text, re.S):
        kind = match.group(1).strip().lower()
        key = match.group(2).strip()
        body = match.group(3)
        fields: dict[str, str] = {}
        for field in re.finditer(r"^\s*([A-Za-z]+)\s*=\s*\{(.*?)\}\s*,?\s*$", body, re.M):
            fields[field.group(1).lower()] = field.group(2).strip()
        entries[key] = Entry(key=key, kind=kind, fields=fields)
    return entries


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_sources(path: Path) -> tuple[str | None, dict[str, list[Source]]]:
    data = load_json(path)
    result: dict[str, list[Source]] = {}
    for key, raw_sources in data.get("sources", {}).items():
        result[key] = [
            Source(
                url=str(raw["url"]),
                version=str(raw.get("version", "unknown")),
                access=str(raw.get("access", "unknown")),
                label=str(raw.get("label", "")),
            )
            for raw in raw_sources
        ]
    openathens = data.get("openathens")
    return str(openathens) if openathens else None, result


def default_sources_from_bib(entry: Entry) -> list[Source]:
    doi = entry.fields.get("doi")
    if not doi:
        return []
    doi_l = doi.lower()
    version = "working-paper" if doi_l.startswith(("10.3386/", "10.59576/")) or entry.kind == "techreport" else "published"
    return [Source(url=f"https://doi.org/{doi}", version=version, access="authenticated", label="DOI resolver")]


def openathens_url(url: str, domain: str) -> str:
    return f"https://go.openathens.net/redirector/{domain}?url={urllib.parse.quote(url, safe='')}"


def with_openathens(sources: list[Source], domain: str | None) -> list[Source]:
    expanded: list[Source] = []
    for source in sources:
        if domain and source.version == "published" and source.url.startswith("http"):
            expanded.append(
                Source(
                    url=openathens_url(source.url, domain),
                    version=source.version,
                    access="institutional",
                    label=f"OpenAthens {domain}: {source.label}",
                )
            )
        expanded.append(source)
    return expanded


def ordered_sources(sources: list[Source], prefer: str) -> list[Source]:
    if prefer == "published":
        priority = {"published": 0, "accepted": 1, "working-paper": 2, "preprint": 3, "whitepaper": 4}
    else:
        priority = {"working-paper": 0, "preprint": 1, "published": 2, "accepted": 3, "whitepaper": 4}
    return sorted(sources, key=lambda source: priority.get(source.version, 50))


def safe_filename(entry: Entry, source: Source) -> str:
    year = entry.fields.get("year", "undated")
    title = entry.fields.get("title", entry.key)
    title = re.sub(r"[{}\\\\]", "", title)
    title = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    title = title[:80].strip("-")
    suffix = "" if source.version == "published" else f"-{source.version}"
    return f"{year}-{entry.key}{suffix}-{title}.pdf"


def is_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF")


@contextlib.contextmanager
def source_deadline(timeout_ms: int):
    if timeout_ms <= 0:
        yield
        return

    def raise_timeout(_signum, _frame):
        raise SourceTimeout(f"source exceeded {timeout_ms}ms")

    old_handler = signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_ms / 1000)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def write_pdf(path: Path, data: bytes, overwrite: bool) -> str:
    if path.exists() and not overwrite:
        return "exists"
    tmp = path.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return f"{len(data)} bytes"


def existing_files_for_key(out_dir: Path, key: str) -> list[Path]:
    return sorted(out_dir.glob(f"*-{key}*.pdf"))


def file_version(path: Path) -> str:
    for version in ["working-paper", "preprint", "accepted", "whitepaper"]:
        if f"-{version}-" in path.name:
            return version
    return "published"


def should_replace_existing(existing: list[Path], source: Source, overwrite: bool) -> bool:
    if overwrite or not existing:
        return True
    return source.version == "published" and all(file_version(path) in {"working-paper", "preprint", "accepted"} for path in existing)


def remove_weaker_versions(existing: list[Path], source_version: str, target: Path) -> None:
    if source_version != "published":
        return
    for path in existing:
        if path != target and file_version(path) in {"working-paper", "preprint", "accepted"}:
            path.unlink()


def pdf_from_response(response: Any) -> bytes | None:
    try:
        data = response.body()
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
    navigation_url = jstor_article_url(url) or url

    def remember_response(response: Any) -> None:
        responses.append(response)

    page.on("response", remember_response)
    try:
        with page.expect_download(timeout=5000) as download_info:
            response = goto_page(page, navigation_url, timeout_ms)
        download = download_info.value
        path = download.path()
        if path:
            data = Path(path).read_bytes()
            if is_pdf(data):
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
                path = download.path()
                if path:
                    data = Path(path).read_bytes()
                    if is_pdf(data):
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
    parser.add_argument("--timeout-ms", type=int, default=90000)
    parser.add_argument("--source-timeout-ms", type=int, default=120000)
    parser.add_argument("--username-env", default="UCL_USER")
    parser.add_argument("--password-env", default="UCL_PW")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    username = os.environ.get(args.username_env)
    password = os.environ.get(args.password_env)

    sync_playwright, _ = import_playwright()
    entries = parse_bibtex(args.bib)
    openathens_domain, source_map = load_sources(args.sources)
    keys = list(entries)
    if args.key:
        wanted = set(args.key)
        keys = [key for key in keys if key in wanted]
    if args.limit:
        keys = keys[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    args.profile.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    with sync_playwright() as p:
        kwargs: dict[str, Any] = {
            "user_data_dir": str(args.profile),
            "headless": args.headless,
            "accept_downloads": True,
            "viewport": {"width": 1400, "height": 1000},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if args.channel:
            kwargs["channel"] = args.channel
        ctx = p.chromium.launch_persistent_context(**kwargs)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
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
                    target = args.out / safe_filename(entry, source)
                    existing = existing_files_for_key(args.out, key)
                    if existing and not should_replace_existing(existing, source, args.overwrite):
                        existing_file = existing[0]
                        remove_weaker_versions(existing, file_version(existing_file), existing_file)
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
                    try:
                        with source_deadline(args.source_timeout_ms):
                            data, detail = browser_fetch_pdf(page, source.url, args.timeout_ms, username, password)
                    except SourceTimeout as exc:
                        data, detail = None, str(exc)
                        try:
                            page.close()
                        except Exception:
                            pass
                        page = ctx.new_page()
                    if data:
                        remove_weaker_versions(existing, source.version, target)
                        saved = write_pdf(target, data, args.overwrite)
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
        finally:
            ctx.close()

    args.manifest.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ok_count = sum(1 for record in records if record["status"] == "ok")
    print(f"downloaded_or_present={ok_count} total_requested={len(keys)} manifest={args.manifest}")
    if args.strict and ok_count != len(keys):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

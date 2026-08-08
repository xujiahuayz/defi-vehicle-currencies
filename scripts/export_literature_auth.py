#!/usr/bin/env python3
"""Export browser cookies for authenticated literature downloads.

This opens a visible persistent browser profile at the PDF/source URLs listed
in literature/pdf-sources.json. After Java signs in or clears publisher checks,
the script writes domain Cookie headers to gitignored
literature/auth/headers.local.json. Then run:

    ./scripts/run scripts/fetch_literature.py --strict

Requires the optional auth dependency:

    python3 -m pip install '.[auth]'
    python3 -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from ddvc.literature_sources import openathens_url  # noqa: E402
from ddvc.paths import (  # noqa: E402
    LITERATURE_BIB,
    LITERATURE_AUTH_HEADERS,
    LITERATURE_DIR,
    LITERATURE_PDF_SOURCES,
)


PROFILE_DIR = LITERATURE_DIR / "auth" / "browser-profile"


def import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run: python3 -m pip install '.[auth]' "
            "&& python3 -m playwright install chromium"
        ) from exc
    return sync_playwright


def load_bib_doi_urls(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [f"https://doi.org/{doi}" for doi in sorted(set(re.findall(r"^\s*doi\s*=\s*\{([^}]+)\}", text, re.M)))]


def load_source_urls(path: Path, *, version: str | None) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    urls: list[str] = []
    for sources in data.get("sources", {}).values():
        for source in sources:
            if version and str(source.get("version")) != version:
                continue
            url = str(source["url"])
            if url.startswith("http"):
                urls.append(url)
    return sorted(set(urls))


def load_openathens_domain(path: Path) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("openathens")
    return str(value) if value else None


def host_for(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def cookie_header(cookies: list[dict[str, Any]], host: str) -> str:
    matching = []
    for cookie in cookies:
        domain = str(cookie.get("domain", "")).lstrip(".")
        if host == domain or host.endswith("." + domain):
            matching.append(cookie)
    matching.sort(key=lambda cookie: (str(cookie.get("domain", "")), str(cookie.get("path", "")), str(cookie.get("name", ""))))
    return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in matching if cookie.get("name"))


def write_headers(path: Path, urls: list[str], cookies: list[dict[str, Any]], user_agent: str | None) -> None:
    domains: dict[str, dict[str, str]] = {}
    for host in sorted({host_for(url) for url in urls}):
        header = cookie_header(cookies, host)
        if header:
            domains[host] = {"Cookie": header}
    headers = {"User-Agent": user_agent} if user_agent else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"headers": headers, "domains": domains}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bib", type=Path, default=LITERATURE_BIB)
    parser.add_argument("--sources", type=Path, default=LITERATURE_PDF_SOURCES)
    parser.add_argument("--out", type=Path, default=LITERATURE_AUTH_HEADERS)
    parser.add_argument("--profile", type=Path, default=PROFILE_DIR)
    parser.add_argument("--hold-seconds", type=int, default=240)
    parser.add_argument("--limit", type=int, default=0, help="Open only the first N unique source URLs; 0 means all.")
    parser.add_argument("--channel", default="chrome", help="Browser channel; use chrome for publisher WAFs when available.")
    parser.add_argument("--version", default="published", help="Source-map version filter; empty string opens all source-map URLs.")
    args = parser.parse_args()

    version = args.version or None
    urls = sorted(set([*load_bib_doi_urls(args.bib), *load_source_urls(args.sources, version=version)]))
    openathens_domain = load_openathens_domain(args.sources)
    if openathens_domain:
        urls = sorted(set([*urls, *(openathens_url(url, openathens_domain) for url in urls)]))
    if args.limit:
        urls = urls[: args.limit]

    sync_playwright = import_playwright()
    args.profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        kwargs: dict[str, Any] = {
            "user_data_dir": str(args.profile),
            "headless": False,
            "viewport": {"width": 1400, "height": 1000},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if args.channel:
            kwargs["channel"] = args.channel
        ctx = p.chromium.launch_persistent_context(**kwargs)
        try:
            for url in urls:
                print(f"open {url}", flush=True)
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as exc:  # noqa: BLE001 - keep opening remaining auth surfaces.
                    print(f"open-failed {url}: {type(exc).__name__}: {exc}", flush=True)
            print(f"Browser open for {args.hold_seconds}s. Sign in/clear checks, then wait.", flush=True)
            time.sleep(args.hold_seconds)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            user_agent = page.evaluate("navigator.userAgent")
            cookies = ctx.cookies()
        finally:
            ctx.close()

    write_headers(args.out, urls, cookies, user_agent)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

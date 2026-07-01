#!/usr/bin/env python3
"""Discover registered PDF source URLs from DOI metadata APIs.

The script is deterministic with respect to committed bibliography input plus
API responses. It currently uses Crossref `link` metadata to find publisher-
registered PDF resources, then optionally merges them into
literature/pdf-sources.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_REPO_ROOT / "src"))

from ddvc.http import DEFAULT_USER_AGENT  # noqa: E402
from ddvc.paths import LITERATURE_BIB, LITERATURE_PDF_SOURCES  # noqa: E402


def parse_bibtex_dois(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for match in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)\n\}", text, re.S):
        body = match.group(3)
        doi = re.search(r"^\s*doi\s*=\s*\{([^}]+)\}", body, re.M)
        if doi:
            result[match.group(2).strip()] = doi.group(1).strip()
    return result


def user_agent() -> str:
    mailto = os.environ.get("CROSSREF_MAILTO")
    suffix = f" (mailto:{mailto})" if mailto else ""
    return f"{DEFAULT_USER_AGENT}{suffix}"


def crossref_work(doi: str) -> dict[str, Any]:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["message"]


def is_pdf_link(link: dict[str, Any]) -> bool:
    haystack = " ".join(str(link.get(field, "")) for field in ["URL", "content-type", "intended-application"]).lower()
    return "pdf" in haystack


def normalized_url(url: str) -> str:
    if url.startswith("http://academic.oup.com/") or url.startswith("http://www.journals.uchicago.edu/"):
        return "https://" + url.removeprefix("http://")
    return url


def source_from_link(link: dict[str, Any]) -> dict[str, str]:
    content_version = str(link.get("content-version", "")).lower()
    version = "published" if content_version == "vor" else "accepted" if content_version == "am" else "published"
    application = str(link.get("intended-application", "registered PDF"))
    return {
        "url": normalized_url(str(link["URL"])),
        "version": version,
        "access": "authenticated",
        "label": f"Crossref {application}",
    }


def discover_sources(dois_by_key: dict[str, str], delay: float) -> dict[str, list[dict[str, str]]]:
    discovered: dict[str, list[dict[str, str]]] = {}
    for key, doi in dois_by_key.items():
        try:
            links = crossref_work(doi).get("link") or []
        except Exception as exc:  # noqa: BLE001 - keep inspecting the rest.
            print(f"warn {key}: {doi}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        sources = [source_from_link(link) for link in links if link.get("URL") and is_pdf_link(link)]
        seen: set[tuple[str, str]] = set()
        for source in sources:
            marker = (source["url"], source["version"])
            if marker in seen:
                continue
            seen.add(marker)
            discovered.setdefault(key, []).append(source)
        time.sleep(delay)
    return discovered


def merge_source_map(path: Path, discovered: dict[str, list[dict[str, str]]]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("sources", {})
    for key, sources in discovered.items():
        existing = data["sources"].setdefault(key, [])
        existing_urls = {source["url"] for source in existing}
        for source in sources:
            if source["url"] not in existing_urls:
                existing.insert(0, source)
                existing_urls.add(source["url"])
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bib", type=Path, default=LITERATURE_BIB)
    parser.add_argument("--sources", type=Path, default=LITERATURE_PDF_SOURCES)
    parser.add_argument("--write", action="store_true", help="Merge discovered URLs into literature/pdf-sources.json.")
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    discovered = discover_sources(parse_bibtex_dois(args.bib), args.delay)
    print(json.dumps({"sources": discovered}, indent=2, sort_keys=True))
    if args.write:
        merge_source_map(args.sources, discovered)
        print(f"updated {args.sources}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

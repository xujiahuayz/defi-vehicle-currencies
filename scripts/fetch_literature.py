#!/usr/bin/env python3
"""Fetch literature PDFs reproducibly from a committed source map.

Inputs committed to the repo:
  - literature/vehicle-currencies.bib
  - literature/pdf-sources.json

Local-only inputs, never committed:
  - literature/auth/headers.local.json
  - literature/sources.local.json

Outputs, never committed:
  - literature/papers/*.pdf
  - literature/papers/download-manifest.json

The script is deterministic: it does not search the web at run time. Add or
change PDF locations in literature/pdf-sources.json, and put auth/cookie
material in literature/auth/headers.local.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_REPO_ROOT / "src"))

from ddvc.http import DEFAULT_USER_AGENT  # noqa: E402
from ddvc.paths import (  # noqa: E402
    LITERATURE_AUTH_HEADERS,
    LITERATURE_BIB,
    LITERATURE_DOWNLOAD_MANIFEST,
    LITERATURE_LOCAL_SOURCES,
    LITERATURE_PAPERS_DIR,
    LITERATURE_PDF_SOURCES,
    REPO_ROOT,
)


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
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_sources(path: Path) -> dict[str, list[Source]]:
    data = load_json(path)
    result: dict[str, list[Source]] = {}
    for key, raw_sources in data.get("sources", {}).items():
        sources: list[Source] = []
        for raw in raw_sources:
            sources.append(
                Source(
                    url=str(raw["url"]),
                    version=str(raw.get("version", "unknown")),
                    access=str(raw.get("access", "unknown")),
                    label=str(raw.get("label", "")),
                )
            )
        result[key] = sources
    return result


def merge_sources(*maps: dict[str, list[Source]]) -> dict[str, list[Source]]:
    merged: dict[str, list[Source]] = {}
    for source_map in maps:
        for key, sources in source_map.items():
            merged.setdefault(key, []).extend(sources)
    return merged


def load_local_source_overlay(path: Path) -> dict[str, list[Source]]:
    data = load_json(path)
    result: dict[str, list[Source]] = {}
    for key, value in data.get("sources", {}).items():
        raw_items = value if isinstance(value, list) else [value]
        sources: list[Source] = []
        for item in raw_items:
            if isinstance(item, str):
                sources.append(Source(url=item, version="local", access="local-auth", label="local"))
            else:
                sources.append(
                    Source(
                        url=str(item["url"]),
                        version=str(item.get("version", "local")),
                        access=str(item.get("access", "local-auth")),
                        label=str(item.get("label", "local")),
                    )
                )
        result[key] = sources
    return result


def load_auth_headers(path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    data = load_json(path)
    global_headers = {str(k): str(v) for k, v in data.get("headers", {}).items()}
    domain_headers = {
        str(domain): {str(k): str(v) for k, v in headers.items()}
        for domain, headers in data.get("domains", {}).items()
    }
    return global_headers, domain_headers


def headers_for(url: str, global_headers: dict[str, str], domain_headers: dict[str, dict[str, str]]) -> dict[str, str]:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/pdf,*/*",
    }
    headers.update(global_headers)
    host = urllib.parse.urlparse(url).netloc
    for domain, extra in domain_headers.items():
        if host == domain or host.endswith("." + domain):
            headers.update(extra)
    return headers


def safe_filename(entry: Entry, source: Source) -> str:
    year = entry.fields.get("year", "undated")
    title = entry.fields.get("title", entry.key)
    title = re.sub(r"[{}\\\\]", "", title)
    title = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    title = title[:80].strip("-")
    suffix = "" if source.version == "published" else f"-{source.version}"
    return f"{year}-{entry.key}{suffix}-{title}.pdf"


def request(url: str, headers: dict[str, str]) -> urllib.request.Request:
    return urllib.request.Request(url, headers=headers)


def is_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF")


def download(url: str, target: Path, headers: dict[str, str], overwrite: bool) -> tuple[bool, str]:
    if target.exists() and not overwrite:
        return True, "exists"
    with urllib.request.urlopen(request(url, headers), timeout=120) as response:
        data = response.read()
    if not is_pdf(data):
        return False, "not-pdf"
    tmp = target.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    return True, f"{len(data)} bytes"


def ordered_sources(sources: list[Source], prefer: str) -> list[Source]:
    if prefer == "published":
        priority = {"published": 0, "accepted": 1, "working-paper": 2, "preprint": 3, "whitepaper": 4}
    elif prefer == "working":
        priority = {"working-paper": 0, "preprint": 1, "published": 2, "accepted": 3, "whitepaper": 4}
    else:
        priority = {}
    return sorted(sources, key=lambda source: priority.get(source.version, 50))


def default_sources_from_bib(entry: Entry) -> list[Source]:
    sources: list[Source] = []
    doi = entry.fields.get("doi")
    if doi:
        doi_l = doi.lower()
        version = "working-paper" if doi_l.startswith(("10.3386/", "10.59576/")) or entry.kind == "techreport" else "published"
        sources.append(
            Source(
                url=f"https://doi.org/{doi}",
                version=version,
                access="authenticated",
                label="DOI resolver",
            )
        )
    url = entry.fields.get("url")
    if url and url.startswith("http") and (not doi or doi not in url):
        sources.append(Source(url=url, version="listed", access="unknown", label="BibTeX URL"))
    return sources


def fetch_all(
    entries: dict[str, Entry],
    sources_by_key: dict[str, list[Source]],
    out_dir: Path,
    manifest_path: Path,
    global_headers: dict[str, str],
    domain_headers: dict[str, dict[str, str]],
    prefer: str,
    overwrite: bool,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for key, entry in entries.items():
        sources = ordered_sources([*default_sources_from_bib(entry), *sources_by_key.get(key, [])], prefer)
        if not sources:
            print(f"skip {key}: no source in literature/pdf-sources.json")
            records.append({"key": key, "status": "no-source"})
            continue

        for index, source in enumerate(sources, start=1):
            target = out_dir / safe_filename(entry, source)
            headers = headers_for(source.url, global_headers, domain_headers)
            try:
                ok, detail = download(source.url, target, headers, overwrite)
            except urllib.error.HTTPError as exc:
                detail = f"HTTP {exc.code}"
                print(f"try {key} [{index}/{len(sources)}] {source.version}: {detail} {source.url}")
            except Exception as exc:  # noqa: BLE001 - keep trying the source list.
                detail = f"{type(exc).__name__}: {exc}"
                print(f"try {key} [{index}/{len(sources)}] {source.version}: {detail} {source.url}")
            else:
                if ok:
                    print(f"ok {key}: {target.relative_to(REPO_ROOT)} ({source.version}, {detail})")
                    records.append(
                        {
                            "key": key,
                            "status": "ok",
                            "file": str(target.relative_to(REPO_ROOT)),
                            "version": source.version,
                            "access": source.access,
                            "url": source.url,
                        }
                    )
                    break
                print(f"try {key} [{index}/{len(sources)}] {source.version}: {detail} {source.url}")
            time.sleep(0.2)
        else:
            records.append({"key": key, "status": "miss", "sources": [source.__dict__ for source in sources]})

    manifest_path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bib", type=Path, default=LITERATURE_BIB)
    parser.add_argument("--sources", type=Path, default=LITERATURE_PDF_SOURCES)
    parser.add_argument("--local-sources", type=Path, default=LITERATURE_LOCAL_SOURCES)
    parser.add_argument("--auth", type=Path, default=LITERATURE_AUTH_HEADERS)
    parser.add_argument("--out", type=Path, default=LITERATURE_PAPERS_DIR)
    parser.add_argument("--manifest", type=Path, default=LITERATURE_DOWNLOAD_MANIFEST)
    parser.add_argument("--prefer", choices=["published", "working", "listed"], default="published")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero unless every BibTeX entry has a PDF.")
    args = parser.parse_args()

    entries = parse_bibtex(args.bib)
    committed_sources = load_sources(args.sources)
    local_sources = load_local_source_overlay(args.local_sources)
    global_headers, domain_headers = load_auth_headers(args.auth)
    records = fetch_all(
        entries,
        merge_sources(local_sources, committed_sources),
        args.out,
        args.manifest,
        global_headers,
        domain_headers,
        args.prefer,
        args.overwrite,
    )

    ok_count = sum(1 for record in records if record["status"] == "ok")
    print(f"downloaded_or_present={ok_count} total_entries={len(entries)} manifest={args.manifest}")
    if args.strict and ok_count != len(entries):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

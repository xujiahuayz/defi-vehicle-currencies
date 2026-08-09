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
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ddvc.http import DEFAULT_USER_AGENT  # noqa: E402
from ddvc.literature_admission import load_source_admission, require_source_admission  # noqa: E402
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
    ordered_sources,
    parse_bibtex,
    partition_existing_by_identity,
    preferred_existing_file,
    remove_local_and_mirrored,
    remove_weaker_versions,
    safe_filename,
    should_replace_existing,
    source_keys_lock,
    write_manifest_records,
    with_openathens,
)
from ddvc.paths import (  # noqa: E402
    LITERATURE_AUTH_HEADERS,
    LITERATURE_BIB,
    LITERATURE_DOWNLOAD_MANIFEST,
    LITERATURE_LOCAL_SOURCES,
    LITERATURE_PAPERS_DIR,
    LITERATURE_PDF_SOURCES,
    LITERATURE_SOURCE_ADMISSION,
    REPO_ROOT,
)

def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
    parsed = urllib.parse.urlparse(url)
    if host == "onlinelibrary.wiley.com" and parsed.path == "/action/downloadSupplement":
        doi = urllib.parse.parse_qs(parsed.query).get("doi", [""])[0]
        if doi:
            headers.setdefault("Referer", f"https://onlinelibrary.wiley.com/doi/{doi}")
    return headers


def request(url: str, headers: dict[str, str]) -> urllib.request.Request:
    return urllib.request.Request(url, headers=headers)


def download(
    url: str,
    target: Path,
    headers: dict[str, str],
    overwrite: bool,
    entry: Entry | None = None,
) -> tuple[bool, str]:
    if target.exists() and not overwrite:
        mirror_validated_pdf(target)
        return True, "exists"
    data = download_with_curl(url, headers)
    if not data or not is_pdf(data):
        with urllib.request.urlopen(request(url, headers), timeout=15) as response:
            data = read_response_with_deadline(response, timeout_seconds=120)
    if not is_pdf(data):
        return False, "not-pdf"
    return True, install_pdf(target, data, overwrite, entry=entry)


def read_response_with_deadline(
    response: Any,
    *,
    timeout_seconds: float,
) -> bytes:
    """Read one HTTP response incrementally under a total wall-clock deadline."""
    deadline = time.monotonic() + timeout_seconds
    chunks: list[bytes] = []
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"direct download exceeded {timeout_seconds:g}s")
        chunk = response.read1(1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def download_with_curl(url: str, headers: dict[str, str]) -> bytes | None:
    curl = shutil.which("curl")
    if not curl:
        return None
    command = [
        curl,
        "--http1.1",
        "-L",
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        "120",
    ]
    for name, value in headers.items():
        command.extend(["-H", f"{name}: {value}"])
    command.append(url)
    try:
        result = subprocess.run(command, check=True, capture_output=True)
    except subprocess.SubprocessError:
        return None
    return result.stdout


def fetch_all(
    entries: dict[str, Entry],
    sources_by_key: dict[str, list[Source]],
    openathens_domain: str | None,
    out_dir: Path,
    global_headers: dict[str, str],
    domain_headers: dict[str, dict[str, str]],
    prefer: str,
    overwrite: bool,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for key, entry in entries.items():
        sources = [
            *ordered_sources(with_openathens(sources_by_key.get(key, []), openathens_domain), prefer),
            *ordered_sources(with_openathens(default_sources_from_bib(entry), openathens_domain), prefer),
        ]
        attempts: list[dict[str, Any]] = []
        if not sources:
            print(f"skip {key}: no source in literature/pdf-sources.json")
            records.append({"key": key, "status": "no-source"})
            continue

        for index, source in enumerate(sources, start=1):
            target = out_dir / safe_filename(
                entry.key,
                entry.fields.get("year", "undated"),
                entry.fields.get("title", entry.key),
                source,
            )
            existing = existing_files_for_key(out_dir, key)
            existing, rejected = partition_existing_by_identity(existing, entry)
            for rejected_path, reason in rejected:
                print(f"reject {key}: {rejected_path.relative_to(REPO_ROOT)} ({reason})")
            if existing and not should_replace_existing(existing, source, overwrite):
                existing_file = preferred_existing_file(existing)
                remove_weaker_versions(existing, file_version(existing_file), existing_file)
                mirror_validated_pdf(existing_file)
                detail = "exists"
                print(f"ok {key}: {existing_file.relative_to(REPO_ROOT)} ({file_version(existing_file)}, {detail})")
                records.append(
                    {
                        "key": key,
                        "status": "ok",
                        "file": str(existing_file.relative_to(REPO_ROOT)),
                        "version": file_version(existing_file),
                        "access": source.access,
                        "url": source.url,
                        "attempts": [attempt_record(source, detail, ok=True)],
                    }
                )
                break
            headers = headers_for(source.url, global_headers, domain_headers)
            try:
                ok, detail = download(
                    source.url,
                    target,
                    headers,
                    overwrite or any(path == target for path, _ in rejected),
                    entry,
                )
            except urllib.error.HTTPError as exc:
                detail = f"HTTP {exc.code}"
                attempts.append(attempt_record(source, detail))
                print(f"try {key} [{index}/{len(sources)}] {source.version}: {detail} {source.url}")
            except Exception as exc:  # noqa: BLE001 - keep trying the source list.
                detail = f"{type(exc).__name__}: {exc}"
                attempts.append(attempt_record(source, detail))
                print(f"try {key} [{index}/{len(sources)}] {source.version}: {detail} {source.url}")
            else:
                if ok:
                    remove_local_and_mirrored(
                        (path for path, _ in rejected),
                        keep=target,
                    )
                    remove_weaker_versions(existing, source.version, target)
                    print(f"ok {key}: {target.relative_to(REPO_ROOT)} ({source.version}, {detail})")
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
                print(f"try {key} [{index}/{len(sources)}] {source.version}: {detail} {source.url}")
            time.sleep(0.2)
        else:
            records.append(
                {
                    "key": key,
                    "status": "miss",
                    "sources": [source.__dict__ for source in sources],
                    "attempts": attempts,
                }
            )

    return records


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
    parser.add_argument("--admission", type=Path, default=LITERATURE_SOURCE_ADMISSION)
    parser.add_argument("--local-sources", type=Path, default=LITERATURE_LOCAL_SOURCES)
    parser.add_argument("--auth", type=Path, default=LITERATURE_AUTH_HEADERS)
    parser.add_argument("--out", type=Path, default=LITERATURE_PAPERS_DIR)
    parser.add_argument("--manifest", type=Path, default=LITERATURE_DOWNLOAD_MANIFEST)
    parser.add_argument("--prefer", choices=["published", "working", "listed"], default="published")
    parser.add_argument("--key", action="append", help="Fetch only this BibTeX key; repeatable.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero unless every BibTeX entry has a PDF.")
    args = parser.parse_args()

    entries = parse_bibtex(args.bib)
    if args.key:
        wanted = set(args.key)
        entries = {key: entry for key, entry in entries.items() if key in wanted}
    require_source_admission(entries, load_source_admission(args.admission))
    openathens_domain, committed_sources = load_source_registry(args.sources)
    local_sources = load_local_source_overlay(args.local_sources)
    global_headers, domain_headers = load_auth_headers(args.auth)
    with source_keys_lock(entries):
        records = fetch_all(
            entries,
            merge_sources(local_sources, committed_sources),
            openathens_domain,
            args.out,
            global_headers,
            domain_headers,
            args.prefer,
            args.overwrite,
        )
        write_manifest_records(args.manifest, records, merge=bool(args.key))

    ok_count = sum(1 for record in records if record["status"] == "ok")
    print(f"downloaded_or_present={ok_count} total_entries={len(entries)} manifest={args.manifest}")
    if args.strict and ok_count != len(entries):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

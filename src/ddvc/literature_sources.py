"""Shared literature-source access routing for direct and browser fetchers."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import re
import urllib.parse
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ddvc.paths import PRIMARY_REPO_ROOT, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import atomic_output


WEAKER_VERSIONS = frozenset({"working-paper", "preprint", "accepted"})
TITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)


@dataclass(frozen=True)
class Source:
    url: str
    version: str
    access: str = "unknown"
    label: str = ""


@dataclass(frozen=True)
class Entry:
    key: str
    kind: str
    fields: dict[str, str]


def parse_bibtex(path: Path) -> dict[str, Entry]:
    """Parse the repository's deliberately simple braced-field BibTeX format."""
    text = path.read_text(encoding="utf-8")
    entries: dict[str, Entry] = {}
    for match in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)\n\}", text, re.S):
        kind = match.group(1).strip().lower()
        key = match.group(2).strip()
        body = match.group(3)
        fields = {
            field.group(1).lower(): field.group(2).strip()
            for field in re.finditer(
                r"^\s*([A-Za-z]+)\s*=\s*\{(.*?)\}\s*,?\s*$",
                body,
                re.M,
            )
        }
        entries[key] = Entry(key=key, kind=kind, fields=fields)
    return entries


def load_source_registry(path: Path) -> tuple[str | None, dict[str, list[Source]]]:
    """Load the institutional domain and committed per-key acquisition routes."""
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    sources = {
        str(key): [
            Source(
                url=str(raw["url"]),
                version=str(raw.get("version", "unknown")),
                access=str(raw.get("access", "unknown")),
                label=str(raw.get("label", "")),
            )
            for raw in raw_sources
        ]
        for key, raw_sources in data.get("sources", {}).items()
    }
    domain = data.get("openathens")
    return (str(domain) if domain else None), sources


def default_sources_from_bib(entry: Entry) -> list[Source]:
    """Derive deterministic DOI and listed-URL fallbacks from one bibliography entry."""
    sources: list[Source] = []
    doi = entry.fields.get("doi")
    if doi:
        doi_l = doi.lower()
        version = (
            "working-paper"
            if doi_l.startswith(("10.3386/", "10.59576/")) or entry.kind == "techreport"
            else "published"
        )
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
        sources.append(
            Source(
                url=url,
                version="listed",
                access="unknown",
                label="BibTeX URL",
            )
        )
    return sources


def ordered_sources(sources: list[Source], prefer: str) -> list[Source]:
    """Apply the same version preference in every acquisition transport."""
    if prefer == "published":
        priority = {
            "published": 0,
            "supplement": 1,
            "accepted": 2,
            "working-paper": 3,
            "preprint": 4,
            "whitepaper": 5,
        }
    elif prefer == "working":
        priority = {
            "working-paper": 0,
            "preprint": 1,
            "published": 2,
            "supplement": 3,
            "accepted": 4,
            "whitepaper": 5,
        }
    else:
        priority = {}
    return sorted(sources, key=lambda source: priority.get(source.version, 50))


@contextmanager
def source_keys_lock(keys: Iterable[str]) -> Iterator[None]:
    """Serialize overlapping fetch sets while allowing disjoint source sets in parallel."""
    SHARED_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    locks = []
    try:
        for key in sorted(set(keys)):
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
            lock_path = SHARED_RUNTIME_DIR / f"literature-source-{digest}.lock"
            lock = lock_path.open("a+", encoding="utf-8")
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            locks.append(lock)
        yield
    finally:
        for lock in reversed(locks):
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()


def openathens_url(url: str, domain: str) -> str:
    return f"https://go.openathens.net/redirector/{domain}?url={urllib.parse.quote(url, safe='')}"


def with_openathens(sources: list[Source], domain: str | None) -> list[Source]:
    """Prepend institutional fallbacks only for sources that may require authentication."""
    if not domain:
        return sources
    expanded: list[Source] = []
    for source in sources:
        if (
            source.version == "published"
            and source.access not in {"public", "institutional"}
            and source.url.startswith("http")
        ):
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


def safe_filename(key: str, year: str, title: str, source: Source) -> str:
    """Canonical filename shared by direct and browser acquisition."""
    slug = re.sub(r"[{}\\\\]", "", title)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-").lower()
    slug = slug[:80].strip("-")
    suffix = "" if source.version == "published" else f"-{source.version}"
    return f"{year}-{key}{suffix}-{slug}.pdf"


def is_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF")


def _identity_words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", re.sub(r"[{}\\]", " ", value.lower()))


def _author_surnames(author_field: str) -> set[str]:
    surnames: set[str] = set()
    for author in re.split(r"\s+and\s+", author_field, flags=re.IGNORECASE):
        words = _identity_words(author.partition(",")[0] if "," in author else author)
        if words:
            surnames.add(words[0] if "," in author else words[-1])
    return surnames


def source_identity_verdict(
    entry: Entry,
    extracted_text: str,
    *,
    byline_text: str | None = None,
) -> tuple[bool, str]:
    """Require title overlap and every bibliography surname in the byline window."""
    observed = set(_identity_words(extracted_text))
    byline_observed = set(_identity_words(byline_text if byline_text is not None else extracted_text))
    title_words = {
        word
        for word in _identity_words(entry.fields.get("title", entry.key))
        if len(word) >= 3 and word not in TITLE_STOPWORDS
    }
    author_surnames = _author_surnames(entry.fields.get("author", ""))
    title_hits = len(title_words & observed)
    title_required = max(1, (len(title_words) + 1) // 2)
    author_hits = author_surnames & byline_observed
    missing_authors = author_surnames - author_hits
    passed = bool(
        title_hits >= title_required
        and author_surnames
        and not missing_authors
    )
    return passed, (
        f"title={title_hits}/{len(title_words)} (required={title_required}); "
        f"author={len(author_hits)}/{len(author_surnames)}"
        f" (missing={','.join(sorted(missing_authors)) or 'none'})"
    )


def pdf_identity_verdict(data: bytes, entry: Entry, *, page_limit: int = 5) -> tuple[bool, str]:
    """Verify title and complete bibliography byline within a bounded PDF header."""
    if not is_pdf(data):
        return False, "not-pdf"
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages[:page_limit]]
        extracted = "\n".join(pages)
        byline = "\n".join(pages[:2])
    except Exception as exc:  # invalid or image-only sources need a manual verified route
        return False, f"identity-extraction-{type(exc).__name__}"
    return source_identity_verdict(entry, extracted, byline_text=byline)


def partition_existing_by_identity(
    existing: Iterable[Path],
    entry: Entry,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Separate reusable literature PDFs from wrong or unverifiable artifacts."""
    valid: list[Path] = []
    invalid: list[tuple[Path, str]] = []
    for path in existing:
        passed, detail = pdf_identity_verdict(path.read_bytes(), entry)
        if passed:
            valid.append(path)
        else:
            invalid.append((path, detail))
    return valid, invalid


def existing_files_for_key(out_dir: Path, key: str) -> list[Path]:
    """Return only files whose canonical filename contains the exact bibliography key."""
    return sorted(out_dir.glob(f"*-{key}-*.pdf"))


def file_version(path: Path) -> str:
    match = re.match(
        r"^[^-]+-[^-]+-(accepted|working-paper|preprint|whitepaper|supplement)-",
        path.name,
    )
    if match:
        return match.group(1)
    return "published"


def should_replace_existing(existing: list[Path], source: Source, overwrite: bool) -> bool:
    if overwrite or not existing:
        return True
    return source.version == "published" and all(file_version(path) in WEAKER_VERSIONS for path in existing)


def preferred_existing_file(existing: list[Path]) -> Path:
    """Choose the strongest installed version when more than one copy survives."""
    priority = {"published": 0, "supplement": 1, "accepted": 2, "working-paper": 3, "preprint": 4, "whitepaper": 5}
    return min(existing, key=lambda path: (priority.get(file_version(path), 50), path.name))


def primary_mirror_path(
    path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    primary_root: Path = PRIMARY_REPO_ROOT,
) -> Path | None:
    """Map a literature PDF in a worktree to the same path in the primary checkout."""
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None
    if relative.parts[:2] != ("literature", "papers") or primary_root.resolve() == repo_root.resolve():
        return None
    return primary_root / relative


def mirror_validated_pdf(
    path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    primary_root: Path = PRIMARY_REPO_ROOT,
) -> Path | None:
    """Atomically mirror a validated worktree PDF into the primary checkout."""
    data = path.read_bytes()
    if not is_pdf(data):
        raise ValueError(f"not a PDF: {path}")
    mirror = primary_mirror_path(path, repo_root=repo_root, primary_root=primary_root)
    if mirror is None:
        return None
    if mirror.exists() and mirror.read_bytes() == data:
        return mirror
    mirror.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(mirror) as temporary:
        temporary.write_bytes(data)
    return mirror


def install_pdf(
    path: Path,
    data: bytes,
    overwrite: bool,
    *,
    entry: Entry | None = None,
    repo_root: Path = REPO_ROOT,
    primary_root: Path = PRIMARY_REPO_ROOT,
) -> str:
    """Validate, atomically install, and primary-mirror one literature PDF."""
    if not is_pdf(data):
        raise ValueError("source payload is not a PDF")
    if entry is not None:
        matched, detail = pdf_identity_verdict(data, entry)
        if not matched:
            raise ValueError(f"source PDF identity mismatch for {entry.key}: {detail}")
    if path.exists() and not overwrite:
        mirror_validated_pdf(path, repo_root=repo_root, primary_root=primary_root)
        return "exists"
    with atomic_output(path) as temporary:
        temporary.write_bytes(data)
    mirror_validated_pdf(path, repo_root=repo_root, primary_root=primary_root)
    return f"{len(data)} bytes"


def remove_local_and_mirrored(
    paths: Iterable[Path],
    *,
    keep: Path,
    repo_root: Path = REPO_ROOT,
    primary_root: Path = PRIMARY_REPO_ROOT,
) -> list[Path]:
    """Remove verified-invalid or superseded files from both literature mirrors."""
    removed: list[Path] = []
    for path in paths:
        if path == keep:
            continue
        path.unlink(missing_ok=True)
        removed.append(path)
        mirror = primary_mirror_path(path, repo_root=repo_root, primary_root=primary_root)
        if mirror is not None and mirror.exists():
            mirror.unlink()
            removed.append(mirror)
    return removed


def remove_weaker_versions(
    existing: list[Path],
    source_version: str,
    target: Path,
    *,
    repo_root: Path = REPO_ROOT,
    primary_root: Path = PRIMARY_REPO_ROOT,
) -> list[Path]:
    """Remove superseded local and primary-mirror copies after a published source lands."""
    if source_version != "published":
        return []
    return remove_local_and_mirrored(
        (path for path in existing if file_version(path) in WEAKER_VERSIONS),
        keep=target,
        repo_root=repo_root,
        primary_root=primary_root,
    )


def write_manifest_records(
    path: Path,
    records: list[dict[str, Any]],
    *,
    merge: bool,
) -> list[dict[str, Any]]:
    """Install a manifest atomically, merging disjoint selective fetches under a process lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            by_key: dict[str, dict[str, Any]] = {}
            if merge and path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing = []
                if isinstance(existing, list):
                    by_key.update(
                        (str(record["key"]), record)
                        for record in existing
                        if isinstance(record, dict) and record.get("key")
                    )
            by_key.update(
                (str(record["key"]), record)
                for record in records
                if record.get("key")
            )
            installed = [by_key[key] for key in sorted(by_key)]
            with atomic_output(path) as temporary:
                temporary.write_text(json.dumps(installed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return installed
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

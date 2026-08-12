"""Provenance stamping so every derived artefact says what produced it.

Why this exists. The raw layer is already auditable: each fetched day carries a
`meta` sidecar with `fetched_at`, `head_block_at_fetch`, block range and row
counts. Everything downstream of it was not. No script recorded the commit or the
code that produced a panel, `data/empirical/` and `data/processed/` are
gitignored, and the `data/manifests/` directory the README promises held nothing
but a `.gitkeep`. The concrete cost of that gap: the route-cost day cache was
keyed on the calendar date alone, so fixing two real bugs in the V3 quoter
invalidated none of its 2,242 cached days, and they kept serving quotes from a
version that under-quoted tick-crossing upward swaps by a median 62.6% and priced
every pool at the 0.30% tier. The cache directory was manually labelled
`v3_exact_tick`, which is the right instinct implemented by hand, and hand-managed
invalidation fails silently: the label asserted a property the code did not have,
and nothing bumped it when the code changed.

The rule this module enforces. An artefact is reproducible only if you can tell,
mechanically, whether the code that produced it is still the code you have. So
every derived artefact gets a sidecar recording the git commit, whether the tree
was dirty, a fingerprint of the source files that can change the result, the
inputs it read, and the script and arguments that produced it. `verify` then
answers the only question that matters when reading a stale artefact: was this
built by the code I am looking at?

Fingerprints cover declared source and input state, not the environment. That is deliberate:
file hashes and input-tree metadata catch the observed stale-cache failures without a
container. Library versions are recorded for the record but not compared, since upgrading
pandas should not invalidate a panel whose numbers it does not change.
"""

from __future__ import annotations

import ast
import functools
import gzip
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ddvc.paths import REPO_ROOT
from ddvc.journaled_publication import (
    publish_journaled_bundle,
    recover_journaled_publications,
)
from ddvc.runtime import (
    atomic_output,
    file_sha256,
    serialized_output_installs,
    serialized_read_installs,
    staged_output,
)

ROOT = REPO_ROOT
MANIFESTS = ROOT / "data" / "manifests"

# Content-hash inputs up to this size; above it, identify by size and mtime. The
# raw layer runs to gigabytes per venue, and rehashing it on every build would
# make stamping expensive enough that people would switch it off.
CONTENT_HASH_MAX_BYTES = 64 * 1024 * 1024
GENERATED_PREFIXES = ("output/", "data/manifests/")


def portable_content_sha256(path: str | Path, *, content_encoding: str | None = None) -> str:
    """Hash a file's logical payload across hosts and compression implementations.

    Gzip container bytes can differ across Python, zlib, or operating-system builds
    even when the ordered decompressed payload is identical. Cross-host transfer
    audits therefore hash the decompressed byte stream for ``*.gz`` and exact bytes
    for every other format. This is intentionally separate from ``describe_input``:
    it validates transfer identity without changing established analytical cache
    keys or pretending that arbitrary binary formats have a semantic canonical form.
    """

    source = Path(path)
    encoding = content_encoding or ("gzip" if source.suffix == ".gz" else "identity")
    if encoding not in {"gzip", "identity"}:
        raise ValueError(f"unsupported portable-content encoding: {encoding}")
    if encoding == "identity":
        return file_sha256(source)
    digest = hashlib.sha256()
    with gzip.open(source, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def portable_content_manifest_for_paths(
    root: str | Path,
    paths: Iterable[str | Path],
) -> list[dict[str, object]]:
    """Describe exact paths under one root using portable content hashes."""

    base = Path(root).resolve()
    if not base.is_dir():
        raise NotADirectoryError(f"portable-manifest root is not a directory: {base}")
    files = sorted({Path(path).resolve() for path in paths})
    if not files:
        raise FileNotFoundError(f"portable-manifest perimeter is empty under {base}")
    escaped = [path for path in files if not path.is_relative_to(base)]
    if escaped:
        raise ValueError(f"portable-manifest path escapes its root: {escaped[0]}")
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"portable-manifest path is absent: {missing[0]}")
    return [
        {
            "path": str(path.relative_to(base)),
            "container_bytes": path.stat().st_size,
            "content_sha256": portable_content_sha256(path),
            "content_encoding": "gzip" if path.suffix == ".gz" else "identity",
        }
        for path in files
    ]


def portable_content_manifest(
    root: str | Path,
    *,
    patterns: list[str],
) -> list[dict[str, object]]:
    """Describe an exact, sorted glob perimeter using portable content hashes."""

    base = Path(root)
    if not base.is_dir():
        raise NotADirectoryError(f"portable-manifest root is not a directory: {base}")
    files = sorted({path for pattern in patterns for path in base.glob(pattern) if path.is_file()})
    if not files:
        raise FileNotFoundError(
            f"portable-manifest perimeter is empty under {base}: {patterns}"
        )
    return portable_content_manifest_for_paths(base, files)


def portable_manifest_sha256(entries: list[dict[str, object]]) -> str:
    """Hash portable file identities while excluding container-size diagnostics."""

    identities = [
        {
            "path": entry["path"],
            "content_sha256": entry["content_sha256"],
            "content_encoding": entry["content_encoding"],
        }
        for entry in entries
    ]
    payload = json.dumps(identities, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.rstrip() if r.returncode == 0 else None


def git_state(exclude_paths: list[str | Path] | None = None) -> dict[str, object]:
    """Commit, branch and dirtiness. `dirty` is the field that matters.

    A stamp from a dirty tree cannot be reproduced from the commit alone, so it is
    recorded rather than quietly presented as a clean build.
    """
    sha = _run(["git", "rev-parse", "HEAD"])
    status = _run(["git", "status", "--porcelain"])
    excluded = {str(_rel(Path(path))) for path in (exclude_paths or [])}
    tracked = untracked = generated = None
    if status is not None:
        tracked, untracked, generated = [], [], []
        for line in status.splitlines():
            if not line[:2].strip():
                continue
            path = line[3:]
            if path in excluded:
                continue
            if path.startswith(GENERATED_PREFIXES):
                generated.append(path)
            elif line.startswith("??"):
                untracked.append(path)
            else:
                tracked.append(path)
    return {
        "commit": sha,
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(tracked or untracked) if tracked is not None else None,
        "dirty_tracked_files": tracked[:40] if tracked else [],
        "dirty_untracked_files": untracked[:40] if untracked else [],
        "dirty_generated_files": generated[:40] if generated else [],
    }


def code_fingerprint(sources: list[str]) -> str:
    """Stable sha256 over the given repo-relative source files.

    Missing files are recorded as such rather than skipped, so deleting a module
    changes the fingerprint instead of leaving it unchanged.
    """
    h = hashlib.sha256()
    for rel in sorted(sources):
        p = ROOT / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    return h.hexdigest()


class _WithoutDocstrings(ast.NodeTransformer):
    """Remove docstrings while preserving every executable AST node."""

    @staticmethod
    def _strip(body: list[ast.stmt]) -> list[ast.stmt]:
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            return body[1:]
        return body

    def visit_Module(self, node: ast.Module) -> ast.AST:
        node.body = self._strip(node.body)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.body = self._strip(node.body)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.body = self._strip(node.body)
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.body = self._strip(node.body)
        return self.generic_visit(node)


def _semantic_source(relative: str, content: bytes) -> bytes:
    """Canonical executable representation, falling back to exact bytes."""
    if not relative.endswith(".py"):
        return content
    try:
        tree = ast.parse(content.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return content
    stripped = _WithoutDocstrings().visit(tree)
    ast.fix_missing_locations(stripped)
    return ast.dump(stripped, annotate_fields=True, include_attributes=False).encode()


def _fingerprint_contents(contents: dict[str, bytes], *, semantic: bool) -> str:
    h = hashlib.sha256()
    for relative in sorted(contents):
        h.update(relative.encode())
        payload = contents[relative]
        h.update(_semantic_source(relative, payload) if semantic else payload)
    return h.hexdigest()


def semantic_code_fingerprint(sources: list[str]) -> str:
    """Fingerprint executable Python structure while ignoring formatting and docstrings."""
    contents = {
        relative: (ROOT / relative).read_bytes() if (ROOT / relative).exists() else b"<missing>"
        for relative in sources
    }
    return _fingerprint_contents(contents, semantic=True)


@functools.lru_cache(maxsize=512)
def _git_source(commit: str, relative: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _legacy_semantic_compatible(record: dict[str, object]) -> bool:
    """Accept an old byte stamp only after reconstructing it exactly and proving an AST-only match."""
    git = record.get("git") or {}
    if not isinstance(git, dict):
        return False
    commit = str(git.get("commit") or "")
    if not commit:
        return False
    dirty = {
        str(path)
        for key in ("dirty_tracked_files", "dirty_untracked_files")
        for path in (git.get(key) or [])
    }
    stamped: dict[str, bytes] = {}
    current: dict[str, bytes] = {}
    for relative_value in record.get("code_sources") or []:
        relative = str(relative_value)
        path = ROOT / relative
        current[relative] = path.read_bytes() if path.exists() else b"<missing>"
        if relative in dirty:
            stamped[relative] = current[relative]
        else:
            prior = _git_source(commit, relative)
            if prior is None:
                return False
            stamped[relative] = prior
    if _fingerprint_contents(stamped, semantic=False) != record.get("code_fingerprint"):
        return False
    return _fingerprint_contents(stamped, semantic=True) == _fingerprint_contents(current, semantic=True)


def dependency_fingerprint(
    sources: list[str], inputs: list[str | Path] | None = None
) -> str:
    """Stable sha256 over code and every declared input state."""
    h = hashlib.sha256()
    h.update(code_fingerprint(sources).encode())
    for item in sorted((describe_input(path) for path in (inputs or [])), key=lambda x: str(x["path"])):
        h.update(json.dumps(item, sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


def cache_key(
    sources: list[str], *, inputs: list[str | Path] | None = None, length: int = 12
) -> str:
    """Short dependency fingerprint for use in a cache directory name.

    Putting the key in the PATH rather than in a column means a stale generation
    cannot be read at all, instead of being readable and merely mislabelled.
    """
    return dependency_fingerprint(sources, inputs)[:length]


def describe_input(path: str | Path) -> dict[str, object]:
    p = Path(path)
    if not p.exists():
        return {"path": str(_rel(p)), "exists": False}
    st = p.stat()
    if p.is_dir():
        h = hashlib.sha256()
        entries = 0
        for child in sorted(q for q in p.rglob("*") if q.is_file()):
            rel = child.relative_to(p)
            child_stat = child.stat()
            h.update(str(rel).encode())
            h.update(str(child_stat.st_size).encode())
            h.update(str(child_stat.st_mtime_ns).encode())
            entries += 1
        return {
            "path": str(_rel(p)),
            "exists": True,
            "kind": "directory",
            "entries": entries,
            "tree_fingerprint": h.hexdigest(),
        }
    d: dict[str, object] = {"path": str(_rel(p)), "exists": True, "bytes": st.st_size}
    if st.st_size <= CONTENT_HASH_MAX_BYTES:
        d["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    else:
        d["mtime_ns"] = st.st_mtime_ns
        d["hashed"] = False
    return d


def _rel(p: Path) -> Path:
    if p.is_absolute():
        try:
            return p.relative_to(ROOT)
        except ValueError:
            pass
    try:
        return p.resolve().relative_to(ROOT)
    except ValueError:
        return p


@dataclass
class Provenance:
    artefact: str
    script: str
    argv: list[str]
    created_at: str
    git: dict[str, object]
    code_fingerprint: str
    code_sources: list[str]
    artefact_bytes: int | None = None
    artefact_mtime_ns: int | None = None
    artefact_sha256: str | None = None
    payload_identity: dict[str, object] | None = None
    inputs: list[dict[str, object]] = field(default_factory=list)
    rows: int | None = None
    notes: str | None = None
    python: str = field(default_factory=lambda: sys.version.split()[0])
    libraries: dict[str, str] = field(default_factory=dict)


def _libraries() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("pandas", "numpy", "pyarrow", "scipy"):
        try:
            out[name] = __import__(name).__version__
        except Exception:
            pass
    return out


def sidecar_path(artefact: str | Path) -> Path:
    """Where an artefact's stamp lives: mirrored under data/manifests/.

    Kept beside the manifests rather than next to the artefact so that provenance
    survives a directory of derived data being wiped, which is a normal and
    encouraged operation.
    """
    rel = _rel(Path(artefact))
    return MANIFESTS / rel.with_suffix(rel.suffix + ".prov.json")


def ensure_released_directory_alias(
    artefact: str | Path,
    *,
    expected: str | Path,
    under: str | Path,
) -> Path | None:
    """Alias a semantically current released cache to its new byte-keyed name.

    Cache directories use exact source bytes in their names, while ``verify`` can prove
    that an older release differs only in comments, formatting, or docstrings. Without
    this bridge, a documentation edit makes consumers look in an empty cache and can
    trigger a duplicate full rebuild. The released artefact's input record is the sole
    authority for the old directory; an executable or input change makes ``verify``
    stale and therefore cannot be aliased.

    Existing paths are never replaced. The alias is relative and contains no copied
    data, so a later executable generation remains separate and auditable.
    """
    expected_path = Path(expected)
    if expected_path.exists() or expected_path.is_symlink():
        return None
    perimeter = Path(under).resolve()
    verdict = verify(artefact)
    if verdict.get("status") != "ok":
        raise RuntimeError(
            f"cannot alias a non-current release: {verdict.get('status')}"
        )
    record = json.loads(sidecar_path(artefact).read_text(encoding="utf-8"))
    candidates = []
    for item in record.get("inputs") or []:
        candidate = _recorded_input_path(item)
        if (
            candidate.parent.resolve() == perimeter
            and candidate.name.startswith("engine_")
            and candidate.is_dir()
        ):
            candidates.append(candidate)
    if len(candidates) != 1:
        raise RuntimeError(
            f"released cache record has {len(candidates)} engine directories under {perimeter}"
        )
    recorded = candidates[0]
    for prior in perimeter.glob("engine_*"):
        if prior.is_symlink() and prior.resolve() == recorded.resolve():
            prior.unlink()
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        expected_path.symlink_to(
            os.path.relpath(recorded, start=expected_path.parent),
            target_is_directory=True,
        )
    except FileExistsError:
        return None
    return recorded


def describe_artifact_payload(
    path: str | Path, *, artefact: str | Path | None = None
) -> dict[str, object]:
    """Bind exact bytes plus format-aware row and schema identity.

    The target name selects the format because staged files intentionally end in ``.tmp``. Every payload gets a complete streaming digest regardless of size; Parquet and JSON Lines also expose the physical row count that a caller's declared ``rows`` must match.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"artifact payload is absent: {source}")
    logical = Path(artefact) if artefact is not None else source
    identity: dict[str, object] = {
        "schema_version": 1,
        "bytes": source.stat().st_size,
        "sha256": file_sha256(source),
    }
    lower_name = logical.name.lower()
    if lower_name.endswith(".parquet"):
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(source)
        schema = parquet.schema_arrow
        identity.update(
            {
                "format": "parquet",
                "rows": parquet.metadata.num_rows,
                "columns": list(schema.names),
                "schema_sha256": hashlib.sha256(
                    schema.serialize().to_pybytes()
                ).hexdigest(),
            }
        )
    elif lower_name.endswith(".jsonl") or lower_name.endswith(".jsonl.gz"):
        opener = gzip.open if lower_name.endswith(".gz") else open
        rows = 0
        try:
            with opener(source, "rt", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        raise ValueError(
                            f"JSON Lines payload contains a blank record at line {line_number}: {source}"
                        )
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"JSON Lines payload contains invalid JSON at line {line_number}: {source}"
                        ) from error
                    rows += 1
        except UnicodeDecodeError as error:
            raise ValueError(f"JSON Lines payload is not UTF-8: {source}") from error
        identity.update({"format": "jsonl", "rows": rows})
    else:
        identity["format"] = "binary"
    return identity


def prepare_stamp(artefact: str | Path, *, content_path: str | Path, code_sources: list[str], inputs: list[str | Path] | None = None, rows: int | None = None, notes: str | None = None, script: str | None = None) -> bytes:
    """Construct provenance for staged artefact bytes without changing released paths."""

    content = Path(content_path)
    if not content.is_file():
        raise FileNotFoundError(f"staged provenance content is absent: {content}")
    out = sidecar_path(artefact)
    content_stat = content.stat()
    payload_identity = describe_artifact_payload(content, artefact=artefact)
    physical_rows = payload_identity.get("rows")
    if rows is not None and physical_rows is not None and rows != physical_rows:
        raise ValueError(
            f"declared row count {rows:,} disagrees with physical payload "
            f"row count {physical_rows:,}: {artefact}"
        )
    prov = Provenance(
        artefact=str(_rel(Path(artefact))),
        script=script or str(_rel(Path(sys.argv[0]))) if sys.argv and sys.argv[0] else "<unknown>",
        argv=list(sys.argv[1:]),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # A tracked generated artefact necessarily becomes modified before it can be
        # stamped, and an existing sidecar is modified by the same operation. Neither
        # is evidence that the CODE used for the build was dirty.
        git=git_state([artefact, out]),
        code_fingerprint=code_fingerprint(code_sources),
        code_sources=sorted(code_sources),
        artefact_bytes=content_stat.st_size,
        artefact_mtime_ns=content_stat.st_mtime_ns,
        artefact_sha256=str(payload_identity["sha256"]),
        payload_identity=payload_identity,
        inputs=[describe_input(i) for i in (inputs or [])],
        rows=rows,
        notes=notes,
        libraries=_libraries(),
    )
    return (json.dumps(asdict(prov), indent=1, sort_keys=True) + "\n").encode()


def install_stamped_artifact(staged: str | Path, artefact: str | Path, prepared_stamp: bytes) -> Path:
    """Install one payload/sidecar pair through a durable recovery journal."""

    staged_path = Path(staged)
    target = Path(artefact)
    sidecar = sidecar_path(target)
    try:
        record = json.loads(prepared_stamp)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("prepared provenance is not valid JSON") from error
    staged_stat = staged_path.stat()
    recorded_identity = record.get("payload_identity")
    current_identity = describe_artifact_payload(staged_path, artefact=target)
    recorded_rows = record.get("rows")
    physical_rows = current_identity.get("rows")
    rows_match = recorded_rows is None or physical_rows is None or recorded_rows == physical_rows
    if record.get("artefact") != str(_rel(target)) or record.get("artefact_bytes") != staged_stat.st_size or record.get("artefact_mtime_ns") != staged_stat.st_mtime_ns or recorded_identity != current_identity or not rows_match:
        raise ValueError("prepared provenance does not identify the staged artefact")
    with serialized_output_installs((target, sidecar)):
        with staged_output(sidecar) as staged_sidecar:
            staged_sidecar.write_bytes(prepared_stamp)
            publish_journaled_bundle(
                targets={"payload": target, "sidecar": sidecar},
                staged={"payload": staged_path, "sidecar": staged_sidecar},
                journal_root=target.parent / ".ddvc-publication-journals",
                validate_live=lambda: _require_current_unlocked(target),
            )
    return sidecar


def recover_stamped_artifact_install(artefact: str | Path) -> int:
    """Recover an interrupted payload/sidecar publication without starting a build."""

    target = Path(artefact)
    sidecar = sidecar_path(target)
    with serialized_output_installs((target, sidecar)):
        return recover_journaled_publications(
            {"payload": target, "sidecar": sidecar},
            journal_root=target.parent / ".ddvc-publication-journals",
        ).recovered


def stamp(artefact: str | Path, *, code_sources: list[str], inputs: list[str | Path] | None = None, rows: int | None = None, notes: str | None = None, script: str | None = None) -> Path:
    """Record how `artefact` was produced. Returns the sidecar path."""

    target = Path(artefact)
    out = sidecar_path(target)
    with serialized_output_installs((target, out)):
        payload = prepare_stamp(target, content_path=target, code_sources=code_sources, inputs=inputs, rows=rows, notes=notes, script=script)
        with atomic_output(out) as temporary:
            temporary.write_bytes(payload)
    return out


def _recorded_input_path(record: dict[str, object]) -> Path:
    value = Path(str(record.get("path", "")))
    return value if value.is_absolute() else ROOT / value


def input_matches(record: dict[str, object]) -> bool:
    """Whether a recorded file-content or directory-tree fingerprint is current."""
    current = describe_input(_recorded_input_path(record))
    keys = (
        "exists",
        "kind",
        "bytes",
        "sha256",
        "mtime_ns",
        "entries",
        "tree_fingerprint",
    )
    return all(current.get(key) == record.get(key) for key in keys if key in record)


def released_input_binding_matches(binding: dict[str, object]) -> bool:
    """Verify an exact release identity even when generic input hashing is bounded."""

    path = _recorded_input_path(binding)
    expected = binding.get("sha256")
    return (
        isinstance(expected, str)
        and len(expected) == 64
        and path.is_file()
        and file_sha256(path) == expected
    )


def _verify_unlocked(artefact: str | Path) -> dict[str, object]:
    """Is this artefact still the product of the code now in the tree?

    Returns a verdict of `ok`, `stale`, `unstamped`, or `missing_artefact`. `stale`
    is the important one: the artefact exists and was stamped, but the sources that
    can change it have changed since, so its numbers must not be quoted.
    """
    p = Path(artefact)
    side = sidecar_path(artefact)
    if not p.exists():
        return {"artefact": str(_rel(p)), "status": "missing_artefact"}
    if not side.exists():
        return {"artefact": str(_rel(p)), "status": "unstamped"}
    rec = json.loads(side.read_text())
    recorded_identity = rec.get("payload_identity")
    try:
        current_identity = describe_artifact_payload(p, artefact=p)
    except (OSError, TypeError, ValueError):
        current_identity = None
    if isinstance(recorded_identity, dict):
        content_ok = recorded_identity == current_identity and (
            rec.get("rows") is None
            or current_identity is None
            or current_identity.get("rows") is None
            or rec.get("rows") == current_identity.get("rows")
        )
    elif current_identity is None:
        content_ok = False
    else:
        recorded_bytes = rec.get("artefact_bytes")
        recorded_mtime_ns = rec.get("artefact_mtime_ns")
        recorded_digest = rec.get("artefact_sha256")
        physical_rows = current_identity.get("rows")
        declared_rows = rec.get("rows")
        rows_ok = (
            declared_rows is None
            or physical_rows is None
            or declared_rows == physical_rows
        )
        if recorded_bytes is None and recorded_mtime_ns is None and recorded_digest is None:
            content_ok = False
        else:
            current_stat = p.stat()
            content_ok = rows_ok and recorded_bytes == current_stat.st_size and (recorded_mtime_ns is None or recorded_mtime_ns == current_stat.st_mtime_ns) and isinstance(recorded_digest, str) and len(recorded_digest) == 64 and recorded_digest == current_identity["sha256"]
    now = code_fingerprint(rec.get("code_sources") or [])
    byte_code_ok = now == rec.get("code_fingerprint")
    documentation_only_change = not byte_code_ok and _legacy_semantic_compatible(rec)
    code_ok = byte_code_ok or documentation_only_change
    input_changes = [
        str(item.get("path"))
        for item in rec.get("inputs") or []
        if not input_matches(item)
    ]
    release_binding_changes: list[str] = []
    for item in rec.get("released_input_bindings") or []:
        if not isinstance(item, dict):
            release_binding_changes.append("<invalid-release-binding>")
        elif not released_input_binding_matches(item):
            release_binding_changes.append(str(item.get("path")))
    input_changes.extend(
        path for path in release_binding_changes if path not in input_changes
    )
    inputs_ok = not input_changes
    return {
        "artefact": str(_rel(p)),
        "status": "ok" if code_ok and inputs_ok and content_ok else "stale",
        "stamped_fingerprint": rec.get("code_fingerprint"),
        "current_fingerprint": now,
        "code_current": code_ok,
        "byte_code_current": byte_code_ok,
        "documentation_only_change": documentation_only_change,
        "inputs_current": inputs_ok,
        "content_current": content_ok,
        "changed_inputs": input_changes,
        "stamped_commit": (rec.get("git") or {}).get("commit"),
        "was_dirty": (rec.get("git") or {}).get("dirty"),
        "created_at": rec.get("created_at"),
    }


def verify(artefact: str | Path) -> dict[str, object]:
    """Verify one payload and sidecar under a shared pair lease.

    Writers own the same two-path perimeter exclusively, so a reader observes the complete prior pair or the complete replacement pair. A crash between the two renames can still leave a mixed pair on disk; the payload identity makes that state fail closed on the next read.
    """

    target = Path(artefact)
    sidecar = sidecar_path(target)
    with serialized_read_installs((target, sidecar), allow_missing=True):
        return _verify_unlocked(target)


def _require_current_unlocked(artefact: str | Path) -> None:
    verdict = _verify_unlocked(artefact)
    if verdict.get("status") != "ok":
        raise RuntimeError(
            f"installed artifact is not current: {verdict['artefact']}={verdict['status']}"
        )


@contextmanager
def current_artifacts(
    artefacts: Iterable[str | Path], *, consumer: str
):
    """Verify and lease a complete payload/sidecar snapshot through consumption."""

    targets = tuple(dict.fromkeys(Path(artefact) for artefact in artefacts))
    if not targets:
        raise ValueError("current-artifact lease requires at least one artifact")
    perimeter = tuple(
        path for target in targets for path in (target, sidecar_path(target))
    )
    with serialized_read_installs(perimeter, allow_missing=True):
        failures = [
            verdict
            for target in targets
            if (verdict := _verify_unlocked(target)).get("status") != "ok"
        ]
        if failures:
            detail = "; ".join(
                f"{verdict['artefact']}={verdict['status']}"
                for verdict in failures
            )
            raise RuntimeError(f"{consumer} requires current analysis inputs: {detail}")
        yield targets
        changed = [
            verdict
            for target in targets
            if (verdict := _verify_unlocked(target)).get("status") != "ok"
        ]
        if changed:
            detail = "; ".join(
                f"{verdict['artefact']}={verdict['status']}"
                for verdict in changed
            )
            raise RuntimeError(f"{consumer} inputs changed during consumption: {detail}")


def require_current_artifacts(
    artefacts: list[str | Path], *, consumer: str
) -> None:
    """Refuse to run a consumer against missing, unstamped, or stale inputs."""
    with current_artifacts(artefacts, consumer=consumer):
        pass

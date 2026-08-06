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

Fingerprints cover SOURCE, not the environment. That is deliberate: a code change
is the failure mode observed here, and file hashes catch it without a container.
Library versions are recorded for the record but not compared, since upgrading
pandas should not invalidate a panel whose numbers it does not change.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "data" / "manifests"

# Content-hash inputs up to this size; above it, identify by size and mtime. The
# raw layer runs to gigabytes per venue, and rehashing it on every build would
# make stamping expensive enough that people would switch it off.
CONTENT_HASH_MAX_BYTES = 64 * 1024 * 1024


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_state() -> dict[str, object]:
    """Commit, branch and dirtiness. `dirty` is the field that matters.

    A stamp from a dirty tree cannot be reproduced from the commit alone, so it is
    recorded rather than quietly presented as a clean build.
    """
    sha = _run(["git", "rev-parse", "HEAD"])
    status = _run(["git", "status", "--porcelain"])
    tracked = None
    if status is not None:
        tracked = [ln[3:] for ln in status.splitlines()
                   if ln[:2].strip() and not ln.startswith("??")]
    return {
        "commit": sha,
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(tracked) if tracked is not None else None,
        "dirty_tracked_files": tracked[:40] if tracked else [],
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


def cache_key(sources: list[str], length: int = 12) -> str:
    """Short fingerprint for use in a cache directory name.

    Putting the key in the PATH rather than in a column means a stale generation
    cannot be read at all, instead of being readable and merely mislabelled.
    """
    return code_fingerprint(sources)[:length]


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


def stamp(artefact: str | Path, *, code_sources: list[str],
          inputs: list[str | Path] | None = None, rows: int | None = None,
          notes: str | None = None, script: str | None = None) -> Path:
    """Record how `artefact` was produced. Returns the sidecar path."""
    prov = Provenance(
        artefact=str(_rel(Path(artefact))),
        script=script or str(_rel(Path(sys.argv[0]))) if sys.argv and sys.argv[0] else "<unknown>",
        argv=list(sys.argv[1:]),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        git=git_state(),
        code_fingerprint=code_fingerprint(code_sources),
        code_sources=sorted(code_sources),
        inputs=[describe_input(i) for i in (inputs or [])],
        rows=rows,
        notes=notes,
        libraries=_libraries(),
    )
    out = sidecar_path(artefact)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(prov), indent=1, sort_keys=True) + "\n")
    return out


def _recorded_input_path(record: dict[str, object]) -> Path:
    value = Path(str(record.get("path", "")))
    return value if value.is_absolute() else ROOT / value


def input_matches(record: dict[str, object]) -> bool:
    """Whether a recorded input is byte-for-byte or tree-state current."""
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


def verify(artefact: str | Path) -> dict[str, object]:
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
    now = code_fingerprint(rec.get("code_sources") or [])
    code_ok = now == rec.get("code_fingerprint")
    input_changes = [
        str(item.get("path"))
        for item in rec.get("inputs") or []
        if not input_matches(item)
    ]
    inputs_ok = not input_changes
    return {
        "artefact": str(_rel(p)),
        "status": "ok" if code_ok and inputs_ok else "stale",
        "stamped_fingerprint": rec.get("code_fingerprint"),
        "current_fingerprint": now,
        "code_current": code_ok,
        "inputs_current": inputs_ok,
        "changed_inputs": input_changes,
        "stamped_commit": (rec.get("git") or {}).get("commit"),
        "was_dirty": (rec.get("git") or {}).get("dirty"),
        "created_at": rec.get("created_at"),
    }

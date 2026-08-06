"""Writers for derived tables, with the format chosen by role.

The repository bans delimited text and prefers Parquet for data panels. Both hold.
What was missing is the distinction between a PANEL, which code reads, and an
EXHIBIT, which a person reads while checking a number that reaches the paper.
Those want different things, and the difference is measured rather than assumed:

  4,880,034-row panel     Parquet against gzipped JSON Lines is 1.2x smaller,
                          85x faster to write, 113x faster to read whole, and
                          165x faster reading a two-column subset. Several build
                          scripts read a handful of columns across 2,277 day
                          files, so that last ratio is the difference between
                          seconds and hours. Parquet, not negotiable on merit.

  188-row exhibit         gzipped JSON Lines is 0.6x the SIZE of Parquet, keeps
                          its dtypes, and every timing is sub-millisecond. The
                          columnar advantages are worth nothing at this scale
                          while Parquet's opacity still costs: it cannot be
                          grepped, headed, or diffed in git, and it cannot be
                          read at all without pyarrow. For the numbers that go
                          into a paper, being able to open the file and look is
                          worth more than a millisecond.

So: exhibits are JSON Lines, panels are Parquet, and the row-count boundary is
explicit below rather than left to whoever writes the next script.

Big integers. `sqrtPriceX96` is uint160 and `liquidity` is uint128, and neither
fits an IEEE-754 double. Python's own json round-trips them exactly because
Python integers are arbitrary precision, which makes the hazard easy to miss:
any other consumer, jq or a browser or a strict-typed reader, silently truncates
1274886371296766398325853120698628 to 1.2748863712967664e+33. Columns holding
values beyond the safe integer range are therefore written as decimal STRINGS, in
either format, so no reader can quietly lose precision.
"""

from __future__ import annotations

import gzip
import inspect
import json
import math
import numbers
from pathlib import Path

import pandas as pd

from ddvc.paths import REPO_ROOT
from ddvc.provenance import stamp

# Above this many rows an artefact is a panel, whatever directory it sits in, and
# the columnar format wins on measured read cost.
EXHIBIT_MAX_ROWS = 100_000

# Beyond 2^53 an IEEE-754 double can no longer represent every integer, which is
# where a non-Python JSON reader starts losing digits.
SAFE_INT_MAX = 2 ** 53 - 1


def _stringify_big_ints(df: pd.DataFrame) -> pd.DataFrame:
    """Render columns holding out-of-range integers as decimal strings."""
    out = df
    for col in df.columns:
        s = df[col]
        if s.dtype != object and not pd.api.types.is_integer_dtype(s):
            continue
        try:
            big = any(isinstance(v, int) and abs(v) > SAFE_INT_MAX
                      for v in s.dropna().head(2000))
        except TypeError:
            big = False
        if big:
            if out is df:
                out = df.copy()
            out[col] = s.map(lambda v: str(v) if isinstance(v, int) else v)
    return out


def _caller_sources(extra: list[str] | None) -> list[str]:
    """Repo-relative sources to fingerprint: the calling script plus this module.

    Provenance that depends on each author remembering to pass `code_sources` gets
    forgotten, which is how 8,633 artefacts came to have none. Defaulting to the
    caller means every write through these helpers is stamped, and a script with a
    wider dependency surface can still pass its own list.
    """
    out = ["src/ddvc/tables.py"]
    try:
        for frame in inspect.stack()[1:]:
            f = Path(frame.filename).resolve()
            if f.is_relative_to(REPO_ROOT) and "ddvc/tables.py" not in str(f):
                out.append(str(f.relative_to(REPO_ROOT)))
                break
    except (ValueError, OSError):
        pass
    return sorted(set(out + (extra or [])))


def write_exhibit(df: pd.DataFrame, path: str | Path,
                  code_sources: list[str] | None = None,
                  inputs: list[str | Path] | None = None,
                  notes: str | None = None) -> Path:
    """Write a paper-facing table as JSON Lines, one record per line.

    Refuses a frame large enough to belong in Parquet instead of silently writing
    a file nobody will want to read, since the whole point of the format here is
    that a person can open it.
    """
    p = Path(path)
    if len(df) > EXHIBIT_MAX_ROWS:
        raise ValueError(
            f"{p.name}: {len(df):,} rows exceeds the {EXHIBIT_MAX_ROWS:,}-row exhibit "
            f"limit; write it as a Parquet panel with write_panel() instead")
    if p.suffix not in (".jsonl", ".gz"):
        p = p.with_suffix(".jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    frame = _stringify_big_ints(df)
    tmp = p.with_name(p.name + ".tmp")
    opener = (lambda: gzip.open(tmp, "wt")) if p.suffix == ".gz" else (lambda: open(tmp, "w"))
    try:
        with opener() as fh:
            for rec in frame.to_dict("records"):
                clean = {
                    key: None if value is None or _is_missing(value) else value
                    for key, value in rec.items()
                }
                fh.write(
                    json.dumps(clean, allow_nan=False, default=str, sort_keys=True) + "\n"
                )
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()
    stamp(
        p,
        code_sources=_caller_sources(code_sources),
        inputs=inputs,
        rows=len(df),
        notes=notes,
    )
    return p


def read_exhibit(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt") as fh:
            return pd.DataFrame([json.loads(x) for x in fh])
    return pd.read_json(p, lines=True)


def write_panel(df: pd.DataFrame, path: str | Path,
                code_sources: list[str] | None = None,
                inputs: list[str | Path] | None = None,
                notes: str | None = None) -> Path:
    """Write an analytic panel as Parquet, which is what code reads."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    try:
        df.to_parquet(tmp, index=False)
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()
    stamp(
        p,
        code_sources=_caller_sources(code_sources),
        inputs=inputs,
        rows=len(df),
        notes=notes,
    )
    return p


def _is_missing(value: object) -> bool:
    """Whether a scalar needs JSON null instead of a non-standard NaN token."""
    if isinstance(value, numbers.Real):
        try:
            if not math.isfinite(value):
                return True
        except OverflowError:
            pass
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    try:
        return bool(missing)
    except (TypeError, ValueError):
        return False

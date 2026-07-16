"""Vehicle-currency network dominance metrics — one row per (date, token).

Reads the unified cross-DEX swap-events table produced by the reconstruct
layer and emits per token per day the full dominance-variable family:

    VolShare        volume share: fraction of total directed route-leg volume
                    assigned to each token as an incoming or outgoing endpoint
    BetwCent        betweenness centrality (route betweenness on the token
                    graph, count-based)
    BetwCent_V      betweenness centrality (volume-weighted)
    EigenCent       directionless eigenvector centrality (average of in/out)
    EigenCent_in    eigenvector centrality of the inflow (Aᵀ) side
    EigenCent_out   eigenvector centrality of the outflow (A) side
    V_in            raw inbound USD volume (legs where token is destination)
    V_out           raw outbound USD volume (legs where token is source)
    V_total         V_in + V_out
    n_routes        number of unambiguous routes in the day's network

Output: data/metrics/daily_token_metrics.parquet  (all days appended)
Also writes per-day Parquet to data/metrics/YYYYMMDD.parquet for resumable runs.

Direction convention:
  Eigenvector is computed on the directed realized-edge network (every leg an
  edge, weighted by USD). EigenCent_in is the eigenvector of Aᵀ; EigenCent_out
  is the eigenvector of A (reversed graph). EigenCent is the directionless mean.

  Betweenness runs on reconstructed *intent* routes: each non-ambiguous
  transaction is collapsed to ultimate_source -> [intermediaries] ->
  ultimate_target, so an intermediary token scores exactly the routing-hub role
  the paper's betweenness is meant to capture.
"""
from __future__ import annotations

import os

# Pin BLAS to one thread per process before numpy import. The range backfill
# fans days across processes; letting each spawn a thread-pool oversubscribes
# the machine and halves throughput.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR
from ddvc.reconstruct import unified_path

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def daily_metrics_path(stamp: str) -> Path:
    """data/metrics/<YYYYMMDD>.parquet — one period's token-metrics table."""
    return DATA_DIR / "metrics" / f"{stamp}.parquet"


COMBINED_METRICS_PATH = DATA_DIR / "metrics" / "daily_token_metrics.parquet"

# Routes used for betweenness: only transactions whose route is unambiguous.
CLEAN_ROUTE_CLASSES = ("single", "coherent")


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

def _directed_volume(legs: pd.DataFrame) -> pd.DataFrame:
    """Per-token directed USD volume on the realized-edge network."""
    v_out = legs.groupby("token_in_sym")["amount_usd"].sum()
    v_in = legs.groupby("token_out_sym")["amount_usd"].sum()
    vol = pd.DataFrame({"V_in": v_in, "V_out": v_out}).fillna(0.0)
    vol["V_total"] = vol["V_in"] + vol["V_out"]
    total = vol["V_total"].sum()
    vol["VolShare"] = vol["V_total"] / total if total > 0 else 0.0
    return vol


# ---------------------------------------------------------------------------
# Eigenvector centrality
# ---------------------------------------------------------------------------

def _dense_principal(m: np.ndarray) -> np.ndarray:
    """Eigenvector of the largest-real-eigenvalue of a dense matrix (or zeros)."""
    if m.size == 0 or not np.any(m):
        return np.zeros(m.shape[0])
    vals, vecs = np.linalg.eig(m)
    return vecs[:, int(np.argmax(vals.real))].real


def _principal_eigenvector(g: nx.DiGraph) -> dict[str, float]:
    """Eigenvector centrality = dominant eigenvector of the weighted adjacency A.

    Replicates ddc's nx.eigenvector_centrality_numpy math (eigenvector of the
    largest real eigenvalue of Aᵀ, sign-fixed, L2-normalised). Implemented
    directly so it works on weakly-connected directed components — the modern
    networkx helper refuses any non-strongly-connected graph, but the dominant
    eigenvector is still well-defined.
    """
    import scipy.sparse.linalg as sla

    nodes = list(g.nodes())
    a = nx.to_scipy_sparse_array(g, nodelist=nodes, weight="weight", dtype=float)
    at = a.T.astype(float)

    if len(nodes) <= 4:
        largest = _dense_principal(at.toarray())
    else:
        try:
            _, vecs = sla.eigs(at, k=1, which="LR", maxiter=10_000)
            largest = vecs.flatten().real
        except (sla.ArpackError, ValueError, TypeError):
            largest = _dense_principal(at.toarray())

    norm = np.sign(largest.sum()) * np.linalg.norm(largest)
    if norm == 0:
        norm = 1.0
    return {n: float(v) for n, v in zip(nodes, largest / norm)}


def _eigen_centrality(legs: pd.DataFrame) -> pd.DataFrame:
    """In / out / directionless eigenvector centrality on the directed USD network."""
    edges = (
        legs.groupby(["token_in_sym", "token_out_sym"])["amount_usd"]
        .sum()
        .reset_index()
    )
    g = nx.DiGraph()
    for src, tgt, w in edges.itertuples(index=False):
        if src == tgt:
            continue
        if g.has_edge(src, tgt):
            g[src][tgt]["weight"] += float(w)
        else:
            g.add_edge(src, tgt, weight=float(w))

    if len(g) == 0:
        return pd.DataFrame(columns=["EigenCent_in", "EigenCent_out", "EigenCent"])

    # Compute on the giant weakly-connected component; assign 0 to the rest.
    giant = max(nx.weakly_connected_components(g), key=len)
    gc = g.subgraph(giant).copy()
    eig_in = _principal_eigenvector(gc)
    eig_out = _principal_eigenvector(gc.reverse(copy=True))
    cent = pd.DataFrame(
        {"EigenCent_in": pd.Series(eig_in), "EigenCent_out": pd.Series(eig_out)}
    ).fillna(0.0)
    cent["EigenCent"] = (cent["EigenCent_in"] + cent["EigenCent_out"]) / 2
    return cent


# ---------------------------------------------------------------------------
# Betweenness
# ---------------------------------------------------------------------------

def _routes(legs: pd.DataFrame) -> list[dict]:
    """Collapse each non-ambiguous transaction component to one (or more) routes.

    A route = ultimate_source -> intermediaries -> ultimate_target, with the
    component's average per-leg USD as its volume.  Splits / joins (>1 source
    or sink) expand to the cartesian set of (source, sink) pairs sharing the
    intermediary set, with volume divided across them so component volume is
    conserved.
    """
    clean = legs[legs["route_class"].isin(CLEAN_ROUTE_CLASSES)]
    if clean.empty:
        return []

    tin = clean["token_in_sym"].to_numpy()
    tout = clean["token_out_sym"].to_numpy()
    tin_role = clean["tin_role"].to_numpy()
    tout_role = clean["tout_role"].to_numpy()
    usd = clean["amount_usd"].to_numpy(dtype=float)

    routes: list[dict] = []
    for idx in clean.groupby(["tx_hash", "component_id"], sort=False).indices.values():
        role: dict[str, str] = {}
        for i in idx:
            for tok, rl in ((tin[i], tin_role[i]), (tout[i], tout_role[i])):
                if role.get(tok) == "intermediate":
                    continue
                if rl == "intermediate" or tok not in role:
                    role[tok] = rl
        sources = [t for t, rl in role.items() if rl == "source"]
        sinks = [t for t, rl in role.items() if rl == "sink"]
        inter = [t for t, rl in role.items() if rl == "intermediate"]
        if not sources or not sinks:
            continue
        avg_vol = usd[idx].sum() / len(idx)
        pairs = [(s, t) for s in sources for t in sinks if s != t]
        if not pairs:
            continue
        per = avg_vol / len(pairs)
        for s, t in pairs:
            routes.append({"src": s, "tgt": t, "inter": frozenset(inter), "vol": per})
    return routes


def _betweenness(routes: list[dict], tokens) -> pd.DataFrame:
    """Count-based and volume-weighted betweenness over the intent routes.

    For each token X: among routes whose ultimate source and target are both
    != X, the share (by count, and by volume) on which X appears as an
    intermediary. Both directionless by construction.
    """
    total_c = float(len(routes))
    total_v = float(sum(r["vol"] for r in routes))
    src_c: dict[str, float] = defaultdict(float)
    tgt_c: dict[str, float] = defaultdict(float)
    inter_c: dict[str, float] = defaultdict(float)
    src_v: dict[str, float] = defaultdict(float)
    tgt_v: dict[str, float] = defaultdict(float)
    inter_v: dict[str, float] = defaultdict(float)
    for r in routes:
        s, t, inter, vol = r["src"], r["tgt"], r["inter"], r["vol"]
        src_c[s] += 1.0
        src_v[s] += vol
        tgt_c[t] += 1.0
        tgt_v[t] += vol
        for m in inter:
            inter_c[m] += 1.0
            inter_v[m] += vol

    bc, bv = {}, {}
    for t in tokens:
        den_c = total_c - src_c[t] - tgt_c[t]
        den_v = total_v - src_v[t] - tgt_v[t]
        bc[t] = inter_c[t] / den_c if den_c > 0 else 0.0
        bv[t] = inter_v[t] / den_v if den_v > 0 else 0.0
    return pd.DataFrame({"BetwCent": pd.Series(bc), "BetwCent_V": pd.Series(bv)})


# ---------------------------------------------------------------------------
# Core compute
# ---------------------------------------------------------------------------

def _compute(legs: pd.DataFrame, date_str: str) -> pd.DataFrame:
    """Full dominance-variable family over one network, one row per token."""
    vol = _directed_volume(legs)
    cent = _eigen_centrality(legs)
    routes = _routes(legs)
    n_routes = len(routes)
    betw = _betweenness(routes, list(vol.index))

    out = (
        vol.join(cent, how="left")
        .join(betw, how="left")
        .fillna(0.0)
        .sort_values("VolShare", ascending=False)
    )
    out.index.name = "token_address"
    out.insert(0, "date", date_str)
    out.insert(2, "n_routes", n_routes)
    return out.reset_index()


def compute_day(stamp: str) -> pd.DataFrame:
    """Full dominance-variable family for one UTC day, one row per token.

    stamp is YYYYMMDD. Reads the unified cross-DEX swap-events Parquet.
    """
    path = unified_path(stamp)
    if not path.exists():
        raise FileNotFoundError(
            f"no unified swap-events table for {stamp}: {path}"
        )
    legs = pd.read_parquet(path)
    date_iso = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    return _compute(legs, date_iso)


# ---------------------------------------------------------------------------
# Batch run
# ---------------------------------------------------------------------------

def _available_stamps() -> list[str]:
    """YYYYMMDD stamps for which a reconstructed unified swap-events Parquet exists."""
    d = DATA_DIR / "unified"
    stamps: list[str] = []
    if d.is_dir():
        for f in d.glob("*.parquet"):
            stem = f.stem
            if len(stem) == 8 and stem.isdigit():
                stamps.append(stem)
    return sorted(stamps)


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def _process_one(stamp: str, skip_existing: bool) -> tuple[str, int]:
    out = daily_metrics_path(stamp)
    if skip_existing and out.exists():
        return stamp, -1
    df = compute_day(stamp)
    _write_parquet(df, out)
    return stamp, len(df)


def run(
    start: str | None = None,
    end: str | None = None,
    day: str | None = None,
    concurrency: int = 6,
    skip_existing: bool = True,
    rebuild_combined: bool = True,
) -> None:
    """Compute and write per-day token metrics, then optionally rebuild the combined table.

    start / end are YYYY-MM-DD inclusive bounds. day overrides for a single day.
    After per-day files are written the combined daily_token_metrics.parquet is
    rebuilt from all per-day files in data/metrics/.
    """
    if day:
        stamp = day.replace("-", "")
        stamps = [stamp]
    else:
        stamps = _available_stamps()
        if start:
            s = start.replace("-", "")
            stamps = [d for d in stamps if d >= s]
        if end:
            e = end.replace("-", "")
            stamps = [d for d in stamps if d <= e]

    if not stamps:
        print("no days to process", flush=True)
        return

    print(
        f"metrics over {len(stamps)} day(s) [{stamps[0]} .. {stamps[-1]}] "
        f"concurrency={concurrency}",
        flush=True,
    )

    done = skipped = 0
    with ProcessPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_process_one, s, skip_existing): s for s in stamps}
        for i, fut in enumerate(as_completed(futs), 1):
            _s, n = fut.result()
            if n == -1:
                skipped += 1
            else:
                done += 1
            if i % 25 == 0 or i == len(stamps):
                print(f"  [{i}/{len(stamps)}] written={done} skipped={skipped}", flush=True)

    print(f"done: {done} written, {skipped} skipped", flush=True)

    if rebuild_combined:
        _rebuild_combined()


def _rebuild_combined() -> None:
    """Concatenate all per-day metric Parquets into the combined table."""
    d = DATA_DIR / "metrics"
    files = sorted(d.glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].parquet"))  # YYYYMMDD.parquet
    if not files:
        print("no per-day metric files found; skipping combined rebuild", flush=True)
        return
    frames = [pd.read_parquet(f) for f in files]
    combined = pd.concat(frames, ignore_index=True)
    _write_parquet(combined, COMBINED_METRICS_PATH)
    print(
        f"combined table rebuilt: {len(combined):,} rows ({len(files)} days) "
        f"-> {COMBINED_METRICS_PATH}",
        flush=True,
    )

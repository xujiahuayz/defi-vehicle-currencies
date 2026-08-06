"""Counterfactual route quoting at historical pool state.

Prices the road not taken. For an executed route this asks what a rival route
would have returned at the *same* pre-trade block, which is the only way to
compare execution costs on-chain: comparing realised trades across a day cannot
work, because intraday price movement swamps execution cost by roughly a factor
of 34 (see `docs/finding-cost-dominance-not-yet-established.md`).

Ported from `defi-dominant-currency/scripts/run_v3_counterfactual_quote_opportunity.py`,
which validated at 1,550 of 1,655 executed swaps reproduced within 1% with median
absolute error 0.00 bp. Two changes here: the logic is a reusable module instead
of a single script, and paths generalise to arbitrary intermediaries rather than
a fixed native-versus-other comparison, since the intermediary asset is this
paper's object of study.

Method. Uniswap's V3 Quoter is a deployed contract whose `quoteExactInput(bytes,
uint256)` simulates a swap without executing it. Called through `eth_call` with a
historical block tag, it returns what the swap would have produced against that
block's pool state. The original V3 Quoter is used because QuoterV2 is not
deployed from the V3 launch period, and the sample begins there.

Raw-first, as in the original: every JSON-RPC request and response is persisted
verbatim before any quote is decoded. Reruns then cost nothing and a decode bug
never requires refetching.

Throughput is the binding constraint. Free archive endpoints rate-limited roughly
37% of jobs in the earlier run, so callers should pace requests and treat a
throttled response as retryable rather than as a missing quote. The original run
failed precisely because throttled error lines were cached as if they were
answers, so `is_cached` here counts only successful quotes.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from eth_abi import decode as abi_decode
from eth_utils import keccak

# The original Quoter, deployed 2021-05, covering the whole V3 sample.
UNISWAP_V3_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
QUOTE_SELECTOR = "0x" + keccak(text="quoteExactInput(bytes,uint256)")[:4].hex()

# Fee tiers in hundredths of a bip: 0.01%, 0.05%, 0.30%, 1.00%.
FEE_TIERS = (100, 500, 3000, 10000)

_UA = "ddvc-quoter/1.0"
_DEFAULT_RPCS = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
    "https://eth.drpc.org",
    "https://1rpc.io/eth",
)
_rpc_idx = 0
_rpc_idx_lock = threading.Lock()


def rpc_urls() -> list[str]:
    raw = os.getenv("ETH_RPC_URLS") or os.getenv("ETH_RPC_URL")
    if raw:
        urls = [u.strip() for u in raw.replace("\n", ",").split(",") if u.strip()]
        if urls:
            return urls
    return list(_DEFAULT_RPCS)


class Throttled(RuntimeError):
    """Endpoint refused for rate-limit reasons; the job is retryable."""


def rpc_post(payload: dict | list[dict], *, timeout: int = 60,
             retries: int = 3, sleep: float = 0.0) -> Any:
    """POST a JSON-RPC payload, rotating endpoints on failure.

    Raises Throttled when every endpoint refuses for rate-limit reasons, so the
    caller can distinguish "ask again later" from "this quote does not exist".
    """
    global _rpc_idx
    data = json.dumps(payload).encode()
    urls = rpc_urls()
    with _rpc_idx_lock:
        start = _rpc_idx % len(urls)
    ordered = urls[start:] + urls[:start]
    throttled = False
    last: Exception | None = None
    for url in ordered:
        for _ in range(retries):
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json", "User-Agent": _UA},
                method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    with _rpc_idx_lock:
                        _rpc_idx = (urls.index(url) + 1) % len(urls)
                    if sleep:
                        time.sleep(sleep)
                    return json.loads(r.read())
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (429, 503, 403):
                    throttled = True
                    time.sleep(max(sleep, 1.0))
                    continue
                break
            except Exception as exc:  # transport failures are retryable
                last = exc
                time.sleep(max(sleep, 0.5))
    if throttled:
        raise Throttled(str(last))
    raise RuntimeError(f"all RPC endpoints failed: {last}")


def encode_path(tokens: Iterable[str], fees: Iterable[int]) -> bytes:
    """Encode a V3 multi-hop path: token, fee, token, fee, ... token.

    Generalised from the original's fixed three-token form so an arbitrary
    number of intermediaries can be priced.
    """
    toks = [t.lower().removeprefix("0x") for t in tokens]
    fs = list(fees)
    if len(toks) != len(fs) + 1:
        raise ValueError(f"{len(toks)} tokens needs {len(toks)-1} fees, got {len(fs)}")
    out = bytes.fromhex(toks[0])
    for fee, tok in zip(fs, toks[1:]):
        out += int(fee).to_bytes(3, "big") + bytes.fromhex(tok)
    return out


def calldata(tokens: Iterable[str], fees: Iterable[int], amount_in: int) -> str:
    path = encode_path(tokens, fees)
    # quoteExactInput(bytes path, uint256 amountIn): offset, amount, len, payload
    head = (32 * 2).to_bytes(32, "big") + int(amount_in).to_bytes(32, "big")
    body = len(path).to_bytes(32, "big") + path.ljust(((len(path) + 31) // 32) * 32, b"\0")
    return QUOTE_SELECTOR + (head + body).hex()


@dataclass(frozen=True)
class QuoteJob:
    """One counterfactual question: this path, this size, this historical block."""
    job_id: str
    block: int
    tokens: tuple[str, ...]
    fees: tuple[int, ...]
    amount_in: int

    def request(self, rpc_id: int) -> dict:
        return {
            "jsonrpc": "2.0", "id": rpc_id, "method": "eth_call",
            "params": [{"to": UNISWAP_V3_QUOTER,
                        "data": calldata(self.tokens, self.fees, self.amount_in)},
                       hex(self.block)],
        }


def decode_quote(result: str) -> int | None:
    """Decode a uint256 amountOut; None when the call reverted (no liquidity)."""
    if not result or result in ("0x", "0x0"):
        return None
    try:
        return int(abi_decode(["uint256"], bytes.fromhex(result[2:]))[0])
    except Exception:
        return None


class QuoteStore:
    """Append-only raw store of request/response pairs, keyed by job id.

    Only SUCCESSFUL quotes count as cached. The earlier run stalled because
    throttled error lines were treated as answers, so a rerun skipped them and
    could never finish.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: set[str] | None = None

    def cached_ids(self) -> set[str]:
        if self._done is not None:
            return self._done
        done: set[str] = set()
        if self.path.exists():
            with gzip.open(self.path, "rt") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("amount_out") is not None:
                        done.add(rec["job_id"])
        self._done = done
        return done

    def append(self, records: list[dict]) -> None:
        if not records:
            return
        with gzip.open(self.path, "at") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        if self._done is not None:
            self._done.update(r["job_id"] for r in records
                              if r.get("amount_out") is not None)


def run_jobs(jobs: list[QuoteJob], store: QuoteStore, *, batch: int = 20,
             sleep: float = 0.6, progress: bool = True) -> dict[str, int]:
    """Quote every job not already answered, persisting raw responses.

    Returns counts of ok / reverted / throttled, so a caller can decide whether
    to keep going or back off.
    """
    todo = [j for j in jobs if j.job_id not in store.cached_ids()]
    stats = {"ok": 0, "reverted": 0, "throttled": 0, "skipped": len(jobs) - len(todo)}
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        payload = [j.request(n) for n, j in enumerate(chunk)]
        try:
            resp = rpc_post(payload, sleep=sleep)
        except Throttled:
            stats["throttled"] += len(chunk)
            time.sleep(5.0)
            continue
        except Exception:
            stats["throttled"] += len(chunk)
            continue
        by_id = {r.get("id"): r for r in (resp if isinstance(resp, list) else [resp])}
        recs = []
        for n, j in enumerate(chunk):
            r = by_id.get(n) or {}
            out = decode_quote(r.get("result", ""))
            recs.append({"job_id": j.job_id, "block": j.block,
                         "tokens": list(j.tokens), "fees": list(j.fees),
                         "amount_in": str(j.amount_in),
                         "amount_out": str(out) if out is not None else None,
                         "error": (r.get("error") or {}).get("message")})
            stats["ok" if out is not None else "reverted"] += 1
        store.append(recs)
        if progress and (i // batch) % 10 == 0:
            print(f"  quoted {i + len(chunk):,}/{len(todo):,}  {stats}", flush=True)
    return stats

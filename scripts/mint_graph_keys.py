#!/usr/bin/env python3
"""Top up the Graph API key pool by minting fresh free-tier Studio accounts.

Each key needs its own account, each account needs a burner Ethereum wallet and a
confirmed email, and each carries 100k queries a month. Confirmation codes are
read out of Gmail through the `glotl gmail` CLI, using +graphN aliases of one
inbox so they all land in the same place.

  .venv/bin/python scripts/mint_graph_keys.py --count 5 --email you@gmail.com

New keys are appended to GRAPH_API_KEYS in .env and recorded, with the wallet that
owns each account, in secrets/minted_graph_keys.json. That ledger is the only way
back into an account if a key has to be reissued, so it needs an out-of-band
backup; it holds private keys, so secrets/ is gitignored. Alias numbering resumes
from the ledger, so a rerun cannot collide with an account that already exists.

Spreading the free tier over many accounts is grey against The Graph's terms of
service; the Growth plan, about $2 per 100k queries, is the clean alternative.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.fetch.mint import alias_for, mint_one

LEDGER_PATH = ROOT / "secrets" / "minted_graph_keys.json"
ENV_PATH = ROOT / ".env"

# Studio confirmation emails come from ops@edgeandnode.com and print the code as
# "Confirmation Code: NNNNNN". They all share one subject, so Gmail collapses them
# into a single thread; `glotl gmail read` joins that thread's messages with a
# "=== From: … ===" header. Matching each block on the wallet address keeps this
# order-independent and immune to stale codes left by earlier runs.
CONFIRMATION_CODE_RE = re.compile(r"Confirmation Code:\s*([0-9]{4,8})", re.I)
MESSAGE_SPLIT_RE = re.compile(r"(?m)^=== From:.*$")


def gmail_code_reader(account: str):
    """Build a CodeReader pulling confirmation codes from an authorised Gmail inbox."""

    def run(args: list[str]) -> str:
        return subprocess.run(
            ["glotl", "gmail", *args, "--account", account],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout

    def reader(address: str) -> str | None:
        raw = run(["list", "--query", "from:edgeandnode.com newer_than:1h", "--limit", "10", "--json"])
        try:
            messages = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return None
        for thread_id in dict.fromkeys(m.get("thread_id") or m.get("id") for m in messages):
            if not thread_id:
                continue
            for block in MESSAGE_SPLIT_RE.split(run(["read", thread_id])):
                if address.lower() in block.lower():
                    hit = CONFIRMATION_CODE_RE.search(block)
                    if hit:
                        return hit.group(1)
        return None

    return reader


def append_to_env(keys: list[str]) -> int:
    """Append keys to GRAPH_API_KEYS in .env, de-duplicated. Returns the pool size."""
    pool: list[str] = []
    others: list[str] = []
    for line in ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []:
        if line.startswith("GRAPH_API_KEYS="):
            pool = [k.strip() for k in line.split("=", 1)[1].split(",") if k.strip()]
        elif line.strip():
            others.append(line)
    pool += [key for key in keys if key not in pool]
    ENV_PATH.write_text("\n".join(["GRAPH_API_KEYS=" + ",".join(pool)] + others) + "\n")
    ENV_PATH.chmod(0o600)
    return len(pool)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=5, help="how many accounts to mint")
    parser.add_argument("--email", required=True, help="inbox receiving the codes; +graphN aliases derive from it")
    args = parser.parse_args()

    reader = gmail_code_reader(args.email)
    ledger = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else []
    start = max((record["index"] for record in ledger), default=0) + 1
    minted: list[str] = []

    for index in range(start, start + args.count):
        email = alias_for(args.email, index)
        print(f"[mint] account {index}: {email} …", file=sys.stderr, flush=True)
        key = mint_one(index, email, reader, name=f"dvc-{index}")
        minted.append(key.key)
        ledger.append(vars(key))
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        LEDGER_PATH.write_text(json.dumps(ledger, indent=2) + "\n")  # after each, so a break resumes
        LEDGER_PATH.chmod(0o600)
        print(f"[mint]   -> key …{key.key[-6:]}", file=sys.stderr, flush=True)

    print(f"[mint] GRAPH_API_KEYS now holds {append_to_env(minted)} key(s)", file=sys.stderr)


if __name__ == "__main__":
    main()

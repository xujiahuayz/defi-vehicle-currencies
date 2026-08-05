#!/usr/bin/env python3
"""Mint free The Graph Studio API keys and keep the rotating pool topped up.

Each key needs its own Studio account, each account needs a burner Ethereum
wallet and a confirmed email, and each account carries its own 100k queries per
month. Confirmation codes are read out of Gmail through the `glotl gmail` CLI.

Examples:

  python3 scripts/mint_graph_keys.py status
  python3 scripts/mint_graph_keys.py mint --count 5 --email you@gmail.com
  python3 scripts/mint_graph_keys.py mint --count 5 --email you@gmail.com --write-env
  python3 scripts/mint_graph_keys.py sync-env

Every minted key is recorded in secrets/minted_graph_keys.json together with the
wallet that owns its account. That wallet is the only route back into the account
if the key is ever lost or has to be reissued, so the ledger matters as much as
the .env line. It holds private keys, so it is gitignored and never committed.

Multiplying the free tier across accounts is grey against The Graph's terms of
service. The paid Growth plan (about $2 per 100k queries) is the clean route when
volume justifies it.
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

from ddvc.fetch.graph import graph_keys
from ddvc.fetch.mint import MintedKey, alias_for, mint_one

LEDGER_PATH = ROOT / "secrets" / "minted_graph_keys.json"
ENV_PATH = ROOT / ".env"

# Studio confirmation emails come from ops@edgeandnode.com, identify the account by
# the registering wallet address in the body, and print the code as
# "Confirmation Code: NNNNNN".
CONFIRMATION_CODE_RE = re.compile(r"Confirmation Code:\s*([0-9]{4,8})", re.I)
# `glotl gmail read` joins the messages of a thread with a "=== From: … ===" header.
MESSAGE_SPLIT_RE = re.compile(r"(?m)^=== From:.*$")


def gmail_code_reader(gmail_account: str):
    """Build a CodeReader that pulls confirmation codes from a Gmail inbox.

    Shells out to `glotl gmail`, which is already authorised for the inbox. All the
    confirmation emails share one subject, so Gmail collapses them into a single
    thread; scanning every message block and matching on the wallet address keeps
    this order-independent and immune to stale codes left over from earlier runs.
    """

    def run(args: list[str]) -> str:
        return subprocess.run(
            ["glotl", "gmail", *args, "--account", gmail_account],
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
        seen: set[str] = set()
        for message in messages:
            thread_id = message.get("thread_id") or message.get("id")
            if not thread_id or thread_id in seen:
                continue
            seen.add(thread_id)
            body = run(["read", thread_id])
            for block in MESSAGE_SPLIT_RE.split(body):
                if address.lower() not in block.lower():
                    continue
                hit = CONFIRMATION_CODE_RE.search(block)
                if hit:
                    return hit.group(1)
        return None

    return reader


def read_ledger() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    return json.loads(LEDGER_PATH.read_text())


def write_ledger(records: list[dict]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(records, indent=2) + "\n")
    LEDGER_PATH.chmod(0o600)


def next_index(records: list[dict]) -> int:
    """First unused +alias index, so a resumed run never reuses an email."""
    return max((record["index"] for record in records), default=0) + 1


def merge_into_env(keys: list[str]) -> tuple[int, int]:
    """Append keys to GRAPH_API_KEYS in .env, de-duplicated. Returns (before, after)."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    existing: list[str] = []
    others: list[str] = []
    for line in lines:
        if line.startswith("GRAPH_API_KEYS="):
            existing = [k.strip() for k in line.split("=", 1)[1].split(",") if k.strip()]
        elif line.strip():
            others.append(line)
    merged = existing + [key for key in keys if key not in existing]
    ENV_PATH.write_text("\n".join(["GRAPH_API_KEYS=" + ",".join(merged)] + others) + "\n")
    ENV_PATH.chmod(0o600)
    return len(existing), len(merged)


def cmd_status(_: argparse.Namespace) -> None:
    records = read_ledger()
    pool = graph_keys()
    ledger_keys = {record["key"] for record in records}
    print(f"pool in .env:      {len(pool)} key(s)")
    print(f"ledger:            {len(records)} minted, next alias index {next_index(records)}")
    print(f"minted but unused: {len([k for k in ledger_keys if k not in pool])}")
    print(f"in pool, no wallet on file: {len([k for k in pool if k not in ledger_keys])}")
    for record in records:
        print(f"  {record['index']:>3}  {record['email']:<34} {record['address']}  …{record['key'][-6:]}")


def cmd_sync_env(_: argparse.Namespace) -> None:
    records = read_ledger()
    if not records:
        print("ledger is empty, nothing to sync", file=sys.stderr)
        return
    before, after = merge_into_env([record["key"] for record in records])
    print(f"GRAPH_API_KEYS: {before} -> {after} key(s)")


def cmd_mint(args: argparse.Namespace) -> None:
    reader = gmail_code_reader(args.gmail_account or args.email)
    records = read_ledger()
    start = args.start_index or next_index(records)
    minted: list[MintedKey] = []

    for index in range(start, start + args.count):
        email = alias_for(args.email, index)
        print(f"[mint] account {index}: {email} …", file=sys.stderr, flush=True)
        key = mint_one(
            index,
            email,
            reader,
            name=f"{args.name_prefix}-{index}",
            monthly_cap_usd=args.monthly_cap,
        )
        minted.append(key)
        records.append(
            {
                "index": key.index,
                "email": key.email,
                "address": key.address,
                "private_key": key.private_key,
                "key": key.key,
            }
        )
        write_ledger(records)  # persist after each one, so an interrupted run resumes
        print(f"[mint]   -> key …{key.key[-6:]}", file=sys.stderr, flush=True)

    if args.write_env:
        before, after = merge_into_env([key.key for key in minted])
        print(f"[mint] GRAPH_API_KEYS in .env: {before} -> {after} key(s)", file=sys.stderr)
    print("\n".join(key.key for key in minted))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show the pool, the ledger, and the next alias index").set_defaults(
        func=cmd_status
    )
    sub.add_parser("sync-env", help="merge every ledger key into GRAPH_API_KEYS in .env").set_defaults(
        func=cmd_sync_env
    )

    mint = sub.add_parser("mint", help="mint N fresh keys, one account each")
    mint.add_argument("--count", type=int, default=5, help="how many accounts to mint")
    mint.add_argument("--email", required=True, help="base inbox; +graphN aliases are derived from it")
    mint.add_argument("--gmail-account", help="`glotl gmail` account receiving the codes (default: --email)")
    mint.add_argument("--start-index", type=int, help="first alias index (default: next unused in the ledger)")
    mint.add_argument("--name-prefix", default="dvc", help="API-key name prefix")
    mint.add_argument("--monthly-cap", type=float, help="optional per-key monthlyCapUSD")
    mint.add_argument("--write-env", action="store_true", help="append the new keys to GRAPH_API_KEYS in .env")
    mint.set_defaults(func=cmd_mint)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

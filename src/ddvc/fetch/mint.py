"""Mint The Graph Studio API keys, one free account per key.

The Free Plan meters 100k queries a month per *account*, not per key, so more
quota means more accounts, and an account means a generated ("burner") Ethereum
wallet plus a confirmed email. This drives the Studio backend GraphQL API
directly: sign in with the wallet (SIWE), confirm an email channel with a code
read from the inbox, create the key. The browser route is closed, since Studio's
wallet connectors stay disabled under automation.

The wallet is the only way back into a minted account, so the caller must persist
it next to the key. Reading the confirmation code is left to an injected callable
so this module stays independent of any particular mail client.

Spreading the free tier over many accounts is grey against The Graph's terms of
service; the Growth plan, about $2 per 100k queries, is the clean alternative.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from ddvc.http import DEFAULT_USER_AGENT

STUDIO_API = "https://api.studio.thegraph.com/graphql"
SIWE_URI = "https://thegraph.com"
SIWE_CHAIN_ID = 42161  # Arbitrum One, where The Graph network lives

_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Content-Type": "application/json",
    "Origin": SIWE_URI,
    "Referer": SIWE_URI + "/",
}

# Given the registering wallet address, which the confirmation email carries in
# its body, return the code or None until it arrives.
CodeReader = Callable[[str], "str | None"]


class StudioError(RuntimeError):
    """A Studio GraphQL request came back with an ``errors`` block."""


def _gql(query: str, variables: dict, token: str | None = None) -> dict:
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(STUDIO_API, data=payload, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode())
    if body.get("errors"):
        raise StudioError(json.dumps(body["errors"]))
    return body["data"]


def alias_for(base_email: str, index: int) -> str:
    """``you@gmail.com`` -> ``you+graph12@gmail.com``, all delivered to one inbox."""
    local, _, domain = base_email.partition("@")
    return f"{local}+graph{index}@{domain}"


@dataclass
class MintedKey:
    """One minted key plus the burner wallet that owns its account."""

    index: int
    email: str
    address: str
    private_key: str
    key: str


def mint_one(index: int, email: str, reader: CodeReader, *, name: str) -> MintedKey:
    """Run the whole flow for one fresh account; returns the key and its wallet."""
    from eth_account import Account
    from eth_account.messages import encode_defunct

    account = Account.create()

    nonce = _gql("{ siweNonce { nonce } }", {})["siweNonce"]["nonce"]
    issued_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    message = (
        f"thegraph.com wants you to sign in with your Ethereum account:\n{account.address}\n\n"
        f"Sign in with Ethereum to the app.\n\nURI: {SIWE_URI}\nVersion: 1\n"
        f"Chain ID: {SIWE_CHAIN_ID}\nNonce: {nonce}\nIssued At: {issued_at}"
    )
    signature = Account.sign_message(encode_defunct(text=message), account.key).signature.hex()
    token = _gql(
        "mutation($a:String!,$m:String!,$s:String!,$n:Int){"
        "login(ethAddress:$a,message:$m,signature:$s,networkId:$n){token}}",
        {
            "a": account.address,
            "m": message,
            "s": signature if signature.startswith("0x") else "0x" + signature,
            "n": SIWE_CHAIN_ID,
        },
    )["login"]["token"]

    _gql(
        "mutation($v:String!){createChannel(value:$v,deliveryMethod:EMAIL,"
        "settings:[{type:CONFIRMATION_CODE,enabled:true}]){id}}",
        {"v": email},
        token,
    )
    _gql("mutation($e:String!){createConfirmationCode(emailAddress:$e)}", {"e": email}, token)

    # The confirmation email identifies the account by wallet address, never by
    # the +alias it was delivered to, so poll on the address.
    for _ in range(20):
        code = reader(account.address)
        if code:
            break
        time.sleep(6)
    else:
        raise TimeoutError(f"no confirmation code for {account.address} after 120s")
    _gql("mutation($c:String!){confirmCode(code:$c)}", {"c": code}, token)

    key = _gql(
        "mutation($n:String!,$d:String!){createApiKey(name:$n,displayName:$d){key}}",
        {"n": name, "d": name},
        token,
    )["createApiKey"]["key"]

    return MintedKey(index, email, account.address, account.key.hex(), key)

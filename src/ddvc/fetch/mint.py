"""Mint The Graph Studio API keys, one free account per key.

The Graph's Free Plan grants 100k queries/month **per account**, not per key, so a
fresh quota means a fresh account. An account is created by signing in with a
generated ("burner") Ethereum wallet and confirming an email address. This module
drives the Studio backend GraphQL API directly, without a browser:

    1. ``query siweNonce``                            -> nonce
    2. sign an EIP-4361 message with a generated key (``eth_account``)
    3. ``mutation login(...)``                        -> JWT bearer token; account created
    4. ``mutation createChannel(value=email, EMAIL)`` -> register the email channel
    5. ``mutation createConfirmationCode(email)``     -> code emailed
    6. read the code from the inbox (``CodeReader``) and ``mutation confirmCode``
    7. ``mutation createApiKey(...)``                 -> the API key string

Each account uses a distinct ``+alias`` of one inbox you control (Gmail delivers
``you+graph12@gmail.com`` to ``you@gmail.com``), so every confirmation code lands
in the same place and the reader picks it up automatically.

The generated wallet is the ONLY way back into a minted account, so the caller
must persist it alongside the key. ``scripts/mint_graph_keys.py`` writes both to
``secrets/minted_graph_keys.json``; the key on its own is not recoverable.

Spreading the free tier across several accounts is grey against The Graph's terms
of service. The Growth plan (about $2 per 100k queries) is the clean alternative.
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
SIWE_DOMAIN = "thegraph.com"
SIWE_URI = "https://thegraph.com"
SIWE_CHAIN_ID = 42161  # Arbitrum One, where The Graph network lives
SIWE_STATEMENT = "Sign in with Ethereum to the app."

_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Content-Type": "application/json",
    "Origin": SIWE_URI,
    "Referer": SIWE_URI + "/",
}


class StudioError(RuntimeError):
    """A Studio GraphQL request came back with an ``errors`` block."""


def _gql(query: str, variables: dict | None = None, token: str | None = None) -> dict:
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    request = urllib.request.Request(STUDIO_API, data=payload, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode())
    if body.get("errors"):
        raise StudioError(json.dumps(body["errors"]))
    return body["data"]


def login(account) -> str:
    """SIWE sign-in for ``account``; returns the bearer JWT. Creates the account."""
    from eth_account import Account
    from eth_account.messages import encode_defunct

    nonce = _gql("{ siweNonce { nonce } }")["siweNonce"]["nonce"]
    issued_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    message = (
        f"{SIWE_DOMAIN} wants you to sign in with your Ethereum account:\n{account.address}\n\n"
        f"{SIWE_STATEMENT}\n\nURI: {SIWE_URI}\nVersion: 1\nChain ID: {SIWE_CHAIN_ID}\n"
        f"Nonce: {nonce}\nIssued At: {issued_at}"
    )
    signature = Account.sign_message(encode_defunct(text=message), account.key).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    data = _gql(
        "mutation($a:String!,$m:String!,$s:String!,$n:Int){"
        "login(ethAddress:$a,message:$m,signature:$s,networkId:$n){token}}",
        {"a": account.address, "m": message, "s": signature, "n": SIWE_CHAIN_ID},
    )
    return data["login"]["token"]


def register_email(token: str, email: str) -> None:
    """Create the EMAIL channel and trigger a confirmation-code email."""
    _gql(
        "mutation($v:String!){createChannel(value:$v,deliveryMethod:EMAIL,"
        "settings:[{type:CONFIRMATION_CODE,enabled:true}]){id}}",
        {"v": email},
        token,
    )
    _gql("mutation($e:String!){createConfirmationCode(emailAddress:$e)}", {"e": email}, token)


def confirm_email(token: str, code: str) -> bool:
    """Confirm the email channel with the code read out of the inbox."""
    return bool(_gql("mutation($c:String!){confirmCode(code:$c)}", {"c": code}, token)["confirmCode"])


def create_api_key(token: str, name: str, monthly_cap_usd: float | None = None) -> str:
    """Create an API key on the now-confirmed account; returns the key string."""
    data = _gql(
        "mutation($n:String!,$d:String!,$c:Float){"
        "createApiKey(name:$n,displayName:$d,monthlyCapUSD:$c){key}}",
        {"n": name, "d": name, "c": monthly_cap_usd},
        token,
    )
    return data["createApiKey"]["key"]


# A confirmation code is read by a callable: given the registering wallet address
# (the confirmation email carries it in the body), return the code or None until
# it arrives. Keeping this injectable means the module has no hard dependency on
# any particular mail client.
CodeReader = Callable[[str], "str | None"]


def alias_for(base_email: str, index: int) -> str:
    """``you@gmail.com`` -> ``you+graph12@gmail.com``."""
    local, _, domain = base_email.partition("@")
    return f"{local}+graph{index}@{domain}"


def poll_code(reader: CodeReader, address: str, *, attempts: int = 20, delay: float = 6.0) -> str:
    """Poll ``reader`` until it yields a code, or raise once the attempts run out."""
    for _ in range(attempts):
        code = reader(address)
        if code:
            return code
        time.sleep(delay)
    raise TimeoutError(f"no confirmation code for {address} after {attempts * delay:.0f}s")


@dataclass
class MintedKey:
    """One minted key plus the burner wallet that owns its account."""

    index: int
    email: str
    address: str
    private_key: str
    key: str


def mint_one(
    index: int,
    email: str,
    reader: CodeReader,
    *,
    name: str,
    monthly_cap_usd: float | None = None,
) -> MintedKey:
    """Run the whole flow for a single fresh account; returns the key and its wallet."""
    from eth_account import Account

    account = Account.create()
    token = login(account)
    register_email(token, email)
    # The confirmation email identifies the account by wallet address, never by the
    # +alias it was delivered to, so poll on the address.
    code = poll_code(reader, account.address)
    confirm_email(token, code)
    key = create_api_key(token, name, monthly_cap_usd)
    return MintedKey(
        index=index,
        email=email,
        address=account.address,
        private_key=account.key.hex(),
        key=key,
    )

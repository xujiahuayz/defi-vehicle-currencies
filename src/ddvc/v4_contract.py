"""Canonical Ethereum mainnet contract identities and event topics for Uniswap V4 evidence."""

from __future__ import annotations

from eth_abi import decode as abi_decode
from eth_utils import keccak


UNISWAP_V4_POOL_MANAGER_ADDRESS = "0x000000000004444c5dc75cb358380d2e3de08a90"
UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK = 21_688_329
UNISWAP_V4_INITIALIZE_SIGNATURE = "Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)"
UNISWAP_V4_MODIFY_LIQUIDITY_SIGNATURE = "ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)"
UNISWAP_V4_SWAP_SIGNATURE = "Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)"
UNISWAP_V4_INITIALIZE_TOPIC = "0x" + keccak(text=UNISWAP_V4_INITIALIZE_SIGNATURE).hex()
UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC = "0x" + keccak(text=UNISWAP_V4_MODIFY_LIQUIDITY_SIGNATURE).hex()
UNISWAP_V4_SWAP_TOPIC = "0x" + keccak(text=UNISWAP_V4_SWAP_SIGNATURE).hex()


def _topic_address(value: object) -> str:
    topic = str(value or "").lower()
    if len(topic) != 66 or topic[2:26] != "0" * 24:
        raise ValueError("canonical V4 sender topic is not ABI-padded")
    return "0x" + topic[-40:]


def _bytes32(value: object, *, label: str) -> str:
    item = str(value or "").lower()
    if len(item) != 66 or not item.startswith("0x") or any(character not in "0123456789abcdef" for character in item[2:]):
        raise ValueError(f"canonical V4 {label} is not bytes32 hex")
    return item


def decode_v4_state_event_identity(record: dict[str, object], kind: str) -> dict[str, object]:
    """Independently decode exact PoolManager Swap/ModifyLiquidity identities."""

    topics = [str(topic).lower() for topic in record.get("topics") or []]
    expected = {
        "swap": (UNISWAP_V4_SWAP_TOPIC, ["int128", "int128", "uint160", "uint128", "int24", "uint24"]),
        "modify_liquidity": (UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC, ["int24", "int24", "int256", "bytes32"]),
    }
    if kind not in expected:
        raise ValueError(f"unsupported V4 state event kind: {kind}")
    topic, types = expected[kind]
    if (
        str(record.get("address") or "").lower() != UNISWAP_V4_POOL_MANAGER_ADDRESS
        or len(topics) != 3
        or topics[0] != topic
    ):
        raise ValueError(f"canonical V4 {kind} event has the wrong PoolManager or topic shape")
    data = bytes.fromhex(str(record.get("data") or "0x").removeprefix("0x"))
    if len(data) != 32 * len(types):
        raise ValueError(f"canonical V4 {kind} event has the wrong ABI data length")
    values = abi_decode(types, data)
    decoded = {
        "kind": kind,
        "pool": _bytes32(topics[1], label="PoolId"),
        "sender": _topic_address(topics[2]),
        "block_number": int(record["block_number"]),
        "block_hash": str(record["block_hash"]).lower(),
        "transaction_hash": str(record["transaction_hash"]).lower(),
        "transaction_index": int(record["transaction_index"]),
        "log_index": int(record["log_index"]),
    }
    if kind == "swap":
        decoded.update(zip(("amount0", "amount1", "sqrt_price_x96", "liquidity", "tick", "fee"), map(int, values), strict=True))
        if int(decoded["amount0"]) * int(decoded["amount1"]) >= 0 or int(decoded["sqrt_price_x96"]) <= 0:
            raise ValueError("canonical V4 Swap has invalid signed amounts or price state")
    else:
        tick_lower, tick_upper, liquidity_delta, salt = values
        if int(tick_lower) >= int(tick_upper):
            raise ValueError("canonical V4 ModifyLiquidity has an invalid tick interval")
        decoded.update({"tick_lower": int(tick_lower), "tick_upper": int(tick_upper), "liquidity_delta": int(liquidity_delta), "salt": "0x" + bytes(salt).hex()})
    return decoded


def validate_v4_provider_event_identity(
    provider: dict[str, object],
    exact: dict[str, object],
) -> None:
    """Require provider rows to name the same exact PoolManager chain event."""

    transaction = provider.get("transaction")
    pool = provider.get("pool")
    if not isinstance(pool, dict):
        raise ValueError("provider V4 row lacks a mapping pool identity")
    transaction_hash = transaction.get("id") if isinstance(transaction, dict) else transaction
    block = provider.get("blockNumber")
    if block is None and isinstance(transaction, dict):
        block = transaction.get("blockNumber")
    identity = (
        str(transaction_hash or "").lower(),
        int(block or -1),
        int(provider["logIndex"]) if provider.get("logIndex") is not None else -1,
        str(pool.get("id") or "").lower(),
    )
    expected = (
        exact["transaction_hash"],
        exact["block_number"],
        exact["log_index"],
        exact["pool"],
    )
    if identity != expected:
        raise ValueError("provider V4 row disagrees with exact PoolManager event identity")
    if exact["kind"] == "swap":
        payload = (
            int(provider["amount0Raw"]),
            int(provider["amount1Raw"]),
            int(provider["sqrtPriceX96"]),
            int(provider["tick"]),
        )
        expected_payload = (
            int(exact["amount0"]),
            int(exact["amount1"]),
            int(exact["sqrt_price_x96"]),
            int(exact["tick"]),
        )
    else:
        payload = (int(provider["tickLower"]), int(provider["tickUpper"]), int(provider["amount"]))
        expected_payload = (int(exact["tick_lower"]), int(exact["tick_upper"]), int(exact["liquidity_delta"]))
    if payload != expected_payload:
        raise ValueError("provider V4 row disagrees with exact PoolManager state payload")

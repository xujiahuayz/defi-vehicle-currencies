"""Uniswap V3 event semantics needed to reconstruct physical pool inventories."""

from __future__ import annotations

from eth_abi import decode as abi_decode
from eth_utils import keccak


EVENT_SIGNATURES = {
    "collect": "Collect(address,address,int24,int24,uint128,uint128)",
    "flash": "Flash(address,address,uint256,uint256,uint256,uint256)",
    "collect_protocol": "CollectProtocol(address,address,uint128,uint128)",
}
EVENT_TOPICS = {
    name: "0x" + keccak(text=signature).hex()
    for name, signature in EVENT_SIGNATURES.items()
}
EVENT_BY_TOPIC = {topic: name for name, topic in EVENT_TOPICS.items()}


def decode_inventory_log(log: dict) -> dict[str, object]:
    """Decode one inventory-changing V3 log into signed raw token deltas."""

    topics = [str(value).lower() for value in log.get("topics") or []]
    if not topics or topics[0] not in EVENT_BY_TOPIC:
        raise ValueError("log is not a registered V3 inventory event")
    event_type = EVENT_BY_TOPIC[topics[0]]
    data = bytes.fromhex(str(log.get("data") or "0x").removeprefix("0x"))
    if event_type == "collect":
        _recipient, amount0, amount1 = abi_decode(
            ["address", "uint128", "uint128"], data
        )
        delta0, delta1 = -int(amount0), -int(amount1)
    elif event_type == "flash":
        amount0, amount1, paid0, paid1 = abi_decode(
            ["uint256", "uint256", "uint256", "uint256"], data
        )
        delta0, delta1 = int(paid0) - int(amount0), int(paid1) - int(amount1)
    else:
        amount0, amount1 = abi_decode(["uint128", "uint128"], data)
        delta0, delta1 = -int(amount0), -int(amount1)
    block = int(str(log["blockNumber"]), 16)
    log_index = int(str(log["logIndex"]), 16)
    tx_hash = str(log["transactionHash"]).lower()
    pool = str(log["address"]).lower()
    return {
        "event_type": event_type,
        "pool": pool,
        "block_number": block,
        "log_index": log_index,
        "tx_hash": tx_hash,
        "event_id": f"{tx_hash}:{log_index}",
        "amount0_delta_raw": delta0,
        "amount1_delta_raw": delta1,
    }

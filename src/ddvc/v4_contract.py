"""Canonical Ethereum mainnet contract identities and event topics for Uniswap V4 evidence."""

from __future__ import annotations

from eth_utils import keccak


UNISWAP_V4_POOL_MANAGER_ADDRESS = "0x000000000004444c5dc75cb358380d2e3de08a90"
UNISWAP_V4_SWAP_SIGNATURE = "Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)"
UNISWAP_V4_SWAP_TOPIC = "0x" + keccak(text=UNISWAP_V4_SWAP_SIGNATURE).hex()

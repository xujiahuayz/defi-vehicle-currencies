"""GraphQL schema specifications for raw over-fetching.

These specs select more fields than the current outline strictly needs. The goal
is a one-shot raw layer that supports route reconstruction, LP repositioning,
liquidity concentration, direct-vs-vehicle route costs, V4 receipt matching, and
future robustness work without repeated network fetches.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntitySpec:
    stream: str
    entity: str
    fields: str
    time_field: str = "timestamp"
    date_field: str | None = None


@dataclass(frozen=True)
class SchemaSpec:
    name: str
    entities: tuple[EntitySpec, ...]


UNI_V3_LIQUIDITY_FIELDS = (
    "id transaction { id blockNumber timestamp } timestamp pool { id token0 { id symbol } "
    "token1 { id symbol } feeTier } owner origin sender amount amount0 amount1 "
    "tickLower tickUpper logIndex"
)


SCHEMAS: dict[str, SchemaSpec] = {
    "uniswap_v2": SchemaSpec(
        name="uniswap_v2",
        entities=(
            EntitySpec(
                stream="swaps",
                entity="swaps",
                fields=(
                    "id transaction { id blockNumber timestamp } timestamp pair { id token0 { id "
                    "symbol decimals } token1 { id symbol decimals } } sender to amount0In "
                    "amount0Out amount1In amount1Out amountUSD logIndex"
                ),
            ),
            EntitySpec(
                stream="daily",
                entity="pairDayDatas",
                date_field="date",
                fields=(
                    "id date pairAddress dailyVolumeUSD reserveUSD reserve0 reserve1 "
                    "token0 { id symbol decimals } token1 { id symbol decimals }"
                ),
            ),
            EntitySpec(
                stream="hourly_reserves",
                entity="pairHourDatas",
                time_field="hourStartUnix",
                fields=(
                    "id hourStartUnix pair { id token0 { id symbol decimals } token1 { id "
                    "symbol decimals } } reserve0 reserve1 hourlyVolumeUSD"
                ),
            ),
        ),
    ),
    "uniswap_v3": SchemaSpec(
        name="uniswap_v3",
        entities=(
            EntitySpec(
                stream="swaps",
                entity="swaps",
                fields=(
                    "id transaction { id blockNumber timestamp } timestamp pool { id feeTier "
                    "token0 { id symbol decimals } token1 { id symbol decimals } } sender "
                    "recipient origin amount0 amount1 amountUSD sqrtPriceX96 tick logIndex"
                ),
            ),
            EntitySpec(
                stream="daily",
                entity="poolDayDatas",
                date_field="date",
                fields=(
                    "id date volumeUSD tvlUSD feesUSD liquidity sqrtPrice token0Price "
                    "token1Price tick pool { id feeTier token0 { id symbol decimals } token1 { id "
                    "symbol decimals } }"
                ),
            ),
            EntitySpec(stream="mints", entity="mints", fields=UNI_V3_LIQUIDITY_FIELDS),
            EntitySpec(stream="burns", entity="burns", fields=UNI_V3_LIQUIDITY_FIELDS),
        ),
    ),
    "uniswap_v4": SchemaSpec(
        name="uniswap_v4",
        entities=(
            EntitySpec(
                stream="swaps",
                entity="swaps",
                fields=(
                    "id transaction { id blockNumber timestamp } timestamp pool { id feeTier "
                    "token0 { id symbol decimals } token1 { id symbol decimals } } sender origin "
                    "amount0 amount1 amountUSD sqrtPriceX96 tick logIndex"
                ),
            ),
            EntitySpec(
                stream="daily",
                entity="poolDayDatas",
                date_field="date",
                fields=(
                    "id date volumeUSD tvlUSD feesUSD liquidity sqrtPrice token0Price "
                    "token1Price tick pool { id feeTier token0 { id symbol decimals } token1 { id "
                    "symbol decimals } }"
                ),
            ),
            EntitySpec(
                stream="modify_liquidities",
                entity="modifyLiquidities",
                fields=(
                    "id transaction { id blockNumber timestamp } timestamp pool { id token0 { id "
                    "symbol decimals } token1 { id symbol decimals } } sender origin amount amount0 "
                    "amount1 tickLower tickUpper logIndex"
                ),
            ),
        ),
    ),
    "messari": SchemaSpec(
        name="messari",
        entities=(
            EntitySpec(
                stream="swaps",
                entity="swaps",
                fields=(
                    "id hash logIndex blockNumber timestamp tokenIn { id symbol decimals } "
                    "amountIn amountInUSD tokenOut { id symbol decimals } amountOut "
                    "amountOutUSD pool { id symbol inputTokens { id symbol decimals } }"
                ),
            ),
            EntitySpec(
                stream="daily",
                entity="liquidityPoolDailySnapshots",
                fields=(
                    "id timestamp dailyVolumeUSD totalValueLockedUSD inputTokenBalances "
                    "inputTokenWeights pool { id symbol inputTokens { id symbol decimals } }"
                ),
            ),
        ),
    ),
    "balancer": SchemaSpec(
        name="balancer",
        entities=(
            EntitySpec(
                stream="swaps",
                entity="swaps",
                fields=(
                    "id tokenIn tokenInSym tokenOut tokenOutSym tokenAmountIn tokenAmountOut "
                    "valueUSD poolId { id } timestamp block tx"
                ),
            ),
            EntitySpec(
                stream="daily",
                entity="poolSnapshots",
                fields=(
                    "id timestamp swapVolume swapFees liquidity pool { id poolType swapFee "
                    "tokens { address symbol decimals balance weight } }"
                ),
            ),
        ),
    ),
}


def get_schema(name: str) -> SchemaSpec:
    try:
        return SCHEMAS[name]
    except KeyError:
        known = ", ".join(sorted(SCHEMAS))
        raise KeyError(f"unknown schema {name!r}; known schemas: {known}") from None

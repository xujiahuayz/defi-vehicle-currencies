"""GraphQL schema specifications for raw over-fetching.

These specs select more fields than the current outline strictly needs. The goal
is a one-shot raw layer that supports route reconstruction, LP repositioning,
liquidity concentration, direct-vs-vehicle route costs, V4 receipt matching, and
future robustness work without repeated network fetches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FetchMode = Literal[
    "day_partitioned",
    "global_historical",
    "static_snapshot",
    "block_pinned_configuration",
    "head_validation_only",
]


@dataclass(frozen=True)
class EntitySpec:
    stream: str
    entity: str
    fields: str
    time_field: str = "timestamp"
    date_field: str | None = None
    fetch_mode: FetchMode = "day_partitioned"
    admission_mode: str = "active_stream"


@dataclass(frozen=True)
class SchemaSpec:
    name: str
    entities: tuple[EntitySpec, ...]


UNI_V3_MINT_FIELDS = (
    "id transaction { id blockNumber timestamp } timestamp pool { id token0 { id symbol } "
    "token1 { id symbol } feeTier } owner origin sender amount amount0 amount1 "
    "tickLower tickUpper logIndex"
)

UNI_V3_BURN_FIELDS = (
    "id transaction { id blockNumber timestamp } timestamp pool { id token0 { id symbol } "
    "token1 { id symbol } feeTier } owner origin amount amount0 amount1 "
    "tickLower tickUpper logIndex"
)

UNISWAP_V4_STATIC_FIELDS = (
    "id pool { id feeTier: fee tickSpacing hooks token0 { id symbol decimals } "
    "token1 { id symbol decimals } }"
)


SCHEMAS: dict[str, SchemaSpec] = {
    "uniswap_v1": SchemaSpec(
        name="uniswap_v1",
        entities=(
            EntitySpec(
                stream="swaps",
                entity="transactions",
                fields=(
                    "id exchangeAddress block timestamp user fee "
                    "tokenPurchaseEvents { id ethAmount tokenAmount tokenFee ethFee } "
                    "ethPurchaseEvents { id ethAmount tokenAmount tokenFee ethFee }"
                ),
            ),
            EntitySpec(
                stream="daily",
                entity="exchangeHistoricalDatas",
                fields=(
                    "id exchangeAddress type timestamp ethLiquidity tokenLiquidity ethBalance "
                    "tokenBalance combinedBalanceInEth combinedBalanceInUSD tokenPriceUSD price "
                    "tradeVolumeToken tradeVolumeEth tradeVolumeUSD totalTxsCount feeInEth"
                ),
            ),
        ),
    ),
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
            # Liquidity events, needed because `pairHourDatas` reserves are an
            # end-of-hour snapshot and unwinding an hour's swaps backwards from it
            # only reconstructs pre-trade state when nothing OTHER than a swap moved
            # the reserves. A mint, burn or direct transfer breaks that, which is
            # detectable from reserve continuity but not correctable without these
            # streams, so roughly 3.2% of pool-hours are currently dropped. The
            # exclusion is not random, since liquidity events concentrate in actively
            # managed and newly launched pools, so recovering them removes a
            # selection concern rather than merely adding coverage.
            EntitySpec(
                stream="mints",
                entity="mints",
                fields=(
                    "id timestamp transaction { id blockNumber timestamp } "
                    "pair { id token0 { id symbol decimals } token1 { id symbol decimals } } "
                    "liquidity amount0 amount1 amountUSD sender to logIndex"
                ),
            ),
            EntitySpec(
                stream="burns",
                entity="burns",
                fields=(
                    "id timestamp transaction { id blockNumber timestamp } "
                    "pair { id token0 { id symbol decimals } token1 { id symbol decimals } } "
                    "liquidity amount0 amount1 amountUSD sender to logIndex needsComplete"
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
            EntitySpec(stream="mints", entity="mints", fields=UNI_V3_MINT_FIELDS),
            EntitySpec(stream="burns", entity="burns", fields=UNI_V3_BURN_FIELDS),
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
                    "tickSpacing hooks token0 { id symbol decimals } "
                    "token1 { id symbol decimals } } sender origin "
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
                    "id timestamp amounts totalShares swapVolume swapFees liquidity "
                    "swapsCount pool { id poolType poolTypeVersion swapFee amp totalWeight "
                    "tokensList tokens { address symbol decimals balance weight } }"
                ),
            ),
            # Balancer balances move on joins and exits as well as on swaps, so a pool's
            # within-day balance path cannot be replayed from swaps alone. Without this stream
            # any pool taking a mid-day join has an unobservable balance jump, which is
            # indistinguishable from the pool running different maths.
            EntitySpec(
                stream="joins_exits",
                entity="joinExits",
                fields=(
                    "id type sender user amounts valueUSD timestamp block tx "
                    "pool { id tokensList }"
                ),
            ),
        ),
    ),
}


def _source_specific_schema(name: str, shared: SchemaSpec) -> SchemaSpec:
    """Give one deployment an independent contract identity while sharing fragments."""

    return SchemaSpec(name=name, entities=shared.entities)


# These deployments happened to begin with the same schema family, but live
# introspection now diverges.  Contract identity is therefore per source; immutable
# field fragments remain shared until a source-specific field is frozen.
SCHEMAS["curve"] = _source_specific_schema("curve", SCHEMAS["messari"])
SCHEMAS["sushiswap_v3"] = _source_specific_schema(
    "sushiswap_v3", SCHEMAS["messari"]
)
SCHEMAS["sushiswap_v2"] = _source_specific_schema(
    "sushiswap_v2", SCHEMAS["uniswap_v2"]
)


def get_schema(name: str) -> SchemaSpec:
    try:
        return SCHEMAS[name]
    except KeyError:
        known = ", ".join(sorted(SCHEMAS))
        raise KeyError(f"unknown schema {name!r}; known schemas: {known}") from None

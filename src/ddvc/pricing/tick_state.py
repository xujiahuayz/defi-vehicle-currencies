"""Shared initialized-tick state updates and transaction-order replay."""

from __future__ import annotations

from collections.abc import Iterator

from ddvc.fetch.raw import block_value, timestamp_value


def event_order(row: dict) -> tuple[int, int]:
    """Canonical within-chain order for a raw swap or liquidity event."""
    return (
        int(block_value(row) or timestamp_value(row) or 0),
        int(row.get("logIndex") or 0),
    )


def apply_tick_change(ticks: dict[int, int], row: dict, *, sign: int = 1) -> None:
    """Apply one signed liquidity change to its lower and upper boundary ticks."""
    try:
        amount = sign * int(row.get("amount") or 0)
        lower, upper = int(row["tickLower"]), int(row["tickUpper"])
    except (TypeError, ValueError, KeyError):
        return
    if amount == 0:
        return
    ticks[lower] = ticks.get(lower, 0) + amount
    ticks[upper] = ticks.get(upper, 0) - amount
    if ticks[lower] == 0:
        del ticks[lower]
    if ticks.get(upper) == 0:
        del ticks[upper]


def active_liquidity(ticks: dict[int, int], current_tick: int) -> int:
    """Active liquidity implied by boundary-tick net changes at ``current_tick``."""
    return sum(value for tick, value in ticks.items() if tick <= current_tick)


def iter_pretrade_states(
    swaps: list[dict],
    changes: list[tuple[int, dict]],
    initial_ticks: dict[int, int],
) -> Iterator[tuple[dict, dict, dict[int, int]]]:
    """Yield consecutive swaps with the tick map immediately before the latter.

    ``changes`` carries an explicit sign because V3 splits mints and burns while V4
    stores signed deltas in one stream. Liquidity and swap events are interleaved by
    block and log index, preventing target-day liquidity from leaking backward.
    """
    stream = [
        (*event_order(row), 0, index, sign, row)
        for index, (sign, row) in enumerate(changes)
    ]
    stream.extend(
        (*event_order(row), 1, index, 0, row)
        for index, row in enumerate(swaps)
    )
    ticks = dict(initial_ticks)
    previous_swap: dict | None = None
    for _block, _log_index, kind, _sequence, sign, row in sorted(stream):
        if kind == 0:
            apply_tick_change(ticks, row, sign=sign)
            continue
        if previous_swap is not None:
            yield previous_swap, row, dict(ticks)
        previous_swap = row

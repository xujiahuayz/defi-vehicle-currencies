"""Deterministic work partitions for ordered, stateful inputs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar


T = TypeVar("T")


def weighted_contiguous_chunks(
    items: Sequence[T],
    weights: Sequence[int],
    parts: int,
) -> list[list[T]]:
    """Split ordered items into exactly ``parts`` near-minimax contiguous chunks."""
    if len(items) != len(weights):
        raise ValueError("items and weights must have the same length")
    if parts < 1:
        raise ValueError("parts must be positive")
    if not items:
        return []
    normalized = [max(1, int(weight)) for weight in weights]
    count = min(parts, len(items))

    def chunks_needed(capacity: int) -> int:
        chunks = 1
        load = 0
        for weight in normalized:
            if load and load + weight > capacity:
                chunks += 1
                load = 0
            load += weight
        return chunks

    lower = max(max(normalized), (sum(normalized) + count - 1) // count)
    upper = sum(normalized)
    while lower < upper:
        middle = (lower + upper) // 2
        if chunks_needed(middle) <= count:
            upper = middle
        else:
            lower = middle + 1
    capacity = lower

    boundaries: list[tuple[int, int]] = []
    end = len(items)
    for remaining in range(count, 0, -1):
        start = end - 1
        load = normalized[start]
        while start > remaining - 1 and load + normalized[start - 1] <= capacity:
            start -= 1
            load += normalized[start]
        boundaries.append((start, end))
        end = start
    return [list(items[start:end]) for start, end in reversed(boundaries)]

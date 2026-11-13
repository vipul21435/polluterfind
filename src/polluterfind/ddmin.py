"""Delta debugging over an ordered list of tests.

``ddmin`` is the minimising algorithm of Zeller and Hildebrandt (2002), "Simplifying and
isolating failure-inducing input". Given a list for which an oracle reports the failure and the
precondition that the empty list does not, it returns a sub-list that still reproduces and is
1-minimal: removing any single element makes the failure go away.

Sub-lists always keep the relative order of the input, because the input here is a test order
and the order is part of what causes the failure.

``bisect_single`` is a cheaper path for the common case of one polluter: it assumes a single
element reproduces on its own and binary searches with one oracle call per level, then confirms.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


def split(items: Sequence[T], n: int) -> list[list[T]]:
    """Split ``items`` into ``n`` contiguous, order-preserving chunks of near-equal size."""
    if n < 1:
        raise ValueError("n must be at least 1")
    n = min(n, len(items)) or 1
    size, extra = divmod(len(items), n)
    chunks: list[list[T]] = []
    start = 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        chunks.append(list(items[start:end]))
        start = end
    return chunks


def ddmin(items: Sequence[T], reproduces: Callable[[list[T]], bool]) -> list[T]:
    """Return a 1-minimal, order-preserving sub-list of ``items`` for which ``reproduces`` holds.

    Preconditions (checked by the caller, not here): ``reproduces(list(items))`` is true and
    ``reproduces([])`` is false. The oracle may return false for an unresolved outcome; ddmin
    treats that the same as "does not reproduce", as in the original algorithm.
    """
    current = list(items)
    n = 2
    while len(current) >= 2:
        chunks = split(current, n)
        n = len(chunks)
        reduced = False
        for chunk in chunks:
            if reproduces(chunk):
                current, n, reduced = chunk, 2, True
                break
        if not reduced and n > 2:
            # With two chunks the complements are the chunks themselves, already tested.
            for i in range(n):
                complement = [x for j, chunk in enumerate(chunks) if j != i for x in chunk]
                if reproduces(complement):
                    current, n, reduced = complement, max(n - 1, 2), True
                    break
        if not reduced:
            if n >= len(current):
                break
            n = min(len(current), 2 * n)
    return current


def bisect_single(items: Sequence[T], reproduces: Callable[[list[T]], bool]) -> T | None:
    """Find one element that reproduces on its own, assuming such an element exists.

    Each level runs only the left half; when it does not reproduce, the element is assumed to be
    in the right half. That costs about ``log2(len(items))`` calls plus one confirming call on the
    final element. Returns ``None`` when the confirmation fails, which means the assumption was
    wrong (the failure needs two or more elements together) and the caller should use ``ddmin``.
    """
    current = list(items)
    if not current:
        return None
    while len(current) > 1:
        mid = len(current) // 2
        left = current[:mid]
        current = left if reproduces(left) else current[mid:]
    return current[0] if reproduces(current) else None


def is_one_minimal(subset: Sequence[T], reproduces: Callable[[list[T]], bool]) -> bool:
    """True when ``subset`` reproduces and removing any one element stops it reproducing."""
    items = list(subset)
    if not reproduces(items):
        return False
    return all(not reproduces(items[:i] + items[i + 1 :]) for i in range(len(items)))

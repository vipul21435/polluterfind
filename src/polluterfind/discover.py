"""Find order-dependent tests by running the whole suite in a few orders, then localise each.

The suite runs in the given order, reversed, and in ``k`` seeded random orders, once each. A
test that passes in one of those orders and fails in another is a candidate. For a candidate,
``find`` runs first on an order where it failed (a victim shows up there); if that does not
classify it as a victim, ``find`` runs on an order where it passed (a brittle test shows up
there). Candidates that are neither are reported with their verification, typically flaky.
"""

from __future__ import annotations

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from .junit import FAILING, PASSED
from .runner import BaseRunner
from .search import FindResult, find
from .verify import BRITTLE, VICTIM


@dataclass
class OrderRun:
    name: str
    order: list[str]
    failed: list[str]
    order_respected: bool


@dataclass
class Candidate:
    test: str
    outcomes: dict[str, str]
    attempts: list[FindResult] = field(default_factory=list)

    @property
    def result(self) -> FindResult | None:
        """The attempt that classified the test as order-dependent, else the last attempt."""
        for attempt in self.attempts:
            if attempt.kind in (VICTIM, BRITTLE):
                return attempt
        return self.attempts[-1] if self.attempts else None


@dataclass
class DiscoverResult:
    orders: list[OrderRun]
    candidates: list[Candidate]
    runs: int = 0
    cache_hits: int = 0
    seconds: float = 0.0


def suite_orders(order: Sequence[str], k: int, seed: int) -> list[tuple[str, list[str]]]:
    """The given order, its reverse and ``k`` shuffles from seeds ``seed``, ``seed + 1``, ..."""
    named = [("given", list(order)), ("reversed", list(reversed(order)))]
    for i in range(k):
        shuffled = list(order)
        random.Random(seed + i).shuffle(shuffled)
        named.append((f"random seed {seed + i}", shuffled))
    return named


def discover(
    runner: BaseRunner,
    order: Sequence[str],
    *,
    orders: int = 3,
    seed: int = 0,
    reruns: int = 3,
    method: str = "auto",
    max_cleaners: int = 1,
    search: bool = True,
) -> DiscoverResult:
    """Run the suite in several orders, list the tests whose outcome changed, and search each."""
    start = time.perf_counter()
    runs0, hits0 = runner.stats.runs, runner.stats.cache_hits
    named = suite_orders(order, orders, seed)
    results = runner.run_many([o for _, o in named])
    order_runs = [
        OrderRun(name, o, [t for t in o if r.failed(t)], r.order_respected)
        for (name, o), r in zip(named, results, strict=True)
    ]
    candidates = []
    for test in order:
        outcomes = {name: r.outcome(test) for (name, _), r in zip(named, results, strict=True)}
        values = set(outcomes.values())
        if PASSED in values and values & FAILING:
            candidates.append(Candidate(test, outcomes))

    if search:
        by_name = dict(named)
        for candidate in candidates:
            failing = next(n for n, o in candidate.outcomes.items() if o in FAILING)
            passing = next(n for n, o in candidate.outcomes.items() if o == PASSED)
            for name in (failing, passing):
                attempt = find(
                    runner,
                    by_name[name],
                    candidate.test,
                    reruns=reruns,
                    max_cleaners=max_cleaners,
                    method=method,
                )
                candidate.attempts.append(attempt)
                if attempt.kind in (VICTIM, BRITTLE):
                    break

    return DiscoverResult(
        orders=order_runs,
        candidates=candidates,
        runs=runner.stats.runs - runs0,
        cache_hits=runner.stats.cache_hits - hits0,
        seconds=time.perf_counter() - start,
    )

"""Check that a test really depends on the order, and classify it.

The terms follow Shi et al. (2019), "iFixFlakies": a *victim* passes alone and fails after some
other test (its polluter) has run; a *brittle* test fails alone and passes only after some other
test (its state-setter) has run. A test whose outcome changes between reruns of one and the same
order is flaky regardless of order, and delta debugging over the order cannot explain it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import NormalDist

from .junit import FAILING, PASSED
from .runner import CommandRunner

VICTIM = "victim"
BRITTLE = "brittle"
NOT_ORDER_DEPENDENT = "not-order-dependent"
FLAKY = "flaky"
UNRESOLVED = "unresolved"


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (Wilson, 1927)."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= successes <= n:
        raise ValueError("successes must lie between 0 and n")
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class Tally:
    """Victim outcomes over reruns of one order."""

    passed: int = 0
    failed: int = 0
    unresolved: int = 0
    outcomes: list[str] = field(default_factory=list)

    def add(self, outcome: str) -> None:
        self.outcomes.append(outcome)
        if outcome == PASSED:
            self.passed += 1
        elif outcome in FAILING:
            self.failed += 1
        else:
            self.unresolved += 1

    @property
    def resolved(self) -> int:
        return self.passed + self.failed

    def pass_interval(self, confidence: float = 0.95) -> tuple[float, float]:
        return wilson_interval(self.passed, self.resolved, confidence)

    @property
    def always_passes(self) -> bool:
        return self.resolved > 0 and self.failed == 0

    @property
    def always_fails(self) -> bool:
        return self.resolved > 0 and self.passed == 0

    @property
    def mixed(self) -> bool:
        return self.passed > 0 and self.failed > 0


def classify(alone: Tally, after_prefix: Tally) -> str:
    """Victim, brittle, flaky (mixed results within one order), not order-dependent, or
    unresolved (no pass or fail recorded, e.g. the id was skipped, missing or timed out)."""
    if alone.mixed or after_prefix.mixed:
        return FLAKY
    if alone.resolved == 0 or after_prefix.resolved == 0:
        return UNRESOLVED
    if alone.always_passes and after_prefix.always_fails:
        return VICTIM
    if alone.always_fails and after_prefix.always_passes:
        return BRITTLE
    return NOT_ORDER_DEPENDENT


@dataclass
class Verification:
    victim: str
    kind: str
    prefix: list[str]
    alone: Tally
    after_prefix: Tally
    reruns: int


def prefix_of(order: Sequence[str], victim: str) -> list[str]:
    """The tests that run before ``victim`` in ``order``."""
    try:
        return list(order[: list(order).index(victim)])
    except ValueError:
        raise ValueError(f"{victim} is not in the test order") from None


def verify(
    runner: CommandRunner, order: Sequence[str], victim: str, reruns: int = 3
) -> Verification:
    """Run the victim alone and after its full prefix, ``reruns`` times each, and classify."""
    if reruns < 1:
        raise ValueError("reruns must be at least 1")
    prefix = prefix_of(order, victim)
    alone, after_prefix = Tally(), Tally()
    for _ in range(reruns):
        alone.add(runner.run([victim], fresh=True).outcome(victim))
        after_prefix.add(runner.run([*prefix, victim], fresh=True).outcome(victim))
    return Verification(victim, classify(alone, after_prefix), prefix, alone, after_prefix, reruns)

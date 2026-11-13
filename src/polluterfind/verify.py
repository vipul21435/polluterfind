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

from .junit import FAILING, PASSED, SKIPPED
from .runner import BaseRunner, RunResult

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
    # The bounds are exactly 0 for no successes and exactly 1 for all successes; computed as
    # centre - half they can miss by a rounding error (2.8e-17 for n = 4 at 95 %).
    low = 0.0 if successes == 0 else max(0.0, centre - half)
    high = 1.0 if successes == n else min(1.0, centre + half)
    return low, high


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
    unresolved_run: dict | None = None


def unresolved_detail(run: RunResult, victim: str, which: str) -> dict:
    """Why a run gave no pass or fail for ``victim``: reason, exit code and last output."""
    outcome = run.outcome(victim)
    if outcome == SKIPPED:
        reason = "the victim was skipped"
    elif run.problem:
        reason = run.problem
    else:
        reason = f"exit code {run.returncode}, but the victim is not in the JUnit report"
    return {
        "order": which,
        "outcome": outcome,
        "reason": reason,
        "returncode": run.returncode,
        "output_tail": run.tail(),
    }


def prefix_of(order: Sequence[str], victim: str) -> list[str]:
    """The tests that run before ``victim`` in ``order``."""
    try:
        return list(order[: list(order).index(victim)])
    except ValueError:
        raise ValueError(f"{victim} is not in the test order") from None


def verify(runner: BaseRunner, order: Sequence[str], victim: str, reruns: int = 3) -> Verification:
    """Run the victim alone and after its full prefix, ``reruns`` times each, and classify.

    The two orders alternate (alone, prefix, alone, ...), and with ``jobs > 1`` they run
    ``jobs`` at a time.
    """
    if reruns < 1:
        raise ValueError("reruns must be at least 1")
    prefix = prefix_of(order, victim)
    alone, after_prefix = Tally(), Tally()
    runs = runner.run_many([[victim], [*prefix, victim]] * reruns, fresh=True)
    detail = None
    for i, run in enumerate(runs):
        (alone if i % 2 == 0 else after_prefix).add(run.outcome(victim))
        if detail is None and not (run.passed(victim) or run.failed(victim)):
            detail = unresolved_detail(run, victim, "alone" if i % 2 == 0 else "after prefix")
    kind = classify(alone, after_prefix)
    return Verification(victim, kind, prefix, alone, after_prefix, reruns, detail)

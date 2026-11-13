"""Localise the cause of an order-dependent test.

For a victim, the search looks for a 1-minimal set of polluters among the tests that ran before
it: their presence (in suite order) makes the victim fail. For a brittle test it looks for a
1-minimal set of state-setters: their presence makes it pass. The single-polluter bisection runs
first; when its confirmation fails, ddmin takes over. For a victim, it then looks for cleaners:
tests that, run between the polluters and the victim, make the victim pass again.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from .ddmin import bisect_single, ddmin
from .runner import CommandRunner
from .verify import BRITTLE, VICTIM, Tally, Verification, verify


@dataclass
class FindResult:
    verification: Verification
    causes: list[str] = field(default_factory=list)
    method: str = "none"
    confirmation: Tally | None = None
    cleaners: list[str] = field(default_factory=list)
    cleaner_candidates_checked: int = 0
    runs: int = 0
    cache_hits: int = 0
    tests_executed: int = 0
    seconds: float = 0.0
    repro_command: str = ""
    cleaner_command: str = ""

    @property
    def victim(self) -> str:
        return self.verification.victim

    @property
    def kind(self) -> str:
        return self.verification.kind

    @property
    def role(self) -> str:
        return "state-setter" if self.kind == BRITTLE else "polluter"

    @property
    def confirmed(self) -> bool:
        if self.confirmation is None or not self.causes:
            return False
        if self.kind == VICTIM:
            return self.confirmation.always_fails
        return self.confirmation.always_passes


def find(
    runner: CommandRunner,
    order: Sequence[str],
    victim: str,
    *,
    reruns: int = 3,
    max_cleaners: int = 1,
    verification: Verification | None = None,
) -> FindResult:
    """Verify ``victim`` against ``order``, then search for its polluters or state-setters."""
    start = time.perf_counter()
    runs0, hits0, tests0 = runner.stats.runs, runner.stats.cache_hits, runner.stats.tests_executed
    checked = verification or verify(runner, order, victim, reruns)
    result = FindResult(checked)

    if checked.kind in (VICTIM, BRITTLE):
        want_failure = checked.kind == VICTIM

        def reproduces(subset: list[str]) -> bool:
            run = runner.run([*subset, victim])
            return run.failed(victim) if want_failure else run.passed(victim)

        single = bisect_single(checked.prefix, reproduces)
        if single is not None:
            result.causes, result.method = [single], "bisection"
        else:
            result.causes, result.method = ddmin(checked.prefix, reproduces), "ddmin"

        confirmation = Tally()
        for _ in range(reruns):
            confirmation.add(runner.run([*result.causes, victim], fresh=True).outcome(victim))
        result.confirmation = confirmation
        result.repro_command = runner.repro_command([*result.causes, victim])

        if want_failure and max_cleaners != 0:
            excluded = {*result.causes, victim}
            for candidate in order:
                if candidate in excluded:
                    continue
                result.cleaner_candidates_checked += 1
                if runner.run([*result.causes, candidate, victim]).passed(victim):
                    result.cleaners.append(candidate)
                    if 0 < max_cleaners <= len(result.cleaners):
                        break
            if result.cleaners:
                result.cleaner_command = runner.repro_command(
                    [*result.causes, result.cleaners[0], victim]
                )

    result.runs = runner.stats.runs - runs0
    result.cache_hits = runner.stats.cache_hits - hits0
    result.tests_executed = runner.stats.tests_executed - tests0
    result.seconds = time.perf_counter() - start
    return result

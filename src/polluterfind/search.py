"""Localise the cause of an order-dependent test.

For a victim, the search looks for a 1-minimal set of polluters among the tests that ran before
it: their presence (in suite order) makes the victim fail. For a brittle test it looks for a
1-minimal set of state-setters: their presence makes it pass. With the default method the
single-polluter bisection runs first; when its confirmation fails, ddmin takes over. For a victim,
it then looks for cleaners: tests that, run between the polluters and the victim, make the
victim pass again.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from .ddmin import bisect_single, ddmin, linear_single
from .runner import BaseRunner
from .verify import BRITTLE, VICTIM, Tally, Verification, verify

METHODS = ("auto", "ddmin", "bisection", "linear")


@dataclass
class FindResult:
    verification: Verification
    causes: list[str] = field(default_factory=list)
    method: str = "none"
    search_runs: int = 0
    confirmation: Tally | None = None
    cleaners: list[str] = field(default_factory=list)
    cleaner_candidates_checked: int = 0
    runs: int = 0
    cache_hits: int = 0
    tests_executed: int = 0
    seconds: float = 0.0
    repro_command: str = ""
    cleaner_command: str = ""
    reordered_runs: int = 0
    reordered_example: tuple[tuple[str, ...], tuple[str, ...]] | None = None

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


def localise(
    runner: BaseRunner,
    prefix: Sequence[str],
    victim: str,
    *,
    want_failure: bool,
    method: str = "auto",
) -> tuple[list[str], str]:
    """Search ``prefix`` for a minimal cause; returns the causes and the method that found them.

    ``auto`` tries the bisection and falls back to ddmin; ``bisection`` and ``linear`` stop with
    an empty result when no single test reproduces on its own.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")

    def reproduces(subset: list[str]) -> bool:
        run = runner.run([*subset, victim])
        return run.failed(victim) if want_failure else run.passed(victim)

    def batch(subsets: list[list[str]]) -> list[bool]:
        runs = runner.run_many([[*subset, victim] for subset in subsets])
        return [r.failed(victim) if want_failure else r.passed(victim) for r in runs]

    width = runner.jobs
    prefix = list(prefix)
    if method == "linear":
        single = linear_single(prefix, reproduces, batch, width)
        return ([single], "linear") if single is not None else ([], "linear")
    if method in ("auto", "bisection"):
        single = bisect_single(prefix, reproduces)
        if single is not None:
            return [single], "bisection"
        if method == "bisection":
            return [], "bisection"
    return ddmin(prefix, reproduces, batch=batch, width=width), "ddmin"


def find_cleaners(
    runner: BaseRunner,
    order: Sequence[str],
    causes: Sequence[str],
    victim: str,
    max_cleaners: int = 1,
) -> tuple[list[str], int]:
    """Try each other test between the causes and the victim; returns cleaners and the count
    of candidates checked. ``max_cleaners`` below zero checks every candidate."""
    excluded = {*causes, victim}
    candidates = [c for c in order if c not in excluded]
    cleaners: list[str] = []
    checked = 0
    width = runner.jobs
    for begin in range(0, len(candidates), width):
        group = candidates[begin : begin + width]
        runs = runner.run_many([[*causes, c, victim] for c in group])
        for candidate, run in zip(group, runs, strict=True):
            checked += 1
            if run.passed(victim):
                cleaners.append(candidate)
                if 0 < max_cleaners <= len(cleaners):
                    return cleaners, checked
    return cleaners, checked


def find(
    runner: BaseRunner,
    order: Sequence[str],
    victim: str,
    *,
    reruns: int = 3,
    max_cleaners: int = 1,
    method: str = "auto",
    verification: Verification | None = None,
) -> FindResult:
    """Verify ``victim`` against ``order``, then search for its polluters or state-setters."""
    start = time.perf_counter()
    stats = runner.stats
    runs0, hits0, tests0 = stats.runs, stats.cache_hits, stats.tests_executed
    reordered0 = stats.reordered_runs
    checked = verification or verify(runner, order, victim, reruns)
    result = FindResult(checked)

    if checked.kind in (VICTIM, BRITTLE):
        want_failure = checked.kind == VICTIM
        before = stats.runs
        result.causes, result.method = localise(
            runner, checked.prefix, victim, want_failure=want_failure, method=method
        )
        result.search_runs = stats.runs - before

        if result.causes:
            confirmation = Tally()
            for run in runner.run_many([[*result.causes, victim]] * reruns, fresh=True):
                confirmation.add(run.outcome(victim))
            result.confirmation = confirmation
            result.repro_command = runner.repro_command([*result.causes, victim])

        if want_failure and result.causes and max_cleaners != 0:
            result.cleaners, result.cleaner_candidates_checked = find_cleaners(
                runner, order, result.causes, victim, max_cleaners
            )
            if result.cleaners:
                result.cleaner_command = runner.repro_command(
                    [*result.causes, result.cleaners[0], victim]
                )

    result.runs = stats.runs - runs0
    result.cache_hits = stats.cache_hits - hits0
    result.tests_executed = stats.tests_executed - tests0
    result.reordered_runs = stats.reordered_runs - reordered0
    if result.reordered_runs:
        result.reordered_example = stats.first_reordered
    result.seconds = time.perf_counter() - start
    return result

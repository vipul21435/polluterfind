from __future__ import annotations

import itertools
import random

import pytest

from polluterfind.ddmin import bisect_single, ddmin, is_one_minimal, split


class CountingOracle:
    """Victim model: each test sets or clears shared flags; the victim fails when every flag of
    any one required group is set at the moment it runs."""

    def __init__(self, effects: dict[str, list[tuple[str, str]]], groups: list[set[str]]):
        self.effects = effects
        self.groups = groups
        self.calls = 0

    def __call__(self, order: list[str]) -> bool:
        self.calls += 1
        state: set[str] = set()
        for test in order:
            for op, flag in self.effects.get(test, []):
                if op == "set":
                    state.add(flag)
                else:
                    state.discard(flag)
        return any(group <= state for group in self.groups)


def names(n: int) -> list[str]:
    return [f"t{i:03d}" for i in range(n)]


def test_split_keeps_order_and_sizes():
    assert split(list(range(7)), 3) == [[0, 1, 2], [3, 4], [5, 6]]
    assert split(list(range(3)), 5) == [[0], [1], [2]]
    assert split([], 2) == [[]]
    with pytest.raises(ValueError):
        split([1], 0)


@pytest.mark.parametrize("position", [0, 1, 6, 12, 19])
def test_single_polluter_found_by_both(position):
    tests = names(20)
    polluter = tests[position]
    oracle = CountingOracle({polluter: [("set", "x")]}, [{"x"}])
    assert ddmin(tests, oracle) == [polluter]
    assert bisect_single(tests, oracle) == polluter


def test_bisection_cost_is_logarithmic():
    tests = names(1024)
    oracle = CountingOracle({tests[700]: [("set", "x")]}, [{"x"}])
    assert bisect_single(tests, oracle) == tests[700]
    assert oracle.calls <= 11  # log2(1024) levels plus one confirmation


def test_paired_polluters_need_ddmin():
    tests = names(16)
    oracle = CountingOracle({tests[3]: [("set", "a")], tests[11]: [("set", "b")]}, [{"a", "b"}])
    assert bisect_single(tests, oracle) is None
    assert ddmin(tests, oracle) == [tests[3], tests[11]]


def test_cleaner_inside_prefix_is_respected():
    # t1 pollutes, t2 cleans, t4 pollutes again; only t4 alone reproduces.
    tests = names(6)
    effects = {
        tests[1]: [("set", "x")],
        tests[2]: [("clear", "x")],
        tests[4]: [("set", "x")],
    }
    oracle = CountingOracle(effects, [{"x"}])
    assert oracle(tests)
    result = ddmin(tests, oracle)
    assert len(result) == 1 and oracle(result)


def test_empty_and_single_input():
    oracle = CountingOracle({"a": [("set", "x")]}, [{"x"}])
    assert ddmin([], oracle) == []
    assert ddmin(["a"], oracle) == ["a"]
    assert bisect_single([], oracle) is None


def brute_force_one_minimal(tests: list[str], oracle) -> list[list[str]]:
    found = []
    for r in range(len(tests) + 1):
        for combo in itertools.combinations(tests, r):
            subset = list(combo)
            if oracle(subset) and all(
                not oracle(subset[:i] + subset[i + 1 :]) for i in range(len(subset))
            ):
                found.append(subset)
    return found


def random_model(rng: random.Random) -> tuple[list[str], CountingOracle]:
    """Draw suites until the full order reproduces (the empty order never does)."""
    flags = ["a", "b", "c"]
    while True:
        tests = names(rng.randint(2, 9))
        effects = {}
        for test in tests:
            if rng.random() < 0.6:
                effects[test] = [(rng.choice(["set", "set", "clear"]), rng.choice(flags))]
        groups = [set(rng.sample(flags, rng.randint(1, 2))) for _ in range(rng.randint(1, 2))]
        oracle = CountingOracle(effects, groups)
        if oracle(tests) and not oracle([]):
            return tests, oracle


@pytest.mark.parametrize("seed", range(60))
def test_ddmin_against_brute_force(seed):
    tests, oracle = random_model(random.Random(seed))
    result = ddmin(tests, oracle)
    assert result in brute_force_one_minimal(tests, oracle)
    assert is_one_minimal(result, oracle)
    # Order is preserved: the result is a subsequence of the input.
    positions = [tests.index(t) for t in result]
    assert positions == sorted(positions)


def test_is_one_minimal_rejects_non_minimal():
    oracle = CountingOracle({"a": [("set", "x")]}, [{"x"}])
    assert is_one_minimal(["a"], oracle)
    assert not is_one_minimal(["a", "b"], oracle)
    assert not is_one_minimal(["b"], oracle)

from __future__ import annotations

import math

import pytest

from polluterfind.junit import FAILED, PASSED, SKIPPED
from polluterfind.verify import (
    BRITTLE,
    FLAKY,
    NOT_ORDER_DEPENDENT,
    UNRESOLVED,
    VICTIM,
    Tally,
    classify,
    prefix_of,
    wilson_interval,
)

Z95 = 1.959963984540054


def tally(*outcomes: str) -> Tally:
    t = Tally()
    for outcome in outcomes:
        t.add(outcome)
    return t


def test_wilson_closed_forms():
    # With no successes the interval is [0, z^2 / (n + z^2)]; with all successes, the mirror.
    for n in (1, 3, 10, 50):
        low, high = wilson_interval(0, n)
        assert low == 0.0
        assert math.isclose(high, Z95**2 / (n + Z95**2), rel_tol=1e-12)
        low, high = wilson_interval(n, n)
        assert math.isclose(low, n / (n + Z95**2), rel_tol=1e-12) and high == 1.0
    # Symmetric around one half for k = n / 2.
    low, high = wilson_interval(5, 10)
    assert math.isclose(low + high, 1.0, rel_tol=1e-12)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(4, 3)


def test_wilson_hand_worked_value():
    # n = 20, k = 15, z = 1.96: centre (0.75 + 0.09604) / 1.19208 = 0.70972,
    # half-width 1.96 * sqrt(0.009375 + 0.002401) / 1.19208 = 0.17842.
    low, high = wilson_interval(15, 20)
    assert math.isclose(low, 0.5313, abs_tol=5e-4)
    assert math.isclose(high, 0.8881, abs_tol=5e-4)


def test_classify():
    assert classify(tally(PASSED, PASSED), tally(FAILED, FAILED)) == VICTIM
    assert classify(tally(FAILED, FAILED), tally(PASSED, PASSED)) == BRITTLE
    assert classify(tally(PASSED), tally(PASSED)) == NOT_ORDER_DEPENDENT
    assert classify(tally(FAILED), tally(FAILED)) == NOT_ORDER_DEPENDENT
    assert classify(tally(PASSED, FAILED), tally(FAILED, FAILED)) == FLAKY
    assert classify(tally(PASSED, PASSED), tally(FAILED, PASSED)) == FLAKY
    assert classify(tally(SKIPPED), tally(FAILED)) == UNRESOLVED
    # Unresolved reruns are counted apart and do not change a clear verdict.
    assert classify(tally(PASSED, SKIPPED), tally(FAILED)) == VICTIM


def test_prefix_of():
    assert prefix_of(["a", "b", "c"], "c") == ["a", "b"]
    assert prefix_of(["a", "b", "c"], "a") == []
    with pytest.raises(ValueError, match="not in the test order"):
        prefix_of(["a"], "z")

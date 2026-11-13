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


def test_period_two_flakiness_aliases_with_the_schedule():
    """Documented limitation: an outcome that flips on every run lines up with the
    alternating alone, prefix, alone, ... schedule and looks order-dependent."""
    from polluterfind.runner import SimulatedRunner
    from polluterfind.verify import verify

    calls = {"n": 0}

    def outcomes(order):
        calls["n"] += 1
        return {t: FAILED if calls["n"] % 2 == 0 and t == "t::x" else PASSED for t in order}

    result = verify(SimulatedRunner(outcomes), ["t::a", "t::x"], "t::x", reruns=3)
    assert result.kind == VICTIM  # wrong in truth: the test is flaky


def test_unresolved_detail_names_the_cause():
    from polluterfind.junit import MISSING
    from polluterfind.runner import RunResult
    from polluterfind.verify import unresolved_detail

    def run(outcome, returncode=0, timed_out=False, executed=("t::v",)):
        return RunResult(
            ("t::v",), {"t::v": outcome}, list(executed), returncode, 7.0, timed_out, "a\nb\n"
        )

    assert unresolved_detail(run(SKIPPED), "t::v", "alone")["reason"] == "the victim was skipped"
    timed = unresolved_detail(run(MISSING, None, True, ()), "t::v", "alone")
    assert timed["reason"] == "timed out after 7 s" and timed["outcome"] == "timeout"
    usage = unresolved_detail(run(MISSING, 4, executed=()), "t::v", "after prefix")
    assert usage["reason"].startswith("exit code 4 (pytest usage error")
    assert usage["order"] == "after prefix" and usage["output_tail"] == "a\nb"
    crashed = unresolved_detail(run(MISSING, 1, executed=()), "t::v", "alone")
    assert crashed["reason"] == "exit code 1, but no requested test is in the JUnit report"
    other = RunResult(("t::a", "t::v"), {"t::v": MISSING}, ["t::a"], 0, 1.0)
    assert unresolved_detail(other, "t::v", "alone")["reason"] == (
        "exit code 0, but the victim is not in the JUnit report"
    )


def test_unresolved_runs_are_explained_in_the_report(make_project, tmp_path):
    from polluterfind.report import verification_dict, verify_markdown
    from polluterfind.runner import CommandRunner
    from polluterfind.verify import verify

    project = make_project(
        {
            "test_ok.py": "def test_v():\n    pass\n",
            "test_broken.py": "def test_x(:\n    pass\n",
        }
    )
    runner = CommandRunner(project, timeout=120)
    # A stale id before the victim: pytest refuses the whole run (exit 4).
    stale = verify(runner, ["test_ok.py::test_gone", "test_ok.py::test_v"], "test_ok.py::test_v", 1)
    assert stale.kind == UNRESOLVED and stale.unresolved_run["order"] == "after prefix"
    assert stale.unresolved_run["returncode"] == 4
    markdown = verify_markdown(stale)
    assert "first unresolved run (after prefix): exit code 4" in markdown
    assert "not found" in markdown  # pytest's own message
    # A module with a syntax error named by node id: pytest refuses it (exit 4 with pytest 9).
    broken = verify(
        runner, ["test_broken.py::test_x", "test_ok.py::test_v"], "test_ok.py::test_v", 1
    )
    assert broken.unresolved_run["returncode"] in (2, 4)
    assert "SyntaxError" in broken.unresolved_run["output_tail"]
    # An interpreter without pytest: exit 1, no report, the error text is kept.
    fake = tmp_path / "python-without-pytest"
    fake.write_text("#!/bin/sh\necho 'No module named pytest' >&2\nexit 1\n")
    fake.chmod(0o755)
    missing = verify(
        CommandRunner(project, python=str(fake)), ["test_ok.py::test_v"], "test_ok.py::test_v", 1
    )
    detail = verification_dict(missing)["unresolved_run"]
    assert detail["returncode"] == 1 and "No module named pytest" in detail["output_tail"]


def test_wilson_bounds_are_exact_at_zero_and_n():
    for n in range(1, 201):
        for confidence in (0.5, 0.8, 0.9, 0.95, 0.99, 0.999):
            assert wilson_interval(0, n, confidence)[0] == 0.0
            assert wilson_interval(n, n, confidence)[1] == 1.0

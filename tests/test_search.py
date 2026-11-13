from __future__ import annotations

import pytest

from polluterfind import verify as v
from polluterfind.generate import plant
from polluterfind.junit import FAILED, PASSED
from polluterfind.report import find_dict, find_markdown
from polluterfind.runner import SimulatedRunner
from polluterfind.search import find, localise


@pytest.mark.parametrize("seed", range(8))
def test_single_polluter_and_cleaner(seed):
    plan = plant(40, causes=1, seed=seed)
    runner = SimulatedRunner(plan.outcomes)
    result = find(runner, plan.ids, plan.target_id, reruns=2)
    assert result.kind == v.VICTIM
    assert result.causes == plan.planted("set") and result.method == "bisection"
    assert result.confirmed and result.role == "polluter"
    assert result.cleaners == plan.planted("clear")
    assert result.repro_command.endswith(f"{result.causes[0]} {plan.target_id}")
    assert result.runs == runner.stats.runs and result.reordered_runs == 0


@pytest.mark.parametrize("seed", range(8))
def test_paired_polluters_fall_back_to_ddmin(seed):
    plan = plant(40, causes=2, seed=seed)
    runner = SimulatedRunner(plan.outcomes)
    result = find(runner, plan.ids, plan.target_id, reruns=1)
    assert result.kind == v.VICTIM
    assert result.causes == plan.planted("set") and result.method == "ddmin"
    assert result.confirmed and result.cleaners == plan.planted("clear")


@pytest.mark.parametrize("causes", [1, 2])
def test_brittle_test_and_state_setters(causes):
    plan = plant(30, kind="brittle", causes=causes, seed=3)
    runner = SimulatedRunner(plan.outcomes)
    result = find(runner, plan.ids, plan.target_id, reruns=2)
    assert result.kind == v.BRITTLE and result.role == "state-setter"
    assert result.causes == plan.planted("set") and result.confirmed
    assert result.cleaners == []
    assert find_dict(result)["state_setters"] == plan.planted("set")
    markdown = find_markdown(result)
    assert f"state-setters ({causes}, by " in markdown
    assert "victim passed in 2 of 2 reruns" in markdown and "cleaners" not in markdown


def test_methods_on_single_and_paired_causes():
    single = plant(64, causes=1, cleaner=False, seed=1)
    paired = plant(64, causes=2, cleaner=False, seed=1)
    for method in ("auto", "ddmin", "bisection", "linear"):
        runner = SimulatedRunner(single.outcomes)
        causes, _ = localise(
            runner, single.ids[:-1], single.target_id, want_failure=True, method=method
        )
        assert causes == single.planted("set"), method
    for method, expected in (("auto", 2), ("ddmin", 2), ("bisection", 0), ("linear", 0)):
        runner = SimulatedRunner(paired.outcomes)
        causes, _ = localise(
            runner, paired.ids[:-1], paired.target_id, want_failure=True, method=method
        )
        assert len(causes) == expected, method
    with pytest.raises(ValueError, match="method"):
        localise(SimulatedRunner(single.outcomes), [], "x", want_failure=True, method="nope")


def test_linear_scan_cost_equals_position():
    plan = plant(50, causes=1, cleaner=False, seed=7)
    position = plan.ids.index(plan.planted("set")[0])
    runner = SimulatedRunner(plan.outcomes)
    localise(runner, plan.ids[:-1], plan.target_id, want_failure=True, method="linear")
    assert runner.stats.runs == position + 1


def test_bisection_without_a_single_cause_reports_none_found():
    plan = plant(30, causes=2, seed=4)
    result = find(SimulatedRunner(plan.outcomes), plan.ids, plan.target_id, method="bisection")
    assert result.kind == v.VICTIM and result.causes == [] and not result.confirmed
    assert result.confirmation is None and result.cleaners == []
    assert "polluters (0, by bisection" in find_markdown(result)
    assert "none found" in find_markdown(result)


@pytest.mark.parametrize("jobs", [2, 3, 4])
def test_jobs_give_the_same_answer(jobs):
    plan = plant(60, causes=2, seed=11)
    sequential = find(SimulatedRunner(plan.outcomes), plan.ids, plan.target_id, reruns=2)
    runner = SimulatedRunner(plan.outcomes, jobs=jobs)
    parallel = find(runner, plan.ids, plan.target_id, reruns=2)
    assert parallel.causes == sequential.causes
    assert parallel.cleaners == sequential.cleaners
    assert parallel.runs >= sequential.runs


def test_not_order_dependent_runs_no_search():
    plan = plant(10, causes=1, cleaner=False, seed=0)
    # Put the victim first: alone and after the (empty) prefix it passes.
    order = [plan.target_id, *plan.ids[:-1]]
    runner = SimulatedRunner(plan.outcomes)
    result = find(runner, order, plan.target_id, reruns=2)
    assert result.kind == v.NOT_ORDER_DEPENDENT
    assert result.causes == [] and not result.confirmed and result.method == "none"
    assert result.runs == 4  # the verification reruns only


def test_flaky_regardless_of_order():
    calls = {"n": 0}

    def outcomes(order):
        calls["n"] += 1
        fails = calls["n"] % 3 == 0
        return {t: FAILED if t == "t.py::flaky" and fails else PASSED for t in order}

    runner = SimulatedRunner(outcomes)
    order = ["t.py::a", "t.py::b", "t.py::flaky"]
    verification = v.verify(runner, order, "t.py::flaky", reruns=3)
    assert verification.kind == v.FLAKY and verification.after_prefix.mixed
    result = find(runner, order, "t.py::flaky", verification=verification)
    assert result.causes == [] and result.method == "none"


def test_reordered_runs_are_reported():
    plan = plant(12, causes=1, seed=2)
    runner = SimulatedRunner(plan.outcomes, executed=lambda order: sorted(order, reverse=True))
    result = find(runner, plan.ids, plan.target_id, reruns=1, max_cleaners=0)
    assert result.reordered_runs > 0 and result.reordered_example is not None
    requested, executed = result.reordered_example
    assert list(executed) == sorted(requested, reverse=True)
    assert "WARNING" in find_markdown(result)
    report = find_dict(result)
    assert report["reordered_runs"] == result.reordered_runs
    assert report["reordered_example"]["executed"] == list(executed)


def test_search_never_repeats_a_cached_order():
    plan = plant(200, causes=2, seed=5)
    seen = []

    def outcomes(order):
        seen.append(order)
        return plan.outcomes(order)

    runner = SimulatedRunner(outcomes)
    result = find(runner, plan.ids, plan.target_id, reruns=1, max_cleaners=-1)
    assert len(seen) == runner.stats.runs
    # Only the fresh verification and confirmation reruns may repeat an order.
    assert len(set(seen)) >= runner.stats.runs - 3
    assert result.cache_hits > 0
    assert result.cleaner_candidates_checked == plan.n - 3

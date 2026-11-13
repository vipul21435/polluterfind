from __future__ import annotations

from polluterfind.discover import discover, suite_orders
from polluterfind.generate import Plan, plant
from polluterfind.junit import FAILED, PASSED
from polluterfind.report import discover_dict, discover_markdown
from polluterfind.runner import SimulatedRunner
from polluterfind.verify import BRITTLE, FLAKY, VICTIM


def test_suite_orders_are_seeded():
    order = [f"t{i}" for i in range(10)]
    named = suite_orders(order, 2, seed=5)
    assert [name for name, _ in named] == ["given", "reversed", "random seed 5", "random seed 6"]
    assert named[1][1] == order[::-1]
    assert suite_orders(order, 2, seed=5) == named
    assert all(sorted(o) == sorted(order) for _, o in named)


def combined(*plans: Plan):
    """Outcomes of several plans over one suite: each plan owns its target."""

    def outcomes(order):
        result = {t: PASSED for t in order}
        for plan in plans:
            own = plan.outcomes(tuple(t for t in order if t in plan.ids))
            result[plan.target_id] = own.get(plan.target_id, PASSED)
        return result

    return outcomes


def test_victim_and_brittle_found_in_one_suite():
    victim = plant(30, causes=1, seed=1)
    brittle = plant(30, kind="brittle", causes=1, seed=2, module="b")
    order = victim.ids + brittle.ids
    runner = SimulatedRunner(combined(victim, brittle))
    result = discover(runner, order, orders=4, seed=0, reruns=2)
    by_test = {c.test: c for c in result.candidates}
    assert set(by_test) == {victim.target_id, brittle.target_id}
    v = by_test[victim.target_id].result
    assert v.kind == VICTIM and v.causes == victim.planted("set")
    b = by_test[brittle.target_id].result
    assert b.kind == BRITTLE and b.causes == brittle.planted("set")
    assert len(by_test[brittle.target_id].attempts) == 2  # failing order first, then passing
    markdown = discover_markdown(result)
    assert "| reversed |" in markdown and victim.target_id in markdown
    report = discover_dict(result)
    assert len(report["order_dependent_candidates"]) == 2 and report["test_runs"] == result.runs


def test_flaky_candidate_is_reported_not_localised():
    calls = {"n": 0}

    def outcomes(order):
        calls["n"] += 1
        # Period 3: a period-2 flip would line up with verify's alternating schedule
        # (alone, prefix, alone, ...) and read as brittle; see the README limitations.
        return {t: FAILED if t == "t::flaky" and calls["n"] % 3 == 0 else PASSED for t in order}

    runner = SimulatedRunner(outcomes)
    result = discover(runner, ["t::a", "t::flaky", "t::b"], orders=2, reruns=3)
    assert [c.test for c in result.candidates] == ["t::flaky"]
    attempt = result.candidates[0].result
    assert attempt.kind == FLAKY and attempt.causes == []


def test_nothing_order_dependent():
    plan = plant(10, causes=1, cleaner=False)
    order = [plan.target_id, *plan.ids[:-1]]
    runner = SimulatedRunner(lambda o: {t: PASSED for t in o})
    result = discover(runner, order, orders=1)
    assert result.candidates == [] and result.runs == 3
    assert "No test changed outcome" in discover_markdown(result)


def test_no_search_lists_candidates_only():
    plan = plant(20, causes=1, seed=0)
    runner = SimulatedRunner(plan.outcomes)
    result = discover(runner, plan.ids, orders=1, search=False)
    assert [c.test for c in result.candidates] == [plan.target_id]
    assert result.candidates[0].result is None
    assert "not searched" in discover_markdown(result)

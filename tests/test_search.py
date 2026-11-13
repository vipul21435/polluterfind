from __future__ import annotations

from suites import (
    BRITTLE,
    CLEAN,
    PAIRED_VICTIM,
    POLLUTE,
    POLLUTE_A,
    POLLUTE_B,
    SET_READY,
    VICTIM,
    generated_suite,
)

from polluterfind import verify as v
from polluterfind.report import find_dict, find_markdown
from polluterfind.runner import CommandRunner
from polluterfind.search import find


def test_single_polluter_and_cleaner(make_project):
    files, ids = generated_suite(12, {2: CLEAN, 6: POLLUTE, 11: VICTIM})
    runner = CommandRunner(make_project(files))
    result = find(runner, ids, ids[11], reruns=2)
    assert result.kind == v.VICTIM
    assert result.causes == [ids[6]] and result.method == "bisection"
    assert result.confirmed and result.role == "polluter"
    assert result.cleaners == [ids[2]]
    assert result.repro_command.endswith(f"{ids[6]} {ids[11]}")
    assert result.runs == runner.stats.runs and result.cache_hits >= 0


def test_paired_polluters_fall_back_to_ddmin(make_project):
    files, ids = generated_suite(10, {1: POLLUTE_A, 7: POLLUTE_B, 9: PAIRED_VICTIM})
    runner = CommandRunner(make_project(files))
    result = find(runner, ids, ids[9], reruns=1, max_cleaners=0)
    assert result.kind == v.VICTIM
    assert result.causes == [ids[1], ids[7]] and result.method == "ddmin"
    assert result.confirmed and result.cleaners == []


def test_brittle_test_and_state_setter(make_project):
    files, ids = generated_suite(8, {3: SET_READY, 7: BRITTLE})
    runner = CommandRunner(make_project(files))
    result = find(runner, ids, ids[7], reruns=2)
    assert result.kind == v.BRITTLE and result.role == "state-setter"
    assert result.causes == [ids[3]] and result.confirmed
    assert result.cleaners == []
    assert find_dict(result)["state_setters"] == [ids[3]]
    markdown = find_markdown(result)
    assert "state-setters (1, by bisection)" in markdown
    assert "victim passed in 2 of 2 reruns" in markdown and "cleaners" not in markdown


def test_not_order_dependent_runs_no_search(make_project):
    files, ids = generated_suite(5, {4: VICTIM})
    runner = CommandRunner(make_project(files))
    result = find(runner, ids, ids[4], reruns=2)
    assert result.kind == v.NOT_ORDER_DEPENDENT
    assert result.causes == [] and not result.confirmed
    assert result.runs == 4  # only the verification reruns


def test_flaky_regardless_of_order(make_project, tmp_path):
    counter = tmp_path / "counter"
    flaky_body = "\n".join(
        [
            "import os",
            'path = os.environ["PF_COUNTER"]',
            "n = int(open(path).read()) if os.path.exists(path) else 0",
            'open(path, "w").write(str(n + 1))',
            "assert n % 3 != 2",
        ]
    )
    files, ids = generated_suite(4, {3: flaky_body})
    runner = CommandRunner(make_project(files), env={"PF_COUNTER": str(counter)})
    verification = v.verify(runner, ids, ids[3], reruns=3)
    assert verification.kind == v.FLAKY
    assert verification.alone.mixed
    result = find(runner, ids, ids[3], verification=verification)
    assert result.causes == [] and result.method == "none"

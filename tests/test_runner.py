from __future__ import annotations

import pytest

from polluterfind.junit import FAILED, MISSING, PASSED
from polluterfind.runner import TIMEOUT, CommandRunner, collect_pytest

SUITE = {
    "shared_state.py": "STATE = {}\n",
    "test_a.py": """
        import shared_state

        def test_pollute():
            shared_state.STATE["x"] = 1

        def test_clean():
            shared_state.STATE.pop("x", None)
    """,
    "test_b.py": """
        import shared_state

        def test_victim():
            assert "x" not in shared_state.STATE
    """,
}


def test_outcomes_follow_the_requested_order(make_project):
    runner = CommandRunner(make_project(SUITE))
    alone = runner.run(["test_b.py::test_victim"])
    assert alone.passed("test_b.py::test_victim")
    polluted = runner.run(["test_a.py::test_pollute", "test_b.py::test_victim"])
    assert polluted.failed("test_b.py::test_victim")
    assert polluted.outcome("test_a.py::test_pollute") == PASSED
    cleaned = runner.run(
        ["test_a.py::test_pollute", "test_a.py::test_clean", "test_b.py::test_victim"]
    )
    assert cleaned.passed("test_b.py::test_victim")
    reverse = runner.run(["test_b.py::test_victim", "test_a.py::test_pollute"])
    assert reverse.executed == ["test_b.py::test_victim", "test_a.py::test_pollute"]
    assert reverse.order_respected and reverse.passed("test_b.py::test_victim")


def test_cache_is_keyed_by_ordered_ids(make_project):
    runner = CommandRunner(make_project(SUITE))
    order = ["test_a.py::test_pollute", "test_b.py::test_victim"]
    first = runner.run(order)
    assert runner.run(order) is first
    assert runner.stats.runs == 1 and runner.stats.cache_hits == 1
    # Same ids, other order: a different key, a new run, a different outcome.
    other = runner.run(list(reversed(order)))
    assert runner.stats.runs == 2
    assert other.outcome("test_b.py::test_victim") == PASSED
    assert first.outcome("test_b.py::test_victim") == FAILED
    # A fresh rerun executes again and leaves the first cached result in place.
    runner.run(order, fresh=True)
    assert runner.stats.runs == 3 and runner.cached(order) is first


def test_timeout_kills_the_run(make_project):
    project = make_project(
        {"test_slow.py": "import time\n\ndef test_hang():\n    time.sleep(60)\n"}
    )
    runner = CommandRunner(project, timeout=2)
    result = runner.run(["test_slow.py::test_hang"])
    assert result.timed_out and result.returncode is None
    assert result.outcome("test_slow.py::test_hang") == TIMEOUT
    assert not result.passed("test_slow.py::test_hang")
    assert not result.failed("test_slow.py::test_hang")
    assert result.seconds < 20


def test_unknown_id_reads_as_missing(make_project):
    runner = CommandRunner(make_project(SUITE))
    result = runner.run(["test_b.py::test_nope"])
    assert result.outcome("test_b.py::test_nope") == MISSING


def test_template_validation_and_repro_command(tmp_path):
    with pytest.raises(ValueError, match="tests"):
        CommandRunner(tmp_path, "pytest --junitxml={junit}")
    with pytest.raises(ValueError, match="junit"):
        CommandRunner(tmp_path, "pytest {tests}")
    runner = CommandRunner(tmp_path)
    assert runner.repro_command(["a.py::t", "b.py::v[x y]"]) == (
        "python -m pytest -p no:randomly -p no:cacheprovider -q a.py::t 'b.py::v[x y]'"
    )
    spaced = CommandRunner(tmp_path, "tox -e py -- --junitxml {junit} {tests}")
    assert spaced.repro_command(["a.py::t"]) == "tox -e py -- a.py::t"
    assert spaced.argv(["a.py::t"], "r.xml") == [
        "tox",
        "-e",
        "py",
        "--",
        "--junitxml",
        "r.xml",
        "a.py::t",
    ]


def test_collect_lists_ids_in_default_order(make_project):
    collected = collect_pytest(make_project(SUITE))
    assert collected.ids == [
        "test_a.py::test_pollute",
        "test_a.py::test_clean",
        "test_b.py::test_victim",
    ]


def test_collect_reports_errors(make_project):
    with pytest.raises(RuntimeError, match="collection failed"):
        collect_pytest(make_project({"test_bad.py": "import not_a_module_here\n"}))

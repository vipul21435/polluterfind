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


def test_jobs_run_in_isolated_copies(make_project):
    files = dict(SUITE)
    # The victim also fails if another run left a marker file in the working directory.
    files["test_files.py"] = """
        import os
        import time

        def test_writes_marker():
            open("marker.txt", "w").close()
            time.sleep(0.3)
            os.remove("marker.txt")

        def test_no_marker():
            assert not os.path.exists("marker.txt")
    """
    project = make_project(files)
    orders = [["test_files.py::test_writes_marker"], ["test_files.py::test_no_marker"]] * 2
    with CommandRunner(project, jobs=2, timeout=120) as runner:
        assert len(runner.slots) == 2 and project not in runner.slots
        assert all((slot / "test_a.py").exists() for slot in runner.slots)
        results = runner.run_many(orders, fresh=True)
        assert [r.passed(order[0]) for r, order in zip(results, orders, strict=True)] == [True] * 4
        assert runner.stats.runs == 4
        # Duplicates without fresh run once, cached orders are reused.
        again = runner.run_many([orders[1], orders[1], orders[0]])
        assert runner.stats.runs == 4 and again[0] is again[1]
        workdir = runner.slots[0].parent.parent
    assert not workdir.exists()
    assert not (project / "marker.txt").exists()


def test_reordered_run_is_counted(make_project):
    project = make_project(
        {
            "test_fix.py": """
                import pytest

                @pytest.fixture(scope="module", params=[1, 2])
                def value(request):
                    return request.param

                def test_a(value):
                    pass

                def test_b(value):
                    pass
            """
        }
    )
    runner = CommandRunner(project, timeout=120)
    order = ["test_fix.py::test_a[1]", "test_fix.py::test_a[2]", "test_fix.py::test_b[1]"]
    result = runner.run(order)
    # pytest groups tests by the module-scoped parameter, so test_b[1] runs before test_a[2].
    assert result.executed == [
        "test_fix.py::test_a[1]",
        "test_fix.py::test_b[1]",
        "test_fix.py::test_a[2]",
    ]
    assert not result.order_respected
    assert runner.stats.reordered_runs == 1 and runner.stats.first_reordered is not None


def test_collect_rejects_a_project_below_the_rootdir(make_project):
    root = make_project({"sub/tests/test_x.py": "def test_v():\n    pass\n"})
    with pytest.raises(RuntimeError, match="rootdir"):
        collect_pytest(root / "sub")
    assert collect_pytest(root).ids == ["sub/tests/test_x.py::test_v"]

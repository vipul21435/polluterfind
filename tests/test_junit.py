from __future__ import annotations

import subprocess
import sys

from polluterfind.junit import (
    ERROR,
    FAILED,
    MISSING,
    PASSED,
    SKIPPED,
    executed_order,
    junit_key,
    outcomes_for,
    parse_junit,
)


def test_junit_key_matches_pytest_naming():
    assert junit_key("test_a.py::test_x") == ("test_a", "test_x")
    assert junit_key("pkg/sub/test_a.py::TestK::test_m") == ("pkg.sub.test_a.TestK", "test_m")
    assert junit_key("test_b.py::test_p[a/b::c.py]") == ("test_b", "test_p[a/b::c.py]")
    assert junit_key("test_b.py::TestK::test_p[1-x]") == ("test_b.TestK", "test_p[1-x]")


def test_outcomes_from_a_real_pytest_report(make_project, tmp_path):
    project = make_project(
        {
            "test_mix.py": """
                import pytest

                def test_pass():
                    pass

                def test_fail():
                    assert 1 == 2

                @pytest.fixture
                def broken():
                    raise RuntimeError("setup")

                def test_setup_error(broken):
                    pass

                @pytest.fixture
                def bad_teardown():
                    yield
                    raise RuntimeError("teardown")

                def test_teardown_error(bad_teardown):
                    pass

                @pytest.mark.skip(reason="no")
                def test_skip():
                    pass

                @pytest.mark.xfail
                def test_xfail():
                    assert False

                @pytest.mark.parametrize("v", ["a/b", "c::d"])
                def test_param(v):
                    assert v != "c::d"
            """,
            "sub/test_cls.py": """
                class TestK:
                    def test_m(self):
                        pass
            """,
        }
    )
    ids = [
        "sub/test_cls.py::TestK::test_m",
        "test_mix.py::test_pass",
        "test_mix.py::test_fail",
        "test_mix.py::test_setup_error",
        "test_mix.py::test_teardown_error",
        "test_mix.py::test_skip",
        "test_mix.py::test_xfail",
        "test_mix.py::test_param[a/b]",
        "test_mix.py::test_param[c::d]",
    ]
    report = tmp_path / "out.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", f"--junitxml={report}"]
        + ids,
        cwd=project,
        capture_output=True,
    )
    cases = parse_junit(report)
    outcomes = outcomes_for(ids + ["test_mix.py::test_absent"], cases)
    assert outcomes == {
        "sub/test_cls.py::TestK::test_m": PASSED,
        "test_mix.py::test_pass": PASSED,
        "test_mix.py::test_fail": FAILED,
        "test_mix.py::test_setup_error": ERROR,
        "test_mix.py::test_teardown_error": ERROR,
        "test_mix.py::test_skip": SKIPPED,
        "test_mix.py::test_xfail": SKIPPED,
        "test_mix.py::test_param[a/b]": PASSED,
        "test_mix.py::test_param[c::d]": FAILED,
        "test_mix.py::test_absent": MISSING,
    }
    assert executed_order(ids, cases) == ids


def test_failure_wins_over_teardown_error_and_bare_testsuite_root():
    xml = """<?xml version="1.0"?>
    <testsuite name="pytest" tests="3">
      <testcase classname="t" name="a" time="0.5">
        <failure message="boom"/><error message="td"/>
      </testcase>
      <testcase classname="t" name="b" time="bad"/>
      <testcase classname="t" name="c"><skipped message="why"/></testcase>
    </testsuite>"""
    cases = parse_junit(xml)
    assert [(c.name, c.outcome) for c in cases] == [("a", FAILED), ("b", PASSED), ("c", SKIPPED)]
    assert cases[0].message == "boom" and cases[0].time == 0.5 and cases[1].time == 0.0
    assert executed_order(["t.py::c", "t.py::a"], cases) == ["t.py::a", "t.py::c"]

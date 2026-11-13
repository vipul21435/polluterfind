from __future__ import annotations

import json

from suites import CLEAN, POLLUTE, VICTIM, generated_suite

from polluterfind.cli import main


def test_find_json_report(make_project, tmp_path):
    # The cleaner runs after the victim in suite order, so the suite order still fails.
    files, ids = generated_suite(9, {1: POLLUTE, 7: VICTIM, 8: CLEAN})
    project = make_project(files)
    out = tmp_path / "report.json"
    code = main(
        ["find", ids[7], "--project", str(project), "--reruns", "1", "--format", "json"]
        + ["--out", str(out)]
    )
    assert code == 0
    report = json.loads(out.read_text())
    assert report["kind"] == "victim"
    assert report["polluters"] == [ids[1]]
    assert report["cleaners"] == [ids[8]]
    assert report["confirmed"] is True
    assert report["test_runs"] >= 3
    assert report["repro_command"].endswith(f"{ids[1]} {ids[7]}")


def test_find_markdown_with_order_file(make_project, tmp_path, capsys):
    files, ids = generated_suite(6, {2: POLLUTE, 5: VICTIM})
    project = make_project(files)
    # Move the victim to the front: alone and after an empty prefix it passes.
    order_file = tmp_path / "order.txt"
    order_file.write_text("# custom order\n" + "\n".join([ids[5], *ids[:5]]) + "\n")
    args = ["--project", str(project), "--order-file", str(order_file), "--reruns", "1"]
    assert main(["find", ids[5], *args]) == 1
    output = capsys.readouterr().out
    assert "not order-dependent" in output
    assert main(["verify", ids[5], *args]) == 1


def test_verify_markdown_and_json(make_project, capsys):
    files, ids = generated_suite(6, {2: POLLUTE, 5: VICTIM})
    project = make_project(files)
    assert main(["verify", ids[5], "--project", str(project), "--reruns", "2"]) == 0
    output = capsys.readouterr().out
    assert "passes alone, fails after" in output and "passed 2 of 2" in output
    code = main(["verify", ids[5], "--project", str(project), "--reruns", "1", "--format", "json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "victim" and report["prefix_length"] == 5


def test_usage_errors(make_project, capsys):
    files, ids = generated_suite(3, {})
    project = make_project(files)
    assert main(["find", "test_nope.py::test_x", "--project", str(project)]) == 2
    assert "not in the test order" in capsys.readouterr().err
    assert main(["find", ids[0], "--project", str(project), "--reruns", "0"]) == 2
    assert main(["find", ids[0], "--project", str(project), "--command", "pytest {tests}"]) == 2
    assert "{junit}" in capsys.readouterr().err

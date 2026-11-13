"""CLI tests. These start real pytest processes, so they are few and use small suites."""

from __future__ import annotations

import json

from polluterfind.cli import main
from polluterfind.generate import plant


def test_find_json_report(tmp_path):
    plan = plant(9, causes=1, seed=2, per_file=5)
    project = plan.write(tmp_path / "proj")
    out = tmp_path / "report.json"
    args = ["find", plan.target_id, "--project", str(project), "--reruns", "1"]
    assert main([*args, "--format", "json", "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["kind"] == "victim"
    assert report["polluters"] == plan.planted("set")
    assert report["cleaners"] == plan.planted("clear")
    assert report["confirmed"] is True and report["reordered_runs"] == 0
    assert report["repro_command"].endswith(f"{plan.planted('set')[0]} {plan.target_id}")


def test_verify_and_order_file(tmp_path, capsys):
    plan = plant(6, causes=1, cleaner=False, seed=1, per_file=5)
    project = plan.write(tmp_path / "proj")
    base = ["--project", str(project), "--reruns", "1"]
    assert main(["verify", plan.target_id, *base]) == 0
    assert "passes alone, fails after" in capsys.readouterr().out
    # With the victim moved to the front it is not order-dependent in that order.
    order_file = tmp_path / "order.txt"
    order_file.write_text("# custom order\n" + "\n".join([plan.target_id, *plan.ids[:-1]]))
    code = main(["verify", plan.target_id, *base, "--order-file", str(order_file)])
    assert code == 1
    assert main(["find", plan.target_id, *base, "--order-file", str(order_file)]) == 1
    assert "not order-dependent" in capsys.readouterr().out


def test_discover_markdown_and_json(tmp_path, capsys):
    plan = plant(8, causes=1, seed=3, per_file=4)
    project = plan.write(tmp_path / "proj")
    base = ["discover", "--project", str(project), "--reruns", "1", "--orders", "1"]
    assert main([*base, "--format", "json", "--jobs", "2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [o["name"] for o in report["orders"]] == ["given", "reversed", "random seed 0"]
    targets = [c["test"] for c in report["order_dependent_candidates"]]
    assert targets == [plan.target_id]
    found = report["order_dependent_candidates"][0]["result"]
    assert found["polluters"] == plan.planted("set")
    assert main([*base, "--no-search"]) == 0
    assert "## `" + plan.target_id in capsys.readouterr().out


def test_usage_errors(tmp_path, capsys):
    plan = plant(3, causes=1, cleaner=False)
    project = plan.write(tmp_path / "proj")
    order_file = tmp_path / "order.txt"
    order_file.write_text("\n".join(plan.ids))
    base = ["--project", str(project), "--order-file", str(order_file)]
    assert main(["find", "tests/test_nope.py::test_x", *base]) == 2
    assert "not in the test order" in capsys.readouterr().err
    assert main(["find", plan.target_id, *base, "--reruns", "0"]) == 2
    assert main(["find", plan.target_id, *base, "--jobs", "0"]) == 2
    assert main(["discover", *base, "--orders", "-1"]) == 2
    assert main(["find", plan.target_id, *base, "--command", "pytest {tests}"]) == 2
    assert "{junit}" in capsys.readouterr().err
    assert main(["find", plan.target_id, "--project", str(tmp_path / "missing")]) == 2

from __future__ import annotations

import random

import pytest

from polluterfind.generate import plant
from polluterfind.junit import FAILED, PASSED
from polluterfind.runner import CommandRunner, collect_pytest


def test_plant_layout():
    plan = plant(100, causes=2, seed=4)
    assert plan.target_id == plan.ids[-1] == "tests/test_m001.py::test_0099"
    assert len(plan.planted("set")) == 2 and len(plan.planted("clear")) == 1
    # The cleaner sits before both polluters, so the suite order still fails.
    assert plan.ids.index(plan.planted("clear")[0]) < plan.ids.index(plan.planted("set")[0])
    assert plan.outcomes(tuple(plan.ids))[plan.target_id] == FAILED
    assert plan.outcomes((plan.target_id,))[plan.target_id] == PASSED
    brittle = plant(20, kind="brittle", causes=1, seed=1)
    assert brittle.planted("clear") == []
    assert brittle.outcomes((brittle.target_id,))[brittle.target_id] == FAILED
    with pytest.raises(ValueError):
        plant(2, causes=2)
    with pytest.raises(ValueError):
        plant(10, kind="other")


def test_written_suite_matches_the_model(tmp_path):
    """The real pytest run and the in-process model agree on every outcome."""
    plan = plant(24, causes=2, seed=9, per_file=8)
    project = plan.write(tmp_path / "suite")
    assert collect_pytest(project).ids == plan.ids
    rng = random.Random(0)
    orders = [plan.ids, list(reversed(plan.ids)), rng.sample(plan.ids, len(plan.ids))]
    orders.append([*plan.planted("set"), plan.target_id])
    orders.append([*plan.planted("set"), *plan.planted("clear"), plan.target_id])
    with CommandRunner(project, timeout=120) as runner:
        for order, run in zip(orders, runner.run_many(orders), strict=True):
            assert run.outcomes == plan.outcomes(tuple(order))
    assert orders[0] and run.passed(plan.target_id)

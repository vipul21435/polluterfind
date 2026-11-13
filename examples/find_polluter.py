"""Use polluterfind from Python on the bundled example and on a generated suite.

    python examples/find_polluter.py

The first part runs the real pytest on examples/unit_registry. The second writes a generated
suite of 300 tests with two planted polluters and a cleaner, then runs discover on it with two
workers, each in its own copy of the suite directory.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from polluterfind.discover import discover
from polluterfind.generate import plant
from polluterfind.report import discover_markdown, find_markdown
from polluterfind.runner import CommandRunner, collect_pytest
from polluterfind.search import find

HERE = Path(__file__).parent


def bundled_example() -> None:
    project = HERE / "unit_registry"
    order = collect_pytest(project).ids
    victim = "tests/test_units.py::test_known_units_are_the_defaults"
    with CommandRunner(project, timeout=120) as runner:
        result = find(runner, order, victim, reruns=2)
    print(find_markdown(result))


def generated_suite() -> None:
    plan = plant(300, causes=2, seed=7)
    with tempfile.TemporaryDirectory() as tmp:
        project = plan.write(Path(tmp) / "suite")
        with CommandRunner(project, timeout=300, jobs=2) as runner:
            result = discover(runner, plan.ids, orders=1, reruns=1)
    print(discover_markdown(result))
    found = result.candidates[0].result
    print("planted polluters:", plan.planted("set"))
    print("found polluters:  ", found.causes if found else None)


if __name__ == "__main__":
    bundled_example()
    generated_suite()

"""Read test outcomes from a JUnit XML report.

pytest writes one ``<testcase>`` per test, in execution order, with ``classname`` and ``name``
derived from the node id: the file path loses ``.py`` and turns ``/`` into ``.``, the class (if
any) is appended to it, and ``name`` keeps the function name with its parameter suffix.
``junit_key`` applies that same mapping to a node id, so outcomes can be looked up by the ids we
asked pytest to run instead of by parsing its text output.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

PASSED = "passed"
FAILED = "failed"
ERROR = "error"
SKIPPED = "skipped"
MISSING = "missing"  # asked for, but no testcase in the report (crash, timeout, bad id)

FAILING = frozenset({FAILED, ERROR})


@dataclass(frozen=True)
class Case:
    classname: str
    name: str
    outcome: str
    time: float
    message: str = ""


def junit_key(nodeid: str) -> tuple[str, str]:
    """Map a pytest node id to the ``(classname, name)`` pair pytest writes for it."""
    path, bracket, params = nodeid.partition("[")
    parts = path.split("::")
    parts[0] = re.sub(r"\.py$", "", parts[0].replace("/", "."))
    parts[-1] += bracket + params
    if len(parts) == 1:
        return "", parts[0]
    return ".".join(parts[:-1]), parts[-1]


def _outcome(element: ET.Element) -> tuple[str, str]:
    tags = {child.tag: child for child in element}
    # A test can carry both a failure (call) and an error (teardown); the failure wins.
    for tag, outcome in (("failure", FAILED), ("error", ERROR), ("skipped", SKIPPED)):
        if tag in tags:
            child = tags[tag]
            return outcome, child.get("message", "") or (child.text or "").strip()[:200]
    return PASSED, ""


def parse_junit(source: str | Path) -> list[Case]:
    """Parse a JUnit XML file (or XML text) into cases, in the order they appear."""
    text = Path(source).read_text(encoding="utf-8") if isinstance(source, Path) else source
    root = ET.fromstring(text)
    cases = []
    for element in root.iter("testcase"):
        outcome, message = _outcome(element)
        try:
            time = float(element.get("time", "0") or 0)
        except ValueError:
            time = 0.0
        cases.append(
            Case(element.get("classname", ""), element.get("name", ""), outcome, time, message)
        )
    return cases


def outcomes_for(nodeids: list[str], cases: list[Case]) -> dict[str, str]:
    """Outcome of each requested node id; ``MISSING`` when the report has no matching case."""
    by_key = {(case.classname, case.name): case.outcome for case in cases}
    return {nodeid: by_key.get(junit_key(nodeid), MISSING) for nodeid in nodeids}


def executed_order(nodeids: list[str], cases: list[Case]) -> list[str]:
    """The requested node ids in the order the report says they ran."""
    position = {(case.classname, case.name): i for i, case in enumerate(cases)}
    present = [n for n in nodeids if junit_key(n) in position]
    return sorted(present, key=lambda n: position[junit_key(n)])

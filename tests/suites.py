"""Builders for small generated pytest projects used across the tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

PYTEST_INI = "[pytest]\npythonpath = .\n"


def write_project(root: Path, files: dict[str, str]) -> Path:
    """Write a small pytest project: a pytest.ini plus the given files (dedented)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pytest.ini").write_text(PYTEST_INI)
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip())
    return root


POLLUTE = 'shared_state.STATE["x"] = 1'
VICTIM = 'assert "x" not in shared_state.STATE'
CLEAN = 'shared_state.STATE.pop("x", None)'
SET_READY = 'shared_state.STATE["ready"] = True'
BRITTLE = 'assert shared_state.STATE.get("ready")'
POLLUTE_A = 'shared_state.STATE["a"] = 1'
POLLUTE_B = 'shared_state.STATE["b"] = 1'
PAIRED_VICTIM = 'assert not ("a" in shared_state.STATE and "b" in shared_state.STATE)'


def generated_suite(
    n: int, planted: dict[int, str] | None = None, per_file: int = 5
) -> tuple[dict[str, str], list[str]]:
    """``n`` tests over several files sharing one module-level dict; ``planted[i]`` replaces
    the body of test ``i``. Returns the files and the ids in collection order."""
    planted = planted or {}
    files = {"shared_state.py": "STATE = {}\n"}
    ids = []
    for f in range((n + per_file - 1) // per_file):
        lines = ["import shared_state", ""]
        for i in range(f * per_file, min(n, (f + 1) * per_file)):
            body = planted.get(i, "assert shared_state is not None")
            lines += [f"def test_{i:04d}():"] + ["    " + line for line in body.splitlines()]
            lines.append("")
            ids.append(f"test_m{f:03d}.py::test_{i:04d}")
        files[f"test_m{f:03d}.py"] = "\n".join(lines)
    return files, ids

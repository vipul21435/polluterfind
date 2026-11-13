from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

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


@pytest.fixture
def make_project(tmp_path):
    def make(files: dict[str, str], name: str = "proj") -> Path:
        return write_project(tmp_path / name, files)

    return make

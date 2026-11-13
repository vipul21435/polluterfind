from __future__ import annotations

from pathlib import Path

import pytest
from suites import write_project


@pytest.fixture
def make_project(tmp_path):
    def make(files: dict[str, str], name: str = "proj") -> Path:
        return write_project(tmp_path / name, files)

    return make

"""Generate pytest suites with planted polluters, cleaners and state-setters.

A ``Plan`` describes a suite of ``n`` tests that share one module-level dict. Planted tests set or
clear flags in it; the target test asserts on them. The same plan writes the suite to disk (real
pytest files) and predicts every outcome in process (``Plan.outcomes``), so the in-process runner
and a real pytest run can be checked against each other.

For a victim plan the target fails when every flag of its group is set when it runs; for a
brittle plan it passes only then. Polluters and state-setters set the flags; a cleaner clears
them. Every other test passes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from .junit import FAILED, PASSED

PYTEST_INI = "[pytest]\npythonpath = .\ntestpaths = tests\n"


@dataclass
class Plan:
    n: int
    target: int
    kind: str  # "victim" or "brittle"
    flags: tuple[str, ...]
    effects: dict[int, list[tuple[str, str]]] = field(default_factory=dict)
    per_file: int = 50
    module: str = "m"

    def file_name(self, f: int) -> str:
        return f"test_{self.module}{f:03d}.py"

    def test_id(self, i: int) -> str:
        return f"tests/{self.file_name(i // self.per_file)}::test_{i:04d}"

    @property
    def ids(self) -> list[str]:
        return [self.test_id(i) for i in range(self.n)]

    @property
    def target_id(self) -> str:
        return self.test_id(self.target)

    def planted(self, op: str) -> list[str]:
        """Ids of the tests whose effect is ``op`` ("set" or "clear"), in suite order."""
        return [
            self.test_id(i)
            for i in sorted(self.effects)
            if any(o == op for o, _ in self.effects[i])
        ]

    def _index(self) -> dict[str, int]:
        key = (self.n, self.per_file, self.module)
        cached = self.__dict__.get("_index_cache")
        if cached is None or cached[0] != key:
            cached = (key, {self.test_id(i): i for i in range(self.n)})
            self.__dict__["_index_cache"] = cached
        return cached[1]

    def outcomes(self, order: tuple[str, ...]) -> dict[str, str]:
        """Predicted outcome of every test in ``order``."""
        index = self._index()
        state: set[str] = set()
        result = {}
        for nodeid in order:
            i = index[nodeid]
            if i == self.target:
                triggered = set(self.flags) <= state
                fails = triggered if self.kind == "victim" else not triggered
                result[nodeid] = FAILED if fails else PASSED
            else:
                result[nodeid] = PASSED
            for op, flag in self.effects.get(i, []):
                if op == "set":
                    state.add(flag)
                else:
                    state.discard(flag)
        return result

    def _body(self, i: int) -> list[str]:
        if i == self.target:
            check = " and ".join(f"STATE.get({f!r})" for f in self.flags)
            if self.kind == "victim":
                return [f"assert not ({check})"]
            return [f"assert {check}"]
        lines = []
        for op, flag in self.effects.get(i, []):
            lines.append(f"STATE[{flag!r}] = True" if op == "set" else f"STATE.pop({flag!r}, None)")
        return lines or [f"assert {i} >= 0"]

    def write(self, root: str | Path) -> Path:
        """Write the suite under ``root`` (a pytest.ini, shared_state.py and tests/)."""
        root = Path(root)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        (root / "pytest.ini").write_text(PYTEST_INI)
        (root / "shared_state.py").write_text("STATE = {}\n")
        for f in range((self.n + self.per_file - 1) // self.per_file):
            lines = ["from shared_state import STATE", ""]
            for i in range(f * self.per_file, min(self.n, (f + 1) * self.per_file)):
                lines += ["", f"def test_{i:04d}():"]
                lines += ["    " + line for line in self._body(i)]
            (root / "tests" / self.file_name(f)).write_text("\n".join(lines) + "\n")
        return root


def plant(
    n: int,
    *,
    kind: str = "victim",
    causes: int = 1,
    cleaner: bool = True,
    seed: int = 0,
    per_file: int = 50,
    module: str = "m",
) -> Plan:
    """A suite of ``n`` tests whose last test is the target.

    ``causes`` polluters (victim) or state-setters (brittle) sit at random positions before it.
    With ``cleaner`` (victim plans only), one more test that clears every flag sits before the
    first polluter, so the suite order still fails and the cleaner can be found by the search.
    """
    if kind not in ("victim", "brittle"):
        raise ValueError("kind must be 'victim' or 'brittle'")
    with_cleaner = cleaner and kind == "victim"
    needed = causes + (1 if with_cleaner else 0)
    if causes < 1 or n < needed + 1:
        raise ValueError("suite too small for the planted tests")
    rng = random.Random(seed)
    positions = sorted(rng.sample(range(n - 1), needed))
    flags = tuple(f"flag{k}" for k in range(causes))
    plan = Plan(n=n, target=n - 1, kind=kind, flags=flags, per_file=per_file, module=module)
    if with_cleaner:
        plan.effects[positions[0]] = [("clear", flag) for flag in flags]
        positions = positions[1:]
    for position, flag in zip(positions, flags, strict=True):
        plan.effects[position] = [("set", flag)]
    return plan

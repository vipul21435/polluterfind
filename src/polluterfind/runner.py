"""Run an ordered list of tests and read back their outcomes.

A runner is a command template. ``{tests}`` must be a whole argument and expands to the ordered
test ids, one argument each. ``{junit}`` is replaced by the path of the JUnit XML report the
command must write, and ``{python}`` by the interpreter. The default template is pytest's:

    {python} -m pytest -p no:randomly -p no:cacheprovider -q --junitxml={junit} {tests}

``-p no:randomly`` stops pytest-randomly (if installed) from shuffling the order we ask for, and
``-p no:cacheprovider`` keeps runs from writing ``.pytest_cache`` into the project.

Results are cached by the ordered id tuple, so a search never pays twice for the same order.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .junit import FAILING, MISSING, PASSED, executed_order, outcomes_for, parse_junit

PYTEST_TEMPLATE = (
    "{python} -m pytest -p no:randomly -p no:cacheprovider -q --junitxml={junit} {tests}"
)
TIMEOUT = "timeout"


@dataclass
class RunResult:
    order: tuple[str, ...]
    outcomes: dict[str, str]
    executed: list[str]
    returncode: int | None
    seconds: float
    timed_out: bool = False
    output_tail: str = ""

    def outcome(self, nodeid: str) -> str:
        if self.timed_out and self.outcomes.get(nodeid, MISSING) == MISSING:
            return TIMEOUT
        return self.outcomes.get(nodeid, MISSING)

    def failed(self, nodeid: str) -> bool:
        return self.outcome(nodeid) in FAILING

    def passed(self, nodeid: str) -> bool:
        return self.outcome(nodeid) == PASSED

    @property
    def order_respected(self) -> bool:
        """False when the report shows the tests ran in a different order than requested."""
        ran = set(self.executed)
        return self.executed == [t for t in self.order if t in ran]


@dataclass
class RunStats:
    runs: int = 0
    cache_hits: int = 0
    tests_executed: int = 0
    seconds: float = 0.0


class CommandRunner:
    """Runs a command template in a project directory and caches results by test order."""

    def __init__(
        self,
        project: str | Path,
        template: str | Sequence[str] = PYTEST_TEMPLATE,
        *,
        python: str | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.project = Path(project).resolve()
        self.template = shlex.split(template) if isinstance(template, str) else list(template)
        if "{tests}" not in self.template:
            raise ValueError("the command template needs a {tests} argument")
        if not any("{junit}" in arg for arg in self.template):
            raise ValueError("the command template needs a {junit} placeholder")
        self.python = python or sys.executable
        self.timeout = timeout
        self.env = env
        self.stats = RunStats()
        self._cache: dict[tuple[str, ...], RunResult] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._workdir = Path(tempfile.mkdtemp(prefix="polluterfind-"))

    def argv(self, order: Sequence[str], junit: str) -> list[str]:
        argv: list[str] = []
        for arg in self.template:
            if arg == "{tests}":
                argv.extend(order)
            else:
                argv.append(arg.replace("{junit}", junit).replace("{python}", self.python))
        return argv

    def repro_command(self, order: Sequence[str]) -> str:
        """The shortest command a person can paste: the template without the report option."""
        parts: list[str] = []
        skip_next = False
        for i, arg in enumerate(self.template):
            if skip_next:
                skip_next = False
                continue
            if arg == "{tests}":
                parts.extend(order)
            elif "{junit}" in arg:
                continue
            elif i + 1 < len(self.template) and self.template[i + 1] == "{junit}":
                skip_next = True  # an option whose value is the report path, e.g. "--junitxml"
            else:
                python = "python" if self.python == sys.executable else self.python
                parts.append(arg.replace("{python}", python))
        return shlex.join(parts)

    def cached(self, order: Sequence[str]) -> RunResult | None:
        with self._lock:
            return self._cache.get(tuple(order))

    def run(self, order: Sequence[str], *, fresh: bool = False) -> RunResult:
        """Run ``order``; reuse a cached result unless ``fresh`` is set (for reruns)."""
        key = tuple(order)
        with self._lock:
            if not fresh and key in self._cache:
                self.stats.cache_hits += 1
                return self._cache[key]
            self._counter += 1
            junit = self._workdir / f"run-{self._counter}.junit.xml"
        result = self._execute(key, junit)
        with self._lock:
            self.stats.runs += 1
            self.stats.tests_executed += len(key)
            self.stats.seconds += result.seconds
            self._cache.setdefault(key, result)
        return result

    def _execute(self, order: tuple[str, ...], junit: Path) -> RunResult:
        env = {**os.environ, **(self.env or {})}
        start = time.perf_counter()
        process = subprocess.Popen(
            self.argv(order, str(junit)),
            cwd=self.project,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        timed_out = False
        try:
            output, _ = process.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(process)
            output, _ = process.communicate()
        seconds = time.perf_counter() - start
        ids = list(order)
        cases = []
        if junit.exists():
            try:
                cases = parse_junit(junit)
            except Exception:  # a truncated report after a crash reads as missing outcomes
                cases = []
            junit.unlink()
        return RunResult(
            order=order,
            outcomes=outcomes_for(ids, cases),
            executed=executed_order(ids, cases),
            returncode=None if timed_out else process.returncode,
            seconds=seconds,
            timed_out=timed_out,
            output_tail=output.decode("utf-8", "replace")[-2000:],
        )


def _kill(process: subprocess.Popen) -> None:
    """Kill the command and anything it started (its whole process group on POSIX)."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


@dataclass
class Collected:
    ids: list[str] = field(default_factory=list)
    output: str = ""


def collect_pytest(
    project: str | Path, python: str | None = None, extra_args: Sequence[str] = ()
) -> Collected:
    """List the suite's node ids in pytest's default order (``--collect-only -q``)."""
    argv = [python or sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly"]
    argv += ["-p", "no:cacheprovider", *extra_args]
    proc = subprocess.run(argv, cwd=Path(project), capture_output=True, text=True)
    ids = [
        line.strip()
        for line in proc.stdout.splitlines()
        if "::" in line and not line.startswith((" ", "<", "="))
    ]
    if proc.returncode not in (0, 5) or not ids:
        raise RuntimeError(f"pytest collection failed (exit {proc.returncode}):\n{proc.stdout}")
    return Collected(ids, proc.stdout)

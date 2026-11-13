"""Run an ordered list of tests and read back their outcomes.

A runner is a command template. ``{tests}`` must be a whole argument and expands to the ordered
test ids, one argument each. ``{junit}`` is replaced by the path of the JUnit XML report the
command must write, and ``{python}`` by the interpreter. The default template is pytest's:

    {python} -m pytest -p no:randomly -p no:cacheprovider -q --junitxml={junit} {tests}

``-p no:randomly`` stops pytest-randomly (if installed) from shuffling the order we ask for, and
``-p no:cacheprovider`` keeps runs from writing ``.pytest_cache`` into the project.

Results are cached by the ordered id tuple, so a search never pays twice for the same order.
With ``jobs > 1`` the runner copies the project directory once per worker and runs batches of
orders concurrently, one per copy, so that concurrent runs cannot see each other's files.
"""

from __future__ import annotations

import os
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import weakref
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .junit import FAILING, MISSING, PASSED, executed_order, outcomes_for, parse_junit

PYTEST_TEMPLATE = (
    "{python} -m pytest -p no:randomly -p no:cacheprovider -q --junitxml={junit} {tests}"
)
TIMEOUT = "timeout"

# Not copied into worker directories: version control, virtual environments and caches.
COPY_IGNORE = (
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    ".tox",
    ".nox",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
)


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

    @property
    def problem(self) -> str | None:
        """Why this run says nothing about the tests, or ``None`` when it ran normally.

        A run is broken when it timed out, when the command exited with a code other than 0
        (all passed) or 1 (some failed), or when none of the requested tests is in the report.
        """
        if self.timed_out:
            return f"timed out after {self.seconds:.0f} s"
        if self.returncode not in (0, 1):
            meaning = PYTEST_EXIT_CODES.get(self.returncode, "")
            return f"exit code {self.returncode}" + (f" ({meaning})" if meaning else "")
        if self.order and not self.executed:
            return f"exit code {self.returncode}, but no requested test is in the JUnit report"
        return None

    def tail(self, lines: int = 12) -> str:
        """The last ``lines`` lines of the command's output."""
        return "\n".join(self.output_tail.rstrip().splitlines()[-lines:])


# pytest's exit codes (pytest documentation, "Exit codes"). With pytest 9.2 a test module that
# fails to import gives 2 when it is named by its path and 4 when it is named by a node id.
PYTEST_EXIT_CODES = {
    2: "interrupted or errors during collection",
    3: "pytest internal error",
    4: "pytest usage error, such as a test id that is not found or cannot be collected",
    5: "no tests collected",
}


@dataclass
class RunStats:
    runs: int = 0
    cache_hits: int = 0
    tests_executed: int = 0
    seconds: float = 0.0
    reordered_runs: int = 0
    first_reordered: tuple[tuple[str, ...], tuple[str, ...]] | None = None


class BaseRunner:
    """Caching, statistics and batching shared by every runner; subclasses run one order."""

    def __init__(self, jobs: int = 1) -> None:
        if jobs < 1:
            raise ValueError("jobs must be at least 1")
        self.jobs = jobs
        self.stats = RunStats()
        self._cache: dict[tuple[str, ...], RunResult] = {}
        self._lock = threading.Lock()

    # Subclasses implement this; ``slot`` is the index of the worker running it.
    def _execute(self, order: tuple[str, ...], slot: int) -> RunResult:
        raise NotImplementedError

    def _acquire_slot(self) -> int:
        return 0

    def _release_slot(self, slot: int) -> None:
        pass

    def repro_command(self, order: Sequence[str]) -> str:
        return shlex.join(order)

    def cached(self, order: Sequence[str]) -> RunResult | None:
        with self._lock:
            return self._cache.get(tuple(order))

    def _record(self, key: tuple[str, ...], result: RunResult) -> None:
        with self._lock:
            self.stats.runs += 1
            self.stats.tests_executed += len(key)
            self.stats.seconds += result.seconds
            if not result.order_respected:
                self.stats.reordered_runs += 1
                if self.stats.first_reordered is None:
                    self.stats.first_reordered = (key, tuple(result.executed))
            self._cache.setdefault(key, result)

    def _run_one(self, key: tuple[str, ...]) -> RunResult:
        slot = self._acquire_slot()
        try:
            result = self._execute(key, slot)
        finally:
            self._release_slot(slot)
        self._record(key, result)
        return result

    def run(self, order: Sequence[str], *, fresh: bool = False) -> RunResult:
        """Run ``order``; reuse a cached result unless ``fresh`` is set (for reruns)."""
        key = tuple(order)
        if not fresh:
            with self._lock:
                if key in self._cache:
                    self.stats.cache_hits += 1
                    return self._cache[key]
        return self._run_one(key)

    def run_many(self, orders: Sequence[Sequence[str]], *, fresh: bool = False) -> list[RunResult]:
        """Run several orders, up to ``jobs`` at a time; results come back in input order.

        Without ``fresh``, cached orders are not rerun and duplicates run once. With ``fresh``
        every entry runs, which is how reruns of one order are requested.
        """
        keys = [tuple(order) for order in orders]
        results: dict[int, RunResult] = {}
        pending: dict[tuple[str, ...], list[int]] = {}
        to_run: list[tuple[str, ...]] = []
        for i, key in enumerate(keys):
            if not fresh:
                with self._lock:
                    hit = self._cache.get(key)
                if hit is not None:
                    with self._lock:
                        self.stats.cache_hits += 1
                    results[i] = hit
                    continue
                if key in pending:
                    pending[key].append(i)
                    continue
                pending[key] = [i]
                to_run.append(key)
            else:
                pending.setdefault(key, []).append(i)
                to_run.append(key)
        if self.jobs == 1 or len(to_run) <= 1:
            outputs = [self._run_one(key) for key in to_run]
        else:
            pool = ThreadPoolExecutor(max_workers=self.jobs)
            try:
                outputs = list(pool.map(self._run_one, to_run))
            except BaseException:
                # Ctrl-C reaches only this thread: stop the workers' processes, then wait.
                self.kill_active()
                pool.shutdown(wait=True, cancel_futures=True)
                raise
            pool.shutdown()
        if fresh:
            for i, result in enumerate(outputs):
                results[i] = result
        else:
            for key, result in zip(to_run, outputs, strict=True):
                for i in pending[key]:
                    results[i] = result
        return [results[i] for i in range(len(keys))]

    def kill_active(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class CommandRunner(BaseRunner):
    """Runs a command template in a project directory (or in per-worker copies of it)."""

    def __init__(
        self,
        project: str | Path,
        template: str | Sequence[str] = PYTEST_TEMPLATE,
        *,
        python: str | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        jobs: int = 1,
    ) -> None:
        super().__init__(jobs)
        self.project = Path(project).resolve()
        self.template = shlex.split(template) if isinstance(template, str) else list(template)
        if "{tests}" not in self.template:
            raise ValueError("the command template needs a {tests} argument")
        if not any("{junit}" in arg for arg in self.template):
            raise ValueError("the command template needs a {junit} placeholder")
        if not self.project.is_dir():
            raise ValueError(f"project directory not found: {self.project}")
        self.python = python or sys.executable
        self.timeout = timeout
        self.env = env
        self._counter = 0
        self._active: set[subprocess.Popen] = set()
        self._workdir = Path(tempfile.mkdtemp(prefix="polluterfind-"))
        self._finalizer = weakref.finalize(self, shutil.rmtree, self._workdir, True)
        self.slots: list[Path] = [self.project]
        if jobs > 1:
            self.slots = [self._copy_project(i) for i in range(jobs)]
        self._free: queue.Queue[int] = queue.Queue()
        for i in range(len(self.slots)):
            self._free.put(i)

    def _copy_project(self, index: int) -> Path:
        target = self._workdir / f"worker-{index}" / self.project.name
        shutil.copytree(
            self.project, target, symlinks=True, ignore=shutil.ignore_patterns(*COPY_IGNORE)
        )
        return target

    def _acquire_slot(self) -> int:
        return self._free.get()

    def _release_slot(self, slot: int) -> None:
        self._free.put(slot)

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

    def _execute(self, order: tuple[str, ...], slot: int) -> RunResult:
        with self._lock:
            self._counter += 1
            junit = self._workdir / f"run-{self._counter}.junit.xml"
        env = {**os.environ, **(self.env or {})}
        start = time.perf_counter()
        process = subprocess.Popen(
            self.argv(order, str(junit)),
            cwd=self.slots[slot],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        with self._lock:
            self._active.add(process)
        timed_out = False
        try:
            output, _ = process.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(process)
            output, _ = process.communicate()
        except BaseException:
            # Interrupted (Ctrl-C) or failed while waiting: the child runs in its own session
            # and would not see the signal, so kill its whole process group before leaving.
            _kill(process)
            process.communicate()
            raise
        finally:
            with self._lock:
                self._active.discard(process)
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

    def kill_active(self) -> None:
        """Kill the process groups of all runs in progress."""
        with self._lock:
            active = list(self._active)
        for process in active:
            _kill(process)

    def close(self) -> None:
        self.kill_active()
        self._finalizer()


class SimulatedRunner(BaseRunner):
    """An in-process runner driven by a function from an order to outcomes.

    It shares the caching and batching code with ``CommandRunner`` and is what the tests and the
    run-count part of the cost study use; it never starts a process. ``executed`` may reorder the
    tests to model a runner that does not honour the requested order.
    """

    def __init__(
        self,
        outcomes: Callable[[tuple[str, ...]], dict[str, str]],
        *,
        executed: Callable[[tuple[str, ...]], list[str]] | None = None,
        jobs: int = 1,
    ) -> None:
        super().__init__(jobs)
        self._outcomes = outcomes
        self._executed = executed

    def _execute(self, order: tuple[str, ...], slot: int) -> RunResult:
        outcomes = self._outcomes(order)
        executed = self._executed(order) if self._executed else list(order)
        return RunResult(order, outcomes, executed, returncode=0, seconds=0.0)

    def repro_command(self, order: Sequence[str]) -> str:
        return "python -m pytest " + shlex.join(order)


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

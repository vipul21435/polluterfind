"""Cost of localising a planted cause, against suite size, for the three search methods.

Part "counts" uses the in-process model (no processes): for every size, scenario, method and
seed it records the runs the search needed and whether it found the planted cause. Part "wall"
writes real suites to disk and runs pytest for each candidate order, recording runs and wall
time. Only the localisation step is measured; verification and the cleaner scan are not.

    python benchmarks/cost_study.py counts
    python benchmarks/cost_study.py wall --sizes 100 500 2000
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import tempfile
import time
from pathlib import Path

from polluterfind.generate import plant
from polluterfind.runner import CommandRunner, SimulatedRunner
from polluterfind.search import find_cleaners, localise

SCENARIOS = {
    "single polluter": ("victim", 1),
    "paired polluters": ("victim", 2),
    "single state-setter": ("brittle", 1),
    "paired state-setters": ("brittle", 2),
}
METHODS = ("auto", "ddmin", "linear")


def measure(runner, plan, method: str) -> tuple[int, bool, float]:
    start = time.perf_counter()
    before = runner.stats.runs
    causes, _ = localise(
        runner, plan.ids[:-1], plan.target_id, want_failure=plan.kind == "victim", method=method
    )
    seconds = time.perf_counter() - start
    return runner.stats.runs - before, causes == plan.planted("set"), seconds


def counts(sizes: list[int], seeds: int, out: Path) -> None:
    rows = []
    for n in sizes:
        for scenario, (kind, causes) in SCENARIOS.items():
            for method in METHODS:
                runs, found, cleaner_runs = [], 0, []
                for seed in range(seeds):
                    plan = plant(n, kind=kind, causes=causes, seed=seed)
                    runner = SimulatedRunner(plan.outcomes)
                    r, ok, _ = measure(runner, plan, method)
                    runs.append(r)
                    found += ok
                    if kind == "victim" and method == "auto" and ok:
                        before = runner.stats.runs
                        find_cleaners(runner, plan.ids, plan.planted("set"), plan.target_id)
                        cleaner_runs.append(runner.stats.runs - before)
                rows.append(
                    {
                        "tests": n,
                        "scenario": scenario,
                        "method": method,
                        "seeds": seeds,
                        "found": found,
                        "runs_mean": round(statistics.mean(runs), 1),
                        "runs_max": max(runs),
                        "cleaner_runs_mean": (
                            round(statistics.mean(cleaner_runs), 1) if cleaner_runs else ""
                        ),
                    }
                )
    write(rows, out / "run_counts.csv")


def wall(sizes: list[int], linear_sizes: list[int], workdir: Path, out: Path) -> None:
    rows = []
    configs = []
    for n in sizes:
        for scenario in ("single polluter", "paired polluters"):
            for method in METHODS:
                # The linear scan is wall-timed only where it is affordable on a loaded
                # machine; its run counts at every size come from part "counts".
                if method == "linear" and (n not in linear_sizes or scenario != "single polluter"):
                    continue
                configs.append((n, scenario, method, 1))
    configs.append((max(sizes), "paired polluters", "ddmin", 2))
    for n, scenario, method, jobs in configs:
        kind, causes = SCENARIOS[scenario]
        plan = plant(n, kind=kind, causes=causes, seed=0)
        project = plan.write(workdir / f"suite-{n}-{causes}")
        with CommandRunner(project, timeout=600, jobs=jobs) as runner:
            runs, ok, seconds = measure(runner, plan, method)
        row = {
            "tests": n,
            "scenario": scenario,
            "method": method,
            "jobs": jobs,
            "found": ok,
            "runs": runs,
            "seconds": round(seconds, 1),
            "seconds_per_run": round(seconds / runs, 2) if runs else "",
        }
        print(row, flush=True)
        rows.append(row)
    write(rows, out / "wall_time.csv")


def write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", choices=["counts", "wall"])
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 200, 500, 1000, 2000])
    parser.add_argument("--seeds", type=int, default=20, help="seeds per cell (counts)")
    parser.add_argument("--linear-sizes", type=int, nargs="+", default=[100])
    parser.add_argument("--workdir", type=Path, help="where wall-time suites are written")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()
    if args.part == "counts":
        counts(args.sizes, args.seeds, args.out)
    else:
        workdir = args.workdir or Path(tempfile.mkdtemp(prefix="polluterfind-suites-"))
        wall(args.sizes, args.linear_sizes, workdir, args.out)


if __name__ == "__main__":
    main()

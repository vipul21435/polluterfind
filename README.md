# polluterfind

Given a pytest test that passes alone and fails in the suite (or the reverse), polluterfind finds a
minimal set of other tests whose earlier execution causes it, by delta debugging over the test order.

## Why this is hard

An order-dependent test fails only in some orders. The cause is state that a different test left
behind (a module-level registry, an environment variable, a file), so the failing test's own code
and traceback point at the wrong place. A suite can have thousands of tests that ran earlier, any
of them or any combination of them can be the cause, and every check costs a pytest run. The
problem is common: Gruber et al. found that order dependency caused 59 % of the 7,571 flaky
tests in their sample of 22,352 PyPI projects.

## Install

```
pip install git+https://github.com/vipul21435/polluterfind
```

Install it into the environment that runs your tests, or pass that environment's interpreter with
`--python`. polluterfind itself has no runtime dependencies; Python 3.10 or later.

## Quickstart

`examples/unit_registry` is a small unit converter with a module-level registry and eleven tests.
One test registers a unit and never removes it; another checks that the registry holds the
defaults. The suite fails in its normal order. From that directory:

```
$ polluterfind find tests/test_units.py::test_known_units_are_the_defaults
# polluterfind report

victim `tests/test_units.py::test_known_units_are_the_defaults`

- kind: victim: passes alone, fails after the tests before it
- alone: passed 3 of 3 (pass rate 95 % Wilson interval 0.44 to 1.00)
- after the 8 tests before it: passed 0 of 3 (pass rate 95 % Wilson interval 0.00 to 0.56)
- polluters (1, by bisection in 3 runs): `tests/test_plugins.py::test_register_furlong`
- confirmation: victim failed in 3 of 3 reruns after the polluters (confirmed)
- cleaners: `tests/test_units.py::test_reset_restores_defaults` (8 candidates checked)
- test runs: 20, cache hits: 1, tests executed: 70, time: 8.2 s

reproduce:

    python -m pytest -p no:randomly -p no:cacheprovider -q tests/test_plugins.py::test_register_furlong tests/test_units.py::test_known_units_are_the_defaults

passes again with the cleaner:

    python -m pytest -p no:randomly -p no:cacheprovider -q tests/test_plugins.py::test_register_furlong tests/test_units.py::test_reset_restores_defaults tests/test_units.py::test_known_units_are_the_defaults
```

The 20 runs are 6 for the verification, 3 for the bisection, 3 confirmation reruns and 8 for the
cleaner scan; the time is wall clock on a loaded laptop and is nearly all pytest start-up.

`polluterfind verify <id>` runs only the classification step. `polluterfind discover` needs no
test id: it runs the whole suite in the given order, reversed and in `--orders` seeded random
orders (default 3), lists the tests whose outcome changed and searches each one. All three
commands take `--format json`, `--out FILE` and `--jobs N`. `verify` exits 0 when the test is
order-dependent, `find` when the cause was found and confirmed, `discover` when every suite run
was usable; otherwise 1, 2 on usage errors, and 3 when `discover` had a broken suite run (a bad
id, a crash, a timeout), which it reports with the run's last output lines. `examples/find_polluter.py` does the same from Python.

## How it works

The terms are those of Shi et al., "iFixFlakies: A Framework for Automatically Fixing
Order-Dependent Flaky Tests" (ESEC/FSE 2019), definitions 3 to 7: a *victim* passes alone and
fails after a *polluter*, run(P + [v]) = FAIL; a *brittle* test fails alone and passes after a
*state-setter*, run(S + [b]) = PASS; a *cleaner* C makes the victim pass again,
run(P + C + [v]) = PASS.

1. **Order.** The suite order is pytest's collection order (`--collect-only -q`) or a file of node
   ids (`--order-file`). Node ids have the form `path/test_mod.py::TestClass::test_method[param]`
   described in the pytest documentation ("How to invoke pytest"). The tests before the victim
   are its prefix.
2. **Verify.** The victim runs alone and after its full prefix, alternately, `--reruns` times each
   (default 3). Passes alone and fails after the prefix: victim. The reverse: brittle. A pass and
   a fail among the reruns of one order: flaky regardless of order, and the search stops, because
   no test order explains it. Each count comes with a 95 % Wilson score interval for the pass
   rate.
3. **Bisection** (`--method auto`, the default). Assuming one polluter, run the left half of the
   prefix before the victim; if the victim still fails keep the left half, otherwise take the
   right half without running it. That is about log2(n) runs plus one confirming run.
4. **ddmin.** If the confirmation fails (the failure needs two or more tests together), the search
   falls back to ddmin from Zeller and Hildebrandt, "Simplifying and Isolating Failure-Inducing
   Input" (IEEE TSE 28(2), 2002). Subsets keep the suite's relative order. The result is
   1-minimal: removing any one test from it makes the victim pass again. `--method ddmin` skips
   the bisection; `--method linear` tries each earlier test alone, which is the baseline in the
   results below.
5. **Confirm and clean.** The minimal set and the victim rerun `--reruns` times. For a victim,
   each other test is then tried between the polluters and the victim until `--cleaners` cleaners
   are found (default 1; `-1` checks all, `0` skips).
6. **Discover.** Lam et al., "iDFlakies: A Framework for Detecting and Partially Classifying
   Flaky Tests" (2019), detect flaky tests, partially classify them as order-dependent or not,
   and study how reordering a suite changes how many are found. `discover` is a minimal
   reorder-and-compare pass in that spirit (given, reversed, k seeded shuffles, one run each).
   For each test whose outcome changed it runs `find` on an order where the test failed and, if
   that does not show a victim, on an order where it passed (a brittle test shows up there).

Every run is a subprocess built from a command template (`--command`) with `{tests}` for the
ordered ids, `{junit}` for the report path and `{python}` for the interpreter. The default is

    {python} -m pytest -p no:randomly -p no:cacheprovider -q --junitxml={junit} {tests}

where `-p no:randomly` keeps pytest-randomly, if installed, from shuffling the run. Outcomes are
read from the JUnit XML report, by mapping each node id to the `classname` and `name` pytest
writes for it, not from the console text. The report also lists the tests in the order they ran;
when that differs from the requested order (pytest regroups tests that share a parametrized
fixture of module or session scope), the run is counted and the report prints a warning with the
first such order. Runs are cached by the ordered id list, and each run has a timeout
(`--timeout`, default 300 s) after which its whole process group is killed; a timed-out run
counts as neither a pass nor a fail.

With `--jobs N` the project directory is copied once per worker (without `.git`, virtual
environments and caches) and up to N runs go at once, one per copy: the verification reruns, the
subsets of one ddmin round, the confirmation reruns and the cleaner candidates. The answer is the
same as with one job (ddmin takes the first reproducing subset in order); only the run count can
grow. Limits: disk use is N copies of the project; an absolute path or an editable install that
points at the original directory bypasses the copy; state outside the directory (a database
server, a shared temporary file, network services) is still shared between workers.

## Results

All numbers come from pytest suites written by the repository's own generator
(`polluterfind.generate`); no third-party project was run. Each suite has n tests sharing one
module-level dict. The last test is the target. The planted polluters (or state-setters) sit at
seeded random positions before it, and for victims a cleaner sits before the first polluter, so
the suite order still fails. The generated code is MIT-licensed with the rest of the repository;
the CSV files are in `benchmarks/results/`.

**Runs needed to localise the cause** (search step only, without verification or cleaner scan),
mean and in brackets maximum over 20 seeds, from the in-process model of the same suites
(`python benchmarks/cost_study.py counts`, 7 s):

| tests | single polluter: auto | ddmin | linear | paired polluters: auto | ddmin | linear |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 7.5 (8) | 10.4 (13) | 60.5 (98) | 39.1 (55) | 31.7 (47) | 99, not found |
| 200 | 8.4 (9) | 11.8 (14) | 120.7 (195) | 48.8 (66) | 40.1 (57) | 199, not found |
| 500 | 9.4 (10) | 13.7 (16) | 314 (495) | 59.4 (69) | 49.5 (59) | 499, not found |
| 1000 | 10.5 (11) | 15.2 (17) | 627.4 (989) | 69.5 (81) | 58.5 (70) | 999, not found |
| 2000 | 11.6 (12) | 16.8 (18) | 1254.5 (1977) | 77.5 (87) | 65.5 (75) | 1999, not found |

| tests | single state-setter: auto | ddmin | linear | paired state-setters: auto | ddmin | linear |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 7.3 (8) | 10 (12) | 45.9 (87) | 44.2 (56) | 36.6 (48) | 99, not found |
| 200 | 8.3 (9) | 11.3 (14) | 91.0 (174) | 53.2 (65) | 44.3 (56) | 199, not found |
| 500 | 9.5 (10) | 13.8 (16) | 241.3 (495) | 64 (73) | 54.1 (63) | 499, not found |
| 1000 | 10.5 (11) | 15.3 (17) | 482.3 (989) | 72.5 (81) | 61.5 (70) | 999, not found |
| 2000 | 11.4 (12) | 17 (18) | 964.1 (1977) | 80 (88) | 68.0 (76) | 1999, not found |

Every auto and ddmin search found exactly the planted tests (20 of 20 per cell). With one cause
the bisection needs about log2(n) + 1 runs, roughly 30 % fewer than ddmin. With two causes the
failed bisection costs 7 to 12 runs more than ddmin alone, so `--method ddmin` is cheaper when
several tests are known to be involved. The linear scan grows with n and cannot find a pair. The cleaner scan is linear too:
with the cleaner at a random position before the polluter it took a mean of 28.1 runs at 100
tests and 611.9 at 2,000 (single polluter), which is why `--cleaners 0` exists.

**Wall time on real pytest runs**, seed 0, one suite per row, `--jobs 1` unless stated
(`python benchmarks/cost_study.py wall --sizes 100 500 2000`). The timings were taken on a
heavily loaded laptop (load average between 20 and 46 on 8 cores while they ran), so read them for
the shape, not the absolute values; nearly all of each run is pytest start-up.

| tests | scenario | method | jobs | runs | seconds | seconds per run |
|---:|---|---|---:|---:|---:|---:|
| 100 | single polluter | auto | 1 | 7 | 3.3 | 0.47 |
| 100 | single polluter | ddmin | 1 | 13 | 6.0 | 0.46 |
| 100 | single polluter | linear | 1 | 98 | 33.3 | 0.34 |
| 100 | paired polluters | auto | 1 | 44 | 12.7 | 0.29 |
| 100 | paired polluters | ddmin | 1 | 38 | 12.1 | 0.32 |
| 500 | single polluter | auto | 1 | 9 | 3.7 | 0.41 |
| 500 | single polluter | ddmin | 1 | 15 | 6.0 | 0.4 |
| 500 | paired polluters | auto | 1 | 51 | 23.3 | 0.46 |
| 500 | paired polluters | ddmin | 1 | 42 | 17.6 | 0.42 |
| 2000 | single polluter | auto | 1 | 11 | 7.5 | 0.68 |
| 2000 | single polluter | ddmin | 1 | 18 | 12.2 | 0.68 |
| 2000 | paired polluters | auto | 1 | 70 | 36.8 | 0.53 |
| 2000 | paired polluters | ddmin | 1 | 58 | 36.7 | 0.63 |
| 2000 | paired polluters | ddmin | 2 | 62 | 19.8 | 0.32 |

Every row found the planted tests. The run counts of the one-worker rows equal the in-process
model's counts for seed 0, which checks the model against real pytest. "Seconds per run" is wall
time divided by runs. The linear scan was timed only at 100 tests (98 runs, 33.3 s); at larger
sizes only its run counts (table above) were measured. With two workers, ddmin on the
2,000-test paired case needed 62 runs instead of 58 (a round's subsets are tried two at a time)
and took 19.8 s instead of 36.7 s.

**The bundled example** (quickstart above): 1 polluter and 1 cleaner among 11 tests, found in
20 runs (3 of them for the search itself) and 8.2 s, as shown in the quickstart.

## Limitations

- This release has not been run on third-party projects. Every measurement above is on suites
  the repository generates itself, where the shared state is one module-level dict.
- polluterfind assumes each run starts from the same state. State that outlives a pytest process
  (a file written into the project, a database, a cache directory) leaks from one run into the
  next, and with `--jobs` it leaks within each worker's copy.
- Reruns cannot tell periodic flakiness from order dependence: a test whose outcome flips on every
  run lines up with the alternating alone/prefix schedule and is classified as a victim or brittle
  (there is a test that shows this).
- ddmin's guarantee is 1-minimality, not the smallest set: with several independent polluters it
  returns one 1-minimal set, not all of them.
- When pytest regroups the requested order (parametrized fixtures of module or session scope),
  polluterfind warns but does not work around it.
- The command line passes every id as an argument; very long orders on systems with a small
  argument limit are not handled.
- `discover` runs each order once, so a test that fails in only one order by chance is a
  candidate until `verify` rejects it as flaky. Tested on macOS and Linux only.

## Related tools

- [graderguard](https://github.com/vipul21435/graderguard) audits benchmark graders by running
  cheats against them; polluterfind localises the cause of an order-dependent test.
- [patchmin](https://github.com/vipul21435/patchmin) applies delta debugging to patches.
- [testlogs](https://github.com/vipul21435/testlogs) parses test-runner output.
- The International Dataset of Flaky Tests (https://github.com/TestingResearchIllinois/idoft)
  lists order-dependent tests in open-source projects, with a Python list (`py-data.csv`) whose
  categories include OD-Vic and OD-Brit in the iFixFlakies sense. Its page states no licence, and
  no data from it is included here.

References: Zeller and Hildebrandt, IEEE TSE 28(2), 2002, doi:10.1109/32.988498; Lam, Oei, Shi,
Marinov and Xie, iDFlakies, 2019, doi:10.1109/ICST.2019.00038; Shi, Lam, Oei, Xie and Marinov,
iFixFlakies, ESEC/FSE 2019, doi:10.1145/3338906.3338925; Gruber, Lukasczyk, Kroiß and Fraser, "An
Empirical Study of Flaky Tests in Python", ICST 2021, arXiv:2101.09077; pytest documentation,
"How to invoke pytest" (https://docs.pytest.org/en/stable/how-to/usage.html).

## Licence

MIT. See [LICENSE](LICENSE).

Built by Vipul Raj Jha · https://vipul21435.github.io

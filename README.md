# polluterfind

Given a pytest test that passes alone and fails in the suite (or the reverse), polluterfind finds a
minimal set of other tests whose earlier execution causes it, by delta debugging over the test order.

Status: early. `verify` and `find` work on pytest suites. `discover`, parallel runs (`--jobs`) and
results on real projects are not implemented yet; see [What is not done yet](#what-is-not-done-yet).

## Why this is hard

An order-dependent test fails only in some orders. The cause is state that a different test left
behind (a module-level registry, an environment variable, a file), so the failing test's own code
and traceback point at the wrong place. A suite can have thousands of tests that ran earlier, any
of them or any combination of them can be the cause, and every check costs a pytest run.

## Install

```
pip install git+https://github.com/vipul21435/polluterfind
```

Install it into the environment that runs your tests, or pass that environment's interpreter with
`--python`. polluterfind itself has no runtime dependencies.

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
- polluters (1, by bisection): `tests/test_plugins.py::test_register_furlong`
- confirmation: victim failed in 3 of 3 reruns after the polluters (confirmed)
- cleaners: `tests/test_units.py::test_reset_restores_defaults` (8 candidates checked)
- test runs: 20, cache hits: 1, tests executed: 70, time: 17.5 s

reproduce:

    python -m pytest -p no:randomly -p no:cacheprovider -q tests/test_plugins.py::test_register_furlong tests/test_units.py::test_known_units_are_the_defaults

passes again with the cleaner:

    python -m pytest -p no:randomly -p no:cacheprovider -q tests/test_plugins.py::test_register_furlong tests/test_units.py::test_reset_restores_defaults tests/test_units.py::test_known_units_are_the_defaults
```

The time is wall clock on a heavily loaded laptop; nearly all of it is pytest start-up across the
20 runs. `polluterfind verify <id>` runs only the classification step. Both commands take
`--format json` and `--out FILE`. They exit 0 when the test is order-dependent (verify) or the
cause was found and confirmed (find), 1 otherwise, and 2 on usage errors.

## How it works

The terms are those of Shi et al., "iFixFlakies: A Framework for Automatically Fixing
Order-Dependent Flaky Tests" (ESEC/FSE 2019): a *victim* passes alone and fails after a *polluter*;
a *brittle* test fails alone and passes after a *state-setter*; a *cleaner* is a test that, run
between the polluter and the victim, makes the victim pass.

1. **Order.** The suite order is pytest's collection order (`--collect-only -q`) or a file of ids
   (`--order-file`). The tests before the victim are its prefix.
2. **Verify.** The victim runs alone and after its full prefix, `--reruns` times each (default 3).
   Passes alone and fails after the prefix: victim. The reverse: brittle. A pass and a fail within
   reruns of the same order: flaky regardless of order, and the search stops, because no test
   order explains it. Each count is reported with a 95 % Wilson score interval for the pass rate.
3. **Bisection.** Assuming one polluter, run the left half of the prefix before the victim; if the
   victim still fails, keep the left half, otherwise take the right half without running it. That
   is about log2(n) runs plus one confirming run of the single candidate.
4. **ddmin.** If the confirmation fails (the failure needs two or more tests together), the search
   falls back to ddmin from Zeller and Hildebrandt, "Simplifying and Isolating Failure-Inducing
   Input" (IEEE TSE 28(2), 2002), over the prefix. Subsets keep the suite's relative order. The
   result is 1-minimal: removing any one test from it makes the victim pass again.
5. **Confirm and clean.** The minimal set and the victim rerun `--reruns` times. For a victim, each
   other test is then tried between the polluters and the victim until `--cleaners` cleaners are
   found (default 1; `-1` checks all, `0` skips).

Every run is a subprocess built from a command template (`--command`) with `{tests}` for the
ordered ids, `{junit}` for the report path and `{python}` for the interpreter. The default is
pytest with `-p no:randomly`, so a shuffling plugin cannot reorder the run. Outcomes are read from
the JUnit XML report, by mapping each node id to the `classname` and `name` pytest writes for it,
not from the console text. Runs are cached by the ordered id list, and each run has a timeout
(`--timeout`, default 300 s); a run that times out counts as neither a pass nor a fail.

## What is not done yet

- `polluterfind discover` (run the suite in several orders and search every order-dependent test).
- `--jobs` to run candidates in parallel on copies of the project directory.
- Results on real open-source projects.
- State that outlives a pytest process (a file written into the project, a database) leaks from
  one run into the next; polluterfind assumes each run starts from the same state.
- pytest may reorder tests that share a parametrized fixture of module or session scope; the
  report does not yet warn when the executed order differs from the requested one.
- Tested on macOS and Linux only.

## Related tools

- [graderguard](https://github.com/vipul21435/graderguard) audits benchmark graders; polluterfind
  localises the cause of an order-dependent test rather than detecting flaky tests.
- [patchmin](https://github.com/vipul21435/patchmin) applies delta debugging to patches.
- [testlogs](https://github.com/vipul21435/testlogs) parses test-runner output.

## Licence

MIT. See [LICENSE](LICENSE).

Built by Vipul Raj Jha · https://vipul21435.github.io

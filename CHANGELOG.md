# Changelog

## 0.1.0

First release.

- `polluterfind verify`: runs a test alone and after the tests before it, `--reruns` times each,
  and classifies it as victim, brittle, not order-dependent, flaky regardless of order, or
  unresolved, with 95 % Wilson intervals for the pass rates.
- `polluterfind find`: localises a 1-minimal set of polluters (victim) or state-setters
  (brittle) with a single-cause bisection and a ddmin fallback (`--method auto`), or with ddmin,
  bisection or a linear scan alone; confirms it with reruns; scans for cleaners.
- `polluterfind discover`: runs the suite in the given order, reversed and in `--orders` seeded
  random orders, lists tests whose outcome changed, and searches each.
- Outcomes come from pytest's JUnit XML. Runs are cached by the ordered id list, have a timeout,
  and can run in parallel (`--jobs`) in per-worker copies of the project directory.
- Reports in Markdown and JSON, with the shortest reproducing command, and a warning when the
  JUnit report shows that the tests ran in a different order than requested.
- A broken run (bad id, collection or import error, missing pytest, timeout) is named with its
  exit code and last output lines; `discover` exits 3 when a suite run is broken, and Ctrl-C
  kills the running test processes and exits 130.
- `polluterfind.generate`: pytest suites with planted polluters, cleaners and state-setters, and
  an in-process model of their outcomes; `benchmarks/cost_study.py` measures search cost on them.

"""JSON and Markdown reports for verification and search results."""

from __future__ import annotations

import json
from typing import Any

from . import __version__
from .discover import DiscoverResult
from .search import FindResult
from .verify import BRITTLE, FLAKY, NOT_ORDER_DEPENDENT, UNRESOLVED, VICTIM, Tally, Verification

KIND_TEXT = {
    VICTIM: "victim: passes alone, fails after the tests before it",
    BRITTLE: "brittle: fails alone, passes after the tests before it",
    NOT_ORDER_DEPENDENT: "not order-dependent: same outcome alone and after the tests before it",
    FLAKY: "flaky regardless of order: outcome changed between reruns of one order",
    UNRESOLVED: "unresolved: no pass or fail recorded (skipped, missing or timed out)",
}


def tally_dict(tally: Tally) -> dict[str, Any]:
    low, high = tally.pass_interval()
    return {
        "passed": tally.passed,
        "failed": tally.failed,
        "unresolved": tally.unresolved,
        "pass_rate_wilson95": [round(low, 4), round(high, 4)],
        "outcomes": tally.outcomes,
    }


def verification_dict(verification: Verification) -> dict[str, Any]:
    return {
        "victim": verification.victim,
        "kind": verification.kind,
        "prefix_length": len(verification.prefix),
        "reruns": verification.reruns,
        "alone": tally_dict(verification.alone),
        "after_prefix": tally_dict(verification.after_prefix),
    }


def find_dict(result: FindResult) -> dict[str, Any]:
    causes_key = "state_setters" if result.kind == BRITTLE else "polluters"
    return {
        "tool": f"polluterfind {__version__}",
        **verification_dict(result.verification),
        causes_key: result.causes,
        "method": result.method,
        "confirmation": tally_dict(result.confirmation) if result.confirmation else None,
        "confirmed": result.confirmed,
        "cleaners": result.cleaners,
        "cleaner_candidates_checked": result.cleaner_candidates_checked,
        "search_runs": result.search_runs,
        "test_runs": result.runs,
        "cache_hits": result.cache_hits,
        "tests_executed": result.tests_executed,
        "seconds": round(result.seconds, 2),
        "repro_command": result.repro_command,
        "cleaner_command": result.cleaner_command,
        "reordered_runs": result.reordered_runs,
        "reordered_example": (
            {"requested": list(ex[0]), "executed": list(ex[1])}
            if (ex := result.reordered_example)
            else None
        ),
    }


def discover_dict(result: DiscoverResult) -> dict[str, Any]:
    return {
        "tool": f"polluterfind {__version__}",
        "orders": [
            {
                "name": run.name,
                "tests": len(run.order),
                "failed": run.failed,
                "order_respected": run.order_respected,
                "problem": run.problem,
                "output_tail": run.output_tail if run.problem else "",
            }
            for run in result.orders
        ],
        "order_dependent_candidates": [
            {
                "test": c.test,
                "outcomes": c.outcomes,
                "result": find_dict(c.result) if c.result else None,
            }
            for c in result.candidates
        ],
        "test_runs": result.runs,
        "cache_hits": result.cache_hits,
        "seconds": round(result.seconds, 2),
    }


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _tally_line(label: str, tally: Tally) -> str:
    low, high = tally.pass_interval()
    extra = f", {tally.unresolved} unresolved" if tally.unresolved else ""
    return (
        f"- {label}: passed {tally.passed} of {tally.resolved}{extra} "
        f"(pass rate 95 % Wilson interval {low:.2f} to {high:.2f})"
    )


def verification_markdown(verification: Verification) -> list[str]:
    after = f"after the {len(verification.prefix)} tests before it"
    return [
        f"victim `{verification.victim}`",
        "",
        f"- kind: {KIND_TEXT[verification.kind]}",
        _tally_line("alone", verification.alone),
        _tally_line(after, verification.after_prefix),
    ]


def find_markdown(result: FindResult) -> str:
    lines = ["# polluterfind report", "", *verification_markdown(result.verification)]
    if result.method != "none":
        names = ", ".join(f"`{c}`" for c in result.causes) or "none found"
        lines.append(
            f"- {result.role}s ({len(result.causes)}, by {result.method} "
            f"in {result.search_runs} runs): {names}"
        )
        if result.confirmation is not None:
            confirmation = result.confirmation
            want = "failed" if result.kind == VICTIM else "passed"
            count = confirmation.failed if result.kind == VICTIM else confirmation.passed
            status = "confirmed" if result.confirmed else "NOT confirmed"
            lines.append(
                f"- confirmation: victim {want} in {count} of {len(result.confirmation.outcomes)} "
                f"reruns after the {result.role}s ({status})"
            )
        if result.kind == VICTIM and result.causes:
            if result.cleaners:
                cleaners = ", ".join(f"`{c}`" for c in result.cleaners)
                lines.append(
                    f"- cleaners: {cleaners} "
                    f"({result.cleaner_candidates_checked} candidates checked)"
                )
            else:
                lines.append(
                    f"- cleaners: none among {result.cleaner_candidates_checked} candidates checked"
                )
    lines.append(
        f"- test runs: {result.runs}, cache hits: {result.cache_hits}, "
        f"tests executed: {result.tests_executed}, time: {result.seconds:.1f} s"
    )
    if result.reordered_runs and result.reordered_example:
        requested, executed = result.reordered_example
        lines += [
            "",
            f"WARNING: in {result.reordered_runs} runs the JUnit report shows a different order "
            "than requested (for example a parametrized fixture of module or session scope "
            "makes pytest regroup tests), so the result may not hold for the requested order.",
            f"first case, requested: {' '.join(requested)}",
            f"executed: {' '.join(executed)}",
        ]
    if result.repro_command:
        lines += ["", "reproduce:", "", "    " + result.repro_command]
    if result.cleaner_command:
        lines += ["", "passes again with the cleaner:", "", "    " + result.cleaner_command]
    return "\n".join(lines) + "\n"


def verify_markdown(verification: Verification) -> str:
    return "\n".join(["# polluterfind verify", "", *verification_markdown(verification)]) + "\n"


def discover_markdown(result: DiscoverResult) -> str:
    lines = ["# polluterfind discover", "", "| order | tests | failed | order respected |"]
    lines.append("|---|---:|---:|---|")
    for run in result.orders:
        respected = "yes" if run.order_respected else "NO"
        failed = f"run broken: {run.problem}" if run.problem else str(len(run.failed))
        lines.append(f"| {run.name} | {len(run.order)} | {failed} | {respected} |")
    lines.append("")
    for run in result.broken_runs:
        lines += [f"ERROR: the {run.name} run is broken ({run.problem}); last output:", ""]
        lines += ["    " + line for line in run.output_tail.splitlines()] + [""]
    if len(result.broken_runs) == len(result.orders):
        lines.append("No usable run: nothing can be said about order dependence.")
    elif not result.candidates:
        lines.append("No test changed outcome between the usable orders.")
    for candidate in result.candidates:
        pattern = ", ".join(f"{name}: {o}" for name, o in candidate.outcomes.items())
        lines += [f"## `{candidate.test}`", "", f"outcomes: {pattern}", ""]
        found = candidate.result
        if found is None:
            lines.append("not searched")
        else:
            lines += find_markdown(found).splitlines()[2:]
        lines.append("")
    lines.append(
        f"total test runs: {result.runs}, cache hits: {result.cache_hits}, "
        f"time: {result.seconds:.1f} s"
    )
    return "\n".join(lines) + "\n"

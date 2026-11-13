"""Command line: ``polluterfind verify``, ``find`` and ``discover``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .discover import discover
from .report import (
    discover_dict,
    discover_markdown,
    find_dict,
    find_markdown,
    to_json,
    verification_dict,
    verify_markdown,
)
from .runner import PYTEST_TEMPLATE, CommandRunner, collect_pytest
from .search import METHODS, find
from .verify import BRITTLE, VICTIM, verify


def read_order(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", type=Path, default=Path("."), help="project directory")
    parser.add_argument(
        "--order-file",
        type=Path,
        help="test ids in suite order, one per line (default: pytest's collection order)",
    )
    parser.add_argument("--python", help="interpreter of the project's environment")
    parser.add_argument(
        "--command",
        default=PYTEST_TEMPLATE,
        help="command template with {tests}, {junit} and optionally {python} "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="seconds per run (default: %(default)s)"
    )
    parser.add_argument(
        "--reruns", type=int, default=3, help="reruns per verified order (default: %(default)s)"
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="parallel runs, each in its own copy of the project directory (default: 1)",
    )
    parser.add_argument("--format", choices=["md", "json"], default="md", help="report format")
    parser.add_argument("--out", type=Path, help="write the report here instead of stdout")


def _search_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--method",
        choices=METHODS,
        default="auto",
        help="auto: bisection, then ddmin if that fails; or ddmin, bisection, linear only "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--cleaners",
        type=int,
        default=1,
        help="stop after this many cleaners; 0 skips the search, -1 checks every test "
        "(default: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polluterfind",
        description="Find the tests whose earlier execution makes another test fail.",
    )
    parser.add_argument("--version", action="version", version=f"polluterfind {__version__}")
    commands = parser.add_subparsers(dest="command_name", required=True)
    verify_parser = commands.add_parser(
        "verify", help="check that a test passes alone and fails after its prefix (or the reverse)"
    )
    verify_parser.add_argument("victim", help="node id of the order-dependent test")
    _common(verify_parser)
    find_parser = commands.add_parser(
        "find", help="verify, then search for a minimal set of polluters and a cleaner"
    )
    find_parser.add_argument("victim", help="node id of the order-dependent test")
    _common(find_parser)
    _search_options(find_parser)
    discover_parser = commands.add_parser(
        "discover",
        help="run the suite in several orders, list tests whose outcome changed, search each",
    )
    _common(discover_parser)
    _search_options(discover_parser)
    discover_parser.add_argument(
        "--orders",
        type=int,
        default=3,
        help="seeded random orders besides the given and reversed ones (default: %(default)s)",
    )
    discover_parser.add_argument("--seed", type=int, default=0, help="first seed (default: 0)")
    discover_parser.add_argument(
        "--no-search", action="store_true", help="list the candidates without searching"
    )
    return parser


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for name in ("reruns", "jobs"):
        if getattr(args, name) < 1:
            print(f"polluterfind: --{name} must be at least 1", file=sys.stderr)
            return 2
    if getattr(args, "orders", 0) < 0:
        print("polluterfind: --orders must not be negative", file=sys.stderr)
        return 2
    try:
        if args.order_file:
            order = read_order(args.order_file)
        else:
            order = collect_pytest(args.project, args.python).ids
        victim = getattr(args, "victim", None)
        if victim is not None and victim not in order:
            print(f"polluterfind: {victim} is not in the test order", file=sys.stderr)
            return 2
        runner = CommandRunner(
            args.project, args.command, python=args.python, timeout=args.timeout, jobs=args.jobs
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"polluterfind: {error}", file=sys.stderr)
        return 2

    with runner:
        if args.command_name == "verify":
            checked = verify(runner, order, victim, args.reruns)
            text = (
                to_json(verification_dict(checked))
                if args.format == "json"
                else verify_markdown(checked)
            )
            _emit(text, args.out)
            return 0 if checked.kind in (VICTIM, BRITTLE) else 1

        if args.command_name == "find":
            result = find(
                runner,
                order,
                victim,
                reruns=args.reruns,
                max_cleaners=args.cleaners,
                method=args.method,
            )
            text = to_json(find_dict(result)) if args.format == "json" else find_markdown(result)
            _emit(text, args.out)
            return 0 if result.confirmed else 1

        found = discover(
            runner,
            order,
            orders=args.orders,
            seed=args.seed,
            reruns=args.reruns,
            method=args.method,
            max_cleaners=args.cleaners,
            search=not args.no_search,
        )
        text = to_json(discover_dict(found)) if args.format == "json" else discover_markdown(found)
        _emit(text, args.out)
        return 0

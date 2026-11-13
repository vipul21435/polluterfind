"""Command line: ``polluterfind verify`` and ``polluterfind find``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .report import find_dict, find_markdown, to_json, verification_dict, verify_markdown
from .runner import PYTEST_TEMPLATE, CommandRunner, collect_pytest
from .search import find
from .verify import BRITTLE, VICTIM, verify


def read_order(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("victim", help="node id of the order-dependent test")
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
    parser.add_argument("--format", choices=["md", "json"], default="md", help="report format")
    parser.add_argument("--out", type=Path, help="write the report here instead of stdout")


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
    _common(verify_parser)
    find_parser = commands.add_parser(
        "find", help="verify, then search for a minimal set of polluters and a cleaner"
    )
    _common(find_parser)
    find_parser.add_argument(
        "--cleaners",
        type=int,
        default=1,
        help="stop after this many cleaners; 0 skips the search, -1 checks every test "
        "(default: %(default)s)",
    )
    return parser


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.reruns < 1:
        print("polluterfind: --reruns must be at least 1", file=sys.stderr)
        return 2
    try:
        if args.order_file:
            order = read_order(args.order_file)
        else:
            order = collect_pytest(args.project, args.python).ids
        if args.victim not in order:
            print(f"polluterfind: {args.victim} is not in the test order", file=sys.stderr)
            return 2
        runner = CommandRunner(args.project, args.command, python=args.python, timeout=args.timeout)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"polluterfind: {error}", file=sys.stderr)
        return 2

    if args.command_name == "verify":
        checked = verify(runner, order, args.victim, args.reruns)
        if args.format == "json":
            _emit(to_json(verification_dict(checked)), args.out)
        else:
            _emit(verify_markdown(checked), args.out)
        return 0 if checked.kind in (VICTIM, BRITTLE) else 1

    result = find(runner, order, args.victim, reruns=args.reruns, max_cleaners=args.cleaners)
    if args.format == "json":
        _emit(to_json(find_dict(result)), args.out)
    else:
        _emit(find_markdown(result), args.out)
    return 0 if result.confirmed else 1

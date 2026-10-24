"""Every catalog operation as a shell command.

Realizes arch.integrate.cli. Exit codes: 0 ok, 1 blocking findings, 2 usage error, 3 internal error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from arch.integrate import catalog

USAGE_ERROR = 2
INTERNAL_ERROR = 3


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arch", description="Design-as-code for humans and coding agents.")
    p.add_argument("--project", type=Path, default=Path.cwd(), help="where to start looking for design/")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="op", required=True, metavar="command")
    ops = {op.name: op for op in catalog.OPERATIONS}
    c = sub.add_parser("check", help=ops["check"].summary)
    c.add_argument("--all", action="store_true", help="also list info findings")
    x = sub.add_parser("context", help=ops["context"].summary)
    x.add_argument("target", help="component id, module, or source path (optionally path:line)")
    x.add_argument("--budget", type=int, default=4000, help="approximate size limit in tokens")
    o = sub.add_parser("outline", help=ops["outline"].summary)
    o.add_argument("root", nargs="?", help="component id to start from")
    o.add_argument("--depth", type=int, help="levels below the root to show")
    m = sub.add_parser("matrix", help=ops["matrix"].summary)
    m.add_argument("parent", nargs="?", help="component whose children to show (default: all)")
    pl = sub.add_parser("plan", help=ops["plan"].summary)
    pl.add_argument("targets", nargs="*", help="components about to change")
    assert set(sub.choices) == set(ops), "every catalog operation needs exactly one command"
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        ws = catalog.open_project(args.project)
        match args.op:
            case "check":
                result = catalog.check(ws, args.all)
            case "context":
                result = catalog.context(ws, args.target, args.budget)
            case "outline":
                result = catalog.outline(ws, args.root, args.depth)
            case "matrix":
                result = catalog.matrix(ws, args.parent)
            case "plan":
                result = catalog.plan(ws, args.targets)
    except (catalog.NoProject, *catalog.UsageError) as e:
        print(f"arch: {e}", file=sys.stderr)
        return USAGE_ERROR
    except Exception as e:  # noqa: BLE001
        print(f"arch: internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return INTERNAL_ERROR
    print(json.dumps(result.data, indent=2) if args.json else result.text)
    return result.outcome.value


if __name__ == "__main__":
    sys.exit(main())

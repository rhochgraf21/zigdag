"""Every catalog operation as a shell command.

Realizes arch.integrate.cli: the parse boundary, where text from the command line becomes domain
types. Exit codes: 0 ok, 1 blocking findings or a rejected edit, 2 usage error, 3 internal error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from arch.change import ops
from arch.integrate import agent, catalog
from arch.integrate.agent.claude import BadSettings
from arch.integrate.catalog import Command, ContextTarget, Depth, Revision, TokenBudget, Workspace
from arch.model.ids import ComponentId, CriterionLabel, NeedId, Ref, Text
from arch.model.schema import Kind, Status
from arch.view.report import EditMode, InfoFindings

USAGE_ERROR = 2
INTERNAL_ERROR = 3


def _names(value: str | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(",") if v.strip()) if value else ()


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arch", description="Design-as-code for humans and coding agents.")
    p.add_argument("--project", type=Path, default=Path.cwd(), help="where to start looking for design/")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")
    summary = {op.command: op.summary for op in catalog.OPERATIONS}

    c = sub.add_parser("check", help=summary[Command.CHECK])
    c.add_argument("--all", action="store_true", help="also list info findings")
    x = sub.add_parser("context", help=summary[Command.CONTEXT])
    x.add_argument("target", help="component id, module, or source path (optionally path:line)")
    x.add_argument("--budget", type=int, default=4000, help="approximate size limit in tokens")
    o = sub.add_parser("outline", help=summary[Command.OUTLINE])
    o.add_argument("root", nargs="?", help="component id to start from")
    o.add_argument("--depth", type=int, help="levels below the root to show")
    m = sub.add_parser("matrix", help=summary[Command.MATRIX])
    m.add_argument("parent", nargs="?", help="component whose children to show (default: all)")
    m.add_argument("--observed", action="store_true", help="overlay imports and git co-change on declared uses")
    nx = sub.add_parser("next", help=summary[Command.NEXT])
    nx.add_argument("scope", nargs="?", help="only actions within this component")
    nx.add_argument("--limit", type=int, default=10)
    pl = sub.add_parser("plan", help=summary[Command.PLAN])
    pl.add_argument("targets", nargs="*", help="components about to change")
    sub.add_parser("baseline", help=summary[Command.BASELINE])
    ag = sub.add_parser("agent", help="Install arch's skills and hooks for a coding agent")
    ag.add_argument("action", choices=["install"])
    ag.add_argument("--agent", default=agent.Product.CLAUDE_CODE.value, choices=[p.value for p in agent.Product])
    ag.add_argument("--command", default="arch", help="how hooks should invoke arch, e.g. 'uv run arch'")
    ag.add_argument("--dry-run", action="store_true", help="list the files that would be written")
    hk = sub.add_parser("hook", help="Handle an agent hook event (reads the hook payload on stdin)")
    hk.add_argument("event", choices=[e.value for e in agent.HookEvent])
    i = sub.add_parser("init", help=summary[Command.INIT])
    i.add_argument("--dry-run", action="store_true", help="show what would be drafted, write nothing")
    d = sub.add_parser("diff", help=summary[Command.DIFF])
    d.add_argument("base", nargs="?", default="HEAD", help="git revision to compare with (default HEAD)")

    dry = argparse.ArgumentParser(add_help=False)
    dry.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                     help="show what would change, write nothing")

    def editing(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[dry])

    add = editing("add", "Add a component, need, acceptance criterion or decision")
    kinds = add.add_subparsers(dest="what", required=True, metavar="what")
    ac = kinds.add_parser("component", parents=[dry])
    ac.add_argument("id")
    ac.add_argument("--realizes", required=True, help="the functional requirement")
    ac.add_argument("--solution", required=True, help="the design parameter")
    ac.add_argument("--hides", help="the decision it encapsulates")
    ac.add_argument("--status", default="specified", choices=[s.value for s in Status])
    ac.add_argument("--uses", help="comma-separated references")
    ac.add_argument("--exports", help="comma-separated child names")
    ac.add_argument("--serves", help="comma-separated need ids")
    ac.add_argument("--criterion", action="append", default=[], help="an acceptance criterion (repeatable)")
    an = kinds.add_parser("need", parents=[dry])
    an.add_argument("id")
    an.add_argument("--statement", required=True)
    an.add_argument("--stakeholder")
    an.add_argument("--signal")
    acr = kinds.add_parser("criterion", parents=[dry])
    acr.add_argument("component")
    acr.add_argument("text")
    ad = kinds.add_parser("decision", parents=[dry])
    ad.add_argument("component")
    for flag in ("--title", "--chose", "--because"):
        ad.add_argument(flag, required=True)
    for flag in ("--over", "--consequences", "--previously", "--backed-by"):
        ad.add_argument(flag)

    s = editing("set", "Set (or --clear) a field of a component or need")
    s.add_argument("node")
    s.add_argument("field", choices=[f.key for f in ops.Settable])
    s.add_argument("value", nargs="?")
    s.add_argument("--clear", action="store_true")
    for name, help_text in (("link", "Add a reference to uses, exports or serves"), ("unlink", "Remove such a reference")):
        lk = editing(name, help_text)
        lk.add_argument("component")
        lk.add_argument("relation", choices=[r.value for r in ops.Relation])
        lk.add_argument("target")
    mv = editing("move", "Rename or re-parent a component, rewriting references")
    mv.add_argument("component")
    mv.add_argument("to")
    rm = editing("remove", "Remove a component, need or acceptance criterion")
    rkinds = rm.add_subparsers(dest="what", required=True, metavar="what")
    for kind in ("component", "need"):
        r = rkinds.add_parser(kind, parents=[dry])
        r.add_argument("id")
        r.add_argument("--cascade", action="store_true", help="also remove references to it (and its subtree)")
    rc = rkinds.add_parser("criterion", parents=[dry])
    rc.add_argument("component")
    rc.add_argument("label", help="e.g. AC3")
    ap = editing("apply", "Apply a batch of operations given as JSON (a list, or one object)")
    ap.add_argument("file", nargs="?", default="-", help="JSON file, or - for stdin (default)")
    return p


def _operations(args: argparse.Namespace, ws: Workspace) -> list[ops.Operation]:
    """Turn an editing command into design operations (the parse boundary)."""
    match args.cmd, getattr(args, "what", None):
        case "add", "component":
            return [ops.AddComponent(
                ComponentId(args.id), Text(args.realizes), Text(args.solution),
                Text(args.hides) if args.hides else None, Status(args.status),
                tuple(Ref(r) for r in _names(args.uses)), tuple(Ref(r) for r in _names(args.exports)),
                tuple(NeedId(n) for n in _names(args.serves)), tuple(Text(c) for c in args.criterion))]
        case "add", "need":
            return [ops.AddNeed(NeedId(args.id), Text(args.statement),
                                Text(args.stakeholder) if args.stakeholder else None, Text(args.signal) if args.signal else None)]
        case "add", "criterion":
            return [ops.AddCriterion(ComponentId(args.component), Text(args.text))]
        case "add", "decision":
            optional = {k: Text(v) for k in ("over", "consequences", "previously", "backed_by") if (v := getattr(args, k))}
            return [ops.AddDecision(ComponentId(args.component), Text(args.title), Text(args.chose), Text(args.because), **optional)]
        case "set", _:
            if args.clear == (args.value is not None):
                raise ops.Rejected("give a value, or --clear")
            return [ops.SetField(Text(args.node), ops.Settable.named(args.field), None if args.clear else Text(args.value))]
        case ("link" | "unlink") as verb, _:
            cls = ops.Link if verb == "link" else ops.Unlink
            return [cls(ComponentId(args.component), ops.Relation(args.relation), Ref(args.target))]
        case "move", _:
            return [ops.Move(ComponentId(args.component), ComponentId(args.to))]
        case "remove", "criterion":
            return [ops.RemoveCriterion(ComponentId(args.component), CriterionLabel(args.label))]
        case "remove", kind:
            mode = ops.Removal.CASCADE if args.cascade else ops.Removal.REFUSE_IF_USED
            return [ops.Remove(Text(args.id), Kind(kind), mode)]
        case "apply", _:
            text = sys.stdin.read() if args.file == "-" else ws.read_input(Path(args.file))
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as e:
                raise ops.Rejected(f"not valid JSON: {e}") from None
            items = raw if isinstance(raw, list) else [raw]
            if not all(isinstance(i, dict) for i in items):
                raise ops.Rejected("expected a JSON object or a list of objects")
            return [ops.from_json(i) for i in items]
    raise ops.Rejected(f"unknown editing command {args.cmd}")


EDITING = frozenset({"add", "set", "link", "unlink", "move", "remove", "apply"})


def _run(args: argparse.Namespace, ws: Workspace) -> catalog.Result:
    if args.cmd in EDITING:
        mode = EditMode.DRY_RUN if getattr(args, "dry_run", False) else EditMode.WRITE
        return catalog.edit(ws, _operations(args, ws), mode)
    runners: dict[str, Callable[[], catalog.Result]] = {
        "check": lambda: catalog.check(ws, InfoFindings.LISTED if args.all else InfoFindings.COUNTED),
        "context": lambda: catalog.context(ws, ContextTarget(args.target), TokenBudget(args.budget)),
        "outline": lambda: catalog.outline(ws, ComponentId(args.root) if args.root else None,
                                           Depth(args.depth) if args.depth is not None else None),
        "matrix": lambda: catalog.matrix(ws, ComponentId(args.parent) if args.parent else None,
                                         catalog.MatrixOverlay.OBSERVED if args.observed else catalog.MatrixOverlay.DECLARED_ONLY),
        "plan": lambda: catalog.plan(ws, [ComponentId(t) for t in args.targets]),
        "next": lambda: catalog.next_(ws, ComponentId(args.scope) if args.scope else None, catalog.ActionLimit(args.limit)),
        "diff": lambda: catalog.diff(ws, Revision(args.base)),
        "baseline": lambda: catalog.baseline(ws),
    }
    return runners[args.cmd]()


def _hook(args: argparse.Namespace) -> int:
    """Hooks must never break the agent: outside an arch project, or on any failure, stay quiet."""
    event = agent.HookEvent(args.event)
    try:
        ws = catalog.open_project(args.project)
    except catalog.NoProject:
        return 0
    payload = sys.stdin.read() if event is agent.HookEvent.POST_EDIT else ""
    try:
        response = agent.handle(event, ws, payload)
    except Exception as e:  # noqa: BLE001
        print(f"arch hook {event.value} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0
    if response.stdout:
        print(response.stdout)
    if response.stderr:
        print(response.stderr, file=sys.stderr)
    return response.exit.value


def _install(args: argparse.Namespace) -> int:
    try:
        ws = catalog.open_project(args.project)
        plan = agent.installation(ws, agent.Product(args.agent), args.command)
    except (*catalog.NoProject, BadSettings) as e:
        print(f"arch: {e}", file=sys.stderr)
        return USAGE_ERROR
    print(json.dumps(plan.to_json(), indent=2) if args.json else
          plan.to_markdown() + (" (dry run: nothing written)" if args.dry_run and plan.edits else ""))
    if not args.dry_run:
        ws.write_project(plan.edits)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "hook":
        return _hook(args)
    if args.cmd == "agent":
        return _install(args)
    try:
        if args.cmd == "init":
            mode = EditMode.DRY_RUN if args.dry_run else EditMode.WRITE
            result = catalog.init(catalog.new_project(args.project), mode)
        else:
            result = _run(args, catalog.open_project(args.project))
    except (*catalog.NoProject, *catalog.UsageError, ops.Rejected) as e:
        print(f"arch: {e}", file=sys.stderr)
        return USAGE_ERROR
    except Exception as e:  # noqa: BLE001
        print(f"arch: internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return INTERNAL_ERROR
    print(json.dumps(result.view.to_json(), indent=2) if args.json else result.view.to_markdown())
    return result.outcome.value


if __name__ == "__main__":
    sys.exit(main())

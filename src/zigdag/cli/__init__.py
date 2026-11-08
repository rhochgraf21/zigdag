"""The shell: the command line. It reads the project, runs the pure core, and writes or prints what it found."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zigdag.agents.claude import POST_EDIT, PRODUCT, SESSION_START
from zigdag.cli import commands as c
from zigdag.cli.files import code_model, from_disk, project_files
from zigdag.core import log as lg
from zigdag.core.checks.run import ProjectFiles
from zigdag.core.code import CodeModel

PROGRAM = "zigdag"
TEST = "test"


def read_project(root: Path) -> ProjectFiles:
    """The project's record, settings and log, as zigdag reads them."""
    return project_files(from_disk(root))


def read_code(root: Path) -> CodeModel | None:
    """The project's code model, or None when there is no code to read."""
    return code_model(from_disk(root))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROGRAM, description="Zigzag from needs to code, and keep it a DAG.")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="the project's root (default: here)")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check the record and the code")
    check.add_argument("--json", action="store_true", help="print the findings as JSON")
    check.add_argument("--base", help="also check the workflow gates for what changed since this git revision")
    commands.add_parser("test", help="run the tests while watching what the code does, then check it all; other "
                        "arguments go to the test command")
    fmt = commands.add_parser("fmt", help="give every design file its canonical layout")
    fmt.add_argument("--check", action="store_true", help="change nothing; fail if a file is not formatted")

    raise_ = commands.add_parser("raise", help="raise a defect, question or idea in the log")
    raise_.add_argument("kind", choices=[k.value for k in lg.Kind])
    raise_.add_argument("on", help="what it is about: an FR, statement, job, outcome, rule or entry")
    raise_.add_argument("say", help="what you noticed")
    raise_.add_argument("--by", required=True, help="who is raising it: a person or an agent")
    raise_.add_argument("--evidence", help="the exact words or code it is about")
    answer = commands.add_parser("answer", help="answer an open thread, or a question a check asked")
    answer.add_argument("ref", help="the thread id or question digest, as zigdag findings shows it")
    answer.add_argument("answer", choices=[a.value for a in lg.Answer])
    answer.add_argument("say", help="the reason")
    answer.add_argument("--by", required=True, help="who is answering")
    answer.add_argument("--countermeasure", help="the rule, statement or FR that will catch this next time")
    commands.add_parser("findings", help="list open threads and open questions, newest first")

    show = commands.add_parser("show", help="one level of the zigzag: an FR, its children and the design matrix")
    show.add_argument("name", nargs="?", help="the FR (default: the root)")
    show.add_argument("--data", action="store_true", help="the data model under the FR, and who touches which data")
    context = commands.add_parser("context", help="what an agent needs before changing some code")
    context.add_argument("target", help="a source file, or an FR")
    commands.add_parser("next", help="what is to do, in the order the design matrix allows building it")

    init = commands.add_parser("init", help="record existing code as it is, so the first check holds")
    init.add_argument("--force", action="store_true", help="replace an existing functional.yaml and process.yaml")
    review = commands.add_parser("review", help="what a change does to the record, and what it broke")
    review.add_argument("base", help="the git revision to compare with, such as main")
    approve = commands.add_parser("approve", help="approve entries at their current content")
    approve.add_argument("names", nargs="*", help="the entries (default: those changed since --base)")
    approve.add_argument("--base", help="approve every entry changed since this git revision")
    approve.add_argument("--by", required=True, help="who approves: a person listed in [settings] people, or an agent")
    critique = commands.add_parser("critique", help="ask a fresh critic about entries, or record its answer")
    asking = critique.add_mutually_exclusive_group(required=True)
    asking.add_argument("--request", action="store_true", help="write the request for a critic")
    asking.add_argument("--record", type=Path, help="record the critic's answer from this file")
    critique.add_argument("names", nargs="*", help="the entries (default: those changed since --base)")
    critique.add_argument("--base", help="ask about every entry changed since this git revision")
    critique.add_argument("--by", help="who critiqued, when recording")
    rename = commands.add_parser("rename", help="rename an FR and everything below it, everywhere it is used")
    rename.add_argument("old")
    rename.add_argument("new")

    agent = commands.add_parser("agent", help="set up a coding agent to work with zigdag")
    agent.add_argument("action", choices=["install"])
    agent.add_argument("product", choices=[PRODUCT])
    agent.add_argument("--command", dest="hook_command", default=PROGRAM, help="how the agent's hooks run zigdag")
    hook = commands.add_parser("hook", help="what an agent's hooks call")
    hook.add_argument("event", choices=[SESSION_START, POST_EDIT])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args, passed_on = parser.parse_known_args(argv)
    if passed_on and args.command != TEST:
        parser.error(f"unrecognized arguments: {' '.join(passed_on)}")
    project = c.Project(args.project.resolve())
    match args.command:
        case "check":
            return c.check(project, args.json, args.base)
        case "test":
            return c.test(project, passed_on)
        case "fmt":
            return c.fmt(project, args.check)
        case "raise":
            return c.raise_(project, args.kind, args.on, args.say, args.by, args.evidence)
        case "answer":
            return c.answer(project, args.ref, args.answer, args.say, args.by, args.countermeasure)
        case "findings":
            return c.findings(project)
        case "show" if args.data:
            return c.view(project, c.DATA_VIEW, args.name)
        case "show" | "context" | "next":
            return c.view(project, args.command, getattr(args, "name", None) or getattr(args, "target", None))
        case "init":
            return c.init_project(project, args.force)
        case "review":
            return c.review(project, args.base)
        case "approve":
            return c.approve(project, args.names, args.base, args.by)
        case "critique" if args.request:
            return c.critique_request(project, args.names, args.base)
        case "critique":
            return c.critique_record(project, args.record, args.by) if args.by else c.refuse("--record needs --by")
        case "rename":
            return c.rename_fr(project, args.old, args.new)
        case "agent":
            return c.agent_install(project, args.product, args.hook_command)
        case "hook":
            return c.hook(project, args.event, sys.stdin.read() if args.event == POST_EDIT else "")
    return c.refuse(f"unknown command {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())

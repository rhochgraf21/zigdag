"""The shell: the command line. It reads the project, has the pure core and plans.py decide, and carries out what they
decided: writes, prints and exits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zigdag.agents.claude import PRODUCT, SESSION_START, TURN_END
from zigdag.cli import commands as c
from zigdag.cli import plans
from zigdag.cli.files import from_disk
from zigdag.core import log as lg
from zigdag.core.checks.run import ProjectFiles
from zigdag.core.code import CodeModel

PROGRAM = "zigdag"


def read_project(root: Path) -> ProjectFiles:
    """The project's record, settings and log, as zigdag reads them."""
    return plans.project_files(from_disk(root))


def read_code(root: Path) -> CodeModel | None:
    """The project's code model, or None when there is no code to read."""
    return plans.code_model(from_disk(root))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROGRAM, description="Zigzag from needs to code, and keep it a DAG.")
    parser.add_argument("--project", type=Path, help="the project's root (default: here)")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check the record and the code")
    check.add_argument("--json", action="store_true", help="print the findings as JSON")
    check.add_argument("--full", action="store_true", help="print every finding, not one line for each direction")
    check.add_argument("--base", help="also check the workflow gates for what changed since this git revision")
    commands.add_parser("test", help="run the tests while watching what the code does, then check it all; other "
                        "arguments go to the test command")
    ready = commands.add_parser("ready", help="one answer for a whole change: run the tests while watching, check "
                                "everything, and say yes or no; other arguments go to the test command")
    ready.add_argument("--base", help="also hold the change to the workflow gates, and to adding nothing to do, "
                       "since this git revision")
    commands.add_parser("profile", help="run the tests under the profiler, and show where the time and memory went "
                        "beside the run before; other arguments go to the test command")
    commands.add_parser("stats", help="where the latest profiled run's time and memory went, by design part")
    commands.add_parser("checks", help="every rule there is: what each holds the code to, its settings, and whether "
                        "failing it is a break or a question")
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
    context.add_argument("--base", help="also show what changed since this git revision that concerns it, and what "
                         "that change asks of it")
    work = commands.add_parser("work", help="what to do next on a change that is built part by part: build a part, "
                               "land one, wait, or what blocks it")
    work.add_argument("--base", required=True, help="the git revision the change began at, before its design changed")
    commands.add_parser("next", help="what is to do, in the order the design matrix allows building it")

    init = commands.add_parser("init", help="record existing code as it is, so the first check holds")
    init.add_argument("--force", action="store_true", help="replace an existing functional.yaml and process.yaml")
    init.add_argument("--default", action="store_true", help="a default setup: zigdag.toml, a starter record, and "
                      "every rule you can tune written out with its default values; works with no code yet")
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
    hook.add_argument("event", choices=[SESSION_START, TURN_END])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args, passed_on = parser.parse_known_args(argv)
    route = plans.route(args, passed_on, Path.cwd())
    if route.rejected:
        parser.error(route.rejection)
    project = c.Project(route.root)
    a = route.args
    match route.command:
        case plans.Command.CHECK:
            return c.check(project, a.base)
        case plans.Command.CHECK_JSON:
            return c.check_json(project, a.base)
        case plans.Command.CHECK_FULL:
            return c.check_full(project, a.base)
        case plans.Command.TEST:
            return c.test(project, list(route.passed_on))
        case plans.Command.READY:
            return c.ready(project, a.base, list(route.passed_on))
        case plans.Command.WORK:
            return c.work(project, a.base)
        case plans.Command.CHECKS:
            return c.checks(project)
        case plans.Command.PROFILE:
            return c.profile(project, list(route.passed_on))
        case plans.Command.STATS:
            return c.stats(project)
        case plans.Command.FMT:
            return c.fmt(project)
        case plans.Command.FMT_CHECK:
            return c.fmt_check(project)
        case plans.Command.RAISE:
            return c.raise_(project, lg.Kind(a.kind), a.on, a.say, a.by, a.evidence)
        case plans.Command.ANSWER:
            return c.answer(project, a.ref, lg.Answer(a.answer), a.say, a.by, a.countermeasure)
        case plans.Command.FINDINGS:
            return c.findings(project)
        case plans.Command.VIEW:
            return c.view(project, route.view, route.target, route.base)
        case plans.Command.INIT:
            return c.init_project(project)
        case plans.Command.INIT_FORCED:
            return c.init_forced(project)
        case plans.Command.INIT_DEFAULT:
            return c.init_default(project)
        case plans.Command.REVIEW:
            return c.review(project, a.base)
        case plans.Command.APPROVE:
            return c.approve(project, a.names, a.base, a.by)
        case plans.Command.CRITIQUE_REQUEST:
            return c.critique_request(project, a.names, a.base)
        case plans.Command.CRITIQUE_RECORD:
            return c.critique_record(project, a.record, a.by)
        case plans.Command.RENAME:
            return c.rename_fr(project, a.old, a.new)
        case plans.Command.AGENT:
            return c.agent_install(project, a.product, a.hook_command)
        case plans.Command.HOOK_TURN:
            return c.turn_hook(project)
        case plans.Command.HOOK_SESSION:
            return c.session_hook(project)
    return c.perform(project, route.refusal)


if __name__ == "__main__":
    sys.exit(main())

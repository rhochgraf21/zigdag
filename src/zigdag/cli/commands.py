"""The commands: each reads what it needs of the project, has plans.py decide what to do with it, and carries that
out with perform. Nothing here decides anything (DESIGN2 §4.1, planned-effects).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path

from zigdag.adapters.adapter import Adapter, Presence
from zigdag.agents import claude
from zigdag.cli import plans
from zigdag.cli.files import checkout, claims, from_disk, from_git, loaded, made, ran, text
from zigdag.cli.plans import Files, GitError, Outcome, WatchedRun
from zigdag.core import log as lg
from zigdag.core.checks.run import Analysis
from zigdag.core.settings import PLAN_FILE, PROFILE_BEFORE, PROFILE_FILE
from zigdag.core.findings import RecordPath
from zigdag.core.names import Revision

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now() -> lg.Timestamp:
    return lg.Timestamp(datetime.now(timezone.utc).strftime(TIME_FORMAT))


@dataclass
class Project:
    """A project on disk: reading it, analysing it, and writing to it."""

    root: Path
    written: list[RecordPath] = field(default_factory=list)  # every file this run wrote, in order

    @cached_property
    def files(self) -> Files:
        return from_disk(self.root)

    @property
    def adapters(self) -> tuple[Adapter, ...]:
        return plans.reading_of(self.files).adapters

    @cached_property
    def analysis(self) -> Analysis:
        return plans.analysis(self.files, ran(self.root, plans.tool_runs(self.files)),
                              loaded(plans.loadings(self.files)))

    def at(self, revision: str) -> Analysis:
        """The analysis of the project as it was at a git revision."""
        files = from_git(self.root, revision)
        return plans.analysis(files, loaded=loaded(plans.loadings(files)))

    def committed(self) -> Analysis:
        """The analysis of the project as its last commit has it, with the log as it is on disk."""
        files = plans.with_log(from_git(self.root, plans.HEAD), self.read(lg.LOG_FILE))
        return plans.analysis(files, loaded=loaded(plans.loadings(files)))

    def read(self, path: RecordPath) -> str | None:
        return text(plans.at_root(self.root, path))

    def write(self, path: RecordPath, contents: str) -> None:
        full = plans.at_root(self.root, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(contents, encoding="utf-8")
        self.written.append(path)

    def append(self, line: str) -> None:
        """Add one event to the log, and make git merge the log as a union so branches never conflict."""
        for w in plans.appended(self.read(lg.LOG_FILE), self.read(plans.GIT_ATTRIBUTES), line):
            self.write(w.path, w.text)


def perform(project: Project, outcome: Outcome) -> int:
    """Carry out what a command decided: write its files, add its log events, print what it says, and exit."""
    for w in outcome.writes:
        project.write(w.path, w.text)
    for event in outcome.log:
        project.append(event)
    for said in outcome.out:
        print(said)
    for said in outcome.err:
        print(said, file=sys.stderr)
    return outcome.exit


def _earlier(project: Project, base: Revision | None) -> tuple[Analysis, ...]:
    """The analysis at the base, when there is one; raises GitError when it cannot be read."""
    return tuple(project.at(revision) for revision in plans.revisions(base))


def check(project: Project, base: Revision | None) -> int:
    try:
        earlier = _earlier(project, base)
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    return perform(project, plans.check(project.analysis, earlier, base))


def check_json(project: Project, base: Revision | None) -> int:
    try:
        earlier = _earlier(project, base)
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    return perform(project, plans.check_json(project.analysis, earlier, base))


def check_full(project: Project, base: Revision | None) -> int:
    try:
        earlier = _earlier(project, base)
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    return perform(project, plans.check_full(project.analysis, earlier, base))


def profile(project: Project, extra: list[str]) -> int:
    """Run the project's tests under the profiler, keeping the run before's profile to compare with."""
    run = plans.profile(project.analysis, project.adapters, project.root, extra)
    if run.refused:
        return perform(project, run.refusal)
    perform(project, run.starting)
    run.profile.parent.mkdir(parents=True, exist_ok=True)
    # The latest profile becomes the one to compare with. When there is none, because the run before failed, the one
    # kept before it stays: a failed run must not cost the comparison.
    with contextlib.suppress(FileNotFoundError):
        run.profile.replace(run.before)
    ran_ = subprocess.run(run.command, cwd=run.root)
    return perform(project, plans.profiled_run(run, Presence(run.profile.is_file()), plans.ExitCode(ran_.returncode),
                                               project.analysis, project.adapters, text(run.profile),
                                               text(run.before)))


def stats(project: Project) -> int:
    return perform(project, plans.costs(project.analysis, project.adapters, project.root,
                                        project.read(PROFILE_FILE), project.read(PROFILE_BEFORE)))


def _watched(project: Project, run: WatchedRun) -> plans.ExitCode:
    """Run the tests, the watched ones with the watcher, having cleared what the run before saw so that only this
    run's is read; then the tests of the adapters that have no watcher."""
    project.write(PLAN_FILE, run.watch)
    for written_before in (run.observed, *run.cleared):
        written_before.unlink(missing_ok=True)
    return plans.exited([plans.ExitCode(subprocess.run(command, cwd=run.root, env=run.environment).returncode)
                         for command in run.commands])


def test(project: Project, extra: list[str]) -> int:
    """Run the project's tests with the watcher, then check everything with what it saw."""
    run = plans.test(project.analysis, project.files, project.root, extra, dict(os.environ))  # read here, not there
    if run.refused:
        return perform(project, run.refusal)
    ran = _watched(project, run)
    return perform(project, plans.tested(run, Presence(run.observed.is_file()), ran,
                                         Project(run.root).analysis))


def ready(project: Project, base: Revision | None, extra: list[str]) -> int:
    """Run the tests with the watcher, then give one answer for the whole change. On the branch of a part, the
    change is the part's: what the branch left its line with is read too, to see what the branch itself changed."""
    on = plans.on_part(checkout(project.root), base)
    if on.refused:
        return perform(project, on.refusal)
    try:
        earlier = _earlier(project, base)
        started = tuple(project.at(revision) for revision in on.starts)
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    run = plans.test(project.analysis, project.files, project.root, extra, dict(os.environ))
    if run.refused:
        return perform(project, run.refusal)
    ran = _watched(project, run)
    after = Project(run.root)
    return perform(project, plans.ready(run, Presence(run.observed.is_file()), ran, after.analysis,
                                        earlier, base, after.files, on.branch, started))


def fmt(project: Project) -> int:
    return perform(project, plans.fmt(project.files))


def fmt_check(project: Project) -> int:
    return perform(project, plans.fmt_check(project.files))


def raise_(project: Project, kind: str, on: str, say: str, by: str, evidence: str | None) -> int:
    return perform(project, plans.raise_(project.analysis, now(), kind, on, say, by, evidence))


def answer(project: Project, ref: str, answer_: str, say: str, by: str, countermeasure: str | None) -> int:
    return perform(project, plans.answer(project.analysis, now(), ref, answer_, say, by, countermeasure))


def findings(project: Project) -> int:
    return perform(project, plans.findings(project.analysis))


def view(project: Project, name: str, target: str | None, base: Revision | None) -> int:
    try:
        earlier = _earlier(project, base)
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    return perform(project, plans.view(project.analysis, name, target, earlier, base))


def work(project: Project, base: Revision) -> int:
    """Say what to do next on a change that is built part by part, and take the part that is handed out."""
    taken = claims(project.root)
    try:
        before, line = project.at(base), project.committed()
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    folders = tuple(Project(folder).analysis for folder in taken.folders)
    handout = plans.work(base, before, line, checkout(project.root), taken, folders)
    return perform(project, plans.handed_out(handout, made(project.root, handout.claims)))


def init_project(project: Project) -> int:
    return perform(project, plans.init(project.files))


def init_forced(project: Project) -> int:
    return perform(project, plans.init_forced(project.files))


def checks(project: Project) -> int:
    return perform(project, plans.checks(project.analysis))


def init_default(project: Project) -> int:
    return perform(project, plans.init_default(project.files, project.root.resolve().name))


def review(project: Project, base: str) -> int:
    try:
        before = project.at(base)
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    return perform(project, plans.review(base, before, project.analysis))


def approve(project: Project, names: list[str], base: str | None, by: str) -> int:
    try:
        earlier = tuple(project.at(revision) for revision in plans.revisions_to_choose(names, base))
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    return perform(project, plans.approve(project.analysis, earlier, names, base, by, now()))


def critique_request(project: Project, names: list[str], base: str | None) -> int:
    try:
        earlier = tuple(project.at(revision) for revision in plans.revisions_to_choose(names, base))
    except GitError as e:
        return perform(project, plans.unreadable(base, e))
    return perform(project, plans.critique_request(project.analysis, earlier, names, base))


def critique_record(project: Project, answer_path: Path, by: str) -> int:
    return perform(project, plans.critique_record(project.analysis, text(answer_path), answer_path, by, now()))


def rename_fr(project: Project, old: str, new: str) -> int:
    return perform(project, plans.rename_fr(project.analysis, project.files, old, new))


def agent_install(project: Project, product: str, command: str) -> int:
    return perform(project, plans.agent_install(product, command, project.read(RecordPath(claude.SETTINGS))))


def session_hook(project: Project) -> int:
    return perform(project, plans.hook(project.analysis, claude.SESSION_START, ""))


def turn_hook(project: Project) -> int:
    """Whether the agent was already told arrives on standard input."""
    return perform(project, plans.hook(project.analysis, claude.TURN_END, sys.stdin.read()))

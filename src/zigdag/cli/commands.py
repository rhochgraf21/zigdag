"""The commands: each reads the project through Project, asks the core, and writes or prints what it found."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path

from zigdag.agents import claude
from zigdag.cli.files import GitError, code_model, from_disk, from_git, project_files, source_roots, test_files
from zigdag.core import log as lg
from zigdag.core import views
from zigdag.core.checks.gates import check_gates
from zigdag.core.checks.run import Analysis, analyse
from zigdag.core.critique import read_answer, request
from zigdag.core.findings import Finding, RecordPath, Report, Result
from zigdag.core.init import init, settings_text
from zigdag.core.names import FrName, fr_name
from zigdag.core.record.entries import Entry
from zigdag.core.record.fmt import format_text
from zigdag.core.record.model import Domain
from zigdag.core.record.read import domain_file
from zigdag.core.rename import keep_code, rename, renamed
from zigdag.core.review import Change, ChangeKind, diff, new_findings, render
from zigdag.core.rubric import RUBRIC_VERSION
from zigdag.core.settings import (
    DEFAULT_REPORT,
    DEFAULT_TEST_COMMAND,
    OBSERVED_FILE,
    PLAN_FILE,
    SETTINGS_FILE,
    WORK_DIR,
)
from zigdag.core.watch import PLAN_VARIABLE, plan

OK, FOUND, REFUSED = 0, 1, 2  # exit codes: nothing wrong; something breaks or would change; the command refused

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
GIT_ATTRIBUTES = RecordPath(".gitattributes")
UNION_MERGE = f"{lg.LOG_FILE} merge=union"
CRITIQUE_REQUEST = RecordPath(f"{WORK_DIR}/critique/request.json")
HOOK_FINDINGS = 15  # at most this many findings in what a hook tells an agent
WATCHER = "zigdag.watchers.python"  # the pytest plugin that watches the tests run
PLUGIN_OPTION, REPORT_OPTION = "-p", "--junitxml"
SHOW, CONTEXT, NEXT, DATA_VIEW = "show", "context", "next", "data"

_HEADINGS = ((Result.BREAKS, "breaks"), (Result.QUESTION, "questions"), (Result.TODO, "to do"))
_COUNTED = {Result.BREAKS: ("break", "breaks"), Result.QUESTION: ("question", "questions"),
            Result.TODO: ("thing to do", "things to do")}


def now() -> lg.Timestamp:
    return lg.Timestamp(datetime.now(timezone.utc).strftime(TIME_FORMAT))


def refuse(say: str) -> int:
    print(f"zigdag: {say}", file=sys.stderr)
    return REFUSED


@dataclass
class Project:
    """A project on disk: reading it, analysing it, and writing to it."""

    root: Path
    written: list[RecordPath] = field(default_factory=list)  # every file this run wrote, in order

    @cached_property
    def files(self) -> dict[RecordPath, str]:
        return from_disk(self.root)

    @cached_property
    def analysis(self) -> Analysis:
        return analyse(project_files(self.files), code_model(self.files))

    def at(self, revision: str) -> Analysis:
        """The analysis of the project as it was at a git revision."""
        files = from_git(self.root, revision)
        return analyse(project_files(files), code_model(files))

    def read(self, path: RecordPath) -> str | None:
        full = self.root / path
        return full.read_text(encoding="utf-8") if full.is_file() else None

    def write(self, path: RecordPath, text: str) -> None:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        self.written.append(path)

    def append(self, line: str) -> None:
        """Add one event to the log, and make git merge the log as a union so branches never conflict."""
        self.write(lg.LOG_FILE, (self.read(lg.LOG_FILE) or "") + line + "\n")
        attributes = self.read(GIT_ATTRIBUTES) or ""
        if UNION_MERGE not in attributes.splitlines():
            self.write(GIT_ATTRIBUTES, attributes + ("" if not attributes or attributes.endswith("\n") else "\n")
                       + UNION_MERGE + "\n")


# ---- reports -----------------------------------------------------------------------------------------------------

def _line(f: Finding) -> str:
    handle = f"  [{f.digest}]" if f.result is Result.QUESTION else ""
    return f"  {f.span or '-'}  {f.rule}  {f.about}: {f.say}{handle}"


def render_report(report: Report) -> str:
    lines = []
    for result, heading in _HEADINGS:
        found = report.of_result(result)
        if found:
            lines += [heading, *map(_line, found), ""]
    counts = []
    for result, _ in _HEADINGS:
        n = len(report.of_result(result))
        one, many = _COUNTED[result]
        counts.append(f"{n} {one if n == 1 else many}")
    return "\n".join([*lines, ", ".join(counts)])


def report_json(report: Report) -> str:
    return json.dumps([
        {"result": f.result.value, "rule": f.rule, "about": f.about, "say": f.say, "digest": f.digest,
         "span": None if f.span is None else {"path": f.span.path, "line": f.span.line, "column": f.span.column}}
        for f in report.findings
    ], indent=2)


# ---- changes against a base --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Changeset:
    """What a project's record and findings look like now, compared with a git revision."""

    base: str
    before: Analysis
    after: Analysis
    changes: tuple[Change, ...]

    @staticmethod
    def of(project: Project, base: str) -> Changeset:
        before, after = project.at(base), project.analysis
        return Changeset(base, before, after, tuple(diff(before.record, after.record, before.sentences,
                                                         after.sentences)))

    @property
    def changed(self) -> list[Entry]:
        return [c.entry for c in self.changes if c.kind is not ChangeKind.REMOVED]

    @property
    def gates(self) -> list[Finding]:
        a = self.after
        return list(check_gates(a.record, a.log, a.people, self.changed, a.report.breaks))

    @property
    def brought(self) -> list[Finding]:
        return new_findings(self.before.report, self.after.report)


def _changeset(project: Project, base: str) -> Changeset | None:
    try:
        return Changeset.of(project, base)
    except GitError as e:
        refuse(f"cannot read {base}: {e}")
        return None


# ---- commands ----------------------------------------------------------------------------------------------------

def check(project: Project, as_json: bool, base: str | None) -> int:
    report = project.analysis.report
    gates: list[Finding] = []
    if base is not None:
        changes = _changeset(project, base)
        if changes is None:
            return REFUSED
        gates = changes.gates
        report = Report.of([*report.findings, *gates])
    print(report_json(report) if as_json else render_report(report))
    open_threads = sum(1 for t in project.analysis.log.threads if t.open)
    if open_threads and not as_json:
        print(f"{open_threads} open threads in the log: zigdag findings")
    return FOUND if report.breaks else OK


def test(project: Project, extra: list[str]) -> int:
    """Run the project's tests with the watcher, then check everything with what it saw."""
    watch = plan(project.analysis, test_files(project.files))
    if watch is None:
        return refuse("no code was read, so there is nothing to watch")
    project.write(PLAN_FILE, watch.to_text())
    seen = project.root / OBSERVED_FILE
    seen.unlink(missing_ok=True)
    command = [*shlex.split(project.analysis.settings.test_command or DEFAULT_TEST_COMMAND),
               PLUGIN_OPTION, WATCHER, f"{REPORT_OPTION}={DEFAULT_REPORT}", *extra]
    ran = subprocess.run(command, cwd=project.root, env={**os.environ, PLAN_VARIABLE: str(project.root / PLAN_FILE)})
    if not seen.is_file():
        return refuse(f"the tests ran ({shlex.join(command)} exited {ran.returncode}), but the watcher saw nothing: "
                      f"the tests' Python must be able to import zigdag")
    report = Project(project.root).analysis.report
    print(render_report(report))
    print(f"tests: {shlex.join(command)} exited {ran.returncode}")
    return FOUND if report.breaks or ran.returncode else OK


def fmt(project: Project, only_check: bool) -> int:
    """Rewrite each design file in its canonical layout; with only_check, list the ones that would change."""
    changed, unreadable = [], []
    for path, text in project_files(project.files).design.items():
        formatted, problems = format_text(path, text)
        if formatted is None:
            unreadable.append(path)
            print("\n".join(_line(p) for p in problems))
        elif formatted != text:
            changed.append(path)
            if not only_check:
                project.write(path, formatted)
    verb = "would reformat" if only_check else "reformatted"
    print("\n".join([*(f"{verb} {p}" for p in changed), f"{len(changed)} {verb}, {len(unreadable)} could not be read"]))
    return FOUND if unreadable or (only_check and changed) else OK


def raise_(project: Project, kind: str, on: str, say: str, by: str, evidence: str | None) -> int:
    a = project.analysis
    if on not in a.known_names:
        return refuse(f'nothing in the record is named "{on}"')
    line = lg.raised(now(), lg.Actor(by), lg.Kind(kind), on, say, evidence)
    thread = lg.thread_id(json.loads(line)["at"], lg.Actor(by), on, say)
    if a.log.thread(thread) is not None:
        return refuse("that was already raised")
    project.append(line)
    print(f"raised {thread}")
    return OK


def answer(project: Project, ref: str, answer_: str, say: str, by: str, countermeasure: str | None) -> int:
    a = project.analysis
    if countermeasure is not None and countermeasure not in a.known_names:
        return refuse(f'the countermeasure names nothing in the record: "{countermeasure}"')
    choice = lg.Answer(answer_)
    thread = a.log.thread(lg.ThreadId(ref))
    if thread is not None:
        if not thread.open:
            return refuse(f"thread {ref} is already answered; raise it again if it is back")
        project.append(lg.answered_thread(now(), lg.Actor(by), thread.raised.id, choice, say, countermeasure))
        print(f"answered thread {ref}")
        return OK
    question = next((f for f in a.report.of_result(Result.QUESTION) if f.digest == ref), None)
    if question is None:
        return refuse(f'no open thread or open question "{ref}" (see zigdag findings)')
    project.append(lg.answered_question(now(), lg.Actor(by), question, choice, say))
    print(f"answered question {ref}")
    return OK


def findings(project: Project) -> int:
    a = project.analysis
    threads = list(lg.open_threads(a.log))
    questions = a.report.of_result(Result.QUESTION)
    lines = []
    if threads:
        lines += ["open threads", *(f"  {t.raised.id}  {t.raised.at}  {t.raised.by}  {t.raised.kind.value}  "
                                    f"{t.raised.on}: {t.raised.say}" for t in threads), ""]
    if questions:
        lines += ["open questions", *(f"  {f.digest}  {f.rule}  {f.about}: {f.say}" for f in questions), ""]
    print("\n".join([*lines, f"{len(threads)} open threads, {len(questions)} open questions"]))
    return OK


def view(project: Project, name: str, target: str | None) -> int:
    a = project.analysis
    if name == SHOW:
        print(views.show(a, FrName(target) if target else None))
    elif name == DATA_VIEW:
        print(views.data(a, FrName(target) if target else None))
    elif name == CONTEXT:
        print(views.context(a, target or ""))
    else:
        print(views.next_steps(a))
    return OK


def init_project(project: Project, force: bool) -> int:
    """Record the code as it is: an FR per package and module, its effects and dependencies, its known breaks."""
    files = project_files(project.files)
    if files.design and not force:
        return refuse("design/ already has a record; use --force to replace its functional.yaml and process.yaml")
    code = code_model(project.files)
    if code is None:
        return refuse("no Python code found to record")
    if files.settings is None:
        new_settings = settings_text(source_roots(project.files))
        project.write(RecordPath(SETTINGS_FILE), new_settings)
        files = project_files({**project.files, RecordPath(SETTINGS_FILE): new_settings})
    written, left = init(files, code)
    if not written:
        return refuse("; ".join(left))
    for path, text in written.items():
        project.write(path, text)
    lines = [f"wrote {p}" for p in project.written]
    if left:
        lines += ["these could not be recorded as debt, and need a decision:", *(f"  {x}" for x in left)]
    print("\n".join([*lines, "next: write the jobs in design/customer.yaml, then each FR's function (zigdag next)"]))
    return OK


def review(project: Project, base: str) -> int:
    changes = _changeset(project, base)
    if changes is None:
        return REFUSED
    gates, brought = changes.gates, changes.brought
    print(render(base, list(changes.changes), changes.after.log, changes.after.people, gates, brought))
    return FOUND if gates or any(f.result is Result.BREAKS for f in brought) else OK


def _chosen(project: Project, names: list[str], base: str | None) -> list[Entry] | None:
    """The entries named, or those changed since base; None (refused) when neither is given or a name is unknown."""
    current = project.analysis.entries
    if names:
        unknown = [n for n in names if n not in current]
        if unknown:
            refuse(f"no entry named {', '.join(unknown)}")
            return None
        return [current[n] for n in names]
    if base is None:
        refuse("name the entries, or give --base to choose those changed since it")
        return None
    changes = _changeset(project, base)
    return changes.changed if changes is not None else None


def approve(project: Project, names: list[str], base: str | None, by: str) -> int:
    chosen = _chosen(project, names, base)
    if chosen is None:
        return REFUSED
    a = project.analysis
    for entry in chosen:
        project.append(lg.approved(now(), lg.Actor(by), entry.name, entry.digest))
    note = "" if by in a.people else f" ({by} is not in [settings] people, so this approval is an agent's)"
    print(f"approved {len(chosen)} entries{note}")
    return OK


def critique_request(project: Project, names: list[str], base: str | None) -> int:
    chosen = _chosen(project, names, base)
    if chosen is None:
        return REFUSED
    a = project.analysis
    text, asked = request(a.record, a.log, chosen)
    project.write(CRITIQUE_REQUEST, text)
    print(f"wrote {CRITIQUE_REQUEST}: {asked} entries with questions to answer, rubric {RUBRIC_VERSION}\n"
          "give that file, and nothing else, to a fresh critic; then: zigdag critique --record <answer.json> --by <critic>")
    return OK


def critique_record(project: Project, answer_path: Path, by: str) -> int:
    if not answer_path.is_file():
        return refuse(f"no answer at {answer_path}")
    judged, problems = read_answer(project.analysis.entries, answer_path.read_text(encoding="utf-8"))
    raised = 0
    for j in judged:
        project.append(lg.critiqued(now(), lg.Actor(by), j.entry.name, j.entry.digest, RUBRIC_VERSION))
        for f in j.findings:
            project.append(lg.raised(now(), lg.Actor(by), f.kind, j.entry.name, f.say, f.evidence))
            raised += 1
    print("\n".join([f"recorded the critique of {len(judged)} entries, raising {raised} findings",
                     *(f"  refused: {p}" for p in problems)]))
    return FOUND if problems else OK


def rename_fr(project: Project, old: str, new: str) -> int:
    a = project.analysis
    old_name, new_name = fr_name(old), fr_name(new)
    if old_name is None or old_name not in a.record.frs:
        return refuse(f'no FR named "{old}"')
    if new_name is None or new_name in a.record.frs:
        return refuse(f'"{new}" is not a free FR name')
    design = project_files(project.files).design
    changed, missed = rename(design, test_files(project.files), old_name, new_name)
    claims = a.tree.claims_under(old_name) if a.tree else {}
    renamed_files = {**project.files, **changed}
    after = analyse(project_files(renamed_files), code_model(renamed_files))
    keep = {}
    for name, units in claims.items():
        new_dp = FrName(renamed(name, old_name, new_name))
        if after.tree is not None and after.tree.claims_of(new_dp) != units:
            keep[new_dp] = units
    if keep:
        physical = domain_file(Domain.PHYSICAL)
        changed[physical] = keep_code(changed.get(physical, design.get(physical)), keep)
    for path, text in changed.items():
        project.write(path, text)
    print("\n".join([f"renamed {old} to {new} in {len(changed)} files", *(f"  {p}" for p in sorted(changed)),
                     *(f"  could not change: {m}" for m in missed)]))
    return FOUND if missed else OK


def agent_install(project: Project, product: str, command: str) -> int:
    if product != claude.PRODUCT:
        return refuse(f"unknown agent {product!r}; known: {claude.PRODUCT}")
    for path, text in claude.skill_files().items():
        project.write(RecordPath(path), text)
    settings = claude.merged_settings(project.read(RecordPath(claude.SETTINGS)), command)
    if settings is None:
        return refuse(f"{claude.SETTINGS} is not a JSON object: fix it, then install again")
    project.write(RecordPath(claude.SETTINGS), settings)
    print(f"installed {len(claude.skill_files())} skills and two hooks for {product}; restart the agent to load them")
    return OK


def hook(project: Project, event: str, payload: str) -> int:
    a = project.analysis
    if event == claude.SESSION_START:
        print(claude.session_text(views.show(a), views.next_steps(a), sum(1 for t in a.log.threads if t.open)))
        return OK
    edited = claude.edited_path(payload)
    relevant = claude.relevant(a, project.root, edited)[:HOOK_FINDINGS]
    if not relevant:
        return OK
    print("\n".join(["zigdag check found:", *map(_line, relevant)]), file=sys.stderr)
    return claude.FEEDBACK_EXIT

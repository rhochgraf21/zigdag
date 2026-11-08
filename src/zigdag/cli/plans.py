"""The command line's decisions, made without effects (DESIGN2 §4.1, planned-effects): which files to read, and what
each command does with what was read, down to the files it writes, the lines it adds to the log, what it prints and
the code it exits with. The rest of the command line only carries these plans out.
"""

from __future__ import annotations

import argparse
import enum
import fnmatch
import json
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NewType

from zigdag.adapters.python import PythonFiles, read_python
from zigdag.agents import claude
from zigdag.core import log as lg
from zigdag.core import views
from zigdag.core.checks.gates import check_gates
from zigdag.core.checks.run import Analysis, ProjectFiles, analyse
from zigdag.core.critique import read_answer, request
from zigdag.core.init import init as init_record
from zigdag.core.init import settings_text
from zigdag.core.record.entries import Entry
from zigdag.core.record.fmt import format_text
from zigdag.core.record.model import Domain
from zigdag.core.record.read import DESIGN_DIR, DESIGN_SUFFIX, domain_file
from zigdag.core.rename import keep_code, rename, renamed
from zigdag.core.review import Change, ChangeKind, diff, new_findings, render
from zigdag.core.rubric import RUBRIC_VERSION
from zigdag.core.settings import (
    DEFAULT_REPORT,
    DEFAULT_TEST_COMMAND,
    OBSERVED_FILE,
    PLAN_FILE,
    PROJECT_ROOT,
    SETTINGS_FILE,
    WORK_DIR,
    Settings,
    read_settings,
)
from zigdag.core.watch import PLAN_VARIABLE
from zigdag.core.watch import plan as watch_plan
from zigdag.core.code import CodeModel
from zigdag.core.findings import Finding, RecordPath, Report, Result
from zigdag.core.log import LOG_FILE
from zigdag.core.names import PYTHON, FrName, fr_name
from zigdag.core.findings import Subject
from zigdag.core.log import Actor, EventLine
from zigdag.core.names import FilePath, ProjectRoot, Revision, ShellCommand
from zigdag.core.texts import FileText, Say, Shown, Written

ExitCode = NewType("ExitCode", int)
OK, FOUND, REFUSED = ExitCode(0), ExitCode(1), ExitCode(2)  # nothing wrong; something breaks or would change; refused

Files = Mapping[RecordPath, FileText]  # project-relative path -> text
GitInput = NewType("GitInput", bytes)  # what git is asked, on its standard input
GitOutput = NewType("GitOutput", bytes)  # what git answers, on its standard output or error
Argument = NewType("Argument", str)  # one argument of a command line, as it was typed
Environment = NewType("Environment", dict[str, str])  # the environment variables, read once by the shell


class Presence(enum.Enum):
    """Whether something is there, as the shell found it: a file, a folder."""

    PRESENT = True
    ABSENT = False


class View(enum.Enum):
    SHOW = "show"
    DATA = "data"  # show --data
    CONTEXT = "context"
    NEXT = "next"


class GitError(Exception):
    """A git revision could not be read."""

PYPROJECT = RecordPath("pyproject.toml")
CONVENTIONAL_SOURCE = "src"  # where Python source is, when zigdag.toml does not say
PYTHON_SUFFIX = ".py"
SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__"})
HIDDEN_PREFIX = "."
DESIGN_DEPTHS = (2, 3)  # design/<domain>.yaml, and design/<domain>/<part>.yaml
ALWAYS_READ = frozenset({RecordPath(SETTINGS_FILE), PYPROJECT, LOG_FILE, OBSERVED_FILE})
GIT_MISSING = "missing"  # what `git cat-file --batch` says instead of a size for a path absent at the revision

GIT_ATTRIBUTES = RecordPath(".gitattributes")
UNION_MERGE = f"{lg.LOG_FILE} merge=union"
CRITIQUE_REQUEST = RecordPath(f"{WORK_DIR}/critique/request.json")
HOOK_FINDINGS = 15  # at most this many findings in what a hook tells an agent
WATCHER = "zigdag.watchers.python"  # the pytest plugin that watches the tests run
PLUGIN_OPTION, REPORT_OPTION = "-p", "--junitxml"
TEST = "test"
LINE_END = "\n"

_HEADINGS = ((Result.BREAKS, "breaks"), (Result.QUESTION, "questions"), (Result.TODO, "to do"))
_COUNTED = {Result.BREAKS: ("break", "breaks"), Result.QUESTION: ("question", "questions"),
            Result.TODO: ("thing to do", "things to do")}


# ---- what a command does -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Write:
    path: RecordPath
    text: str


@dataclass(frozen=True)
class Outcome:
    """What a command does once it has decided: the files it writes, the lines it adds to the log, what it prints,
    and the code it exits with. They are carried out in that order."""

    exit: ExitCode = OK
    out: tuple[Shown, ...] = ()  # printed to standard output, one item a print
    err: tuple[Shown, ...] = ()  # printed to standard error
    writes: tuple[Write, ...] = ()
    log: tuple[EventLine, ...] = ()  # events added to the log


def refused(say: str) -> Outcome:
    return Outcome(REFUSED, err=(f"zigdag: {say}",))


def appended(log: FileText | None, attributes: FileText | None, line: EventLine) -> tuple[Write, ...]:
    """Adding one event to the log, and making git merge the log as a union so branches never conflict."""
    to_log = Write(lg.LOG_FILE, (log or "") + line + LINE_END)
    current = attributes or ""
    if UNION_MERGE in current.splitlines():
        return (to_log,)
    ended = current if not current or current.endswith(LINE_END) else current + LINE_END
    return to_log, Write(GIT_ATTRIBUTES, ended + UNION_MERGE + LINE_END)


def at_root(root: ProjectRoot, path: RecordPath) -> FilePath:
    return root / path


# ---- which files to read -----------------------------------------------------------------------------------------

def _visited(folder: str) -> bool:
    """Whether a folder is worth looking in: not hidden (except zigdag's own), not a cache."""
    return folder not in SKIPPED_FOLDERS and (not folder.startswith(HIDDEN_PREFIX) or folder == WORK_DIR)


def _under(path: str, root: str) -> bool:
    return root == PROJECT_ROOT or path.startswith(root + "/")


@dataclass(frozen=True)
class Reading:
    """What to read, once the settings are known."""

    settings: Settings
    source_roots: tuple[str, ...]

    @staticmethod
    def of(settings_text: FileText | None, has_conventional_source: Presence) -> Reading:
        settings, _ = read_settings(settings_text)
        configured = settings.source_roots(PYTHON)
        default = (CONVENTIONAL_SOURCE,) if has_conventional_source is Presence.PRESENT else (PROJECT_ROOT,)
        return Reading(settings, configured if configured is not None else default)

    @property
    def folders(self) -> tuple[str, ...]:
        """The folders to walk; the whole project when the source is the project itself."""
        if PROJECT_ROOT in self.source_roots:
            return (PROJECT_ROOT,)
        return (DESIGN_DIR, WORK_DIR, *self.source_roots, *self.settings.test_roots)

    def is_source(self, path: str) -> bool:
        return path.endswith(PYTHON_SUFFIX) and any(_under(path, r) for r in self.source_roots) and not self.is_test(
            path)

    def is_test(self, path: str) -> bool:
        return path.endswith(PYTHON_SUFFIX) and any(_under(path, r) for r in self.settings.test_roots)

    def is_report(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.settings.report_patterns)

    def wants(self, path: str) -> bool:
        parts = path.split("/")
        if not all(_visited(p) for p in parts[:-1]):
            return False
        is_design = parts[0] == DESIGN_DIR and path.endswith(DESIGN_SUFFIX) and len(parts) in DESIGN_DEPTHS
        return path in ALWAYS_READ or is_design or self.is_source(path) or self.is_test(path) or self.is_report(path)

    def chosen(self, paths: Iterable[str]) -> list[RecordPath]:
        return [RecordPath(p) for p in sorted(set(paths)) if self.wants(p)]


@dataclass(frozen=True)
class OnDisk:
    """Where a project on disk keeps what decides how it is read."""

    settings: Path
    conventional_source: Path
    always: tuple[Path, ...]  # read wherever the source is


def on_disk(root: ProjectRoot) -> OnDisk:
    return OnDisk(root / SETTINGS_FILE, root / CONVENTIONAL_SOURCE, tuple(root / name for name in sorted(ALWAYS_READ)))


def walked(root: ProjectRoot, reading: Reading) -> tuple[FilePath, ...]:
    return tuple(root / folder for folder in reading.folders)


def visited(folders: Iterable[Written]) -> list[Written]:
    return sorted(f for f in folders if _visited(f))


def found(root: ProjectRoot, here: Written, names: Iterable[Subject]) -> list[RecordPath]:
    return [(Path(here) / name).relative_to(root).as_posix() for name in names]


def present(root: ProjectRoot, checked: Iterable[tuple[FilePath, Presence]]) -> list[RecordPath]:
    """The paths that exist, of those checked."""
    return [RecordPath(path.relative_to(root).as_posix()) for path, exists in checked if exists is Presence.PRESENT]


@dataclass(frozen=True)
class Listed:
    """What git listed at a revision: its paths, or why it could not."""

    failed: bool
    error: str
    paths: tuple[str, ...]

    @property
    def settings_paths(self) -> tuple[str, ...]:
        return (SETTINGS_FILE,) if SETTINGS_FILE in self.paths else ()


def listed(revision: Revision, returncode: ExitCode, stdout: GitOutput, stderr: GitOutput) -> Listed:
    if returncode != 0:
        return Listed(True, stderr.decode().strip() or f"cannot read {revision}", ())
    return Listed(False, "", tuple(stdout.decode().splitlines()))


def git_reading(listing: Listed, settings: Mapping[RecordPath, FileText]) -> Reading:
    return Reading.of(settings.get(RecordPath(SETTINGS_FILE)),
                      Presence(any(_under(p, CONVENTIONAL_SOURCE) for p in listing.paths)))


def batch_request(revision: Revision, paths: Iterable[RecordPath]) -> GitInput:
    """What `git cat-file --batch` is asked for: each path at the revision, one a line."""
    return "".join(f"{revision}:{p}{LINE_END}" for p in paths).encode()


def _object_size(header: str) -> int | None:
    """The size from a `git cat-file --batch` header: `<object> <type> <size>`, or `<name> missing`."""
    last = header.rsplit(" ", 1)[-1]
    return None if last == GIT_MISSING else int(last)


def batch_texts(paths: Sequence[RecordPath], out: GitOutput) -> dict[RecordPath, FileText]:
    """The text of each path, read from one `git cat-file --batch` answer. Paths absent at the revision are left
    out."""
    texts: dict[str, str] = {}
    at = 0
    for path in paths:
        end = out.index(b"\n", at)
        size = _object_size(out[at:end].decode())
        at = end + 1
        if size is not None:
            texts[path] = out[at:at + size].decode("utf-8", errors="replace")
            at += size + 1  # the content is followed by a newline
    return texts


def git_files(reading: Reading, texts: Mapping[RecordPath, FileText]) -> dict[RecordPath, FileText]:
    return {path: texts[path] for path in reading.chosen(texts)}


# ---- what was read -----------------------------------------------------------------------------------------------

def reading_of(files: Files) -> Reading:
    return Reading.of(files.get(RecordPath(SETTINGS_FILE)), Presence(any(_under(p, CONVENTIONAL_SOURCE) for p in files)))


def project_files(files: Files) -> ProjectFiles:
    design = {p: t for p, t in files.items() if p.startswith(DESIGN_DIR + "/") and p.endswith(DESIGN_SUFFIX)}
    return ProjectFiles(files.get(RecordPath(SETTINGS_FILE)), design, files.get(LOG_FILE))


def python_files(files: Files) -> PythonFiles | None:
    """What the Python adapter reads, or None when there is no Python source."""
    reading = reading_of(files)
    sources = {p: t for p, t in files.items() if reading.is_source(p)}
    if not sources:
        return None
    return PythonFiles(sources, reading.source_roots, reading.settings.vendor,
                       {p: t for p, t in files.items() if reading.is_test(p)}, files.get(PYPROJECT),
                       {p: t for p, t in files.items() if reading.is_report(p)}, files.get(OBSERVED_FILE))


def source_roots(files: Files) -> tuple[str, ...]:
    """Where the project's Python source is."""
    return reading_of(files).source_roots


def test_files(files: Files) -> dict[RecordPath, str]:
    reading = reading_of(files)
    return {p: t for p, t in files.items() if reading.is_test(p)}


def code_model(files: Files) -> CodeModel | None:
    python = python_files(files)
    return read_python(python) if python is not None else None


def analysis(files: Files) -> Analysis:
    return analyse(project_files(files), code_model(files))


# ---- reports -----------------------------------------------------------------------------------------------------

def line(f: Finding) -> str:
    handle = f"  [{f.digest}]" if f.result is Result.QUESTION else ""
    return f"  {f.span or '-'}  {f.rule}  {f.about}: {f.say}{handle}"


def render_report(report: Report) -> str:
    lines = []
    for result, heading in _HEADINGS:
        found_ = report.of_result(result)
        if found_:
            lines += [heading, *map(line, found_), ""]
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
    def of(base: str, before: Analysis, after: Analysis) -> Changeset:
        return Changeset(base, before, after, tuple(diff(before.record, after.record, before.sentences,
                                                         after.sentences)))

    @property
    def changed(self) -> list[Entry]:
        return [c.entry for c in self.changes if c.kind is not ChangeKind.REMOVED]

    @property
    def gates(self) -> list[Finding]:
        a = self.after
        return list(check_gates(a.record, a.log, a.people, self.changed, a.report))

    @property
    def brought(self) -> list[Finding]:
        return new_findings(self.before.report, self.after.report)


def revisions(base: Revision | None) -> tuple[Revision, ...]:
    """The revisions to read: the base, when there is one."""
    return (base,) if base is not None else ()


def revisions_to_choose(names: Sequence[Subject], base: Revision | None) -> tuple[Revision, ...]:
    """The revisions to read to choose entries: the base, when entries are chosen by what changed since it."""
    return () if names else revisions(base)


def unreadable(base: Revision | None, error: GitError) -> Outcome:
    return refused(f"cannot read {base}: {error}")


@dataclass(frozen=True)
class Chosen:
    """The entries a command is about, or why there are none."""

    entries: tuple[Entry, ...]
    refusal: Outcome | None = None


def _chosen(a: Analysis, earlier: Sequence[Analysis], names: Sequence[str], base: str | None) -> Chosen:
    """The entries named, or those changed since the base; refused when neither is given or a name is unknown."""
    current = a.entries
    if names:
        unknown = [n for n in names if n not in current]
        if unknown:
            return Chosen((), refused(f"no entry named {', '.join(unknown)}"))
        return Chosen(tuple(current[n] for n in names))
    if base is None:
        return Chosen((), refused("name the entries, or give --base to choose those changed since it"))
    return Chosen(tuple(Changeset.of(base, earlier[0], a).changed))


# ---- commands ----------------------------------------------------------------------------------------------------

def _gated(a: Analysis, earlier: Sequence[Analysis], base: Revision | None) -> Report:
    """The report, with the workflow gates for what changed since the base, when there is one."""
    report = a.report
    for before in earlier:
        report = Report.of([*report.findings, *Changeset.of(base or Revision(""), before, a).gates])
    return report


def check(a: Analysis, earlier: Sequence[Analysis], base: Revision | None) -> Outcome:
    report = _gated(a, earlier, base)
    open_threads = sum(1 for t in a.log.threads if t.open)
    note = (Shown(f"{open_threads} open threads in the log: zigdag findings"),) if open_threads else ()
    return Outcome(FOUND if report.breaks else OK, (Shown(render_report(report)), *note))


def check_json(a: Analysis, earlier: Sequence[Analysis], base: Revision | None) -> Outcome:
    report = _gated(a, earlier, base)
    return Outcome(FOUND if report.breaks else OK, (Shown(report_json(report)),))


@dataclass(frozen=True)
class WatchedRun:
    """How the tests are run under the watcher, or why they cannot be."""

    refused: bool
    refusal: Outcome
    watch: str  # the watch plan, as the watcher reads it
    observed: Path  # where the watcher writes what it saw
    command: tuple[str, ...]
    root: Path
    environment: Mapping[str, str]


def test(a: Analysis, files: Files, root: ProjectRoot, extra: Sequence[Argument],
         environment: Environment) -> WatchedRun:
    watch = watch_plan(a, test_files(files))
    observed = root / OBSERVED_FILE
    if watch is None:
        return WatchedRun(True, refused("no code was read, so there is nothing to watch"), "", observed, (), root, {})
    command = (*shlex.split(a.settings.test_command or DEFAULT_TEST_COMMAND), PLUGIN_OPTION, WATCHER,
               f"{REPORT_OPTION}={DEFAULT_REPORT}", *extra)
    return WatchedRun(False, Outcome(), watch.to_text(), observed, command, root,
                   {**environment, PLAN_VARIABLE: str(root / PLAN_FILE)})


def tested(run: WatchedRun, seen: Presence, returncode: ExitCode, after: Analysis) -> Outcome:
    shown = shlex.join(run.command)
    if seen is Presence.ABSENT:
        return refused(f"the tests ran ({shown} exited {returncode}), but the watcher saw nothing: the tests' Python "
                       f"must be able to import zigdag")
    report = after.report
    return Outcome(FOUND if report.breaks or returncode else OK, (render_report(report), f"tests: {shown} exited "
                                                                                         f"{returncode}"))


@dataclass(frozen=True)
class Formatted:
    """Each design file in its canonical layout: the ones that change, and what could not be read."""

    changed: tuple[Write, ...]
    unreadable: tuple[RecordPath, ...]
    problems: tuple[Shown, ...]

    @staticmethod
    def of(files: Files) -> Formatted:
        changed, unreadable_, problems = [], [], []
        for path, text in project_files(files).design.items():
            formatted, found_ = format_text(path, text)
            if formatted is None:
                unreadable_.append(path)
                problems.append(Shown("\n".join(line(p) for p in found_)))
            elif formatted != text:
                changed.append(Write(path, formatted))
        return Formatted(tuple(changed), tuple(unreadable_), tuple(problems))

    def summary(self, verb: str) -> Shown:
        return Shown("\n".join([*(f"{verb} {w.path}" for w in self.changed), f"{len(self.changed)} {verb}, "
                                                                            f"{len(self.unreadable)} could not be read"]))


def fmt(files: Files) -> Outcome:
    """Each design file rewritten in its canonical layout."""
    done = Formatted.of(files)
    return Outcome(FOUND if done.unreadable else OK, (*done.problems, done.summary("reformatted")), writes=done.changed)


def fmt_check(files: Files) -> Outcome:
    """The design files that are not in their canonical layout, changing nothing."""
    done = Formatted.of(files)
    return Outcome(FOUND if done.unreadable or done.changed else OK, (*done.problems, done.summary("would reformat")))


def raise_(a: Analysis, at: lg.Timestamp, kind: lg.Kind, on: Subject, say: Say, by: Actor, evidence: Written | None) -> Outcome:
    if on not in a.known_names:
        return refused(f'nothing in the record is named "{on}"')
    event = lg.raised(at, lg.Actor(by), lg.Kind(kind), on, say, evidence)
    thread = lg.thread_id(json.loads(event)["at"], lg.Actor(by), on, say)
    if a.log.thread(thread) is not None:
        return refused("that was already raised")
    return Outcome(out=(f"raised {thread}",), log=(event,))


def answer(a: Analysis, at: lg.Timestamp, ref: Written, answer_: lg.Answer, say: Say, by: Actor,
           countermeasure: Subject | None) -> Outcome:
    if countermeasure is not None and countermeasure not in a.known_names:
        return refused(f'the countermeasure names nothing in the record: "{countermeasure}"')
    choice = answer_
    thread = a.log.thread(lg.ThreadId(ref))
    if thread is not None:
        if not thread.open:
            return refused(f"thread {ref} is already answered; raise it again if it is back")
        return Outcome(out=(f"answered thread {ref}",),
                       log=(lg.answered_thread(at, lg.Actor(by), thread.raised.id, choice, say, countermeasure),))
    question = next((f for f in a.report.of_result(Result.QUESTION) if f.digest == ref), None)
    if question is None:
        return refused(f'no open thread or open question "{ref}" (see zigdag findings)')
    return Outcome(out=(f"answered question {ref}",),
                   log=(lg.answered_question(at, lg.Actor(by), question, choice, say),))


def findings(a: Analysis) -> Outcome:
    threads = list(lg.open_threads(a.log))
    questions = a.report.of_result(Result.QUESTION)
    lines = []
    if threads:
        lines += ["open threads", *(f"  {t.raised.id}  {t.raised.at}  {t.raised.by}  {t.raised.kind.value}  "
                                    f"{t.raised.on}: {t.raised.say}" for t in threads), ""]
    if questions:
        lines += ["open questions", *(f"  {f.digest}  {f.rule}  {f.about}: {f.say}" for f in questions), ""]
    return Outcome(out=("\n".join([*lines, f"{len(threads)} open threads, {len(questions)} open questions"]),))


def view(a: Analysis, name: View, target: Written | None) -> Outcome:
    match name:
        case View.SHOW:
            return Outcome(out=(views.show(a, FrName(target) if target else None),))
        case View.DATA:
            return Outcome(out=(views.data(a, FrName(target) if target else None),))
        case View.CONTEXT:
            return Outcome(out=(views.context(a, target or Written("")),))
    return Outcome(out=(views.next_steps(a),))


def init(files: Files) -> Outcome:
    """The code recorded as it is, when there is no record yet."""
    if project_files(files).design:
        return refused("design/ already has a record; use --force to replace its functional.yaml and process.yaml")
    return init_forced(files)


def init_forced(files: Files) -> Outcome:
    """The code recorded as it is: an FR per package and module, its effects and dependencies, its known breaks."""
    read = project_files(files)
    code = code_model(files)
    if code is None:
        return refused("no Python code found to record")
    writes: list[Write] = []
    if read.settings is None:
        new_settings = settings_text(source_roots(files))
        writes.append(Write(RecordPath(SETTINGS_FILE), new_settings))
        read = project_files({**files, RecordPath(SETTINGS_FILE): new_settings})
    written, left = init_record(read, code)
    if not written:
        return refused("; ".join(left))
    writes += [Write(path, text) for path, text in written.items()]
    lines = [f"wrote {w.path}" for w in writes]
    if left:
        lines += ["these could not be recorded as debt, and need a decision:", *(f"  {x}" for x in left)]
    return Outcome(out=("\n".join([*lines, "next: write the jobs in design/customer.yaml, then each FR's function "
                                           "(zigdag next)"]),), writes=tuple(writes))


def review(base: Revision, before: Analysis, after: Analysis) -> Outcome:
    changes = Changeset.of(base, before, after)
    gates, brought = changes.gates, changes.brought
    shown = render(base, list(changes.changes), after.log, after.people, gates, brought)
    return Outcome(FOUND if gates or any(f.result is Result.BREAKS for f in brought) else OK, (shown,))


def approve(a: Analysis, earlier: Sequence[Analysis], names: Sequence[Subject], base: Revision | None, by: Actor,
            at: lg.Timestamp) -> Outcome:
    chosen = _chosen(a, earlier, names, base)
    if chosen.refusal is not None:
        return chosen.refusal
    events = tuple(lg.approved(at, lg.Actor(by), entry.name, entry.digest) for entry in chosen.entries)
    note = "" if by in a.people else f" ({by} is not in [settings] people, so this approval is an agent's)"
    return Outcome(out=(f"approved {len(chosen.entries)} entries{note}",), log=events)


def critique_request(a: Analysis, earlier: Sequence[Analysis], names: Sequence[Subject], base: Revision | None) -> Outcome:
    chosen = _chosen(a, earlier, names, base)
    if chosen.refusal is not None:
        return chosen.refusal
    text, asked = request(a.record, a.log, list(chosen.entries))
    return Outcome(out=(f"wrote {CRITIQUE_REQUEST}: {asked} entries with questions to answer, rubric {RUBRIC_VERSION}\n"
                        "give that file, and nothing else, to a fresh critic; then: zigdag critique --record "
                        "<answer.json> --by <critic>",), writes=(Write(CRITIQUE_REQUEST, text),))


def critique_record(a: Analysis, answer_text: FileText | None, answer_path: FilePath, by: Actor, at: lg.Timestamp) -> Outcome:
    if answer_text is None:
        return refused(f"no answer at {answer_path}")
    judged, problems = read_answer(a.entries, answer_text)
    events = []
    for j in judged:
        events.append(lg.critiqued(at, lg.Actor(by), j.entry.name, j.entry.digest, RUBRIC_VERSION))
        events += [lg.raised(at, lg.Actor(by), f.kind, j.entry.name, f.say, f.evidence) for f in j.findings]
    raised = len(events) - len(judged)
    return Outcome(FOUND if problems else OK, ("\n".join([f"recorded the critique of {len(judged)} entries, raising "
                                                          f"{raised} findings", *(f"  refused: {p}" for p in problems)]),),
                   log=tuple(events))


def rename_fr(a: Analysis, files: Files, old: Written, new: Written) -> Outcome:
    old_name, new_name = fr_name(old), fr_name(new)
    if old_name is None or old_name not in a.record.frs:
        return refused(f'no FR named "{old}"')
    if new_name is None or new_name in a.record.frs:
        return refused(f'"{new}" is not a free FR name')
    design = project_files(files).design
    changed, missed = rename(design, test_files(files), old_name, new_name)
    claims = a.tree.claims_under(old_name) if a.tree else {}
    after = analysis({**files, **changed})
    keep = {}
    for name, units in claims.items():
        new_dp = FrName(renamed(name, old_name, new_name))
        if after.tree is not None and after.tree.claims_of(new_dp) != units:
            keep[new_dp] = units
    if keep:
        physical = domain_file(Domain.PHYSICAL)
        changed[physical] = keep_code(changed.get(physical, design.get(physical)), keep)
    shown = "\n".join([f"renamed {old} to {new} in {len(changed)} files", *(f"  {p}" for p in sorted(changed)),
                       *(f"  could not change: {m}" for m in missed)])
    return Outcome(FOUND if missed else OK, (shown,), writes=tuple(Write(p, t) for p, t in changed.items()))


def agent_install(product: Written, command: ShellCommand, settings: FileText | None) -> Outcome:
    if product != claude.PRODUCT:
        return refused(f"unknown agent {product!r}; known: {claude.PRODUCT}")
    merged = claude.merged_settings(settings, command)
    if merged is None:
        return refused(f"{claude.SETTINGS} is not a JSON object: fix it, then install again")
    skills = tuple(Write(RecordPath(path), text) for path, text in claude.skill_files().items())
    return Outcome(out=(f"installed {len(skills)} skills and two hooks for {product}; restart the agent to load them",),
                   writes=(*skills, Write(RecordPath(claude.SETTINGS), merged)))


def hook(a: Analysis, root: ProjectRoot, event: claude.HookEvent, payload: claude.Payload) -> Outcome:
    if event == claude.SESSION_START:
        return Outcome(out=(claude.session_text(views.show(a), views.next_steps(a),
                                                sum(1 for t in a.log.threads if t.open)),))
    shown = claude.relevant(a, root, claude.edited_path(payload))[:HOOK_FINDINGS]
    if not shown:
        return Outcome()
    return Outcome(ExitCode(claude.FEEDBACK_EXIT), err=("\n".join(["zigdag check found:", *map(line, shown)]),))


# ---- which command -----------------------------------------------------------------------------------------------

class Command(enum.Enum):
    CHECK = "check"
    CHECK_JSON = "check --json"
    TEST = "test"
    FMT = "fmt"
    FMT_CHECK = "fmt --check"
    RAISE = "raise"
    ANSWER = "answer"
    FINDINGS = "findings"
    VIEW = "view"  # show, context, next, and show --data
    INIT = "init"
    INIT_FORCED = "init --force"
    REVIEW = "review"
    APPROVE = "approve"
    CRITIQUE_REQUEST = "critique --request"
    CRITIQUE_RECORD = "critique --record"
    RENAME = "rename"
    AGENT = "agent"
    HOOK_SESSION = "hook session-start"
    HOOK_EDIT = "hook post-edit"  # reads what the agent edited from standard input
    REFUSED = "refused"


_COMMANDS = {c.value: c for c in Command}
_VIEWS = frozenset({View.SHOW.value, View.CONTEXT.value, View.NEXT.value})
_CHOSEN_BY_FLAG = {"check": ("json", Command.CHECK_JSON), "fmt": ("check", Command.FMT_CHECK),
                   "init": ("force", Command.INIT_FORCED)}  # a command a flag picks: (the flag, the command)


@dataclass(frozen=True)
class Route:
    """Which command runs, on which project, with the arguments it was given."""

    command: Command
    root: Path
    args: argparse.Namespace
    passed_on: tuple[str, ...]  # what goes on to the test command
    rejected: bool  # the arguments are wrong: the parser says so, and exits
    rejection: str
    refusal: Outcome  # for a command that cannot run as asked
    view: View = View.NEXT
    target: Written | None = None


def _command(args: argparse.Namespace) -> Command:
    if args.command in _VIEWS:
        return Command.VIEW
    if args.command == "critique":
        return Command.CRITIQUE_REQUEST if args.request else Command.CRITIQUE_RECORD if args.by else Command.REFUSED
    if args.command == "hook":
        return Command.HOOK_EDIT if args.event == claude.POST_EDIT else Command.HOOK_SESSION
    flag, flagged = _CHOSEN_BY_FLAG.get(args.command, (None, None))
    if flag is not None and getattr(args, flag):
        return flagged
    return _COMMANDS.get(args.command, Command.REFUSED)


def route(args: argparse.Namespace, passed_on: Sequence[str], cwd: Path) -> Route:
    """The command the arguments ask for. The project is where --project says, or here."""
    rejected = bool(passed_on) and args.command != TEST
    command = _command(args)
    refusal = refused("--record needs --by") if args.command == "critique" else refused(
        f"unknown command {args.command!r}")
    view = View.DATA if args.command == View.SHOW.value and args.data else View(args.command) if (
        args.command in _VIEWS) else View.NEXT
    target = getattr(args, "name", None) or getattr(args, "target", None)
    return Route(command, cwd / (args.project or cwd), args, tuple(passed_on), rejected,
                 f"unrecognized arguments: {' '.join(passed_on)}", refusal, view, target)

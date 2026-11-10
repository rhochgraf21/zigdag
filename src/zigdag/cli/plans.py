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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NewType

import deal

from zigdag.adapters.python import PythonFiles, read_python
from zigdag.adapters.python.observed import Recording
from zigdag.adapters.python.profiler import PROFILER, full_profile, profiled, read_profile
from zigdag.adapters.python import tools
from zigdag.adapters.python.tools import ToolOutput, ToolRun
from zigdag.agents import claude
from zigdag.core import log as lg
from zigdag.core import views
from zigdag.core.checks.directions import COUNTED, Standing, counted, standings
from zigdag.core.codec import Unreadable
from zigdag.core.profile import Cost, Profile, Suspect, by_part, compared, suspects
from zigdag.core.kinds.registry import Direction
from zigdag.core.checks.gates import check_gates
from zigdag.core.checks.rules import kinds_named
from zigdag.core.checks.tool_rules import wanted
from zigdag.core.checks.run import Analysis, ProjectFiles, analyse
from zigdag.core.critique import read_answer, request
from zigdag.core.init import init as init_record
from zigdag.core.init import CUSTOMER, CUSTOMER_TEMPLATE, settings_text, starter, tunable
from zigdag.core.record.entries import Entry
from zigdag.core.record.fmt import format_text
from zigdag.core.record.model import Domain
from zigdag.core.record.read import DESIGN_DIR, DESIGN_SUFFIX, domain_file, read_record
from zigdag.core.rename import keep_code, rename, renamed
from zigdag.core.review import Change, ChangeKind, diff, new_findings, render
from zigdag.core.rubric import RUBRIC_VERSION
from zigdag.core.settings import (
    CARRIED_FILE,
    DEFAULT_REPORT,
    DEFAULT_TEST_COMMAND,
    OBSERVED_FILE,
    PLAN_FILE,
    PROFILE_BEFORE,
    PROFILE_FILE,
    PROJECT_ROOT,
    SETTINGS_FILE,
    WORK_DIR,
    Settings,
    read_settings,
)
from zigdag.core.watch import PLAN_VARIABLE, LastRun
from zigdag.core.watch import plan as watch_plan
from zigdag.core.code import CodeModel
from zigdag.core.findings import Finding, RecordPath, Report, Result, Span, finding
from zigdag.core.log import LOG_FILE
from zigdag.core.measures import Count
from zigdag.core.names import PYTHON, FolderName, FrName, RuleId, fr_name
from zigdag.core.checks.custom import CHECKS_DIR, CUSTOM_CHECKS, CompiledCode, Loaded, Loading, fresh_names, read_checks
from zigdag.core.measures import Column, Line
from zigdag.core.effects import phrase
from zigdag.core.findings import Subject
from zigdag.core.log import Actor, EventLine
from zigdag.core.names import Argument, FilePath, ProjectRoot, Revision, ShellCommand
from zigdag.core.texts import FileText, Say, Shown, Written

ExitCode = NewType("ExitCode", int)
OK, FOUND, REFUSED = ExitCode(0), ExitCode(1), ExitCode(2)  # nothing wrong; something breaks or would change; refused

Files = Mapping[RecordPath, FileText]  # project-relative path -> text
GitInput = NewType("GitInput", bytes)  # what git is asked, on its standard input
GitOutput = NewType("GitOutput", bytes)  # what git answers, on its standard output or error
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
_WHOLE_FILE = "exec"  # how Python is told to compile a whole file, not one expression
CONVENTIONAL_SOURCE = "src"  # where Python source is, when zigdag.toml does not say
PYTHON_SUFFIX = ".py"
SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__"})
HIDDEN_PREFIX = "."
DESIGN_DEPTHS = (2, 3)  # design/<domain>.yaml, and design/<domain>/<part>.yaml
ALWAYS_READ = frozenset({RecordPath(SETTINGS_FILE), PYPROJECT, LOG_FILE, OBSERVED_FILE, CARRIED_FILE})
GIT_MISSING = "missing"  # what `git cat-file --batch` says instead of a size for a path absent at the revision

GIT_ATTRIBUTES = RecordPath(".gitattributes")
UNION_MERGE = f"{lg.LOG_FILE} merge=union"
CRITIQUE_REQUEST = RecordPath(f"{WORK_DIR}/critique/request.json")
REPORTS = RecordPath(f"{WORK_DIR}/check")  # each direction's findings in full, rewritten by every check
BREAKS_SHOWN = 10  # breaks of a direction shown under it; the rest are in its file
COLUMN_GAP = 2  # spaces between the columns of the summary
READY = "ready: yes"
NOT_READY = "ready: no"
FULL = "zigdag check --full"  # what shows every finding, with what the last zigdag test saw
HOOK_FINDINGS = 15  # at most this many findings in what a hook tells an agent
WATCHER = "zigdag.watchers.python"  # the pytest plugin that watches the tests run
PLUGIN_OPTION, REPORT_OPTION = "-p", "--junitxml"
TEST = "test"
LINE_END = "\n"

_TAGS = {Result.BREAKS: "break", Result.QUESTION: "question", Result.OUT_OF_DATE: "out-of-date", Result.TODO: "to-do"}  # as ty tags: error[rule]


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


def _changes_nothing(outcome: Outcome) -> bool:
    """Whether carrying an outcome out only prints: it writes no file and adds nothing to the log."""
    return not outcome.writes and not outcome.log


@deal.post(lambda result: result.exit == REFUSED and _changes_nothing(result))
def refused(say: str) -> Outcome:
    return Outcome(REFUSED, err=(f"zigdag: {say}",))


@deal.ensure(lambda log, attributes, line, result: result[0].path == lg.LOG_FILE
             and result[0].text == (log or "") + line + LINE_END)  # append-only: what was there stays, first
@deal.ensure(lambda log, attributes, line, result: all(w.path == GIT_ATTRIBUTES and UNION_MERGE in w.text.splitlines()
                                                       for w in result[1:]))
def appended(log: FileText | None, attributes: FileText | None, line: EventLine) -> tuple[Write, ...]:
    """Adding one event to the log, and making git merge the log as a union so branches never conflict."""
    to_log = Write(lg.LOG_FILE, (log or "") + line + LINE_END)
    current = attributes or ""
    if UNION_MERGE in current.splitlines():
        return (to_log,)
    ended = current if not current or current.endswith(LINE_END) else current + LINE_END
    return to_log, Write(GIT_ATTRIBUTES, ended + UNION_MERGE + LINE_END)


@deal.pre(lambda root, path: not Path(path).is_absolute())  # a record path is relative to the project
@deal.ensure(lambda root, path, result: result.is_relative_to(root))
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
    @deal.post(lambda result: bool(result.source_roots))  # source is always somewhere, if only the project itself
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
        # A file of custom checks is the project's design, not its code: where the source is the whole project, it
        # must not be read as a module that some design parameter has to own.
        return path.endswith(PYTHON_SUFFIX) and any(_under(path, r) for r in self.source_roots) and not (
            self.is_test(path) or is_custom_check(path))

    def is_test(self, path: str) -> bool:
        return path.endswith(PYTHON_SUFFIX) and any(_under(path, r) for r in self.settings.test_roots)

    def is_report(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.settings.report_patterns)

    def wants(self, path: str) -> bool:
        parts = path.split("/")
        if not all(_visited(p) for p in parts[:-1]):
            return False
        is_design = parts[0] == DESIGN_DIR and path.endswith(DESIGN_SUFFIX) and len(parts) in DESIGN_DEPTHS
        return (path in ALWAYS_READ or is_design or is_custom_check(path) or self.is_source(path)
                or self.is_test(path) or self.is_report(path))

    @deal.ensure(lambda self, paths, result: result == sorted(set(result)) and all(self.wants(p) for p in result))
    def chosen(self, paths: Iterable[str]) -> list[RecordPath]:
        return [RecordPath(p) for p in sorted(set(paths)) if self.wants(p)]


def is_custom_check(path: str) -> bool:
    return _under(path, CHECKS_DIR) and path.endswith(PYTHON_SUFFIX)


@dataclass(frozen=True)
class OnDisk:
    """Where a project on disk keeps what decides how it is read."""

    settings: Path
    conventional_source: Path
    always: tuple[Path, ...]  # read wherever the source is


@deal.ensure(lambda root, result: len(result.always) == len(ALWAYS_READ) and all(
    p.is_relative_to(root) for p in (result.settings, result.conventional_source, *result.always)))
def on_disk(root: ProjectRoot) -> OnDisk:
    return OnDisk(root / SETTINGS_FILE, root / CONVENTIONAL_SOURCE, tuple(root / name for name in sorted(ALWAYS_READ)))


@deal.ensure(lambda root, reading, result: len(result) == len(reading.folders))
def walked(root: ProjectRoot, reading: Reading) -> tuple[FilePath, ...]:
    return tuple(root / folder for folder in reading.folders)


@deal.post(lambda result: result == sorted(result) and all(_visited(f) for f in result))
def visited(folders: Iterable[Written]) -> list[Written]:
    return sorted(f for f in folders if _visited(f))


@deal.post(lambda result: not any(Path(p).is_absolute() for p in result))  # paths relative to the project
def found(root: ProjectRoot, here: Written, names: Iterable[Subject]) -> list[RecordPath]:
    return [(Path(here) / name).relative_to(root).as_posix() for name in names]


@deal.post(lambda result: not any(Path(p).is_absolute() for p in result))
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
    @deal.ensure(lambda self, result: set(result) <= {SETTINGS_FILE} and set(result) <= set(self.paths))
    def settings_paths(self) -> tuple[str, ...]:
        return (SETTINGS_FILE,) if SETTINGS_FILE in self.paths else ()


@deal.ensure(lambda revision, returncode, stdout, stderr, result: result.failed == (returncode != 0))
@deal.ensure(lambda revision, returncode, stdout, stderr, result: not result.failed or (
    bool(result.error) and result.paths == ()))  # a failure says why, and lists nothing
def listed(revision: Revision, returncode: ExitCode, stdout: GitOutput, stderr: GitOutput) -> Listed:
    if returncode != 0:  # git's message is for people: a byte it cannot decode is shown as a replacement
        return Listed(True, stderr.decode(errors="replace").strip() or f"cannot read {revision}", ())
    # paths are kept byte for byte, whatever their encoding, so that each can be asked for again as it was listed
    return Listed(False, "", tuple(stdout.decode(errors="surrogateescape").splitlines()))


@deal.post(lambda result: bool(result.source_roots))
def git_reading(listing: Listed, settings: Mapping[RecordPath, FileText]) -> Reading:
    return Reading.of(settings.get(RecordPath(SETTINGS_FILE)),
                      Presence(any(_under(p, CONVENTIONAL_SOURCE) for p in listing.paths)))


@deal.post(lambda result: not result or result.endswith(LINE_END.encode()))  # git reads one request a line
def batch_request(revision: Revision, paths: Iterable[RecordPath]) -> GitInput:
    """What `git cat-file --batch` is asked for: each path at the revision, one a line."""
    return "".join(f"{revision}:{p}{LINE_END}" for p in paths).encode()


def _object_size(header: str) -> int | None:
    """The size from a `git cat-file --batch` header: `<object> <type> <size>`, or `<name> missing`."""
    last = header.rsplit(" ", 1)[-1]
    return None if last == GIT_MISSING else int(last)


@deal.raises(ValueError)  # an answer not in git's batch form: git never gives one, and nothing can be read from it
@deal.ensure(lambda paths, out, result: set(result) <= set(paths))
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


@deal.ensure(lambda reading, texts, result: all(p in texts and reading.wants(p) for p in result))
def git_files(reading: Reading, texts: Mapping[RecordPath, FileText]) -> dict[RecordPath, FileText]:
    return {path: texts[path] for path in reading.chosen(texts)}


# ---- what was read -----------------------------------------------------------------------------------------------

def reading_of(files: Files) -> Reading:
    return Reading.of(files.get(RecordPath(SETTINGS_FILE)), Presence(any(_under(p, CONVENTIONAL_SOURCE) for p in files)))


@deal.ensure(lambda files, result: all(p in files and p.startswith(f"{DESIGN_DIR}/") for p in result.design))
def project_files(files: Files) -> ProjectFiles:
    design = {p: t for p, t in files.items() if p.startswith(DESIGN_DIR + "/") and p.endswith(DESIGN_SUFFIX)}
    return ProjectFiles(files.get(RecordPath(SETTINGS_FILE)), design, files.get(LOG_FILE))


def python_files(files: Files, ran: Sequence[ToolOutput] = ()) -> PythonFiles | None:
    """What the Python adapter reads, with what its tools printed, or None when there is no Python source."""
    reading = reading_of(files)
    sources = {p: t for p, t in files.items() if reading.is_source(p)}
    if not sources:
        return None
    return PythonFiles(sources, reading.source_roots, reading.settings.vendor,
                       {p: t for p, t in files.items() if reading.is_test(p)}, files.get(PYPROJECT),
                       {p: t for p, t in files.items() if reading.is_report(p)}, files.get(OBSERVED_FILE), tuple(ran))


@deal.ensure(lambda files, result: not result or python_files(files) is not None)  # no source, nothing to run
def tool_runs(files: Files) -> tuple[ToolRun, ...]:
    """The linters and type checkers to run before the checks: only those that a rule in the record needs."""
    if python_files(files) is None:
        return ()
    record, _ = read_record(project_files(files).design)  # what cannot be read is reported when the record is checked
    reading = reading_of(files)
    return tools.runs(reading.settings, reading.source_roots, wanted(kinds_named(record)))


def source_roots(files: Files) -> tuple[str, ...]:
    """Where the project's Python source is."""
    return reading_of(files).source_roots


def test_files(files: Files) -> dict[RecordPath, str]:
    reading = reading_of(files)
    return {p: t for p, t in files.items() if reading.is_test(p)}


@deal.ensure(lambda files, ran=(), *, result: (result is None) == (python_files(files) is None))  # no source, no model
def code_model(files: Files, ran: Sequence[ToolOutput] = ()) -> CodeModel | None:
    python = python_files(files, ran)
    return read_python(python) if python is not None else None


def _custom_sources(files: Files) -> dict[RecordPath, FileText]:
    return {path: text for path, text in sorted(files.items()) if is_custom_check(path)}


def _with_effects(files: Files) -> tuple[Finding, ...]:
    """A break for each effect a file of custom checks has. A check that reads a file or the clock could give two
    runs of the same project different findings, so such a file is refused whole, and never run (DESIGN2 §4.2)."""
    sources = _custom_sources(files)
    if not sources:
        return ()
    read = read_python(PythonFiles(sources, (RecordPath(CHECKS_DIR),), (), {}, None, {}))
    return tuple(finding(Result.BREAKS, CUSTOM_CHECKS, e.span.path, e.span,
                         f"a custom check may not have effects, and {e.at} is {phrase(e.effect)} (through {e.via}): "
                         f"a check reads only what zigdag hands it, so that two runs give the same findings")
                 for e in read.effects)


def _compiled(files: Files) -> tuple[tuple[Loading, ...], tuple[Finding, ...]]:
    """Each file of custom checks that may be run, and a break for each that may not: one in which zigdag finds an
    effect, or one that is not Python."""
    refused = _with_effects(files)
    loadings, problems = [], [*refused]
    for path, text in _custom_sources(files).items():
        if path in {f.about for f in refused}:
            continue
        try:
            loadings.append(Loading(path, CompiledCode(compile(text, path, _WHOLE_FILE)), fresh_names(path)))
        except (SyntaxError, ValueError) as e:  # ValueError: the text holds a null character
            problems.append(finding(Result.BREAKS, CUSTOM_CHECKS, Subject(path), Span(path, Line(1), Column(1)),
                                    f"{path} is not Python that can be read: {e}"))
    return tuple(loadings), tuple(problems)


@deal.ensure(lambda files, result: all(is_custom_check(loading.path) for loading in result))
def loadings(files: Files) -> tuple[Loading, ...]:
    """The files of custom checks to run."""
    return _compiled(files)[0]


@deal.ensure(lambda files, ran=(), loaded=(), *, result: (result.code is None) == (python_files(files) is None))
def analysis(files: Files, ran: Sequence[ToolOutput] = (), loaded: Sequence[Loaded] = ()) -> Analysis:
    """The analysis of the files, of what the tools that tool_runs chose printed, and with the custom checks that
    were loaded; a revision read from git has no tools run on it, so the rules that need them wait there."""
    return analyse(project_files(files), code_model(files, ran), read_checks(loaded, _compiled(files)[1]))


# ---- reports -----------------------------------------------------------------------------------------------------

@deal.post(lambda result: "\n" not in result)
def line(f: Finding) -> str:
    """One finding on one line, as ty writes a diagnostic: where, what kind under which rule, and what it says. A
    question ends with the handle it is answered by."""
    tag = f"{_TAGS[f.result]}[{f.rule}]"
    where = f"{f.span}: {tag} {f.about}:" if f.span is not None else f"{f.about}: {tag}"
    handle = f" [{f.digest}]" if f.result is Result.QUESTION else ""
    return f"{where} {f.say}{handle}"


def report_file(direction: Direction) -> RecordPath:
    return RecordPath(f"{REPORTS}/{direction.value}.txt")


@deal.ensure(lambda s, result: result.endswith(f"{s.direction.value}: {s.verdict}"))
def _in_full(s: Standing) -> str:
    """One direction as a linter reports a run: its findings, breaks first, then its verdict."""
    return "\n".join([*(line(f) for r in COUNTED for f in s.findings if f.result is r),
                      f"{s.direction.value}: {s.verdict}"])


def _totals(standings: tuple[Standing, ...]) -> str:
    every = [f for s in standings for f in s.findings]
    return ", ".join(counted(r, Count(sum(f.result is r for f in every))) for r in COUNTED)


@deal.ensure(lambda standings, result: all(s.direction.value in result[0] for s in standings))
@deal.ensure(lambda standings, result: [w.path for w in result[1]] == [report_file(s.direction) for s in standings])
def summary(standings: tuple[Standing, ...]) -> tuple[Shown, tuple[Write, ...]]:
    """A table of the directions: each one's name, how it stands, and the file its findings are in, or the debt a
    pass leaves out. Why a direction was not checked is left to its file, to keep the table short. A direction's breaks
    are listed under it all the same, since a run that breaks must say why where it is read, such as a build's log.
    Each direction's file is written in full."""
    names = max(len(d.value) for d in Direction) + COLUMN_GAP
    statuses = max(len(s.status) for s in standings) + COLUMN_GAP
    under = " " * names  # what is listed under a direction starts where its status does
    out: list[str] = []
    for s in standings:
        path = report_file(s.direction)
        breaks = [f for f in s.findings if f.result is Result.BREAKS]
        detail = path if s.findings else "; ".join(s.brief) if s.passed else ""
        out.append(f"{s.direction.value:<{names}}{s.status:<{statuses}}{detail}".rstrip())
        out += [f"{under}{line(f)}" for f in breaks[:BREAKS_SHOWN]]
        if len(breaks) > BREAKS_SHOWN:
            out.append(f"{under}and {len(breaks) - BREAKS_SHOWN} more breaks in {path}")
    held_back = any(f.result is not Result.BREAKS for s in standings for f in s.findings)
    out += ["", _totals(standings), *([f"To see every finding: {FULL}"] if held_back else [])]
    return Shown("\n".join(out)), tuple(Write(report_file(s.direction), _in_full(s) + LINE_END) for s in standings)


@deal.ensure(lambda standings, result: all(f"{s.direction.value}: {s.verdict}" in result for s in standings))
def render_report(standings: tuple[Standing, ...]) -> str:
    """Each direction as a linter reports a run: its findings, breaks first, then whether all its checks passed;
    then the counts over every direction."""
    out: list[str] = []
    for s in standings:
        if s.findings and out and out[-1]:
            out.append("")
        out.append(_in_full(s))
        if s.findings:
            out.append("")
    return "\n".join([*out, *([""] if out and out[-1] else []), _totals(standings)])


@deal.ensure(lambda report, standings, result: len(json.loads(result)) == len(report.findings))
def report_json(report: Report, standings: tuple[Standing, ...]) -> str:
    """Every finding in the report's order, with the direction it is about."""
    direction = {f: s.direction for s in standings for f in s.findings}
    return json.dumps([
        {"result": f.result.value, "rule": f.rule, "about": f.about, "say": f.say, "digest": f.digest,
         "direction": direction[f].value,
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
        """What the change brought; a rule the base could not check had no chance to find anything there, so what it
        finds now is not counted as new."""
        unchecked = self.before.unchecked
        return [f for f in new_findings(self.before.report, self.after.report) if f.rule not in unchecked]


@deal.ensure(lambda base, result: result == (() if base is None else (base,)))
def revisions(base: Revision | None) -> tuple[Revision, ...]:
    """The revisions to read: the base, when there is one."""
    return (base,) if base is not None else ()


@deal.ensure(lambda names, base, result: result == (() if names else revisions(base)))  # names need no base
def revisions_to_choose(names: Sequence[Subject], base: Revision | None) -> tuple[Revision, ...]:
    """The revisions to read to choose entries: the base, when entries are chosen by what changed since it."""
    return () if names else revisions(base)


@deal.ensure(lambda base, error, result: result.exit == REFUSED and _changes_nothing(result))
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


def _threads_note(a: Analysis) -> tuple[Shown, ...]:
    open_threads = sum(1 for t in a.log.threads if t.open)
    threads = "1 open thread" if open_threads == 1 else f"{open_threads} open threads"
    return (Shown(f"{threads} in the log: zigdag findings"),) if open_threads else ()


def _reports_only(outcome: Outcome) -> bool:
    """Whether carrying an outcome out writes only the report's files, and adds nothing to the log."""
    return not outcome.log and all(w.path.startswith(f"{REPORTS}/") for w in outcome.writes)


@deal.ensure(lambda a, earlier, base, result: _reports_only(result) and result.exit in (OK, FOUND))
def check(a: Analysis, earlier: Sequence[Analysis], base: Revision | None) -> Outcome:
    """Each direction in a line, its findings in its file."""
    report = _gated(a, earlier, base)
    shown, writes = summary(standings(a, report))
    return Outcome(OK if report.passes else FOUND, (shown, *_threads_note(a)), writes=writes)


@deal.ensure(lambda a, earlier, base, result: _changes_nothing(result) and result.exit in (OK, FOUND))
def check_full(a: Analysis, earlier: Sequence[Analysis], base: Revision | None) -> Outcome:
    """Every finding of every direction, printed."""
    report = _gated(a, earlier, base)
    return Outcome(OK if report.passes else FOUND, (Shown(render_report(standings(a, report))), *_threads_note(a)))


@deal.ensure(lambda a, earlier, base, result: _changes_nothing(result) and result.exit in (OK, FOUND))
@deal.ensure(lambda a, earlier, base, result: len(json.loads(result.out[0])) >= len(a.report.findings))
def check_json(a: Analysis, earlier: Sequence[Analysis], base: Revision | None) -> Outcome:
    report = _gated(a, earlier, base)
    return Outcome(OK if report.passes else FOUND, (Shown(report_json(report, standings(a, report))),))


PARTS_SHOWN = 12  # parts of the project in the table of costs; the rest are counted


@dataclass(frozen=True)
class ProfiledRun:
    """How the tests are run under the profiler, or why they cannot be."""

    refused: bool
    refusal: Outcome
    starting: Outcome  # what is said before the run, which takes a while
    command: tuple[Argument, ...]
    root: Path
    profile: Path  # where the profiler writes the profile
    before: Path  # where the profile from the run before is kept, to compare with


@deal.ensure(lambda a, root, extra, result: result.refused or PROFILE_FILE in result.command)
def profile(a: Analysis, root: ProjectRoot, extra: Sequence[Argument]) -> ProfiledRun:
    """The tests run once more, under the adapter's profiler, for zigdag stats (DESIGN2 §4.7)."""
    written, before = root / PROFILE_FILE, root / PROFILE_BEFORE
    if a.code is None:
        return ProfiledRun(True, refused("no code was read, so there is nothing to profile"), Outcome(), (), root,
                           written, before)
    command = profiled(a.settings, extra)
    starting = Outcome(out=(Shown(f"profiling the tests: {shlex.join(command)}"),))
    return ProfiledRun(False, Outcome(), starting, command, root, written, before)


NEW = "none"  # what a part cost in the run before, when it had no cost then


def _shown(c: Cost | None) -> tuple[str, str, str]:
    """A part's CPU time, its share of the run, and its memory, as the table shows them."""
    return (f"{c.seconds:.2f} s", f"{c.time:.0f}%", f"{c.allocated:.1f} MB") if c is not None else (NEW, NEW, NEW)


def _leaks(found: tuple[Suspect, ...]) -> list[str]:
    """The lines the profiler suspects of leaking, the likeliest first, or that it suspects none."""
    if not found:
        return ["no suspected memory leaks"]
    rows = [(f"{s.leak.span.path}:{s.leak.span.line}", s.part, f"{s.leak.likelihood:.0%} likely",
             f"growing {s.leak.growth:.2f} MB/s") for s in found]  # a whole line: scalene names no column
    return [f"suspected memory leaks, as {PROFILER} judges them:", *(f"  {r}" for r in _table(rows))]


def _change(now: str, before: str) -> str:
    return now if before == now else f"{before} → {now}"


def _table(rows: list[tuple[str, ...]]) -> list[str]:
    """Rows in columns as wide as their widest cell."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return [(" " * COLUMN_GAP).join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in rows]


@deal.ensure(lambda a, root, now, before, result: _changes_nothing(result))
def costs(a: Analysis, root: ProjectRoot, now: FileText | None, before: FileText | None) -> Outcome:
    """Where the time and memory of the latest profiled run went, by design part, beside the run before it."""
    if a.code is None or a.tree is None:
        return refused("no code was read, so a profile cannot be told by design part")
    if now is None:
        return refused("there is no profile yet: run zigdag profile")
    latest = read_profile(now, root)
    if isinstance(latest, Unreadable):
        return refused(f"{PROFILE_FILE} cannot be read: {latest.say}")
    earlier = read_profile(before, root) if before is not None else None
    earlier = earlier if isinstance(earlier, Profile) else None  # one that cannot be read compares with nothing
    tests = a.settings.test_roots
    parts = by_part(latest, a.code, a.tree, tests)
    head = f"the tests ran for {latest.elapsed:.1f} s, holding at most {latest.peak:.0f} MB at once"
    if earlier is not None:
        head += f"; the run before, {earlier.elapsed:.1f} s and {earlier.peak:.0f} MB"
    rows: list[tuple[str, ...]] = [("part", "CPU time", "share", "memory allocated")]
    for c in compared(parts, by_part(earlier, a.code, a.tree, tests) if earlier is not None else ())[:PARTS_SHOWN]:
        now_, then = _shown(c.now), _shown(c.before)
        rows.append((c.now.part, *(_change(n, b) if earlier is not None else n for n, b in zip(now_, then))))
    more = len(parts) - PARTS_SHOWN
    found = suspects(latest, a.code, a.tree, tests)
    return Outcome(out=(Shown("\n".join([head, "", *_table(rows), *([f"and {more} more parts"] if more > 0 else []),
                                         "", *_leaks(found), "", full_profile(a.settings)])),))


@deal.ensure(lambda run, written, returncode, a, now, before, result: _changes_nothing(result) or result.exit == REFUSED)
@deal.ensure(lambda run, written, returncode, a, now, before, result: written is Presence.PRESENT
             or result.exit == REFUSED)
def profiled_run(run: ProfiledRun, written: Presence, returncode: ExitCode, a: Analysis, now: FileText | None,
                 before: FileText | None) -> Outcome:
    shown = shlex.join(run.command)
    if written is Presence.ABSENT:
        return refused(f"the tests ran under the profiler ({shown} exited {returncode}), but it wrote no profile: "
                       f"is scalene installed where the tests run?")
    table = costs(a, ProjectRoot(run.root), now, before)
    return Outcome(OK if returncode == 0 else FOUND, (*table.out, Shown(f"tests: {shown} exited {returncode}")))


@dataclass(frozen=True)
class WatchedRun:
    """How the tests are run under the watcher, or why they cannot be."""

    refused: bool
    refusal: Outcome
    watch: FileText  # the watch plan, as the watcher reads it
    observed: FilePath  # where the watcher writes what it saw
    command: tuple[Argument, ...]
    root: ProjectRoot
    environment: Environment


def _kept(files: Files) -> LastRun | None:
    """The mutants the watcher kept as it judged them, or None when there is no such file or it cannot be read."""
    kept = LastRun.from_text(files[CARRIED_FILE]) if CARRIED_FILE in files else None
    return kept if isinstance(kept, LastRun) else None


@deal.ensure(lambda files, result: (kept := _kept(files)) is None or all(m in result.mutants for m in kept.mutants))
def carried(files: Files) -> LastRun:
    """The mutants to carry over: those of the last finished run, with those that a later run judged before it was
    stopped taking their functions' place. A file that cannot be read carries nothing."""
    last = Recording.from_text(files[OBSERVED_FILE]) if OBSERVED_FILE in files else None
    finished = last.for_next_run if isinstance(last, Recording) else LastRun()
    kept = _kept(files)
    return finished.merged(kept) if kept is not None else finished


@deal.ensure(lambda a, files, root, extra, environment, result: result.refused or (
    WATCHER in result.command and PLAN_VARIABLE in result.environment))  # the watcher is always told its plan
def test(a: Analysis, files: Files, root: ProjectRoot, extra: Sequence[Argument],
         environment: Environment) -> WatchedRun:
    watch = watch_plan(a, test_files(files), files)
    observed = root / OBSERVED_FILE
    if watch is None:
        return WatchedRun(True, refused("no code was read, so there is nothing to watch"), "", observed, (), root, {})
    command = (*shlex.split(a.settings.test_command or DEFAULT_TEST_COMMAND), PLUGIN_OPTION, WATCHER,
               f"{REPORT_OPTION}={DEFAULT_REPORT}", *extra)
    return WatchedRun(False, Outcome(), replace(watch, last_run=carried(files)).to_text(), observed, command, root,
                      {**environment, PLAN_VARIABLE: str(root / PLAN_FILE)})


@deal.ensure(lambda run, seen, returncode, after, result: _reports_only(result))
@deal.ensure(lambda run, seen, returncode, after, result: seen is Presence.PRESENT or result.exit == REFUSED)
def tested(run: WatchedRun, seen: Presence, returncode: ExitCode, after: Analysis) -> Outcome:
    shown = shlex.join(run.command)
    if seen is Presence.ABSENT:
        return refused(f"the tests ran ({shown} exited {returncode}), but the watcher saw nothing: the tests' Python "
                       f"must be able to import zigdag")
    report = after.report
    summed, writes = summary(standings(after, report))
    return Outcome(OK if report.passes and returncode == OK else FOUND, (summed, f"tests: {shown} exited {returncode}"),
                   writes=writes)


def _not_ready(report: Report, returncode: ExitCode, unformatted: Count, brought: Sequence[Finding],
               base: Revision | None) -> tuple[Say, ...]:
    """Each reason a change is not ready, in the order to deal with them; none when it is."""
    counts = {result: Count(len(report.of_result(result))) for result in Result}
    reasons = [
        (returncode != OK, f"the tests failed (they exited {returncode})"),
        (counts[Result.BREAKS], f"{counted(Result.BREAKS, counts[Result.BREAKS])}"),
        (counts[Result.QUESTION], f"{counted(Result.QUESTION, counts[Result.QUESTION])} left open: answer each with "
                                  f"zigdag answer"),
        (counts[Result.OUT_OF_DATE], f"{counted(Result.OUT_OF_DATE, counts[Result.OUT_OF_DATE])}, after the tests "
                                     f"just ran: see {FULL}"),
        (unformatted, ("1 design file is not in its layout" if unformatted == 1 else
                       f"{unformatted} design files are not in their layout") + ": zigdag fmt"),
        (brought, f"the change adds {counted(Result.TODO, Count(len(brought)))} since {base}: old gaps are debt, "
                  f"and new ones are not let in"),
    ]
    return tuple(Say(say) for holds, say in reasons if holds)


@deal.ensure(lambda run, seen, returncode, after, earlier, base, files, result: _reports_only(result))
@deal.ensure(lambda run, seen, returncode, after, earlier, base, files, result:
             result.exit != OK or (returncode == OK and _gated(after, earlier, base).passes))  # never yes on a no
def ready(run: WatchedRun, seen: Presence, returncode: ExitCode, after: Analysis, earlier: Sequence[Analysis],
          base: Revision | None, files: Files) -> Outcome:
    """One answer to "is this change ready?", after the tests ran under the watcher. Yes only when the tests pass,
    nothing breaks, no question is open, no result is out of date, the design files are in their layout and, when
    there is a base to compare with, the change adds nothing to do."""
    shown = shlex.join(run.command)
    if seen is Presence.ABSENT:
        return refused(f"the tests ran ({shown} exited {returncode}), but the watcher saw nothing: the tests' Python "
                       f"must be able to import zigdag")
    report = _gated(after, earlier, base)
    summed, writes = summary(standings(after, report))
    brought = [f for before in earlier for f in Changeset.of(base or Revision(""), before, after).brought
               if f.result is Result.TODO]
    reasons = _not_ready(report, returncode, Count(len(Formatted.of(files).changed)), brought, base)
    verdict = READY if not reasons else "\n".join([NOT_READY, *(f"  {reason}" for reason in reasons)])
    return Outcome(FOUND if reasons else OK, (summed, f"tests: {shown} exited {returncode}", "", verdict),
                   writes=writes)


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


@deal.ensure(lambda files, result: not result.log and all(w.path in files for w in result.writes))
@deal.ensure(lambda files, result: all(format_text(w.path, w.text)[0] == w.text for w in result.writes))  # settled
def fmt(files: Files) -> Outcome:
    """Each design file rewritten in its canonical layout."""
    done = Formatted.of(files)
    return Outcome(FOUND if done.unreadable else OK, (*done.problems, done.summary("reformatted")), writes=done.changed)


@deal.ensure(lambda files, result: _changes_nothing(result))
def fmt_check(files: Files) -> Outcome:
    """The design files that are not in their canonical layout, changing nothing."""
    done = Formatted.of(files)
    return Outcome(FOUND if done.unreadable or done.changed else OK, (*done.problems, done.summary("would reformat")))


@deal.ensure(lambda a, at, kind, on, say, by, evidence, result: result.exit != REFUSED or _changes_nothing(result))
@deal.ensure(lambda a, at, kind, on, say, by, evidence, result: result.exit == REFUSED or (
    len(result.log) == 1 and not result.writes))  # one event, and nothing else
def raise_(a: Analysis, at: lg.Timestamp, kind: lg.Kind, on: Subject, say: Say, by: Actor, evidence: Written | None) -> Outcome:
    if on not in a.known_names:
        return refused(f'nothing in the record is named "{on}"')
    event = lg.raised(at, lg.Actor(by), lg.Kind(kind), on, say, evidence)
    thread = lg.thread_id(json.loads(event)["at"], lg.Actor(by), on, say)
    if a.log.thread(thread) is not None:
        return refused("that was already raised")
    return Outcome(out=(f"raised {thread}",), log=(event,))


@deal.ensure(lambda a, at, ref, answer_, say, by, countermeasure, result: result.exit != REFUSED or _changes_nothing(result))
@deal.ensure(lambda a, at, ref, answer_, say, by, countermeasure, result: result.exit == REFUSED or (
    len(result.log) == 1 and not result.writes))
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


@deal.ensure(lambda a, result: _changes_nothing(result) and result.out[-1].endswith("open questions"))
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


@deal.ensure(lambda a, name, target, result: _changes_nothing(result) and len(result.out) == 1)
def view(a: Analysis, name: View, target: Written | None) -> Outcome:
    match name:
        case View.SHOW:
            return Outcome(out=(views.show(a, FrName(target) if target else None),))
        case View.DATA:
            return Outcome(out=(views.data(a, FrName(target) if target else None),))
        case View.CONTEXT:
            return Outcome(out=(views.context(a, target or Written("")),))
    return Outcome(out=(views.next_steps(a),))


@deal.ensure(lambda a, result: _changes_nothing(result) and result.exit == OK)
def checks(a: Analysis) -> Outcome:
    """Every rule there is, with the project's own among them."""
    return Outcome(out=(views.rules(a.settings).rstrip(),))


@deal.ensure(lambda files, result: not project_files(files).design or result.exit == REFUSED)  # never over a record
@deal.ensure(lambda files, result: result.exit != REFUSED or _changes_nothing(result))
def init(files: Files) -> Outcome:
    """The code recorded as it is, when there is no record yet."""
    if project_files(files).design:
        return refused("design/ already has a record; use --force to replace its functional.yaml and process.yaml")
    return init_forced(files)


@deal.ensure(lambda files, result: result.exit != REFUSED or _changes_nothing(result))
@deal.ensure(lambda files, result: result.exit == REFUSED or (bool(result.writes) and not result.log))
def init_forced(files: Files) -> Outcome:
    """The code recorded as it is: an FR per package and module, its effects and dependencies, its known breaks."""
    return _recorded(files, frozenset(), ())


@deal.ensure(lambda files, folder, result: not project_files(files).design or result.exit == REFUSED)
@deal.ensure(lambda files, folder, result: result.exit != REFUSED or _changes_nothing(result))
@deal.ensure(lambda files, folder, result: result.exit == REFUSED or (
    {RecordPath(SETTINGS_FILE), CUSTOMER} <= {w.path for w in result.writes} | set(files) and not result.log))
def init_default(files: Files, folder: FolderName) -> Outcome:
    """A default setup: the settings, a place for the jobs, and every rule a project can tune spelled out with its
    default values. Existing code is recorded as it is; with no code yet, the root FR is named after the folder."""
    if project_files(files).design:
        return refused("design/ already has a record: a default setup is for a project that has none")
    template = () if CUSTOMER in files else (Write(CUSTOMER, CUSTOMER_TEMPLATE),)
    if code_model(files) is not None:
        return _recorded(files, tunable(), template)
    root = fr_name(Written(folder.lower().replace("-", "_")))
    if root is None or "." in root:
        return refused(f"there is no code yet, and the folder's name, {folder!r}, cannot name the root FR: an FR "
                       f"name is lowercase letters, digits and underscores. Rename the folder, or write the first "
                       f"package and run this again")
    writes = tuple(Write(path, text) for path, text in starter(root, (RecordPath(CONVENTIONAL_SOURCE),)).items())
    return Outcome(out=("\n".join([
        *(f"wrote {w.path}" for w in writes),
        f"next: write the jobs in design/customer.yaml and the function of {root} in design/functional.yaml; "
        f"put the code in {CONVENTIONAL_SOURCE}/{root}/"]),), writes=writes)


def _recorded(files: Files, spelled: frozenset[RuleId], also: tuple[Write, ...]) -> Outcome:
    """The code recorded as it is, with what else the command writes beside the record."""
    read = project_files(files)
    code = code_model(files)
    if code is None:
        return refused("no Python code found to record")
    writes: list[Write] = []
    if read.settings is None:
        new_settings = settings_text(source_roots(files))
        writes.append(Write(RecordPath(SETTINGS_FILE), new_settings))
        read = project_files({**files, RecordPath(SETTINGS_FILE): new_settings})
    written, left = init_record(read, code, spelled)
    if not written:
        return refused("; ".join(left))
    writes += [*(Write(path, text) for path, text in written.items()), *also]
    lines = [f"wrote {w.path}" for w in writes]
    if left:
        lines += ["these could not be recorded as debt, and need a decision:", *(f"  {x}" for x in left)]
    return Outcome(out=("\n".join([*lines, "next: write the jobs in design/customer.yaml, then each FR's function "
                                           "(zigdag next)"]),), writes=tuple(writes))


@deal.ensure(lambda base, before, after, result: _changes_nothing(result))
def review(base: Revision, before: Analysis, after: Analysis) -> Outcome:
    changes = Changeset.of(base, before, after)
    gates, brought = changes.gates, changes.brought
    shown = render(base, list(changes.changes), after.log, after.people, gates, brought)
    return Outcome(FOUND if gates or any(f.result is Result.BREAKS for f in brought) else OK, (shown,))


@deal.ensure(lambda a, earlier, names, base, by, at, result: result.exit != REFUSED or _changes_nothing(result) and not result.writes)
def approve(a: Analysis, earlier: Sequence[Analysis], names: Sequence[Subject], base: Revision | None, by: Actor,
            at: lg.Timestamp) -> Outcome:
    chosen = _chosen(a, earlier, names, base)
    if chosen.refusal is not None:
        return chosen.refusal
    events = tuple(lg.approved(at, lg.Actor(by), entry.name, entry.digest) for entry in chosen.entries)
    note = "" if by in a.people else f" ({by} is not in [settings] people, so this approval is an agent's)"
    return Outcome(out=(f"approved {len(chosen.entries)} entries{note}",), log=events)


@deal.ensure(lambda a, earlier, names, base, result: result.exit != REFUSED or _changes_nothing(result) and not result.log)
@deal.ensure(lambda a, earlier, names, base, result: result.exit == REFUSED or [w.path for w in result.writes] == [
    CRITIQUE_REQUEST])  # the request, and nothing else
def critique_request(a: Analysis, earlier: Sequence[Analysis], names: Sequence[Subject], base: Revision | None) -> Outcome:
    chosen = _chosen(a, earlier, names, base)
    if chosen.refusal is not None:
        return chosen.refusal
    text, asked = request(a.record, a.log, list(chosen.entries))
    return Outcome(out=(f"wrote {CRITIQUE_REQUEST}: {asked} entries with questions to answer, rubric {RUBRIC_VERSION}\n"
                        "give that file, and nothing else, to a fresh critic; then: zigdag critique --record "
                        "<answer.json> --by <critic>",), writes=(Write(CRITIQUE_REQUEST, text),))


@deal.ensure(lambda a, answer_text, answer_path, by, at, result: result.exit != REFUSED or _changes_nothing(result) and not result.writes)
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


@deal.ensure(lambda a, files, old, new, result: result.exit != REFUSED or _changes_nothing(result) and not result.log)  # the log is history
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


@deal.ensure(lambda product, command, settings, result: result.exit != REFUSED or _changes_nothing(result) and not result.log)
@deal.ensure(lambda product, command, settings, result: result.exit == REFUSED or any(
    w.path == claude.SETTINGS for w in result.writes))  # installed means the hooks are registered
def agent_install(product: Written, command: ShellCommand, settings: FileText | None) -> Outcome:
    if product != claude.PRODUCT:
        return refused(f"unknown agent {product!r}; known: {claude.PRODUCT}")
    merged = claude.merged_settings(settings, command)
    if merged is None:
        return refused(f"{claude.SETTINGS} is not a JSON object: fix it, then install again")
    skills = tuple(Write(RecordPath(path), text) for path, text in claude.skill_files().items())
    return Outcome(out=(f"installed {len(skills)} skills and two hooks for {product}; restart the agent to load them",),
                   writes=(*skills, Write(RecordPath(claude.SETTINGS), merged)))


@deal.ensure(lambda a, event, payload, result: _changes_nothing(result)
             and result.exit in (OK, claude.FEEDBACK_EXIT))  # a hook only speaks
def hook(a: Analysis, event: claude.HookEvent, payload: claude.Payload) -> Outcome:
    if event == claude.SESSION_START:
        return Outcome(out=(claude.session_text(views.show(a), views.next_steps(a),
                                                sum(1 for t in a.log.threads if t.open)),))
    shown = a.report.of_result(Result.BREAKS)[:HOOK_FINDINGS]
    if not shown or claude.told_already(payload):
        return Outcome()
    return Outcome(ExitCode(claude.FEEDBACK_EXIT), err=("\n".join(["zigdag check found:", *map(line, shown)]),))


# ---- which command -----------------------------------------------------------------------------------------------

class Command(enum.Enum):
    CHECK = "check"
    CHECK_JSON = "check --json"
    CHECK_FULL = "check --full"
    TEST = "test"
    PROFILE = "profile"
    STATS = "stats"
    FMT = "fmt"
    FMT_CHECK = "fmt --check"
    RAISE = "raise"
    ANSWER = "answer"
    FINDINGS = "findings"
    VIEW = "view"  # show, context, next, and show --data
    READY = "ready"
    CHECKS = "checks"
    INIT = "init"
    INIT_FORCED = "init --force"
    INIT_DEFAULT = "init --default"
    REVIEW = "review"
    APPROVE = "approve"
    CRITIQUE_REQUEST = "critique --request"
    CRITIQUE_RECORD = "critique --record"
    RENAME = "rename"
    AGENT = "agent"
    HOOK_SESSION = "hook session-start"
    HOOK_TURN = "hook turn-end"  # reads from standard input whether the agent was already told
    REFUSED = "refused"


_COMMANDS = {c.value: c for c in Command}
_PASSING_ON = frozenset({Command.TEST.value, Command.PROFILE.value, Command.READY.value})  # commands whose other arguments go to the tests
_VIEWS = frozenset({View.SHOW.value, View.CONTEXT.value, View.NEXT.value})
# the commands a flag picks, by (the flag, the command), first match first: JSON already holds every finding
_CHOSEN_BY_FLAG = {"check": (("json", Command.CHECK_JSON), ("full", Command.CHECK_FULL)),
                   "fmt": (("check", Command.FMT_CHECK),), "init": (("default", Command.INIT_DEFAULT), ("force", Command.INIT_FORCED))}


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
        return Command.HOOK_TURN if args.event == claude.TURN_END else Command.HOOK_SESSION
    flagged = next((command for flag, command in _CHOSEN_BY_FLAG.get(args.command, ()) if getattr(args, flag)), None)
    if flagged is not None:
        return flagged
    return _COMMANDS.get(args.command, Command.REFUSED)


@deal.pre(lambda args, passed_on, cwd: hasattr(args, "command") and hasattr(args, "project"))  # zigdag's own parser
@deal.ensure(lambda args, passed_on, cwd, result: result.passed_on == tuple(passed_on))
@deal.ensure(lambda args, passed_on, cwd, result: not result.rejected or result.command is not Command.TEST)
def route(args: argparse.Namespace, passed_on: Sequence[str], cwd: Path) -> Route:
    """The command the arguments ask for. The project is where --project says, or here."""
    rejected = bool(passed_on) and args.command not in _PASSING_ON
    command = _command(args)
    refusal = refused("--record needs --by") if args.command == "critique" else refused(
        f"unknown command {args.command!r}")
    view = View.DATA if args.command == View.SHOW.value and args.data else View(args.command) if (
        args.command in _VIEWS) else View.NEXT
    target = getattr(args, "name", None) or getattr(args, "target", None)
    return Route(command, cwd / (args.project or cwd), args, tuple(passed_on), rejected,
                 f"unrecognized arguments: {' '.join(passed_on)}", refusal, view, target)

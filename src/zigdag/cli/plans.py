"""The command line's decisions, made without effects (DESIGN2 §4.1, planned-effects): which files to read, and what
each command does with what was read, down to the files it writes, the lines it adds to the log, what it prints and
the code it exits with. The rest of the command line only carries these plans out.
"""

from __future__ import annotations

import argparse
import enum
import json
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NewType

import deal

from zigdag.adapters.adapter import Adapter, Files, Presence, Profiling
from zigdag.adapters.known import adapters as known_adapters
from zigdag.adapters.python import PythonFiles, read_python
from zigdag.adapters.python.adapter import CONVENTIONAL_SOURCE, PythonAdapter
from zigdag.adapters.python.adapter import SUFFIX as PYTHON_SUFFIX
from zigdag.adapters.python.observed import Recording
from zigdag.adapters.tools import ToolOutput, ToolRun
from zigdag.agents import claude
from zigdag.core import log as lg
from zigdag.core import views
from zigdag.core.checks.directions import COUNTED, Standing, counted, standings
from zigdag.core.codec import Unreadable
from zigdag.core.profile import Cost, Profile, Suspect, by_part, compared, suspects
from zigdag.core.kinds.registry import Direction
from zigdag.core.checks.evidence import check_changed
from zigdag.core.checks.gates import THE_CHANGE, check_gates
from zigdag.core.checks.part_rules import PartBranch, check_part
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
from zigdag.core.work import NOT_WAITING, Answer, Step, Taken, Waiting, asked, delta, next_step, unsettled, waiting
from zigdag.core.watch import plan as watch_plan
from zigdag.core.code import CodeModel, ToolName, joined
from zigdag.core.findings import Finding, RecordPath, Report, Result, Span, finding
from zigdag.core.log import GIT_ATTRIBUTES, LOG_FILE
from zigdag.core.measures import Count
from zigdag.core.names import PART_BRANCHES, BranchName, FolderName, FrName, RuleId, branch_of, fr_name, part_built_on
from zigdag.core.checks.custom import CHECKS_DIR, CUSTOM_CHECKS, CompiledCode, Loaded, Loading, fresh_names, read_checks
from zigdag.core.measures import Column, Line
from zigdag.core.effects import phrase
from zigdag.core.findings import Subject
from zigdag.core.log import Actor, EventLine
from zigdag.core.names import Argument, FilePath, ProjectRoot, Revision, ShellCommand
from zigdag.core.texts import FileText, Say, Shown, Written

ExitCode = NewType("ExitCode", int)
OK, FOUND, REFUSED = ExitCode(0), ExitCode(1), ExitCode(2)  # nothing wrong; something breaks or would change; refused

GitInput = NewType("GitInput", bytes)  # what git is asked, on its standard input
GitOutput = NewType("GitOutput", bytes)  # what git answers, on its standard output or error
Environment = NewType("Environment", dict[str, str])  # the environment variables, read once by the shell


class View(enum.Enum):
    SHOW = "show"
    DATA = "data"  # show --data
    CONTEXT = "context"
    NEXT = "next"


class GitError(Exception):
    """A git revision could not be read."""

_WHOLE_FILE = "exec"  # how Python is told to compile a whole file, not one expression
SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__"})
HIDDEN_PREFIX = "."
DESIGN_DEPTHS = (2, 3)  # design/<domain>.yaml, and design/<domain>/<part>.yaml
ALWAYS_READ = frozenset({RecordPath(SETTINGS_FILE), LOG_FILE, OBSERVED_FILE, CARRIED_FILE})  # zigdag's own
GIT_MISSING = "missing"  # what `git cat-file --batch` says instead of a size for a path absent at the revision

UNION_MERGE = f"{lg.LOG_FILE} merge=union"
CRITIQUE_REQUEST = RecordPath(f"{WORK_DIR}/critique/request.json")
REPORTS = RecordPath(f"{WORK_DIR}/check")  # each direction's findings in full, rewritten by every check
BREAKS_SHOWN = 10  # breaks of a direction shown under it; the rest are in its file
COLUMN_GAP = 2  # spaces between the columns of the summary
READY = "ready: yes"
NOT_READY = "ready: no"
BUILT = "built: waiting on"  # how ready answers for a part's branch that only waits for other parts to land
FULL = "zigdag check --full"  # what shows every finding, with what the last zigdag test saw
HOOK_FINDINGS = 15  # at most this many findings in what a hook tells an agent
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
    """What to read, once the settings are known: zigdag's own files, and what each adapter wants."""

    settings: Settings
    adapters: tuple[Adapter, ...]

    @staticmethod
    @deal.post(lambda result: len({adapter.name for adapter in result.adapters}) == len(result.adapters))
    def of(settings_text: FileText | None, conventional_source: Presence) -> Reading:
        settings, _ = read_settings(settings_text)
        return Reading(settings, known_adapters(settings, conventional_source))

    @property
    def folders(self) -> tuple[str, ...]:
        """The folders to walk; the whole project when an adapter's files may be anywhere in it."""
        wanted = tuple(folder for adapter in self.adapters for folder in adapter.folders)
        return (PROJECT_ROOT,) if PROJECT_ROOT in wanted else (DESIGN_DIR, WORK_DIR, *wanted)

    @property
    @deal.ensure(lambda self, result: ALWAYS_READ <= set(result) and result == sorted(result))
    def always(self) -> list[RecordPath]:
        """The single files read wherever they are, since no folder that is walked need hold them."""
        return sorted(ALWAYS_READ | {file for adapter in self.adapters for file in adapter.files})

    def wants(self, path: str) -> bool:
        parts = path.split("/")
        if not all(_visited(p) for p in parts[:-1]):
            return False
        is_design = parts[0] == DESIGN_DIR and path.endswith(DESIGN_SUFFIX) and len(parts) in DESIGN_DEPTHS
        return (path in ALWAYS_READ or is_design or is_custom_check(path)
                or any(adapter.wants(RecordPath(path)) for adapter in self.adapters))

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


@deal.ensure(lambda root, result: all(p.is_relative_to(root) for p in (result.settings, result.conventional_source)))
def on_disk(root: ProjectRoot) -> OnDisk:
    return OnDisk(root / SETTINGS_FILE, root / CONVENTIONAL_SOURCE)


@deal.ensure(lambda root, reading, result: len(result) == len(reading.always))
def always(root: ProjectRoot, reading: Reading) -> tuple[FilePath, ...]:
    """Where each file is that is read wherever the source is."""
    return tuple(root / name for name in reading.always)


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


@deal.ensure(lambda listing, settings, result: result.settings == read_settings(
    settings.get(RecordPath(SETTINGS_FILE)))[0])
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


# ---- the branch that is checked out ------------------------------------------------------------------------------

UPSTREAM = "@{upstream}"  # as git names the branch that the one checked out tracks
# What git is asked about the folder a command runs in, in the order checkout reads the answers. Each is asked
# whatever the others answer: one that cannot be answered, as on a branch that tracks none, says so by failing.
CHECKOUT_QUESTIONS: tuple[tuple[Argument, ...], ...] = (
    ("symbolic-ref", "--short", "-q", "HEAD"),  # the branch checked out
    ("rev-parse", "--abbrev-ref", UPSTREAM),  # the branch it tracks
    ("merge-base", "HEAD", UPSTREAM),  # where it left that branch
    ("rev-list", "--count", f"HEAD..{UPSTREAM}"),  # how many commits of that branch it does not have
    ("diff", "--name-only", "--relative", "--merge-base", UPSTREAM),  # the files that differ from where it left
    ("ls-files", "--others", "--exclude-standard"),  # and the files git does not know yet
)


@dataclass(frozen=True)
class GitAnswer:
    """What git answered one question with: the code it exited with, and what it printed."""

    exit: ExitCode
    out: GitOutput

    @property
    @deal.ensure(lambda self, result: self.exit == OK or result == ())  # a failure answers nothing
    def lines(self) -> tuple[Written, ...]:
        """What it printed, line by line; nothing, when git failed."""
        return tuple(Written(said) for said in self.out.decode(errors="surrogateescape").splitlines()) if (
            self.exit == OK) else ()


@dataclass(frozen=True)
class Checkout:
    """What git says of the folder a command runs in: the branch checked out there, and how it stands against the
    branch it tracks. A branch that tracks none has no line, no start and nothing touched."""

    branch: BranchName | None  # None when no branch is checked out
    line: BranchName | None  # the branch it tracks, which is the one it lands on
    start: Revision | None  # where it left the line
    behind: Count  # commits of the line it does not have
    touched: tuple[RecordPath, ...]  # files that are not as they were at the start, zigdag's own work files aside

    @property
    @deal.ensure(lambda self, result: result is None or (self.branch is not None and part_built_on(self.branch)
                                                         == result))
    def part(self) -> FrName | None:
        """The part this is the branch of; None for any other branch."""
        return part_built_on(self.branch) if self.branch is not None else None


def _made_by_tools(path: str) -> bool:
    """Whether a file is one that running the project leaves behind, and nobody wrote: zigdag's own work files, or
    one in a cache folder. A project's .gitignore usually hides these; one that does not must not make every run
    of the tests look like a change."""
    return _under(path, WORK_DIR) or not SKIPPED_FOLDERS.isdisjoint(path.split("/")[:-1])


@deal.pre(lambda answers: len(answers) == len(CHECKOUT_QUESTIONS))  # one answer for each question, in their order
@deal.ensure(lambda answers, result: list(result.touched) == sorted(set(result.touched))
             and not any(_made_by_tools(path) for path in result.touched))
def checkout(answers: Sequence[GitAnswer]) -> Checkout:
    """The answers to CHECKOUT_QUESTIONS, read."""
    head, line, start, behind, changed, unknown = (answer.lines for answer in answers)
    return Checkout(BranchName(head[0]) if head else None, BranchName(line[0]) if line else None,
                    Revision(start[0]) if start else None, Count(int(behind[0])) if behind else Count(0),
                    tuple(RecordPath(path) for path in sorted({*changed, *unknown}) if not _made_by_tools(path)))


@dataclass(frozen=True)
class OnPart:
    """The part's branch a command runs on, with the revision it left its line at; no branch, when the command runs
    on any other; or why the command cannot run there."""

    refused: bool
    refusal: Outcome
    branch: PartBranch | None = None
    starts: tuple[Revision, ...] = ()  # the revisions to read: where the branch left its line


@deal.ensure(lambda found, base, result: (result.branch is None) == (found.part is None or result.refused))
@deal.ensure(lambda found, base, result: len(result.starts) == (result.branch is not None))
def on_part(found: Checkout, base: Revision | None) -> OnPart:
    """What a command that judges a whole change is told of the branch it runs on. On a part's branch it needs to
    know where the change began, to tell what the change asks of the part, and what the branch lands on, to tell
    what the branch itself changed."""
    part = found.part
    if part is None:
        return OnPart(False, Outcome())
    if base is None:
        return OnPart(True, refused(f"this is the branch of {part}: say where the change it is part of began, with "
                                    f"--base"))
    if found.line is None or found.start is None:
        return OnPart(True, refused(f"the branch of {part} tracks no branch, so what it lands on cannot be told: "
                                    f"git branch --set-upstream-to=<the branch it lands on>"))
    return OnPart(False, Outcome(), PartBranch(part, found.line, found.behind, found.touched), (found.start,))


HEAD = Revision("HEAD")  # as git names the commit that is checked out
WORKTREE, CHECKED_OUT = "worktree ", "branch refs/heads/"  # how `git worktree list --porcelain` starts two of its lines
STATUS_PREFIX = 3  # `git status --porcelain` writes two letters and a space before each path
# What git is asked before work is handed out, in the order claims reads the answers.
WORK_QUESTIONS: tuple[tuple[Argument, ...], ...] = (
    ("for-each-ref", "--format=%(refname:short)", f"refs/heads/{PART_BRANCHES}"),  # the branches of parts
    ("worktree", "list", "--porcelain"),  # the folders branches are checked out in
    ("rev-parse", "--show-prefix"),  # where the project is inside its repository, and so inside each such folder
    ("status", "--porcelain", "--", DESIGN_DIR),  # what of the design is not committed
)


@dataclass(frozen=True)
class Claimed:
    """A part whose branch exists, and the project's folder where that branch is checked out, when it is."""

    part: FrName
    folder: FilePath | None


@dataclass(frozen=True)
class Claims:
    """What git says before work is handed out: the parts that are taken, and the design files that are not as the
    last commit has them."""

    parts: tuple[Claimed, ...]
    uncommitted: tuple[RecordPath, ...]  # design files, the log aside: it is added to all the time

    @property
    @deal.ensure(lambda self, result: len(result) == sum(c.folder is not None for c in self.parts))
    def folders(self) -> tuple[FilePath, ...]:
        """The folders to read, in the order of the parts that have one."""
        return tuple(c.folder for c in self.parts if c.folder is not None)


def _checked_out(listing: Sequence[str], prefix: str) -> dict[BranchName, FilePath]:
    """Each branch that is checked out in a folder, with the project's folder there."""
    out: dict[BranchName, FilePath] = {}
    folder = None
    for said in listing:
        if said.startswith(WORKTREE):
            folder = Path(said.removeprefix(WORKTREE)) / prefix
        elif said.startswith(CHECKED_OUT) and folder is not None:
            out[BranchName(said.removeprefix(CHECKED_OUT))] = FilePath(folder)
    return out


@deal.pre(lambda answers: len(answers) == len(WORK_QUESTIONS))
@deal.ensure(lambda answers, result: [c.part for c in result.parts] == sorted({c.part for c in result.parts}))
@deal.ensure(lambda answers, result: not any(path.endswith(LOG_FILE) for path in result.uncommitted))
def claims(answers: Sequence[GitAnswer]) -> Claims:
    """The answers to WORK_QUESTIONS, read."""
    branches, listing, prefix, status = (answer.lines for answer in answers)
    folders = _checked_out(listing, prefix[0] if prefix else "")
    parts = {part: Claimed(part, folders.get(BranchName(branch))) for branch in branches
             if (part := part_built_on(BranchName(branch))) is not None}
    changed = sorted({RecordPath(said[STATUS_PREFIX:]) for said in status})
    return Claims(tuple(parts[part] for part in sorted(parts)),
                  tuple(path for path in changed if not path.endswith(LOG_FILE)))


@deal.ensure(lambda files, log, result: result.get(LOG_FILE) == log and all(
    result[path] == text for path, text in files.items() if path != LOG_FILE))
def with_log(files: Files, log: FileText | None) -> Files:
    """A project's files with another log: what was committed, with the log as it is on disk, where what was just
    raised or answered is before anyone commits it."""
    kept = {path: text for path, text in files.items() if path != LOG_FILE}
    return {**kept, LOG_FILE: log} if log is not None else kept


# ---- what was read -----------------------------------------------------------------------------------------------

def _conventional(files: Files) -> Presence:
    return Presence(any(_under(p, CONVENTIONAL_SOURCE) for p in files))


@deal.ensure(lambda files, result: result.settings == read_settings(files.get(RecordPath(SETTINGS_FILE)))[0])
def reading_of(files: Files) -> Reading:
    return Reading.of(files.get(RecordPath(SETTINGS_FILE)), _conventional(files))


@deal.ensure(lambda files, result: all(p in files and p.startswith(f"{DESIGN_DIR}/") for p in result.design))
def project_files(files: Files) -> ProjectFiles:
    design = {p: t for p, t in files.items() if p.startswith(DESIGN_DIR + "/") and p.endswith(DESIGN_SUFFIX)}
    return ProjectFiles(files.get(RecordPath(SETTINGS_FILE)), design, files.get(LOG_FILE))


@deal.ensure(lambda files, result: len({run.tool for run in result}) == len(result))  # each tool once
def tool_runs(files: Files) -> tuple[ToolRun, ...]:
    """The linters and type checkers to run before the checks: only those that a rule in the record needs, and only
    those of an adapter that has code here."""
    record, _ = read_record(project_files(files).design)  # what cannot be read is reported when the record is checked
    needed = tuple(wanted(kinds_named(record)))
    return tuple(run for adapter in reading_of(files).adapters for run in adapter.tool_runs(files, needed))


@deal.ensure(lambda files, ran=(), *, result: result is None or bool(result.units) or bool(result.problems))
def code_model(files: Files, ran: Sequence[ToolOutput] = ()) -> CodeModel | None:
    """What every adapter read of the project, each given what its own tools printed, as one code model; None when
    no adapter found anything of its kind."""
    models = [model for adapter in reading_of(files).adapters
              if (model := adapter.read(files, [o for o in ran if o.tool.adapter == adapter.name])) is not None]
    return joined(models) if models else None


def test_files(files: Files) -> dict[RecordPath, str]:
    """The files of the project's tests, whatever they are written in."""
    roots = reading_of(files).settings.test_roots
    return {p: t for p, t in files.items() if any(_under(p, r) for r in roots)}


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


@deal.ensure(lambda files, ran=(), loaded=(), *, result: (result.code is None) == (code_model(files) is None))
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
    def unverified(self) -> list[Finding]:
        """The statements the change changed, whose tests it left as they were."""
        return list(check_changed(self.before.record, self.before.tests, self.after.record, self.after.tests,
                                  Revision(self.base)))

    @property
    def brought(self) -> list[Finding]:
        """What the change brought; a rule the base could not check had no chance to find anything there, so what it
        finds now is not counted as new."""
        unchecked = self.before.unchecked
        return [*(f for f in new_findings(self.before.report, self.after.report) if f.rule not in unchecked),
                *self.unverified]


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
    """The report, with what only a change can be held to, when there is a base to compare with: the workflow gates
    for the entries it changed, and the statements it changed whose tests it left as they were."""
    report = a.report
    for before in earlier:
        changes = Changeset.of(base or Revision(""), before, a)
        report = Report.of([*report.findings, *changes.gates, *changes.unverified])
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
    unwritten: Say = Say("")  # what to look at when the tests ran and the profiler wrote no profile


def _profiler(a: Analysis, adapters: Sequence[Adapter], root: ProjectRoot,
              extra: Sequence[Argument] = ()) -> tuple[Adapter, Profiling] | None:
    """The adapter whose profiler the tests run under, and how: the first that has both code here and a profiler,
    since a profile is of one run of the tests."""
    having = a.code.adapters if a.code is not None else frozenset()
    return next(((adapter, profiling) for adapter in adapters if adapter.name in having
                 and (profiling := adapter.profiled_tests(extra, root)) is not None), None)


@deal.ensure(lambda a, adapters, root, extra, result: result.refused or bool(result.command))
def profile(a: Analysis, adapters: Sequence[Adapter], root: ProjectRoot, extra: Sequence[Argument]) -> ProfiledRun:
    """The tests run once more, under the adapter's profiler, for zigdag stats (DESIGN2 §4.7)."""
    written, before = root / PROFILE_FILE, root / PROFILE_BEFORE
    if a.code is None:
        return ProfiledRun(True, refused("no code was read, so there is nothing to profile"), Outcome(), (), root,
                           written, before)
    chosen = _profiler(a, adapters, root, extra)
    if chosen is None:
        return ProfiledRun(True, refused("no adapter that read code here has a profiler"), Outcome(), (), root,
                           written, before)
    command = chosen[1].command
    starting = Outcome(out=(Shown(f"profiling the tests: {shlex.join(command)}"),))
    return ProfiledRun(False, Outcome(), starting, command, root, written, before, chosen[1].unwritten)


NEW = "none"  # what a part cost in the run before, when it had no cost then


def _shown(c: Cost | None) -> tuple[str, str, str]:
    """A part's CPU time, its share of the run, and its memory, as the table shows them."""
    return (f"{c.seconds:.2f} s", f"{c.time:.0f}%", f"{c.allocated:.1f} MB") if c is not None else (NEW, NEW, NEW)


_COLUMNS = ("part", "CPU time", "share", "memory allocated")


def _run(profile: Profile) -> str:
    """How long a profiled run took, and the most memory it held, when the profiler measures memory."""
    took = f"{profile.elapsed:.1f} s"
    return f"{took}, holding at most {profile.peak:.0f} MB at once" if profile.peak is not None else took


def _leaks(found: tuple[Suspect, ...], profiler: ToolName) -> list[str]:
    """The lines the profiler suspects of leaking, the likeliest first, or that it suspects none."""
    if not found:
        return ["no suspected memory leaks"]
    rows = [(f"{s.leak.span.path}:{s.leak.span.line}", s.part, f"{s.leak.likelihood:.0%} likely",
             f"growing {s.leak.growth:.2f} MB/s") for s in found]  # a whole line: scalene names no column
    return [f"suspected memory leaks, as {profiler} judges them:", *(f"  {r}" for r in _table(rows))]


def _change(now: str, before: str) -> str:
    return now if before == now else f"{before} → {now}"


def _table(rows: list[tuple[str, ...]]) -> list[str]:
    """Rows in columns as wide as their widest cell."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return [(" " * COLUMN_GAP).join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in rows]


@deal.ensure(lambda a, adapters, root, now, before, result: _changes_nothing(result))
def costs(a: Analysis, adapters: Sequence[Adapter], root: ProjectRoot, now: FileText | None,
          before: FileText | None) -> Outcome:
    """Where the time and memory of the latest profiled run went, by design part, beside the run before it."""
    if a.code is None or a.tree is None:
        return refused("no code was read, so a profile cannot be told by design part")
    chosen = _profiler(a, adapters, root)
    if chosen is None:
        return refused("no adapter that read code here has a profiler")
    adapter, profiling = chosen
    if now is None:
        return refused("there is no profile yet: run zigdag profile")
    latest = adapter.read_profile(now, root)
    if isinstance(latest, Unreadable):
        return refused(f"{PROFILE_FILE} cannot be read: {latest.say}")
    earlier = adapter.read_profile(before, root) if before is not None else None
    earlier = earlier if isinstance(earlier, Profile) else None  # one that cannot be read compares with nothing
    tests = a.settings.test_roots
    parts = by_part(latest, a.code, a.tree, tests)
    # A profiler that measures no memory has no memory to show: its column and its leaks are left out, not shown
    # as nothing.
    columns = len(_COLUMNS) if latest.peak is not None else len(_COLUMNS) - 1
    head = f"the tests ran for {_run(latest)}"
    if earlier is not None:
        held = f" and {earlier.peak:.0f} MB" if earlier.peak is not None else ""
        head += f"; the run before, {earlier.elapsed:.1f} s{held}"
    rows: list[tuple[str, ...]] = [_COLUMNS[:columns]]
    for c in compared(parts, by_part(earlier, a.code, a.tree, tests) if earlier is not None else ())[:PARTS_SHOWN]:
        now_, then = _shown(c.now), _shown(c.before)
        rows.append((c.now.part, *(_change(n, b) if earlier is not None else n for n, b in zip(now_, then)))[:columns])
    more = len(parts) - PARTS_SHOWN
    memory = (_leaks(suspects(latest, a.code, a.tree, tests), profiling.profiler) if latest.peak is not None
              else [f"{profiling.profiler} measures time only: memory and leaks are not known"])
    return Outcome(out=(Shown("\n".join([head, "", *_table(rows), *([f"and {more} more parts"] if more > 0 else []),
                                         "", *memory, "", profiling.full])),))


@deal.ensure(lambda run, written, returncode, a, adapters, now, before, result:
             _changes_nothing(result) or result.exit == REFUSED)
@deal.ensure(lambda run, written, returncode, a, adapters, now, before, result: written is Presence.PRESENT
             or result.exit == REFUSED)
def profiled_run(run: ProfiledRun, written: Presence, returncode: ExitCode, a: Analysis, adapters: Sequence[Adapter],
                 now: FileText | None, before: FileText | None) -> Outcome:
    shown = shlex.join(run.command)
    if written is Presence.ABSENT:
        return refused(f"the tests ran under the profiler ({shown} exited {returncode}), but it wrote no profile: "
                       f"{run.unwritten}")
    table = costs(a, adapters, ProjectRoot(run.root), now, before)
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
    unseen: Say = Say("")  # what to look at when the tests ran and the watcher wrote nothing
    unwatched: tuple[tuple[Argument, ...], ...] = ()  # the test commands of adapters that have no watcher, run after
    cleared: tuple[FilePath, ...] = ()  # what the run before wrote that this one writes anew: removed first

    @property
    @deal.ensure(lambda self, result: len(result) == len(self.unwatched) + bool(self.command))
    def commands(self) -> tuple[tuple[Argument, ...], ...]:
        """Every test command of the run, in the order they are run: the watched one, when there is one, first."""
        return (*((self.command,) if self.command else ()), *self.unwatched)

    @property
    @deal.ensure(lambda self, result: all(shlex.join(command) in result for command in self.commands))
    def shown(self) -> Shown:
        return Shown("; ".join(shlex.join(command) for command in self.commands))


@deal.post(lambda result: result >= 0)
@deal.ensure(lambda codes, result: (result == OK) == all(code == OK for code in codes))
def exited(codes: Sequence[ExitCode]) -> ExitCode:
    """What several test commands exited with, as one: the first that is not zero, so a failure of any is one."""
    return next((code for code in codes if code != OK), OK)


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
    bool(result.commands) and PLAN_VARIABLE in result.environment))  # the watcher is always told its plan
def test(a: Analysis, files: Files, root: ProjectRoot, extra: Sequence[Argument],
         environment: Environment) -> WatchedRun:
    watch = watch_plan(a, test_files(files), files)
    observed = root / OBSERVED_FILE
    if watch is None:
        return WatchedRun(True, refused("no code was read, so there is nothing to watch"), "", observed, (), root, {})
    runs = [run for adapter in reading_of(files).adapters
            if (run := adapter.test_run(files, extra, root)) is not None]
    # One run is watched, since a watcher writes what it saw to one file: the first adapter's that has a watcher.
    watching = next((run for run in runs if run.watched), None)
    if not runs:
        return WatchedRun(True, refused("no adapter that read code here has tests to run"), "", observed, (),
                          root, {})
    told = {name: value for run in runs for name, value in run.environment.items()}
    return WatchedRun(False, Outcome(), replace(watch, last_run=carried(files)).to_text(), observed,
                      watching.command if watching is not None else (), root,
                      {**environment, **told, PLAN_VARIABLE: str(root / PLAN_FILE)},
                      (watching.unseen if watching is not None else None) or Say(""),
                      tuple(run.command for run in runs if run is not watching),
                      tuple(root / path for run in runs for path in run.clears))


@deal.ensure(lambda run, seen, returncode, after, result: _reports_only(result))
# A run with a watched command must have been seen by its watcher. One with none, such as a project whose tests
# are all run without a watcher, has no watcher's file to wait for.
@deal.ensure(lambda run, seen, returncode, after, result: seen is Presence.PRESENT or not run.command
             or result.exit == REFUSED)
def tested(run: WatchedRun, seen: Presence, returncode: ExitCode, after: Analysis) -> Outcome:
    shown = run.shown
    if seen is Presence.ABSENT and run.command:
        return refused(f"the tests ran ({shown} exited {returncode}), but the watcher saw nothing: "
                       f"{run.unseen}")
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


def _held_to(branch: PartBranch | None, started: Sequence[Analysis], after: Analysis) -> tuple[Finding, ...]:
    """What a part's branch breaks by what it changed; nothing, on any other branch."""
    return tuple(f for start in started for f in check_part(branch, start, after)) if branch is not None else ()


def _waits(branch: PartBranch | None, earlier: Sequence[Analysis], after: Analysis) -> Waiting:
    """Which failing tests of a part's branch wait for other parts to land; none, on any other branch."""
    if branch is None or not earlier:
        return NOT_WAITING
    return waiting(after, branch.part, asked(earlier[0], after))


def _verdict(reasons: Sequence[Say], waits: Waiting) -> Shown:
    """The last thing ready says: yes; that a part's branch is built and only waits; or no, with each reason."""
    held_up = "1 failing test waits" if len(waits.tests) == 1 else f"{len(waits.tests)} failing tests wait"
    if reasons:
        return Shown("\n".join([NOT_READY, *(f"  {reason}" for reason in reasons),
                                *([f"  {held_up} for {', '.join(waits.on)} to land, which is not this branch's to "
                                   f"fix"] if waits.tests else [])]))
    return Shown(f"{BUILT} {', '.join(waits.on)} to land") if waits.is_all else Shown(READY)


@deal.ensure(lambda run, seen, returncode, after, earlier, base, files, branch=None, started=(), *, result:
             _reports_only(result))
@deal.ensure(lambda run, seen, returncode, after, earlier, base, files, branch=None, started=(), *, result:
             result.exit != OK or (returncode == OK and _gated(after, earlier, base).passes))  # never yes on a no
@deal.ensure(lambda run, seen, returncode, after, earlier, base, files, branch=None, started=(), *, result:
             (result.exit == OK) == (result.out[-1:] == (READY,)))
def ready(run: WatchedRun, seen: Presence, returncode: ExitCode, after: Analysis, earlier: Sequence[Analysis],
          base: Revision | None, files: Files, branch: PartBranch | None = None,
          started: Sequence[Analysis] = ()) -> Outcome:
    """One answer to "is this change ready?", after the tests ran under the watcher. Yes only when the tests pass,
    nothing breaks, no question is open, no result is out of date, the design files are in their layout and, when
    there is a base to compare with, the change adds nothing to do.

    On the branch of a part, the change is the part's alone. It is held to what the change asks of that part, to
    changing nothing but the part, and to having every commit of the line it lands on. A test that fails because it
    ran another part's code that is not written yet is not the branch's to fix: when only such tests stand in the
    way, the answer is that the part is built and waits."""
    shown = run.shown
    if seen is Presence.ABSENT and run.command:
        return refused(f"the tests ran ({shown} exited {returncode}), but the watcher saw nothing: "
                       f"{run.unseen}")
    outside = _held_to(branch, started, after)
    summed, writes = summary(standings(after, Report.of([*_gated(after, earlier, base).findings, *outside])))
    waits = _waits(branch, earlier, after)
    # What a waiting test's failure says is set aside before the gates are asked, so that a gate which stops a
    # change while anything breaks does not stop a branch for a break that is not its own.
    calm = replace(after, report=Report(tuple(f for f in after.report.findings if f not in waits.set_aside)))
    judged = Report.of([*_gated(calm, earlier, base).findings, *outside])
    brought = [f for before in earlier for f in Changeset.of(base or Revision(""), before, after).brought
               if f.result is Result.TODO and (branch is None or after.is_under(f, branch.part))]
    behind = branch.behind if branch is not None else Count(0)
    reasons = (*_not_ready(judged, OK if waits.is_all else returncode, Count(len(Formatted.of(files).changed)),
                           brought, base),
               *([Say(f"{branch.line} has {'1 commit' if behind == 1 else f'{behind} commits'} that this branch "
                      f"does not: merge {branch.line}, and ask again")] if branch is not None and behind else []))
    verdict = _verdict(reasons, waits)
    return Outcome(OK if verdict == READY else FOUND, (summed, f"tests: {shown} exited {returncode}", "", verdict),
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


def _delta(a: Analysis, earlier: Sequence[Analysis], base: Revision | None, target: Written):
    """What the change since the base says of the part a context is asked for; None with no base, or no such part."""
    part = a.dp_of(target)
    if part is None or base is None or not earlier:
        return None
    return delta(base, earlier[0], a, part)


@deal.ensure(lambda a, name, target, earlier=(), base=None, *, result: _changes_nothing(result)
             and len(result.out) == 1)
def view(a: Analysis, name: View, target: Written | None, earlier: Sequence[Analysis] = (),
         base: Revision | None = None) -> Outcome:
    match name:
        case View.SHOW:
            return Outcome(out=(views.show(a, FrName(target) if target else None),))
        case View.DATA:
            return Outcome(out=(views.data(a, FrName(target) if target else None),))
        case View.CONTEXT:
            return Outcome(out=(views.context(a, target or Written(""), _delta(a, earlier, base, target or Written(""))),))
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


def _python_source(files: Files) -> tuple[RecordPath, ...]:
    """Where the project's Python source is. A setup records Python: it is the one adapter that reads a project
    that has configured nothing."""
    reading = reading_of(files)
    return PythonAdapter.of(reading.settings, _conventional(files)).source_roots


def _recorded(files: Files, spelled: frozenset[RuleId], also: tuple[Write, ...]) -> Outcome:
    """The code recorded as it is, with what else the command writes beside the record."""
    read = project_files(files)
    code = code_model(files)
    if code is None:
        return refused("no code found to record")
    writes: list[Write] = []
    if read.settings is None:
        new_settings = settings_text(_python_source(files))
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


# ---- handing out the work of a change ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    """A branch to make for a part, tracking the branch it lands on: how a part is taken."""

    branch: BranchName
    line: BranchName

    @property
    @deal.ensure(lambda self, result: result[-2:] == (self.branch, self.line))
    def command(self) -> tuple[Argument, ...]:
        """What git is asked, to make it. Git refuses a branch that exists, so a part is never taken twice."""
        return (Argument("branch"), Argument("--track"), Argument(self.branch), Argument(self.line))


@dataclass(frozen=True)
class Handout:
    """What work answers, and the branch to make first when the answer hands a free part out."""

    outcome: Outcome
    claims: tuple[Claim, ...] = ()


def _not_settled(base: Revision, before: Analysis, line: Analysis, uncommitted: Sequence[RecordPath]) -> tuple[Say, ...]:
    """Each reason the design is not settled yet: a design file that is not committed, so no part's branch would
    have it; a changed entry that has not passed a gate; and what the change brought that is wrong with the design
    itself. A gate that stops a change while anything breaks is not asked: building the parts is what mends that."""
    gates = [f for f in Changeset.of(base, before, line).gates if f.about != THE_CHANGE]
    return (*(Say(f"{path} has changes that are not committed, so no part's branch would have them")
              for path in uncommitted),
            *(Say(f"{f.about}: {f.say}") for f in (*gates, *unsettled(before, line))))


def _handed(answer: Answer, base: Revision, line: BranchName) -> list[str]:
    """An answer as work prints it: what to do in the first line, and under it what whoever does it needs."""
    why = [f"  {said}" for said in answer.why]
    if answer.part is None:
        first, *rest = answer.why or (Say(""),)
        return [f"{answer.step.value}: {first}" if first else answer.step.value, *(f"  {said}" for said in rest)]
    branch = branch_of(answer.part)
    if answer.step is Step.LAND:
        return [f"{Step.LAND.value} {answer.part}", *why,
                f"  bring {branch} up to date with {line}, then: zigdag ready --base {base}",
                f"  on yes, merge {branch} into {line}"]
    return [f"{Step.BUILD.value} {answer.part}", *why, f"  on {branch}, which lands on {line}",
            f"  what to build: zigdag context {answer.part} --base {base}",
            f"  built when: zigdag ready --base {base} says yes, or built"]


@deal.pre(lambda base, before, line, found, taken, folders: len(folders) == len(taken.folders))
@deal.ensure(lambda base, before, line, found, taken, folders, result: _changes_nothing(result.outcome))
@deal.ensure(lambda base, before, line, found, taken, folders, result: all(
    part_built_on(c.branch) is not None and part_built_on(c.branch) not in {t.part for t in taken.parts}
    for c in result.claims))  # only a part nobody has is taken
def work(base: Revision, before: Analysis, line: Analysis, found: Checkout, taken: Claims,
         folders: Sequence[Analysis]) -> Handout:
    """What to do next on a change that is built part by part, since the revision the change began at (DESIGN2 §4.8).
    `line` is the project where the parts land, as committed; `folders` are the projects in the folders of the parts
    that are checked out, in their order."""
    if found.branch is None:
        return Handout(refused("no branch is checked out: ask from the branch the parts land on"))
    if found.part is not None:
        return Handout(refused(f"this is the branch of {found.part}: ask from the branch the parts land on"))
    read = iter(folders)
    held = tuple(Taken(c.part, next(read) if c.folder is not None else None) for c in taken.parts)
    answer = next_step(before, line, held, _not_settled(base, before, line, taken.uncommitted))
    free = answer.step is Step.BUILD and answer.part not in {c.part for c in taken.parts}
    return Handout(Outcome(FOUND if answer.step is Step.BLOCKED else OK,
                           (Shown("\n".join(_handed(answer, base, found.branch))),)),
                   (Claim(branch_of(answer.part), found.branch),) if free and answer.part is not None else ())


@deal.pre(lambda handout, made: len(made) == len(handout.claims))
@deal.ensure(lambda handout, made, result: result == handout.outcome or result.exit == REFUSED)
def handed_out(handout: Handout, made: Sequence[GitAnswer]) -> Outcome:
    """What work says once the branch it needed was made: its answer, or, when git made no branch, that the part
    could not be taken. An answer is not given for a part that was not taken: two agents would be told to build it."""
    failed = [claim.branch for claim, answer in zip(handout.claims, made) if answer.exit != OK]
    if failed:
        return refused(f"git did not make {', '.join(failed)}, so the part is not taken: ask again")
    return handout.outcome


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
    WORK = "work"
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
    base: Revision | None = None  # for a view that takes one: where the change it shows began


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
                 f"unrecognized arguments: {' '.join(passed_on)}", refusal, view, target, getattr(args, "base", None))

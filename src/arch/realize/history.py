"""Change history: how often units change, and which change together.

Realizes arch.realize.history. Reads `git log --numstat` output supplied by the workspace. Windows are
counted in commits, not time, so the same log always gives the same facts; commits that touch many files
(mass renames, formatting sweeps) are left out because they would make everything look coupled.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from typing import NewType

import re

from arch.realize.facts import (
    ChangeEvent,
    CommitId,
    Content,
    DiffLine,
    DiffLineKind,
    Facts,
    FileChange,
    FileDiff,
    FileShape,
    Hunk,
    LineNo,
    SourcePath,
    SourceText,
    Text,
    UnitName,
    VcsLog,
)

NumStat = NewType("NumStat", str)  # raw `git diff --numstat` output
UnifiedDiff = NewType("UnifiedDiff", str)  # raw `git diff -M` output
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")

Count = NewType("Count", int)
FileLimit = NewType("FileLimit", int)
CommitWindow = NewType("CommitWindow", int)  # how many recent commits to read

COMMIT_MARK = "commit "
MAX_FILES_PER_COMMIT = FileLimit(30)


def parse_log(log: VcsLog, max_files: FileLimit = MAX_FILES_PER_COMMIT) -> tuple[ChangeEvent, ...]:
    """Commits from `git log --numstat --format='commit %H'`, skipping ones that touch more than max_files."""
    events: list[ChangeEvent] = []
    commit: str | None = None
    paths: list[SourcePath] = []

    def flush() -> None:
        if commit is not None and 0 < len(paths) <= max_files:
            events.append(ChangeEvent(CommitId(commit), tuple(paths)))

    for line in log.splitlines():
        if line.startswith(COMMIT_MARK):
            flush()
            commit, paths = line[len(COMMIT_MARK):].strip(), []
        elif line.strip() and commit is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                paths.append(SourcePath(_renamed_to(parts[2])))
    flush()
    return tuple(events)


def parse_numstat(text: NumStat) -> tuple[FileChange, ...]:
    """Changed files with their line counts; binary files count as zero lines."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, removed = (int(x) if x.isdigit() else 0 for x in parts[:2])
            out.append(FileChange(SourcePath(_renamed_to(parts[2])), LineNo(added), LineNo(removed)))
    return tuple(sorted(out, key=lambda c: c.path))


def _renamed_to(path: str) -> str:
    """numstat writes renames as `a/{old => new}/b` or `old => new`; keep the new path."""
    if "{" in path and " => " in path:
        head, rest = path.split("{", 1)
        inner, tail = rest.split("}", 1)
        return (head + inner.split(" => ")[1] + tail).replace("//", "/")
    return path.split(" => ")[-1]


@dataclass(frozen=True)
class History:
    """Churn and co-change by unit, from the change events in a set of facts."""

    churn: Counter = field(default_factory=Counter)  # UnitName -> commits touching it
    together: Counter = field(default_factory=Counter)  # frozenset({a, b}) -> commits touching both

    @staticmethod
    def of(facts: Facts) -> History:
        unit_at = {u.path: u.name for u in facts.units}
        churn: Counter = Counter()
        together: Counter = Counter()
        for event in facts.changes:
            units = sorted({unit_at[p] for p in event.paths if p in unit_at})
            churn.update(units)
            together.update(frozenset(pair) for pair in combinations(units, 2))
        return History(churn, together)

    def co_changes(self, a: Iterable[UnitName], b: Iterable[UnitName]) -> Count:
        """Commits that changed something in group a and something in group b."""
        a, b = set(a), set(b)
        total = 0
        for pair, n in self.together.items():
            x, y = tuple(pair)
            if (x in a and y in b) or (x in b and y in a):
                total += n
        return Count(total)


def parse_diff(text: UnifiedDiff) -> tuple[FileDiff, ...]:
    """Files and hunks from `git diff -M --no-color` output; renames, additions and deletions included."""
    files: list[FileDiff] = []
    current: dict = {}
    hunks: list[Hunk] = []
    lines: list[DiffLine] = []
    hunk_head: tuple[int, int, str] | None = None
    old_no = new_no = 0

    def close_hunk() -> None:
        nonlocal lines, hunk_head
        if hunk_head is not None:
            hunks.append(Hunk(LineNo(hunk_head[0]), LineNo(hunk_head[1]), Text(hunk_head[2]), tuple(lines)))
        lines, hunk_head = [], None

    def close_file() -> None:
        nonlocal hunks
        close_hunk()
        if current:
            shape = current.get("shape", FileShape.MODIFIED)
            path = current.get("new") if shape is not FileShape.DELETED else current.get("old")
            old = current.get("old") if shape is FileShape.RENAMED else None
            files.append(FileDiff(SourcePath(path), SourcePath(old) if old else None, shape, tuple(hunks),
                                  current.get("content", Content.TEXT), current.get("similarity")))
        current.clear()
        hunks = []

    for line in text.split("\n"):
        if line.startswith("diff --git "):
            close_file()
            a, _, b = line[len("diff --git "):].partition(" b/")
            current.update(old=a.removeprefix("a/"), new=b)
        elif hunk_head is None and line.startswith("new file mode"):
            current["shape"] = FileShape.ADDED
        elif hunk_head is None and line.startswith("deleted file mode"):
            current["shape"] = FileShape.DELETED
        elif hunk_head is None and line.startswith("rename from "):
            current.update(shape=FileShape.RENAMED, old=line[len("rename from "):])
        elif hunk_head is None and line.startswith("rename to "):
            current["new"] = line[len("rename to "):]
        elif hunk_head is None and line.startswith("similarity index "):
            current["similarity"] = LineNo(int(line[len("similarity index "):].rstrip("%") or 0))
        elif line.startswith("Binary files "):
            current["content"] = Content.BINARY
        elif (m := _HUNK.match(line)) is not None:
            close_hunk()
            old_no, new_no = int(m.group(1)), int(m.group(2))
            hunk_head = (old_no, new_no, m.group(3))
        elif hunk_head is not None and line[:1] in (" ", "+", "-"):
            kind = DiffLineKind(line[0])
            lines.append(DiffLine(kind, Text(line[1:]), LineNo(old_no) if kind is not DiffLineKind.ADDED else None,
                                  LineNo(new_no) if kind is not DiffLineKind.REMOVED else None))
            old_no += kind is not DiffLineKind.ADDED
            new_no += kind is not DiffLineKind.REMOVED
    close_file()
    return tuple(sorted(files, key=lambda f: f.path))


def added_file(path: SourcePath, text: SourceText) -> FileDiff:
    """A new, untracked file as a diff in which every line is added."""
    rows = text.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    lines = tuple(DiffLine(DiffLineKind.ADDED, Text(r), None, LineNo(i)) for i, r in enumerate(rows, 1))
    return FileDiff(path, None, FileShape.ADDED, (Hunk(LineNo(0), LineNo(1), Text(""), lines),) if lines else ())

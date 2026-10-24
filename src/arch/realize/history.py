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

from arch.realize.facts import ChangeEvent, CommitId, Facts, SourcePath, UnitName, VcsLog

COMMIT_MARK = "commit "
MAX_FILES_PER_COMMIT = 30
Count = NewType("Count", int)


def parse_log(log: VcsLog, max_files: int = MAX_FILES_PER_COMMIT) -> tuple[ChangeEvent, ...]:
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

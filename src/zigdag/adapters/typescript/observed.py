"""What zigdag's watcher for vitest saw while the tests ran (zigdag/watchers/typescript/setup.mjs), and the part of
it that is still current: for each test, the modules whose code ran while it did.

That is all this watcher sees. What the code did, its effects and the values it passed, is not watched yet.

An observation counts only while every file it was seen in is unchanged: a run shows what the code did then. The
watcher writes each file with a digest of what it held, and the same digest is taken here of what it holds now.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import deal

from zigdag.adapters.typescript.modules import SUFFIXES, unit_path
from zigdag.adapters.typescript.tests import name_pattern
from zigdag.core.code import Observations, Run, TestId
from zigdag.core.findings import RecordPath
from zigdag.core.names import CodePath
from zigdag.core.settings import WORK_DIR
from zigdag.core.texts import FileText

SEEN_FILE = RecordPath(f"{WORK_DIR}/observed.typescript.jsonl")  # one line a test, as the watcher appends them
WATCHER_VARIABLE, SEEN_VARIABLE, ROOT_VARIABLE = "ZIGDAG_WATCHER", "ZIGDAG_SEEN", "ZIGDAG_ROOT"
# What a project writes in the test section of its vitest config to attach the watcher.
ATTACHED_BY = f"setupFiles: process.env.{WATCHER_VARIABLE} ? [process.env.{WATCHER_VARIABLE}] : []"
ENCODING = "utf-8"

ContentDigest = str  # a file's content, as the watcher and this module both digest it: SHA-256, in hexadecimal


@deal.pure
@deal.post(lambda result: len(result) == hashlib.sha256().digest_size * 2)
def digest(text: FileText) -> ContentDigest:
    return hashlib.sha256(text.encode(ENCODING)).hexdigest()


@dataclass(frozen=True)
class Seen:
    """One test as it ran, with the files whose code ran while it did, each as it was then."""

    file: RecordPath  # the test's file
    name: str  # the groups it is in and its own name, as vitest's report gives it
    held: ContentDigest  # what the test's file held
    ran: tuple[tuple[RecordPath, ContentDigest], ...]


def _file(raw: object) -> tuple[RecordPath, ContentDigest] | None:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("file"), str) or not isinstance(raw.get("digest"), str):
        return None
    return RecordPath(raw["file"]), raw["digest"]


@deal.ensure(lambda text, result: result is None or len(result) == len([written for written in text.splitlines() if written.strip()]))
def read_seen(text: FileText) -> tuple[Seen, ...] | None:
    """Each test the watcher wrote, in the order they ended; None when a line does not read as the watcher writes
    it, so that nothing is taken from a file half read."""
    seen = []
    for line in (written for written in text.splitlines() if written.strip()):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return None
        test = raw.get("test") if isinstance(raw, Mapping) else None
        described = _file(test)
        ran = [_file(file) for file in (raw.get("ran") if isinstance(raw.get("ran"), list) else [None])] \
            if isinstance(raw, Mapping) else [None]
        if described is None or not isinstance(test, Mapping) or not isinstance(test.get("name"), str) or None in ran:
            return None
        seen.append(Seen(described[0], test["name"], described[1], tuple(f for f in ran if f is not None)))
    return tuple(seen)


def _patterns(tests: Iterable[TestId]) -> dict[RecordPath, list[tuple[re.Pattern[str], TestId]]]:
    by_file: dict[RecordPath, list[tuple[re.Pattern[str], TestId]]] = {}
    for test in tests:
        path, _, name = test.partition("::")
        by_file.setdefault(RecordPath(path), []).append((name_pattern(name), test))
    return by_file


@deal.ensure(lambda seen, tests, now, result: set(result.runs) <= set(tests))
@deal.ensure(lambda seen, tests, now, result: all(run.test == test for test, run in result.runs.items()))
def observations(seen: Iterable[Seen], tests: Iterable[TestId], now: Mapping[RecordPath, FileText]) -> Observations:
    """For each test that was seen running: the modules whose code ran, and whether the test and all of that code
    are as they were. A test written for several cases ran once for each: what ran in any of them ran in it, and
    it is current only when every one of them is."""
    held = {path: digest(text) for path, text in now.items()}
    by_file = _patterns(tests)
    ran: dict[TestId, set[CodePath]] = {}
    current: dict[TestId, bool] = {}
    for one in seen:
        same = held.get(one.file) == one.held and all(held.get(path) == was for path, was in one.ran)
        units = {unit_path(path) for path, _ in one.ran if path.endswith(SUFFIXES)}
        for pattern, test in by_file.get(one.file, ()):
            if pattern.fullmatch(one.name) is not None:
                ran.setdefault(test, set()).update(units)
                current[test] = current.get(test, True) and same
    return Observations(runs={test: Run(test, frozenset(units), current[test]) for test, units in sorted(ran.items())})


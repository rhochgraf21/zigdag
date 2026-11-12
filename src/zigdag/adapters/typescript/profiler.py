"""TypeScript's profiler, the one Node has built in (DESIGN2 §4.7): how zigdag profile starts it on the project's
tests, and what its profile says, line by line.

Node's CPU profile measures time, and no memory. vitest runs the tests in a process of its own, so that process is
the one profiled: one process, one file after another, so that there is one profile. The profile names each line
as Node ran it, after vitest made the TypeScript into JavaScript, which keeps a file's lines where they were as
far as it can.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path

import deal

from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath, Span
from zigdag.core.measures import Column, Line, Megabytes, Seconds, Share
from zigdag.core.names import TYPESCRIPT, Argument, Key, ProjectRoot
from zigdag.core.profile import Profile, ProfiledLine
from zigdag.core.settings import PROFILE_FILE, Settings
from zigdag.core.texts import FileText, Say

PROFILER = "node --cpu-prof"  # as people know it
TEST_COMMAND_KEY = Key("test_command")
DEFAULT_TEST_COMMAND = "npx vitest run"
_ONE_PROCESS = ("--pool=forks", "--no-file-parallelism")  # the tests in one process of their own, a file at a time
_TO_NODE = "--execArgv="  # how vitest passes an option on to the process that runs the tests
_FILE_SCHEME = "file://"
_MICROSECONDS = 1_000_000  # the profile's times are in millionths of a second
_WHOLE = 100  # a share is a percentage
_NO_MEMORY = Megabytes(0.0)  # a CPU profile measures none
_FIRST_COLUMN = Column(1)  # the profile's ticks are counted by whole lines


@deal.ensure(lambda settings, extra, root, result: result[-len(extra):] == tuple(extra) if extra else True)
def profiled(settings: Settings, extra: Sequence[Argument], root: ProjectRoot) -> tuple[Argument, ...]:
    """The command that runs the tests with Node's CPU profiler on the process that runs them, writing the profile
    where zigdag stats reads it. vitest runs from its own folder, so the profile's place is given in full."""
    start = shlex.split(settings.command(TYPESCRIPT, TEST_COMMAND_KEY) or DEFAULT_TEST_COMMAND)
    written = root / PROFILE_FILE
    to_node = ("--cpu-prof", f"--cpu-prof-dir={written.parent}", f"--cpu-prof-name={written.name}")
    return tuple(Argument(a) for a in (*start, *_ONE_PROCESS, *(f"{_TO_NODE}{option}" for option in to_node), *extra))


@deal.post(lambda result: PROFILE_FILE in result)
def full_profile() -> Say:
    """What the profile holds beyond zigdag's table, and how to open it."""
    return Say(f"To see the calls in full: open {PROFILE_FILE} in a browser's developer tools (Performance, Load "
               f"profile), or in an editor that reads a .cpuprofile")


def _path(url: str, root: ProjectRoot) -> RecordPath:
    """A profiled file as the project names it, relative to its root; a file elsewhere, or code of Node's own, keeps
    the name the profile gives it."""
    file = Path(url.removeprefix(_FILE_SCHEME))
    return RecordPath(file.relative_to(root).as_posix() if file.is_relative_to(root) else url)


def _self_times(raw: Mapping) -> dict[int, float] | None:
    """How long the run was in each node of the profile's own code: the time before each sample goes to the node it
    was taken in."""
    samples, deltas = raw.get("samples"), raw.get("timeDeltas")
    if not isinstance(samples, list) or not isinstance(deltas, list) or len(samples) != len(deltas):
        return None
    times: dict[int, float] = {}
    for node, delta in zip(samples, deltas):
        if not isinstance(node, int) or not isinstance(delta, int | float):
            return None
        times[node] = times.get(node, 0.0) + max(delta, 0)
    return times


@deal.ensure(lambda text, root, result: isinstance(result, Unreadable) or all(0 <= line.time for line in result.lines))
@deal.ensure(lambda text, root, result: isinstance(result, Unreadable) or result.peak is None)  # it measures no memory
def read_profile(text: FileText, root: ProjectRoot) -> Profile | Unreadable:
    """The lines a Node CPU profile gives time to, with how long the run took. A node's time is shared among its
    lines by how often the profiler found the run on each."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Unreadable(Say(f"not JSON: {e}"))
    nodes = raw.get("nodes") if isinstance(raw, Mapping) else None
    times = _self_times(raw) if isinstance(raw, Mapping) else None
    start, end = (raw.get("startTime"), raw.get("endTime")) if isinstance(raw, Mapping) else (None, None)
    if not isinstance(nodes, list) or times is None or not isinstance(start, int | float) or not isinstance(
            end, int | float):
        return Unreadable(Say("not a Node CPU profile: it lacks its nodes, its samples or its times"))
    elapsed = max(end - start, 0)
    by_line: dict[tuple[RecordPath, int], float] = {}
    for node in nodes:
        frame = node.get("callFrame") if isinstance(node, Mapping) else None
        if not isinstance(frame, Mapping) or not isinstance(node.get("id"), int):
            return Unreadable(Say("a node of the profile lacks its place in the code"))
        url, spent = frame.get("url"), times.get(node["id"], 0.0)
        if not isinstance(url, str) or not url or not spent:
            continue  # time in no file, such as waiting, is no line's
        ticks = [t for t in node.get("positionTicks", ()) if isinstance(t, Mapping) and isinstance(t.get("line"), int)
                 and isinstance(t.get("ticks"), int) and t["ticks"] > 0]
        whole = sum(t["ticks"] for t in ticks)
        declared = frame.get("lineNumber")
        places = [(t["line"], t["ticks"] / whole) for t in ticks] or [
            ((declared + 1) if isinstance(declared, int) and declared >= 0 else 1, 1.0)]
        for line, part in places:
            key = (_path(url, root), max(line, 1))
            by_line[key] = by_line.get(key, 0.0) + spent * part
    lines = tuple(ProfiledLine(Span(path, Line(line), _FIRST_COLUMN),
                               Share(spent / elapsed * _WHOLE if elapsed else 0.0), _NO_MEMORY)
                  for (path, line), spent in sorted(by_line.items()))
    return Profile(Seconds(elapsed / _MICROSECONDS), None, lines)

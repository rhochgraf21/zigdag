"""Python's profiler, scalene (DESIGN2 §4.7): how zigdag profile starts it on the project's tests, and what its profile
says, line by line."""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path

import deal

from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath, Span
from zigdag.core.measures import Column, Growth, Likelihood, Line, Megabytes, Seconds, Share
from zigdag.core.names import PYTHON, Argument, Key, ProjectRoot
from zigdag.core.profile import Leak, Profile, ProfiledLine
from zigdag.core.settings import CURRENT_FOLDER, PROFILE_FILE, Settings
from zigdag.core.texts import FileText, Say

PROFILER = Key("scalene")  # its key in [adapters.python], which says how to start it
_RUN = "run"
_OUTFILE, _PROGRAM_PATH = "--outfile", "--program-path"
# scalene samples on the real-time interval timer by default, which zigdag's mutants use to stop one that never
# returns: sharing it, each resets the other, and a mutant that loops is never stopped. On the CPU-time timer, they
# never meet, and what scalene measures is CPU time, which is what zigdag reports.
_VIRTUAL_TIME = "--use-virtual-time"
_PYTEST = ("-m", "pytest")  # the tests, run as a module, as python -m would
_PROGRAM_ARGUMENTS = "---"  # what comes after this goes to the program, not to scalene
_TIME = ("n_cpu_percent_python", "n_cpu_percent_c", "n_sys_percent")  # a line's time: in Python, native code, the OS
_ALLOCATED = "n_malloc_mb"
_FIRST_COLUMN = Column(1)  # scalene profiles whole lines


@deal.ensure(lambda settings, extra, result: result[-len(extra):] == tuple(extra) if extra else True)
def profiled(settings: Settings, extra: Sequence[Argument]) -> tuple[Argument, ...]:
    """The command that runs the tests under scalene, from the project's root: it profiles the project's own code,
    which is everything under the root, and writes the profile where zigdag stats reads it."""
    start = shlex.split(settings.command(PYTHON, PROFILER) or PROFILER)
    return tuple(Argument(a) for a in (*start, _RUN, _OUTFILE, PROFILE_FILE, _PROGRAM_PATH, CURRENT_FOLDER,
                                       _VIRTUAL_TIME, *_PYTEST, _PROGRAM_ARGUMENTS, *extra))


_VIEW, _IN_TERMINAL = "view", "--cli"


@deal.ensure(lambda settings, result: PROFILE_FILE in result)
def full_profile(settings: Settings) -> Say:
    """What the profile holds beyond zigdag's table, and how to open it."""
    view = shlex.join([*shlex.split(settings.command(PYTHON, PROFILER) or PROFILER), _VIEW, PROFILE_FILE])
    return Say(f"To see line by line, with CPU, memory, GPU and copy volume: {view} (add {_IN_TERMINAL} for the "
               f"terminal)")


def _path(name: str, root: ProjectRoot) -> RecordPath:
    """A profiled file as the project names it, relative to its root; a file elsewhere keeps its own path."""
    file = Path(name)
    return RecordPath(file.relative_to(root).as_posix() if file.is_relative_to(root) else file.as_posix())


def _lines(path: RecordPath, lines: object) -> list[ProfiledLine] | None:
    if not isinstance(lines, list):
        return None
    out = []
    for raw in lines:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("lineno"), int):
            return None
        time = sum(v for k in _TIME if isinstance(v := raw.get(k, 0), int | float))
        allocated = raw.get(_ALLOCATED, 0)
        if time or allocated:
            out.append(ProfiledLine(Span(path, Line(raw["lineno"]), _FIRST_COLUMN), Share(time),
                                    Megabytes(allocated if isinstance(allocated, int | float) else 0.0)))
    return out


def _leaks(path: RecordPath, leaks: object) -> list[Leak] | None:
    """The lines scalene suspects of leaking: by line number, how likely, and how fast the memory grows."""
    if not isinstance(leaks, Mapping):
        return None
    out = []
    for line, raw in leaks.items():
        likelihood = raw.get("likelihood") if isinstance(raw, Mapping) else None
        growth = raw.get("velocity_mb_s", 0.0) if isinstance(raw, Mapping) else None
        if not str(line).isdigit() or not isinstance(likelihood, int | float) or not isinstance(growth, int | float):
            return None
        out.append(Leak(Span(path, Line(int(line)), _FIRST_COLUMN), Likelihood(likelihood), Growth(growth)))
    return out


@deal.ensure(lambda text, root, result: isinstance(result, Unreadable) or all(
    0 <= line.time for line in result.lines))
def read_profile(text: FileText, root: ProjectRoot) -> Profile | Unreadable:
    """The lines a scalene profile gives time or memory to, and the lines it suspects of leaking, with how long the
    run took and the most it held."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Unreadable(Say(f"not JSON: {e}"))
    files = raw.get("files") if isinstance(raw, Mapping) else None
    elapsed, peak = (raw.get("elapsed_time_sec"), raw.get("max_footprint_mb")) if isinstance(raw, Mapping) else (0, 0)
    if not isinstance(files, Mapping) or not isinstance(elapsed, int | float) or not isinstance(peak, int | float):
        return Unreadable(Say("not a scalene profile: it lacks its files, its time or its memory"))
    lines: list[ProfiledLine] = []
    leaks: list[Leak] = []
    for name, data in files.items():
        path, data = _path(name, root), data if isinstance(data, Mapping) else {}
        found, leaked = _lines(path, data.get("lines")), _leaks(path, data.get("leaks", {}))
        if found is None or leaked is None:
            return Unreadable(Say(f"the profile of {name} does not read as scalene writes it"))
        lines += found
        leaks += leaked
    return Profile(Seconds(elapsed), Megabytes(peak), tuple(lines), tuple(leaks))

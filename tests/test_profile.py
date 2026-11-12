"""Profiling (DESIGN2 §4.7): where the tests' time and memory went, line by line as scalene measured it, summed up by
design part beside the run before. A view: nothing in it breaks or asks."""

import json

from test_tools import build

from zigdag import verifies
from zigdag.adapters.python.profiler import read_profile
from zigdag.cli import plans
from zigdag.cli.files import from_disk
from zigdag.core.codec import Unreadable
from zigdag.adapters.adapter import Presence
from zigdag.adapters.known import adapters
from zigdag.core.names import ProjectRoot
from zigdag.core.settings import Settings

ADAPTERS = adapters(Settings(), Presence.ABSENT)


def scalene(root, elapsed: float, core: float, tests: float) -> str:
    """A profile as scalene writes it, with the time shares given to shop.core.charge and to a test."""
    def lines(*pairs):
        return [{"lineno": n, "n_cpu_percent_python": t, "n_cpu_percent_c": 0.0, "n_sys_percent": 0.0,
                 "n_malloc_mb": t / 10} for n, t in pairs]
    return json.dumps({"elapsed_time_sec": elapsed, "max_footprint_mb": 40.0, "files": {
        str(root / "src/shop/core.py"): {"lines": lines((5, core), (6, 0.0)),
                                         "leaks": {"6": {"likelihood": 0.99, "velocity_mb_s": 1.5}}},
        str(root / "tests/test_shop.py"): {"lines": lines((3, tests))},
        "/usr/lib/python3/site.py": {"lines": lines((1, 1.0))}}})


@verifies("zigdag.adapters.python#profile")
def test_a_profile_is_read_line_by_line_with_paths_the_project_names(tmp_path):
    profile = read_profile(scalene(tmp_path, 2.0, 30.0, 5.0), ProjectRoot(tmp_path))
    assert (profile.elapsed, profile.peak) == (2.0, 40.0)
    assert [(line.span.path, line.span.line, line.time) for line in profile.lines] == [
        ("src/shop/core.py", 5, 30.0), ("tests/test_shop.py", 3, 5.0), ("/usr/lib/python3/site.py", 1, 1.0)]
    assert isinstance(read_profile("{}", ProjectRoot(tmp_path)), Unreadable)


@verifies("zigdag.cli.plans#costs")
def test_each_part_is_shown_beside_what_it_cost_in_the_run_before(tmp_path):
    root = build(tmp_path)
    a = plans.analysis(from_disk(root))
    shown = plans.costs(a, ADAPTERS, ProjectRoot(root), scalene(root, 3.0, 60.0, 5.0), scalene(root, 2.0, 30.0, 5.0)).out[0]
    lines = shown.splitlines()
    assert lines[0] == "the tests ran for 3.0 s, holding at most 40 MB at once; the run before, 2.0 s and 40 MB"
    core = next(line for line in lines if line.startswith("shop.core"))
    assert "0.60 s → 1.80 s" in core  # its CPU time: 30% of 2 s, then 60% of 3 s
    assert "30% → 60%" in core and "3.0 MB → 6.0 MB" in core
    tests = next(line for line in lines if line.startswith("the tests  "))  # the row, not the line above the table
    assert "0.10 s → 0.15 s" in tests and "5% →" not in tests  # the same share of a longer run
    assert any(line.startswith("outside the project") for line in lines)
    assert lines[-1].startswith("To see line by line") and "scalene view .zigdag/profile.json" in lines[-1]


def test_without_a_profile_it_says_how_to_make_one(tmp_path):
    a = plans.analysis(from_disk(build(tmp_path)))
    told = plans.costs(a, ADAPTERS, ProjectRoot(tmp_path), None, None)
    assert told.exit == plans.REFUSED and "run zigdag profile" in told.err[0]


@verifies("zigdag.cli.plans#costs")
def test_a_line_the_profiler_suspects_of_leaking_is_shown_with_its_part(tmp_path):
    root = build(tmp_path)
    a = plans.analysis(from_disk(root))
    lines = plans.costs(a, ADAPTERS, ProjectRoot(root), scalene(root, 3.0, 60.0, 5.0), None).out[0].splitlines()
    leak = lines[lines.index("suspected memory leaks, as scalene judges them:") + 1]
    assert leak.split() == ["src/shop/core.py:6", "shop.core", "99%", "likely", "growing", "1.50", "MB/s"]

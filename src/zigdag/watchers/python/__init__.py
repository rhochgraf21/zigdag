"""The Python watcher, as a pytest plugin: `zigdag test` runs the project's tests with `-p zigdag.watchers.python`
and the plan in the ZIGDAG_WATCH environment variable. Without a plan, the plugin does nothing.
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

from _pytest.runner import runtestprotocol  # runs a test without reporting it

import deal

from zigdag.adapters.python import apis
from zigdag.adapters.python.tests import test_module
from zigdag.core.code import TestId
from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath
from zigdag.core.settings import PLAN_FILE
from zigdag.adapters.python.observed import Recording
from zigdag.core.texts import Say
from zigdag.core.watch import PLAN_VARIABLE, LastRun, WatchPlan
from zigdag.watchers.python.watcher import Watcher

NAME = "zigdag-watcher"
_NODE_SEPARATOR = "::"
_PARAMETERS = "["  # where a parametrised test's own id starts: test_price[5]
_TERMINAL = "terminalreporter"  # pytest's plugin that writes to the terminal
_TOLD = "zigdag:"  # starts each line the watcher tells, so it is not taken for pytest's own
_PARTIAL = ".partial"  # the suffix of a file while it is being written
_STREAMS = (("capstdout", apis.STDOUT, "standard output"), ("capstderr", apis.STDERR, "standard error"),
            ("caplog", apis.STDERR, "a log record"))


def pytest_configure(config) -> None:  # noqa: ANN001 (pytest's own types are not imported)
    plan_path = os.environ.get(PLAN_VARIABLE)
    if not plan_path or hasattr(config, "workerinput"):  # a pytest-xdist worker: watching needs one process
        return
    plan_file = Path(plan_path).resolve()
    root = plan_file.parents[len(Path(PLAN_FILE).parts) - 1]
    plan = WatchPlan.from_text(plan_file.read_text(encoding="utf-8"))
    if isinstance(plan, Unreadable):
        print(f"zigdag: the watch plan {plan_file} could not be read ({plan.say}), so nothing is watched",
              file=sys.stderr)
        return
    config.pluginmanager.register(_Hooks(Watcher(plan, root), Path(config.rootpath), root), NAME)


class _Hooks:
    """The pytest hooks that tell the watcher when the run and each test start and end."""

    def __init__(self, watcher: Watcher, rootpath: Path, root: Path):
        self.watcher = watcher
        self.rootpath = rootpath
        self.root = root

    @deal.ensure(lambda self, nodeid, result: _PARAMETERS not in result[0].partition(_NODE_SEPARATOR)[2])
    def _test(self, nodeid: str) -> tuple[TestId, RecordPath]:
        file, *names = nodeid.split(_NODE_SEPARATOR)
        path = RecordPath(os.path.relpath(self.rootpath / file, self.root).replace(os.sep, "/"))
        name = _NODE_SEPARATOR.join(names).split(_PARAMETERS)[0]
        return TestId(f"{test_module(path)}{_NODE_SEPARATOR}{name}"), path

    def pytest_sessionstart(self, session) -> None:  # noqa: ANN001
        self.watcher.start()

    def pytest_runtest_logstart(self, nodeid: str, location) -> None:  # noqa: ANN001
        self.watcher.begin(*self._test(nodeid))

    def pytest_runtest_logreport(self, report) -> None:  # noqa: ANN001
        for attribute, effect, where in _STREAMS:
            self.watcher.captured(getattr(report, attribute, ""), effect, where)

    def pytest_runtest_logfinish(self, nodeid: str, location) -> None:  # noqa: ANN001
        self.watcher.end()

    def pytest_sessionfinish(self, session, exitstatus) -> None:  # noqa: ANN001
        items: dict[TestId, list] = {}
        for item in session.items:
            items.setdefault(self._test(item.nodeid)[0], []).append(item)

        def rerun(test: TestId) -> bool:
            """Run a test again, every parametrised case of it, telling pytest nothing: whether it passed."""
            return all(not report.failed for item in items.get(test, ())
                       for report in runtestprotocol(item, log=False, nextitem=None))

        reporter = session.config.pluginmanager.get_plugin(_TERMINAL)

        def tell(say: Say) -> None:
            """A line for the person running the tests: pytest's own when it shows any, else standard error."""
            line = f"{_TOLD} {say}"
            if reporter is not None:
                reporter.write_line(line)
            else:
                print(line, file=sys.stderr, flush=True)

        recording = self.watcher.finish(rerun, functools.partial(_written, self.root / self.watcher.plan.carried), tell)
        _written(self.root / self.watcher.plan.observed, recording)


def _written(path: Path, value: Recording | LastRun) -> None:
    """Write what the watcher hands over whole or not at all, so that a run stopped while writing leaves the last
    complete version, which the next run can still read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + _PARTIAL)
    partial.write_text(value.to_text(), encoding="utf-8")
    partial.replace(path)

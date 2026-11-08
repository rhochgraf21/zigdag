"""What the Python watcher sees while a project's tests run (DESIGN2 §4.5), charged to the code that did it.

- **Effects** come from audit hooks (files, processes, sockets, the environment) and from wrapping the APIs that
  raise no audit event (the clock, randomness, the console, environment reads).
- **Calls, values and errors crossing a boundary** come from sys.monitoring: each call into the project's code is
  checked for which design parameter it comes from.
- **Changes to recorded structures** come from wrapping their __setattr__ and __delattr__, and from comparing a
  structure's contents before and after a call into another component (changes in place).
- **Protected values** are remembered as they are made, and looked for in what the code writes.
- **Calls into code that may have no effects** are recorded with a copy of their arguments, to be made again.

Everything an effect or a change is charged to is the innermost frame of the project's own code; the import system's
own work is never charged. Nothing is stopped: the run is watched, and reported.
"""

from __future__ import annotations

import builtins
import copy
import functools
import inspect
import logging
import os
import random
import re
import sys
import threading
import time
import typing
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import CodeType, FrameType

from zigdag.adapters.python import apis
from zigdag.adapters.python.observed import COLLECTION, Ran, Recording
from zigdag.core.code import (
    RETURNED,
    Access,
    AccessKind,
    Call,
    Cases,
    Crossing,
    Dependency,
    DependencyKind,
    EffectStart,
    Escape,
    Leak,
    Mutant,
    Outcome,
    Place,
    Qualified,
    Replay,
    SymbolName,
    TestId,
    TypeOf,
    Verdict,
)
from zigdag.core.effects import Effect
from zigdag.core.findings import Digest, RecordPath, Span, digest_of
from zigdag.core.names import CodePath, FrName
from zigdag.core.watch import WatchPlan
from zigdag.watchers.python import mutants
from zigdag.watchers.python.values import conforms, fields_of, fingerprint, type_name

try:
    import deal  # runs contracts on generated inputs, when the project has it
except ImportError:
    deal = None

MIN_CANARY = 5  # shorter protected text is not looked for: it would match by chance
CANARIES = 2000  # at most this many protected values are remembered
RECORDED_CALLS = 10  # calls recorded per operation, to be made again
CASES, SEED = 50, 0  # generated inputs per contract, and their fixed seed
READ_BACK = 1 << 20  # at most this much of a written file is read back to look for protected values
_TOOLS = (2, 3, 4)  # sys.monitoring tool ids to try, after the debugger's and coverage's
_IMPORT_SYSTEM = "<frozen importlib"
# Test tooling: what it does on the project's behalf, such as timing a test or tracing its branches, is its own.
_TOOLING = frozenset({"_pytest", "pytest", "pluggy", "hypothesis", "_hypothesis_pytestplugin", "coverage",
                      "_hypothesis_globals"})
_PROCESS_EVENTS = frozenset({"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                             "os.forkpty", "pty.spawn", "os.startfile"})
_LAZY = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE
_IMPORT = "import"
_NOT_ESCAPES = (GeneratorExit, StopIteration, StopAsyncIteration, KeyboardInterrupt)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODES = frozenset("wax+")
_COLOURS = re.compile(r"\x1b\[[0-9;]*m")  # terminal colour codes, as some libraries put in their messages
DETAIL = 300  # at most this much of an error's message is kept

_AUDITED: Mapping[str, Effect] = {
    **dict.fromkeys(["os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod", "os.chown", "os.truncate",
                     "os.utime", "os.link", "os.symlink", "shutil.copyfile", "shutil.copytree", "shutil.move",
                     "shutil.rmtree", "shutil.make_archive", "shutil.unpack_archive"], apis.WRITE),
    **dict.fromkeys(["os.listdir", "os.scandir", "glob.glob"], apis.READ),
    **dict.fromkeys(["subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                     "os.forkpty", "os.kill", "os.killpg", "pty.spawn", "os.startfile"], apis.SYSCALL),
    **dict.fromkeys(["socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname",
                     "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg", "http.client.connect",
                     "urllib.Request", "ftplib.connect", "smtplib.connect", "poplib.connect", "imaplib.open"],
                    apis.NETWORK),
    **dict.fromkeys(["os.putenv", "os.unsetenv"], apis.ENV),
}
_OPEN = "open"

# The APIs that raise no audit event, wrapped where they are looked up: (module, attribute, effect).
_WRAPPED: tuple[tuple[object, str, Effect], ...] = (
    *((time, n, apis.TIME) for n in ("time", "time_ns", "monotonic", "monotonic_ns", "perf_counter",
                                     "perf_counter_ns", "localtime", "gmtime", "ctime")),
    *((random, n, apis.RANDOM) for n in ("random", "randint", "randrange", "choice", "choices", "shuffle", "sample",
                                         "uniform", "gauss", "getrandbits", "randbytes")),
    (os, "urandom", apis.RANDOM),
    (os._Environ, "__getitem__", apis.ENV),  # the class of os.environ, named without touching the environment
)


@dataclass(frozen=True)
class _Code:
    """A code object of the project's own: where it runs, whose it is, and the file it is in."""

    place: Place
    dp: FrName | None
    path: RecordPath

    @property
    def operation(self) -> Qualified:
        return Qualified(str(self.place))


_TEST = "test"  # a caller in a test file: outside every design parameter


@dataclass
class _Snapshot:
    """A guarded structure passed into another component: its fields' identities and contents on the way in."""

    type: Qualified
    value: object
    fields: dict[str, tuple[int, str | None]]


@dataclass
class _Pending:
    """The work left for when a watched call returns."""

    code: _Code
    caller: _Code | str | None
    span: Span  # the call
    hints: Mapping[str, object] = field(default_factory=dict)
    crossing: bool = False  # it came from another design parameter
    snapshots: list[_Snapshot] = field(default_factory=list)
    replay: tuple[Callable, tuple, dict] | None = None


@dataclass
class _Recorded:
    """One call into code that may have no effects, to be made again."""

    function: Callable
    args: tuple
    kwargs: dict
    result: str | None  # the result's fingerprint, or the error it raised; None when it cannot be compared
    test: TestId
    span: Span


def _symbol(code: CodeType) -> SymbolName | None:
    """The symbol a code object belongs to, as the code model names it: a nested function counts as the function
    around it, and module or class bodies as the module."""
    if not code.co_flags & inspect.CO_OPTIMIZED:
        return None
    parts = []
    for part in code.co_qualname.split("."):
        if part.startswith("<"):
            break
        parts.append(part)
    return SymbolName(".".join(parts)) if parts else None


class Watcher:
    def __init__(self, plan: WatchPlan, root: Path):
        self.plan = plan
        self.root = root
        mine = str(Path(__file__).resolve().parent)  # the watcher's own code, which it does not watch
        self.units = {os.path.realpath(root / path): (path, unit) for path, unit in plan.sources.items()
                      if not os.path.realpath(root / path).startswith(mine)}
        self.unwatched = tuple(sorted(unit for path, unit in plan.sources.items()
                                      if os.path.realpath(root / path).startswith(mine)))
        self.test_files = {os.path.realpath(root / path) for path in plan.tests}
        self.replayed = frozenset(plan.replayed)
        self.mutated = frozenset(m.place for m in plan.mutated)
        self.reached: dict[Place, set[TestId]] = {}  # each function to mutate, and the tests that ran it
        self.protected = frozenset(plan.protected)
        # named types by (module, name), so that a call of one is matched without making a named type itself
        self.protected_types = {tuple(t.rsplit(".", 1)): t for t in plan.protected}
        self.owners: dict[Qualified, FrName] = {g.type: g.owner for g in plan.guarded}
        self.guarded: dict[type, Qualified] = {}
        self.codes: dict[CodeType, _Code | str | None] = {}  # the project's code, a test's (_TEST), or neither
        self.hints: dict[CodeType, tuple[Callable | None, Mapping[str, object]]] = {}
        self.local = threading.local()
        self.active = False
        self.test: TestId = COLLECTION
        self.test_file: RecordPath = RecordPath("")
        self.ran: set[CodePath] = set()
        self.processes = False  # the current test started another process
        self.written: dict[str, tuple[_Code, int]] = {}
        self.initializing: set[int] = set()
        self.canaries: dict[str, Qualified] = {}
        self.pending: dict[FrameType, _Pending] = {}
        self.recorded: dict[Place, list[_Recorded]] = {}
        self.uncopyable: dict[Place, Replay] = {}
        self.tool: int | None = None
        self.files: dict[RecordPath, Digest] = {}
        self.runs: list[Ran] = []
        self.effects: dict[tuple, EffectStart] = {}
        self.dependencies: dict[tuple, Dependency] = {}
        self.calls: dict[tuple, Call] = {}
        self.accesses: dict[tuple, Access] = {}
        self.crossings: dict[tuple, Crossing] = {}
        self.escapes: dict[tuple, Escape] = {}
        self.leaks: dict[tuple, Leak] = {}

    # ---- whose code is this ------------------------------------------------------------------------------------

    def whose(self, code: CodeType) -> _Code | str | None:
        """The project's code with where it runs, _TEST for a test's code, or None for anyone else's."""
        known = self.codes.get(code, False)
        if known is not False:
            return known
        real = os.path.realpath(code.co_filename)
        found = self.units.get(real)
        info: _Code | str | None = _TEST if real in self.test_files else None
        if found is not None:
            path, unit = found
            info = _Code(Place(unit, _symbol(code)), self.plan.owners.get(unit), path)
        self.codes[code] = info
        return info

    def code(self, code: CodeType) -> _Code | None:
        info = self.whose(code)
        return info if isinstance(info, _Code) else None

    def innermost(self, frame: FrameType | None) -> tuple[_Code, int] | None:
        """The project's own code nearest the top of the stack, and its line. Work the import system or the test
        tooling does on the code's behalf, such as reading module files or timing a test, is charged to nobody."""
        while frame is not None:
            info = self.code(frame.f_code)
            if info is not None:
                return info, frame.f_lineno
            if frame.f_code.co_filename.startswith(_IMPORT_SYSTEM) or _tooling(frame):
                return None
            frame = frame.f_back
        return None

    def caller(self, frame: FrameType | None) -> tuple[_Code | str | None, int, RecordPath]:
        """Who made a call: the project's own code, a test, or neither (pytest, a library)."""
        while frame is not None:
            info = self.whose(frame.f_code)
            if isinstance(info, _Code):
                return info, frame.f_lineno, info.path
            if info == _TEST:
                return _TEST, frame.f_lineno, RecordPath(os.path.relpath(frame.f_code.co_filename, self.root))
            frame = frame.f_back
        return None, 0, RecordPath("")

    @property
    def busy(self) -> bool:
        return getattr(self.local, "busy", False)

    def watching(self) -> bool:
        return self.active and not self.busy

    # ---- effects -----------------------------------------------------------------------------------------------

    def effect_at(self, frame: FrameType | None, effect: Effect, via: str) -> _Code | None:
        found = self.innermost(frame)
        if found is None:
            return None
        info, line = found
        key = (info.place, effect)
        if key not in self.effects:
            self.effects[key] = EffectStart(info.place, effect, via, Span(info.path, line, 1), self.test)
        return info

    def audit(self, event: str, args: tuple) -> None:
        effect = _AUDITED.get(event)
        if effect is None and event not in (_OPEN, _IMPORT):
            return
        if not self.watching():
            return
        if event in _PROCESS_EVENTS:
            self.processes = True
        self.local.busy = True
        try:
            frame = sys._getframe(1)
            if event == _IMPORT:
                self._imported(frame, str(args[0]))
            elif event == _OPEN:
                self._opened(frame, args)
            else:
                self.effect_at(frame, effect, event)
        finally:
            self.local.busy = False

    def _opened(self, frame: FrameType, args: tuple) -> None:
        path, mode, flags = (tuple(args) + (None, None, 0))[:3]
        writes = bool(set(mode) & _WRITE_MODES) if isinstance(mode, str) else bool((flags or 0) & _WRITE_FLAGS)
        info = self.effect_at(frame, apis.WRITE if writes else apis.READ, _OPEN)
        if writes and info is not None and isinstance(path, str | bytes | os.PathLike):
            self.written.setdefault(os.fsdecode(path), (info, frame.f_lineno))

    def _imported(self, frame: FrameType, module: str) -> None:
        """An import the project's own code made: a library importing its own parts is the library's business."""
        while frame is not None and frame.f_code.co_filename.startswith(_IMPORT_SYSTEM):
            frame = frame.f_back
        info = self.code(frame.f_code) if frame is not None else None
        if info is None:
            return
        line = frame.f_lineno
        span = Span(info.path, line, 1)
        self.dependencies.setdefault((info.place, module), Dependency(
            info.place, Qualified(module), DependencyKind.IMPORT, span, self.test))
        if info.place.symbol is not None:  # importing while running, rather than as the module loads
            self.effects.setdefault((info.place, apis.IMPORT), EffectStart(
                info.place, apis.IMPORT, f"import {module}", span, self.test))

    def wrap(self, owner: object, name: str, effect: Effect) -> None:
        original = getattr(owner, name)
        watcher = self
        via = f"{getattr(owner, '__name__', type(owner).__name__)}.{name}"

        @functools.wraps(original)
        def watched(*args, **kwargs):
            if watcher.watching():
                watcher.local.busy = True
                try:
                    watcher.effect_at(sys._getframe(1), effect, via)
                finally:
                    watcher.local.busy = False
            return original(*args, **kwargs)

        setattr(owner, name, watched)

    def printed(self, original: Callable) -> Callable:
        watcher = self

        @functools.wraps(original)
        def print_(*args, **kwargs):
            if watcher.watching():
                target = kwargs.get("file")
                effect = apis.STDOUT if target is None or target is sys.stdout else (
                    apis.STDERR if target is sys.stderr else apis.WRITE)
                watcher.local.busy = True
                try:
                    watcher.effect_at(sys._getframe(1), effect, "print")
                finally:
                    watcher.local.busy = False
            return original(*args, **kwargs)

        return print_

    def logged(self, record: logging.LogRecord) -> None:
        if not self.watching():
            return
        self.local.busy = True
        try:
            info = self.effect_at(sys._getframe(1), apis.STDERR, apis.LOGGING)
            self.search(record.getMessage(), apis.STDERR, "a log record", info, record.lineno)
        finally:
            self.local.busy = False

    # ---- protected values --------------------------------------------------------------------------------------

    def remember(self, value: object, kind: Qualified) -> None:
        text = str(value) if isinstance(value, str | int | float | bytes) else None
        if text is not None and len(text) >= MIN_CANARY and len(self.canaries) < CANARIES:
            self.canaries.setdefault(text, kind)

    def search(self, text: str, effect: Effect, where: str, info: _Code | None, line: int) -> None:
        for canary, kind in self.canaries.items():
            if canary in text:
                at = info.place if info is not None else None
                span = Span(info.path, line, 1) if info is not None else None
                self.leaks.setdefault((kind, effect, where), Leak(kind, effect, where, at, span, self.test))

    def new_type_call(self, new_type: typing.NewType, value: object) -> object:
        name = self.protected_types.get((new_type.__module__, new_type.__qualname__))
        if name is not None and self.watching():
            self.remember(value, name)
        return value  # a named type's call is the identity function

    # ---- structures --------------------------------------------------------------------------------------------

    def guard(self) -> None:
        """Wrap each recorded structure whose module has been imported, once."""
        for type_name_, owner in self.owners.items():
            cls = _find(type_name_)
            if isinstance(cls, type) and cls not in self.guarded:
                self.guarded[cls] = type_name_
                self._guard(cls, type_name_)

    def _guard(self, cls: type, name: Qualified) -> None:
        watcher = self
        set_original, del_original, init_original = cls.__setattr__, cls.__delattr__, cls.__init__
        protected = name in self.protected

        def __setattr__(obj, attr, value):
            set_original(obj, attr, value)
            watcher.changed(sys._getframe(1), name, obj, attr)

        def __delattr__(obj, attr):
            del_original(obj, attr)
            watcher.changed(sys._getframe(1), name, obj, attr)

        @functools.wraps(init_original)
        def __init__(obj, *args, **kwargs):
            watcher.initializing.add(id(obj))
            try:
                init_original(obj, *args, **kwargs)
            finally:
                watcher.initializing.discard(id(obj))
            if protected and watcher.watching():
                for value in (fields_of(obj) or {}).values():
                    watcher.remember(value, name)

        cls.__setattr__, cls.__delattr__, cls.__init__ = __setattr__, __delattr__, __init__

    def changed(self, frame: FrameType, kind: Qualified, obj: object, attr: str) -> None:
        if id(obj) in self.initializing or not self.watching():
            return
        self.local.busy = True
        try:
            found = self.innermost(frame)
            if found is not None:
                info, line = found
                self.accesses.setdefault((info.place, kind, attr), Access(
                    info.place, TypeOf(kind, False), attr, AccessKind.UPDATES, False, Span(info.path, line, 1),
                    self.test))
        finally:
            self.local.busy = False

    def _snapshots(self, values: Iterable[object], callee: _Code) -> list[_Snapshot]:
        out = []
        for value in values:
            kind = next((self.guarded[k] for k in type(value).__mro__ if k in self.guarded), None)
            if kind is None or self.owners.get(kind) == callee.dp:
                continue
            contents = fields_of(value) or {}
            out.append(_Snapshot(kind, value, {k: (id(v), fingerprint(v)) for k, v in contents.items()}))
        return out

    def _compare(self, snapshot: _Snapshot, callee: _Code, line: int) -> None:
        contents = fields_of(snapshot.value) or {}
        for name, (before_id, before) in snapshot.fields.items():
            now = contents.get(name)
            if id(now) == before_id and before is not None and fingerprint(now) != before:
                self.accesses.setdefault((callee.place, snapshot.type, name), Access(
                    callee.place, TypeOf(snapshot.type, False), name, AccessKind.UPDATES, True,
                    Span(callee.path, line, 1), self.test))

    # ---- calls -------------------------------------------------------------------------------------------------

    def started(self, code: CodeType, offset: int) -> object:
        info = self.code(code)
        if info is None:
            return sys.monitoring.DISABLE
        if not self.watching():
            return None
        self.local.busy = True
        try:
            self.ran.add(info.place.unit)
            if info.place in self.mutated and self.test != COLLECTION:
                self.reached.setdefault(info.place, set()).add(self.test)
            if info.place.symbol is not None:
                self._enter(sys._getframe(1), code, info)
        finally:
            self.local.busy = False
        return None

    def _enter(self, frame: FrameType, code: CodeType, info: _Code) -> None:
        caller, line, path = self.caller(frame.f_back)
        caller_dp = caller.dp if isinstance(caller, _Code) else caller
        if caller is None or caller_dp == info.dp:
            return
        pending = _Pending(info, caller, Span(path, line, 1))
        values = [frame.f_locals.get(n) for n in _parameters(code)]
        if isinstance(caller, _Code):
            self.calls.setdefault((caller.place, info.operation), Call(
                caller.place, info.operation, pending.span, self.test))
            pending.crossing = True
            function, pending.hints = self._hints(frame, code)
            self._crossings(info, code, frame, pending)
        pending.snapshots = self._snapshots(values, info)
        if info.place in self.replayed:
            self._record(frame, code, info, pending)
        if pending.crossing or pending.snapshots or pending.replay:
            self.pending[frame] = pending

    def _hints(self, frame: FrameType, code: CodeType) -> tuple[Callable | None, Mapping[str, object]]:
        known = self.hints.get(code)
        if known is None:
            function = _function(frame, code)
            try:
                hints = typing.get_type_hints(function) if function is not None else {}
            except Exception:  # noqa: BLE001 (annotations that cannot be resolved are not checked)
                hints = {}
            known = self.hints[code] = (function, hints)
        return known

    def _crossing(self, info: _Code, where: str, value: object, pending: _Pending) -> None:
        hint = pending.hints.get(where if where != RETURNED else "return")
        fits = conforms(value, hint) if hint is not None else None
        if hint is not None and hint not in (typing.Any, object) and fits is not False:
            return  # the annotation says what crosses, and the value fits it: the static check judges the rest
        actual = Qualified(type_name(value))
        key = (info.place, where, actual, fits is not False)
        if key not in self.crossings:
            expected = None if hint is None else _hint_text(hint)
            self.crossings[key] = Crossing(info.place, where, expected, actual, fits is not False, pending.span,
                                           self.test)

    def _crossings(self, info: _Code, code: CodeType, frame: FrameType, pending: _Pending) -> None:
        names = _parameters(code)
        if "." in (info.place.symbol or "") and names and names[0] in ("self", "cls"):
            names = names[1:]
        for name in names:
            self._crossing(info, name, frame.f_locals.get(name), pending)

    def _record(self, frame: FrameType, code: CodeType, info: _Code, pending: _Pending) -> None:
        if len(self.recorded.get(info.place, ())) >= RECORDED_CALLS or info.place in self.uncopyable:
            return
        if code.co_flags & _LAZY:  # what a generator or coroutine gives is consumed by its caller as it runs
            return
        function, _ = self._hints(frame, code)
        if function is None:
            return
        args, kwargs = _arguments(code, frame)
        try:
            pending.replay = (function, *copy.deepcopy((args, kwargs)))
        except Exception as e:  # noqa: BLE001 (any value may refuse to be copied)
            self.uncopyable[info.place] = Replay(info.place, Verdict.NOT_COPYABLE, f"its arguments cannot be copied "
                                                 f"({type(e).__name__})", Span(info.path, code.co_firstlineno, 1),
                                                 self.test)

    def returned(self, code: CodeType, offset: int, value: object) -> object:
        if self.code(code) is None:
            return sys.monitoring.DISABLE
        self._leave(sys._getframe(1), code, value, None)
        return None

    def unwound(self, code: CodeType, offset: int, error: BaseException) -> None:
        if self.pending:
            self._leave(sys._getframe(1), code, None, error)

    def _leave(self, frame: FrameType, code: CodeType, value: object, error: BaseException | None) -> None:
        pending = self.pending.pop(frame, None)
        if pending is None or not self.watching():
            return
        self.local.busy = True
        try:
            info = pending.code
            if pending.crossing and error is None:
                self._crossing(info, RETURNED, value, pending)
            elif pending.crossing and not isinstance(error, _NOT_ESCAPES):
                error_type = Qualified(type_name(error))
                self.escapes.setdefault((info.place, error_type), Escape(info.place, error_type, pending.span,
                                                                         self.test))
            for snapshot in pending.snapshots:
                self._compare(snapshot, info, code.co_firstlineno)
            if pending.replay is not None and not isinstance(value, Iterator):  # an iterator is consumed once
                function, args, kwargs = pending.replay
                result = _outcome(value, error)
                self.recorded.setdefault(info.place, []).append(_Recorded(
                    function, args, kwargs, result, self.test, Span(info.path, code.co_firstlineno, 1)))
        finally:
            self.local.busy = False

    # ---- the run -----------------------------------------------------------------------------------------------

    def start(self) -> None:
        for path in (*self.plan.sources, *self.plan.tests):
            full = self.root / path
            if full.is_file():
                self.files[path] = digest_of(full.read_text(encoding="utf-8"))
        sys.addaudithook(self.audit)
        for owner, name, effect in _WRAPPED:
            self.wrap(owner, name, effect)
        builtins.print = self.printed(builtins.print)
        self.wrap(builtins, "input", apis.STDIN)
        if self.protected_types:
            typing.NewType.__call__ = lambda new_type, value: self.new_type_call(new_type, value)
        logging.getLogger().addHandler(_LogWatch(self))
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is not None:
            self.tool = next((t for t in _TOOLS if monitoring.get_tool(t) is None), None)
        if self.tool is not None:
            events = monitoring.events
            monitoring.use_tool_id(self.tool, "zigdag")
            monitoring.register_callback(self.tool, events.PY_START, self.started)
            monitoring.register_callback(self.tool, events.PY_RETURN, self.returned)
            monitoring.register_callback(self.tool, events.PY_UNWIND, self.unwound)
            monitoring.set_events(self.tool, events.PY_START | events.PY_RETURN | events.PY_UNWIND)
        self.active = True

    def begin(self, test: TestId, file: RecordPath) -> None:
        self.guard()
        self.test, self.test_file = test, file
        self.ran, self.written, self.processes = set(), {}, False

    def captured(self, text: str, effect: Effect, where: str) -> None:
        """Text a test phase wrote to the console, as pytest captured it."""
        if text and self.canaries:
            self.search(text, effect, where, None, 0)

    def end(self) -> None:
        for path, (info, line) in sorted(self.written.items()):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read(READ_BACK)
            except OSError:
                continue
            shown = os.path.relpath(path, self.root) if os.path.isabs(path) else path
            self.search(text, apis.WRITE, shown, info, line)
        self.runs.append(Ran(self.test, self.test_file, frozenset(self.ran), self.processes))
        self.test = COLLECTION

    def cases(self, place: Place) -> Cases | None:
        function = _find(f"{place.unit}.{place.symbol}")
        code = getattr(inspect.unwrap(function), "__code__", None) if callable(function) else None
        info = self.code(code) if code is not None else None
        return _cases(place, Span(info.path, code.co_firstlineno, 1)) if info is not None else None

    def mutate(self, rerun: mutants.Rerun) -> tuple[list[Mutant], str | None]:
        """The mutants of each planned function with a contract, judged by its cases and the tests that ran it; or why
        none could be made."""
        if not self.plan.mutated:
            return [], None
        why = mutants.unavailable()
        if why is not None:
            return [], why
        out: list[Mutant] = []
        for target in self.plan.mutated:
            place = target.place
            function = _find(f"{place.unit}.{place.symbol}")
            code = getattr(inspect.unwrap(function), "__code__", None) if callable(function) else None
            info = self.code(code) if code is not None else None
            if info is not None:
                span = Span(info.path, code.co_firstlineno, 1)
                tests = tuple(sorted(self.reached.get(place, ())))
                out += mutants.mutants(target, function, span, functools.partial(_cases, place, span), tests, rerun)
        return out, None

    def finish(self, rerun: mutants.Rerun) -> Recording:
        """Stop watching, make the recorded calls again, run the contracts and their mutants, and hand over what was
        seen."""
        self.active = False
        if self.tool is not None:
            sys.monitoring.set_events(self.tool, 0)
            sys.monitoring.free_tool_id(self.tool)
        self.local.busy = True
        replays = [*self.uncopyable.values(), *(_replay(place, calls) for place, calls in sorted(
            self.recorded.items(), key=lambda kv: str(kv[0])))]
        cases = [self.cases(place) for place in self.plan.contracts]
        made, unavailable = self.mutate(rerun)
        return Recording(
            files=self.files, runs=tuple(self.runs), effects=tuple(self.effects.values()),
            dependencies=tuple(self.dependencies.values()), calls=tuple(self.calls.values()),
            accesses=tuple(self.accesses.values()), crossings=tuple(self.crossings.values()),
            escapes=tuple(self.escapes.values()), leaks=tuple(self.leaks.values()), replays=tuple(replays),
            cases=tuple(c for c in cases if c is not None), mutants=tuple(made), mutation_unavailable=unavailable,
            unwatched=self.unwatched)


class _LogWatch(logging.Handler):
    """Every log record the code emits: its effect, and any protected text in it."""

    def __init__(self, watcher: Watcher):
        super().__init__(logging.NOTSET)
        self.watcher = watcher

    def emit(self, record: logging.LogRecord) -> None:
        self.watcher.logged(record)


def _tooling(frame: FrameType) -> bool:
    return str(frame.f_globals.get("__name__", "")).partition(".")[0] in _TOOLING


def _find(name: str) -> object:
    """The object a qualified name names, if its module has been imported."""
    parts = name.split(".")
    for i in range(len(parts) - 1, 0, -1):
        module = sys.modules.get(".".join(parts[:i]))
        if module is not None:
            target: object = module
            for part in parts[i:]:
                target = getattr(target, part, None)
            return target
    return None


def _parameters(code: CodeType) -> tuple[str, ...]:
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS) + bool(code.co_flags & inspect.CO_VARKEYWORDS)
    return code.co_varnames[:count]


def _arguments(code: CodeType, frame: FrameType) -> tuple[tuple, dict]:
    """The arguments a call was made with, read back from the frame as it starts."""
    names, local = code.co_varnames, frame.f_locals
    at = code.co_argcount + code.co_kwonlyargcount
    args = [local[n] for n in names[:code.co_argcount]]
    kwargs = {n: local[n] for n in names[code.co_argcount:at]}
    if code.co_flags & inspect.CO_VARARGS:
        args += list(local[names[at]])
        at += 1
    if code.co_flags & inspect.CO_VARKEYWORDS:
        kwargs.update(local[names[at]])
    return tuple(args), kwargs


def _function(frame: FrameType, code: CodeType) -> Callable | None:
    """The function whose code this is, found by its qualified name; None for nested or replaced functions."""
    parts = code.co_qualname.split(".")
    if any(p.startswith("<") for p in parts):
        return None
    target = frame.f_globals.get(parts[0])
    for part in parts[1:]:
        target = getattr(target, part, None)
    target = getattr(target, "__func__", target)
    inner = inspect.unwrap(target) if callable(target) else None
    return target if inner is not None and getattr(inner, "__code__", None) is code else None


def _said(error: BaseException) -> str:
    """An error as one plain line: its type and message, without colours."""
    return _COLOURS.sub("", f"{type(error).__name__}: {error}")[:DETAIL]


def _hint_text(hint: object) -> str:
    """An annotation as a person would write it."""
    if isinstance(hint, type | typing.NewType):
        return hint.__name__
    return str(hint).replace("typing.", "")


def _outcome(value: object, error: BaseException | None) -> str | None:
    return f"raised {type_name(error)}" if error is not None else fingerprint(value)


def _replay(place: Place, calls: list[_Recorded]) -> Replay:
    """Each recorded call made again, last first, with a fresh copy of its arguments."""
    verdict, detail = Verdict.SAME, f"{len(calls)} calls made again gave the same results"
    for i, call in enumerate(reversed(calls)):
        try:
            args, kwargs = copy.deepcopy((call.args, call.kwargs))
        except Exception as e:  # noqa: BLE001
            return Replay(place, Verdict.NOT_COPYABLE, f"its arguments cannot be copied ({type(e).__name__})",
                          call.span, call.test)
        try:
            again = _outcome(call.function(*args, **kwargs), None)
        except Exception as e:  # noqa: BLE001 (raising is a result, compared like any other)
            again = _outcome(None, e)
        if call.result is None or again is None:
            verdict, detail = Verdict.NOT_COPYABLE, "its result has nothing that can be compared"
        elif again != call.result:
            return Replay(place, Verdict.DIFFERENT, f"the call from {call.test} gave a different result the second "
                          f"time", call.span, call.test)
    return Replay(place, verdict, detail, calls[0].span, calls[0].test)


def _cases(place: Place, span: Span) -> Cases:
    """A contract's operation run on generated inputs with a fixed seed (deal.cases)."""
    function = _find(f"{place.unit}.{place.symbol}")
    if deal is None:
        return Cases(place, Outcome.ERROR, "deal is not installed, so the contract was not run", span)
    try:
        generated = list(deal.cases(function, count=CASES, seed=SEED))
    except Exception as e:  # noqa: BLE001 (inputs that cannot be generated are reported, not raised)
        return Cases(place, Outcome.ERROR, f"inputs could not be generated: {_said(e)}", span)
    for case in generated:
        try:
            case()
        except Exception as e:  # noqa: BLE001
            return Cases(place, Outcome.FAILED, _said(e), span)
    return Cases(place, Outcome.PASSED, f"{len(generated)} generated cases held", span)

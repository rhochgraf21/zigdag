from __future__ import annotations

from arch import realize, realizes
from arch.realize.facts import Effect, Reach, Role, Roots, Snapshot, SourcePath, UnitName
from arch.realize.python.extract import extract


def effects(src: str, unit: str = "m"):
    f = extract(SourcePath("src/m.py"), src, UnitName(unit), Role.SOURCE)
    return {(e.symbol, e.effect) for e in f.effects}, {(c.symbol, c.callee) for c in f.calls}


@realizes("arch.realize.python.extract#AC2")
def test_direct_effects_from_resolved_names():
    found, _ = effects(
        "import os, subprocess\nfrom time import time as now\nfrom datetime import datetime\n"
        "def a():\n    return os.environ['X']\n"
        "def b():\n    subprocess.run(['ls'])\n"
        "def c():\n    return now(), datetime.now()\n"
        "def d(p):\n    print(open(p, 'w'))\n"
        "def e(p):\n    return open(p).read()\n"
        "def f(xs):\n    return sorted(xs)\n"
    )
    assert found == {("a", Effect.ENV), ("b", Effect.SUBPROCESS), ("c", Effect.TIME),
                     ("d", Effect.STDIO), ("d", Effect.FS_WRITE), ("e", Effect.FS_READ)}


def test_pathlib_methods_count_only_where_pathlib_is_used():
    with_pathlib, _ = effects("from pathlib import Path\ndef r(p):\n    return p.read_text()\n")
    without, _ = effects("def r(p):\n    return p.read_text()\n")
    assert with_pathlib == {("r", Effect.FS_READ)} and without == set()


@realizes("arch.realize.python.extract#AC3")
def test_dynamic_code_is_unknown_not_pure():
    found, _ = effects("import importlib\ndef a(s):\n    return eval(s)\ndef b(n):\n    return importlib.import_module(n)\n")
    assert found == {("a", Effect.UNKNOWN), ("b", Effect.UNKNOWN)}


@realizes("arch.realize.python.extract#AC6")
def test_calls_resolve_self_annotations_constructors_and_imports():
    _, calls = effects(
        "from pkg.ws import Workspace, find\n"
        "class C:\n    def a(self):\n        return self.b()\n    def b(self): ...\n"
        "def use(ws: Workspace | None):\n    return ws.facts()\n"
        "def build():\n    w = Workspace()\n    return w.design()\n"
        "def go():\n    return find(), helper\n"
        "def helper(): ...\n"
        "REGISTRY = [go]\n"
        "TABLE = dict(cb=go)\n",
    )
    assert {("C.a", "m.C.b"), ("use", "pkg.ws.Workspace.facts"), ("build", "pkg.ws.Workspace"),
            ("build", "pkg.ws.Workspace.design"), ("go", "pkg.ws.find")} <= calls
    assert not any(symbol == "<module>" and callee == "m.go" for symbol, callee in calls)  # stored, not run


@realizes("arch.realize#AC4")
def test_effects_propagate_through_calls_to_a_fixed_point():
    files = {
        "src/p/io.py": "def read(p):\n    return open(p).read()\n",
        "src/p/mid.py": "from p.io import read\n\ndef load(p):\n    return read(p)\n\ndef loop(n):\n    return again(n)\n\ndef again(n):\n    return loop(n) or load(n)\n",
        "src/p/top.py": "from p import mid\n\ndef main():\n    return mid.load('x')\n",
    }
    f = realize.extract(Snapshot({SourcePath(k): v for k, v in files.items()}, Roots(("src",), ())))
    eff = {(e.unit, e.symbol, e.reach is Reach.DIRECT, e.via) for e in f.effects if e.effect is Effect.FS_READ}
    assert ("p.io", "read", True, None) in eff
    assert ("p.mid", "load", False, "p.io.read") in eff
    assert ("p.top", "main", False, "p.mid.load") in eff
    assert {s for u, s, d, _ in eff if u == "p.mid"} == {"load", "loop", "again"}  # through the cycle too

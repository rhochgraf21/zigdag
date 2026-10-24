from __future__ import annotations

from arch import realize, realizes
from arch.realize.facts import Roots, Snapshot, SourcePath
from arch.realize.mapping import map_units
from arch.realize.python import PythonAdapter
from tests.conftest import NEED, component, graph

ROOTS = Roots((SourcePath("src"),), (SourcePath("tests"),))


def test_unit_names_follow_roots():
    name = PythonAdapter().unit_name
    assert name(SourcePath("src/app/core/__init__.py"), ROOTS) == "app.core"
    assert name(SourcePath("src/app/core/api.py"), ROOTS) == "app.core.api"
    assert name(SourcePath("tests/test_api.py"), ROOTS) == "tests.test_api"
    assert name(SourcePath("scripts/x.py"), ROOTS) is None
    assert name(SourcePath("src/my-app/x.py"), ROOTS) is None  # not importable


G = graph({
    "needs/n.md": NEED,
    "components/app.md": component(serves="n"),
    "components/app/core.md": component(serves="n"),
})


@realizes("arch.realize.mapping#AC1", "arch.realize.mapping#AC2", "arch.realize.mapping#AC4")
def test_longest_prefix_mapping_and_test_units():
    snap = Snapshot({
        SourcePath("src/app/__init__.py"): "",
        SourcePath("src/app/core/deep/x.py"): "",
        SourcePath("src/other.py"): "",
        SourcePath("tests/test_x.py"): "",
    }, ROOTS)
    m = map_units(G, realize.extract(snap))
    assert m.component_of == {"app": "app", "app.core.deep.x": "app.core"}
    assert [u.name for u in m.unmapped] == ["other"]
    assert m.resolve("app.core.deep.x.func") == "app.core.deep.x"
    assert m.resolve("os.path") is None

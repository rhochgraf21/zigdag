from __future__ import annotations

from arch import realize, realizes
from arch.realize.facts import Reach, Roots, Snapshot, SourcePath
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


def test_names_reexported_by_a_package_resolve_to_the_package():
    snap = Snapshot({
        SourcePath("src/app/__init__.py"): "",
        SourcePath("src/app/core/__init__.py"): "from app.core.impl import run\n",
        SourcePath("src/app/core/impl.py"): "import os\n\ndef run():\n    return os.environ\n",
        SourcePath("src/app/core/run.py"): "",
        SourcePath("src/app/shell.py"): "from app.core import run\n\ndef main():\n    return run()\n",
    }, ROOTS)
    facts = realize.extract(snap)
    m = map_units(G, facts)
    imp = next(i for i in facts.imports if i.unit == "app.shell")
    assert m.target_of(imp) == "app.core"  # the function the package binds, not the submodule app.core.run
    assert any(e.unit == "app.shell" and e.symbol == "main" and e.reach is Reach.TRANSITIVE for e in facts.effects)  # followed the alias

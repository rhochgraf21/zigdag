from __future__ import annotations

from arch import realizes
from tests.conftest import NEED, component, graph

CONSTRAINT = "---\nkind: constraint\napplies_to: [sys.core]\n---\nNo effects.\n"

G = graph({
    "needs/n.md": NEED,
    "constraints/pure.md": CONSTRAINT,
    "components/sys.md": component(serves="n"),
    "components/sys/core.md": component(exports="api", serves="n"),
    "components/sys/core/api.md": component(),
    "components/sys/core/internal.md": component(),
    "components/sys/shell.md": component(uses="core.api, core.internal", serves="n"),
    "components/sys/shell/cli.md": component(uses="core.api"),
})


@realizes("arch.model.graph#AC1")
def test_hierarchy_from_ids():
    assert G.parent("sys.core.api") == "sys.core"
    assert G.children("sys.core") == ("sys.core.api", "sys.core.internal")
    assert G.roots == ("sys",)


@realizes("arch.model.graph#AC2")
def test_lexical_resolution():
    assert G.resolve("sys.shell.cli", "core.api") == "sys.core.api"
    assert G.resolve("sys.shell", "core") == "sys.core"
    assert G.resolve("sys.shell", "nowhere") is None


@realizes("arch.model.graph#AC4")
def test_visibility_requires_exports():
    assert G.may_use("sys.shell", "sys.core.api")
    assert not G.visible("sys.shell", "sys.core.internal")
    assert not G.may_use("sys.shell", "sys.core.internal")
    assert not G.may_use("sys.core", "sys.shell")  # not declared


@realizes("arch.model.graph#AC3")
def test_constraints_are_inherited():
    assert G.effective_constraints("sys.core.internal") == ("pure",)
    assert G.effective_constraints("sys.shell") == ()


@realizes("arch.model.graph#AC5")
def test_needs_are_inherited():
    assert G.needs_of("sys.core.api") == ("n",)

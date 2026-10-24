from __future__ import annotations

import anyio
import pytest

from arch import realizes
from arch.integrate import catalog
from tests.test_agent import project

mcp = pytest.importorskip("arch.integrate.mcp")


@realizes("arch.integrate.mcp#AC1", "arch.integrate#AC1")
def test_every_catalog_operation_is_one_tool(tmp_path):
    srv = mcp.server(project(tmp_path).root)
    tools = anyio.run(srv.list_tools)
    offered = sorted(op.command.value for op in catalog.OPERATIONS if op.audience is catalog.Audience.ANYONE)
    assert sorted(t.name for t in tools) == offered
    assert "review_decide" not in offered  # agents never record verdicts


def test_tools_run_the_same_operations_as_the_cli(tmp_path):
    root = project(tmp_path).root
    srv = mcp.server(root)

    async def call(name, args):
        result = await srv.call_tool(name, args)
        return result.content[0].text, result.is_error

    outline, err = anyio.run(call, "outline", {"depth": 1})
    assert not err and "core" in outline
    dry, err = anyio.run(call, "edit", {"operations": [{"op": "add_criterion", "component": "app.core",
                                                         "text": "It shall work."}], "dry_run": True})
    assert not err and "would apply 1 operation" in dry
    assert "AC2" not in (root / "design/components/app/core.md").read_text()

"""The adapters zigdag has, set up for one project. Supporting another language or tool is writing its adapter and
naming it here: nothing else in zigdag knows which adapters there are."""

from __future__ import annotations

import deal

from zigdag.adapters.adapter import Adapter, Presence
from zigdag.adapters.python.adapter import PythonAdapter
from zigdag.adapters.terraform.adapter import TerraformAdapter
from zigdag.adapters.typescript.adapter import TypeScriptAdapter
from zigdag.core.settings import Settings


@deal.ensure(lambda settings, conventional_source, result: len({a.name for a in result}) == len(result))
def adapters(settings: Settings, conventional_source: Presence) -> tuple[Adapter, ...]:
    """Each adapter that may find something to read in a project with these settings. Python reads a project that
    configures nothing; an adapter that must be told where to read is there only when its section is."""
    told = (TerraformAdapter.of(settings), TypeScriptAdapter.of(settings))
    return (PythonAdapter.of(settings, conventional_source), *(adapter for adapter in told if adapter is not None))

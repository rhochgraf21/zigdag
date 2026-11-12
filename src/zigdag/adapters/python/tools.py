"""The Python linter, type checker and security checker: ruff, ty and bandit, and how each one's report is read."""

from __future__ import annotations

from collections.abc import Mapping

import deal

from zigdag.adapters import tools
from zigdag.adapters.code_quality import read_report
from zigdag.adapters.python.bandit import read_bandit
from zigdag.adapters.tools import ReportReader, Tool, ToolOutput
from zigdag.core.code import Diagnosis, Diagnostic, ToolName
from zigdag.core.findings import Finding
from zigdag.core.names import PYTHON, Argument

_CODE_QUALITY = tuple(Argument(a) for a in ("check", "--output-format=gitlab", "--exit-zero"))  # ruff and ty alike
_BANDIT = tuple(Argument(a) for a in ("--format=json", "--exit-zero", "--quiet", "--recursive"))  # its own form only

# Each is run with --exit-zero: finding something is no failure to run.
RUFF = Tool(PYTHON, ToolName("ruff"), Diagnosis.LINT, _CODE_QUALITY)
TY = Tool(PYTHON, ToolName("ty"), Diagnosis.TYPES, _CODE_QUALITY)
BANDIT = Tool(PYTHON, ToolName("bandit"), Diagnosis.SECURITY, _BANDIT)
TOOLS = (RUFF, TY, BANDIT)

_READERS: Mapping[Tool, ReportReader] = {RUFF: read_report, TY: read_report,
                                         BANDIT: read_bandit}  # bandit writes no GitLab report


@deal.ensure(lambda output, result: (result[1] is None) or result[0] == ())
def diagnostics(output: ToolOutput) -> tuple[tuple[Diagnostic, ...], Finding | None]:
    """What one of Python's tools reported, or why it reported nothing that can be used."""
    return tools.diagnostics(output, _READERS[output.tool])

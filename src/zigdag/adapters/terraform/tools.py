"""Terraform's linter and security checker: tflint and trivy, and how each one's report is read.

Both write SARIF. tflint names a file from the project's root. trivy names it from the folder it was given, the
root module's, so a path is matched to the source file it means. trivy also writes each message as a small form
(Artifact, Type, Severity, Message, Link), of which only the message says what is wrong.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import replace

import deal

from zigdag.adapters import tools
from zigdag.adapters.sarif import read_sarif
from zigdag.adapters.tools import Tool, ToolOutput, ToolRun
from zigdag.core.code import Diagnosis, Diagnostic, ToolName
from zigdag.core.findings import Finding, RecordPath
from zigdag.core.names import TERRAFORM, Argument, Key
from zigdag.core.settings import CURRENT_FOLDER, PROJECT_ROOT, Settings
from zigdag.core.texts import Say

# --force: finding something is no failure to run. tflint reads the folder it is told to change into.
TFLINT = Tool(TERRAFORM, ToolName("tflint"), Diagnosis.LINT, (Argument("--format=sarif"), Argument("--force")))
# trivy exits zero whatever it finds unless told otherwise, and reads the folder it is given.
TRIVY = Tool(TERRAFORM, ToolName("trivy"), Diagnosis.SECURITY,
             (Argument("config"), Argument("--format=sarif"), Argument("--quiet")))
TOOLS = (TFLINT, TRIVY)
_CHANGE_INTO = "--chdir="  # how tflint is given its folder


@deal.ensure(lambda settings, root, wanted, result: {r.tool.diagnosis for r in result} == (
    set(wanted) & {t.diagnosis for t in TOOLS}))
def runs(settings: Settings, root: RecordPath, wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
    """Those of Terraform's tools that report what the rules want, each started as [adapters.terraform] says, or by
    its own name, on the root module's folder."""
    folder = Argument(CURRENT_FOLDER if root == PROJECT_ROOT else root)
    chosen = set(wanted)
    out = []
    for tool in TOOLS:
        if tool.diagnosis not in chosen:
            continue
        start = tuple(Argument(a) for a in shlex.split(settings.command(TERRAFORM, Key(tool.name)) or tool.name))
        given = (Argument(f"{_CHANGE_INTO}{folder}"),) if tool == TFLINT else (folder,)
        out.append(ToolRun(tool, (*start, *tool.arguments, *given)))
    return tuple(out)


def _meant(path: RecordPath, sources: Iterable[RecordPath], root: RecordPath) -> RecordPath:
    """The source file a reported path means: the path itself when it is one, then the path read from the root
    module's folder, where a tool given that folder names its files from. Failing both, the one source file whose
    path ends as the reported one does, or that the reported one ends with, as a full path on disk does."""
    known = sorted(sources)
    if path in known:
        return path
    inside = RecordPath(f"{root}/{path}" if root else path)
    if inside in known:
        return inside
    alike = [s for s in known if s.endswith(f"/{path}") or path.endswith(f"/{s}")]
    return alike[0] if len(alike) == 1 else path


_MESSAGE = re.compile(r"\bMessage: (.+?)(?: Link: |$)")  # the part of trivy's form that says what is wrong


def _said(say: Say) -> Say:
    """What a diagnostic says, without the form trivy writes around it."""
    found = _MESSAGE.search(say)
    return Say(found.group(1)) if found is not None else say


@deal.ensure(lambda output, sources, root, result: (result[1] is None) or result[0] == ())
def diagnostics(output: ToolOutput, sources: Mapping[RecordPath, object],
                root: RecordPath) -> tuple[tuple[Diagnostic, ...], Finding | None]:
    """What one of Terraform's tools reported, each diagnostic at the source file it is about, or why the tool
    reported nothing that can be used."""
    reported, failure = tools.diagnostics(output, read_sarif)
    return tuple(replace(d, say=_said(d.say), span=replace(d.span, path=_meant(d.span.path, sources, root)))
                 for d in reported), failure

from __future__ import annotations

from pathlib import Path

from zigdag.core.checks.run import ProjectFiles, check
from zigdag.core.findings import RecordPath, Report, Result

EXAMPLES = Path(__file__).parent / "examples"

SETTINGS = """
[settings]
ruleset = 1

[adapters]
default = "python"
"""

CUSTOMER = """
verify-programs:
  job: Verify that a Mojo program meets its spec
  performer: Mojo developer
  outcomes:
    wrong-proof-passes: Minimize the likelihood that a proof passes for a program that breaks its spec
"""

FUNCTIONAL = """
frs:
  app:
    statements:
      run: The app shall translate a program.
  app.core:
    serves: [verify-programs.wrong-proof-passes]
    statements:
      translate: The core shall translate Mojo source text into Verus source text.
"""


def project(settings: str | None = SETTINGS, **domains: str) -> Report:
    """Check a project made of the given domain files; defaults give a minimal valid record."""
    files = {"customer": CUSTOMER, "functional": FUNCTIONAL, **domains}
    design = {RecordPath(f"design/{name}.yaml"): text for name, text in files.items() if text is not None}
    return check(ProjectFiles(settings, design))


def rules(report: Report, result: Result) -> set[str]:
    return {f.rule for f in report.of_result(result)}


def says(report: Report, result: Result) -> list[str]:
    return [f.say for f in report.of_result(result)]

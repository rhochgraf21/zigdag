"""lint and types (DESIGN2 §4.1): the project's own linter and type checker, run by zigdag and held to the record's
scopes. The end-to-end tests run the real ruff and ty, which are dev dependencies, so the tools' report form is
checked as the tools write it, not as a fixture remembers it."""

import json
from pathlib import Path

import subprocess

from zigdag import verifies
from zigdag.adapters.code_quality import read_report
from zigdag.adapters.python.adapter import PythonAdapter
from zigdag.adapters.adapter import Presence
from zigdag.adapters.python.tools import RUFF, TY, diagnostics
from zigdag.adapters.tools import ExitStatus, Started, ToolOutput, finished, not_started
from zigdag.cli import main
from zigdag.core.code import Diagnosis, Severity, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.settings import read_settings
from zigdag.core.texts import ToolText

SETTINGS = '[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
PYPROJECT = '[project]\nname = "shop"\nrequires-python = ">=3.11"\n'
CUSTOMER = """
pay:
  job: Pay for an order
  performer: Shopper
  outcomes:
    wrong-charge: Minimize the likelihood that an order is charged the wrong amount
"""
FUNCTIONAL = """
frs:
  shop:
    statements:
      sell: The shop shall take payment for orders.
  shop.core:
    serves: [pay.wrong-charge]
    statements:
      plan: The core shall decide what each order is charged.
  shop.legacy:
    serves: [pay.wrong-charge]
    statements:
      keep: The legacy shall charge orders the old way.
"""
PROCESS = """
lint:
  kind: code-rule
  on: shop
  serves: [pay.wrong-charge]
  check: lint
types:
  kind: code-rule
  on: shop.core
  serves: [pay.wrong-charge]
  check: types
  except:
    - tolerated
"""
CORE = '''"""What each order is charged."""
import os


def charge(cents: int) -> int:
    """The amount to charge."""
    return str(cents)


def tolerated(cents: int) -> int:
    """Known debt."""
    return str(cents)
'''
LEGACY = '''"""The old way: outside the types rule, so its type error is not reported."""


def charge(cents: int) -> int:
    """The amount to charge."""
    return str(cents)
'''


def build(tmp_path: Path, process: str = PROCESS) -> Path:
    files = {"zigdag.toml": SETTINGS, "pyproject.toml": PYPROJECT, "src/shop/__init__.py": '"""Shop."""\n',
             "src/shop/core.py": CORE, "src/shop/legacy.py": LEGACY, "design/customer.yaml": CUSTOMER,
             "design/functional.yaml": FUNCTIONAL, "design/process.yaml": process}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def checked(root: Path, capsys) -> list[dict]:
    main(["--project", str(root), "check", "--json"])
    return json.loads(capsys.readouterr().out)


RUFF_REPORT = """[{"check_name": "F401", "description": "F401: `os` imported but unused", "severity": "major",
  "fingerprint": "1", "location": {"path": "src/shop/core.py", "positions": {"begin": {"line": 2, "column": 8},
  "end": {"line": 2, "column": 10}}}},
 {"check_name": "deprecated", "description": "deprecated: old", "severity": "minor",
  "location": {"path": "./src/shop/core.py", "lines": {"begin": 5}}}]"""


@verifies("zigdag.adapters#reports")
def test_a_code_quality_report_is_read_whole_or_refused_whole():
    first, second = read_report(ToolText(RUFF_REPORT), Diagnosis.LINT, ToolName("ruff"))
    assert (first.code, first.say, str(first.span), first.severity) == (
        "F401", "`os` imported but unused", "src/shop/core.py:2:8", Severity.ERROR)
    assert (str(second.span), second.severity) == ("src/shop/core.py:5:1", Severity.WARNING)
    assert read_report(ToolText("[]"), Diagnosis.TYPES, ToolName("ty")) == ()
    assert isinstance(read_report(ToolText("not json"), Diagnosis.LINT, ToolName("ruff")), Unreadable)
    missing_line = '[{"check_name": "F401", "description": "x", "location": {"path": "a.py"}}]'
    assert isinstance(read_report(ToolText(missing_line), Diagnosis.LINT, ToolName("ruff")), Unreadable)


@verifies("zigdag.adapters.python#tools")
def test_only_the_tools_a_rule_needs_run_and_each_starts_as_the_settings_say():
    settings, _ = read_settings('[adapters.python]\nsource = ["src"]\nty = "uv run ty"\n')
    python = PythonAdapter.of(settings, Presence.ABSENT)
    source = {"src/shop/core.py": ""}
    assert python.tool_runs(source, ()) == () and python.tool_runs({}, (Diagnosis.LINT,)) == ()  # no source, no run
    (lint,) = python.tool_runs(source, (Diagnosis.LINT,))
    assert lint.tool is RUFF and lint.command[0] == "ruff" and lint.command[-1] == "src"
    (types,) = PythonAdapter(settings, ("",)).tool_runs(source, (Diagnosis.TYPES,))
    assert types.command[:3] == ("uv", "run", "ty") and types.command[-1] == "."  # the project itself as a folder


@verifies("zigdag.adapters.python#tool-failed")
def test_a_tool_that_cannot_report_breaks_instead_of_passing():
    reported, failure = diagnostics(not_started(TY))
    assert not reported and "ty could not be started" in failure.say
    crashed = finished(RUFF, ExitStatus(2), ToolText(""), ToolText("error: bad config\nmore"))
    assert "ruff failed (exit 2): error: bad config" in diagnostics(crashed)[1].say
    garbled = ToolOutput(RUFF, Started.STARTED, out=ToolText("{"))
    assert "cannot read" in diagnostics(garbled)[1].say
    for output in (not_started(TY), crashed, garbled):
        assert diagnostics(output)[1].result.value == "breaks"


@verifies("zigdag.core.analysis.checks#diagnosed", "zigdag.adapters.python#tools")
def test_the_real_tools_report_inside_the_scope_of_each_rule_and_outside_its_except(tmp_path, capsys):
    findings = checked(build(tmp_path), capsys)
    lint = [(f["about"], f["say"]) for f in findings if f["rule"] == "lint"]
    assert lint == [("shop.core", "ruff F401: `os` imported but unused")]  # module-level code is the unit's own
    types = [f for f in findings if f["rule"] == "types"]
    assert [f["about"] for f in types] == ["shop.core.charge"]  # not tolerated (excepted), not legacy (out of scope)
    assert types[0]["say"].startswith("ty invalid-return-type") and types[0]["result"] == "breaks"
    assert not [f for f in findings if f["rule"] == "tools"]


@verifies("zigdag.adapters.python#tool-failed")
def test_a_rule_whose_tool_is_missing_breaks(tmp_path, capsys):
    root = build(tmp_path)
    (root / "zigdag.toml").write_text(SETTINGS + 'ruff = "no-such-linter"\n')
    findings = checked(root, capsys)
    assert any(f["rule"] == "tools" and f["result"] == "breaks" and "ruff could not be started" in f["say"]
               for f in findings)
    assert not [f for f in findings if f["rule"] == "lint"]


@verifies("zigdag.adapters.python#tools")
def test_no_tool_runs_without_a_rule_that_needs_it(tmp_path, capsys):
    root = build(tmp_path, process="")
    (root / "zigdag.toml").write_text(SETTINGS + 'ruff = "no-such-linter"\nty = "no-such-checker"\n')
    assert not [f for f in checked(root, capsys) if f["rule"] in ("tools", "lint", "types")]


@verifies("zigdag.cli.plans#unchecked")
def test_a_review_does_not_count_diagnostics_that_the_base_could_not_see_as_brought(tmp_path, capsys):
    root = build(tmp_path)
    for args in (("init", "-q"), ("add", "-A"), ("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    core = root / "src/shop/core.py"
    core.write_text(core.read_text() + "\n\ndef added(cents: int) -> int:\n    \"\"\"New.\"\"\"\n    return cents\n")
    main(["--project", str(root), "review", "HEAD"])
    shown = capsys.readouterr().out
    assert "ty invalid-return-type" not in shown and "ruff F401" not in shown  # there before the change, unseen there

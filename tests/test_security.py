"""Security (DESIGN2 §4.1, §4.6): what the project's security checker reports, bandit for Python, held to the record's
scopes like lint and types. bandit's own severity decides: a low one is a thing to do, the rest break."""

import json

from test_tools import PROCESS, build

from zigdag import verifies
from zigdag.adapters.python.bandit import read_bandit
from zigdag.cli import main
from zigdag.core.code import Diagnosis, Severity, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.texts import ToolText

SECURITY = PROCESS + """security:
  kind: code-rule
  on: shop
  serves: [pay.wrong-charge]
  check: security
"""
RISKY = '''"""The old way, with what a security checker looks for."""
import subprocess


def charge(cents: int) -> int:
    """The amount to charge."""
    return str(cents)


def total(expression: str) -> int:
    """Adds up what it is given."""
    return eval(expression)


def listing() -> str:
    """What is here."""
    return subprocess.run(["ls"], capture_output=True, text=True).stdout
'''
BANDIT = ToolText(json.dumps({"errors": [], "results": [
    {"test_id": "B307", "issue_text": "Use of possibly insecure function.", "filename": "./src/shop/legacy.py",
     "line_number": 12, "col_offset": 11, "issue_severity": "MEDIUM", "issue_confidence": "HIGH"},
    {"test_id": "B404", "issue_text": "Consider the security implications of subprocess.", "filename": "src/shop/legacy.py",
     "line_number": 2, "col_offset": 0, "issue_severity": "LOW", "issue_confidence": "HIGH"}]}))


def checked(root, capsys) -> list[dict]:
    main(["--project", str(root), "check", "--json"])
    return json.loads(capsys.readouterr().out)


@verifies("zigdag.adapters.python#security", "zigdag.core.analysis.checks#diagnosed")
def test_what_bandit_finds_is_reported_in_the_security_direction(tmp_path, capsys):
    root = build(tmp_path, process=SECURITY)
    (root / "src/shop/legacy.py").write_text(RISKY)
    found = [f for f in checked(root, capsys) if f["rule"] == "security"]
    assert {f["direction"] for f in found} == {"security"}
    breaks = [f for f in found if f["result"] == "breaks"]
    assert [(f["about"], f["say"].split(":")[0]) for f in breaks] == [("shop.legacy.total", "bandit B307")]
    assert {f["result"] for f in found if f["say"].startswith(("bandit B404", "bandit B603"))} == {"to do"}


@verifies("zigdag.adapters.python#security")
def test_bandit_is_run_only_for_a_security_rule(tmp_path, capsys):
    root = build(tmp_path)  # lint and types, but no security rule
    (root / "src/shop/legacy.py").write_text(RISKY)
    assert not [f for f in checked(root, capsys) if f["rule"] == "security"]


@verifies("zigdag.adapters.python#tool-failed")
def test_a_missing_bandit_breaks_the_security_direction(tmp_path, capsys):
    root = build(tmp_path, process=SECURITY)
    (root / "zigdag.toml").write_text((root / "zigdag.toml").read_text() + 'bandit = "no-such-checker"\n')
    failed = [f for f in checked(root, capsys) if f["rule"] == "tools"]
    assert [(f["direction"], f["result"]) for f in failed] == [("security", "breaks")]
    assert failed[0]["say"].startswith("bandit could not be started")


@verifies("zigdag.adapters#reports")
def test_a_bandit_report_is_read_whole_or_refused_whole():
    risky, imported = read_bandit(BANDIT, Diagnosis.SECURITY, ToolName("bandit"))
    assert (risky.code, risky.severity, risky.span.path, risky.span.line, risky.span.column) == (
        "B307", Severity.ERROR, "src/shop/legacy.py", 12, 12)  # bandit counts columns from 0
    assert imported.severity is Severity.WARNING  # a low one is a thing to do
    unscanned = json.dumps({"errors": [{"filename": "src/shop/broken.py", "reason": "syntax error"}], "results": []})
    assert isinstance(read_bandit(ToolText(unscanned), Diagnosis.SECURITY, ToolName("bandit")), Unreadable)
    assert isinstance(read_bandit(ToolText("[]"), Diagnosis.SECURITY, ToolName("bandit")), Unreadable)

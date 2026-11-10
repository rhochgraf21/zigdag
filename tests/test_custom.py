"""Custom checks (DESIGN2 §4.2): a project's own rules are plain functions in design/checks/, and zigdag runs them."""

import json

from test_code import build

from zigdag import verifies
from zigdag.cli import main

CHECKS = '''"""This project's own rules."""

from zigdag.checks import asked, broken


def short_module_names(context, rule, *, longest: int = 20):
    """Each module has a name short enough to say."""
    for path, unit in sorted(context.model.units.items()):
        name = path.rpartition(".")[2]
        if len(name) > longest and context.in_scope(rule, context.tree.unit_owner.get(path)):
            yield broken(rule, path, unit.span, f"{name} is {len(name)} letters; at most {longest}")


def brief_statements(context, rule, *, words: int = 30):
    """Each statement of the design is brief: a rule about the design itself, not the code."""
    for fr in context.record.frs.values():
        for statement in fr.statements:
            said = len(statement.sentence.text.split())
            if said > words and context.in_scope(rule, fr.name):
                yield asked(rule, statement.ref, statement.sentence.span, f"{said} words; at most {words}")


def _helper():
    """Private, so it is no check."""
'''
RULES = """
names-can-be-said:
  kind: code-rule
  on: tiny
  serves: [maintain.find-code]
  check: short-module-names
  with:
    longest: 4

brief:
  kind: code-rule
  on: tiny.core
  serves: [maintain.review-time]
  check: brief-statements
  with:
    words: 4
"""
READS_A_FILE = '''def nosy(context, rule):
    """Reads a file, so two runs could differ."""
    open("notes.txt").read()
    return []
'''


def found(root, capsys, rule: str) -> dict[str, str]:
    main(["--project", str(root), "check", "--json"])
    return {f["about"]: f"{f['result']}: {f['say']}" for f in json.loads(capsys.readouterr().out) if f["rule"] == rule}


@verifies("zigdag.core.analysis.checks#custom")
def test_a_function_in_design_checks_is_a_rule_of_the_code_or_of_the_design(tmp_path, capsys):
    root = build(tmp_path, extra={"design/checks/ours.py": CHECKS, "design/process.yaml": RULES})
    assert found(root, capsys, "names-can-be-said") == {
        "tiny.core.model": "breaks: model is 5 letters; at most 4", "tiny.core.rules": "breaks: rules is 5 letters; at most 4"}
    assert found(root, capsys, "brief") == {  # a guess about the design, inside tiny.core only
        "tiny.core#price": "question: 6 words; at most 4", "tiny.core.model#hold": "question: 9 words; at most 4",
        "tiny.core.model.order#lines": "question: 8 words; at most 4",
        "tiny.core.rules#price": "question: 8 words; at most 4"}
    assert found(root, capsys, "custom-checks") == {}  # the private helper is no check, and nothing is wrong

    (root / "design/process.yaml").write_text(RULES.replace("longest: 4", "longest: four"))
    assert "is not a whole number" in str(found(root, capsys, "params"))  # its settings are checked as a built-in's are


@verifies("zigdag.core.analysis.checks#custom-refused")
def test_a_custom_check_with_an_effect_or_that_fails_breaks_and_never_passes(tmp_path, capsys):
    rule = "nosy:\n  kind: code-rule\n  on: tiny\n  serves: [maintain.find-code]\n  check: nosy\n"
    root = build(tmp_path, extra={"design/checks/ours.py": READS_A_FILE, "design/process.yaml": rule})
    refused = found(root, capsys, "custom-checks")
    assert list(refused) == ["design/checks/ours.py"] and "may not have effects" in refused["design/checks/ours.py"]

    fails = 'def nosy(context, rule):\n    """Fails."""\n    return [1 // 0]\n'
    (root / "design/checks/ours.py").write_text(fails)
    assert "failed to run (ZeroDivisionError" in found(root, capsys, "nosy")["tiny"]
    (root / "design/checks/ours.py").write_text(fails.replace("1 // 0", '"not a finding"'))
    assert "something that is not a finding" in found(root, capsys, "nosy")["tiny"]
    (root / "design/checks/ours.py").write_text("def nosy(context):\n    return []\n")
    assert "must take what it reads and the rule" in found(root, capsys, "custom-checks")["design/checks/ours.py"]

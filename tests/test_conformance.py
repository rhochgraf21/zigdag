from __future__ import annotations

from arch import realize, realizes
from arch.check import check
from arch.check.engine import Severity
from arch.realize.facts import Roots, Snapshot, SourcePath
from tests.conftest import NEED, component, graph

ROOTS = Roots((SourcePath("src"),), (SourcePath("tests"),))
ALLOW = "---\nkind: constraint\napplies_to: [s]\nrule:\n  imports:\n    allow_third_party: [requests]\n---\nDeps.\n"
PURE = "---\nkind: constraint\napplies_to: [s.core]\nrule:\n  effects:\n    allow: []\n---\nPure.\n"

DESIGN = {
    "needs/n.md": NEED,
    "constraints/allow.md": ALLOW,
    "constraints/pure.md": PURE,
    "components/s.md": component(serves="n"),
    "components/s/core.md": component(serves="n", exports="api"),
    "components/s/core/api.md": component(),
    "components/s/core/inner.md": component(),
    "components/s/shell.md": component(serves="n", uses="core"),
    "components/s/idle.md": component(serves="n", status="contracted"),
}


def run(code: dict[str, str], design=DESIGN):
    snap = Snapshot({SourcePath(k): v for k, v in code.items()}, ROOTS)
    return check(graph(design), realize.extract(snap)).findings


def rules(findings, severity=None):
    return {(f.rule, f.subject) for f in findings if severity is None or f.severity is severity}


BASE = {"src/s/__init__.py": "", "src/s/core/api.py": "", "src/s/core/inner.py": "", "src/s/idle.py": ""}


@realizes("arch.check.conformance#AC1")
def test_imports_need_declared_visible_uses():
    ok = run({**BASE, "src/s/shell.py": "from s.core.api import x\n"})
    assert not any(r == "C001" for r, _ in rules(ok))
    hidden = run({**BASE, "src/s/shell.py": "import s.core.inner\n"})
    assert ("C001", "s.shell") in rules(hidden, Severity.ERROR)  # declared, but not exported
    backwards = run({**BASE, "src/s/core/api.py": "from s import shell\n", "src/s/shell.py": ""})
    assert ("C001", "s.core.api") in rules(backwards, Severity.ERROR)  # not declared at all


@realizes("arch.check.conformance#AC4", "arch.check.conformance#AC6")
def test_dangling_links_are_errors_with_locations():
    f = run({**BASE, "tests/test_s.py": "@realizes('s.core#AC1', 's.core#AC9', 'nope')\ndef test(): ...\n"})
    bad = [x for x in f if x.rule == "C004"]
    assert sorted(x.key for x in bad) == ["link:nope", "link:s.core#AC9"]
    assert all(str(x.location).startswith("tests/test_s.py:") for x in bad)


@realizes("arch.check.conformance#AC3")
def test_evidence_strictness_scales_with_maturity():
    f = run(BASE)
    assert ("C005", "s.core") in rules(f, Severity.INFO)
    assert ("C005", "s.idle") in rules(f, Severity.ERROR)  # contracted


@realizes("arch.check.conformance#AC5")
def test_unanalyzed_effects_are_reported_not_passed():
    assert ("C007", "s.core.api") in rules(run(BASE), Severity.INFO)


def test_third_party_allowlist_and_stdlib():
    f = run({**BASE, "src/s/shell.py": "import json\nimport requests.adapters\nimport numpy\n"})
    third = [x for x in f if x.rule == "C006"]
    assert [x.key for x in third] == ["third-party:numpy"]


@realizes("arch.check.conformance#AC7")
def test_unbuilt_subtrees_reported_once():
    f = run({"src/s/__init__.py": ""})
    assert {s for r, s in rules(f) if r == "C003"} == {"s.core", "s.shell", "s.idle"}


def test_unmapped_and_unparseable():
    f = run({**BASE, "src/stray.py": "", "src/s/shell.py": "def (:\n"})
    assert ("C002", "stray") in rules(f, Severity.WARNING)
    assert ("C000", "src/s/shell.py") in rules(f, Severity.ERROR)

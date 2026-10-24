from __future__ import annotations

import re
from dataclasses import replace

from arch import realize, realizes
from arch.change.diff import diff as design_diff
from arch.check import check
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import DesignPath, Text
from arch.realize.facts import FileChange, LineNo, NameKind, Role, Roots, Snapshot, SourcePath, UnitName, port_changes
from arch.realize.history import UnifiedDiff, added_file, parse_diff
from arch.realize.python.extract import extract, names
from arch.review import items as review_items
from arch.review.assess import ReviewInput, criteria_evidence, file_risks
from arch.review.explain import Why
from arch.review.items import CodeBody, Glossary
from arch.review.page import render
from arch.review.session import Session
from tests.conftest import NEED, component

SAMPLE = '''from dataclasses import dataclass


@dataclass
class Input:
    """What a review compares."""

    after: int  # the design after the change


class _Hidden:
    value: int


def use(inp: Input) -> int:
    first = helper(inp.after)
    return helper(
        inp.after,
    )


def helper(x):
    return x
'''


@realizes("arch.realize.facts#AC8", "arch.realize.facts#AC9", "arch.realize.python.extract#AC9")
def test_every_definition_and_call_site_is_recorded():
    facts = extract(SourcePath("src/m.py"), SAMPLE, UnitName("m"), Role.SOURCE)
    defs = {d.name: d for d in facts.definitions}
    assert {"Input", "Input.after", "_Hidden", "_Hidden.value", "use", "helper"} <= set(defs)
    assert defs["Input"].location.line == 4 and defs["Input"].summary == "What a review compares."  # starts at its decorator
    assert defs["Input.after"].summary == "the design after the change"
    assert defs["use"].end_line == 19
    assert "_Hidden.value" not in {s.name for s in facts.symbols}  # a private class's member is not interface
    sites = [(c.location.line, c.end_line) for c in facts.calls if c.symbol == "use" and c.callee == "m.helper"]
    assert sites == [(16, 16), (17, 19)]


@realizes("arch.realize.python.extract#AC8", "arch.realize#AC7")
def test_names_resolve_through_typed_parameters_only_when_asked():
    refs = {(r.text, r.kind): r.target for r in names(SourcePath("src/m.py"), SAMPLE, UnitName("m")) if r.location.line == 16}
    assert refs[("inp.after", NameKind.DEFINITION)] == "m.Input.after"
    assert refs[("inp", NameKind.VALUE)] == "m.Input" and refs[("helper", NameKind.DEFINITION)] == "m.helper"
    snap = Snapshot({SourcePath("src/m.py"): SAMPLE, SourcePath("src/n.py"): SAMPLE}, Roots(("src",), ("tests",)))
    assert realize.extract(snap).references == ()
    assert {r.location.path for r in realize.names(snap, [SourcePath("src/m.py")])} == {"src/m.py"}


# a change to an interface, and a caller that only follows it

DESIGN = {"needs/n.md": NEED, "components/s.md": component(serves="n"),
          "components/s/core.md": component(serves="n"), "components/s/shell.md": component(serves="n", uses="core")}
BEFORE = {"src/s/__init__.py": "", "src/s/core.py": "def f(x: X) -> Y:\n    return x\n",
          "src/s/shell.py": "from s.core import f\n\n\ndef main() -> Y:\n    return f(1)\n"}
AFTER = {**BEFORE, "src/s/core.py": 'def f(x: X, y: X) -> Y:\n    """Combine two things."""\n    return x\n',
         "src/s/shell.py": "from s.core import f\n\n\ndef main() -> Y:\n    return f(1, 2)\n"}
FOLLOW = UnifiedDiff("""diff --git a/src/s/core.py b/src/s/core.py
--- a/src/s/core.py
+++ b/src/s/core.py
@@ -1,2 +1,3 @@
-def f(x: X) -> Y:
+def f(x: X, y: X) -> Y:
+    \"\"\"Combine two things.\"\"\"
     return x
diff --git a/src/s/shell.py b/src/s/shell.py
--- a/src/s/shell.py
+++ b/src/s/shell.py
@@ -4,2 +4,2 @@ def main
 def main() -> Y:
-    return f(1)
+    return f(1, 2)
""")


def change(before_code, after_code, diffs, design_after=None, design_before=None):
    roots = Roots(("src",), ("tests",))
    snap_before = Snapshot({SourcePath(k): v for k, v in before_code.items()}, roots)
    snap_after = Snapshot({SourcePath(k): v for k, v in after_code.items()}, roots)
    paths = [d.path for d in diffs]
    facts_before = replace(realize.extract(snap_before), references=realize.names(snap_before, paths))
    facts_after = replace(realize.extract(snap_after), references=realize.names(snap_after, paths))
    before = codec.load({DesignPath(k): v for k, v in (design_before or DESIGN).items()})
    after = codec.load({DesignPath(k): v for k, v in (design_after or DESIGN).items()})
    return ReviewInput(Text("main"), before, after, facts_before, facts_after, check(Graph(before), facts_before),
                       check(Graph(after), facts_after), tuple(), tuple(diffs))


def page(items, page_id):
    return next(i for i in items if i.id == page_id)


def html_of(inp):
    items = review_items.build(inp)
    return items, render(items, Session(Text("b")), Text("Review"), Glossary.of(inp.after, items, Text("design")))


@realizes("arch.review.explain#AC4", "arch.review.explain#AC5", "arch.review.items#AC9", "arch.review.explain#AC1",
          "arch.review.items#AC10")
def test_a_caller_that_only_follows_an_interface_change_is_shown_with_it():
    items, html = html_of(change(BEFORE, AFTER, parse_diff(FOLLOW)))
    assert not any(i.id == "code:s.shell" for i in items)  # nothing else changed there
    core = page(items, "code:s.core").body
    (note,) = core.interfaces
    assert note.change.symbol == "f" and note.change.compatibility.value == "breaking"
    (caller,) = note.callers
    assert caller.path == "src/s/shell.py" and caller.component == "s.shell" and caller.hunk.enclosing.name == "main"
    (reason,) = caller.hunk.reasons
    assert reason.why is Why.FOLLOWS and reason.refs == ("s.core.f",)
    assert "1 caller updated to match" in html and "It updates calls to" in html
    (own,) = core.sources[0].hunks
    assert own.unexplained and "No reason given." in html  # the signature change itself: nothing traced
    tallies = {t.label: t.count for t in page(items, "overview").body.tallies}
    assert tallies["change with no reason given"] == 1


@realizes("arch.review.explain#AC7", "arch.review.page#AC7", "arch.review.page#AC8")
def test_changes_show_their_definition_and_explain_their_names():
    _, html = html_of(change(BEFORE, AFTER, parse_diff(FOLLOW)))
    assert 'In <code class="sig">f(x: X, y: X) -&gt; Y</code><div class="muted">Combine two things.</div>' in html
    tip = r'<span class="name" data-tip="([^"]*)">f</span>\(<span class="t-number">1</span>'
    new = re.search(tip + r', <span class="t-number">2</span>\)', html)
    old = re.search(tip + r'\)', html)
    assert new and new.group(1) == "f(x: X, y: X) -&gt; Y\nCombine two things."  # the added line: f as it is now
    assert old and old.group(1) == "f(x: X) -&gt; Y"  # the removed line: f as it was


# a new component, with a test of its criterion

GROWN = {**DESIGN, "components/s/cache.md": component(serves="n")}
CACHE = {**BEFORE, "src/s/cache.py": "def get() -> Y:\n    return 1\n",
         "tests/test_cache.py": "from s.cache import get\n\n\n@realizes('s.cache#AC1')\ndef test_get():\n    get()\n"}


@realizes("arch.review.explain#AC2", "arch.review.explain#AC3", "arch.review.explain#AC6", "arch.review.assess#AC4",
          "arch.review.explain#AC9")
def test_new_code_cites_the_criteria_and_component_it_serves():
    diffs = (added_file(SourcePath("src/s/cache.py"), CACHE["src/s/cache.py"]),
             added_file(SourcePath("tests/test_cache.py"), CACHE["tests/test_cache.py"]))
    inp = change(BEFORE, CACHE, diffs, GROWN)
    items = review_items.build(inp)
    body = page(items, "code:s.cache").body
    assert isinstance(body, CodeBody)
    preamble, test = body.tests[0].hunks  # a new file, cut at its definitions
    assert [r.why for r in preamble.reasons] == [Why.IMPORTS] and test.enclosing.name == "test_get"
    test_reasons = {r.why: r for r in test.reasons}
    assert test_reasons[Why.TESTS].refs == ("s.cache#AC1",) and test_reasons[Why.TESTS].detail == "added"
    source = {r.why: r for r in body.sources[0].hunks[0].reasons}
    assert source[Why.EXERCISED].refs == ("s.cache#AC1",)  # its test calls get()
    assert source[Why.NEW_COMPONENT].refs == ("s.cache",)
    evidence = {e.criterion: e.verdict for e in criteria_evidence(design_diff(inp.before, inp.after), inp.after, inp.facts_after)}
    assert evidence["s.cache#AC1"] == "linked, no report"


HELPED = {**BEFORE, "src/s/cache.py": "def get() -> Y:\n    return _load()\n\n\ndef _load() -> Y:\n    return 1\n",
          "tests/test_cache.py": CACHE["tests/test_cache.py"]}
HELPED_AFTER = {**HELPED, "src/s/cache.py": HELPED["src/s/cache.py"].replace("return 1", "return 2")}
HELPER_DIFF = UnifiedDiff("""diff --git a/src/s/cache.py b/src/s/cache.py
--- a/src/s/cache.py
+++ b/src/s/cache.py
@@ -5,2 +5,2 @@
 def _load() -> Y:
-    return 1
+    return 2
""")


@realizes("arch.review.explain#AC3")
def test_a_test_that_reaches_a_helper_through_its_component_is_cited():
    reworded = {**GROWN, "components/s/cache.md": GROWN["components/s/cache.md"].replace("do the thing.", "do it twice.")}
    items = review_items.build(change(HELPED, HELPED_AFTER, parse_diff(HELPER_DIFF), reworded, GROWN))
    (view,) = page(items, "code:s.cache").body.sources[0].hunks
    (reason,) = view.reasons
    assert (reason.why, reason.refs, reason.detail, reason.via) == (Why.EXERCISED, ("s.cache#AC1",), "reworded", "get")


IMPORTED = {**BEFORE, "src/s/shell.py": "from s.core import f\n\n__all__ = []\n\n\ndef main() -> Y:\n    return f(1)\n"}
IMPORTED_AFTER = {**IMPORTED, "src/s/shell.py": "from s.core import (\n    f,\n)\n\n__all__ = [\"main\"]\n\n\ndef main() -> Y:\n    return f(1)\n"}
IMPORT_DIFF = UnifiedDiff("""diff --git a/src/s/shell.py b/src/s/shell.py
--- a/src/s/shell.py
+++ b/src/s/shell.py
@@ -1,3 +1,5 @@
-from s.core import f
+from s.core import (
+    f,
+)
 
-__all__ = []
+__all__ = ["main"]
""")


@realizes("arch.review.explain#AC8")
def test_a_change_to_imports_and_exports_only_says_so():
    items = review_items.build(change(IMPORTED, IMPORTED_AFTER, parse_diff(IMPORT_DIFF)))
    (view,) = page(items, "code:s.shell").body.sources[0].hunks
    assert [r.why for r in view.reasons] == [Why.IMPORTS] and not view.unexplained


# a re-exported name changes where it is defined, not where it is re-exported

REEXPORT_BEFORE = {"src/s/__init__.py": "", "src/s/core.py": "class C:\n    x: X\n",
                   "src/s/shell.py": 'from s.core import C\n\n__all__ = ["C", "main"]\n\n\ndef main() -> Y:\n    return 1\n'}
REEXPORT_AFTER = {**REEXPORT_BEFORE, "src/s/core.py": "class C:\n    x: Y\n",
                  "src/s/shell.py": REEXPORT_BEFORE["src/s/shell.py"].replace("return 1", "return 2")}


@realizes("arch.review.assess#AC3")
def test_a_file_is_not_charged_for_names_it_only_reexports():
    inp = change(REEXPORT_BEFORE, REEXPORT_AFTER, ())
    inp = replace(inp, changed=(FileChange(SourcePath("src/s/core.py"), LineNo(1), LineNo(1)),
                                 FileChange(SourcePath("src/s/shell.py"), LineNo(1), LineNo(1))))
    ports = port_changes(inp.facts_before, inp.facts_after)
    assert {(p.unit, p.reexport_of) for p in ports} == {("s.core", None), ("s.shell", "s.core.C.x")}
    risks = {r.path: r.reasons for r in file_risks(inp, Graph(inp.after), ports)}
    assert "1 interface change that needs review" in risks["src/s/core.py"]
    assert not any("interface" in r for r in risks["src/s/shell.py"])


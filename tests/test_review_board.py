from __future__ import annotations

import http.client
import json
import re
import threading

import pytest

from arch import realize, realizes
from arch.change import apply
from arch.change.ops import AddCriterion
from arch.check import check
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import ComponentId, DesignPath, Text
from arch.realize.facts import Roots, Snapshot, SourcePath
from arch.realize.history import UnifiedDiff, added_file, parse_diff
from arch.review import items as review_items
from arch.review.assess import ReviewInput
from arch.review.items import Glossary, Mechanical, Stage
from arch.review.page import Board, Editor, ProjectRoot, render
from arch.review.feedback import Feedback, Record
from arch.review.session import Category, Decision, ItemState, Reviewer, Session, Verdict, Weight
from tests.conftest import NEED, component

DESIGN = {"needs/n.md": NEED, "components/s.md": component(serves="n"),
          "components/s/core.md": component(serves="n"), "components/s/shell.md": component(serves="n", uses="core")}
CODE = {"src/s/__init__.py": "", "src/s/core.py": "def f(x: X) -> Y:\n    return x\n",
        "src/s/shell.py": "from s.core import f\n\ndef main() -> Y:\n    return f(1)\n",
        "tests/test_core.py": "@realizes('s.core#AC1')\ndef test_f(): ...\n"}
DIFF = UnifiedDiff("""diff --git a/src/s/core.py b/src/s/core.py
--- a/src/s/core.py
+++ b/src/s/core.py
@@ -1,2 +1,3 @@
 def f(x: X) -> Y:
-    return x
+    y = x
+    return y
diff --git a/src/s/shell.py b/src/s/shell.py
--- a/src/s/shell.py
+++ b/src/s/shell.py
@@ -3,2 +3,2 @@ def main
 def main() -> Y:
-    return f(1)
+    return  f(1)
diff --git a/uv.lock b/uv.lock
--- a/uv.lock
+++ b/uv.lock
@@ -1 +1 @@
-x
+y
""")


CONSTRAINT = "---\nkind: constraint\napplies_to: [s.core]\nrule:\n  effects:\n    allow: []\n---\nThe core is pure.\n"


def board_input(extra_ops=(), diff=DIFF, design_after=None):
    before = codec.load({DesignPath(k): v for k, v in DESIGN.items()})
    base_after = codec.load({DesignPath(k): v for k, v in (design_after or DESIGN).items()})
    after = apply(base_after, [AddCriterion(ComponentId("s.core"), Text("When asked twice, it shall answer twice.")),
                               *extra_ops]).after
    facts = realize.extract(Snapshot({SourcePath(k): v for k, v in CODE.items()}, Roots(("src",), ("tests",))))
    diffs = (*parse_diff(diff), added_file(SourcePath("tests/test_core.py"), CODE["tests/test_core.py"]))
    return ReviewInput(Text("main"), before, after, facts, facts, check(Graph(before), facts), check(Graph(after), facts),
                       tuple(), diffs)


def page(items, page_id):
    return next(i for i in items if i.id == page_id)


def deck(inp=None):
    """Pages and the glossary that explains their ids."""
    inp = inp or board_input()
    items = review_items.build(inp)
    return items, Glossary.of(inp.design_after, items, Text("design"))


@realizes("arch.review#AC1", "arch.review#AC2", "arch.review.items#AC1")
def test_pages_come_in_review_order_and_code_in_build_order():
    items = review_items.build(board_input())
    stages = [i.stage for i in items]
    assert stages == sorted(stages, key=list(Stage).index) and items[0].id == "overview"
    both = UnifiedDiff(DIFF.replace("+    return  f(1)", "+    return f(2)"))  # a real change in shell too
    order = [i.id for i in review_items.build(board_input(diff=both)) if i.stage is Stage.CODE]
    assert order == ["code:s.core", "code:s.shell"]  # core is used by shell, so it is reviewed first
    core = page(items, "code:s.core").body
    assert [h.diff.path for h in core.tests] == ["tests/test_core.py"] and [h.diff.path for h in core.sources] == ["src/s/core.py"]
    assert core.realizes == "Do the thing" and core.serves == ("n",)


@realizes("arch.review.items#AC7")
def test_hunks_name_their_definition_and_the_criteria_it_proves():
    core = page(review_items.build(board_input()), "code:s.core").body
    assert [v.enclosing.name for v in core.sources[0].hunks] == ["f"]
    (test,) = core.tests[0].hunks
    assert test.enclosing.name == "test_f" and test.proves == ("s.core#AC1",)


@realizes("arch.review.items#AC4")
def test_needs_and_requirements_are_on_one_page():
    new_need = "---\nkind: need\nstakeholder: Operator\n---\nAn operator can restart it.\n"
    items = review_items.build(board_input(design_after={**DESIGN, "needs/restart.md": new_need}))
    intent = page(items, "intent").body
    assert [(n.need, n.change.value) for n in intent.needs] == [("restart", "added")]
    core = next(r for r in intent.requirements if r.component == "s.core")
    assert [(c.label, c.change.value, c.evidence) for c in core.criteria if c.change.value != "unchanged"] == [
        ("AC2", "added", "no evidence")]
    assert core.serves == ("n",)


@realizes("arch.review.items#AC5", "arch.review.page#AC3", "arch.view.diagram#AC8")
def test_architecture_is_shown_before_and_after_on_one_layout():
    grown = {**DESIGN, "components/s/cache.md": component(serves="n"),
             "components/s/shell.md": component(serves="n", uses="core, cache")}
    items = review_items.build(board_input(design_after=grown))
    arch = page(items, "architecture").body
    panel = next(p for p in arch.panels if p.parent == "s")
    assert "s.cache" not in {n.id for n in panel.before.nodes}
    assert {n.id: n.mark.value for n in panel.after.nodes}["s.cache"] == "added"
    from arch.view.diagram import svg as svg_render
    left, right = svg_render.render_pair(panel.before, panel.after)
    spot = lambda svg, cid: re.search(rf'data-component="{cid}"><title>[^<]*</title><rect x="([\d.]+)" y="([\d.]+)"', svg).groups()
    assert spot(left, "s.core") == spot(right, "s.core")  # same place on both sides
    assert 'class="node ghost" data-component="s.cache"' in left  # missing before: drawn as a ghost
    assert any(r.component == "s.shell" and "now uses cache" in r.detail for r in arch.rewiring)


@realizes("arch.review.items#AC6")
def test_constraints_are_on_one_page_in_plain_words():
    items = review_items.build(board_input(design_after={**DESIGN, "constraints/pure.md": CONSTRAINT}))
    body = page(items, "constraints").body
    (c,) = body.constraints
    assert c.change.value == "added" and c.scope_after == ("s.core",) and "Code must have no effects." in c.rule_after


@realizes("arch.review.items#AC3")
def test_mechanical_changes_are_batched():
    items = review_items.build(board_input())
    batch = page(items, "batch").body
    assert {(h.diff.path, why) for h, why in batch.files} == {("uv.lock", Mechanical.GENERATED),
                                                            ("src/s/shell.py", Mechanical.FORMATTING)}
    assert not any(i.id == "code:s.shell" for i in items)


@realizes("arch.review.items#AC2")
def test_digests_change_exactly_when_the_page_changes():
    a = {i.id: i.digest for i in review_items.build(board_input())}
    assert a == {i.id: i.digest for i in review_items.build(board_input())}
    c = {i.id: i.digest for i in review_items.build(board_input([AddCriterion(ComponentId("s.shell"), Text("It shall start."))]))}
    assert c["batch"] == a["batch"] and c["intent"] != a["intent"]


ME = Reviewer("me")


def verdict(item, decision, weight=Weight.BLOCKING, comment=None):
    return Verdict(item.id, decision, item.digest, ME, comment, Category.BUG, weight)


@realizes("arch.review.session#AC1", "arch.review.session#AC2")
def test_verdicts_go_stale_and_block_downstream():
    items = review_items.build(board_input())
    intent, code = page(items, "intent"), page(items, "code:s.core")
    s = Session(Text("branch")).decide(verdict(intent, Decision.CHANGES_REQUESTED, comment="that is a solution"))
    assert s.state(intent, items) is ItemState.CHANGES_REQUESTED and s.state(code, items) is ItemState.BLOCKED
    changed = review_items.build(board_input([AddCriterion(ComponentId("s.core"), Text("It shall also log."))]))
    assert s.state(page(changed, "intent"), changed) is ItemState.STALE and not s.open_requests(changed)


@realizes("arch.review.feedback#AC1", "arch.review.feedback#AC2")
def test_feedback_lists_blocking_requests_first_and_round_trips():
    items = review_items.build(board_input())
    s = (Session(Text("branch"))
         .decide(verdict(page(items, "code:s.core"), Decision.CHANGES_REQUESTED, Weight.NIT, "rename y"))
         .decide(verdict(page(items, "intent"), Decision.CHANGES_REQUESTED, comment="say what, not how"))
         .decide(verdict(page(items, "overview"), Decision.APPROVED)))
    text = Feedback(s, items).to_markdown()
    assert text.index("say what, not how") < text.index("rename y") and "[blocking, bug]" in text
    assert "made at the code station" in text and "--found-at review" in text  # each request is an escape
    assert Session.load(s.dump(), Text("x")) == s and Session.load("not json", Text("x")) == Session(Text("x"))
    assert "Reviewed-by: me" in Record(s, items).to_markdown()


@realizes("arch.review.page#AC1")
def test_page_is_self_contained_and_escapes_content():
    items, glossary = deck(board_input([AddCriterion(ComponentId("s.core"), Text("It shall render <script>x</script>."))]))
    html = render(items, Session(Text("b")), Text("Review"), glossary)
    assert not re.search(r'(src|href)="(https?:)?//', html)
    assert "<script>x</script>" not in html and "&lt;script&gt;x&lt;/script&gt;" in html
    assert all(f'id="{i.id}"' in html for i in items) and 'class="t-keyword">def</span>' in html


@realizes("arch.review.page#AC2")
def test_arrow_keys_flip_pages_and_every_action_has_a_key():
    html = render(*deck()[:1], Session(Text("b")), Text("Review"), deck()[1])
    for key in ("'ArrowRight'", "'ArrowLeft'", "'a'", "'r'", "'c'", "'n'"):
        assert f"k === {key}" in html
    assert "decision === 'approved' ? nextOpen()" in html  # approving moves on to the next undecided page


class FakeWorkspace:
    """Just enough workspace for the catalog's review operations."""

    def __init__(self, board):
        self.saved = None
        self._board = board

    def session(self, name):
        return self.saved or Session(name)

    def save_session(self, session):
        self.saved = session

    def reviewer(self):
        return ME


@realizes("arch.integrate.server#AC1", "arch.integrate.server#AC2")
def test_server_binds_loopback_and_refuses_foreign_writes():
    from arch.integrate import server

    items, glossary = deck()
    board = Board(items, Session(Text("b")), Text("Review"), glossary)
    reviewing = server.Reviewing.__new__(server.Reviewing)
    reviewing.ws, reviewing.base, reviewing.board = FakeWorkspace(board), "HEAD", board
    try:
        httpd = server.make_server(reviewing)
    except PermissionError:
        pytest.skip("this environment does not allow binding a local port")
    host, port = httpd.server_address
    assert host == "127.0.0.1"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(method, path, body=None, headers=None):
        c = http.client.HTTPConnection(host, port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        return r.status, r.read().decode()

    try:
        assert call("GET", "/")[0] == 200
        assert call("GET", "/", headers={"Host": "evil.example"})[0] == 403
        item = board.items[0]
        payload = json.dumps({"item": item.id, "digest": item.digest, "decision": "approved"})
        assert call("POST", "/api/verdict", payload, {"Content-Type": "text/plain"})[0] == 403
        assert call("POST", "/api/verdict", payload, {"Content-Type": "application/json", "Origin": "https://evil.example"})[0] == 403
        status, body = call("POST", "/api/verdict", payload, {"Content-Type": "application/json"})
        assert status == 200 and json.loads(body)["items"][0]["state"] == "approved"
        assert reviewing.ws.saved.verdicts[item.id].reviewer == "me"
        stale = json.dumps({"item": item.id, "digest": "0" * 16, "decision": "approved"})
        assert call("POST", "/api/verdict", stale, {"Content-Type": "application/json"})[0] == 409
    finally:
        httpd.shutdown()
        httpd.server_close()


@realizes("arch.review.page#AC4")
def test_every_id_explains_itself_on_hover_and_links_somewhere():
    items, glossary = deck()
    html = render(items, Session(Text("b")), Text("Review"), glossary, ProjectRoot("/repo"), Editor.VSCODE)
    assert 'data-tip="AC1: When asked, it shall do the thing.' in html  # a criterion says what it means
    assert '<a class="ref" href="#code:s.core" data-tip="s.core must do the thing">core</a>' in html  # to its code page
    assert 'href="vscode://file/repo/src/s/core.py:2"' in html  # a changed line opens in the editor
    assert 'href="vscode://file/repo/design/components/s/core.md"' in html  # and so does the design
    assert 'href=""' not in html  # nothing links to nowhere
    plain = render(items, Session(Text("b")), Text("Review"), glossary, ProjectRoot("/repo"), Editor.NONE)
    assert "vscode://" not in plain


@realizes("arch.review.page#AC5")
def test_each_page_says_in_one_sentence_what_it_shows():
    items, glossary = deck()
    html = render(items, Session(Text("b")), Text("Review"), glossary)
    leads = re.findall(r'<p class="lead">(.*?)</p>', html)
    assert len(leads) == len(items)
    assert all(";" not in lead and lead.count(". ") <= 2 for lead in leads)


@realizes("arch.review.items#AC8", "arch.review.page#AC6")
def test_the_legend_shows_only_the_colours_in_use():
    grown = {**DESIGN, "components/s/cache.md": component(serves="n"),
             "components/s/shell.md": component(serves="n", uses="core, cache")}
    items, glossary = deck(board_input(design_after=grown))
    html = render(items, Session(Text("b")), Text("Review"), glossary)
    legend = re.search(r'<div class="legend">(.*?)</div>', html).group(1)
    assert "Added" in legend and "Removed" not in legend
    assert page(items, "architecture").title.startswith("2 components changed")


@realizes("arch.review.items#AC12")
def test_findings_raised_and_answers_given_are_reviewed():
    from dataclasses import replace

    from arch.check.engine import Finding, FindingKey, Kind, RuleId, Source, Station, Subject
    from arch.check.ledger import Answer, Ledger, Noticed, Response, render_noticed, render_response

    late = Noticed(Finding(Subject("s.core"), RuleId("robert"), FindingKey("adds-a-function"), Kind.DEFECT,
                           Text("AC2 adds a function."), Text(""), None, Station.REQUIREMENTS, source=Source.PERSON,
                           evidence=Text("answer twice"), found_at=Station.REVIEW), "adds-a-function")
    no = Response("declined-it", Answer.DECLINED, Text("claude"), Text("AC2 sets the output of the one function."),
                  (late.finding.identity,))
    ledger = Ledger.parse({late.path: render_noticed(late), no.path: render_response(no)})
    inp = board_input()
    inp = replace(inp, ledger_after=ledger, report_after=check(Graph(inp.design_after), inp.facts_after, ledger))
    items = review_items.build(inp)
    findings = page(items, "findings")
    assert findings.title == "1 answer given and 1 finding raised" and findings.risk.value == "high"  # a declined defect
    html = render(items, Session(Text("b")), Text("Review"), Glossary.of(inp.design_after, items, Text("design")))
    assert "AC2 sets the output of the one function." in html and '<blockquote class="quote">answer twice' in html
    assert "Made at requirements, noticed at review" in html

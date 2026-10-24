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
from arch.review.items import Mechanical, Stage
from arch.review.page import Board, render
from arch.review.session import Category, Decision, Feedback, ItemState, Record, Reviewer, Session, Verdict, Weight
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


def board_input(extra_ops=(), diff=DIFF):
    before = codec.load({DesignPath(k): v for k, v in DESIGN.items()})
    after = apply(before, [AddCriterion(ComponentId("s.core"), Text("When asked twice, it shall answer twice.")),
                           *extra_ops]).after
    facts = realize.extract(Snapshot({SourcePath(k): v for k, v in CODE.items()}, Roots(("src",), ("tests",))))
    diffs = (*parse_diff(diff), added_file(SourcePath("tests/test_core.py"), CODE["tests/test_core.py"]))
    return ReviewInput(Text("main"), before, after, facts, facts, check(Graph(before), facts), check(Graph(after), facts),
                       tuple(), diffs)


@realizes("arch.review#AC1", "arch.review#AC2", "arch.review.items#AC1")
def test_items_come_in_review_order_and_code_in_build_order():
    items = review_items.build(board_input())
    stages = [i.stage for i in items]
    assert stages == sorted(stages, key=list(Stage).index)
    ids = [i.id for i in items]
    assert ids[0] == "readiness" and "intent:component:s.core" in ids
    both = UnifiedDiff(DIFF.replace("+    return  f(1)", "+    return f(2)"))  # now a real change in shell too
    order = [i.id for i in review_items.build(board_input(diff=both)) if i.stage is Stage.CODE]
    assert order == ["code:s.core", "code:s.shell"]  # core is used by shell, so it is reviewed first
    core = next(i for i in items if i.id == "code:s.core").body
    assert [h.diff.path for h in core.tests] == ["tests/test_core.py"] and [h.diff.path for h in core.sources] == ["src/s/core.py"]
    assert core.sources[0].symbols == ("f",)
    assert "intent:component:s.core" in next(i for i in items if i.id == "code:s.core").blocked_by


@realizes("arch.review.items#AC3")
def test_mechanical_changes_are_batched():
    items = review_items.build(board_input())
    batch = next(i for i in items if i.stage is Stage.BATCH).body
    assert {(h.diff.path, why) for h, why in batch.files} == {("uv.lock", Mechanical.GENERATED),
                                                            ("src/s/shell.py", Mechanical.FORMATTING)}
    assert not any(i.id == "code:s.shell" for i in items)  # its only change was formatting


@realizes("arch.review.items#AC2")
def test_digests_change_exactly_when_the_item_changes():
    a = {i.id: i.digest for i in review_items.build(board_input())}
    b = {i.id: i.digest for i in review_items.build(board_input())}
    assert a == b
    c = {i.id: i.digest for i in review_items.build(board_input([AddCriterion(ComponentId("s.shell"), Text("It shall start."))]))}
    assert c["code:s.core"] == a["code:s.core"]  # a change elsewhere leaves this item's approval valid
    d = {i.id: i.digest for i in review_items.build(board_input([AddCriterion(ComponentId("s.core"), Text("It shall stop."))]))}
    assert d["code:s.core"] != a["code:s.core"]  # a change to what the item shows invalidates it


ME = Reviewer("me")


def verdict(item, decision, weight=Weight.BLOCKING, comment=None):
    return Verdict(item.id, decision, item.digest, ME, comment, Category.BUG, weight)


@realizes("arch.review.session#AC1", "arch.review.session#AC2")
def test_verdicts_go_stale_and_block_downstream():
    items = review_items.build(board_input())
    by_id = {i.id: i for i in items}
    intent, code = by_id["intent:component:s.core"], by_id["code:s.core"]
    s = Session(Text("branch")).decide(verdict(intent, Decision.CHANGES_REQUESTED, comment="that is a solution"))
    assert s.state(intent, items) is ItemState.CHANGES_REQUESTED
    assert s.state(code, items) is ItemState.BLOCKED
    changed = review_items.build(board_input([AddCriterion(ComponentId("s.core"), Text("It shall also log."))]))
    new_intent = next(i for i in changed if i.id == intent.id)
    assert s.state(new_intent, changed) is ItemState.STALE and not s.open_requests(changed)


@realizes("arch.review.session#AC3")
def test_feedback_lists_blocking_requests_first_and_round_trips():
    items = review_items.build(board_input())
    by_id = {i.id: i for i in items}
    s = (Session(Text("branch"))
         .decide(verdict(by_id["code:s.core"], Decision.CHANGES_REQUESTED, Weight.NIT, "rename y"))
         .decide(verdict(by_id["intent:component:s.core"], Decision.CHANGES_REQUESTED, comment="say what, not how"))
         .decide(verdict(by_id["readiness"], Decision.APPROVED)))
    text = Feedback(s, items).to_markdown()
    assert text.index("say what, not how") < text.index("rename y") and "[blocking, bug]" in text
    assert Session.load(s.dump(), Text("x")) == s
    assert Session.load("not json", Text("x")) == Session(Text("x"))
    assert "Reviewed-by: me" in Record(s, items).to_markdown()


@realizes("arch.review.page#AC1")
def test_page_is_self_contained_and_escapes_content():
    items = review_items.build(board_input([AddCriterion(ComponentId("s.core"), Text("It shall render <script>x</script>."))]))
    page = render(items, Session(Text("b")), Text("Review"))
    assert not re.search(r'(src|href)="(https?:)?//', page)
    assert "<script>x</script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page
    assert all(f'id="{i.id}"' in page for i in items)
    assert '"approved"' in page and "/api/verdict" in page


@realizes("arch.review.page#AC2")
def test_page_has_keys_for_every_action():
    page = render(review_items.build(board_input()), Session(Text("b")), Text("Review"))
    for key in ("'j'", "'k'", "'n'", "'a'", "'r'", "'c'"):
        assert f"k === {key}" in page
    assert "nextOpen()" in page.split("async function send")[1]  # approving moves on to the next open item


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

    board = Board(review_items.build(board_input()), Session(Text("b")), Text("Review"))
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

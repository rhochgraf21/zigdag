from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arch import realize, realizes
from arch.change import Outcome, apply
from arch.change.diff import ChangeClass, NodeChangeType, diff
from arch.change.ops import (
    AddComponent, AddCriterion, AddDecision, AddNeed, Link, Move, Rejected, Relation, Remove, Removal,
    SetField, Settable, Unlink, from_json,
)
from arch.model import codec
from arch.model.codec import NodeFile
from arch.model.ids import ComponentId, DesignPath, Ref, Text
from arch.model.schema import Kind
from arch.realize.facts import Roots, Snapshot, SourcePath
from tests.conftest import NEED, component

FILE = component(uses="b", serves="n") + "\n## Rationale\nKeep this.  # odd spacing\n"


@realizes("arch.model.codec#AC2")
def test_set_field_touches_only_its_line():
    f = NodeFile(Kind.COMPONENT, FILE)
    f.set_field("hides", Text("a different secret"))
    before, after = FILE.split("\n"), f.text.split("\n")
    assert len(before) == len(after)
    assert [i for i, (x, y) in enumerate(zip(before, after)) if x != y] == [4]


@realizes("arch.change.ops#AC4")
@given(st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1).filter(lambda s: s.strip()))
def test_set_and_reset_restore_bytes(value):
    f = NodeFile(Kind.COMPONENT, FILE)
    f.set_field("realizes", Text(value))
    assert codec.parse(DesignPath("components/s/a.md"), f.text)[0].realizes == value.strip()
    f.set_field("realizes", Text("Do the thing"))
    assert f.text == FILE


def test_new_fields_go_in_canonical_order():
    f = NodeFile(Kind.COMPONENT, FILE)
    f.set_field("exports", (Ref("x"),))
    keys = [line.split(":")[0] for line in f.text.split("---")[1].strip().split("\n")]
    original = [line.split(":")[0] for line in FILE.split("---")[1].strip().split("\n")]
    assert [k for k in keys if k != "exports"] == original  # existing order is the author's; left alone
    assert keys.index("exports") == keys.index("status") - 1  # the new field goes where canonical order puts it


def test_criteria_and_decisions_are_appended_in_their_sections():
    f = NodeFile(Kind.COMPONENT, FILE)
    assert f.add_criterion(Text("When asked twice, it shall answer twice.")) == "AC2"
    from arch.model.codec.edit import DecisionDraft
    from arch.model.schema import DecisionLabel
    f.add_decision(DecisionDraft(Text("Use X"), [(DecisionLabel.CHOSE, Text("X")), (DecisionLabel.BECAUSE, Text("simple"))]))
    node, issues = codec.parse(DesignPath("components/s/a.md"), f.text)
    assert not issues
    assert [c.id for c in node.criteria] == ["s.a#AC1", "s.a#AC2"]
    assert [d.title for d in node.decisions] == ["Use X"] and "Keep this.  # odd spacing" in f.text


DESIGN = {
    "needs/n.md": NEED,
    "components/s.md": component(serves="n"),
    "components/s/core.md": component(serves="n", exports="api"),
    "components/s/core/api.md": component(),
    "components/s/shell.md": component(serves="n", uses="core.api"),
}


def design(files=DESIGN):
    return codec.load({DesignPath(k): v for k, v in files.items()})


@realizes("arch.change#AC1", "arch.change#AC3")
def test_batches_apply_all_or_nothing():
    ok = apply(design(), [AddComponent(ComponentId("s.cli"), Text("Offer commands"), Text("A CLI"), Text("Parsing"),
                                       uses=(Ref("shell"),), serves=("n",), criteria=(Text("It shall run."),)),
                          Link(ComponentId("s.shell"), Relation.EXPORTS, Ref("x"))])
    assert ok.outcome is Outcome.REJECTED and "x" in ok.reason  # exports a child that does not exist
    good = apply(design(), [AddComponent(ComponentId("s.cli"), Text("Offer commands"), Text("A CLI"), Text("Parsing"),
                                         uses=(Ref("shell"),), serves=("n",), criteria=(Text("It shall run."),))])
    assert good.outcome is Outcome.APPLIED
    assert [e.path for e in good.design_edits] == ["components/s/cli.md"] and good.design_edits[0].before is None
    assert good.after.components["s.cli"].uses == ("shell",)
    assert [c.id for c in good.after.components["s.cli"].criteria] == ["s.cli#AC1"]


@realizes("arch.change#AC2")
def test_preconditions_and_integrity_reject():
    assert apply(design(), [AddComponent(ComponentId("x.y"), Text("r"), Text("s"))]).outcome is Outcome.REJECTED
    dangling = apply(design(), [Link(ComponentId("s.shell"), Relation.USES, Ref("nowhere"))])
    assert dangling.outcome is Outcome.REJECTED and "nowhere" in dangling.reason
    quality = apply(design(), [SetField(Text("s.core.api"), Settable.HIDES, None)])
    assert quality.outcome is Outcome.APPLIED and [f.rule for f in quality.new_findings.findings] == ["S006"]


@realizes("arch.change.ops#AC2")
def test_move_rewrites_references_exports_and_links_in_code():
    code = {SourcePath("tests/test_api.py"): "@realizes('s.core.api#AC1')\ndef test(): ...\n"}
    snap = Snapshot(code, Roots(("src",), ("tests",)))
    links = realize.extract(snap).links
    r = apply(design(), [Move(ComponentId("s.core"), ComponentId("s.engine"))], snap, links)
    assert r.outcome is Outcome.APPLIED, r.reason
    assert set(r.after.components) >= {"s.engine", "s.engine.api"} and "s.core" not in r.after.components
    assert r.after.components["s.shell"].uses == ("engine.api",)
    assert [e.after for e in r.source_edits] == ["@realizes('s.engine.api#AC1')\ndef test(): ...\n"]
    rename = apply(design(), [Move(ComponentId("s.core.api"), ComponentId("s.core.port"))])
    assert rename.after.components["s.core"].exports == ("port",)
    assert rename.after.components["s.shell"].uses == ("core.port",)


@realizes("arch.change.ops#AC3")
def test_remove_refuses_while_used_and_cascades_on_request():
    refused = apply(design(), [Remove(Text("s.core"))])
    assert refused.outcome is Outcome.REJECTED and "s.shell" in refused.reason
    gone = apply(design(), [Remove(Text("s.core"), Kind.COMPONENT, Removal.CASCADE)])
    assert gone.outcome is Outcome.APPLIED, gone.reason
    assert "s.core.api" not in gone.after.components and gone.after.components["s.shell"].uses == ()


@realizes("arch.change.ops#AC1")
def test_operations_round_trip_through_json():
    ops = [Link(ComponentId("a"), Relation.USES, Ref("b")), SetField(Text("a"), Settable.STATUS, Text("draft")),
           Remove(Text("n"), Kind.NEED, Removal.CASCADE), AddNeed("n2", Text("People can do X."))]
    assert [from_json(op.to_json()) for op in ops] == ops
    for bad in ({"op": "teleport"}, {"op": "link", "component": "a", "relation": "likes", "target": "b"},
                {"op": "set", "node": "a", "field": "colour", "value": "x"}, {"op": "move", "component": "a", "extra": 1}):
        try:
            from_json(bad)
            raise AssertionError(bad)
        except Rejected:
            pass


@realizes("arch.change.diff#AC1", "arch.change.diff#AC2", "arch.change.diff#AC3")
def test_diff_classifies_changes_and_detects_moves():
    before = design()
    r = apply(before, [SetField(Text("s.shell"), Settable.REALIZES, Text("Offer it")),
                       AddCriterion(ComponentId("s.shell"), Text("It shall be offered.")),
                       AddDecision(ComponentId("s.shell"), Text("Shell first"), Text("a shell"), Text("simple")),
                       Move(ComponentId("s.core"), ComponentId("s.engine")),
                       Unlink(ComponentId("s.shell"), Relation.SERVES, Ref("n"))])
    d = diff(before, r.after)
    by_id = {c.ident: c for c in d.changes}
    assert by_id["s.engine"].type is NodeChangeType.MOVED and by_id["s.engine"].moved_from == "s.core"
    shell = {f.field: f.change_class for f in by_id["s.shell"].fields}
    assert shell["realizes"] is ChangeClass.INTENT and shell["AC2"] is ChangeClass.INTENT
    assert shell["serves"] is ChangeClass.INTENT and shell["uses"] is ChangeClass.STRUCTURE
    assert shell["decision 'Shell first'"] is ChangeClass.DESIGN
    reformatted = design({**DESIGN, "components/s/shell.md": DESIGN["components/s/shell.md"].replace("uses: [core.api]", "uses: [ core.api ]")})
    assert diff(before, reformatted).empty


@realizes("arch.change.ops#AC6", "arch.change.ops#AC7")
def test_split_gives_a_second_function_its_own_part_and_relinks_its_tests():
    from arch.change.ops import Split
    from arch.model.ids import CriterionLabel

    files = {DesignPath("needs/n.md"): NEED, DesignPath("components/s.md"): component(serves="n"),
             DesignPath("components/s/review.md"): component(serves="n", criteria=3)}
    code = {SourcePath("src/s/__init__.py"): "",
            SourcePath("tests/test_r.py"): "@realizes('s.review#AC1')\ndef a(): ...\n\n@realizes('s.review#AC3')\ndef b(): ...\n"}
    snap = Snapshot(code, Roots(("src",), ("tests",)))
    links = realize.extract(snap).links
    split = Split(ComponentId("s.review"), (CriterionLabel("AC3"),), ComponentId("s.feedback"),
                  Text("Tell the author which change requests are still open"), Text("A list built from the verdicts"),
                  Text("How requests are ranked"))
    r = apply(codec.load(files), [split], snap, links)
    assert r.outcome is Outcome.APPLIED, r.reason
    review, feedback = r.after.components["s.review"], r.after.components["s.feedback"]
    assert [c.id for c in review.criteria] == ["s.review#AC1", "s.review#AC2"]  # the others keep their labels
    assert [c.id for c in feedback.criteria] == ["s.feedback#AC1"] and feedback.serves == ("n",)  # a top-level part
    (edit,) = r.source_edits
    assert "@realizes('s.feedback#AC1')" in edit.after and "@realizes('s.review#AC1')" in edit.after
    everything = Split(ComponentId("s.review"), tuple(CriterionLabel(f"AC{i}") for i in (1, 2, 3)), ComponentId("s.x"),
                       Text("Do it"), Text("A part"))
    assert apply(codec.load(files), [everything], snap, links).outcome is Outcome.REJECTED

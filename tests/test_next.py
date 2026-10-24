from __future__ import annotations

from arch import realizes
from arch.check import Baseline, check
from arch.guide.method import MethodName
from arch.guide.next import ActionKind, next_actions
from tests.conftest import NEED, component, graph

G = graph({
    "needs/n.md": NEED,
    "components/s.md": component(serves="n"),
    "components/s/a.md": component(serves="n", uses="b"),
    "components/s/b.md": component(serves="n", uses="a"),
    "components/s/c.md": component(serves="n", hides=None, criteria=0),
    "components/s/c/deep.md": component(uses="ghost"),
})


@realizes("arch.guide.next#AC1", "arch.guide.next#AC2")
def test_actions_are_ranked_deterministically_and_say_how():
    actions = next_actions(G, check(G))
    kinds = [a.kind for a in actions]
    assert kinds == sorted(kinds, key=list(ActionKind).index)
    assert actions[0].kind is ActionKind.FIX_BLOCKING and actions[0].subject == "s.c.deep"
    coupling = next(a for a in actions if a.kind is ActionKind.RESOLVE_COUPLING)
    assert coupling.method is MethodName.RESOLVE_COUPLING
    assert any(a.method is MethodName.WRITE_REQUIREMENTS for a in actions if a.subject == "s.c")
    assert next_actions(G, check(G)) == actions


def test_baselined_findings_and_scope_are_respected():
    report = check(G)
    baselined = check(G, baseline=Baseline.of(report.findings))
    assert all(a.because.rule != "S001" for a in next_actions(G, baselined))
    assert {a.subject for a in next_actions(G, report, "s.c")} <= {"s.c", "s.c.deep"}

from __future__ import annotations

from arch import realizes
from arch.check import Baseline, BaselineText, check
from arch.check.engine import Severity
from tests.conftest import NEED, component, graph

BROKEN = graph({"needs/n.md": NEED, "components/s.md": component(serves="n"),
                "components/s/a.md": component(uses="ghost", serves="n")})


@realizes("arch.check.baseline#AC1", "arch.check#AC3")
def test_baselined_findings_are_reported_but_do_not_block():
    first = check(BROKEN)
    assert first.blocking
    base = Baseline.of(first.findings)
    again = check(BROKEN, baseline=base)
    assert not again.blocking and any(again.is_baselined(f) for f in again.findings)


@realizes("arch.check.baseline#AC2")
def test_fixed_findings_are_flagged_and_drop_out_on_update():
    base = Baseline.of(check(BROKEN).findings)
    fixed = graph({"needs/n.md": NEED, "components/s.md": component(serves="n"), "components/s/a.md": component(serves="n")})
    report = check(fixed, baseline=base)
    nudge = [f for f in report.findings if f.rule == "B001"]
    assert len(nudge) == 1 and nudge[0].severity is Severity.INFO
    assert Baseline.of(report.findings).entries == frozenset()


@realizes("arch.check.baseline#AC3")
def test_baseline_file_is_sorted_one_per_line_and_round_trips():
    base = Baseline.of(check(BROKEN).findings)
    text = base.render()
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == sorted(lines) and all(l.count("\t") == 2 for l in lines)
    assert Baseline.parse(BaselineText(text)) == base

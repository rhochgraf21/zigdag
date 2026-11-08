from zigdag import verifies
from zigdag.core.findings import Report, Result, Span, finding


@verifies("zigdag.core.vocabulary.findings#carry", "zigdag.core.vocabulary#define")
def test_findings_carry_their_rule_subject_place_and_a_stable_digest():
    a = finding(Result.BREAKS, "names", "app", Span("design/x.yaml", 2, 1), "bad", "content")
    b = finding(Result.BREAKS, "names", "app", Span("design/x.yaml", 1, 1), "bad", "content")
    assert (a.rule, a.about, a.span.line) == ("names", "app", 2)
    assert a.digest == b.digest == finding(Result.QUESTION, "names", "app", None, "other", "content").digest
    report = Report.of([a, b, a])
    assert [f.span.line for f in report.findings] == [1, 2] and report.breaks

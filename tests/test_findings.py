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


@verifies("zigdag.core.vocabulary.findings.report#passes")
def test_a_run_passes_only_with_no_break_and_no_open_question():
    def of(*results: Result) -> Report:
        return Report.of(finding(r, "names", f"app.{i}", None, "said", "content") for i, r in enumerate(results))

    assert of().passes and of(Result.TODO).passes  # work not yet started does not stand in the way
    assert not of(Result.QUESTION).passes and not of(Result.TODO, Result.BREAKS).passes

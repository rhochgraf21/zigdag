"""What a check reports (DESIGN2 §1, principle 6): a break, a question, something to do, or a test result that is out
of date. Holding reports nothing."""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NewType

import deal

from zigdag.core.measures import Column, Line
from zigdag.core.texts import Content, Say

RuleName = NewType("RuleName", str)  # the rule that reported: a check kind, a built-in, or a record rule such as "names"
Subject = NewType("Subject", str)  # the name a finding is about: an FR, an outcome reference, a rule, a file
RecordPath = NewType("RecordPath", str)  # a path relative to the project root, with forward slashes
Digest = NewType("Digest", str)  # a short sha256 of the content a finding is about


class Result(enum.Enum):
    BREAKS = "breaks"
    TODO = "to do"
    QUESTION = "question"
    # What the tests showed no longer counts, because the code or the tests changed since they ran. It is apart from
    # "to do" because the two are answered differently: this one by running the tests again, that one by doing work.
    # So a run can refuse to say yes on stale results without refusing on work that was never started.
    OUT_OF_DATE = "out of date"


BUILT_IN_PATH = RecordPath("<built-in>")  # where what zigdag itself provides is "written"
DIGEST_LENGTH = 16  # hex digits: enough that two contents sharing a digest is not a practical worry
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True, order=True)
class Span:
    """Where something is written. Line and column count from 1."""

    path: RecordPath
    line: Line
    column: Column

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}"

    @property
    @deal.ensure(lambda self, result: result == (self.path == BUILT_IN_PATH))
    def built_in(self) -> bool:
        """Whether it is zigdag's own, such as a built-in rule, rather than written in the project."""
        return self.path == BUILT_IN_PATH


BUILT_IN_SPAN = Span(BUILT_IN_PATH, 1, 1)


@dataclass(frozen=True)
class Finding:
    result: Result
    rule: RuleName
    about: Subject
    span: Span | None
    say: Say
    digest: Digest

    @deal.ensure(lambda self, result: result[3:] == (self.rule, self.about, self.say))  # place first, then the rest
    def sort_key(self) -> tuple:
        where = (self.span.path, self.span.line, self.span.column) if self.span else ("", 0, 0)
        return (*where, self.rule, self.about, self.say)


@deal.post(lambda result: len(result) == DIGEST_LENGTH and set(result) <= _HEX_DIGITS)
def digest_of(*parts: Content) -> Digest:
    return Digest(hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:DIGEST_LENGTH])


@deal.ensure(lambda kind, rule, about, span, say, *content, result: (result.result, result.rule, result.about,
                                                                     result.span, result.say) == (kind, rule, about,
                                                                                                  span, say))
@deal.ensure(lambda kind, rule, about, span, say, *content, result: result.digest == digest_of(
    rule, about, *(content or (say,))))  # the same content, the same digest, so an answer finds its question again
def finding(kind: Result, rule: RuleName, about: Subject, span: Span | None, say: Say, *content: Content) -> Finding:
    """A finding whose digest covers what it is about, so an answered question returns when that content changes."""
    return Finding(kind, RuleName(rule), Subject(about), span, say, digest_of(rule, about, *(content or (say,))))


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]

    @staticmethod
    @deal.post(lambda report: list(report.findings) == sorted(report.findings, key=Finding.sort_key))
    @deal.post(lambda report: len({(f.result, f.rule, f.about, f.span, f.say) for f in report.findings})
               == len(report.findings))  # each finding once
    def of(findings: Iterable[Finding]) -> Report:
        unique = {(f.result, f.rule, f.about, f.span, f.say): f for f in findings}
        return Report(tuple(sorted(unique.values(), key=Finding.sort_key)))

    @deal.ensure(lambda self, kind, result: all(f.result is kind for f in result))
    @deal.ensure(lambda self, kind, result: len(result) == sum(f.result is kind for f in self.findings))
    def of_result(self, kind: Result) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.result is kind)

    @property
    @deal.ensure(lambda self, result: result == bool(self.of_result(Result.BREAKS)))
    def breaks(self) -> bool:
        return any(f.result is Result.BREAKS for f in self.findings)

    @property
    @deal.ensure(lambda self, result: result == all(f.result is Result.TODO for f in self.findings))
    def passes(self) -> bool:
        """Whether a run may say yes. A break, a question left open, and a test result that is out of date are each
        not a yes (DESIGN2 §1, principle 6); a thing to do is work not yet started, so it does not stand in the way."""
        return all(f.result is Result.TODO for f in self.findings)

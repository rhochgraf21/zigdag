"""What a check reports (DESIGN2 §1, principle 6): a break, something to do, or a question. Holding reports nothing."""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NewType

RuleName = NewType("RuleName", str)  # the rule that reported: a check kind, a built-in, or a record rule such as "names"
Subject = NewType("Subject", str)  # the name a finding is about: an FR, an outcome reference, a rule, a file
RecordPath = NewType("RecordPath", str)  # a path relative to the project root, with forward slashes
Digest = NewType("Digest", str)  # a short sha256 of the content a finding is about


class Result(enum.Enum):
    BREAKS = "breaks"
    TODO = "to do"
    QUESTION = "question"


BUILT_IN_PATH = RecordPath("<built-in>")  # where what zigdag itself provides is "written"


@dataclass(frozen=True, order=True)
class Span:
    """Where something is written. Line and column count from 1."""

    path: RecordPath
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}"

    @property
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
    say: str
    digest: Digest

    def sort_key(self) -> tuple:
        where = (self.span.path, self.span.line, self.span.column) if self.span else ("", 0, 0)
        return (*where, self.rule, self.about, self.say)


def digest_of(*parts: str) -> Digest:
    return Digest(hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16])


def finding(result: Result, rule: str, about: str, span: Span | None, say: str, *content: str) -> Finding:
    """A finding whose digest covers what it is about, so an answered question returns when that content changes."""
    return Finding(result, RuleName(rule), Subject(about), span, say, digest_of(rule, about, *(content or (say,))))


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]

    @staticmethod
    def of(findings: Iterable[Finding]) -> Report:
        unique = {(f.result, f.rule, f.about, f.span, f.say): f for f in findings}
        return Report(tuple(sorted(unique.values(), key=Finding.sort_key)))

    def of_result(self, result: Result) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.result is result)

    @property
    def breaks(self) -> bool:
        return any(f.result is Result.BREAKS for f in self.findings)

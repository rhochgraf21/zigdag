"""The log (DESIGN2 §7.7): what people and agents raised, answered, critiqued and approved, one event per line.

The log is append-only and ordered by time. Check results are never logged; they are worked out each time.
A question a guess check asks is answered once, and stays answered until what it is about changes.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import NewType

import deal

from zigdag.core.record.read import DESIGN_DIR
from zigdag.core.findings import Digest, Finding, RecordPath, Report, Result, RuleName, Span, Subject, digest_of, finding
from zigdag.core.measures import Line, Version
from zigdag.core.texts import FileText, Say, Written

LOG_FILE = RecordPath(f"{DESIGN_DIR}/log.jsonl")
LOG_RULE = "log"
GIT_ATTRIBUTES = RecordPath(".gitattributes")  # where git is told to merge the log as a union, when an event is added

Timestamp = NewType("Timestamp", str)  # UTC, to the second: 2026-11-04T14:12:05Z
Actor = NewType("Actor", str)  # who: a person or an agent
EventLine = NewType("EventLine", str)  # one event, as one line of the log
ThreadId = NewType("ThreadId", str)  # worked out from at, by, on and say

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DIGEST = re.compile(r"[0-9a-f]{16}")


class Kind(enum.Enum):
    DEFECT = "defect"
    QUESTION = "question"
    IDEA = "idea"


class Answer(enum.Enum):
    FIXED = "fixed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    ANSWERED = "answered"


@dataclass(frozen=True)
class Raised:
    at: Timestamp
    by: Actor
    id: ThreadId
    on: str
    kind: Kind
    say: str
    evidence: str | None
    line: int


@dataclass(frozen=True)
class Answered:
    """An answer to a raised thread (id), or to a question a check asked (check, on, digest)."""

    at: Timestamp
    by: Actor
    answer: Answer
    say: Say
    id: ThreadId | None
    check: RuleName | None
    on: Subject | None
    digest: Digest | None
    countermeasure: Subject | None
    line: Line


@dataclass(frozen=True)
class Critiqued:
    at: Timestamp
    by: Actor
    on: str
    digest: Digest
    rubric: int | None  # the rubric version the critic answered
    line: int


@dataclass(frozen=True)
class Approved:
    at: Timestamp
    by: Actor
    on: str
    digest: Digest
    line: int


Event = Raised | Answered | Critiqued | Approved


@dataclass(frozen=True)
class Thread:
    raised: Raised
    answers: tuple[Answered, ...]

    @property
    def open(self) -> bool:
        return not self.answers


@dataclass(frozen=True)
class Log:
    events: tuple[Event, ...]  # in time order

    @property
    @deal.ensure(lambda self, result: len(result) == sum(isinstance(e, Raised) for e in self.events))
    @deal.ensure(lambda self, result: all(a.id == t.raised.id for t in result for a in t.answers))
    def threads(self) -> tuple[Thread, ...]:
        answers: dict[ThreadId, list[Answered]] = {}
        for e in self.events:
            if isinstance(e, Answered) and e.id is not None:
                answers.setdefault(e.id, []).append(e)
        return tuple(Thread(e, tuple(answers.get(e.id, ()))) for e in self.events if isinstance(e, Raised))

    @deal.ensure(lambda self, id, result: result is None or result.raised.id == id)
    def thread(self, id: ThreadId) -> Thread | None:
        return next((t for t in self.threads if t.raised.id == id), None)

    @deal.ensure(lambda self, on, digest, result: all(c.on == on and c.digest == digest for c in result))
    def critiques(self, on: Subject, digest: Digest) -> tuple[Critiqued, ...]:
        return tuple(e for e in self.events if isinstance(e, Critiqued) and e.on == on and e.digest == digest)

    @deal.ensure(lambda self, on, digest, result: all(a.on == on and a.digest == digest for a in result))
    def approvals(self, on: Subject, digest: Digest) -> tuple[Approved, ...]:
        return tuple(e for e in self.events if isinstance(e, Approved) and e.on == on and e.digest == digest)

    @property
    @deal.ensure(lambda self, result: len(result) <= sum(isinstance(e, Answered) for e in self.events))
    def answered_questions(self) -> frozenset[tuple[RuleName, Subject, Digest]]:
        return frozenset((e.check, Subject(e.on), e.digest) for e in self.events
                         if isinstance(e, Answered) and e.check is not None and e.on is not None and e.digest)


@deal.post(lambda result: _DIGEST.fullmatch(result) is not None)
def thread_id(at: Timestamp, by: Actor, on: Subject, say: Say) -> ThreadId:
    return ThreadId(digest_of(at, by, on, say))


_FIELDS: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {  # event -> (required, optional)
    "raised": (frozenset({"at", "by", "event", "id", "on", "kind", "say"}), frozenset({"evidence"})),
    "answered": (frozenset({"at", "by", "event", "answer", "say"}),
                 frozenset({"id", "check", "on", "digest", "countermeasure"})),
    "critiqued": (frozenset({"at", "by", "event", "on", "digest"}), frozenset({"rubric"})),
    "approved": (frozenset({"at", "by", "event", "on", "digest"}), frozenset()),
}


def _bad(line: int, say: str) -> Finding:
    return finding(Result.BREAKS, LOG_RULE, LOG_FILE, Span(LOG_FILE, line, 1), say)


def _event(raw: object, line: int) -> tuple[Event | None, str | None]:
    if not isinstance(raw, dict):
        return None, "each line is one JSON object"
    kind = raw.get("event")
    if kind not in _FIELDS:
        return None, f"unknown event {kind!r}; known: {', '.join(_FIELDS)}"
    required, optional = _FIELDS[kind]
    missing, unknown = sorted(required - set(raw)), sorted(set(raw) - required - optional)
    if missing or unknown:
        return None, f"{kind}: " + "; ".join([*(f"needs {m}" for m in missing), *(f"has no field {u}" for u in unknown)])
    if not all(isinstance(v, str) for v in raw.values()):
        return None, f"{kind}: every value is text"
    if not _TIMESTAMP.fullmatch(raw["at"]):
        return None, f'{kind}: "at" is a UTC time to the second, such as 2026-11-04T14:12:05Z'
    if "digest" in raw and not _DIGEST.fullmatch(raw["digest"]):
        return None, f'{kind}: "digest" is 16 hex digits'
    at, by = Timestamp(raw["at"]), Actor(raw["by"])
    try:
        if kind == "raised":
            if raw["id"] != thread_id(at, by, raw["on"], raw["say"]):
                return None, "raised: the id does not match its at, by, on and say; was the line edited?"
            return Raised(at, by, ThreadId(raw["id"]), raw["on"], Kind(raw["kind"]), raw["say"],
                          raw.get("evidence"), line), None
        if kind == "answered":
            question = [raw.get(k) for k in ("check", "on", "digest")]
            if ("id" in raw) == any(question) or (any(question) and not all(question)):
                return None, 'answered: either "id" (a raised thread) or all of "check", "on" and "digest" (a question)'
            return Answered(at, by, Answer(raw["answer"]), raw["say"], raw.get("id"), raw.get("check"),
                            raw.get("on"), raw.get("digest"), raw.get("countermeasure"), line), None
        if kind == "critiqued":
            rubric = raw.get("rubric")
            if rubric is not None and not rubric.isdigit():
                return None, 'critiqued: "rubric" is a version number'
            return Critiqued(at, by, raw["on"], Digest(raw["digest"]), int(rubric) if rubric else None, line), None
        return Approved(at, by, raw["on"], Digest(raw["digest"]), line), None
    except ValueError as e:
        return None, f"{kind}: {e}"


@deal.ensure(lambda text, result: [(e.at, e.line) for e in result[0].events] == sorted(
    (e.at, e.line) for e in result[0].events))  # in time order, whatever order the lines are in
@deal.ensure(lambda text, result: all(p.result is Result.BREAKS and p.rule == LOG_RULE for p in result[1]))
def read_log(text: FileText | None) -> tuple[Log, tuple[Finding, ...]]:
    if not text:
        return Log(()), ()
    events: list[Event] = []
    problems: list[Finding] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(_bad(n, f"not JSON: {e.msg}"))
            continue
        event, problem = _event(raw, n)
        if problem:
            problems.append(_bad(n, problem))
        elif event is not None:
            events.append(event)
    events.sort(key=lambda e: (e.at, e.line))
    raised = {e.id for e in events if isinstance(e, Raised)}
    for e in events:
        if isinstance(e, Answered) and e.id is not None and e.id not in raised:
            problems.append(_bad(e.line, f'answered: no raised thread "{e.id}"'))
    return Log(tuple(events)), tuple(problems)


@deal.ensure(lambda report, log, result: set(result.findings) <= set(report.findings))
@deal.ensure(lambda report, log, result: all(f.result is Result.QUESTION
                                             for f in set(report.findings) - set(result.findings)))
def without_answered(report: Report, log: Log) -> Report:
    """The report, less the questions that have been answered for exactly their current content."""
    answered = log.answered_questions
    return Report(tuple(f for f in report.findings
                        if not (f.result is Result.QUESTION and (f.rule, f.about, f.digest) in answered)))


def line_of(fields: Mapping[str, str]) -> str:
    """One log line: canonical JSON, keys sorted, so the same event is always written the same way."""
    return json.dumps(dict(sorted(fields.items())), ensure_ascii=False, separators=(", ", ": "))


def _read_back(line: EventLine) -> tuple[Event, ...]:
    """The events one written line reads back as: what each event writer promises to be exactly what it was given."""
    return read_log(line)[0].events


@deal.pre(lambda at, by, kind, on, say, evidence: _TIMESTAMP.fullmatch(at) is not None)
@deal.ensure(lambda at, by, kind, on, say, evidence, result: _read_back(result) == (
    Raised(at, by, thread_id(at, by, on, say), on, kind, say, evidence or None, 1),))
def raised(at: Timestamp, by: Actor, kind: Kind, on: Subject, say: Say, evidence: Written | None) -> EventLine:
    fields = {"at": at, "by": by, "event": "raised", "id": thread_id(at, by, on, say), "kind": kind.value, "on": on,
              "say": say}
    return line_of({**fields, **({"evidence": evidence} if evidence else {})})


@deal.pre(lambda at, by, id, answer, say, countermeasure: _TIMESTAMP.fullmatch(at) is not None)
@deal.ensure(lambda at, by, id, answer, say, countermeasure, result: _read_back(result) == (
    Answered(at, by, answer, say, id, None, None, None, countermeasure or None, 1),))
def answered_thread(at: Timestamp, by: Actor, id: ThreadId, answer: Answer, say: Say,
                    countermeasure: Subject | None) -> EventLine:
    fields = {"at": at, "by": by, "event": "answered", "id": id, "answer": answer.value, "say": say}
    return line_of({**fields, **({"countermeasure": countermeasure} if countermeasure else {})})


@deal.pre(lambda at, by, question, answer, say: _TIMESTAMP.fullmatch(at) is not None
          and _DIGEST.fullmatch(question.digest) is not None)
@deal.ensure(lambda at, by, question, answer, say, result: _read_back(result) == (
    Answered(at, by, answer, say, None, question.rule, question.about, question.digest, None, 1),))
def answered_question(at: Timestamp, by: Actor, question: Finding, answer: Answer, say: Say) -> EventLine:
    return line_of({"at": at, "by": by, "event": "answered", "check": question.rule, "on": question.about,
                    "digest": question.digest, "answer": answer.value, "say": say})


@deal.pre(lambda at, by, on, digest, rubric: _TIMESTAMP.fullmatch(at) is not None
          and _DIGEST.fullmatch(digest) is not None and rubric >= 0)
@deal.ensure(lambda at, by, on, digest, rubric, result: _read_back(result) == (
    Critiqued(at, by, on, digest, rubric, 1),))
def critiqued(at: Timestamp, by: Actor, on: Subject, digest: Digest, rubric: Version) -> EventLine:
    return line_of({"at": at, "by": by, "event": "critiqued", "on": on, "digest": digest, "rubric": str(rubric)})


@deal.pre(lambda at, by, on, digest: _TIMESTAMP.fullmatch(at) is not None and _DIGEST.fullmatch(digest) is not None)
@deal.ensure(lambda at, by, on, digest, result: _read_back(result) == (Approved(at, by, on, digest, 1),))
def approved(at: Timestamp, by: Actor, on: Subject, digest: Digest) -> EventLine:
    return line_of({"at": at, "by": by, "event": "approved", "on": on, "digest": digest})


@deal.post(lambda result: all(t.open for t in result))
@deal.post(lambda result: [(t.raised.at, t.raised.line) for t in result] == sorted(
    ((t.raised.at, t.raised.line) for t in result), reverse=True))
def open_threads(log: Log) -> Iterable[Thread]:
    """Open threads, newest first."""
    return sorted((t for t in log.threads if t.open), key=lambda t: (t.raised.at, t.raised.line), reverse=True)

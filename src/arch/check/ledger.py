"""What critics, people and agents noticed, and every answer given to any finding.

Realizes arch.check.ledger. Two kinds of plain-text file under design/, both committed:

- `findings/<name>.md`: a finding a critic, a person or an agent noticed. Rules' findings are not stored,
  because every run finds them again.
- `responses/<name>.md`: an answer to one or more findings, always with a reason. A finding with an answer
  is still reported, but it no longer blocks. An escaped finding (noticed later than the station that made
  it) must also say what changed upstream, so it is caught there next time.

Answers are reviewed like any other change to the design: that is what keeps "declined" honest.
"""

from __future__ import annotations

import enum
import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import NewType

from arch.check.engine import (
    Finding,
    FindingIdentity,
    FindingKey,
    Kind,
    Report,
    RuleId,
    Source,
    Station,
    Subject,
)
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import DesignPath, Location, Text
from arch.model.schema import Kind as NodeKind

EntryName = NewType("EntryName", str)  # a ledger file's name, without folder or suffix
LedgerText = NewType("LedgerText", str)  # the contents of one ledger file
Digest = NewType("Digest", str)  # of a subject's content when the finding was noticed

FINDINGS_DIR = "findings"
RESPONSES_DIR = "responses"
_NAME = re.compile(r"[^a-z0-9]+")


class Answer(enum.Enum):
    FIXED = "fixed"  # the defect is gone
    ACCEPTED = "accepted"  # it is real, and it stays for now: existing debt, or coupling kept on purpose
    DECLINED = "declined"  # it is not a defect here, or the idea is not worth doing
    ANSWERED = "answered"  # the answer to a question


@dataclass(frozen=True)
class Response:
    name: EntryName
    answer: Answer
    by: Text  # who answered
    reason: Text
    findings: tuple[FindingIdentity, ...]
    countermeasure: Text | None = None  # for an escape: what changed upstream so the defect is caught there

    @property
    def path(self) -> DesignPath:
        return DesignPath(f"{RESPONSES_DIR}/{self.name}.md")


@dataclass(frozen=True)
class Noticed:
    """A stored finding, with the content digest of its subject when it was noticed."""

    finding: Finding
    name: EntryName
    digest: Digest | None = None

    @property
    def path(self) -> DesignPath:
        return DesignPath(f"{FINDINGS_DIR}/{self.name}.md")


@dataclass(frozen=True)
class Ledger:
    noticed: tuple[Noticed, ...] = ()
    responses: tuple[Response, ...] = ()
    problems: tuple[Finding, ...] = ()  # ledger files that could not be read

    @staticmethod
    def parse(files: Mapping[DesignPath, LedgerText]) -> Ledger:
        noticed, responses, problems = [], [], []
        for path in sorted(files):
            folder, _, file = path.partition("/")
            if folder not in (FINDINGS_DIR, RESPONSES_DIR) or not file.endswith(".md"):
                continue
            front = codec.frontmatter(path, files[path])
            raw, name, body = front.fields, EntryName(file.removesuffix(".md")), Text(front.body.strip())
            try:
                if raw is None:
                    raise ValueError(front.problem.message)
                if folder == FINDINGS_DIR:
                    noticed.append(_noticed(name, raw, body, path))
                else:
                    responses.append(_response(name, raw, body))
            except (ValueError, KeyError, TypeError) as e:
                problems.append(_problem(path, f"cannot be read: {e}"))
        return Ledger(tuple(noticed), tuple(responses), tuple(problems))

    def apply(self, report: Report, graph: Graph) -> Report:
        """The report with stored findings added, answered ones marked, and the ledger's own problems."""
        stored = [_placed(n, graph) for n in self.noticed]
        findings = [*report.findings, *stored]
        present = {f.identity for f in findings}
        by_identity = {f.identity: f for f in findings}
        answered: set[FindingIdentity] = set()
        extra = list(self.problems)
        for r in self.responses:
            if not r.reason.strip():
                extra.append(_problem(r.path, "gives no reason", key="reason"))
                continue
            gone = [i for i in r.findings if i not in present]
            answered.update(i for i in r.findings if i in present)
            if gone:
                extra.append(_ledger_finding("L001", r.path, "gone", Kind.IDEA,
                                             f"answers {len(gone)} finding{'s' * (len(gone) != 1)} that no longer occur",
                                             "remove those entries, or the file, so they cannot come back unnoticed"))
            if r.answer in (Answer.FIXED, Answer.ACCEPTED) and not r.countermeasure:
                for i in r.findings:
                    if i in by_identity and by_identity[i].escaped:
                        f = by_identity[i]
                        extra.append(_ledger_finding(
                            "L002", r.path, f"countermeasure:{'|'.join(i)}", Kind.QUESTION,
                            f"{f.rule} on {f.subject} was made at {f.station.value} but noticed at {f.found_at.value}, "
                            "and the answer names no countermeasure",
                            "say what changes upstream (a lint, a critic question, a method step, a model change) so "
                            "this is caught where it is made", station=Station.REVIEW))
        return Report(tuple(sorted([*findings, *extra], key=lambda f: (f.subject, f.rule, f.key))), graph,
                      report.answered | frozenset(answered))

    def answer_for(self, identity: FindingIdentity) -> Response | None:
        return next((r for r in self.responses if identity in r.findings), None)


def digest_of(graph: Graph, subject: Subject) -> Digest | None:
    """The content of a design node, so a finding can tell when its subject has changed since."""
    for kind, nodes in ((NodeKind.COMPONENT, graph.design.components), (NodeKind.NEED, graph.design.needs),
                        (NodeKind.CONSTRAINT, graph.design.constraints)):
        if subject in nodes:
            text = graph.design.sources.get(codec.path_of(kind, subject))
            return Digest(hashlib.sha256(text.encode()).hexdigest()[:12]) if text is not None else None
    return None


def name_for(text: Text) -> EntryName:
    """A file name from a title: lower case words joined by hyphens."""
    return EntryName(_NAME.sub("-", text.lower()).strip("-")[:60] or "entry")


def render_noticed(n: Noticed) -> LedgerText:
    f = n.finding
    fields = [("kind", f.kind.value), ("station", f.station.value), ("found_at", f.found_at.value if f.found_at else None),
              ("source", f.source.value), ("by", f.rule), ("subject", f.subject), ("digest", n.digest),
              ("evidence", f.evidence), ("hint", f.hint or None)]
    return _render(fields, f.message)


def render_response(r: Response) -> LedgerText:
    head = [("answer", r.answer.value), ("by", r.by), ("countermeasure", r.countermeasure)]
    lines = ["---", *(f"{k}: {codec.scalar(Text(v))}" for k, v in head if v), "findings:"]
    lines += [f"  - {{rule: {codec.scalar(Text(a))}, subject: {codec.scalar(Text(b))}, key: {codec.scalar(Text(c))}}}"
              for a, b, c in sorted(r.findings)]
    return LedgerText("\n".join([*lines, "---", r.reason.strip(), ""]))


def accepting(findings: Iterable[Finding], name: EntryName, by: Text, reason: Text) -> Response:
    """One answer accepting many findings at once, such as the errors that existed when arch was adopted."""
    return Response(name, Answer.ACCEPTED, by, reason, tuple(sorted({f.identity for f in findings})))


def _render(fields, body: str) -> LedgerText:
    lines = ["---", *(f"{k}: {codec.scalar(Text(v))}" for k, v in fields if v), "---", body.strip(), ""]
    return LedgerText("\n".join(lines))


def _noticed(name: EntryName, raw: dict, body: Text, path: DesignPath) -> Noticed:
    found_at = raw.get("found_at")
    finding = Finding(
        Subject(str(raw["subject"])), RuleId(str(raw["by"])), FindingKey(name), Kind(raw["kind"]), body,
        Text(str(raw.get("hint") or "")), Location(path), Station(raw["station"]), Source(raw["source"]),
        Text(str(raw["evidence"])) if raw.get("evidence") else None, Station(found_at) if found_at else None)
    if finding.source is Source.RULE:
        raise ValueError("rules' findings are found again on every run and are not stored")
    return Noticed(finding, name, Digest(str(raw["digest"])) if raw.get("digest") else None)


def _response(name: EntryName, raw: dict, body: Text) -> Response:
    entries = raw.get("findings") or []
    if not isinstance(entries, list):
        raise ValueError("findings must be a list")
    identities = tuple((RuleId(str(e["rule"])), Subject(str(e["subject"])), FindingKey(str(e["key"]))) for e in entries)
    countermeasure = raw.get("countermeasure")
    return Response(name, Answer(raw["answer"]), Text(str(raw.get("by") or "")), body, identities,
                    Text(str(countermeasure)) if countermeasure else None)


def _placed(n: Noticed, graph: Graph) -> Finding:
    f = n.finding
    now = digest_of(graph, f.subject)
    if n.digest is not None and now is not None and now != n.digest:
        f = replace(f, message=Text(f"{f.message} (its subject has changed since this was noticed)"))
    return f


def _ledger_finding(rule: str, path: DesignPath, key: str, kind: Kind, message: str, hint: str,
                    station: Station = Station.FORM) -> Finding:
    return Finding(Subject(path), RuleId(rule), FindingKey(key), kind, Text(message), Text(hint), Location(path),
                   station)


def _problem(path: DesignPath, message: str, key: str = "parse") -> Finding:
    return Finding(Subject(path), RuleId("L000"), FindingKey(key), Kind.DEFECT, Text(message),
                   Text("fix the file so arch can read it"), Location(path), Station.FORM)


__all__ = ["Answer", "Digest", "EntryName", "Ledger", "LedgerText", "Noticed", "Response", "accepting", "digest_of", "name_for",
           "render_noticed", "render_response"]

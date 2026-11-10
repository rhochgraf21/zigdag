"""Critique (DESIGN2 §10): a request a fresh critic answers from that file alone, and checking its answer.

The critic sees each entry, what it serves, and the rubric questions still to ask; never the author's reasoning.
Its findings must quote the entry's own words, so a critic cannot judge what is not written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.core.record.entries import Entry, EntryKind
from zigdag.core.record.model import Record
from zigdag.core.rubric import RUBRIC_VERSION, still_to_ask
from zigdag.core.log import Kind, Log
from zigdag.core.names import FrName, parent
from zigdag.core.findings import Subject
from zigdag.core.measures import Count
from zigdag.core.texts import FileText, Say

INSTRUCTIONS = (
    "You are an independent critic. Judge each entry only by what is written here. For every question, either "
    "find nothing (leave it out) or add a finding: kind is defect (it is wrong), question (it is unclear) or idea "
    "(a better way, saying what it removes and what it costs). 'evidence' must be words copied exactly from the "
    "entry. Answer with JSON: {\"entries\": [{\"name\", \"digest\", \"findings\": [{\"question\", \"kind\", "
    "\"say\", \"evidence\"}]}]}. Include every entry you judged, even with no findings, and nothing else."
)


def _function(record: Record, name: FrName) -> str | None:
    fr = record.frs.get(name)
    return next((s.sentence.text for s in fr.statements), None) if fr else None


def _context(record: Record, entry: Entry) -> dict[str, object]:
    out: dict[str, object] = {}
    if entry.scope and entry.scope in record.frs:
        name = FrName(entry.scope)
        chain = []
        n: FrName | None = name
        while n is not None:
            chain.append(n)
            n = parent(n)
        served = [str(r.value) for c in chain if c in record.frs for r in record.frs[c].serves]
        outcomes = {str(k): o for k, o in record.outcomes.items()}
        out["serves"] = [outcomes[o].sentence.text for o in served if o in outcomes]
        p = parent(name)
        if p is not None and entry.kind is EntryKind.FR:
            out["parent function"] = _function(record, p)
            out["children"] = [n for n in record.frs if parent(n) == name]
    return out


def _asked_under(log: Log, entry: Entry) -> int | None:
    versions = [c.rubric or 0 for c in log.critiques(entry.name, entry.digest)]
    return max(versions) if versions else None


@deal.ensure(lambda record, log, chosen, result: result[1] == len(json.loads(result[0])["entries"]) <= len(chosen))
def request(record: Record, log: Log, chosen: list[Entry]) -> tuple[FileText, Count]:
    """The request as JSON text, and how many entries in it still have questions to answer."""
    items = []
    for e in chosen:
        questions = still_to_ask(e.kind, _asked_under(log, e))
        if not questions:
            continue
        items.append({"name": e.name, "kind": e.kind.value, "digest": e.digest, "content": dict(e.fields),
                      "context": _context(record, e), "questions": [{"id": q.id, "ask": q.ask} for q in questions]})
    return json.dumps({"rubric": RUBRIC_VERSION, "instructions": INSTRUCTIONS, "entries": items}, indent=2,
                      ensure_ascii=False), len(items)


@dataclass(frozen=True)
class CritiqueFinding:
    question: str
    kind: Kind
    say: str
    evidence: str


@dataclass(frozen=True)
class Judged:
    entry: Entry
    findings: tuple[CritiqueFinding, ...]


def _texts(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [t for v in value.values() for t in _texts(v)] + [str(k) for k in value]
    if isinstance(value, list | tuple):
        return [t for v in value for t in _texts(v)]
    return []


@deal.ensure(lambda current, text, result: all(current.get(j.entry.name) == j.entry for j in result[0]))
@deal.ensure(lambda current, text, result: all(f.evidence for j in result[0] for f in j.findings))
def read_answer(current: Mapping[Subject, Entry], text: FileText) -> tuple[list[Judged], list[Say]]:
    """The entries the critic judged at their current content, and why anything else was refused."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"the answer is not JSON: {e.msg}"]
    judged, problems = [], []
    for item in raw.get("entries", []) if isinstance(raw, dict) else []:
        name, digest = item.get("name"), item.get("digest")
        entry = current.get(name)
        if entry is None:
            problems.append(f"{name}: no such entry")
            continue
        if digest != entry.digest:
            problems.append(f"{name}: changed since the request was made; ask again")
            continue
        asked = {q.id for q in still_to_ask(entry.kind, None)}
        words = " ".join(_texts(entry.fields))
        findings = []
        for f in item.get("findings", []):
            question, kind, say, evidence = (f.get(k) for k in ("question", "kind", "say", "evidence"))
            if question not in asked:
                problems.append(f"{name}: no question {question!r} for a {entry.kind.value}")
            elif kind not in {k.value for k in Kind} or not say:
                problems.append(f"{name}: a finding needs a kind (defect, question, idea) and what it says")
            elif not evidence or evidence not in words:
                problems.append(f"{name}: the evidence {evidence!r} is not words from the entry")
            else:
                findings.append(CritiqueFinding(question, Kind(kind), say, evidence))
        judged.append(Judged(entry, tuple(findings)))
    return judged, problems

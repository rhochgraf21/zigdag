"""Reviewing a change (DESIGN2 §9): what it does to the record, entry by entry and in domain order, and what it
broke. A reviewer reads intent first: customer, functional, physical, process; prose is never shown as raw YAML.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.core.record.entries import Entry, entries, plain
from zigdag.core.record.model import Domain, Record
from zigdag.core.findings import Finding, Report, Result
from zigdag.core.log import Log
from zigdag.core.log import Actor
from zigdag.core.names import Revision, RuleId
from zigdag.core.texts import Say, SentenceText, Shown


class ChangeKind(enum.Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    RENAMED = "renamed"


_MARK = {ChangeKind.ADDED: "+", ChangeKind.REMOVED: "-", ChangeKind.CHANGED: "~", ChangeKind.RENAMED: ">"}


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    entry: Entry  # the entry as it is now; for a removal, as it was
    before: Entry | None
    details: tuple[Say, ...]

    @property
    @deal.ensure(lambda self, result: result is self.entry.domain)
    def domain(self) -> Domain:
        return self.entry.domain


def _show(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(map(str, value)) + "]" if value else "[]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_show(v)}" for k, v in value.items()) + "}"
    return "(none)" if value is None or value == "" else str(value)


def _details(before: Mapping[str, object], after: Mapping[str, object], sentences: tuple[str | None, str | None]) -> list[str]:
    out = []
    old_rule, new_rule = sentences
    if old_rule != new_rule and (old_rule or new_rule):
        out.append(f'rule: "{old_rule or "(none)"}" → "{new_rule or "(none)"}"')
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        if a == b or (key in _SHOWN_BY_RULE and (old_rule or new_rule)):
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a:
                    out.append(f"{key} {k} added: {_show(b[k])}")
                elif k not in b:
                    out.append(f"{key} {k} removed: {_show(a[k])}")
                elif a[k] != b[k]:
                    out.append(f'{key} {k}: "{_show(a[k])}" → "{_show(b[k])}"')
        elif isinstance(a, list) and isinstance(b, list):
            added, removed = [x for x in b if x not in a], [x for x in a if x not in b]
            out += [f"{key} + {x}" for x in added] + [f"{key} - {x}" for x in removed]
        else:
            out.append(f'{key}: "{_show(a)}" → "{_show(b)}"')
    return out


_SHOWN_BY_RULE = frozenset({"check", "with"})  # fields a rendered rule sentence already says


def _said(fields: Mapping[str, object], rule: str | None) -> list[str]:
    """What a new entry says: its rule as a sentence, and every field that holds something."""
    out = [f'rule: "{rule}"'] if rule else []
    for key, value in fields.items():
        if value in (None, "", [], {}) or (rule and key in _SHOWN_BY_RULE):
            continue
        if isinstance(value, dict):
            out += [f"{key} {k}: {_show(v)}" for k, v in value.items()]
        else:
            out.append(f"{key}: {_show(value)}")
    return out


@deal.ensure(lambda before, after, *sentences, result: [list(Domain).index(c.domain) for c in result] == sorted(
    list(Domain).index(c.domain) for c in result))  # in domain order: what a reviewer reads first comes first
@deal.ensure(lambda before, after, *sentences, result: all((c.before is None) == (c.kind is ChangeKind.ADDED)
                                                           for c in result))
def diff(before: Record, after: Record, sentences_before: Mapping[RuleId, SentenceText] | None = None,
         sentences_after: Mapping[RuleId, SentenceText] | None = None) -> list[Change]:
    """What changed between two records, with renames found where an entry left one name and came back under another
    with the same content."""
    old, new = entries(before), entries(after)
    sb, sa = sentences_before or {}, sentences_after or {}
    changes: list[Change] = []
    removed = [old[n] for n in sorted(set(old) - set(new))]
    added = [new[n] for n in sorted(set(new) - set(old))]
    renamed: set[str] = set()
    for a in added:
        match = next((r for r in removed if r.name not in renamed and r.kind is a.kind and r.content == a.content
                      and r.kind.value != "physical entry"), None)
        if match is not None:
            renamed.add(match.name)
            changes.append(Change(ChangeKind.RENAMED, a, match, (f"from {match.name}",)))
        else:
            changes.append(Change(ChangeKind.ADDED, a, None, tuple(_said(a.fields, sa.get(a.name)))))
    for r in removed:
        if r.name not in renamed:
            changes.append(Change(ChangeKind.REMOVED, r, r, ()))
    for name in sorted(set(old) & set(new)):
        if old[name].digest != new[name].digest:
            details = _details(old[name].fields, new[name].fields, (sb.get(name), sa.get(name)))
            changes.append(Change(ChangeKind.CHANGED, new[name], old[name], tuple(details)))
    order = list(Domain)
    return sorted(changes, key=lambda c: (order.index(c.domain), c.entry.name))


@deal.ensure(lambda before, after, result: all(f in after.findings for f in result))
@deal.ensure(lambda before, after, result: not any((f.result, f.rule, f.about, f.say) == (b.result, b.rule, b.about,
                                                                                         b.say)
                                                   for f in result for b in before.findings))
def new_findings(before: Report, after: Report) -> list[Finding]:
    """Findings the change brought: in the report after it, and not before."""
    seen = {(f.result, f.rule, f.about, f.say) for f in before.findings}
    return [f for f in after.findings if (f.result, f.rule, f.about, f.say) not in seen]


def _status(change: Change, log: Log, people: tuple[str, ...]) -> str:
    if change.kind is ChangeKind.REMOVED:
        return ""
    e = change.entry
    critiqued = bool(log.critiques(e.name, e.digest))
    approvals = log.approvals(e.name, e.digest)
    by_people = [a.by for a in approvals if a.by in people]
    parts = ["critiqued" if critiqued else "not critiqued",
             f"approved by {', '.join(sorted(set(by_people)))}" if by_people else (
                 "approved by an agent only" if approvals else "not approved")]
    return "  [" + "; ".join(parts) + "]"


@deal.pre(lambda base, changes, log, people, gates, brought: all(plain(c.entry.fields) for c in changes))
@deal.ensure(lambda base, changes, log, people, gates, brought, result: all(c.entry.name in result for c in changes))
@deal.ensure(lambda base, changes, log, people, gates, brought, result: (bool(changes) or bool(brought))
             != result.startswith("no change"))
def render(base: Revision, changes: list[Change], log: Log, people: tuple[Actor, ...], gates: list[Finding],
           brought: list[Finding]) -> Shown:
    if not changes and not brought:
        return f"no change to the record or its findings since {base}"
    lines = [f"review against {base}: {len(changes)} entries changed"]
    for domain in Domain:
        mine = [c for c in changes if c.domain is domain]
        if not mine:
            continue
        lines += ["", domain.value]
        for c in mine:
            lines.append(f"  {_MARK[c.kind]} {c.entry.kind.value} {c.entry.name}{_status(c, log, people)}")
            lines += [f"      {d}" for d in c.details]
    if gates:
        lines += ["", "gates", *(f"  {f.rule}: {f.about}: {f.say}" for f in gates)]
    if brought:
        lines += ["", "what the change brought"]
        for result in (Result.BREAKS, Result.QUESTION, Result.OUT_OF_DATE, Result.TODO):
            lines += [f"  {result.value}: {f.span or '-'}  {f.rule}  {f.about}: {f.say}"
                      for f in brought if f.result is result]
    return "\n".join(lines)

"""Why each code change was made, and what the names in it mean. Realizes arch.review.explain.

A reason is traced, never guessed. It comes from a criterion the change added or reworded, from a test of
such a criterion, from an interface that changed and the calls that had to follow it, or from a component
the change adds. When none of these explains a change, the change says so.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from arch.model.ids import ComponentId, Text, split_criterion
from arch.realize.facts import (
    Column,
    Definition,
    DiffLineKind,
    Facts,
    FileDiff,
    FileShape,
    Hunk,
    LineNo,
    NameKind,
    PortChange,
    PortChangeType,
    Role,
    SourcePath,
    needs_description,
)

_ALIAS_DEPTH = 8


class Why(enum.Enum):
    """The kinds of reason, strongest first."""

    TESTS = "tests"  # a test of a criterion this change added or reworded
    REALIZES = "realizes"  # code linked to such a criterion
    EXERCISED = "exercised"  # a test of such a criterion calls this code
    FOLLOWS = "follows"  # updates calls to an interface that changed in this change
    NEW_COMPONENT = "new component"  # part of a component this change adds
    IMPORTS = "imports"  # it only changes imports or the list of exported names; the code that uses them says why
    NONE = "none"  # nothing traced


class Standing(enum.Enum):
    """Whether a change stands on its own or only follows a change elsewhere."""

    OWN = "own"
    FOLLOW_ON = "follow-on"  # every changed line, blank ones aside, is in a call to an interface that changed


class Touch(enum.Enum):
    """How the change touched a criterion."""

    ADDED = "added"
    REWORDED = "reworded"


@dataclass(frozen=True)
class Reason:
    why: Why
    refs: tuple[Text, ...] = ()  # criterion ids, dotted interface names, or a component id
    detail: Text | None = None  # how the criteria were touched, or how the interface changed
    via: Text | None = None  # for a test that reaches the code through other calls: what the test calls


class Doubt(enum.Enum):
    """What a reviewer should check about a definition's description."""

    STALE = "stale"  # its signature changed and its description did not
    UNDESCRIBED = "undescribed"  # a new or changed interface name that its name and type do not explain


@dataclass(frozen=True)
class Question:
    """Something a reviewer should check about one definition's description."""

    doubt: Doubt
    name: Text  # the definition, qualified within its unit


@dataclass(frozen=True)
class NameTip:
    """What a name on a line refers to, by its position in the line."""

    start: Column
    end: Column
    tip: Text


@dataclass(frozen=True)
class Enclosing:
    """The definition a change sits in."""

    name: Text
    signature: Text
    summary: Text | None


@dataclass(frozen=True)
class HunkView:
    hunk: Hunk
    enclosing: Enclosing | None
    reasons: tuple[Reason, ...]  # empty only for changes that need no reason (mechanical ones)
    proves: tuple[Text, ...]  # every criterion linked to the definitions it touches
    follows: tuple[Text, ...]  # interfaces (dotted) whose calls it updates
    standing: Standing
    names: tuple[tuple[NameTip, ...], ...]  # per line of the hunk
    questions: tuple[Question, ...] = ()  # about the descriptions of the definitions it changes

    @property
    def only_follows(self) -> bool:
        return self.standing is Standing.FOLLOW_ON

    @property
    def unexplained(self) -> bool:
        return any(r.why is Why.NONE for r in self.reasons)


@dataclass(frozen=True)
class Trace:
    """What the change touched, as reasons can cite it."""

    facts_before: Facts
    facts_after: Facts
    criteria: Mapping[Text, Touch]  # criteria this change added or reworded
    ports: tuple[PortChange, ...]
    new_components: frozenset[ComponentId]
    component_of: Mapping[SourcePath, ComponentId]  # each source file's component


class Side:
    """One revision's facts, indexed for looking up what is at a line."""

    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self.definitions: dict[str, list[Definition]] = {}
        for d in facts.definitions:
            self.definitions.setdefault(d.location.path, []).append(d)
        self.by_dotted = {f"{d.unit}.{d.name}": d for d in facts.definitions}
        self.calls: dict[str, list] = {}
        for c in facts.calls:
            self.calls.setdefault(c.location.path, []).append(c)
        self.references: dict[tuple[str, int], list] = {}
        for r in facts.references:
            self.references.setdefault((r.location.path, r.location.line), []).append(r)
        self.aliases = {f"{a.unit}.{a.name}": a.target for a in facts.aliases}
        self.imports: dict[str, list] = {}
        for i in facts.imports:
            self.imports.setdefault(i.location.path, []).append(i)

    def resolve(self, dotted: str) -> str:
        """Follow re-exports to where a name is defined."""
        for _ in range(_ALIAS_DEPTH):
            if dotted in self.by_dotted or dotted not in self.aliases:
                break
            dotted = self.aliases[dotted]
        return dotted

    def innermost(self, path: str, line: LineNo) -> Definition | None:
        around = [d for d in self.definitions.get(path, ()) if d.location.line <= line <= d.end_line]
        return min(around, key=lambda d: d.end_line - d.location.line, default=None)

    def calls_at(self, path: str, line: LineNo) -> list:
        return [c for c in self.calls.get(path, ()) if c.spans(line)]

    def imports_or_exports(self, path: str, line: LineNo) -> bool:
        if any(i.location.line <= line <= (i.end_line or i.location.line) for i in self.imports.get(path, ())):
            return True
        d = self.innermost(path, line)
        return d is not None and d.kind == "exports"


class Tracer:
    """Explains the hunks of a change. Build it once per review; indexing the facts is the costly part."""

    def __init__(self, trace: Trace) -> None:
        self.trace = trace
        self.before, self.after = Side(trace.facts_before), Side(trace.facts_after)
        self.followed = {p.dotted: p for p in trace.ports
                         if p.reexport_of is None and p.type in (PortChangeType.SIGNATURE, PortChangeType.REMOVED)}
        roles = {u.name: u.role for u in (*trace.facts_before.units, *trace.facts_after.units)}
        self.links: dict[tuple[str, str], list[Text]] = {}
        for link in trace.facts_after.links:
            self.links.setdefault((link.unit, link.symbol), []).append(link.target)
        self.is_test = {k: roles.get(k[0]) is Role.TEST for k in self.links}
        self.exercised = self._exercised(trace)
        self.undescribed = needs_description(trace.facts_after)

    def hunks(self, diff: FileDiff) -> tuple[HunkView, ...]:
        """Each hunk explained. A new file is cut at its top-level definitions, so each gets its own reason."""
        old_path = diff.old_path or diff.path
        pieces = self._split(diff) if diff.shape is FileShape.ADDED else diff.hunks
        return tuple(self._hunk(h, diff.path, old_path) for h in pieces)

    def _split(self, diff: FileDiff) -> tuple[Hunk, ...]:
        starts = sorted({d.location.line for d in self.after.definitions.get(diff.path, ()) if "." not in d.name})
        out: list[Hunk] = []
        for h in diff.hunks:
            cuts = [i for i, line in enumerate(h.lines) if line.new_line in starts and i > 0]
            for a, b in zip([0, *cuts], [*cuts, len(h.lines)]):
                lines = h.lines[a:b]
                out.append(Hunk(h.old_start, lines[0].new_line or h.new_start, h.header, lines))
        return tuple(out)

    def plain(self, diff: FileDiff) -> tuple[HunkView, ...]:
        """Hunks shown as they are, with names explained but no reasons: for mechanical changes."""
        old_path = diff.old_path or diff.path
        return tuple(HunkView(h, None, (), (), (), Standing.OWN, self._names(h, diff.path, old_path)) for h in diff.hunks)

    def _hunk(self, h: Hunk, path: str, old_path: str) -> HunkView:
        changed = [line for line in h.lines if line.kind is not DiffLineKind.CONTEXT]
        touched: list[Definition] = []
        follows: list[Text] = []
        covered = housekeeping = True
        for line in changed:
            side, at, n = ((self.after, path, line.new_line) if line.kind is DiffLineKind.ADDED
                           else (self.before, old_path, line.old_line))
            if n is None:
                continue
            if (d := side.innermost(at, n)) is not None and d not in touched:
                touched.append(d)
            hits = [Text(side.resolve(c.callee)) for c in side.calls_at(at, n)]
            hits = [x for x in hits if x in self.followed]
            follows += [x for x in hits if x not in follows]
            covered &= bool(hits) or not line.text.strip()
            housekeeping &= side.imports_or_exports(at, n) or not line.text.strip()
        first_added = next((line.new_line for line in changed if line.kind is DiffLineKind.ADDED and line.new_line), None)
        enclosing = (self.after.innermost(path, first_added) if first_added else None) or (touched[0] if touched else None)
        proves = tuple(dict.fromkeys(t for d in touched for t in self.links.get((d.unit, d.name), ())))
        reasons = (Reason(Why.IMPORTS),) if changed and housekeeping else self._reasons(touched, follows, path)
        return HunkView(h, Enclosing(Text(enclosing.name), enclosing.signature, enclosing.summary) if enclosing else None,
                        reasons, proves, tuple(follows),
                        Standing.FOLLOW_ON if changed and follows and covered else Standing.OWN, self._names(h, path, old_path),
                        self._questions(touched))

    def _questions(self, touched: list[Definition]) -> tuple[Question, ...]:
        out: list[Question] = []
        for d in touched:
            now = self.after.by_dotted.get(f"{d.unit}.{d.name}")
            was = self.before.by_dotted.get(f"{d.unit}.{d.name}")
            if now is None:
                continue  # removed
            changed = was is None or was.signature != now.signature
            if was is not None and changed and was.summary is not None and was.summary == now.summary:
                out.append(Question(Doubt.STALE, Text(now.name)))
            elif changed and (now.unit, now.name) in self.undescribed:
                out.append(Question(Doubt.UNDESCRIBED, Text(now.name)))
        return tuple(dict.fromkeys(out))

    def _reasons(self, touched: list[Definition], follows: list[Text], path: str) -> tuple[Reason, ...]:
        criteria = self.trace.criteria
        out: list[Reason] = []
        for why, test in ((Why.TESTS, True), (Why.REALIZES, False)):
            linked = [t for d in touched for t in self.links.get((d.unit, d.name), ())
                      if t in criteria and self.is_test.get((d.unit, d.name)) is test]
            if linked:
                out.append(Reason(why, tuple(dict.fromkeys(linked)), _touch(criteria[t] for t in linked)))
        cited = {t for r in out for t in r.refs}
        reached = [(t, via) for d in touched for key in self._entries(d) for t, via in sorted(self.exercised.get(key, {}).items())
                   if t not in cited]
        if reached:
            refs = tuple(dict.fromkeys(t for t, _ in reached))
            direct = any(via is None for _, via in reached)
            out.append(Reason(Why.EXERCISED, refs, _touch(criteria[t] for t in refs),
                              None if direct else next(via for _, via in reached if via is not None)))
        if follows:
            kinds = {self.followed[f].type for f in follows}
            detail = Text("removed") if kinds == {PortChangeType.REMOVED} else Text("changed")
            out.append(Reason(Why.FOLLOWS, tuple(follows), detail))
        if (cid := self.trace.component_of.get(path)) is not None and cid in self.trace.new_components:
            out.append(Reason(Why.NEW_COMPONENT, (Text(cid),)))
        return tuple(out) or (Reason(Why.NONE),)

    def _entries(self, d: Definition) -> list[str]:
        """The dotted names a call reaches this definition by: itself, and for a field, its class."""
        own = f"{d.unit}.{d.name}"
        return [own, own.rpartition(".")[0]] if d.kind == "field" else [own]

    def _exercised(self, trace: Trace) -> dict[str, dict[Text, Text | None]]:
        """definition -> {criterion: what the test calls to reach it, or None when the test calls it directly}.

        From each test of a criterion this change added or reworded, follow project calls as far as they go,
        but credit only definitions of that criterion's own component: a test of a component's criterion speaks
        for that component's code. It does not speak for what it happens to call, nor for the parts of a parent."""
        side = self.after
        calls: dict[str, list[str]] = {}
        for c in trace.facts_after.calls:
            calls.setdefault(f"{c.unit}.{c.symbol}", []).append(side.resolve(c.callee))
        component_of_def = {k: trace.component_of.get(d.location.path) for k, d in side.by_dotted.items()}
        out: dict[str, dict[Text, Text | None]] = {}
        for (unit, symbol), targets in self.links.items():
            if not self.is_test.get((unit, symbol)):
                continue
            for criterion in (t for t in targets if t in trace.criteria):
                owner = split_criterion(criterion)[0]
                start = calls.get(f"{unit}.{symbol}", [])
                seen: dict[str, str | None] = {}
                frontier = [(callee, None) for callee in start]
                while frontier:
                    name, via = frontier.pop()
                    for target in (name, f"{name}.__init__", f"{name}.__post_init__"):
                        if target not in side.by_dotted or target in seen:
                            continue
                        seen[target] = via
                        entry = via or side.by_dotted[target].name
                        frontier += [(callee, entry) for callee in calls.get(target, [])]
                for target, via in seen.items():
                    where = component_of_def.get(target)
                    if where == owner:
                        out.setdefault(target, {}).setdefault(criterion, Text(via) if via else None)
        return out

    def _names(self, h: Hunk, path: str, old_path: str) -> tuple[tuple[NameTip, ...], ...]:
        out = []
        for line in h.lines:
            side, at, n = (self.before, old_path, line.old_line) if line.kind is DiffLineKind.REMOVED else (self.after, path, line.new_line)
            tips = [] if n is None else [t for r in side.references.get((at, n), ()) if (t := self._tip(side, r)) is not None]
            out.append(tuple(sorted(set(tips), key=lambda t: (t.start, -t.end))))
        return tuple(out)

    def _tip(self, side: Side, ref) -> NameTip | None:
        d = side.by_dotted.get(side.resolve(ref.target)) if ref.target else None
        if ref.kind is NameKind.LOCAL:
            made_by = f"\n{d.signature}" + (f"\n{d.summary}" if d.summary else "") if d is not None else ""
            return NameTip(ref.column, ref.end_column, Text(f"Set on line {ref.bound_at}: {ref.binding}{made_by}"))
        if d is None:
            return None
        about = f"\n{d.summary}" if d.summary else ""
        if ref.kind is NameKind.VALUE:
            if d.kind != "class":
                return None
            text = f"{ref.text} is a {d.name}.{about}"
        else:
            text = f"{d.signature}{about}"
        return NameTip(ref.column, ref.end_column, Text(text))


def _touch(touches: Iterable[Touch]) -> Text:
    kinds = set(touches)
    return Text("added" if kinds == {Touch.ADDED} else "reworded" if kinds == {Touch.REWORDED} else "added or reworded")


__all__ = ["Doubt", "Enclosing", "HunkView", "NameTip", "Question", "Reason", "Standing", "Touch", "Trace", "Tracer", "Why"]

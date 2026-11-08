"""Strict YAML (DESIGN2 §7.2): every value is text; no anchors, aliases or tags; duplicate keys are errors.

Hides the YAML library. The rest of zigdag sees only this module's nodes, with their spans and reasons.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError
from ruamel.yaml.events import AliasEvent, CollectionStartEvent, ScalarEvent
from ruamel.yaml.nodes import ScalarNode
from ruamel.yaml.resolver import VersionedResolver

from zigdag.core.record.comments import Comments, scan
from zigdag.core.findings import Finding, RecordPath, Result, Span, finding
from zigdag.core.names import Key
from zigdag.core.texts import FileText, Say, Written

YAML_RULE = "yaml"


class _TextResolver(VersionedResolver):
    """Resolves every plain scalar to text, so `no` stays "no" and `3` stays "3"."""

    def resolve(self, kind, value, implicit):  # noqa: ANN001, ANN201 (ruamel's signature)
        if kind is ScalarNode and implicit[0]:
            return self.DEFAULT_SCALAR_TAG
        return super().resolve(kind, value, implicit)


@dataclass(frozen=True)
class Text:
    text: Written
    span: Span
    reason: Say | None  # the comment beside it, if any


@dataclass(frozen=True)
class Seq:
    items: tuple[Node, ...]
    span: Span


@dataclass(frozen=True)
class Entry:
    key: Key
    key_span: Span
    value: Node
    reason: Say | None  # the comment beside the key, or directly above it


@dataclass(frozen=True)
class Map:
    entries: tuple[Entry, ...]
    span: Span

    def get(self, key: Key) -> Entry | None:
        return next((e for e in self.entries if e.key == key), None)

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries)


Node = Text | Seq | Map


class _PlainYAML(YAML):
    """ruamel's YAML without plug-ins: looking for them would search ruamel's own folder on disk each time."""

    def official_plug_ins(self) -> list:
        return []


def _yaml() -> YAML:
    y = _PlainYAML(typ="rt")
    y.Resolver = _TextResolver
    y.allow_duplicate_keys = False
    return y


def _convert(value: object, path: RecordPath, line: int, column: int, comments: Comments) -> Node:
    if isinstance(value, CommentedMap):
        entries = []
        for key in value:
            kl, kc = value.lc.key(key)
            vl, vc = value.lc.value(key)
            child = _convert(value[key], path, vl + 1, vc + 1, comments)
            reason = comments.beside.get(kl) or comments.above(kl)
            entries.append(Entry(str(key), Span(path, kl + 1, kc + 1), child, reason))
        return Map(tuple(entries), Span(path, line, column))
    if isinstance(value, CommentedSeq):
        items = []
        block = not value.fa.flow_style()
        for i, item in enumerate(value):
            il, ic = value.lc.item(i)
            child = _convert(item, path, il + 1, ic + 1, comments)
            if isinstance(child, Text) and block:  # an item on its own line can carry a reason
                child = Text(child.text, child.span, comments.beside.get(il) or comments.above(il))
            items.append(child)
        return Seq(tuple(items), Span(path, line, column))
    return Text("" if value is None else str(value), Span(path, line, column), None)


def read_tree(path: RecordPath, text: FileText) -> tuple[Node | None, tuple[Finding, ...]]:
    """The file's node tree, or None with the findings that explain why it could not be read."""
    problems: list[Finding] = []
    y = _yaml()
    try:
        for event in y.parse(text):
            at = Span(path, event.start_mark.line + 1, event.start_mark.column + 1)
            if isinstance(event, AliasEvent):
                problems.append(finding(Result.BREAKS, YAML_RULE, path, at, "no aliases: write the value out"))
            elif isinstance(event, ScalarEvent | CollectionStartEvent):
                if event.anchor:
                    problems.append(finding(Result.BREAKS, YAML_RULE, path, at, "no anchors: write each value out"))
                if event.tag:
                    problems.append(finding(Result.BREAKS, YAML_RULE, path, at, f"no tags: remove {event.tag}"))
        if problems:
            return None, tuple(problems)
        data = _yaml().load(text)
    except YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        at = Span(path, mark.line + 1, mark.column + 1) if mark else Span(path, 1, 1)
        what = (getattr(e, "problem", None) or str(e).splitlines()[0]).strip()
        return None, (finding(Result.BREAKS, YAML_RULE, path, at, f"cannot be read: {what}"),)
    if data is None:
        return Map((), Span(path, 1, 1)), ()
    return _convert(data, path, 1, 1, scan(text)), ()

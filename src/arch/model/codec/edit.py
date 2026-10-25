"""Editing one design file with the smallest possible text change.

Part of arch.model.codec. A NodeFile knows a file's frontmatter fields and body sections; changing a
field rewrites only that field's lines, and new fields go in canonical order. Everything else, including
comments and formatting people chose, is left exactly as it was.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NewType

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from arch.model.ids import CriterionLabel, FieldName, Ref, Text
from arch.model.codec.read import HeadValue
from arch.model.schema import DecisionLabel, Kind, SourceText

FieldValue = Text | tuple[Ref, ...] | None  # None removes the field
_YamlScalar = NewType("_YamlScalar", str)

_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$")
_CRITERION = re.compile(r"^- AC(\d+):")
_ORDER: Mapping[Kind, tuple[str, ...]] = {
    Kind.COMPONENT: ("kind", "realizes", "solution", "hides", "publishes", "serves", "uses", "exports", "status"),
    Kind.NEED: ("kind", "stakeholder", "signal"),
    Kind.CONSTRAINT: ("kind", "applies_to", "rule"),
}
_CRITERIA = "Acceptance criteria"
_DECISIONS = "Decisions"
_PLAIN_UNSAFE = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`\s]|: | #|\s$|^(true|false|yes|no|on|off|null|~)$|^[0-9.+-]", re.I)


# characters JSON leaves as they are that YAML refuses, or reads as a line break, inside quotes
_UNPRINTABLE = re.compile("[\x7f-\x9f\u2028\u2029\ufffe\uffff]")
_FLOW_INDICATOR = re.compile(r"[,\[\]{}]")  # these end a plain value inside [...] or {...}
_yaml = YAML(typ="safe", pure=True)


def _scalar(value: Text, flow: bool = False) -> _YamlScalar:
    """A YAML scalar for `value`: plain when it reads back as exactly `value`, else double-quoted, with the
    characters YAML refuses to read escaped. Inside a one-line list or mapping (`flow`), fewer values are plain."""
    if (value and not _PLAIN_UNSAFE.search(value) and "\n" not in value and not (flow and _FLOW_INDICATOR.search(value))
            and _reads_back(value)):
        return _YamlScalar(value)
    quoted = json.dumps(value, ensure_ascii=False)
    return _YamlScalar(_UNPRINTABLE.sub(lambda m: f"\\u{ord(m.group()):04x}", quoted))


def _reads_back(plain: str) -> bool:
    try:
        return _yaml.load(io.StringIO(f"k: {plain}\n")) == {"k": plain}
    except YAMLError:
        return False


def _render(value: FieldValue) -> _YamlScalar:
    if isinstance(value, str):
        return _scalar(value)
    return _YamlScalar("[" + ", ".join(_scalar(Text(r), flow=True) for r in value) + "]")


def document(head: Sequence[tuple[FieldName, HeadValue]], body: Text) -> SourceText:
    """A whole file in the design's format, frontmatter then body, from plain values; the codec does all the
    quoting. Other stores kept in the same format, such as the findings ledger, write through this."""
    lines = ["---"]
    for name, value in head:
        if isinstance(value, str):
            if value:
                lines.append(f"{name}: {_scalar(value)}")
        elif value is not None:
            lines.append(f"{name}:" if value else f"{name}: []")
            lines += ["  - {" + ", ".join(f"{k}: {_scalar(v, flow=True)}" for k, v in e.items()) + "}" for e in value]
    return SourceText("\n".join([*lines, "---", body.strip(), ""]))


@dataclass(frozen=True)
class DecisionDraft:
    title: Text
    lines: Sequence[tuple[DecisionLabel, Text]]  # in the order to write them


class NodeFile:
    """One design file, edited in place. Construct from text, call edits, read `.text`."""

    def __init__(self, kind: Kind, text: SourceText):
        self.kind = kind
        lines = text.split("\n")
        if not lines or lines[0] != "---" or "---" not in lines[1:]:
            raise ValueError("not a design file: missing frontmatter")
        self._end = lines.index("---", 1)  # index of the closing delimiter
        self._lines = lines

    @staticmethod
    def new(kind: Kind, fields: Mapping[FieldName, FieldValue], body: Text = Text("")) -> NodeFile:
        f = NodeFile(kind, f"---\nkind: {kind.value}\n---\n")
        for name in _ORDER[kind]:
            if name in fields and fields[name] is not None:
                f.set_field(name, fields[name])
        if body:
            f.set_body(body)
        return f

    @property
    def text(self) -> SourceText:
        return "\n".join(self._lines)

    # frontmatter

    def _field_span(self, name: FieldName) -> tuple[int, int] | None:
        """Line range [start, end) of a top-level key and its indented continuation lines."""
        for i in range(1, self._end):
            m = _KEY.match(self._lines[i])
            if m and m.group(1) == name:
                j = i + 1
                while j < self._end and self._lines[j][:1] in (" ", "\t"):
                    j += 1
                return i, j
        return None

    def set_field(self, name: FieldName, value: FieldValue) -> None:
        span = self._field_span(name)
        empty = value is None or (isinstance(value, tuple) and not value)
        if empty:
            if span:
                del self._lines[span[0] : span[1]]
                self._end -= span[1] - span[0]
            return
        line = f"{name}: {_render(value)}"
        if span:
            self._lines[span[0] : span[1]] = [line]
            self._end -= span[1] - span[0] - 1
            return
        order = _ORDER[self.kind]
        later = order[order.index(name) + 1 :] if name in order else ()
        at = next((s[0] for s in (self._field_span(n) for n in later) if s), self._end)
        self._lines.insert(at, line)
        self._end += 1

    def set_body(self, text: Text) -> None:
        """Replace everything after the frontmatter (a need's statement)."""
        self._lines = self._lines[: self._end + 1] + text.rstrip("\n").split("\n") + [""]

    # body sections

    def _section(self, title: str) -> tuple[int, int] | None:
        """Line range [heading, end) of a `## title` section in the body."""
        for i in range(self._end + 1, len(self._lines)):
            if self._lines[i] == f"## {title}":
                j = i + 1
                while j < len(self._lines) and not self._lines[j].startswith("## "):
                    j += 1
                return i, j
        return None

    def _ensure_section(self, title: str, first: bool) -> tuple[int, int]:
        if (span := self._section(title)) is not None:
            return span
        if first:  # directly after the frontmatter, before other sections
            at = self._end + 1
            self._lines[at:at] = [f"## {title}", ""]
            return at, at + 2
        while self._lines and self._lines[-1] == "":
            self._lines.pop()
        self._lines += ["", f"## {title}", ""]
        return len(self._lines) - 2, len(self._lines)

    def add_criterion(self, text: Text) -> CriterionLabel:
        start, end = self._ensure_section(_CRITERIA, first=True)
        numbers = [int(m.group(1)) for line in self._lines[start:end] if (m := _CRITERION.match(line))]
        label = CriterionLabel(f"AC{max(numbers, default=0) + 1}")
        last = max((i for i in range(start, end) if _CRITERION.match(self._lines[i])), default=start)
        self._lines.insert(last + 1, f"- {label}: {text}")
        return label

    def set_criterion(self, label: CriterionLabel, text: Text) -> bool:
        span = self._section(_CRITERIA)
        for i in range(*span) if span else ():
            if self._lines[i].startswith(f"- {label}:"):
                self._lines[i] = f"- {label}: {text}"
                return True
        return False

    def remove_criterion(self, label: CriterionLabel) -> bool:
        span = self._section(_CRITERIA)
        for i in range(*span) if span else ():
            if self._lines[i].startswith(f"- {label}:"):
                del self._lines[i]
                return True
        return False

    def add_decision(self, draft: DecisionDraft) -> None:
        start, end = self._ensure_section(_DECISIONS, first=False)
        block = [f"### {draft.title}", *(f"- {label.value}: {text}" for label, text in draft.lines)]
        while end > start + 1 and self._lines[end - 1] == "":
            end -= 1
        has_entries = any(line.startswith("### ") for line in self._lines[start:end])
        self._lines[end:end] = ([""] if has_entries else []) + block
        if end + len(block) >= len(self._lines) or self._lines[-1] != "":
            self._lines.append("")

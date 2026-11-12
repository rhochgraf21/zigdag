"""An IAM policy written as text inside a resource's block, with jsonencode or as a heredoc, read from the source for
what each of its statements allows.

The plan cannot give this: a policy that refers to another resource is not known until it is applied, and the plan
records only which resources the whole text refers to. So the text itself is read, by its braces and its keys, and
only as far as it can be read for certain. A policy that says anything this cannot follow, a name passed in from
elsewhere or an exclusion, is not read at all: a statement half read would report access as missing that is granted.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import deal

from zigdag.core.names import Identifier
from zigdag.core.texts import Written

_KEY = r'"?{}"?\s*[=:]\s*'  # a key of a statement, as HCL writes it or as JSON does
_ACTION, _RESOURCE = re.compile(_KEY.format("Action")), re.compile(_KEY.format("Resource"))
_DENIES = re.compile(_KEY.format("Effect") + '"Deny"')
# What excludes rather than names: read as naming, each would grant the opposite of what is written.
_EXCLUDES = re.compile(r'"?Not(Action|Resource)"?\s*[=:]')
# A name whose value is given elsewhere, so what it stands for here cannot be told from this block.
_ELSEWHERE = re.compile(r"\b(var|local|module|data|each|count)\.")
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_REFERENCE = re.compile(r"\b([a-z][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_-]*)")
_OPEN, _CLOSE, _QUOTE, _ESCAPE = "{", "}", '"', "\\"
_OPENERS, _CLOSERS = "[({", "])}"
_ENDS_A_VALUE = ",\n])}"  # what ends a value that is not inside a bracket of its own


@dataclass(frozen=True)
class Statement:
    """One statement of a written policy that allows."""

    actions: tuple[Written, ...]  # s3:PutObject
    on: tuple[tuple[Identifier, Identifier], ...]  # the resources of its module it names, each by type and name
    everything: bool  # it names no resource of its module: its resources are constants, such as "*"


def _outside_texts(text: str) -> list[int]:
    """Each position of the text that is not inside a quoted text."""
    positions, inside, at = [], False, 0
    while at < len(text):
        if text[at] == _ESCAPE and inside:
            at += 2
            continue
        if text[at] == _QUOTE:
            inside = not inside
        elif not inside:
            positions.append(at)
        at += 1
    return positions


def _objects(text: str) -> list[tuple[int, int]]:
    """Where each pair of braces opens and closes, a brace inside a quoted text not counting."""
    opened, pairs = [], []
    for at in _outside_texts(text):
        if text[at] == _OPEN:
            opened.append(at)
        elif text[at] == _CLOSE and opened:
            pairs.append((opened.pop(), at))
    return pairs


def _value(text: str, start: int) -> str:
    """The value written from a position on: up to the comma, the line's end or the closing bracket that ends it,
    one inside a list, a call or a quoted text of its own not counting."""
    outside = set(_outside_texts(text))
    depth = 0
    for at in range(start, len(text)):
        if at not in outside:
            continue
        if text[at] in _OPENERS:
            depth += 1
        elif text[at] in _CLOSERS and depth:
            depth -= 1
        elif text[at] in _ENDS_A_VALUE and not depth:
            return text[start:at]
    return text[start:]


def _constants(value: str) -> tuple[Written, ...] | None:
    """The texts a value is made of, or None when it is anything but texts in a list."""
    rest = _QUOTED.sub("", value).translate(str.maketrans("", "", "[], \n\t"))
    return tuple(Written(t) for t in _QUOTED.findall(value)) if not rest else None


@deal.pure
@deal.ensure(lambda lines, known, result: result is None or all(
    s.actions and set(s.on) <= set(known) and s.everything == (not s.on) for s in result))
def statements(lines: Sequence[str], known: frozenset[tuple[Identifier, Identifier]]) -> tuple[Statement, ...] | None:
    """What each statement written in a block allows, on which of its module's resources; None when the block says
    something that cannot be read for certain, so that nothing is taken from it. A statement that denies, or that
    names no resource at all, as one that says who may take a role does, grants nothing and is left out."""
    text = "\n".join(lines)
    if _EXCLUDES.search(text) is not None:
        return None
    objects = _objects(text)
    found = []
    for action in _ACTION.finditer(text):
        around = [(start, end) for start, end in objects if start < action.start() < end]
        if not around:
            return None
        start, end = max(around)  # the innermost braces it is written in: its statement
        statement = text[start:end + 1]
        resource = _RESOURCE.search(statement)
        if _DENIES.search(statement) is not None or resource is None:
            continue
        actions = _constants(_value(text, action.end()))
        named = _value(statement, resource.end())
        if actions is None or not actions or _ELSEWHERE.search(named) is not None:
            return None
        on = tuple(sorted({(Identifier(t), Identifier(n)) for t, n in _REFERENCE.findall(named)} & known))
        found.append(Statement(actions, on, not on))
    return tuple(found)

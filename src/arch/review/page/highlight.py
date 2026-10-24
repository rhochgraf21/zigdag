"""Syntax highlighting for Python diff lines, done here so the page needs no script library.

Part of arch.review.page. Works line by line (a diff hunk is a fragment, not a program), so it uses
patterns rather than a parser; unknown text passes through escaped.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NewType

from arch.review.explain import NameTip

HighlightedHtml = NewType("HighlightedHtml", str)
CodeLine = NewType("CodeLine", str)  # one line of source as it appears in a diff

_KEYWORDS = (
    "def class return if elif else for while in is not and or import from as with try except finally raise yield "
    "lambda pass break continue global nonlocal assert del async await match case"
).split()
_CONSTANTS = ("None", "True", "False", "self", "cls")
_TOKEN = re.compile(
    r"(?P<comment>#.*$)"
    r"|(?P<string>(?:[rRbBfFuU]{1,2})?(?:\"\"\"|'''|\"(?:\\.|[^\"\\])*\"?|'(?:\\.|[^'\\])*'?))"
    r"|(?P<decorator>^\s*@[\w.]+)"
    r"|(?P<defname>(?<=\bdef )\w+|(?<=\bclass )\w+)"
    r"|(?P<keyword>\b(?:" + "|".join(_KEYWORDS) + r")\b)"
    r"|(?P<constant>\b(?:" + "|".join(_CONSTANTS) + r")\b)"
    r"|(?P<number>\b\d[\d_]*(?:\.\d+)?\b)"
)


def python(line: CodeLine, names: Sequence[NameTip] = ()) -> HighlightedHtml:
    tokens = [_Span(m.start(), m.end(), f'<span class="t-{m.lastgroup}">') for m in _TOKEN.finditer(line)]
    return _render(line, tokens, names)


def plain(line: CodeLine, names: Sequence[NameTip] = ()) -> HighlightedHtml:
    return _render(line, [], names)


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    open: str


def _render(line: str, tokens: list[_Span], names: Sequence[NameTip]) -> HighlightedHtml:
    """Tokens and explained names as nested spans. A name that would cross a token's edge is left out."""
    spans = list(tokens)
    for n in names:
        span = _Span(n.start, n.end, f'<span class="name" data-tip="{html.escape(n.tip)}">')
        if n.start < n.end and all(_nests(span, s) for s in spans):
            spans.append(span)
    spans.sort(key=lambda s: (s.start, -s.end))

    def emit(start: int, end: int, inner: list[_Span]) -> str:
        out, pos, i = [], start, 0
        while i < len(inner):
            s, j = inner[i], i + 1
            while j < len(inner) and inner[j].start < s.end:
                j += 1
            out += [html.escape(line[pos:s.start]), s.open, emit(s.start, s.end, inner[i + 1:j]), "</span>"]
            pos, i = s.end, j
        out.append(html.escape(line[pos:end]))
        return "".join(out)
    return HighlightedHtml(emit(0, len(line), spans))


def _nests(a: _Span, b: _Span) -> bool:
    return a.end <= b.start or b.end <= a.start or (b.start <= a.start and a.end <= b.end) or (a.start <= b.start and b.end <= a.end)

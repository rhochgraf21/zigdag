"""Syntax highlighting for Python diff lines, done here so the page needs no script library.

Part of arch.review.page. Works line by line (a diff hunk is a fragment, not a program), so it uses
patterns rather than a parser; unknown text passes through escaped.
"""

from __future__ import annotations

import html
import re
from typing import NewType

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


def python(line: CodeLine) -> HighlightedHtml:
    out, pos = [], 0
    for m in _TOKEN.finditer(line):
        out.append(html.escape(line[pos:m.start()]))
        out.append(f'<span class="t-{m.lastgroup}">{html.escape(m.group())}</span>')
        pos = m.end()
    out.append(html.escape(line[pos:]))
    return HighlightedHtml("".join(out))


def plain(line: CodeLine) -> HighlightedHtml:
    return HighlightedHtml(html.escape(line))

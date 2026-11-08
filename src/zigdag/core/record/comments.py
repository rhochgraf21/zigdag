"""Where a design file's comments are, line by line. Reasons (DESIGN2 §7.2) and formatting both read them here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Comments:
    whole: Mapping[int, str]  # 0-based line -> the text of a line that is only a comment
    beside: Mapping[int, str]  # 0-based line -> the text of a comment after something on that line

    def above(self, line: int) -> str | None:
        """The whole-line comments directly above a line, joined: the reason for what starts on it."""
        found: list[str] = []
        i = line - 1
        while i in self.whole:
            if self.whole[i]:
                found.insert(0, self.whole[i])
            i -= 1
        return " ".join(found) or None


def _comment_start(line: str) -> int | None:
    """Where a YAML comment starts on the line: a # outside quotes, at the start or after a space."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote == '"' and c == "\\":
            i += 2
            continue
        if quote is None and c in "\"'" and (i == 0 or line[i - 1] in " \t[{,:-"):
            quote = c
        elif quote == "'" and c == "'":
            if i + 1 < len(line) and line[i + 1] == "'":
                i += 2
                continue
            quote = None
        elif quote == '"' and c == '"':
            quote = None
        elif quote is None and c == "#" and (i == 0 or line[i - 1] in " \t"):
            return i
        i += 1
    return None


def _text(comment: str) -> str:
    return comment[1:].strip()


def scan(text: str) -> Comments:
    whole: dict[int, str] = {}
    beside: dict[int, str] = {}
    for n, line in enumerate(text.splitlines()):
        if line.strip().startswith("#"):
            whole[n] = _text(line.strip())
        elif (at := _comment_start(line)) is not None:
            beside[n] = _text(line[at:])
    return Comments(whole, beside)

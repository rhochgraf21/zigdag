"""Terraform source and test files, read only for where each block is written: what is deployed is read from the
plan, and the source gives each finding its location (DESIGN2 §5.3).

Only a block's first line and its length are found, by its braces, and the lines directly inside it. The language
itself is not parsed: what a block means is the plan's to say.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

import deal

from zigdag.core.measures import Line, LineCount
from zigdag.core.names import Identifier
from zigdag.core.texts import FileText, Written

_HEADER = re.compile(r'\s*(resource|module|run)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{')
_HEREDOC = re.compile(r"<<-?\s*(\w+)\s*$")
_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
_COMMENT = re.compile(r"(#|//).*$")
_OPEN, _CLOSE = "{", "}"


class BlockKind(enum.Enum):
    RESOURCE = "resource"
    MODULE = "module"
    RUN = "run"  # one run of a test file


@dataclass(frozen=True)
class Block:
    """One top-level block of a file: a resource, a call of a module, or a run of a test file."""

    kind: BlockKind
    type: Identifier | None  # a resource's type: aws_s3_bucket; a module call and a run have none
    name: Identifier
    line: Line
    size: LineCount
    own: tuple[Written, ...] = ()  # the lines directly inside it, not inside a block of its own, without comments
    comments: tuple[tuple[Line, Written], ...] = ()  # each comment inside it or directly above it, and its line


def _code(line: str) -> str:
    """A line without what braces inside it would not be the block's own: its texts and its comment."""
    return _COMMENT.sub("", _QUOTED.sub('""', line))


def _length(lines: list[str], start: int) -> LineCount:
    """How many lines the block that opens at a line runs for, to the brace that closes it; to the end of the file
    when none does."""
    depth, heredoc = 0, None
    for at in range(start, len(lines)):
        if heredoc is not None:  # the text of a heredoc is not code, whatever braces it holds
            heredoc = None if lines[at].strip() == heredoc else heredoc
            continue
        code = _code(lines[at])
        opened = _HEREDOC.search(code)
        heredoc = opened.group(1) if opened else None
        depth += code.count(_OPEN) - code.count(_CLOSE)
        if depth <= 0:
            return LineCount(at - start + 1)
    return LineCount(len(lines) - start)


def _own(lines: list[str], start: int, size: LineCount) -> tuple[Written, ...]:
    """The lines of a block that are its own: at its first depth, where its arguments are written."""
    depth, own = 0, []
    for line in lines[start:start + size]:
        code = _code(line)
        if depth == 1 and code.strip():
            own.append(Written(code.strip()))
        depth += code.count(_OPEN) - code.count(_CLOSE)
    return tuple(own)


def _comment(line: str) -> Written | None:
    found = _COMMENT.search(_QUOTED.sub('""', line))
    return Written(found.group().lstrip("#/").strip()) if found else None


def _comments(lines: list[str], start: int, size: LineCount) -> list[tuple[Line, Written]]:
    return [(Line(at + 1), said) for at in range(start, start + size) if (said := _comment(lines[at])) is not None]


def _above(lines: list[str], start: int) -> list[tuple[Line, Written]]:
    """The comment lines directly above a block, which are about it."""
    at, found = start - 1, []
    while at >= 0 and lines[at].strip().startswith(("#", "//")):
        found.append((Line(at + 1), Written(lines[at].strip().lstrip("#/").strip())))
        at -= 1
    return found[::-1]


_LOCALS = re.compile(r"\s*locals\s*\{")
_LOCAL = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(.+)$")
_REFERS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_]")  # one name inside another: a reference, or a call's result
_INTERPOLATED = "${"  # a text that holds an expression, which may refer to anything
_OPENS_A_VALUE = ("{", "[", "(")  # how a line ends when the value it begins goes on below it


@deal.pure
@deal.ensure(lambda text, result: all(name and not name[0].isdigit() for name in result))
def constant_locals(text: FileText) -> frozenset[Identifier]:
    """The local values a file gives a plain constant: a text, a number or a truth value written on one line, with
    no name in it. Such a local refers to nothing, whatever refers to it."""
    lines = text.splitlines()
    found = set()
    for at, line in enumerate(lines):
        if _LOCALS.match(line) is None:
            continue
        depth = 0
        for raw in lines[at:at + _length(lines, at)]:
            code = _code(raw)
            entry = _LOCAL.match(code.strip()) if depth == 1 else None
            depth += code.count(_OPEN) - code.count(_CLOSE)
            if entry is None or entry.group(2).rstrip().endswith(_OPENS_A_VALUE):
                continue  # a value that runs over several lines may hold anything
            if _REFERS.search(entry.group(2)) is None and _INTERPOLATED not in raw:
                found.add(Identifier(entry.group(1)))
    return frozenset(found)


@deal.pure
@deal.ensure(lambda text, result: all(1 <= b.line <= len(text.splitlines()) and b.size >= 1 for b in result))
@deal.ensure(lambda text, result: [b.line for b in result] == sorted(b.line for b in result))
def blocks(text: FileText) -> tuple[Block, ...]:
    """The resources, module calls and test runs a file writes, in the file's order."""
    lines = text.splitlines()
    found = []
    for at, line in enumerate(lines):
        header = _HEADER.match(line)
        if header is None:
            continue
        kind = BlockKind(header.group(1))
        first, second = header.group(2), header.group(3)
        if (kind is BlockKind.RESOURCE) != (second is not None):
            continue  # a resource has a type and a name; a module call and a run have a name only
        size = _length(lines, at)
        found.append(Block(kind, Identifier(first) if second else None, Identifier(second or first), Line(at + 1),
                           size, _own(lines, at, size), (*_above(lines, at), *_comments(lines, at, size))))
    return tuple(found)

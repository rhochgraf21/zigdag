"""The numbers zigdag counts and places things by, each with its own name (DESIGN2 §4.1, edge-types)."""

from __future__ import annotations

from typing import NewType

Count = NewType("Count", int)  # how many of something there are
LineCount = NewType("LineCount", int)  # how many lines a unit or a symbol has
Line = NewType("Line", int)  # a line of a file, counting from 1
Column = NewType("Column", int)  # a column of a line, counting from 1
Offset = NewType("Offset", int)  # a position inside a string, counting from 0
Seconds = NewType("Seconds", float)  # a length of time
Version = NewType("Version", int)  # a version number: of the rubric, or of a rule set

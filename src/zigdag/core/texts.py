"""The kinds of text zigdag reads, writes and shows, each with its own name, so that one is never passed where
another is meant (DESIGN2 §4.1, edge-types)."""

from __future__ import annotations

from typing import NewType

FileText = NewType("FileText", str)  # the text of a file of the project: a design file, the settings, source, a test
Say = NewType("Say", str)  # words for people: a finding's message, a reason, a description, an answer
Shown = NewType("Shown", str)  # what zigdag prints for people: a report, a view, a review
Written = NewType("Written", str)  # text as someone wrote it, before it is read: a name, an annotation, a line of code
SentenceText = NewType("SentenceText", str)  # a sentence of the record, or a part of one, as written
Word = NewType("Word", str)  # one word, as the grammar and the lexicons use it
Content = NewType("Content", str)  # what a digest covers: the content a finding or an entry is about
ToolText = NewType("ToolText", str)  # what a tool that zigdag ran printed, on its standard output or error

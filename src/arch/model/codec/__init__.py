"""Design files <-> nodes, without losing or reformatting what people wrote.

Realizes arch.model.codec. Hides the on-disk format: reading lives in `read`, minimal-diff editing of a
single file and writing a whole one in `edit`. Callers pass and get plain values; YAML stays in here.
"""

from __future__ import annotations

from arch.model.codec.edit import DecisionDraft, FieldValue, NodeFile, document
from arch.model.codec.read import Document, Entry, HeadValue, kind_of, load, node_id, parse, path_of, read_document

__all__ = ["DecisionDraft", "Document", "Entry", "FieldValue", "HeadValue", "NodeFile", "document", "kind_of", "load",
           "node_id", "parse", "path_of", "read_document"]

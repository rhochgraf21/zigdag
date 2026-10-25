"""Design files <-> nodes, without losing or reformatting what people wrote.

Realizes arch.model.codec. Hides the on-disk format: reading lives in `read`, minimal-diff editing of a
single file in `edit`.
"""

from __future__ import annotations

from arch.model.codec.edit import DecisionDraft, FieldValue, NodeFile, scalar
from arch.model.codec.read import Frontmatter, frontmatter, kind_of, load, node_id, parse, path_of

__all__ = ["DecisionDraft", "FieldValue", "Frontmatter", "NodeFile", "frontmatter", "kind_of", "load", "node_id", "parse", "path_of", "scalar"]

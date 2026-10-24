"""The vocabulary every view renders with: Markdown, JSON values, sizes and counts.

Realizes arch.view.render.
"""

from __future__ import annotations

from typing import NewType, Protocol, TypeAlias

Markdown = NewType("Markdown", str)
JsonValue: TypeAlias = "dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None"
JsonObject: TypeAlias = "dict[str, JsonValue]"
Columns = NewType("Columns", int)  # a width in characters
Count = NewType("Count", int)


class Rendering(Protocol):
    def to_markdown(self) -> Markdown: ...
    def to_json(self) -> JsonValue: ...

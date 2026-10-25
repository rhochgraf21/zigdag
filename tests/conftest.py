from __future__ import annotations

from collections.abc import Mapping

from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import DesignPath


def component(uses: str = "", exports: str = "", serves: str = "", status: str = "specified",
              hides: str | None = "a secret", criteria: int = 1, body: str = "") -> str:
    lines = ["---", "kind: component", "realizes: Do the thing", "solution: The thing-doer"]
    if hides:
        lines.append(f"hides: {hides}")
    for key, value in (("uses", uses), ("exports", exports), ("serves", serves)):
        if value:
            lines.append(f"{key}: [{value}]")
    lines += [f"status: {status}", "---", "## Acceptance criteria"]
    lines += [f"- AC{i}: When asked, it shall do the thing." for i in range(1, criteria + 1)]
    return "\n".join(lines) + "\n" + body


NEED = "---\nkind: need\n---\nSomeone can get something done.\n"


def graph(files: Mapping[str, str]) -> Graph:
    return Graph(codec.load({DesignPath(k): v for k, v in files.items()}))

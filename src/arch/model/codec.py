"""Design files <-> nodes.

Realizes arch.model.codec. Hides the on-disk format: Markdown files with YAML frontmatter, laid out as
needs/, constraints/ and components/ (where the directory tree is the decomposition).

Parsing only for now. Rendering and minimal-diff edits arrive with arch.change.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping

import deal
from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from arch.model.ids import (
    ComponentId,
    ConstraintId,
    CriterionId,
    DesignPath,
    FieldName,
    Issue,
    LineNo,
    Location,
    NeedId,
    Ref,
    Text,
)
from arch.model.policy import Policy
from arch.model.schema import (
    Component,
    Constraint,
    Criterion,
    DecisionEntry,
    DecisionLabel,
    Design,
    Kind,
    Need,
    SourceText,
    Status,
    validate_fields,
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
_CRITERION = re.compile(r"^- (AC\d+):[ \t]*(.+)$", re.M)
_SECTION = re.compile(r"^## (.+?)[ \t]*$", re.M)
_ENTRY = re.compile(r"^### (.+?)[ \t]*$", re.M)
_LABEL = re.compile(r"^- (" + "|".join(label.value for label in DecisionLabel) + r"):", re.M)
_KIND_DIRS: Mapping[str, Kind] = {
    "needs": Kind.NEED,
    "constraints": Kind.CONSTRAINT,
    "components": Kind.COMPONENT,
}

_yaml = YAML(typ="safe", pure=True)


def node_id(path: DesignPath) -> str | None:
    """`components/arch/model/schema.md` -> `arch.model.schema`; None for files that are not nodes."""
    parts = path.split("/")
    if len(parts) < 2 or parts[0] not in _KIND_DIRS or not parts[-1].endswith(".md"):
        return None
    parts[-1] = parts[-1].removesuffix(".md")
    if parts[0] != "components" and len(parts) != 2:
        return None
    return ".".join(parts[1:])


def kind_of(path: DesignPath) -> Kind | None:
    return _KIND_DIRS.get(path.split("/")[0]) if node_id(path) else None


@deal.has()
def load(files: Mapping[DesignPath, SourceText]) -> Design:
    """Parse every node file into a Design. Problems become issues; nothing raises."""
    components: dict[ComponentId, Component] = {}
    needs: dict[NeedId, Need] = {}
    constraints: dict[ConstraintId, Constraint] = {}
    issues: list[Issue] = []
    for path in sorted(files):
        kind = kind_of(path)
        if kind is None:
            continue
        node, node_issues = parse(path, files[path])
        issues.extend(node_issues)
        match node:
            case Component():
                components[node.id] = node
            case Need():
                needs[node.id] = node
            case Constraint():
                constraints[node.id] = node
    sources = {p: files[p] for p in sorted(files) if kind_of(p) is not None}
    return Design(components, needs, constraints, tuple(issues), sources)


Node = Component | Need | Constraint


def parse(path: DesignPath, text: SourceText) -> tuple[Node | None, tuple[Issue, ...]]:
    kind, ident = kind_of(path), node_id(path)
    loc = Location(path)
    if kind is None or ident is None:
        return None, (Issue(loc, None, Text("not a design node path")),)

    m = _FRONTMATTER.match(text)
    if not m:
        return None, (Issue(loc, None, Text("missing YAML frontmatter delimited by '---' lines")),)
    try:
        raw = _yaml.load(io.StringIO(m.group(1))) or {}
    except MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        line = LineNo(mark.line + 2) if mark else LineNo(1)
        return None, (Issue(Location(path, line), None, Text(f"invalid YAML: {e.problem or e}")),)
    except YAMLError as e:
        return None, (Issue(loc, None, Text(f"invalid YAML: {e}")),)
    if not isinstance(raw, dict):
        return None, (Issue(loc, None, Text("frontmatter must be a mapping")),)

    if raw.get("kind") != kind.value:
        return None, (Issue(loc, FieldName("kind"), Text(f"kind must be '{kind.value}' for files in this directory")),)

    issues = validate_fields(kind, raw, loc)
    if any(i.message.startswith("missing required") or i.field in _hard_fields(kind) for i in issues):
        return None, issues

    body_start = m.end()
    body = text[body_start:]

    def refs(name: str) -> tuple[Ref, ...]:
        value = raw.get(name)
        return tuple(Ref(v) for v in value) if isinstance(value, list) else ()

    def opt_text(name: str) -> Text | None:
        value = raw.get(name)
        return Text(value.strip()) if isinstance(value, str) and value.strip() else None

    def line_at(offset_in_body: int) -> LineNo:
        return LineNo(text.count("\n", 0, body_start + offset_in_body) + 1)

    match kind:
        case Kind.COMPONENT:
            cid = ComponentId(ident)
            criteria = tuple(
                Criterion(CriterionId(f"{cid}#{c.group(1)}"), Text(c.group(2).strip()), Location(path, line_at(c.start())))
                for c in _CRITERION.finditer(body)
            )
            sets = raw.get("accepts_coupling")
            accepted = tuple(tuple(Ref(v) for v in s) for s in sets if isinstance(s, list)) if isinstance(sets, list) else ()
            node: Node = Component(
                id=cid,
                realizes=Text(raw["realizes"].strip()),
                solution=Text(raw["solution"].strip()),
                hides=opt_text("hides"),
                serves=tuple(NeedId(r) for r in refs("serves")),
                uses=refs("uses"),
                exports=refs("exports"),
                accepts_coupling=accepted,
                status=Status(raw["status"]),
                criteria=criteria,
                decisions=_decisions(body, path, line_at),
                location=loc,
            )
        case Kind.NEED:
            statement = body.strip()
            if not statement:
                return None, issues + (Issue(loc, None, Text("a need's statement is its body text, which is empty")),)
            node = Need(NeedId(ident), Text(statement), opt_text("stakeholder"), opt_text("signal"), loc)
        case Kind.CONSTRAINT:
            rule = raw.get("rule")
            policy, problems = Policy.parse(rule) if isinstance(rule, dict) else (Policy(), ())
            issues += tuple(Issue(loc, FieldName("rule"), p) for p in problems)
            node = Constraint(ConstraintId(ident), tuple(ComponentId(r) for r in refs("applies_to")),
                              policy, Text(body.strip()), loc)
    return node, issues


def _decisions(body: str, path: DesignPath, line_at) -> tuple[DecisionEntry, ...]:
    """Entries under `## Decisions`: each `### title` up to the next entry or section."""
    sections = list(_SECTION.finditer(body))
    for i, s in enumerate(sections):
        if s.group(1) != "Decisions":
            continue
        start, end = s.end(), sections[i + 1].start() if i + 1 < len(sections) else len(body)
        heads = list(_ENTRY.finditer(body, start, end))
        entries = []
        for j, h in enumerate(heads):
            stop = heads[j + 1].start() if j + 1 < len(heads) else end
            chunk = body[h.end():stop].strip()
            labels = frozenset(DecisionLabel(m.group(1)) for m in _LABEL.finditer(chunk))
            entries.append(DecisionEntry(Text(h.group(1)), Text(chunk), labels, Location(path, line_at(h.start()))))
        return tuple(entries)
    return ()


def _hard_fields(kind: Kind) -> frozenset[FieldName]:
    """Fields whose malformation prevents building the node at all."""
    return {
        Kind.COMPONENT: frozenset({FieldName("realizes"), FieldName("solution"), FieldName("status")}),
        Kind.CONSTRAINT: frozenset(),
        Kind.NEED: frozenset(),
    }[kind]

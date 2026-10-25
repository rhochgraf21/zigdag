"""Structural defects in the design.

Realizes arch.check.structure. Each rule is a pure function of the design graph.
"""

from __future__ import annotations

from collections.abc import Iterator

from arch.check.engine import Context, Finding, FindingKey, Kind, Rule, RuleId, Station, Subject
from arch.model.graph import is_within, parent_of
from arch.model.matrix import matrix_of
from arch.model.ids import Text
from arch.model.schema import DecisionLabel

MAX_SPAN = 9


def _finding(rule: str, subject: str, key: str, kind: Kind, message: str, hint: str, location=None) -> Finding:
    return Finding(Subject(subject), RuleId(rule), FindingKey(key), kind, Text(message), Text(hint), location)


def invalid_nodes(ctx: Context) -> Iterator[Finding]:
    for issue in ctx.graph.design.issues:
        yield _finding(
            "S000", issue.location.path, f"{issue.field}:{issue.message}", Kind.DEFECT,
            issue.message, "fix the frontmatter so the node parses", issue.location,
        )


def dangling_references(ctx: Context) -> Iterator[Finding]:
    g, design = ctx.graph, ctx.graph.design
    for cid in g.ids():
        c = g[cid]
        for ref in c.uses:
            if g.resolve(cid, ref) is None:
                yield _finding("S001", cid, f"uses:{ref}", Kind.DEFECT, f"uses '{ref}', which resolves to no component",
                               "name a sibling, or a path from a sibling or an ancestor's sibling", c.location)
        for ref in c.exports:
            if f"{cid}.{ref}" not in g:
                yield _finding("S001", cid, f"exports:{ref}", Kind.DEFECT, f"exports '{ref}', which is not one of its children",
                               "exports may only name direct children", c.location)
        for need in c.serves:
            if need not in design.needs:
                yield _finding("S001", cid, f"serves:{need}", Kind.DEFECT, f"serves unknown need '{need}'",
                               "add the need under design/needs/ or fix the name", c.location)
    for k, con in sorted(design.constraints.items()):
        for ref in con.applies_to:
            if ref not in g:
                yield _finding("S001", k, f"applies_to:{ref}", Kind.DEFECT, f"applies to unknown component '{ref}'",
                               "use the component's full dotted id", con.location)


def orphans(ctx: Context) -> Iterator[Finding]:
    g = ctx.graph
    for cid in g.ids():
        parent = parent_of(cid)
        if parent is not None and parent not in g:
            yield _finding("S011", cid, "parent", Kind.DEFECT, f"its parent {parent} has no design file",
                           f"add the component {parent}, or move this one", g[cid].location)


def untraced(ctx: Context) -> Iterator[Finding]:
    g, design = ctx.graph, ctx.graph.design
    for root in g.roots:
        for cid in g.children(root):
            if not g[cid].serves:
                yield _finding("S002", cid, "serves", Kind.DEFECT, "top-level component declares no needs it serves",
                               "add `serves: [...]` naming the needs this part exists for", g[cid].location)
    # A root that has children delegates; the needs must be traced to the parts. A lone root is a whole project.
    served = {n for cid in g.ids() if parent_of(cid) is not None or not g.children(cid) for n in g[cid].serves}
    for nid, need in sorted(design.needs.items()):
        if nid not in served:
            yield _finding("S003", nid, "unserved", Kind.DEFECT, "no component below the root serves this need",
                           "serve it from a top-level component, or remove the need", need.location)


def span(ctx: Context) -> Iterator[Finding]:
    g = ctx.graph
    for cid in g.ids():
        if (n := len(g.children(cid))) > MAX_SPAN:
            yield _finding("S004", cid, "span", Kind.QUESTION, f"has {n} children (more than {MAX_SPAN})",
                           "group children into intermediate components", g[cid].location)


def coupling(ctx: Context) -> Iterator[Finding]:
    """Coupled children are a defect. Coupling kept on purpose is an accepted answer to this finding, with a
    decision entry saying why it could not be resolved."""
    g = ctx.graph
    for cid in g.ids():
        if not g.children(cid):
            continue
        c = g[cid]
        for coupled in matrix_of(g, cid).layering.coupled:
            names = ", ".join(x.rsplit(".", 1)[1] for x in coupled)
            yield _finding(
                "S005", cid, f"coupled:{'|'.join(coupled)}", Kind.DEFECT,
                f"children are coupled (cyclic uses): {names}",
                "remove a use, or move the shared part down a level. To keep it on purpose, accept this finding "
                "(`arch respond accepted`) and add a decision entry saying why", c.location,
            )


def decision_entries(ctx: Context) -> Iterator[Finding]:
    """Each decision entry states what was chosen and why (DP selection, in prose)."""
    g = ctx.graph
    for cid in g.ids():
        for entry in g[cid].decisions:
            missing = [l.value for l in (DecisionLabel.CHOSE, DecisionLabel.BECAUSE) if l not in entry.labels]
            if missing:
                yield _finding(
                    "S010", cid, f"decision:{entry.title}", Kind.DEFECT,
                    f"decision '{entry.title}' has no {' or '.join(missing)} line",
                    "write `- Chose: ...` and `- Because: ...` (optionally Over, Consequences, Previously, Backed by)",
                    entry.location,
                )


def missing_secret(ctx: Context) -> Iterator[Finding]:
    g = ctx.graph
    for cid in g.ids():
        c = g[cid]
        if parent_of(cid) is not None and c.hides is None and c.publishes is None:
            yield _finding("S006", cid, "hides", Kind.DEFECT,
                           "states neither a decision it hides nor a vocabulary it publishes",
                           "name the decision it keeps from the other parts (`hides`), or, for a design rule that "
                           "others build against, what it publishes (`publishes`)", c.location)


def missing_criteria(ctx: Context) -> Iterator[Finding]:
    g = ctx.graph
    for cid in g.ids():
        c = g[cid]
        if not c.criteria:
            yield _finding("S009", cid, "criteria", Kind.DEFECT, "has no acceptance criteria",
                           "add `- AC1: When ..., ... shall ...` lines to the body", c.location)


def illegal_uses(ctx: Context) -> Iterator[Finding]:
    g = ctx.graph
    for cid in g.ids():
        parent = parent_of(cid)
        for target in g.uses(cid):
            if not g.visible(cid, target):
                yield _finding("S008", cid, f"invisible:{target}", Kind.DEFECT,
                               f"uses {target}, which its parent does not export",
                               f"export it from {parent_of(target)}, or use that parent instead", g[cid].location)
            inside_parent = parent is not None and is_within(target, parent)  # a sibling or a sibling's part
            if parent is not None and not inside_parent and not any(is_within(target, u) for u in g.uses(parent)):
                yield _finding("S007", cid, f"outside:{target}", Kind.DEFECT,
                               f"uses {target}, which its parent {parent} may not use",
                               f"add it to the uses of {parent}, or remove this use", g[cid].location)


RULES: tuple[Rule, ...] = (
    Rule(RuleId("S000"), Station.FORM, Text("node files parse and match their schema"), invalid_nodes),
    Rule(RuleId("S001"), Station.FORM, Text("references resolve"), dangling_references),
    Rule(RuleId("S011"), Station.FORM, Text("every component's parent exists"), orphans),
    Rule(RuleId("S002"), Station.NEEDS, Text("top-level components and needs trace to each other"), untraced),
    Rule(RuleId("S004"), Station.SOLUTION, Text("at most nine children"), span),
    Rule(RuleId("S005"), Station.SOLUTION, Text("children are not coupled"), coupling),
    Rule(RuleId("S006"), Station.SOLUTION, Text("components state what they hide or publish"), missing_secret),
    Rule(RuleId("S007"), Station.SOLUTION, Text("uses stay within what the parent may use, and are visible"), illegal_uses),
    Rule(RuleId("S009"), Station.REQUIREMENTS, Text("components have acceptance criteria"), missing_criteria),
    Rule(RuleId("S010"), Station.SOLUTION, Text("decision entries say what was chosen and why"), decision_entries),
)

__all__ = ["RULES"]

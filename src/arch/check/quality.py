"""How easy the code's interfaces are to use and to change.

Realizes arch.check.quality. Rules over the code facts: names that need a description, parts that hide a decision
behind too wide an interface (Ousterhout's depth), parameters that pick the behaviour, wide parameters of which
one field is read, and abstractions with one implementation. Most are questions, because each has fair
exceptions that a person or a critic judges.
"""

from __future__ import annotations

from collections.abc import Iterator

from arch.check.conformance import mapping_of, source_units
from arch.check.engine import Context, Finding, FindingKey, Kind, Rule, RuleId, Station, Subject
from arch.model.graph import is_within, parent_of
from arch.model.ids import ComponentId, Text
from arch.realize.facts import Facts, UnitName, needs_description


def descriptions(ctx: Context) -> Iterator[Finding]:
    """Interface names say what they are. A name needs a one-line description when its name and type do not
    explain it, and the description must say more than the name."""
    m = mapping_of(ctx)
    source = source_units(ctx)
    facts = ctx.facts or Facts()
    defs = {(d.unit, d.name): d for d in facts.definitions}
    needed = needs_description(facts)
    for sym in facts.symbols:
        cid = m.component_of.get(sym.unit)
        d = defs.get((sym.unit, sym.name))
        if cid is None or d is None or sym.unit not in source:
            continue
        where = f"{sym.unit}.{sym.name}"
        if (sym.unit, sym.name) in needed:
            yield _finding("C014", cid, f"undescribed:{where}", Kind.DEFECT,
                           f"{where} is part of the interface, and its name and type do not say what it is",
                           _DESCRIBE, d.location)
        elif d.restates_name():
            yield _finding("C015", cid, f"restated:{where}", Kind.QUESTION,
                           f"the description of {where} only repeats its name and type: {d.summary!r}", _DESCRIBE, d.location)


MIN_DEPTH = 3.0  # lines of implementation per name or parameter a part shows the others
MIN_SURFACE = 8  # parts with smaller interfaces are not judged


def depth(ctx: Context) -> Iterator[Finding]:
    """A part that hides a decision earns its boundary by depth: an interface much smaller than what it hides
    (Ousterhout). One that is about as large outside as inside is a candidate to merge into its parent. A design
    rule, which publishes a vocabulary the other parts build against, is judged by stability instead."""
    g, m = ctx.graph, mapping_of(ctx)
    facts, source = ctx.facts or Facts(), source_units(ctx)
    units_of: dict[ComponentId, list[UnitName]] = {}
    for unit, cid in m.component_of.items():
        if unit in source:
            units_of.setdefault(cid, []).append(unit)
    lines: dict[UnitName, int] = {}
    for d in facts.definitions:
        if d.unit in source and "." not in d.name:  # top-level definitions; members are inside them
            lines[d.unit] = lines.get(d.unit, 0) + d.end_line - d.location.line + 1
    surface: dict[UnitName, int] = {}
    for sym in facts.symbols:
        if sym.unit in source:
            surface[sym.unit] = surface.get(sym.unit, 0) + 1 + len(sym.parameters)

    def visible(cid: ComponentId) -> list[UnitName]:
        return [*units_of.get(cid, ()), *(u for e in g[cid].exports if f"{cid}.{e}" in g for u in visible(ComponentId(f"{cid}.{e}")))]

    for cid in g.ids():
        c = g[cid]
        if parent_of(cid) is None or c.hides is None or c.publishes is not None:
            continue
        inside = sum(lines.get(u, 0) for k, us in units_of.items() if is_within(k, cid) for u in us)
        outside = sum(surface.get(u, 0) for u in visible(cid))
        if outside >= MIN_SURFACE and inside / outside < MIN_DEPTH:
            yield _finding("C016", cid, "shallow", Kind.QUESTION,
                           f"may be shallow: {inside} lines behind an interface of {outside} names and parameters, "
                           f"{inside / outside:.1f} lines each",
                           "merge it into its parent, or hide more behind a smaller interface. If it is a vocabulary the "
                           "other parts build against, say what it publishes (`publishes`)", c.location)


def _finding(rule: str, subject: str, key: str, kind: Kind, message: str, hint: str, location=None) -> Finding:
    return Finding(Subject(subject), RuleId(rule), FindingKey(key), kind, Text(message), Text(hint), location)


WIDE = 4  # a parameter type with this many public fields is wide enough to be worth narrowing


def _classes(facts: Facts) -> tuple[set[str], dict[str, int], dict[str, list]]:
    """Enum class names, public field counts per class name, and protocol classes with their methods."""
    enums, fields, protocols = set(), {}, {}
    for d in facts.definitions:
        if d.kind == "class" and "(" in d.signature:
            bases = d.signature.split("(", 1)[1]
            if "Enum" in bases:
                enums.add(d.name.rsplit(".", 1)[-1])
            if "Protocol" in bases:
                protocols[(d.unit, d.name)] = []
    for sym in facts.symbols:
        owner, _, member = sym.name.rpartition(".")
        if sym.kind == "field" and owner:
            fields[owner.rsplit(".", 1)[-1]] = fields.get(owner.rsplit(".", 1)[-1], 0) + 1
    for d in facts.definitions:
        owner, _, member = d.name.rpartition(".")
        if d.kind == "method" and (d.unit, owner) in protocols and not member.startswith("_"):
            protocols[(d.unit, owner)].append(member)
    return enums, fields, protocols


def interface_smells(ctx: Context) -> Iterator[Finding]:
    """Two signs of an interface that is harder to use than it needs to be. A parameter that picks the
    behaviour (an enum or a flag the body branches on) hides several functions inside one. A wide parameter of
    which only one field is read asks callers for more than the function needs (interface segregation)."""
    m, source = mapping_of(ctx), source_units(ctx)
    facts = ctx.facts or Facts()
    enums, fields, _ = _classes(facts)
    defs = {(d.unit, d.name): d for d in facts.definitions}
    for sym in facts.symbols:
        cid = m.component_of.get(sym.unit)
        d = defs.get((sym.unit, sym.name))
        if cid is None or d is None or sym.unit not in source or sym.kind not in ("function", "method"):
            continue
        where = f"{sym.unit}.{sym.name}"
        reads = dict(d.reads)
        for p in sym.parameters:
            leaves = {leaf.rsplit(".", 1)[-1] for leaf in p.type.leaves} if p.type else set()
            if p.name in d.branches_on and (leaves & enums or "bool" in leaves):
                yield _finding("C017", cid, f"control:{where}:{p.name}", Kind.QUESTION,
                               f"{where} picks its behaviour with `{p.name}`",
                               "consider one function per behaviour, or passing the behaviour in as a function or an "
                               "object", d.location)
            wide = [t for t in leaves if fields.get(t, 0) >= WIDE]
            used = reads.get(p.name, ())
            if wide and len(used) == 1 and p.name not in d.whole:
                yield _finding("C018", cid, f"narrow:{where}:{p.name}", Kind.QUESTION,
                               f"{where} takes a whole `{wide[0]}` as `{p.name}` but reads only `{p.name}.{used[0]}`",
                               f"take what it reads, so callers need not build a whole {wide[0]}", d.location)


def single_implementation(ctx: Context) -> Iterator[Finding]:
    """An abstraction with one implementation may be speculative: closed until a second one is needed. Python
    protocols are structural, so an implementation is any other class that defines all of its methods."""
    m, source = mapping_of(ctx), source_units(ctx)
    facts = ctx.facts or Facts()
    _, _, protocols = _classes(facts)
    methods: dict[tuple[str, str], set[str]] = {}
    for d in facts.definitions:
        owner, _, member = d.name.rpartition(".")
        if d.kind == "method" and owner:
            methods.setdefault((d.unit, owner), set()).add(member)
    for (unit, name), wanted in sorted(protocols.items()):
        cid = m.component_of.get(unit)
        if cid is None or unit not in source or not wanted:
            continue
        impls = sorted(f"{u}.{c}" for (u, c), have in methods.items() if (u, c) not in protocols and set(wanted) <= have)
        if len(impls) == 1:
            yield _finding("C019", cid, f"single:{unit}.{name}", Kind.QUESTION,
                           f"the protocol {unit}.{name} has one implementation, {impls[0]}",
                           "use the class directly until a second implementation is needed, or say in a decision why "
                           "the seam must exist now")


_DESCRIBE = ("add one line that says what the name and type cannot: its purpose, its units or invariants, where the "
             "value comes from, or what None means (for a function, its docstring; for a field, a comment on its line)")


RULES: tuple[Rule, ...] = (
    Rule(RuleId("C014"), Station.INTERFACE, Text("interface names their type does not explain have a description (C015: one that "
                                                 "says more than the name)"), descriptions),
    Rule(RuleId("C016"), Station.SOLUTION, Text("parts that hide a decision are deep"), depth),
    Rule(RuleId("C017"), Station.INTERFACE, Text("interfaces take what they use, and no parameter picks the behaviour "
                                                 "(C018: a wide parameter used for one field)"), interface_smells),
    Rule(RuleId("C019"), Station.SOLUTION, Text("an abstraction has more than one implementation"), single_implementation),
)

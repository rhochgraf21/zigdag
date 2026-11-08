"""The rules checked against the code (DESIGN2 §4.1, §4.4): one function per check kind, over the code model,
the DP tree and the relationships. A rule's findings never depend on the language the code is in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from zigdag.core.checks import data_rules, interface_rules, mutation_rules, plan_rules
from zigdag.core.checks.context import Check, Context, a_type, asked, broken
from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import (
    RETURNED,
    Crossing,
    Outcome,
    Place,
    Qualified,
    Symbol,
    SymbolKind,
    TypeExpr,
    TypeKind,
    Verdict,
)
from zigdag.core.effects import Effect, expand, phrase
from zigdag.core.findings import Finding, Result, finding
from zigdag.core.names import CheckKindName, FrName
from zigdag.core.relate import Edge, Where, classify
from zigdag.core.resolve import Level

NOT_CHECKED = "not-checked"
DECLARED_EFFECTS = "declared-effects"
CONTRACTS = "contracts"
CANT_TELL = "cant-tell"


# ---- dependencies ------------------------------------------------------------------------------------------------

def encapsulation(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Crossing into another DP goes only through names its language marks public."""
    for edge in ctx.relations.edges:
        if not ctx.in_scope(rule, edge.source) or rule.skips(ctx.tree, edge.place):
            continue
        target = edge.target_name
        unit = ctx.model.unit_of(target)
        private = []
        if unit is not None and not ctx.model.units[unit].public:
            private.append(f"module {unit}")
        rest = target[len(unit) + 1:].split(".") if unit and target != unit else []
        for i in range(1, len(rest) + 1):
            symbol = ctx.model.symbols.get(Qualified(f"{unit}.{'.'.join(rest[:i])}"))
            if symbol is not None and not symbol.public:
                private.append(symbol.name)
                break
        if private:
            yield broken(rule, str(edge.place), edge.span,
                         f"{edge.place} reaches into {edge.target} through {private[0]}, which is private "
                         f"to it", target)


def _cycles(nodes: tuple[FrName, ...], cells: Mapping[tuple[FrName, FrName], Edge]) -> list[list[FrName]]:
    """The strongly connected groups of more than one node (Tarjan)."""
    index: dict[FrName, int] = {}
    low: dict[FrName, int] = {}
    stack: list[FrName] = []
    on_stack: set[FrName] = set()
    groups: list[list[FrName]] = []

    def visit(v: FrName) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        on_stack.add(v)
        for w in nodes:
            if (v, w) in cells:
                if w not in index:
                    visit(w)
                    low[v] = min(low[v], low[w])
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            group = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                group.append(w)
                if w == v:
                    break
            if len(group) > 1:
                groups.append(sorted(group))

    for v in nodes:
        if v not in index:
            visit(v)
    return groups


def no_cycles(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    for name, dp in sorted(ctx.tree.dps.items()):
        if not dp.children or not ctx.tree.within(name, rule.on):
            continue
        order, cells = ctx.relations.matrix(ctx.tree, name)
        for group in _cycles(order, cells):
            links = [f"{a} → {b} ({cells[(a, b)].span})" for a in group for b in group if (a, b) in cells]
            yield broken(rule, name, ctx.record.frs[name].span,
                         f"siblings under {name} depend on each other in a cycle: " + "; ".join(links), *group)


def may_depend_on(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    allowed = tuple(rule.params["allow"])
    seen: set[tuple[str, str]] = set()
    for d in ctx.model.dependencies:
        source = ctx.relations.dp_of(d.source)
        if not ctx.in_scope(rule, source) or rule.skips(ctx.tree, d.source):
            continue
        target = classify(ctx.model, ctx.tree, d.target)
        if target.where is Where.STANDARD:
            continue
        if target.where is Where.PROJECT:
            if target.owner is None or ctx.tree.within(target.owner, rule.on):
                continue
            if any(ctx.tree.within(target.owner, a) for a in allowed):
                continue
            what = target.owner
        elif target.top in allowed:
            continue
        else:
            what = target.top
        if (str(source), what) not in seen:
            seen.add((str(source), what))
            yield broken(rule, str(d.source), d.span,
                         f"{d.source} depends on {what}, which {rule.name} does not allow", what)


def declared_libraries(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    declared = ctx.model.libraries.declared
    seen: set[str] = set()
    for d in ctx.model.dependencies:
        target = classify(ctx.model, ctx.tree, d.target)
        source = ctx.relations.dp_of(d.source)
        if target.where is not Where.THIRD_PARTY or not ctx.in_scope(rule, source) or target.top in seen:
            continue
        if rule.skips(ctx.tree, d.source):
            continue
        seen.add(target.top)
        if declared is None:
            yield finding(Result.QUESTION, rule.name, str(d.source), d.span,
                          f"{target.top} is imported, and no declared dependencies could be read to check it",
                          target.top)
        elif target.top not in declared and target.top.lower() not in declared:
            yield broken(rule, str(d.source), d.span, f"{target.top} is imported but not declared as a dependency",
                         target.top)


def container_boundaries(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    containers = [n for n, dp in ctx.tree.dps.items() if dp.level is Level.CONTAINER]
    for edge in ctx.relations.edges:
        a = next((c for c in containers if ctx.tree.within(edge.source, c)), None)
        b = next((c for c in containers if ctx.tree.within(edge.target, c)), None)
        if a and b and a != b and edge.is_import:
            yield broken(rule, str(edge.place), edge.span,
                         f"{edge.source} in {a} imports {edge.target} in another container, {b}")


def one_writer_per_data_store(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Data containers come from infrastructure adapters; with none described, there is nothing to share."""
    return ()


# ---- effects -----------------------------------------------------------------------------------------------------

def effects(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    allowed = expand(rule.params["allow"])
    reported: set[tuple[str, Effect]] = set()
    for place, found in sorted(ctx.relations.effects.items(), key=lambda kv: str(kv[0])):
        dp = ctx.relations.dp_of(place)
        if not ctx.in_scope(rule, dp):
            continue
        for effect, origins in sorted(found.items()):
            if effect in allowed:
                continue
            for origin in sorted(origins, key=lambda o: (str(o.place), o.span)):
                if rule.skips(ctx.tree, origin.place) or (str(origin.place), effect) in reported:
                    continue
                reported.add((str(origin.place), effect))
                inside = ctx.relations.dp_of(origin.place)
                reach = "" if ctx.in_scope(rule, inside) else f", reached from {place}"
                yield broken(rule, str(origin.place), origin.span,
                             f"{origin.place} has an effect {rule.name} does not allow: {phrase(effect)} "
                             f"(through {origin.how}){reach}", str(origin.place), effect)
    for u in ctx.model.unknowns:
        dp = ctx.relations.dp_of(u.at)
        if ctx.in_scope(rule, dp) and not rule.skips(ctx.tree, u.at):
            yield finding(Result.QUESTION, CANT_TELL, str(u.at), u.span,
                          f"{rule.name} applies here, and what {u.what} does cannot be read", u.what)
    if not allowed:
        yield from _replays(ctx, rule)


def _replays(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Code that may have no effects gives the same result when called again with the same arguments (§4.5)."""
    for r in ctx.observed.replays:
        if not ctx.in_scope(rule, ctx.relations.dp_of(r.at)) or rule.skips(ctx.tree, r.at):
            continue
        if r.verdict is Verdict.DIFFERENT:
            yield broken(rule, str(r.at), r.span, f"{r.at} may have no effects, yet {r.detail} with a copy of the "
                         f"same arguments: its result depends on something else", r.detail)
        elif r.verdict is Verdict.NOT_COPYABLE:
            yield asked(rule, str(r.at), r.span, f"{r.at} could not be called again to see that its result depends "
                        f"only on its arguments: {r.detail}", r.detail)


def declared_effects(ctx: Context) -> Iterable[Finding]:
    """Always on: every @deal.has / @deal.pure declaration covers the effects found (§3)."""
    for symbol in ctx.model.symbols.values():
        if symbol.declared_effects is None:
            continue
        found = ctx.relations.effects.get(Place(symbol.unit, symbol.name), {})
        declared = expand(symbol.declared_effects)
        for effect in sorted(set(found) - declared):
            origin = min(found[effect], key=lambda o: o.span)
            yield finding(Result.BREAKS, DECLARED_EFFECTS, symbol.qualified, origin.span,
                          f"{symbol.qualified} declares its effects, but also has {phrase(effect)} "
                          f"(through {origin.how} in {origin.place})", effect)


def contracts(ctx: Context) -> Iterable[Finding]:
    """Always on: every contract holds on the inputs generated for it while the tests ran (§4.5)."""
    for c in ctx.observed.cases:
        if c.outcome is Outcome.FAILED:
            yield finding(Result.BREAKS, CONTRACTS, str(c.at), c.span, f"{c.at} breaks its own contract on generated "
                          f"inputs: {c.detail}", c.detail)
        elif c.outcome is Outcome.ERROR:
            yield finding(Result.QUESTION, CONTRACTS, str(c.at), c.span, f"{c.at} has a contract that was not run on "
                          f"generated inputs: {c.detail}", c.detail)


# ---- interfaces --------------------------------------------------------------------------------------------------

def _leaves(t: TypeExpr) -> list[TypeExpr]:
    if t.kind in (TypeKind.CONTAINER, TypeKind.UNION):
        return [leaf for a in t.args for leaf in _leaves(a)]
    if t.kind is TypeKind.REF and t.args:
        return [TypeExpr(TypeKind.REF, t.text, t.name), *(leaf for a in t.args for leaf in _leaves(a))]
    return [t]


def _leaf_problem(ctx: Context, leaf: TypeExpr, returned: bool, bool_returns: bool) -> tuple[Result, str] | None:
    if leaf.kind in (TypeKind.NONE, TypeKind.LITERAL):
        return None
    if leaf.kind is TypeKind.BOOL:
        return None if returned and bool_returns else (Result.BREAKS, f"{leaf.text} is not project-defined")
    if leaf.kind in (TypeKind.ANY, TypeKind.UNKNOWN):
        return Result.QUESTION, f"{leaf.text} cannot be checked"
    if leaf.kind is TypeKind.CONTAINER:  # a bare container, such as list, with nothing inside
        return Result.BREAKS, f"{leaf.text} says nothing about what it holds"
    symbol = ctx.model.symbols.get(leaf.name) if leaf.name else None
    if symbol is None:
        return Result.BREAKS, f"{leaf.text} is not defined by the project: name it first"
    if symbol.kind is SymbolKind.NAMED_TYPE:
        return None
    if symbol.kind is SymbolKind.CLASS:
        if symbol.qualified in ctx.tree.type_owner:
            return None
        return Result.BREAKS, f"{leaf.text} is a project class that is not a recorded structure"
    return Result.QUESTION, f"{leaf.text} is a {symbol.kind.value}, not a type"


def _signature_types(ctx: Context, symbol: Symbol) -> list[tuple[str, TypeExpr | None, bool]]:
    """(where, type, whether it is returned) for everything a use of the symbol passes across the edge."""
    out: list[tuple[str, TypeExpr | None, bool]] = []
    targets = [symbol] if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD) else []
    if symbol.kind is SymbolKind.CLASS:
        targets = ctx.model.members_of(symbol)
        out += [(f"field {f.name}", f.type, False) for f in symbol.fields if not f.name.startswith("_")]
    for s in targets:
        if s.signature is None:
            continue
        out += [(f"{s.name}({p.name})", p.type, False) for p in s.signature.params]
        if not s.name.endswith("__init__"):
            out.append((f"{s.name} returns", s.signature.returns, True))
    return out


def edge_types(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    bool_returns = rule.params["bool-returns"] == "allowed"
    for name, span in sorted(ctx.used_from_other_dps(rule).items()):
        symbol = ctx.model.symbols[name]
        if rule.skips(ctx.tree, name):
            continue
        breaks, questions = [], []
        for where, t, returned in _signature_types(ctx, symbol):
            if t is None:
                questions.append(f"{where} has no type")
                continue
            for leaf in _leaves(t):
                problem = _leaf_problem(ctx, leaf, returned, bool_returns)
                if problem:
                    (breaks if problem[0] is Result.BREAKS else questions).append(f"{where}: {problem[1]}")
        owner = ctx.tree.owner(name)
        if breaks:
            yield broken(rule, name, symbol.span, f"{name} is used outside {owner}, and passes types the project "
                         f"does not define: " + "; ".join(sorted(set(breaks))), *sorted(set(breaks)))
        if questions:
            yield finding(Result.QUESTION, rule.name, name, symbol.span,
                          f"{name} is used outside {owner}, and some of what it passes cannot be checked: "
                          + "; ".join(sorted(set(questions))), *sorted(set(questions)))
    for c in ctx.observed.crossings:
        operation = Qualified(str(c.at))
        if not ctx.in_scope(rule, ctx.relations.dp_of(c.at)) or rule.skips(ctx.tree, operation):
            continue
        if (problem := _crossing_problem(ctx, c, bool_returns)) is not None:
            yield broken(rule, operation, c.span, f"{_crossed(c)}, {problem} (seen while {c.seen} ran)",
                         c.where, c.actual)


def _crossed(c: Crossing) -> str:
    return f"{c.at} returned {a_type(c.actual)}" if c.where == RETURNED else f"{c.at} was given {a_type(c.actual)} " \
        f"for {c.where}"


_NONE_TYPE = Qualified("builtins.NoneType")
_BOOL_TYPE = Qualified("builtins.bool")


def _crossing_problem(ctx: Context, c: Crossing, bool_returns: bool) -> str | None:
    """What is wrong with a value seen crossing a boundary: it does not fit its annotation, or it has no
    annotation and its type is not the project's own."""
    if not c.conforms:
        return f"which its annotation, {c.expected}, does not allow"
    if c.actual == _NONE_TYPE or c.actual in ctx.model.symbols or (bool_returns and c.where == RETURNED
                                                                     and c.actual == _BOOL_TYPE):
        return None
    what = "its annotation, " + c.expected + "," if c.expected else "no annotation"
    return f"and {what} lets through {a_type(c.actual)}, a type the project does not define"


def declared_errors(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    raised: dict[Place, list] = {}
    for r in ctx.model.raises:
        if not r.caught:
            raised.setdefault(r.at, []).append(r)
    for name, _ in sorted(ctx.used_from_other_dps(rule).items()):
        symbol = ctx.model.symbols[name]
        operations = [symbol] if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD) else (
            ctx.model.members_of(symbol) if symbol.kind is SymbolKind.CLASS else [])
        for op in operations:
            if rule.skips(ctx.tree, op.qualified):
                continue
            declared = {t.name for t in op.declared_errors or () if t.name}
            for r in raised.get(Place(op.unit, op.name), ()):
                if r.error.kind is not TypeKind.REF or r.error.name is None:
                    yield finding(Result.QUESTION, rule.name, op.qualified, r.span,
                                  f"{op.qualified} raises {r.error.text}, which cannot be read", r.error.text)
                elif r.error.name not in ctx.model.symbols:
                    yield broken(rule, op.qualified, r.span, f"{op.qualified} is used across a boundary and raises "
                                 f"{r.error.text}, which is not a project-defined error", r.error.text)
                elif r.error.name not in declared:
                    yield broken(rule, op.qualified, r.span, f"{op.qualified} is used across a boundary and raises "
                                 f"{r.error.text} without declaring it (@deal.raises)", r.error.text)
    for e in ctx.observed.escapes:
        operation = Qualified(str(e.at))
        if not ctx.in_scope(rule, ctx.relations.dp_of(e.at)) or rule.skips(ctx.tree, operation):
            continue
        symbol = ctx.model.symbols.get(operation)
        declared = {t.name for t in (symbol.declared_errors or ()) if t.name} if symbol else set()
        seen = f"{a_type(e.error)} left {operation} for another design parameter while {e.seen} ran"
        if e.error not in ctx.model.symbols:
            yield broken(rule, operation, e.span, f"{seen}, and it is not a project-defined error", e.error)
        elif e.error not in declared:
            yield broken(rule, operation, e.span, f"{seen}, and {operation} does not declare it (@deal.raises)",
                         e.error)


def _describes(description: str, name: str) -> bool:
    """A guess: the description says something beyond the words of the name."""
    words = {w.lower().strip(".,:;") for w in description.split()}
    name_words = {w.lower() for w in name.replace(".", "_").split("_")} | {"the", "a", "an", "of", "returns", "return"}
    return bool(words - name_words)


def described_names(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    for name, _ in sorted(ctx.used_from_other_dps(rule).items()):
        symbol = ctx.model.symbols[name]
        if rule.skips(ctx.tree, name):
            continue
        if not symbol.description:
            yield broken(rule, name, symbol.span,
                         f"{name} is used outside {ctx.tree.owner(name)} and has no one-line description")
        elif not _describes(symbol.description, symbol.name.split(".")[-1]):
            yield finding(Result.QUESTION, rule.name, name, symbol.span,
                          f'the description of {name}, "{symbol.description}", only repeats its name',
                          symbol.description)


def max_lines(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    limits = {SymbolKind.FUNCTION: rule.params["function"], SymbolKind.METHOD: rule.params["function"],
              SymbolKind.CLASS: rule.params["class"]}
    for name, symbol in sorted(ctx.model.symbols.items()):
        limit = limits.get(symbol.kind)
        if limit is None or symbol.size <= limit or rule.skips(ctx.tree, name):
            continue
        if ctx.in_scope(rule, ctx.tree.owner(name)):
            yield broken(rule, name, symbol.span, f"{name} is {symbol.size} lines; at most {limit}",
                         str(symbol.size))


CHECKS: Mapping[CheckKindName, Check] = {
    CheckKindName("encapsulation"): encapsulation,
    CheckKindName("no-cycles"): no_cycles,
    CheckKindName("may-depend-on"): may_depend_on,
    CheckKindName("declared-libraries"): declared_libraries,
    CheckKindName("container-boundaries"): container_boundaries,
    CheckKindName("one-writer-per-data-store"): one_writer_per_data_store,
    CheckKindName("effects"): effects,
    CheckKindName("edge-types"): edge_types,
    CheckKindName("declared-errors"): declared_errors,
    CheckKindName("described-names"): described_names,
    CheckKindName("max-lines"): max_lines,
    **data_rules.CHECKS,
    **interface_rules.CHECKS,
    **mutation_rules.CHECKS,
    **plan_rules.CHECKS,
}

# Kinds that need only the record, and are checked with it.
RECORD_KINDS = frozenset({CheckKindName("max-children")})


def check_code(ctx: Context, rules: list[RuleUse], supplied_kinds: frozenset[CheckKindName]) -> list[Finding]:
    """Every rule whose kind this version checks; one question naming the rest that the adapters could feed."""
    out: list[Finding] = [*declared_effects(ctx), *contracts(ctx)]
    unchecked = []
    for rule in rules:
        check = CHECKS.get(rule.kind)
        if check is not None:
            try:
                out += check(ctx, rule)
            except Exception as e:  # noqa: BLE001 (principle 6: a check that fails to run breaks, never skipped)
                out.append(finding(Result.BREAKS, rule.name, rule.on, rule.span,
                                   f"the {rule.kind} check failed to run ({type(e).__name__}: {e}): a zigdag bug"))
        elif rule.kind not in RECORD_KINDS and rule.kind in supplied_kinds:
            unchecked.append(rule.name)
    if unchecked:
        out.append(finding(Result.QUESTION, NOT_CHECKED, "zigdag", None,
                           "this version of zigdag does not check these rules yet: " + ", ".join(sorted(unchecked)),
                           *sorted(unchecked)))
    return out


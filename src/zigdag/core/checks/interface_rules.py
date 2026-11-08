"""The interface checks (DESIGN2 §4.1): deep components, parameters that pick a mode or carry more than is used,
and abstractions with one implementation. All of them are guesses, so each failure is a question.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

from zigdag.core.checks.context import Check, Context, a_type, asked, short_name
from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import CONSTRUCTOR, CONSTRUCTOR_NAME, Abstraction, CodeModel, Param, Qualified, Symbol, SymbolKind, TypeExpr, \
    TypeKind
from zigdag.core.findings import Finding
from zigdag.core.names import CheckKindName, CodePath
from zigdag.core.resolve import Level

_OPERATIONS = (SymbolKind.FUNCTION, SymbolKind.METHOD)
_DUNDER = "__"
_PRIVATE = "_"


# ---- min-depth ---------------------------------------------------------------------------------------------------

def _interface(model: CodeModel, symbols: list[Symbol]) -> Iterator[str]:
    """The interface of a unit's symbols, one element at a time: each public name, each parameter of a public
    function or method (a public class's constructor included), and each public field of a public class."""
    for s in symbols:
        constructor = s.kind is SymbolKind.METHOD and s.name.endswith(CONSTRUCTOR) and _class_public(model, s)
        if s.public:
            yield s.qualified
        if (s.public or constructor) and s.signature is not None:
            yield from (f"{s.qualified}({p.name})" for p in s.signature.params)
        if s.public and s.kind is SymbolKind.CLASS:
            yield from (f"{s.qualified}.{f.name}" for f in s.fields if not f.name.startswith(_PRIVATE))


def _class_public(model: CodeModel, method: Symbol) -> bool:
    owner = model.symbols.get(Qualified(method.qualified.rpartition(".")[0]))
    return owner is not None and owner.public


def min_depth(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Each component hides enough code behind each element of its interface."""
    ratio = rule.params["ratio"]
    by_unit: dict[CodePath, list[Symbol]] = {}
    for s in ctx.model.symbols.values():
        by_unit.setdefault(s.unit, []).append(s)
    for name, dp in sorted(ctx.tree.dps.items()):
        if dp.level is not Level.COMPONENT or not ctx.in_scope(rule, name):
            continue
        units = [ctx.model.units[u] for u, owner in sorted(ctx.tree.unit_owner.items())
                 if owner == name and u in ctx.model.units and not rule.skips(ctx.tree, u)]
        interface = sorted({e for u in units for e in _interface(ctx.model, by_unit.get(u.path, []))})
        lines = sum(u.size for u in units)
        if interface and lines / len(interface) < ratio:
            yield asked(rule, name, units[0].span,
                        f"{name} has {lines} lines of code behind {len(interface)} names and parameters in its "
                        f"interface: {lines / len(interface):.1f} lines each, where {ratio:g} are asked for",
                        *interface)


# ---- parameters --------------------------------------------------------------------------------------------------

def _operations(ctx: Context, rule: RuleUse) -> Iterator[Symbol]:
    """The functions and methods another DP uses: used directly, or exposed by a class it uses."""
    for name, _ in sorted(ctx.used_from_other_dps(rule).items()):
        symbol = ctx.model.symbols[name]
        for s in [symbol] if symbol.kind in _OPERATIONS else ctx.model.members_of(symbol):
            if s.signature is not None and not rule.skips(ctx.tree, s.qualified):
                yield s


def _alone(t: TypeExpr) -> TypeExpr:
    """The one type an optional parameter holds when it holds something: bool for bool | None."""
    if t.kind is TypeKind.UNION:
        others = [a for a in t.args if a.kind is not TypeKind.NONE]
        return others[0] if len(others) == 1 else t
    return t


def _picks(model: CodeModel, t: TypeExpr | None) -> bool:
    """Whether a type is one a mode is picked by: a bool, a literal, or a project enumeration."""
    if t is None:
        return False
    alone = _alone(t)
    if alone.kind in (TypeKind.BOOL, TypeKind.LITERAL):
        return True
    symbol = model.symbols.get(alone.name) if alone.kind is TypeKind.REF and alone.name else None
    return symbol is not None and symbol.kind is SymbolKind.CLASS and bool(symbol.members)


def no_mode_parameters(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """No function another DP uses picks its behaviour by a parameter."""
    for s in _operations(ctx, rule):
        for p in s.signature.params:
            if p.branched_on and _picks(ctx.model, p.type):
                yield asked(rule, s.qualified, p.span,
                            f"{s.qualified} picks what it does by its {p.name} parameter ({p.type.text}), so it is "
                            f"two functions under one name", p.name, p.type.text)


def _carried(model: CodeModel, p: Param) -> tuple[Symbol, str] | None:
    """The class a parameter carries and the one field of it the function reads, when that is all it reads."""
    if p.used_whole or len(p.fields_read) != 1 or p.type is None:
        return None
    named = _alone(p.type).named
    cls = model.symbols.get(named) if named else None
    field = p.fields_read[0]
    if cls is None or cls.kind is not SymbolKind.CLASS or len(cls.fields) < 2 or cls.field(field) is None:
        return None
    return cls, field


def narrow_parameters(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """No function another DP uses takes a whole class to read one field of it."""
    for s in _operations(ctx, rule):
        for p in s.signature.params:
            carried = _carried(ctx.model, p)
            if carried is not None:
                cls, field = carried
                yield asked(rule, s.qualified, p.span,
                            f"{s.qualified} reads only {p.name}.{field} of {a_type(cls.qualified)}: it could take "
                            f"the {field} instead", p.name, cls.qualified, field)


# ---- abstractions ------------------------------------------------------------------------------------------------

def _ancestors(model: CodeModel, cls: Symbol) -> set[Qualified]:
    """The project classes a class names as bases, directly or through other classes."""
    seen: set[Qualified] = set()
    todo = [b.name for b in cls.bases if b.name]
    while todo:
        name = todo.pop()
        base = model.symbols.get(name)
        if name in seen or base is None or base.kind is not SymbolKind.CLASS:
            continue
        seen.add(name)
        todo += [b.name for b in base.bases if b.name]
    return seen


def _protocol_members(model: CodeModel, protocol: Symbol) -> set[str]:
    """What a class must define to have a protocol's shape: its public methods, special methods and fields."""
    prefix = f"{protocol.qualified}."
    methods = {q[len(prefix):] for q, s in model.symbols.items() if q.startswith(prefix) and s.kind is SymbolKind.METHOD
               and "." not in q[len(prefix):]}
    kept = {m for m in methods if not m.startswith(_PRIVATE) or (m.startswith(_DUNDER) and m.endswith(_DUNDER)
                                                                  and m != CONSTRUCTOR_NAME)}
    return kept | {f.name for f in protocol.fields if not f.name.startswith(_PRIVATE)}


def _defines(model: CodeModel, cls: Symbol, member: str) -> bool:
    for owner in (cls.qualified, *_ancestors(model, cls)):
        holder = model.symbols.get(Qualified(owner))
        if Qualified(f"{owner}.{member}") in model.symbols or (holder is not None and holder.field(member)):
            return True
    return False


def _implements(model: CodeModel, cls: Symbol, abstraction: Symbol, members: set[str]) -> bool:
    if abstraction.qualified in _ancestors(model, cls):
        return True
    return abstraction.abstraction is Abstraction.PROTOCOL and bool(members) and all(
        _defines(model, cls, m) for m in members)


def no_single_implementations(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """No protocol or abstract base class has exactly one implementation."""
    classes: Mapping[Qualified, Symbol] = {q: s for q, s in sorted(ctx.model.symbols.items())
                                           if s.kind is SymbolKind.CLASS}
    for name, abstraction in classes.items():
        if abstraction.abstraction is None or rule.skips(ctx.tree, name) or not ctx.in_scope(
                rule, ctx.tree.owner(name)):
            continue
        members = _protocol_members(ctx.model, abstraction)
        implementations = [q for q, s in classes.items()
                           if s.abstraction is None and _implements(ctx.model, s, abstraction, members)]
        if len(implementations) == 1:
            yield asked(rule, name, abstraction.span,
                        f"{name} is {abstraction.abstraction.with_article} with one implementation, "
                        f"{short_name(implementations[0])}: the abstraction adds a name without hiding a choice",
                        implementations[0])


CHECKS: Mapping[CheckKindName, Check] = {
    CheckKindName("min-depth"): min_depth,
    CheckKindName("no-mode-parameters"): no_mode_parameters,
    CheckKindName("narrow-parameters"): narrow_parameters,
    CheckKindName("no-single-implementations"): no_single_implementations,
}

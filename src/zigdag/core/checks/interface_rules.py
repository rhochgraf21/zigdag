"""The interface checks (DESIGN2 §4.1): parameters that pick a mode or carry more than is used, and abstractions
with one implementation. All of them are guesses, so each failure is a question.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

from zigdag.core.checks.context import Check, Context, a_type, asked, broken, short_name
from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import CONSTRUCTOR_NAME, Abstraction, CodeModel, Param, Qualified, Symbol, SymbolKind, TypeExpr, \
    TypeKind
from zigdag.core.findings import Finding
from zigdag.core.names import CheckKindName

_OPERATIONS = (SymbolKind.FUNCTION, SymbolKind.METHOD)
_DUNDER = "__"
_PRIVATE = "_"


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


# ---- contracts at interfaces --------------------------------------------------------------------------------------

def _offered(ctx: Context, rule: RuleUse) -> dict[Qualified, str]:
    """Each pure function an interface offers, with who relies on it: another DP that uses it, or a function with
    effects that calls it."""
    out: dict[Qualified, str] = {}
    for s in _operations(ctx, rule):
        if s.qualified in ctx.declared_pure:
            out.setdefault(s.qualified, f"used outside {ctx.tree.owner(s.qualified)}")
    for c in sorted(ctx.model.calls, key=lambda c: (str(c.caller), c.callee)):
        caller = Qualified(str(c.caller))
        callee = ctx.model.symbols.get(c.callee)
        if callee is None or c.caller.symbol is None or caller in ctx.declared_pure or rule.skips(ctx.tree, c.callee):
            continue
        if callee.qualified in ctx.declared_pure and ctx.in_scope(rule, ctx.tree.owner(callee.qualified)):
            out.setdefault(callee.qualified, f"called by {caller}, which has effects")
    return out


def _contracted(model: CodeModel, function: Symbol) -> bool:
    """Whether a function states what it promises: a contract of its own, or an invariant of its class."""
    owner = model.symbols.get(Qualified(function.qualified.rpartition(".")[0]))
    return function.contract or (owner is not None and owner.kind is SymbolKind.CLASS and owner.contract)


def contracted_interfaces(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Each pure function an interface offers has a contract."""
    for name, relied in sorted(_offered(ctx, rule).items()):
        function = ctx.model.symbols[name]
        if not _contracted(ctx.model, function):
            yield broken(rule, name, function.span, f"{name} is {relied}, but states no contract: say what it "
                         f"promises (@deal.post, @deal.ensure), so its callers can rely on it and its mutants are "
                         f"judged by it")


CHECKS: Mapping[CheckKindName, Check] = {
    CheckKindName("narrow-parameters"): narrow_parameters,
    CheckKindName("no-single-implementations"): no_single_implementations,
    CheckKindName("contracted-interfaces"): contracted_interfaces,
}

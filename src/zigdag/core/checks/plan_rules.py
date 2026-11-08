"""planned-effects (DESIGN2 §4.1): decisions belong in pure code, where contracts and mutants check them, and code with
effects only carries them out. In each function that is not declared pure, every condition must be a plan value, every
argument of every call a plan value or the function's own parameter, and nothing may be worked out. A plan value is a
constant, what a declared-pure function returns, a parameter of a type such a function returns, or anything read,
formatted or built from those.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from zigdag.core.checks.context import Check, Context, asked, broken
from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import CONSTRUCTOR, Need, Place, PlannedUse, Qualified, Source, SymbolKind, ValueSource
from zigdag.core.findings import Finding
from zigdag.core.kinds.registry import PLANNED_EFFECTS
from zigdag.core.names import CheckKindName

_SHOWN = 60  # characters of an expression shown in a finding
_A_CALL = "a call"  # what a callee that cannot be named is called


def _shown(text: str) -> str:
    return text if len(text) <= _SHOWN else f"{text[:_SHOWN - 1]}…"


def _callee(ctx: Context, call: ValueSource) -> Qualified | None:
    """Who a call calls: its name as written, or its method on the type of its receiver."""
    if call.name is not None:
        return call.name
    owner = ctx.model.type_of(call.receiver) if call.receiver is not None else None
    return Qualified(f"{owner}.{call.method}") if owner is not None and call.method else None


def _builds(ctx: Context, callee: Qualified | None) -> bool:
    """Whether a call only builds a value from what it is given: a project structure whose constructor is not written
    or is declared pure, or a named type."""
    symbol = ctx.model.symbols.get(callee) if callee is not None else None
    if symbol is None or symbol.kind not in (SymbolKind.CLASS, SymbolKind.NAMED_TYPE):
        return False
    constructor = Qualified(f"{callee}{CONSTRUCTOR}")
    return constructor not in ctx.model.symbols or constructor in ctx.declared_pure


class _Plans:
    """Which values are plan values, given the functions declared pure."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        returns = (ctx.model.symbols[q].signature for q in ctx.declared_pure)
        self.types = frozenset(s.returns.named for s in returns if s is not None and s.returns and s.returns.named)

    def source(self, s: ValueSource, need: Need) -> bool | None:
        """Whether a source gives what a use needs, None when it cannot be told: a plan value, or, for an argument,
        also one of the function's own parameters, which passing on decides nothing."""
        if s.kind is Source.CONSTANT:
            return True
        if s.kind is Source.PARAMETER:
            return need is Need.ARGUMENT or s.name in self.types
        if s.kind is Source.BUILT:
            return self.all(s.built_from, need)
        if s.kind is Source.CALL:
            callee = _callee(self.ctx, s)
            if callee in self.ctx.declared_pure:
                return True
            return self.all(s.built_from, need) if _builds(self.ctx, callee) else False
        if s.kind is Source.UNKNOWN:
            return None
        return False  # worked out in place

    def all(self, sources: Iterable[ValueSource], need: Need) -> bool | None:
        found = [self.source(s, need) for s in sources]
        if False in found:
            return False
        return None if None in found else True


def _given_freely(ctx: Context, call: ValueSource) -> bool:
    """Whether a call may be given anything: a pure function, since deciding is its job; or one that only builds a
    value, whose value is then judged where it is used."""
    callee = _callee(ctx, call)
    return call.kind is Source.BUILT or callee in ctx.declared_pure or _builds(ctx, callee)


def _covered(ctx: Context, rule: RuleUse, place: Place) -> bool:
    name = Qualified(str(place))
    return name not in ctx.declared_pure and ctx.in_scope(rule, ctx.tree.owner_of(place)) and not rule.skips(
        ctx.tree, name)


def _said(ctx: Context, u: PlannedUse) -> str:
    """What a use that is not a plan value does, and what to do about it."""
    text = _shown(u.text)
    if u.need is Need.CONDITION:
        return f"{u.at} branches on `{text}`, which is not a plan value: decide it in a pure function, and branch on " \
               f"its result"
    callee = (_callee(ctx, u.call) if u.call is not None else None) or _A_CALL
    return f"{u.at} passes `{text}` to {callee}, and it is neither a plan value nor its own parameter: hand it to a " \
           f"pure function, and pass what that function returns"


def planned_effects(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Every function not declared pure passes on and branches on only what pure code decided, and works out
    nothing itself."""
    plans = _Plans(ctx)
    for c in ctx.model.computations:
        if _covered(ctx, rule, c.at):
            yield broken(rule, str(c.at), c.span, f"{c.at} works out `{_shown(c.text)}` in code with effects: work "
                         f"it out in a pure function, and use its result", c.text)
    for u in ctx.model.planned_uses:
        if not _covered(ctx, rule, u.at) or any(s.kind is Source.WORKED_OUT for s in u.sources):
            continue  # what is worked out in place is reported where it is worked out
        if u.need is Need.ARGUMENT and u.call is not None and _given_freely(ctx, u.call):
            continue
        planned = plans.all(u.sources, u.need)
        if planned is None:
            yield asked(rule, str(u.at), u.span, f"{u.at} uses `{_shown(u.text)}`, whose source cannot be traced, so "
                        f"whether it is a plan value is unknown", u.text)
        elif not planned:
            yield broken(rule, str(u.at), u.span, _said(ctx, u), u.text)


CHECKS: Mapping[CheckKindName, Check] = {PLANNED_EFFECTS: planned_effects}

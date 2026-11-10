"""The rules checked against the data model (DESIGN2 §2.4, §4.1): who may change a structure, what references must
point at, how representations must agree, where protected values may become text, and which states and features a
statement may name.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import deal

from zigdag.core.checks.context import Check, Context, a_type, asked, broken, short_name
from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import AccessKind, CodeModel, Place, Qualified, SymbolKind, UseKind
from zigdag.core.data import DataModel, RelationKind, Structure, choices, is_flag, shape
from zigdag.core.effects import expand, phrase
from zigdag.core.findings import Finding, Result, Span, finding
from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.sentences import DataClause, parse_ears
from zigdag.core.names import CheckKindName, FrName
from zigdag.core.record.model import Record, Sentence

STATE = "ears.state"
FEATURE = "ears.feature"
_CHANGES = (AccessKind.UPDATES, AccessKind.DELETES)




def _what(s: Structure, field: str | None) -> str:
    return s.primary.name + (f".{field}" if field else "")


# ---- ownership and references ------------------------------------------------------------------------------------

def data_ownership(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Only a structure's own component changes it. A change seen while tests ran breaks; one read from Python
    code, whose types the language does not enforce, is a question."""
    seen: set[tuple[str, str, str | None]] = set()
    changes = sorted((a for a in ctx.data.accesses if a.kind in _CHANGES),
                     key=lambda a: (a.seen is None, str(a.place), a.structure, a.field or "", a.span))
    for a in changes:
        s = ctx.data.structures[a.structure]
        if s.owner is None or ctx.tree.within(a.dp, s.owner) or not ctx.in_scope(rule, a.dp):
            continue
        if rule.skips(ctx.tree, a.place) or (str(a.place), a.structure, a.field) in seen:
            continue
        seen.add((str(a.place), a.structure, a.field))
        how = " in place" if a.in_place else ""
        if a.seen is not None:
            yield broken(rule, str(a.place), a.span, f"{a.place} changed {_what(s, a.field)}{how} while {a.seen} ran; "
                         f"only {s.owner} may change {s.dp}", a.structure, a.field or "")
        else:
            yield asked(rule, str(a.place), a.span, f"{a.place} may change {_what(s, a.field)}{how}; only {s.owner} "
                        f"may change {s.dp}", a.structure, a.field or "")


def references_resolve(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    for r in ctx.data.relations:
        if r.kind is not RelationKind.REFERS_TO or r.target is not None or not ctx.in_scope(rule, r.source):
            continue
        s = ctx.data.structures[r.source]
        if rule.skips(ctx.tree, s.primary.qualified):
            continue
        yield broken(rule, r.source, r.field.span, f"{_what(s, r.field.name)} refers to {a_type(r.target_type)} by "
                     f"its identity, and {r.target_type} is not a recorded structure: give it a DP", r.target_type)


# ---- representations ---------------------------------------------------------------------------------------------

def _plain(name: str) -> str:
    """A field's name compared across languages: order_id, orderId and OrderID are one name."""
    return name.replace("_", "").lower()


def representations_agree(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    for dp, s in sorted(ctx.data.structures.items()):
        if len(s.representations) < 2 or not ctx.in_scope(rule, dp):
            continue
        first, *others = sorted(s.representations)
        base = {_plain(f.name): f for f in s.representations[first].fields}
        for adapter in others:
            mine = {_plain(f.name): f for f in s.representations[adapter].fields}
            differences = [f"{base[n].name} is in {first} but not in {adapter}" for n in sorted(set(base) - set(mine))]
            differences += [f"{mine[n].name} is in {adapter} but not in {first}" for n in sorted(set(mine) - set(base))]
            for n in sorted(set(base) & set(mine)):
                (a_type, a_card), (b_type, b_card) = shape(base[n].type), shape(mine[n].type)
                if a_card is not b_card:
                    differences.append(f"{base[n].name} is {a_card.value} in {first} and {b_card.value} in {adapter}")
                a_held, b_held = ctx.data.structure_of(a_type), ctx.data.structure_of(b_type)
                if (a_held or b_held) and a_held != b_held:
                    differences.append(f"{base[n].name} holds {a_held.dp if a_held else a_type} in {first} and "
                                       f"{b_held.dp if b_held else b_type} in {adapter}")
                elif a_type and b_type and not a_held and short_name(a_type) != short_name(b_type):
                    differences.append(f"{base[n].name} is a {short_name(a_type)} in {first} and a {short_name(b_type)} in "
                                       f"{adapter}")
            if differences:
                yield broken(rule, dp, s.span, f"the representations of {dp} disagree: " + "; ".join(differences),
                             *differences)


# ---- access ------------------------------------------------------------------------------------------------------

def access_sanity(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """A guess: stored data that is written and never read, or read and never written, is likely a mistake."""
    for dp, s in sorted(ctx.data.structures.items()):
        if not s.stored or not ctx.in_scope(rule, dp):
            continue
        kinds = {a.kind for a in ctx.data.accesses if a.structure == dp}
        if AccessKind.CREATES in kinds and AccessKind.READS not in kinds:
            yield asked(rule, dp, s.span, f"{dp} is stored and created, but no code reads it")
        elif AccessKind.READS in kinds and AccessKind.CREATES not in kinds:
            yield asked(rule, dp, s.span, f"{dp} is stored and read, but no code creates it")


def messages_agree(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Queues are containers, which come from infrastructure adapters. With none described there are no messages."""
    return ()


def endpoints_agree(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Endpoints belong to containers, which come from infrastructure adapters. With none described there are no
    requests between containers."""
    return ()


# ---- data flow ---------------------------------------------------------------------------------------------------

@deal.ensure(lambda ctx, rule, result: all(q in ctx.model.symbols for q in result[0]))
@deal.ensure(lambda ctx, rule, result: all(p.result is Result.BREAKS for p in result[1]))
def protected_types(ctx: Context, rule: RuleUse) -> tuple[frozenset[Qualified], list[Finding]]:
    """The types a data-flow rule protects: recorded structures by DP name, or named types by code name."""
    out: set[Qualified] = set()
    problems = []
    bases = ctx.tree.code_base(rule.on)
    for name in rule.params["data"]:
        s = ctx.data.structures.get(name)
        if s is not None:
            out |= {rep.qualified for rep in s.representations.values()}
            continue
        candidates = [Qualified(f"{b}.{name}") for b in bases] + [Qualified(name)]
        found = next((q for q in candidates if (sym := ctx.model.symbols.get(q)) is not None
                      and sym.kind in (SymbolKind.CLASS, SymbolKind.NAMED_TYPE)), None)
        if found is None:
            problems.append(broken(rule, rule.name, rule.span, f'"{name}" under data names no structure or named type',
                                   name))
        else:
            out.add(found)
    return frozenset(out), problems


def _home(ctx: Context, type_name: Qualified) -> FrName | None:
    """The component a protected type belongs to: the only code that may make it into text."""
    s = ctx.data.structure_of(type_name)
    if s is not None:
        return s.owner
    unit = ctx.model.unit_of(type_name)
    return ctx.tree.owner(unit) if unit is not None else None


def data_flow(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    protected, problems = protected_types(ctx, rule)
    yield from problems
    if not protected:
        return
    held = ctx.data.holding(protected)
    never = expand(rule.params["never-reaches"])
    unknown: dict[Place, list[str]] = {}
    for vu in ctx.data.uses:
        u = vu.use
        if not ctx.in_scope(rule, vu.dp) or rule.skips(ctx.tree, u.at):
            continue
        reaches = u.kind is UseKind.EFFECT and u.effect is not None and u.effect in never
        if vu.unknown and (reaches or u.kind is UseKind.RELEASE):
            unknown.setdefault(u.at, []).append(u.via)
        elif u.kind is UseKind.RELEASE and vu.type in protected:
            home = _home(ctx, vu.type)
            if home is None or not ctx.tree.within(vu.dp, home):
                yield broken(rule, str(u.at), u.span, f"{u.at} makes {a_type(vu.type)} into text ({u.via}); only "
                             f"{home} may, unless the place is listed under except", vu.type, u.via)
        elif reaches and vu.type in held:
            yield broken(rule, str(u.at), u.span, f"{u.at} passes {a_type(vu.type)} straight to {u.via}, which is "
                         f"{phrase(u.effect)}", vu.type, u.via)
    for a in ctx.model.accesses:  # reading the plain value out of a distinct named type
        type_name = ctx.model.type_of(a.value)
        symbol = ctx.model.symbols.get(type_name) if type_name in protected else None
        dp = ctx.relations.dp_of(a.at)
        if symbol is None or symbol.kind is not SymbolKind.NAMED_TYPE or not ctx.in_scope(rule, dp):
            continue
        home = _home(ctx, type_name)
        if not rule.skips(ctx.tree, a.at) and (home is None or not ctx.tree.within(dp, home)):
            yield broken(rule, str(a.at), a.span, f"{a.at} reads the text out of {a_type(type_name)} (.{a.field}); "
                         f"only {home} may", type_name, a.field or "")
    for place, vias in sorted(unknown.items(), key=lambda kv: str(kv[0])):
        yield asked(rule, str(place), None, f"{place} gives {len(vias)} values of a type that cannot be worked out "
                    f"to {', '.join(sorted(set(vias)))}, so whether a protected value is released there cannot be told",
                    *sorted(set(vias)))
    for leak in ctx.observed.leaks:
        dp = ctx.relations.dp_of(leak.at) if leak.at is not None else None
        if leak.data in held and leak.effect in never and (leak.at is None or ctx.in_scope(rule, dp)):
            yield broken(rule, str(leak.at or rule.on), leak.span, f"the text of {a_type(leak.data)} was written "
                         f"to {leak.where} while {leak.seen} ran", leak.data, leak.where)


# ---- states and features in statements ---------------------------------------------------------------------------

def _words(name: str) -> str:
    return name.replace("_", " ").lower()


def _clause(model: CodeModel, data: DataModel, clause: DataClause, feature: bool, about: str,
            span: Span) -> Finding | None:
    rule = FEATURE if feature else STATE
    keyword = "Where" if feature else "While"

    def bad(say: str) -> Finding:
        return finding(Result.BREAKS, rule, about, span, f'the "{keyword}" clause {say}', clause.structure,
                       clause.field or "", clause.value)

    found = data.named(clause.structure)
    if not found:
        known = ", ".join(sorted({s.name for s in data.structures.values()})) or "none"
        return bad(f'names "{clause.structure}", which is no recorded structure (recorded: {known})')
    if len(found) > 1:
        return bad(f'names "{clause.structure}", which could be {", ".join(s.dp for s in found)}')
    s = found[0]
    if clause.field is not None:
        field = next((f for f in s.fields if _words(f.name) == clause.field), None)
        if field is None:
            return bad(f'names "{clause.field}", which is no field of {s.dp}')
    else:
        candidates = [f for f in s.fields if (is_flag(f.type) if feature else choices(model, f.type))]
        if len(candidates) != 1:
            kind = "yes-or-no" if feature else "enumeration"
            return bad(f"must name the field: {s.dp} has {len(candidates)} {kind} fields, not one")
        field = candidates[0]
    if feature:
        return None if is_flag(field.type) else bad(f"names {field.name}, which is not a yes-or-no field")
    values = choices(model, field.type)
    if values is None:
        return bad(f"names {field.name}, which is not an enumeration")
    if clause.value not in {_words(v) for v in values}:
        return bad(f'says "{clause.value}", which {s.primary.name}.{field.name} cannot be: it is one of '
                   + ", ".join(_words(v) for v in values))
    return None


def _sentences(record: Record) -> list[tuple[str, Sentence]]:
    out = [(str(st.ref), st.sentence) for fr in record.frs.values() for st in fr.statements]
    out += [(name, c.statement) for name, c in record.constraints.items() if c.statement is not None]
    return sorted(out, key=lambda x: x[0])


def check_clauses(record: Record, model: CodeModel, data: DataModel, lexicons: Lexicons) -> list[Finding]:
    """Every While clause names a value of a recorded structure's enumeration; every Where clause, a yes-or-no
    field (DESIGN2 §6.4)."""
    out = []
    for about, sentence in _sentences(record):
        ears, _ = parse_ears(sentence.text, lexicons)
        if ears is None:
            continue
        for clause, feature in ((ears.where, True), (ears.while_, False)):
            if clause is not None and (f := _clause(model, data, clause, feature, about, sentence.span)):
                out.append(f)
    return out


CHECKS: Mapping[CheckKindName, Check] = {
    CheckKindName("data-ownership"): data_ownership,
    CheckKindName("references-resolve"): references_resolve,
    CheckKindName("representations-agree"): representations_agree,
    CheckKindName("access-sanity"): access_sanity,
    CheckKindName("messages-agree"): messages_agree,
    CheckKindName("endpoints-agree"): endpoints_agree,
    CheckKindName("data-flow"): data_flow,
}

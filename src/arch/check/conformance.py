"""Where the realization departs from the design.

Realizes arch.check.conformance: compares facts about the code with the design. Rules never pass
silently on something an adapter did not analyze; they report it as not analyzed.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from weakref import WeakKeyDictionary

from arch.check.engine import Context, Finding, FindingKey, Rule, RuleId, Severity, Subject, by_maturity
from arch.model.graph import is_within, parent_of
from arch.model.ids import ComponentId, CriterionId, Text
from arch.model.policy import EffectKind, EffectVerdict, PackageName, Policy
from arch.realize.facts import Capability, Effect, Facts, Role, UnitName
from arch.realize.mapping import UnitMap, map_units

_maps: WeakKeyDictionary[Context, UnitMap] = WeakKeyDictionary()


def _mapping(ctx: Context) -> UnitMap:
    if ctx not in _maps:
        _maps[ctx] = map_units(ctx.graph, ctx.facts or Facts())
    return _maps[ctx]


def _finding(rule: str, subject: str, key: str, severity: Severity, message: str, hint: str, location=None) -> Finding:
    return Finding(Subject(subject), RuleId(rule), FindingKey(key), severity, Text(message), Text(hint), location)


def _source_units(ctx: Context) -> frozenset[UnitName]:
    return frozenset(u.name for u in ctx.facts.units if u.role is Role.SOURCE) if ctx.facts else frozenset()


def parse_errors(ctx: Context) -> Iterator[Finding]:
    for e in ctx.facts.errors if ctx.facts else ():
        yield _finding("C000", e.path, "parse", Severity.ERROR, f"could not be analyzed: {e.message}",
                       "fix the syntax error; nothing in this file is checked until then", e.location)


def boundaries(ctx: Context) -> Iterator[Finding]:
    """An import from component a into component b needs `b` among a's uses, and b visible to a."""
    g, m = ctx.graph, _mapping(ctx)
    seen: dict[tuple[ComponentId, ComponentId], Finding] = {}
    for imp in ctx.facts.imports if ctx.facts else ():
        a = m.component_of.get(imp.unit)
        target = m.target_of(imp)
        b = m.component_of.get(target) if target else None
        if a is None or b is None or is_within(b, a) or g.may_use(a, b) or (a, b) in seen:
            continue
        declared = any(is_within(b, u) for u in g.uses(a))
        why, hint = (
            (f"which {parent_of(b)} does not export", f"export it from {parent_of(b)}, or depend on {parent_of(b)}'s port")
            if declared else
            ("which is not among its uses", f"add it to the uses of {a} (if its parent may use it), or remove the import")
        )
        seen[(a, b)] = _finding("C001", a, f"import:{b}", Severity.ERROR,
                                f"{imp.unit} imports {target} (component {b}), {why}", hint, imp.location)
    yield from seen.values()


def unmapped(ctx: Context) -> Iterator[Finding]:
    for unit in _mapping(ctx).unmapped:
        yield _finding("C002", unit.name, "unmapped", Severity.WARNING, f"{unit.path} belongs to no component",
                       "add a component whose id is a prefix of this module, or move the module")


def unbuilt(ctx: Context) -> Iterator[Finding]:
    """Components with no code yet; only the topmost of an unbuilt subtree is reported."""
    g, m = ctx.graph, _mapping(ctx)
    for cid in g.ids():
        parent = parent_of(cid)
        if m.units_in(cid) or (parent is not None and not m.units_in(parent)):
            continue
        c = g[cid]
        sev = by_maturity(c.status, draft=Severity.INFO, specified=Severity.INFO, contracted=Severity.ERROR)
        yield _finding("C003", cid, "no-code", sev, "has no code yet", f"create the module {cid}", c.location)


def links(ctx: Context) -> Iterator[Finding]:
    g = ctx.graph
    criteria = {cr.id for cid in g.ids() for cr in g[cid].criteria}
    for link in ctx.facts.links if ctx.facts else ():
        comp, _, ac = link.target.partition("#")
        if comp not in g:
            problem = f"no component '{comp}'"
        elif ac and CriterionId(link.target) not in criteria:
            problem = f"{comp} has no acceptance criterion {ac}"
        else:
            continue
        yield _finding("C004", f"{link.unit}.{link.symbol}", f"link:{link.target}", Severity.ERROR,
                       f"links to {link.target}, but {problem}", "fix the id in @realizes(...)", link.location)


def evidence(ctx: Context) -> Iterator[Finding]:
    g = ctx.graph
    linked = {l.target for l in ctx.facts.links} if ctx.facts else set()
    for cid in g.ids():
        c = g[cid]
        for cr in c.criteria:
            if cr.id not in linked:
                sev = by_maturity(c.status, draft=Severity.INFO, specified=Severity.INFO, contracted=Severity.ERROR)
                yield _finding("C005", cid, f"evidence:{cr.id}", sev, f"{cr.id.partition('#')[2]} has no linked test or contract",
                               f'add @realizes("{cr.id}") to a test or contract that checks it', cr.location)


def third_party(ctx: Context) -> Iterator[Finding]:
    """Imports outside the project and the standard library must be allowed by an imports constraint."""
    g, m = ctx.graph, _mapping(ctx)
    seen: set[tuple[ComponentId, str]] = set()
    source = _source_units(ctx)
    for imp in ctx.facts.imports if ctx.facts else ():
        a = m.component_of.get(imp.unit)
        if a is None or imp.unit not in source or m.target_of(imp) is not None:
            continue
        top = imp.target.split(".")[0]
        rule = g.effective_policy(a).imports
        if top in sys.stdlib_module_names or rule is None or (a, top) in seen:
            continue
        if not rule.allows(a, PackageName(imp.target)):
            seen.add((a, top))
            yield _finding("C006", a, f"third-party:{top}", Severity.ERROR,
                           f"{imp.unit} imports third-party '{imp.target}', which no constraint allows here",
                           "add it to the dependency allowlist (with a decision entry), or remove it", imp.location)


def effect_violations(ctx: Context) -> Iterator[Finding]:
    """Effects (direct, or reached through calls) outside what the component's policy allows."""
    g, m = ctx.graph, _mapping(ctx)
    policies: dict[ComponentId, Policy] = {}
    seen: set[tuple[ComponentId, str, str]] = set()
    source = _source_units(ctx)
    for e in ctx.facts.effects if ctx.facts else ():
        cid = m.component_of.get(e.unit)
        if cid is None or e.unit not in source:
            continue
        policy = policies.setdefault(cid, g.effective_policy(cid))
        how = "directly" if e.direct else f"via {e.via}"
        if e.effect is Effect.UNKNOWN:
            if policy.restricts_effects and (cid, "unknown", e.symbol) not in seen:
                seen.add((cid, "unknown", e.symbol))
                yield _finding("C009", cid, f"unknown:{e.unit}.{e.symbol}", Severity.WARNING,
                               f"{e.unit}.{e.symbol} uses dynamic code ({how}), so its effects cannot be checked",
                               "avoid eval/exec/dynamic imports here, or move them to a shell component", e.location)
            continue
        problem = _effect_problem(policy, cid, EffectKind(e.effect.value), e.direct)
        if problem and (cid, e.effect.value, problem) not in seen:
            seen.add((cid, e.effect.value, problem))
            yield _finding("C008", cid, f"effect:{e.effect.value}", Severity.ERROR,
                           f"{e.unit}.{e.symbol} has effect {e.effect.value} ({how}), which {problem}",
                           "move the effect behind a shell component and pass data in, or change the constraint "
                           "(with a decision entry)", e.location)


def _effect_problem(policy: Policy, cid: ComponentId, effect: EffectKind, direct: bool) -> str | None:
    verdict = policy.effects.verdict(effect)
    if verdict is EffectVerdict.FORBIDDEN:
        return verdict.value
    if verdict is EffectVerdict.NOT_ALLOWED:
        allowed = ", ".join(sorted(k.value for k in policy.effects.allow or ())) or "none"
        return f"{verdict.value} (allowed: {allowed})"
    if direct and policy.direct_effects is not None and not policy.direct_effects.permits(cid, effect):
        holders = ", ".join(policy.direct_effects.holders(effect)) or "no component"
        return f"may be done directly only in {holders}"
    return None


def effects_unanalyzed(ctx: Context) -> Iterator[Finding]:
    g, m = ctx.graph, _mapping(ctx)
    for cid in g.ids():
        units = [ctx.facts.unit(u) for u, c in m.component_of.items() if c == cid] if ctx.facts else []
        if not units or all(Capability.EFFECTS in u.capabilities for u in units if u):
            continue
        if g.effective_policy(cid).restricts_effects:
            yield _finding("C007", cid, "effects", Severity.INFO, "effect constraints apply, but effects were not analyzed",
                           "the adapter could not analyze effects for some of this component's code", g[cid].location)


RULES: tuple[Rule, ...] = (
    Rule(RuleId("C000"), Text("source files can be analyzed"), parse_errors),
    Rule(RuleId("C001"), Text("imports stay within declared, visible uses"), boundaries),
    Rule(RuleId("C002"), Text("every source unit belongs to a component"), unmapped),
    Rule(RuleId("C003"), Text("components have code"), unbuilt),
    Rule(RuleId("C004"), Text("design links point at real components and criteria"), links),
    Rule(RuleId("C005"), Text("acceptance criteria have linked evidence"), evidence),
    Rule(RuleId("C006"), Text("third-party imports are allowed by a constraint"), third_party),
    Rule(RuleId("C007"), Text("effect constraints are analyzable"), effects_unanalyzed),
    Rule(RuleId("C008"), Text("effects stay within what constraints allow (C009: effects that cannot be known)"), effect_violations),
)

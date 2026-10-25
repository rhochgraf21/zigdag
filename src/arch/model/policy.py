"""Constraint rules as typed policies, and how policies combine down the tree.

Realizes arch.model.policy. Hides the rule syntax written in constraint files. Each rule kind knows
how to parse itself, how to combine with the same rule from other constraints, and what it permits.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import NewType, TypeAlias

from arch.model.ids import ComponentId, Text, is_within

PackageName = NewType("PackageName", str)  # a dotted import name, e.g. "ruamel.yaml"
TypeName = NewType("TypeName", str)  # a type as named in code, e.g. "str"
MetricName = NewType("MetricName", str)
Quantity = NewType("Quantity", float)
RawRule: TypeAlias = Mapping[str, object]  # a rule as read from YAML, before parsing


class EffectKind(enum.Enum):
    """Effects a constraint can talk about. Mirrors arch.realize.facts.Effect (kept equal by a test)."""

    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    SUBPROCESS = "subprocess"
    STDIO = "stdio"
    NETWORK = "network"
    TIME = "time"
    RANDOM = "random"
    ENV = "env"


class Problems:
    """Collects what is wrong with a rule while parsing it, so parsing never raises."""

    def __init__(self) -> None:
        self.messages: list[Text] = []

    def add(self, message: Text) -> None:
        self.messages.append(message)

    def names(self, raw: object, where: Text) -> tuple[Text, ...]:
        if raw is None:
            return ()
        if isinstance(raw, list) and all(isinstance(v, str) for v in raw):
            return tuple(Text(v) for v in raw)
        self.add(Text(f"{where} must be a list of names"))
        return ()

    def effects(self, raw: object, where: Text) -> frozenset[EffectKind]:
        known = {e.value: e for e in EffectKind}
        kinds = set()
        for name in self.names(raw, where):
            if name in known:
                kinds.add(known[name])
            else:
                self.add(Text(f"{where}: unknown effect '{name}' (known: {', '.join(known)})"))
        return frozenset(kinds)

    def mapping(self, raw: object, where: Text) -> RawRule:
        if raw is None:
            return {}
        if isinstance(raw, Mapping):
            return raw
        self.add(Text(f"{where} must be a mapping"))
        return {}


@dataclass(frozen=True)
class EffectRule:
    forbid: frozenset[EffectKind] = frozenset()
    allow: frozenset[EffectKind] | None = None  # None: no allow-list applies
    exempt: frozenset[ComponentId] = frozenset()  # subtrees the forbid list does not reach (a recorded exception)

    @staticmethod
    def parse(raw: RawRule, problems: Problems) -> EffectRule:
        allow = problems.effects(raw["allow"], Text("effects.allow")) if "allow" in raw else None
        exempt = frozenset(ComponentId(n) for n in problems.names(raw.get("except_in"), Text("effects.except_in")))
        return EffectRule(problems.effects(raw.get("forbid"), Text("effects.forbid")), allow, exempt)

    @staticmethod
    def combine(rules: Iterable[EffectRule]) -> EffectRule:
        """Forbids accumulate; allow-lists intersect, so a descendant can only tighten. Exemptions are kept
        per rule: they are resolved against the component by `for_component` before combining."""
        forbid: set[EffectKind] = set()
        allow: frozenset[EffectKind] | None = None
        for r in rules:
            forbid |= r.forbid
            if r.allow is not None:
                allow = r.allow if allow is None else allow & r.allow
        return EffectRule(frozenset(forbid), allow)

    def for_component(self, cid: ComponentId) -> EffectRule:
        """This rule as it applies to `cid`: without its forbid list inside an exempt subtree."""
        if any(is_within(cid, e) for e in self.exempt):
            return EffectRule(frozenset(), self.allow)
        return EffectRule(self.forbid, self.allow)

    def verdict(self, effect: EffectKind) -> EffectVerdict:
        if effect in self.forbid:
            return EffectVerdict.FORBIDDEN
        if self.allow is not None and effect not in self.allow:
            return EffectVerdict.NOT_ALLOWED
        return EffectVerdict.PERMITTED

    @property
    def restricts(self) -> bool:
        return bool(self.forbid) or self.allow is not None


class EffectVerdict(enum.Enum):
    PERMITTED = "permitted"
    FORBIDDEN = "is forbidden here"
    NOT_ALLOWED = "is not allowed here"


@dataclass(frozen=True)
class DirectEffects:
    """Which components may perform which effects directly (others only by calling them)."""

    grants: Mapping[ComponentId, frozenset[EffectKind]] = field(default_factory=dict)

    @staticmethod
    def parse(raw: RawRule, problems: Problems) -> DirectEffects:
        return DirectEffects({ComponentId(k): problems.effects(v, Text(f"direct_effects.{k}")) for k, v in raw.items()})

    @staticmethod
    def combine(rules: Iterable[DirectEffects]) -> DirectEffects:
        grants: dict[ComponentId, frozenset[EffectKind]] = {}
        for r in rules:
            for cid, kinds in r.grants.items():
                grants[cid] = grants.get(cid, frozenset()) | kinds
        return DirectEffects(grants)

    def permits(self, cid: ComponentId, effect: EffectKind) -> bool:
        return any(is_within(cid, holder) and effect in kinds for holder, kinds in self.grants.items())

    def holders(self, effect: EffectKind) -> tuple[ComponentId, ...]:
        return tuple(sorted(c for c, kinds in self.grants.items() if effect in kinds))


@dataclass(frozen=True)
class ImportRule:
    """Third-party packages allowed everywhere in scope, and per component."""

    allowed: frozenset[PackageName] = frozenset()
    allowed_in: Mapping[ComponentId, frozenset[PackageName]] = field(default_factory=dict)

    @staticmethod
    def parse(raw: RawRule, problems: Problems) -> ImportRule:
        per = problems.mapping(raw.get("allow_third_party_in"), Text("imports.allow_third_party_in"))
        allowed = problems.names(raw.get("allow_third_party"), Text("imports.allow_third_party"))
        return ImportRule(
            frozenset(PackageName(n) for n in allowed),
            {ComponentId(k): frozenset(PackageName(n) for n in problems.names(v, Text(f"imports.allow_third_party_in.{k}")))
             for k, v in per.items()},
        )

    @staticmethod
    def combine(rules: Iterable[ImportRule]) -> ImportRule:
        allowed: set[PackageName] = set()
        per: dict[ComponentId, frozenset[PackageName]] = {}
        for r in rules:
            allowed |= r.allowed
            for cid, pkgs in r.allowed_in.items():
                per[cid] = per.get(cid, frozenset()) | pkgs
        return ImportRule(frozenset(allowed), per)

    def allows(self, cid: ComponentId, module: PackageName) -> bool:
        packages = set(self.allowed)
        for holder, pkgs in self.allowed_in.items():
            if is_within(cid, holder):
                packages |= pkgs
        return any(module == p or module.startswith(p + ".") for p in packages)


@dataclass(frozen=True)
class PortTypeRule:
    """Built-in types that may not appear in public ports (bool is usually allowed as a return)."""

    forbid: frozenset[TypeName] = frozenset()
    allow_in_returns: frozenset[TypeName] = frozenset()
    exempt: frozenset[ComponentId] = frozenset()

    @staticmethod
    def parse(raw: RawRule, problems: Problems) -> PortTypeRule:
        return PortTypeRule(
            frozenset(TypeName(n) for n in problems.names(raw.get("forbid"), Text("port_types.forbid"))),
            frozenset(TypeName(n) for n in problems.names(raw.get("allow_in_returns"), Text("port_types.allow_in_returns"))),
            frozenset(ComponentId(n) for n in problems.names(raw.get("except_in"), Text("port_types.except_in"))),
        )

    @staticmethod
    def combine(rules: Iterable[PortTypeRule]) -> PortTypeRule:
        rules = list(rules)
        return PortTypeRule(
            frozenset().union(*(r.forbid for r in rules)),
            frozenset().union(*(r.allow_in_returns for r in rules)),
            frozenset().union(*(r.exempt for r in rules)),
        )

    def applies_to(self, cid: ComponentId) -> bool:
        return bool(self.forbid) and not any(is_within(cid, e) for e in self.exempt)


@dataclass(frozen=True)
class BudgetRule:
    limits: Mapping[MetricName, Quantity] = field(default_factory=dict)

    @staticmethod
    def parse(raw: RawRule, problems: Problems) -> BudgetRule:
        limits = {}
        for k, v in raw.items():
            if isinstance(v, int | float) and not isinstance(v, bool):
                limits[MetricName(k)] = Quantity(float(v))
            elif not isinstance(v, str):  # text values are notes about the measurement
                problems.add(Text(f"budget.{k} must be a number"))
        return BudgetRule(limits)

    @staticmethod
    def combine(rules: Iterable[BudgetRule]) -> BudgetRule:
        limits: dict[MetricName, Quantity] = {}
        for r in rules:
            for k, v in r.limits.items():
                limits[k] = Quantity(min(v, limits.get(k, v)))
        return BudgetRule(limits)


class Critique(enum.Enum):
    """Whether design text must be judged by an independent critic before its stations count as passed."""

    OPTIONAL = "optional"
    REQUIRED = "required"

    @staticmethod
    def parse(raw: RawRule, problems: Problems) -> Critique:
        required = raw.get("required", True)
        if not isinstance(required, bool):
            problems.add(Text("critique.required must be true or false"))
            return Critique.OPTIONAL
        return Critique.REQUIRED if required else Critique.OPTIONAL


class RuleKind(enum.Enum):
    EFFECTS = "effects"
    DIRECT_EFFECTS = "direct_effects"
    IMPORTS = "imports"
    PORT_TYPES = "port_types"
    BUDGET = "budget"
    CRITIQUE = "critique"


@dataclass(frozen=True)
class Policy:
    """Everything a constraint (or a combination of constraints) says about a component."""

    effects: EffectRule = EffectRule()
    direct_effects: DirectEffects | None = None
    imports: ImportRule | None = None
    port_types: PortTypeRule = PortTypeRule()
    budget: BudgetRule = BudgetRule()
    critique: Critique = Critique.OPTIONAL

    @staticmethod
    def parse(raw: RawRule) -> tuple[Policy, tuple[Text, ...]]:
        problems = Problems()
        known = {k.value for k in RuleKind}
        for name in sorted(set(raw) - known):
            problems.add(Text(f"unknown rule '{name}' (known: {', '.join(sorted(known))})"))
        sections = {k: problems.mapping(raw.get(k.value), Text(k.value)) for k in RuleKind}
        policy = Policy(
            effects=EffectRule.parse(sections[RuleKind.EFFECTS], problems),
            direct_effects=DirectEffects.parse(sections[RuleKind.DIRECT_EFFECTS], problems)
            if RuleKind.DIRECT_EFFECTS.value in raw else None,
            imports=ImportRule.parse(sections[RuleKind.IMPORTS], problems) if RuleKind.IMPORTS.value in raw else None,
            port_types=PortTypeRule.parse(sections[RuleKind.PORT_TYPES], problems),
            budget=BudgetRule.parse(sections[RuleKind.BUDGET], problems),
            critique=Critique.parse(sections[RuleKind.CRITIQUE], problems)
            if RuleKind.CRITIQUE.value in raw else Critique.OPTIONAL,
        )
        return policy, tuple(problems.messages)

    @staticmethod
    def combine(policies: Iterable[Policy]) -> Policy:
        ps = list(policies)
        directs = [p.direct_effects for p in ps if p.direct_effects is not None]
        imports = [p.imports for p in ps if p.imports is not None]
        return Policy(
            effects=EffectRule.combine(p.effects for p in ps),
            direct_effects=DirectEffects.combine(directs) if directs else None,
            imports=ImportRule.combine(imports) if imports else None,
            port_types=PortTypeRule.combine(p.port_types for p in ps),
            budget=BudgetRule.combine(p.budget for p in ps),
            critique=Critique.REQUIRED if any(p.critique is Critique.REQUIRED for p in ps) else Critique.OPTIONAL,
        )

    def describe(self) -> Text:
        """The policy in plain words, one short sentence per line, for people reviewing a change to it."""
        names = lambda xs: ", ".join(sorted(str(x.value if isinstance(x, enum.Enum) else x) for x in xs))  # noqa: E731
        lines = []
        if self.effects.forbid:
            lines.append(f"Code must not use these effects: {names(self.effects.forbid)}.")
            if self.effects.exempt:
                lines.append(f"This does not apply in {names(self.effects.exempt)}.")
        if self.effects.allow is not None:
            lines.append(f"Code may use only these effects: {names(self.effects.allow)}." if self.effects.allow
                         else "Code must have no effects.")
        if self.direct_effects is not None:
            if self.direct_effects.grants:
                lines.append("Only these parts may cause effects themselves:")
                lines += [f"- {c} may cause {names(k)}." for c, k in sorted(self.direct_effects.grants.items())]
            else:
                lines.append("No part may cause effects itself.")
        if self.imports is not None:
            lines.append(f"Code may import only these outside packages: {names(self.imports.allowed)}." if self.imports.allowed
                         else "Code must not import outside packages.")
            lines += [f"- {c} may also import {names(p)}." for c, p in sorted(self.imports.allowed_in.items())]
        if self.port_types.forbid:
            lines.append(f"Public functions must not take or return these bare types: {names(self.port_types.forbid)}.")
            if self.port_types.allow_in_returns:
                lines.append(f"They may return {names(self.port_types.allow_in_returns)}.")
            if self.port_types.exempt:
                lines.append(f"This does not apply in {names(self.port_types.exempt)}.")
        lines += [f"{k} must be at most {v:g}." for k, v in sorted(self.budget.limits.items())]
        if self.critique is Critique.REQUIRED:
            lines.append("An independent critic must judge the design text before its stations count as passed.")
        return Text("\n".join(lines) or "No rule here is checked by machine.")

    def for_component(self, cid: ComponentId) -> Policy:
        """This policy with exemptions resolved for `cid`."""
        return Policy(self.effects.for_component(cid), self.direct_effects, self.imports, self.port_types, self.budget,
                      self.critique)

    @property
    def restricts_effects(self) -> bool:
        return self.effects.restricts or self.direct_effects is not None

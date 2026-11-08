"""The rules in force (DESIGN2 §4): project constraints and process variables, and the built-ins after tuning,
each with its typed parameters, the FR it covers, and the code it skips.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from zigdag.core.code import Place, Qualified
from zigdag.core.effects import BUILT_IN as BUILT_IN_EFFECTS
from zigdag.core.effects import resource_container
from zigdag.core.findings import BUILT_IN_SPAN, Span
from zigdag.core.kinds.params import Params, convert
from zigdag.core.kinds.registry import CheckKind
from zigdag.core.names import CheckKindName, FrName, RuleId
from zigdag.core.record.builtins import BUILT_INS
from zigdag.core.record.model import CodeRule, Excepted, Record
from zigdag.core.resolve import Tree
from zigdag.core.settings import Settings


@dataclass(frozen=True)
class RuleUse:
    name: RuleId
    kind: CheckKindName
    params: Params
    on: FrName
    excepted: tuple[Excepted, ...]
    span: Span

    def skips(self, tree: Tree, where: Place | Qualified | str) -> bool:
        """Whether the code is excepted: it is, or is inside, a name under `except`."""
        text = str(where)
        return any(text == c or text.startswith(c + ".") for c in self._candidates(tree))

    def _candidates(self, tree: Tree) -> list[str]:
        bases = tree.code_base(self.on)
        out = []
        for e in self.excepted:
            out += [f"{b}.{e.code.path}" for b in bases] + [e.code.path]
        return out


def _effect_known(record: Record, settings: Settings):
    def known(name: str) -> bool:
        container = resource_container(name)
        return name in BUILT_IN_EFFECTS or name in settings.effects or (container is not None and container in record.frs)
    return known


def rules_in_force(record: Record, settings: Settings, kinds: Mapping[CheckKindName, CheckKind]) -> list[RuleUse]:
    """Every check-enforced rule whose kind exists, whose parameters convert and whose FR exists."""
    root = record.root.name if record.root else None
    known = _effect_known(record, settings)
    out: list[RuleUse] = []

    def add(name: RuleId, kind: CheckKindName, raw: Mapping, on: FrName | None, excepted, span: Span) -> None:
        k = kinds.get(kind)
        if k is None or on is None or on not in record.frs:
            return
        params, problems = convert(k.params, {p: v.value for p, v in raw.items()}, known)
        if not problems:
            out.append(RuleUse(name, kind, params, on, tuple(excepted), span))

    for name, c in record.constraints.items():
        if c.check is not None:
            add(name, c.check.kind.value, c.check.params, c.on.value, c.check.excepted, c.span)
    for name, v in record.process.items():
        if isinstance(v.kind, CodeRule):
            add(name, v.kind.check.kind.value, v.kind.check.params, v.on.value, v.kind.check.excepted, v.span)
    for name, b in BUILT_INS.items():
        tuning = record.tunings.get(name)
        if tuning is not None and tuning.off and not b.always_on:
            continue
        on = tuning.on.value if tuning is not None and tuning.on is not None else root
        add(name, b.kind, tuning.params if tuning else {}, on, tuning.excepted if tuning else (),
            tuning.span if tuning else BUILT_IN_SPAN)
    return sorted(out, key=lambda r: r.name)

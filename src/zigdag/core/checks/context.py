"""What every check of the code sees: the record and settings, the code model, the DP tree, the relationships and
the data model, all worked out once per run."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import CodeModel, Observations, Qualified, SymbolKind
from zigdag.core.data import DataModel
from zigdag.core.findings import Digest, Finding, Result, RuleName, Span, Subject, finding
from zigdag.core.kinds.registry import EFFECTS
from zigdag.core.names import FrName
from zigdag.core.record.model import Record
from zigdag.core.relate import Relations
from zigdag.core.resolve import Tree
from zigdag.core.settings import Settings


@dataclass(frozen=True)
class Context:
    record: Record
    settings: Settings
    model: CodeModel
    tree: Tree
    relations: Relations
    data: DataModel
    answered: frozenset[tuple[RuleName, Subject, Digest]] = frozenset()  # questions answered for their content
    declared_pure: frozenset[Qualified] = frozenset()  # functions declared pure (§3), in code or by an effects rule

    def is_answered(self, question: Finding) -> bool:
        return (question.rule, question.about, question.digest) in self.answered

    def in_scope(self, rule: RuleUse, dp: FrName | None) -> bool:
        """Whether code of this DP is covered by the rule."""
        return dp is not None and self.tree.within(dp, rule.on)

    def used_from_other_dps(self, rule: RuleUse) -> dict[Qualified, Span]:
        """Project symbols used from another DP, inside the rule's scope, with where each is first used."""
        out: dict[Qualified, Span] = {}
        for edge in self.relations.edges:
            if not (self.in_scope(rule, edge.target) or self.in_scope(rule, edge.source)):
                continue
            name = edge.target_name
            while name and Qualified(name) not in self.model.symbols:
                name = name.rpartition(".")[0]
            symbol = self.model.symbols.get(Qualified(name)) if name else None
            if symbol is not None and self.tree.owner(symbol.qualified) == edge.target:
                out.setdefault(symbol.qualified, edge.span)
        return out

    @property
    def observed(self) -> Observations:
        """What was seen while the tests ran and is still current; nothing, before the first watched run."""
        return self.model.observed or Observations()


Check = Callable[[Context, RuleUse], Iterable[Finding]]


def declared_pure(model: CodeModel, tree: Tree, rules: Iterable[RuleUse]) -> frozenset[Qualified]:
    """The functions declared pure (DESIGN2 §3): by their code, or by an effects rule that allows nothing."""
    allow_nothing = [r for r in rules if r.kind == EFFECTS and not r.params["allow"]]
    out: set[Qualified] = set()
    for name, symbol in model.symbols.items():
        if symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
            continue
        owner = tree.owner(name)
        if symbol.declared_pure or (owner is not None and any(
                tree.within(owner, r.on) and not r.skips(tree, name) for r in allow_nothing)):
            out.add(name)
    return frozenset(out)


def short_name(name: str) -> str:
    return name.rpartition(".")[2]


def a_type(name: str) -> str:
    """A type's short name with its article: an Email, a CustomerId."""
    short = short_name(name)
    return f"{'an' if short[:1].lower() in 'aeiou' else 'a'} {short}"


def broken(rule: RuleUse, about: str, span: Span | None, say: str, *content: str) -> Finding:
    return finding(Result.BREAKS, rule.name, about, span, say, *content)


def asked(rule: RuleUse, about: str, span: Span | None, say: str, *content: str) -> Finding:
    return finding(Result.QUESTION, rule.name, about, span, say, *content)

"""What the author of a custom check imports (DESIGN2 §4.2), in one place.

A custom check is a function in design/checks/:

    from zigdag.checks import Context, RuleUse, broken

    def short_modules(context: Context, rule: RuleUse, *, lines: int = 300):
        '''Each module is short enough to read in one sitting.'''
        for path, unit in context.model.units.items():
            if unit.size > lines and context.in_scope(rule, context.tree.unit_owner.get(path)):
                yield broken(rule, path, unit.span, f"{path} is {unit.size} lines; at most {lines}")

It reads the same context zigdag's own checks read: the record (context.record), the code (context.model), and what
zigdag worked out from them. It reports with broken(...) for what is certainly wrong and asked(...) for a guess.
"""

from __future__ import annotations

import deal

from zigdag.core.checks.context import Context
from zigdag.core.checks.rules import RuleUse
from zigdag.core.findings import Finding, Result, RuleName, Span, Subject, finding
from zigdag.core.names import OutcomeRef, StatementRef
from zigdag.core.texts import Say

__all__ = ["Context", "Finding", "RuleUse", "Span", "asked", "broken"]

# What a finding can be about, as a check has it in hand: a name as text, or one of the record's own names, such as
# a statement's reference. An author passes what the record gave, and need not know which of them are text.
Named = Subject | StatementRef | OutcomeRef


def _named(about: Named) -> Subject:
    return Subject(str(about))


@deal.ensure(lambda rule, about, where, say, result: result.result is Result.BREAKS and result.rule == rule.name)
def broken(rule: RuleUse, about: Named, where: Span | None, say: Say) -> Finding:
    """A finding that the rule is certainly broken: what it is about, where that is written, and what is wrong."""
    return finding(Result.BREAKS, RuleName(rule.name), _named(about), where, say)


@deal.ensure(lambda rule, about, where, say, result: result.result is Result.QUESTION and result.rule == rule.name)
def asked(rule: RuleUse, about: Named, where: Span | None, say: Say) -> Finding:
    """A finding that the rule may be broken: a guess, which a person answers once."""
    return finding(Result.QUESTION, RuleName(rule.name), _named(about), where, say)

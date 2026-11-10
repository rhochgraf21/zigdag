"""lint, types and security (DESIGN2 §4.1): what the project's own linter, type checker and security checker report,
held to the record's scopes.

Which rules the tools apply is their configuration, not zigdag's, so it is never stated twice. zigdag decides only
where a diagnostic counts: on code inside the rule's DP and outside its except, owned by the innermost symbol around
it, so a rule can except one function as well as a whole module.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

import deal

from zigdag.core.checks.context import Check, Context
from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import Diagnosis, Diagnostic, Qualified, Severity
from zigdag.core.findings import Finding, Result, RuleName, Subject, finding
from zigdag.core.kinds.registry import LINT, SECURITY, TYPES
from zigdag.core.measures import Count
from zigdag.core.names import CheckKindName
from zigdag.core.texts import Content, Say

# A warning is what the tool's configuration chose not to fail on, so zigdag does not block on it either.
_RESULTS = {Severity.ERROR: Result.BREAKS, Severity.WARNING: Result.TODO}


def _in_scope(ctx: Context, rule: RuleUse, diagnosis: Diagnosis) -> Iterator[tuple[Diagnostic, Qualified]]:
    """Each diagnosis of the kind on code inside the rule's DP, with the innermost symbol it counts against."""
    for d in ctx.model.diagnostics:
        name = ctx.model.code_at(d.span) if d.diagnosis is diagnosis else None
        if name is not None and ctx.in_scope(rule, ctx.tree.owner(name)):
            yield d, name


def _diagnosed(diagnosis: Diagnosis) -> Check:
    def check(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
        for d, name in _in_scope(ctx, rule, diagnosis):
            if rule.skips(ctx.tree, name):
                continue
            # The line is left out of the digest, so the finding keeps its identity when code above it moves.
            yield finding(_RESULTS[d.severity], RuleName(rule.name), Subject(name), d.span,
                          Say(f"{d.tool} {d.code}: {d.say}"), Content(d.code), Content(d.say))
    return check


@deal.pre(lambda ctx, rule: rule.kind in DIAGNOSES)
@deal.ensure(lambda ctx, rule, result: result >= 0 and (result == 0 or bool(rule.excepted)))
def tolerated(ctx: Context, rule: RuleUse) -> Count:
    """How many of the tool's diagnoses a rule lets stand, on code it lists under except: its debt, as the tool
    would count it."""
    return Count(sum(1 for _, name in _in_scope(ctx, rule, DIAGNOSES[rule.kind]) if rule.skips(ctx.tree, name)))


DIAGNOSES: Mapping[CheckKindName, Diagnosis] = {LINT: Diagnosis.LINT, TYPES: Diagnosis.TYPES,  # what each kind reads
                                               SECURITY: Diagnosis.SECURITY}
CHECKS: Mapping[CheckKindName, Check] = {kind: _diagnosed(diagnosis) for kind, diagnosis in DIAGNOSES.items()}


@deal.ensure(lambda kinds, result: len(result) <= len(DIAGNOSES))
@deal.ensure(lambda kinds, result: all(any(DIAGNOSES.get(k) is d for k in kinds) for d in result))
def wanted(kinds: Iterable[CheckKindName]) -> frozenset[Diagnosis]:
    """What the tools must report for rules of these kinds: what the shell must run before the checks."""
    return frozenset(DIAGNOSES[k] for k in kinds if k in DIAGNOSES)

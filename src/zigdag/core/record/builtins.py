"""What every project gets without writing it (DESIGN2 §2.1, §4.4): the maintainer job and the built-in rules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import deal

from zigdag.core.findings import BUILT_IN_SPAN
from zigdag.core.names import INFRASTRUCTURE, AdapterName, CheckKindName, OutcomeRef, RuleId, Slug
from zigdag.core.record.model import Domain, Job, Outcome, Sentence
from zigdag.core.names import ParamName
from zigdag.core.texts import Written

MAINTAIN = Slug("maintain")
_HERE = BUILT_IN_SPAN


def _outcome(name: str, text: str) -> Outcome:
    return Outcome(OutcomeRef(MAINTAIN, Slug(name)), Sentence(text, _HERE))


MAINTAIN_JOB = Job(
    MAINTAIN,
    Sentence("Change the code without breaking it", _HERE),
    Sentence("Maintainer, a person or an agent", _HERE),
    (
        _outcome("find-code", "Minimize the time it takes to find the code that performs a function"),
        _outcome("unrelated-breakage", "Minimize the likelihood that a change breaks an unrelated function"),
        _outcome("review-time", "Minimize the time it takes to review a change"),
    ),
    built_in=True,
)

FIND_CODE = OutcomeRef(MAINTAIN, Slug("find-code"))
UNRELATED_BREAKAGE = OutcomeRef(MAINTAIN, Slug("unrelated-breakage"))
REVIEW_TIME = OutcomeRef(MAINTAIN, Slug("review-time"))


@dataclass(frozen=True)
class BuiltIn:
    """A rule every project has. Always-on ones cannot be switched off; the others can be tuned (§4.4)."""

    name: RuleId
    domain: Domain
    kind: CheckKindName
    params: Mapping[ParamName, Written | tuple[Written, ...]]
    serves: OutcomeRef
    always_on: bool
    # In force only where the project sets an infrastructure adapter up. A project that describes no infrastructure
    # grants nothing, so such a rule has nothing to check there, and a rule in force that checked nothing would
    # show its direction as passing (DESIGN2 §5.3, principle 6).
    of_infrastructure: bool = False

    @deal.ensure(lambda self, adapters, result: result or self.of_infrastructure)  # any other rule is every project's
    def applies(self, adapters: Iterable[AdapterName]) -> bool:
        """Whether a project that sets these adapters up has this rule."""
        return not self.of_infrastructure or bool(INFRASTRUCTURE & set(adapters))


def _rule(name: str, domain: Domain, serves: OutcomeRef, always_on: bool = False, of_infrastructure: bool = False,
          **params) -> BuiltIn:
    return BuiltIn(RuleId(name), domain, CheckKindName(name), params, serves, always_on, of_infrastructure)


_F, _P = Domain.FUNCTIONAL, Domain.PROCESS

# co-change is designed (DESIGN2 §4.4) and not here: no adapter reads git history yet, so nothing could check it.
# In force, it would only leave every project with a standing question that no work on the project can settle. It
# joins when an adapter can feed it.
BUILT_INS: Mapping[RuleId, BuiltIn] = {
    b.name: b
    for b in (
        _rule("encapsulation", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("container-boundaries", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("data-ownership", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("no-cycles", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("representations-agree", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("messages-agree", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("endpoints-agree", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("references-resolve", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("designed-modules", _F, FIND_CODE),
        _rule("declared-libraries", _F, UNRELATED_BREAKAGE),
        _rule("edge-types", _F, UNRELATED_BREAKAGE),
        _rule("declared-errors", _F, UNRELATED_BREAKAGE),
        _rule("access-sanity", _F, UNRELATED_BREAKAGE),
        _rule("one-writer-per-data-store", _F, UNRELATED_BREAKAGE),
        _rule("permitted-effects", _F, UNRELATED_BREAKAGE, always_on=True, of_infrastructure=True),
        _rule("least-privilege", _F, UNRELATED_BREAKAGE, of_infrastructure=True),
        _rule("max-lines", _P, FIND_CODE),
        _rule("max-children", _P, FIND_CODE),
        _rule("described-names", _P, REVIEW_TIME),
        _rule("narrow-parameters", _P, UNRELATED_BREAKAGE),
        _rule("no-single-implementations", _P, FIND_CODE),
        _rule("mutation", _P, UNRELATED_BREAKAGE),
        _rule("planned-effects", _P, UNRELATED_BREAKAGE),
        _rule("contracted-interfaces", _P, UNRELATED_BREAKAGE),
    )
}

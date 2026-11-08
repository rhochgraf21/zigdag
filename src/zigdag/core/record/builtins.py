"""What every project gets without writing it (DESIGN2 §2.1, §4.4): the maintainer job and the built-in rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from zigdag.core.findings import BUILT_IN_SPAN
from zigdag.core.names import CheckKindName, OutcomeRef, RuleId, Slug
from zigdag.core.record.model import Domain, Job, Outcome, Sentence

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
    params: Mapping[str, str | tuple[str, ...]]
    serves: OutcomeRef
    always_on: bool


def _rule(name: str, domain: Domain, serves: OutcomeRef, always_on: bool = False, **params) -> BuiltIn:
    return BuiltIn(RuleId(name), domain, CheckKindName(name), params, serves, always_on)


_F, _P = Domain.FUNCTIONAL, Domain.PROCESS

BUILT_INS: Mapping[RuleId, BuiltIn] = {
    b.name: b
    for b in (
        _rule("encapsulation", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("container-boundaries", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("data-ownership", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("no-cycles", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("permitted-effects", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("representations-agree", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("messages-agree", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("endpoints-agree", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("references-resolve", _F, UNRELATED_BREAKAGE, always_on=True),
        _rule("declared-libraries", _F, UNRELATED_BREAKAGE),
        _rule("edge-types", _F, UNRELATED_BREAKAGE),
        _rule("declared-errors", _F, UNRELATED_BREAKAGE),
        _rule("access-sanity", _F, UNRELATED_BREAKAGE),
        _rule("one-writer-per-data-store", _F, UNRELATED_BREAKAGE),
        _rule("least-privilege", _F, UNRELATED_BREAKAGE),
        _rule("max-lines", _P, FIND_CODE),
        _rule("max-children", _P, FIND_CODE),
        _rule("described-names", _P, REVIEW_TIME),
        _rule("min-depth", _P, FIND_CODE),
        _rule("no-mode-parameters", _P, UNRELATED_BREAKAGE),
        _rule("narrow-parameters", _P, UNRELATED_BREAKAGE),
        _rule("no-single-implementations", _P, FIND_CODE),
        _rule("co-change", _P, UNRELATED_BREAKAGE),
        _rule("mutation", _P, UNRELATED_BREAKAGE),
        _rule("planned-effects", _P, UNRELATED_BREAKAGE),
    )
}

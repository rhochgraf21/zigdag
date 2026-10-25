"""Defective need and requirement statements, caught deterministically.

Realizes arch.check.statements. Lexicons and patterns, not judgement: solution terms inside needs,
requirements that join two functions, criteria a test cannot decide. Nuanced critique ("is this a need or
a solution in disguise?") is the elicit-needs and write-requirements methods' job, run by an agent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import NewType

from arch.check.engine import Context, Finding, FindingKey, Kind, Rule, RuleId, Station, Subject
from arch.model.ids import Text

Term = NewType("Term", str)

SOLUTION_TERMS: frozenset[Term] = frozenset(Term(t) for t in (
    "database", "sql", "nosql", "api", "rest", "graphql", "http", "json", "yaml", "xml", "server", "backend",
    "frontend", "cache", "queue", "microservice", "microservices", "kubernetes", "docker", "container",
    "aws", "azure", "gcp", "redis", "postgres", "postgresql", "mysql", "mongodb", "kafka", "rabbitmq", "s3",
    "lambda", "dashboard", "button", "dropdown", "modal", "endpoint", "webhook", "cron", "framework", "sdk",
    "python", "javascript", "typescript", "java", "react", "django", "flask", "blockchain", "using", "via",
    "implemented", "implement",
))
VAGUE_TERMS: frozenset[Term] = frozenset(Term(t) for t in (
    "fast", "quickly", "quick", "slow", "easy", "easily", "simple", "simply", "user-friendly", "intuitive",
    "robust", "scalable", "efficient", "efficiently", "flexible", "seamless", "seamlessly", "appropriate",
    "appropriately", "adequate", "reasonable", "optimal", "optimally", "etc",
))
# Verbs that start a second function when they follow "and"/"or" in a requirement.
FUNCTION_VERBS: frozenset[Term] = frozenset(Term(t) for t in (
    "compute", "detect", "derive", "classify", "order", "store", "persist", "send", "receive", "validate",
    "render", "display", "notify", "convert", "transform", "extract", "load", "save", "write", "parse", "rank",
    "reject", "record", "track", "produce", "generate", "emit", "update", "delete", "create", "remove", "merge",
    "sort", "filter", "schedule", "retry", "publish", "authenticate", "authorize", "encrypt", "verify",
    "measure", "monitor", "alert", "compare", "keep", "print", "draw", "charge", "ship", "bill",
    "tell", "get", "combine", "show", "say", "explain", "find", "offer", "present", "answer", "report",
))
_WORD = re.compile(r"[a-z][a-z0-9-]*")
_NUMBER = re.compile(r"\d")


@dataclass(frozen=True)
class Lexicon:
    solution: frozenset[Term] = SOLUTION_TERMS
    vague: frozenset[Term] = VAGUE_TERMS
    verbs: frozenset[Term] = FUNCTION_VERBS

    def extended(self, solution: Iterable[Term] = (), vague: Iterable[Term] = ()) -> Lexicon:
        return Lexicon(self.solution | {Term(t.lower()) for t in solution}, self.vague | {Term(t.lower()) for t in vague},
                       self.verbs)


def _finding(rule: str, subject: str, key: str, kind: Kind, message: str, hint: str, location) -> Finding:
    return Finding(Subject(subject), RuleId(rule), FindingKey(key), kind, Text(message), Text(hint), location)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("`", " "))


def _terms_in(text: str, lexicon: frozenset[Term]) -> list[str]:
    seen = []
    for w in _words(text):
        if w in lexicon and w not in seen:
            seen.append(w)
    return seen


def rules(lexicon: Lexicon = Lexicon()) -> tuple[Rule, ...]:
    def solution_in_needs(ctx: Context) -> Iterator[Finding]:
        for nid, need in sorted(ctx.graph.design.needs.items()):
            for term in _terms_in(need.statement, lexicon.solution):
                yield _finding("S101", nid, f"solution:{term}", Kind.QUESTION,
                               f"need mentions '{term}', which names a solution rather than an outcome",
                               "say what must be true for the stakeholder; keep technology for components",
                               need.location)

    def vague_criteria(ctx: Context) -> Iterator[Finding]:
        g = ctx.graph
        for cid in g.ids():
            c = g[cid]
            for cr in c.criteria:
                vague = _terms_in(cr.text, lexicon.vague)
                if vague and not _NUMBER.search(cr.text):
                    label = cr.id.partition("#")[2]
                    yield _finding("S102", cid, f"vague:{label}:{vague[0]}", Kind.QUESTION,
                                   f"{label} says '{vague[0]}' without a measure, so no test can decide it",
                                   "replace it with a number or an observable condition", cr.location)

    def non_ears(ctx: Context) -> Iterator[Finding]:
        g = ctx.graph
        for cid in g.ids():
            c = g[cid]
            for cr in c.criteria:
                if "shall" not in _words(cr.text):
                    label = cr.id.partition("#")[2]
                    yield _finding("S103", cid, f"ears:{label}", Kind.DEFECT, f"{label} has no 'shall'",
                                   "write it in EARS form: 'When <trigger>, the <part> shall <response>' "
                                   "(or 'The <part> shall ...', 'If ..., then ...', 'While ...')", cr.location)

    def compound_requirements(ctx: Context) -> Iterator[Finding]:
        g = ctx.graph
        for cid in g.ids():
            c = g[cid]
            words = _words(c.realizes)
            second = next((words[i + 1] for i, w in enumerate(words[:-1])
                           if w in ("and", "or") and words[i + 1] in lexicon.verbs), None)
            if second:
                yield _finding("S104", cid, f"compound:{second}", Kind.QUESTION,
                               f"what it realizes joins a second function ('... and {second} ...')",
                               "one function per requirement, and each needs its own solution: split it into two "
                               "components (`arch split`). A criterion pins down a function; it never adds one",
                               c.location)

    def readability(ctx: Context) -> Iterator[Finding]:
        """Short, single statements: INCOSE's rules on combinators, parentheses and length, made checkable."""
        g, design = ctx.graph, ctx.graph.design
        for nid, need in sorted(design.needs.items()):
            yield from _readable("need", nid, nid, need.statement, need.location)
        for cid in g.ids():
            c = g[cid]
            yield from _readable("realizes", cid, cid, c.realizes, c.location)
            yield from _readable("solution", cid, cid, c.solution, c.location)
            if c.hides:
                yield from _readable("hides", cid, cid, c.hides, c.location)
            for cr in c.criteria:
                yield from _readable("criterion", cid, cr.id, cr.text, cr.location)

    return (
        Rule(RuleId("S107"), Station.REQUIREMENTS, Text("statements are short and say one thing"), readability),
        Rule(RuleId("S101"), Station.NEEDS, Text("needs name outcomes, not solutions"), solution_in_needs),
        Rule(RuleId("S102"), Station.REQUIREMENTS, Text("criteria are measurable"), vague_criteria),
        Rule(RuleId("S103"), Station.REQUIREMENTS, Text("criteria are in EARS form"), non_ears),
        Rule(RuleId("S104"), Station.REQUIREMENTS, Text("one function per requirement"), compound_requirements),
    )


# Word limits per kind of statement; criteria may be longer because EARS adds a trigger clause.
WORD_LIMITS: dict[str, int] = {"need": 30, "realizes": 20, "solution": 25, "hides": 12, "criterion": 40}


def _readable(kind: str, subject: str, key: str, text: str, location) -> Iterator[Finding]:
    words = len(text.split())
    limit = WORD_LIMITS[kind]
    what = {"realizes": "what it must do", "criterion": key.partition("#")[2] or key}.get(kind, kind)
    if words > limit:
        yield _finding("S107", subject, f"long:{key}:{kind}", Kind.QUESTION,
                       f"{what} has {words} words (limit {limit})", "say one thing, in plain words; move detail into criteria",
                       location)
    if ";" in text:
        yield _finding("S108", subject, f"semicolon:{key}:{kind}", Kind.QUESTION, f"{what} joins statements with a semicolon",
                       "write one statement; split the rest out", location)
    if "(" in text and kind != "criterion":
        yield _finding("S108", subject, f"parenthesis:{key}:{kind}", Kind.QUESTION, f"{what} has a parenthetical",
                       "say it plainly, or leave it out", location)
    sentences = [s for s in text.replace("e.g.", "eg").split(". ") if s.strip()]
    if len(sentences) > 1 and kind in ("realizes", "solution", "hides"):
        yield _finding("S108", subject, f"sentences:{key}:{kind}", Kind.QUESTION, f"{what} has {len(sentences)} sentences",
                       "one statement only; put the rest in the rationale", location)


RULES: tuple[Rule, ...] = rules()

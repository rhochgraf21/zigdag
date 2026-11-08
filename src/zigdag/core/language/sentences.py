"""The grammars of the record's sentences (DESIGN2 §6.1 to §6.4), and parsers that never raise."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.tokens import Token, tokenize, words
from zigdag.core.findings import RuleName
from zigdag.core.texts import Say, SentenceText, Word


@dataclass(frozen=True)
class Problem:
    """Something wrong with a sentence. An exact problem breaks; a guess is a question."""

    rule: RuleName
    exact: bool
    say: Say


class Pattern(enum.Enum):
    UBIQUITOUS = "ubiquitous"
    EVENT = "event"
    STATE = "state"
    UNWANTED = "unwanted"
    OPTIONAL = "optional"
    COMPLEX = "complex"


@dataclass(frozen=True)
class DataClause:
    """A While or Where clause: the structure, its field (when named), and the value it must have."""

    structure: Word
    field: Word | None
    value: Word


@dataclass(frozen=True)
class Ears:
    tokens: tuple[Token, ...]
    where: DataClause | None
    while_: DataClause | None
    when: SentenceText | None
    if_: SentenceText | None
    subject: SentenceText
    negated: bool
    response: tuple[Token, ...]

    @property
    def pattern(self) -> Pattern:
        present = [p for p, c in ((Pattern.OPTIONAL, self.where), (Pattern.STATE, self.while_),
                                  (Pattern.EVENT, self.when), (Pattern.UNWANTED, self.if_)) if c is not None]
        if not present:
            return Pattern.UBIQUITOUS
        return present[0] if len(present) == 1 else Pattern.COMPLEX


EARS = "ears"
OUTCOME = "outcome"
JOB = "job"
PERFORMER = "performer"


def _join(tokens: tuple[Token, ...]) -> str:
    return " ".join(t.text for t in tokens)


def _data_clause(tokens: tuple[Token, ...], keyword: str, feature: bool) -> tuple[DataClause | None, str | None]:
    """Parse "the STRUCTURE['s FIELD] is VALUE"; returns the clause, or the reason it does not fit."""
    lower = [t.lower for t in tokens]
    if not lower or lower[0] != "the" or "is" not in lower:
        return None, f'a "{keyword}" clause must read "the <structure> is <value>"'
    at = len(lower) - 1 - lower[::-1].index("is")
    named, value = tokens[1:at], tokens[at + 1:]
    split = next((i for i, t in enumerate(named) if t.text in ("'s", "'", "’")), None)
    structure = named if split is None else named[:split]
    field = None if split is None else named[split + 1:]
    if not structure or (field is not None and not field) or not value:
        return None, f'a "{keyword}" clause must name a structure, optionally its field, and a value'
    if feature and [t.lower for t in value] not in (["enabled"], ["disabled"]):
        return None, 'a "Where" clause must end in "is enabled" or "is disabled"'
    return DataClause(_lowered(structure), _lowered(field) if field else None, _lowered(value)), None


def _lowered(tokens: tuple[Token, ...]) -> str:
    return " ".join(t.lower for t in tokens)


def parse_ears(text: SentenceText, lexicons: Lexicons) -> tuple[Ears | None, tuple[Problem, ...]]:
    tokens = tokenize(text)
    if not tokens or tokens[-1].text != ".":
        return None, (Problem(EARS, True, "an EARS statement ends with a full stop"),)
    body = tokens[:-1]
    lower = [t.lower for t in body]
    i = 0

    def clause(keyword: str) -> tuple[tuple[Token, ...], str | None]:
        nonlocal i
        if "," not in lower[i:]:
            return (), f'a "{keyword}" clause ends with a comma'
        end = lower.index(",", i)
        part, i = body[i + 1:end], end + 1
        return part, None if part else f'a "{keyword}" clause cannot be empty'

    where = while_ = None
    when = if_ = None
    if i < len(lower) and lower[i] == "where":
        part, problem = clause("Where")
        if problem:
            return None, (Problem(EARS, True, problem),)
        where, problem = _data_clause(part, "Where", feature=True)
        if problem:
            return None, (Problem(EARS, True, problem),)
    if i < len(lower) and lower[i] == "while":
        part, problem = clause("While")
        if problem:
            return None, (Problem(EARS, True, problem),)
        while_, problem = _data_clause(part, "While", feature=False)
        if problem:
            return None, (Problem(EARS, True, problem),)
    if i < len(lower) and lower[i] == "when":
        part, problem = clause("When")
        if problem:
            return None, (Problem(EARS, True, problem),)
        when = _join(part)
    elif i < len(lower) and lower[i] == "if":
        part, problem = clause("If")
        if problem:
            return None, (Problem(EARS, True, problem),)
        if i >= len(lower) or lower[i] != "then":
            return None, (Problem(EARS, True, 'an "If" clause is followed by "then"'),)
        if_, i = _join(part), i + 1
    if i >= len(lower) or lower[i] != "the" or "shall" not in lower[i:]:
        return None, (Problem(EARS, True, 'the main clause must read "the <name> shall <response>"'),)
    shall = lower.index("shall", i)
    subject_tokens = body[i + 1:shall]
    if not subject_tokens:
        return None, (Problem(EARS, True, 'the main clause names its subject: "the <name> shall"'),)
    rest = body[shall + 1:]
    negated = bool(rest) and rest[0].lower == "not"
    response = rest[1:] if negated else rest
    if not response or not response[0].is_word:
        return None, (Problem(EARS, True, 'a response follows "shall"'),)
    problems = ()
    if response[0].lower not in lexicons.verbs:
        problems = (Problem(EARS, True, f'the response starts with a verb, not "{response[0].text}"'),)
    ears = Ears(tokens, where, while_, when, if_, " ".join(t.lower for t in subject_tokens), negated, response)
    return ears, problems


_MEASURES = (
    ("time", "it", "takes", "to"),
    ("time", "between"),
    ("likelihood", "that"),
    ("number", "of"),
    ("amount", "of"),
    ("frequency", "of"),
)


def parse_outcome(text: SentenceText) -> tuple[Problem, ...]:
    w = words(tokenize(text))
    if w[:2] != ("minimize", "the"):
        return (Problem(OUTCOME, True, 'an outcome starts "Minimize the"'),)
    rest = w[2:]
    measure = next((m for m in _MEASURES if rest[: len(m)] == m), None)
    if measure is None:
        forms = "; ".join(" ".join(m) for m in _MEASURES)
        return (Problem(OUTCOME, True, f'after "Minimize the" comes one of: {forms}'),)
    phrase = rest[len(measure):]
    if measure == ("time", "between"):
        if "and" not in phrase or phrase.index("and") in (0, len(phrase) - 1):
            return (Problem(OUTCOME, True, 'a "time between" outcome names two moments joined by "and"'),)
    elif not phrase:
        return (Problem(OUTCOME, True, f'"{" ".join(measure)}" is followed by what is measured'),)
    return ()


def parse_job(text: SentenceText, lexicons: Lexicons) -> tuple[Problem, ...]:
    w = words(tokenize(text))
    if not w:
        return (Problem(JOB, True, "a job cannot be empty"),)
    if w[0] not in lexicons.verbs:
        return (Problem(JOB, True, f'a job starts with a verb, not "{w[0]}"'),)
    if len(w) < 2:
        return (Problem(JOB, True, "a job names what the verb acts on"),)
    return ()


def parse_performer(text: SentenceText) -> tuple[Problem, ...]:
    return () if words(tokenize(text)) else (Problem(PERFORMER, True, "a performer cannot be empty"),)

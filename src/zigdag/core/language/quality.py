"""The quality checks on sentences (DESIGN2 §6.5): INCOSE's atomic, measurable, specific, active and readable."""

from __future__ import annotations

from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.sentences import Ears, Problem
from zigdag.core.language.tokens import Token, contains_phrase, tokenize, words
from zigdag.core.measures import Count
from zigdag.core.texts import SentenceText, Word

ATOMIC = "quality.atomic"
MEASURABLE = "quality.measurable"
SPECIFIC = "quality.specific"
ACTIVE = "quality.active"
SOLUTION_FREE = "quality.solution-free"
READABLE = "quality.readable"

STATEMENT_WORDS = 40
JOB_AND_OUTCOME_WORDS = 30

_BOUNDS = ("within", "under", "over", "at most", "at least", "less than", "more than", "up to")
_NOT_COMPARISONS = frozenset({("no", "longer"), ("any", "longer"), ("no", "more"), ("any", "more")})  # "not anymore"
_IRREGULAR_PARTICIPLES = frozenset("""
born broken brought built chosen done drawn driven eaten fallen found given gone grown held hidden kept known laid
led left lost made meant met paid put read run said seen sent set shown shut spent split taken taught thought told
understood won written
""".split())


def readable(text: SentenceText, limit: Count) -> tuple[Problem, ...]:
    tokens = tokenize(text)
    problems = []
    inner = tokens[:-1] if tokens and tokens[-1].text == "." else tokens
    if any(t.text in ".!?" for t in inner):
        problems.append(Problem(READABLE, True, "write one sentence"))
    if (n := len(words(tokens))) > limit:
        problems.append(Problem(READABLE, True, f"{n} words; keep it to {limit}"))
    if any(t.text == ";" for t in tokens):
        problems.append(Problem(READABLE, True, "no semicolons: split it, or say less"))
    if any(t.text in "()[]{}" for t in tokens):
        problems.append(Problem(READABLE, True, "no brackets: say it in the sentence, or leave it out"))
    return tuple(problems)


def _found(word_list: tuple[str, ...], lexicon: frozenset[str]) -> list[str]:
    """Lexicon entries present in the words, single words and phrases alike, in sorted order."""
    return sorted(e for e in lexicon if (" " in e and contains_phrase(word_list, e)) or (" " not in e and e in word_list))


def solution_words(text: SentenceText, lexicons: Lexicons, ignore: tuple[Word, ...] = ()) -> tuple[Problem, ...]:
    w = tuple(x for x in words(tokenize(text)) if x not in ignore)
    return tuple(Problem(SOLUTION_FREE, False, f'"{x}" names a solution, not a need') for x in _found(w, lexicons.solution_words))


def vague_words(text: SentenceText, lexicons: Lexicons) -> tuple[Problem, ...]:
    w = words(tokenize(text))
    return tuple(Problem(MEASURABLE, False, f'"{x}" is vague: give a number or an observable condition')
                 for x in _found(w, lexicons.vague_words))


def _response_joins_verbs(response: tuple[Token, ...], lexicons: Lexicons) -> list[str]:
    w = words(response)
    return [f"{a} {b}" for a, b in zip(w, w[1:]) if a in ("and", "or") and b in lexicons.verbs]


def _unitless_bounds(tokens: tuple[Token, ...], lexicons: Lexicons) -> list[str]:
    """Numbers after a bound word ("within 5") that have no unit after them."""
    lower = [t.lower for t in tokens]
    out = []
    for i, t in enumerate(tokens):
        if not t.is_number or t.hyphen_unit:
            continue
        before = " ".join(lower[max(0, i - 2):i])
        if not any(before == b or before.endswith(" " + b) for b in _BOUNDS):
            continue
        unit = lower[i + 1] if i + 1 < len(lower) else None
        if unit not in lexicons.units:
            out.append(t.text)
    return out


def ears_quality(ears: Ears, lexicons: Lexicons) -> tuple[Problem, ...]:
    tokens = ears.tokens
    w = words(tokens)
    text = " ".join(t.text for t in tokens)
    problems: list[Problem] = []
    if (shalls := w.count("shall")) != 1:
        problems.append(Problem(ATOMIC, True, f'use "shall" exactly once, not {shalls} times'))
    for pair in _response_joins_verbs(ears.response, lexicons):
        problems.append(Problem(ATOMIC, False, f'"{pair}" may join two responses: one function per statement'))
    if any(a.text == "and" and b.text == "/" for a, b in zip(tokens, tokens[1:])):
        problems.append(Problem(ATOMIC, True, 'no "and/or": say which one'))
    problems += vague_words(text, lexicons)
    for number in _unitless_bounds(tokens, lexicons):
        problems.append(Problem(MEASURABLE, True, f'"{number}" needs a unit'))
    for i, x in enumerate(w):
        idiom = i > 0 and (w[i - 1], x) in _NOT_COMPARISONS
        if x in lexicons.comparatives and not idiom and "than" not in w[i + 1:]:
            problems.append(Problem(MEASURABLE, False, f'"{x}" than what? Give the reference'))
    for x in sorted(set(w) & lexicons.pronouns):
        problems.append(Problem(SPECIFIC, True, f'"{x}" is a pronoun: name the thing'))
    for x in _found(w, lexicons.escape_clauses):
        problems.append(Problem(SPECIFIC, True, f'"{x}" is an escape clause: state when it applies'))
    for x in _found(w, lexicons.open_endings):
        problems.append(Problem(SPECIFIC, True, f'"{x}" leaves the list open: list everything, or say what holds'))
    for x in sorted(set(w) & lexicons.modals):
        problems.append(Problem(SPECIFIC, True, f'"{x}" is a modal: use "shall"'))
    for i, x in enumerate(w[:-2]):
        if x == "shall" and w[i + 1] == "be" and (w[i + 2].endswith("ed") or w[i + 2] in _IRREGULAR_PARTICIPLES):
            problems.append(Problem(ACTIVE, False, f'"shall be {w[i + 2]}" is passive: say who does it'))
    problems += readable(text, STATEMENT_WORDS)
    return tuple(problems)


def named_solutions(ears: Ears, lexicons: Lexicons) -> tuple[Problem, ...]:
    """The words of an EARS statement that name a solution rather than a need: for statements that must stay free
    of them."""
    return tuple(solution_words(Word(" ".join(t.text for t in ears.tokens)), lexicons,
                                ignore=tuple(Word(w) for w in ears.subject.split())))

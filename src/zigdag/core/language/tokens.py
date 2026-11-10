"""Splitting a sentence into tokens: words, numbers and punctuation."""

from __future__ import annotations

import re
from dataclasses import dataclass

import deal

from zigdag.core.measures import Offset
from zigdag.core.texts import SentenceText, Word

# Numbers (10,000-line), words with dots, hyphens or underscores (emit.translator_names), possessives, punctuation.
_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?(?:-\w+)*|\w+(?:[-.]\w+)*|'s\b|['’]|[^\s\w]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?(?:-\w+)*")
_WORD_START = re.compile(r"\w")  # a letter, a digit or an underscore


@dataclass(frozen=True)
class Token:
    text: Word  # never empty: tokenize makes no empty token
    start: Offset  # character offset in the sentence

    @property
    @deal.ensure(lambda self, result: result == self.text.lower())
    def lower(self) -> Word:
        return self.text.lower()

    @property
    @deal.ensure(lambda self, result: result == bool(_WORD_START.match(self.text)))
    def is_word(self) -> bool:
        return self.text[0].isalnum() or self.text[0] == "_"

    @property
    @deal.ensure(lambda self, result: not result or self.text[0].isdigit())
    def is_number(self) -> bool:
        return bool(_NUMBER.fullmatch(self.text))

    @property
    @deal.ensure(lambda self, result: result is None or (self.is_number and self.lower.endswith(f"-{result}")))
    def hyphen_unit(self) -> Word | None:
        """For a number such as 10,000-line, the unit after the hyphen."""
        number, dash, unit = self.text.partition("-")
        return unit.lower() if dash and _NUMBER.fullmatch(number) else None


@deal.ensure(lambda text, result: all(t.text and text[t.start:t.start + len(t.text)] == t.text for t in result))
@deal.ensure(lambda text, result: all(a.start + len(a.text) <= b.start for a, b in zip(result, result[1:])))
def tokenize(text: SentenceText) -> tuple[Token, ...]:
    return tuple(Token(m.group(), m.start()) for m in _TOKEN.finditer(text))


@deal.pre(lambda tokens: all(t.text for t in tokens))  # tokens as tokenize makes them
@deal.ensure(lambda tokens, result: len(result) <= len(tokens) and all(w == w.lower() for w in result))
def words(tokens: tuple[Token, ...]) -> tuple[Word, ...]:
    """The words, lowercased, in order."""
    return tuple(t.lower for t in tokens if t.is_word)


def contains_phrase(word_list: tuple[str, ...], phrase: str) -> bool:
    """Whether the words contain the phrase as consecutive whole words."""
    return f" {phrase} " in f" {' '.join(word_list)} "

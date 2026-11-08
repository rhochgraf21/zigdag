"""Splitting a sentence into tokens: words, numbers and punctuation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from zigdag.core.measures import Offset
from zigdag.core.texts import SentenceText, Word

# Numbers (10,000-line), words with dots, hyphens or underscores (emit.translator_names), possessives, punctuation.
_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?(?:-\w+)*|\w+(?:[-.]\w+)*|'s\b|['’]|[^\s\w]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?(?:-\w+)*")


@dataclass(frozen=True)
class Token:
    text: Word
    start: Offset  # character offset in the sentence

    @property
    def lower(self) -> Word:
        return self.text.lower()

    @property
    def is_word(self) -> bool:
        return self.text[0].isalnum() or self.text[0] == "_"

    @property
    def is_number(self) -> bool:
        return bool(_NUMBER.fullmatch(self.text))

    @property
    def hyphen_unit(self) -> Word | None:
        """For a number such as 10,000-line, the unit after the hyphen."""
        number, dash, unit = self.text.partition("-")
        return unit.lower() if dash and _NUMBER.fullmatch(number) else None


def tokenize(text: SentenceText) -> tuple[Token, ...]:
    return tuple(Token(m.group(), m.start()) for m in _TOKEN.finditer(text))


def words(tokens: tuple[Token, ...]) -> tuple[Word, ...]:
    """The words, lowercased, in order."""
    return tuple(t.lower for t in tokens if t.is_word)


def contains_phrase(word_list: tuple[str, ...], phrase: str) -> bool:
    """Whether the words contain the phrase as consecutive whole words."""
    return f" {phrase} " in f" {' '.join(word_list)} "

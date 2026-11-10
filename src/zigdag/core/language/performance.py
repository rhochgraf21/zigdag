"""The performance phrases of a statement (DESIGN2 §6.4, §4.7): the bounds it puts on time, memory, scaling and
steadiness, each in the unit zigdag measures in."""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.core.language.tokens import Token, tokenize
from zigdag.core.measures import Bytes, Power, Seconds
from zigdag.core.texts import Say, SentenceText, Word


class Characteristic(enum.Enum):
    """What a performance phrase bounds, and so what a test must measure."""

    TIME = "time"
    MEMORY = "memory"
    SCALING = "scaling"
    STEADINESS = "steadiness"


_BOUND_WORDS = (("within",), ("under",), ("at", "most"), ("less", "than"), ("up", "to"))
_SECONDS: Mapping[str, float] = {
    **dict.fromkeys(("ns", "nanosecond", "nanoseconds"), 1e-9),
    **dict.fromkeys(("us", "microsecond", "microseconds"), 1e-6),
    **dict.fromkeys(("ms", "millisecond", "milliseconds"), 1e-3),
    **dict.fromkeys(("s", "sec", "second", "seconds"), 1.0),
    **dict.fromkeys(("min", "minute", "minutes"), 60.0),
    **dict.fromkeys(("h", "hour", "hours"), 3600.0),
}
_KIB = 1024  # memory is measured in binary units, as the interpreter and the operating system report it
_BYTES: Mapping[str, int] = {**dict.fromkeys(("b", "byte", "bytes"), 1), "kb": _KIB, "mb": _KIB ** 2,
                              "gb": _KIB ** 3}
_GROWTH: Mapping[Word, Power] = {Word("linearly"): Power(1.0), Word("quadratically"): Power(2.0)}
_GROWS = ("grows", "at", "most")  # in time that grows at most linearly with ...
_STEADY = ("keeping", "memory", "steady", "across", "repeated")


@dataclass(frozen=True)
class Bound:
    """One limit a statement puts on performance, in the unit zigdag measures it in."""

    characteristic: Characteristic
    limit: float  # seconds for time, bytes for memory, the power of the size for scaling; none for steadiness
    said: Say  # the phrase as the statement writes it

    @property
    @deal.ensure(lambda self, result: result.startswith("the "))
    def what(self) -> Say:
        """What it bounds, in words: the time, the memory."""
        return Say(f"the {self.characteristic.value}")


def _at(tokens: tuple[Token, ...], i: int, phrase: tuple[str, ...]) -> bool:
    return tuple(t.lower for t in tokens[i:i + len(phrase)]) == phrase


def _said(tokens: tuple[Token, ...], start: int, end: int) -> Say:
    return Say(" ".join(t.text for t in tokens[start:end]))


def _number(token: Token) -> float | None:
    return float(token.text.replace(",", "")) if token.is_number and not token.hyphen_unit else None


def _amount(tokens: tuple[Token, ...], i: int) -> Bound | None:
    """A bound word, a number and a unit, starting at i: its unit says whether it is time or memory."""
    words = next((w for w in _BOUND_WORDS if _at(tokens, i, w)), None)
    if words is None or i + len(words) + 1 >= len(tokens):
        return None
    number, unit = _number(tokens[i + len(words)]), tokens[i + len(words) + 1].lower
    if number is None:
        return None
    said = _said(tokens, i, i + len(words) + 2)
    if unit in _SECONDS:
        return Bound(Characteristic.TIME, Seconds(number * _SECONDS[unit]), said)
    if unit in _BYTES:
        return Bound(Characteristic.MEMORY, Bytes(round(number * _BYTES[unit])), said)
    return None


def _growth(tokens: tuple[Token, ...], i: int) -> Bound | None:
    if not _at(tokens, i, _GROWS) or i + len(_GROWS) >= len(tokens):
        return None
    power = _GROWTH.get(tokens[i + len(_GROWS)].lower)
    return Bound(Characteristic.SCALING, power, _said(tokens, i, i + len(_GROWS) + 1)) if power else None


@deal.ensure(lambda text, result: all(b.said in text for b in result))  # each as the statement writes it
@deal.ensure(lambda text, result: all(b.limit > 0 or b.characteristic is Characteristic.STEADINESS for b in result))
def bounds(text: SentenceText) -> tuple[Bound, ...]:
    """Every performance bound a statement puts, in the order it writes them."""
    tokens = tokenize(text)
    out = []
    for i in range(len(tokens)):
        found = _amount(tokens, i) or _growth(tokens, i)
        if found is None and _at(tokens, i, _STEADY):
            found = Bound(Characteristic.STEADINESS, 0.0, _said(tokens, i, i + len(_STEADY)))
        if found is not None:
            out.append(found)
    return tuple(out)

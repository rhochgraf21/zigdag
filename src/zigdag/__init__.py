"""zigdag: zigzag from needs to code, and keep it a DAG."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")


def verifies(*targets: str) -> Callable[[_T], _T]:
    """Mark a test as evidence for FR statements (fr#statement) or constraint statements (DESIGN2 §4.3)."""

    def mark(test: _T) -> _T:
        test.__zigdag_verifies__ = targets  # type: ignore[attr-defined]
        return test

    return mark

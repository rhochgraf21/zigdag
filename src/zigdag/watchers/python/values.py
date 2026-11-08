"""Judging Python values at runtime: their type's name, whether they fit an annotation, and a fingerprint of their
contents that two equal values share, so a change in place or a different result can be seen."""

from __future__ import annotations

import collections.abc as abc
import dataclasses
import enum
import hashlib
import types
import typing

SAMPLED = 3  # the elements of a collection checked against its annotation
DEPTH = 6  # how deep a fingerprint looks into a value
_ITERATORS = (abc.Iterator, abc.Generator, abc.AsyncIterator, abc.AsyncGenerator, abc.Iterable, abc.AsyncIterable)


def type_name(value: object) -> str:
    """The qualified name of a value's own type: builtins.str, shop.orders.Order."""
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"


def conforms(value: object, hint: object) -> bool | None:
    """Whether a value fits an annotation; None when that cannot be told. A distinct named type is checked as its
    base type, since that is all it is at runtime."""
    try:
        return _conforms(value, hint)
    except Exception:  # noqa: BLE001 (an annotation zigdag cannot judge is not a finding)
        return None


def _all(results: typing.Iterable[bool | None]) -> bool | None:
    seen = list(results)
    return False if False in seen else (None if None in seen else True)


def _conforms(value: object, hint: object) -> bool | None:
    if hint is typing.Any or hint is object:
        return True
    if hint is None or hint is type(None):
        return value is None
    if isinstance(hint, typing.NewType):
        return _conforms(value, hint.__supertype__)
    if isinstance(hint, typing.TypeVar | typing.ForwardRef | str):
        return None
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin is typing.Union or origin is types.UnionType:
        results = [_conforms(value, a) for a in args]
        return True if True in results else (None if None in results else False)
    if origin is typing.Literal:
        return value in args
    if origin is typing.Annotated:
        return _conforms(value, args[0])
    if origin is type:
        return isinstance(value, type)
    if origin in (abc.Callable,):
        return callable(value)
    if origin is not None and isinstance(origin, type):
        if not isinstance(value, origin):
            return False
        if origin in _ITERATORS or not args:
            return True
        if issubclass(origin, tuple):
            items = list(value)
            if len(args) == 2 and args[1] is ...:
                return _all(_conforms(v, args[0]) for v in items[:SAMPLED])
            return len(items) == len(args) and _all(_conforms(v, a) for v, a in zip(items, args))
        if issubclass(origin, abc.Mapping) and len(args) == 2:
            pairs = list(value.items())[:SAMPLED]
            return _all(r for k, v in pairs for r in (_conforms(k, args[0]), _conforms(v, args[1])))
        if issubclass(origin, abc.Collection):
            return _all(_conforms(v, args[0]) for v in list(value)[:SAMPLED])
        return True
    if isinstance(hint, type):
        if hint is float and isinstance(value, int):
            return True
        if hint is complex and isinstance(value, int | float):
            return True
        try:
            return isinstance(value, hint)
        except TypeError:  # a protocol that cannot be checked at runtime
            return None
    return None


def fingerprint(value: object) -> str | None:
    """A digest of what a value holds; None when part of it cannot be compared, such as an object with no
    contents to read."""
    parts: list[str] = []
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16] if _walk(value, parts, DEPTH, set()) else None


def _walk(value: object, out: list[str], depth: int, seen: set[int]) -> bool:
    if value is None or isinstance(value, bool | int | float | complex | str | bytes | enum.Enum):
        out.append(f"{type_name(value)}:{value!r}")
        return True
    if depth == 0 or id(value) in seen:
        out.append("…")
        return True
    seen = seen | {id(value)}
    out.append(type_name(value))
    if isinstance(value, abc.Mapping):
        items = sorted(value.items(), key=lambda kv: repr(kv[0]))
        return all(_walk(k, out, depth - 1, seen) and _walk(v, out, depth - 1, seen) for k, v in items)
    if isinstance(value, abc.Set):
        prints = sorted(fingerprint(v) or "?" for v in value)
        out.extend(prints)
        return "?" not in prints
    if isinstance(value, list | tuple | abc.Sequence):
        return all(_walk(v, out, depth - 1, seen) for v in value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return all(_walk(getattr(value, f.name), out, depth - 1, seen) for f in dataclasses.fields(value))
    contents = fields_of(value)
    if contents is None:
        return False
    return all(_walk(v, out, depth - 1, seen) for _, v in sorted(contents.items()))


def fields_of(value: object) -> dict[str, object] | None:
    """An object's own fields, from its __dict__ or its slots; None when it has neither."""
    own = getattr(value, "__dict__", None)
    if isinstance(own, dict):
        return dict(own)
    slots = [s for k in type(value).__mro__ for s in getattr(k, "__slots__", ())]
    if not slots:
        return None
    return {s: getattr(value, s) for s in slots if isinstance(s, str) and hasattr(value, s)}

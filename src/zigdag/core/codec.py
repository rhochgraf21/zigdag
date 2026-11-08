"""The code model's values as JSON, read back exactly: what one process hands another, such as what a test watcher
should watch and what it saw. Frozen dataclasses, enums, named types, tuples, sets and mappings round-trip; text that
does not fit its type is refused whole, never half-read, and reading never raises.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass
import json
import types
import typing
from collections.abc import Mapping
from functools import cache
from typing import TypeVar
from zigdag.core.texts import FileText, Say

T = TypeVar("T")


class _Misfit(Exception):
    """Text that does not fit the type it is read as."""


@dataclass(frozen=True)
class Unreadable:
    """Text that was refused, and why."""

    say: Say


def encode(value: object) -> object:
    """A JSON-ready form of a value: dataclasses as objects, enums as their values, sets in sorted order."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): encode(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, frozenset | set):
        return sorted((encode(v) for v in value), key=json.dumps)
    if isinstance(value, tuple | list):
        return [encode(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return repr(value)  # not a value of the code model: kept as text, and refused when it is read back


def dumps(value: object) -> FileText:
    return json.dumps(encode(value), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def loads(kind: type[T], text: FileText) -> T | Unreadable:
    """The value of the given type that the text holds, or why it holds none."""
    try:
        return _decode(kind, json.loads(text))
    except json.JSONDecodeError as e:
        return Unreadable(f"not JSON: {e}")
    except _Misfit as e:
        return Unreadable(str(e))


@cache
def _hints(cls: type) -> Mapping[str, object]:
    return typing.get_type_hints(cls)


def _decode(kind: object, data: object) -> typing.Any:
    """The value of the given type that `data` encodes."""
    if isinstance(kind, typing.NewType):
        return _decode(kind.__supertype__, data)
    origin, args = typing.get_origin(kind), typing.get_args(kind)
    if origin is typing.Union or origin is types.UnionType:
        if data is None and type(None) in args:
            return None
        return _decode(next(a for a in args if a is not type(None)), data)
    if origin is tuple:
        items = _list(data)
        if args[-1] is ...:
            return tuple(_decode(args[0], d) for d in items)
        if len(items) != len(args):
            raise _Misfit(f"expected {len(args)} items, not {len(items)}")
        return tuple(_decode(a, d) for a, d in zip(args, items))
    if origin in (frozenset, set):
        return frozenset(_decode(args[0], d) for d in _list(data))
    if origin in (dict, Mapping):
        if not isinstance(data, dict):
            raise _Misfit(f"expected an object, not {data!r}")
        return {_decode(args[0], k): _decode(args[1], v) for k, v in data.items()}
    if isinstance(kind, type) and dataclasses.is_dataclass(kind):
        if not isinstance(data, dict):
            raise _Misfit(f"expected a {kind.__name__}, not {data!r}")
        hints = _hints(kind)
        given = {f.name: _decode(hints[f.name], data[f.name]) for f in dataclasses.fields(kind) if f.name in data}
        try:
            return kind(**given)
        except TypeError as e:
            raise _Misfit(f"{kind.__name__}: {e}") from e
    if isinstance(kind, type) and issubclass(kind, enum.Enum):
        try:
            return kind(data)
        except ValueError as e:
            raise _Misfit(str(e)) from e
    if kind is float and isinstance(data, int | float) and not isinstance(data, bool):
        return float(data)
    if kind in (str, int, bool) and type(data) is kind:
        return data
    if kind is type(None) and data is None:
        return None
    raise _Misfit(f"expected {kind}, not {data!r}")


def _list(data: object) -> list:
    if not isinstance(data, list):
        raise _Misfit(f"expected a list, not {data!r}")
    return data

"""Check parameters: their schema, and turning the record's text into typed values."""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import deal

from zigdag.core.effects import Effect
from zigdag.core.names import ParamName
from zigdag.core.texts import Word, Written


EffectTest = Callable[[str], bool]  # whether a name is an effect the project knows


class ParamType(enum.Enum):
    COUNT = "count"  # a whole number, 0 or more
    RATIO = "ratio"  # a number, 0 or more
    CHOICE = "choice"  # one of a fixed set of words
    EFFECTS = "effects"  # a list of effects
    NAMES = "names"  # a list of FR names, libraries or type names
    TEXT = "text"


@dataclass(frozen=True)
class ParamSpec:
    type: ParamType
    default: object = None  # None means the parameter must be given
    choices: tuple[Word, ...] = ()


ParamSchema = Mapping[str, ParamSpec]
Params = Mapping[str, object]  # int, float, str, or a tuple of Effect or str


@dataclass(frozen=True)
class ParamProblem:
    param: str
    say: str


@deal.ensure(lambda schema, raw, is_effect, result: set(result[0]) <= set(schema))
@deal.ensure(lambda schema, raw, is_effect, result: bool(result[1]) or set(result[0]) == set(schema))  # all, or why not
def convert(
    schema: ParamSchema,
    raw: Mapping[ParamName, Written | tuple[Written, ...]],
    is_effect: EffectTest,
) -> tuple[Params, tuple[ParamProblem, ...]]:
    """The typed parameters, with defaults filled in, and what is wrong with the ones given."""
    out: dict[str, object] = {}
    problems: list[ParamProblem] = []
    for name in sorted(set(raw) - set(schema)):
        known = ", ".join(sorted(schema)) or "none"
        problems.append(ParamProblem(name, f'"{name}" is not a parameter of this check (it takes: {known})'))
    for name, spec in schema.items():
        if name not in raw:
            if spec.default is None:
                problems.append(ParamProblem(name, f'"{name}" must be given'))
            else:
                out[name] = spec.default
            continue
        value, problem = _one(spec, raw[name], is_effect)
        if problem:
            problems.append(ParamProblem(name, f'"{name}": {problem}'))
        else:
            out[name] = value
    return out, tuple(problems)


def _one(spec: ParamSpec, value: str | tuple[str, ...], is_effect: Callable[[str], bool]) -> tuple[object, str | None]:
    listed = spec.type in (ParamType.EFFECTS, ParamType.NAMES)
    if listed != isinstance(value, tuple):
        return None, "must be a list" if listed else "must be a single value"
    if spec.type is ParamType.COUNT:
        return (int(value), None) if value.isdigit() else (None, f'"{value}" is not a whole number')
    if spec.type is ParamType.RATIO:
        try:
            number = float(value)
        except ValueError:
            return None, f'"{value}" is not a number'
        return (number, None) if number >= 0 else (None, "cannot be negative")
    if spec.type is ParamType.CHOICE:
        return (value, None) if value in spec.choices else (None, f"must be one of {', '.join(spec.choices)}")
    if spec.type is ParamType.EFFECTS:
        unknown = [e for e in value if not is_effect(e)]
        return (None, f"unknown effects: {', '.join(unknown)}") if unknown else (tuple(map(Effect, value)), None)
    return value, None

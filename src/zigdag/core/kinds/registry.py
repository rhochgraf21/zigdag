"""The registry of check kinds (DESIGN2 §4.1): each kind's parameters, what it reads, and the sentence it renders.

Structure in, sentence out: a rule is written as structure, and its sentence comes from here. Every sentence
must itself be a valid EARS statement, which the record rules check.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from zigdag.core.kinds.params import ParamSchema, Params, ParamSpec, ParamType
from zigdag.core.effects import phrase
from zigdag.core.names import CheckKindName


class Part(enum.Enum):
    """The parts of the code model (§5.1), plus the record and git history, that a check can read."""

    RECORD = "record"
    UNITS = "units"
    PUBLIC_NAMES = "public names"
    DEPENDENCIES = "dependencies"
    SYMBOLS = "symbols"
    STRUCTURES = "structures"
    CALLS_AND_EFFECTS = "calls and effects"
    PERMISSIONS = "permissions and connections"
    TESTS = "tests"
    OBSERVATIONS = "observations"
    HISTORY = "history"


class Exactness(enum.Enum):
    EXACT = "exact"  # a failure breaks
    GUESS = "guess"  # a failure is a question
    BOTH = "both"  # some failures break, others are questions


Sentence = Callable[[str, Params, tuple[str, ...]], str]  # (subject, params, excepted code names) -> EARS


@dataclass(frozen=True)
class CheckKind:
    name: CheckKindName
    params: ParamSchema
    reads: frozenset[Part]
    exactness: Exactness
    sentence: Sentence


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def _excepted(excepted: tuple[str, ...]) -> str:
    return f", except in {_and(list(excepted))}" if excepted else ""


def _last(name: str) -> str:
    return name.rpartition(".")[2].replace("_", " ")


def _effects(s: str, p: Params, x: tuple[str, ...]) -> str:
    allowed = [phrase(e) for e in p["allow"]]
    other = f" other than {_and(allowed)}" if allowed else ""
    return f"The {s} shall have no side effects{other}{_excepted(x)}."


def _depends(s: str, p: Params, x: tuple[str, ...]) -> str:
    targets = [_last(n) for n in p["allow"]] or ["the standard library"]
    return f"The {s} shall depend only on {_and(targets)}{_excepted(x)}."


def _fixed(text: str) -> Sentence:
    return lambda s, p, x: f"The {s} shall {text}{_excepted(x)}."


EFFECTS = CheckKindName("effects")
DATA_FLOW = CheckKindName("data-flow")
MUTATION = CheckKindName("mutation")
PLANNED_EFFECTS = CheckKindName("planned-effects")

_C = frozenset
_P = Part
_EFFECTS = {"allow": ParamSpec(ParamType.EFFECTS)}

_KINDS = (
    CheckKind(EFFECTS, _EFFECTS, _C({_P.CALLS_AND_EFFECTS}), Exactness.EXACT, _effects),
    CheckKind(CheckKindName("may-depend-on"), {"allow": ParamSpec(ParamType.NAMES)},
              _C({_P.DEPENDENCIES}), Exactness.EXACT, _depends),
    CheckKind(CheckKindName("encapsulation"), {}, _C({_P.DEPENDENCIES, _P.PUBLIC_NAMES}), Exactness.EXACT,
              _fixed("reach each other design parameter only through the public names of that design parameter")),
    CheckKind(CheckKindName("container-boundaries"), {}, _C({_P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("not import code from another container")),
    CheckKind(CheckKindName("data-ownership"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("change each structure only from the component that owns the structure")),
    CheckKind(CheckKindName("no-cycles"), {}, _C({_P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("keep the dependencies between sibling design parameters free of cycles")),
    CheckKind(CheckKindName("declared-libraries"), {}, _C({_P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("import only the standard library and declared or vendored packages")),
    CheckKind(CheckKindName("edge-types"),
              {"bool-returns": ParamSpec(ParamType.CHOICE, "allowed", ("allowed", "forbidden"))},
              _C({_P.SYMBOLS, _P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("pass only project-defined types between components")),
    CheckKind(CheckKindName("declared-errors"), {}, _C({_P.SYMBOLS, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("raise only declared errors of project-defined types between components")),
    CheckKind(CheckKindName("representations-agree"), {}, _C({_P.STRUCTURES}), Exactness.EXACT,
              _fixed("keep every representation of a structure in agreement")),
    CheckKind(CheckKindName("messages-agree"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("use one structure for every message on a queue")),
    CheckKind(CheckKindName("endpoints-agree"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("use the structures of an endpoint when calling the endpoint")),
    CheckKind(CheckKindName("references-resolve"), {}, _C({_P.STRUCTURES}), Exactness.EXACT,
              _fixed("refer only to recorded structures")),
    CheckKind(CheckKindName("access-sanity"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.GUESS,
              _fixed("read each stored structure that a design parameter creates")),
    CheckKind(DATA_FLOW,
              {"data": ParamSpec(ParamType.NAMES), "never-reaches": ParamSpec(ParamType.EFFECTS)},
              _C({_P.SYMBOLS, _P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              lambda s, p, x: f"The {s} shall not use {_and([_last(d) for d in p['data']])} values when "
                              f"{_or([phrase(e) for e in p['never-reaches']])}{_excepted(x)}."),
    CheckKind(CheckKindName("one-writer-per-data-store"), {}, _C({_P.CALLS_AND_EFFECTS}), Exactness.EXACT,
              _fixed("give each data container exactly one writing container")),
    CheckKind(CheckKindName("permitted-effects"), {}, _C({_P.CALLS_AND_EFFECTS, _P.PERMISSIONS}), Exactness.EXACT,
              _fixed("use only the access that the infrastructure grants")),
    CheckKind(CheckKindName("least-privilege"), {}, _C({_P.CALLS_AND_EFFECTS, _P.PERMISSIONS}), Exactness.GUESS,
              _fixed("request only the access that the code uses")),
    CheckKind(CheckKindName("max-lines"),
              {"function": ParamSpec(ParamType.COUNT, 200), "class": ParamSpec(ParamType.COUNT, 1000)},
              _C({_P.SYMBOLS}), Exactness.EXACT,
              lambda s, p, x: f"The {s} shall keep each function within {p['function']} lines and each class "
                              f"within {p['class']} lines{_excepted(x)}."),
    CheckKind(CheckKindName("max-children"), {"count": ParamSpec(ParamType.COUNT, 9)}, _C({_P.RECORD}),
              Exactness.EXACT,
              lambda s, p, x: f"The {s} shall have at most {p['count']} children under each functional "
                              f"requirement{_excepted(x)}."),
    CheckKind(CheckKindName("described-names"), {}, _C({_P.SYMBOLS}), Exactness.BOTH,
              _fixed("describe each public name in one line")),
    CheckKind(CheckKindName("min-depth"), {"ratio": ParamSpec(ParamType.RATIO, 5.0)}, _C({_P.SYMBOLS}),
              Exactness.GUESS,
              lambda s, p, x: f"The {s} shall keep at least {p['ratio']:g} lines of code behind each name and "
                              f"parameter of each component interface{_excepted(x)}."),
    CheckKind(CheckKindName("no-mode-parameters"), {}, _C({_P.SYMBOLS}), Exactness.GUESS,
              _fixed("not choose between behaviours by a parameter")),
    CheckKind(CheckKindName("narrow-parameters"), {}, _C({_P.SYMBOLS}), Exactness.GUESS,
              _fixed("take only the data that each function uses")),
    CheckKind(CheckKindName("no-single-implementations"), {}, _C({_P.SYMBOLS}), Exactness.GUESS,
              _fixed("not keep an abstraction with only one implementation")),
    CheckKind(MUTATION, {"paths": ParamSpec(ParamType.COUNT, 200), "seconds": ParamSpec(ParamType.RATIO, 10.0)},
              _C({_P.SYMBOLS}), Exactness.BOTH,
              _fixed("have the contract of each function declared without effects notice every small change to "
                     "the function")),
    CheckKind(PLANNED_EFFECTS, {}, _C({_P.SYMBOLS, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("make every decision in a function that is declared without effects")),
    CheckKind(CheckKindName("co-change"),
              {"commits": ParamSpec(ParamType.COUNT, 500), "threshold": ParamSpec(ParamType.RATIO, 0.5)},
              _C({_P.HISTORY, _P.DEPENDENCIES}), Exactness.GUESS,
              _fixed("not change sibling design parameters together without a dependency between the siblings")),
)

BUILT_IN_KINDS: Mapping[CheckKindName, CheckKind] = {k.name: k for k in _KINDS}

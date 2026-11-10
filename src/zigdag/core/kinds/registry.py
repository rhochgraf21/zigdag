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
    LINT_DIAGNOSTICS = "lint diagnostics"
    TYPE_DIAGNOSTICS = "type diagnostics"
    SECURITY_DIAGNOSTICS = "security diagnostics"
    HISTORY = "history"


class Direction(enum.Enum):
    """A way code quality is judged (DESIGN2 §4.6), in the order the report gives them: zigdag's own directions first,
    from the design to what the code does, then the project's linter and type checker."""

    DESIGN = "design"  # the record itself: its grammar, its names, its tree and its rules
    ARCHITECTURE = "architecture"  # whether the code matches the design
    SECURITY = "security"
    CORRECTNESS = "correctness"
    LINT = "lint"
    TYPECHECK = "typecheck"


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
    direction: Direction  # what its findings say about the code: the report sums them up by direction


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


EXCEPTIONS_NAMED = 4  # at most this many exceptions are named in a sentence; more are counted, so it stays short


def _excepted(excepted: tuple[str, ...]) -> str:
    if not excepted:
        return ""
    if len(excepted) > EXCEPTIONS_NAMED:
        return f", except in the {len(excepted)} places that the rule lists"
    return f", except in {_and(list(excepted))}"


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
CONTRACTED_INTERFACES = CheckKindName("contracted-interfaces")
LINT = CheckKindName("lint")
TYPES = CheckKindName("types")
SECURITY = CheckKindName("security")

_C = frozenset
_P = Part
_EFFECTS = {"allow": ParamSpec(ParamType.EFFECTS)}

_KINDS = (
    CheckKind(EFFECTS, _EFFECTS, _C({_P.CALLS_AND_EFFECTS}), Exactness.EXACT, _effects, Direction.ARCHITECTURE),
    CheckKind(CheckKindName("may-depend-on"), {"allow": ParamSpec(ParamType.NAMES)},
              _C({_P.DEPENDENCIES}), Exactness.EXACT, _depends, Direction.ARCHITECTURE),
    CheckKind(CheckKindName("designed-modules"), {}, _C({_P.UNITS}), Exactness.EXACT,
              _fixed("hold only the modules that the design names"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("encapsulation"), {}, _C({_P.DEPENDENCIES, _P.PUBLIC_NAMES}), Exactness.EXACT,
              _fixed("reach each other design parameter only through the public names of that design parameter"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("container-boundaries"), {}, _C({_P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("not import code from another container"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("data-ownership"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("change each structure only from the component that owns the structure"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("no-cycles"), {}, _C({_P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("keep the dependencies between sibling design parameters free of cycles"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("declared-libraries"), {}, _C({_P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("import only the standard library and declared or vendored packages"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("edge-types"),
              {"bool-parameters": ParamSpec(ParamType.CHOICE, "allowed", ("allowed", "forbidden")),
               "bool-returns": ParamSpec(ParamType.CHOICE, "allowed", ("allowed", "forbidden")),
               "bool-fields": ParamSpec(ParamType.CHOICE, "allowed", ("allowed", "forbidden"))},
              _C({_P.SYMBOLS, _P.DEPENDENCIES}), Exactness.EXACT,
              _fixed("pass only project-defined types between components"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("declared-errors"), {}, _C({_P.SYMBOLS, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("raise only declared errors of project-defined types between components"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("representations-agree"), {}, _C({_P.STRUCTURES}), Exactness.EXACT,
              _fixed("keep every representation of a structure in agreement"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("messages-agree"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("use one structure for every message on a queue"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("endpoints-agree"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("use the structures of an endpoint when calling the endpoint"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("references-resolve"), {}, _C({_P.STRUCTURES}), Exactness.EXACT,
              _fixed("refer only to recorded structures"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("access-sanity"), {}, _C({_P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.GUESS,
              _fixed("read each stored structure that a design parameter creates"), Direction.ARCHITECTURE),
    CheckKind(DATA_FLOW,
              {"data": ParamSpec(ParamType.NAMES), "never-reaches": ParamSpec(ParamType.EFFECTS)},
              _C({_P.SYMBOLS, _P.STRUCTURES, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              lambda s, p, x: f"The {s} shall not use {_and([_last(d) for d in p['data']])} values when "
                              f"{_or([phrase(e) for e in p['never-reaches']])}{_excepted(x)}.", Direction.SECURITY),
    CheckKind(CheckKindName("one-writer-per-data-store"), {}, _C({_P.CALLS_AND_EFFECTS}), Exactness.EXACT,
              _fixed("give each data container exactly one writing container"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("permitted-effects"), {}, _C({_P.CALLS_AND_EFFECTS, _P.PERMISSIONS}), Exactness.EXACT,
              _fixed("use only the access that the infrastructure grants"), Direction.SECURITY),
    CheckKind(CheckKindName("least-privilege"), {}, _C({_P.CALLS_AND_EFFECTS, _P.PERMISSIONS}), Exactness.GUESS,
              _fixed("request only the access that the code uses"), Direction.SECURITY),
    CheckKind(CheckKindName("max-lines"),
              {"function": ParamSpec(ParamType.COUNT, 200), "class": ParamSpec(ParamType.COUNT, 1000),
               # a file holds its classes whole: a default below the class's would break on a class the rule allows
               "file": ParamSpec(ParamType.COUNT, 1000)},
              _C({_P.SYMBOLS}), Exactness.EXACT,
              lambda s, p, x: f"The {s} shall keep each function within {p['function']} lines, each class within "
                              f"{p['class']} lines and each file within {p['file']} lines{_excepted(x)}.",
              Direction.ARCHITECTURE),
    CheckKind(CheckKindName("max-children"), {"count": ParamSpec(ParamType.COUNT, 9)}, _C({_P.RECORD}),
              Exactness.EXACT,
              lambda s, p, x: f"The {s} shall have at most {p['count']} children under each functional "
                              f"requirement{_excepted(x)}.", Direction.DESIGN),
    CheckKind(CheckKindName("described-names"), {}, _C({_P.SYMBOLS}), Exactness.BOTH,
              _fixed("describe each public name in one line"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("narrow-parameters"), {}, _C({_P.SYMBOLS}), Exactness.GUESS,
              _fixed("take only the data that each function uses"), Direction.ARCHITECTURE),
    CheckKind(CheckKindName("no-single-implementations"), {}, _C({_P.SYMBOLS}), Exactness.GUESS,
              _fixed("not keep an abstraction with only one implementation"), Direction.ARCHITECTURE),
    CheckKind(MUTATION, {"paths": ParamSpec(ParamType.COUNT, 200), "seconds": ParamSpec(ParamType.RATIO, 10.0)},
              _C({_P.SYMBOLS}), Exactness.BOTH,
              _fixed("have the contract of each function declared without effects notice every small change to "
                     "the function"), Direction.CORRECTNESS),
    CheckKind(PLANNED_EFFECTS, {}, _C({_P.SYMBOLS, _P.CALLS_AND_EFFECTS}), Exactness.BOTH,
              _fixed("make every decision in a function that is declared without effects"), Direction.ARCHITECTURE),
    CheckKind(CONTRACTED_INTERFACES, {}, _C({_P.SYMBOLS, _P.DEPENDENCIES, _P.CALLS_AND_EFFECTS}), Exactness.EXACT,
              _fixed("give a contract to each function declared without effects that an interface offers"), Direction.ARCHITECTURE),
    CheckKind(LINT, {}, _C({_P.LINT_DIAGNOSTICS}), Exactness.EXACT,
              _fixed("break no rule of the linter of the project"), Direction.LINT),
    CheckKind(TYPES, {}, _C({_P.TYPE_DIAGNOSTICS}), Exactness.EXACT,
              _fixed("break no rule of the type checker of the project"), Direction.TYPECHECK),
    CheckKind(SECURITY, {}, _C({_P.SECURITY_DIAGNOSTICS}), Exactness.EXACT,
              _fixed("break no rule of the security checker of the project"), Direction.SECURITY),
    CheckKind(CheckKindName("co-change"),
              {"commits": ParamSpec(ParamType.COUNT, 500), "threshold": ParamSpec(ParamType.RATIO, 0.5)},
              _C({_P.HISTORY, _P.DEPENDENCIES}), Exactness.GUESS,
              _fixed("not change sibling design parameters together without a dependency between the siblings"), Direction.ARCHITECTURE),
)

BUILT_IN_KINDS: Mapping[CheckKindName, CheckKind] = {k.name: k for k in _KINDS}

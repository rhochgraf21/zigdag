"""The code model (DESIGN2 §5.1): what an adapter reads from a language, and the only thing checks see of code.

It is language-free. Names are qualified by the adapter (`zigdag.core.names.fr_name`, `subprocess.run`), and
every language-specific judgement, such as which types are standard containers, is made by the adapter.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import NewType

from zigdag.core.effects import Effect
from zigdag.core.findings import Digest, Finding, RecordPath, Span
from zigdag.core.kinds.registry import Part
from zigdag.core.names import AdapterName, CodePath
from zigdag.core.record.model import EvidenceKind

SymbolName = NewType("SymbolName", str)  # a name inside a unit: emit_module, Emitter, Emitter.emit_expr
CONSTRUCTOR_NAME = "__init__"  # a class's constructor
CONSTRUCTOR = f".{CONSTRUCTOR_NAME}"  # how a constructor ends its symbol name: Emitter.__init__
Qualified = NewType("Qualified", str)  # a fully qualified name, inside the project or not: subprocess.run
TestId = NewType("TestId", str)  # tests.test_names::test_fr_names_are_dotted (module, then function)


class UnitKind(enum.Enum):
    PACKAGE = "package"
    MODULE = "module"
    TABLE = "table"  # stored data: its structures are stored structures


@dataclass(frozen=True)
class Unit:
    path: CodePath  # zigdag.core.names
    adapter: AdapterName
    kind: UnitKind
    public: bool  # its language marks it public: no part of its name starts with _
    span: Span
    size: int  # lines


class SymbolKind(enum.Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    NAMED_TYPE = "named type"  # NewType, a type alias, a type variable
    CONSTANT = "constant"


class Abstraction(enum.Enum):
    """A class that only says what its implementations do (DESIGN2 §4.1, no-single-implementations)."""

    PROTOCOL = "protocol"  # implemented by having its members, whether or not a class names it as a base
    ABSTRACT_BASE = "abstract base class"  # implemented by naming it as a base

    @property
    def with_article(self) -> str:
        return f"{'an' if self.value[0] in 'aeiou' else 'a'} {self.value}"


class TypeKind(enum.Enum):
    REF = "ref"  # a named type: project-defined or not; `name` is qualified
    CONTAINER = "container"  # a standard wrapper around `args`: list[...], Callable[..., ...]
    UNION = "union"
    NONE = "none"
    LITERAL = "literal"
    BOOL = "bool"
    ANY = "any"  # Any, object: nothing can be said
    UNKNOWN = "unknown"  # the adapter could not read it


@dataclass(frozen=True)
class TypeExpr:
    kind: TypeKind
    text: str  # as written
    name: Qualified | None = None
    args: tuple[TypeExpr, ...] = ()
    values: tuple[str, ...] = ()  # a literal's values, as written: paid, shipped

    @property
    def named(self) -> Qualified | None:
        """The one named type a value of this type is, looking through `| None`; None for anything else."""
        if self.kind is TypeKind.REF:
            return self.name
        if self.kind is TypeKind.UNION:
            others = [a for a in self.args if a.kind is not TypeKind.NONE]
            return others[0].named if len(others) == 1 else None
        return None


@dataclass(frozen=True)
class Param:
    name: str
    type: TypeExpr | None  # None when it has no annotation
    span: Span
    branched_on: bool = False  # the body takes a branch by its value: if flag:, match kind:
    fields_read: tuple[str, ...] = ()  # the fields of it the body reads, in order of first reading
    used_whole: bool = True  # the body also uses it as a whole: passes, returns, compares, changes or calls it


@dataclass(frozen=True)
class Signature:
    params: tuple[Param, ...]
    returns: TypeExpr | None
    span: Span


@dataclass(frozen=True)
class Field:
    name: str
    type: TypeExpr | None
    description: str | None
    span: Span
    key: bool = False  # the adapter marks it as its structure's identity: a primary key, or a field named id


@dataclass(frozen=True)
class Symbol:
    unit: CodePath
    name: SymbolName
    kind: SymbolKind
    public: bool
    span: Span
    size: int
    description: str | None  # a docstring's first line, or a comment at the end of the line
    signature: Signature | None = None  # functions and methods
    fields: tuple[Field, ...] = ()  # classes
    bases: tuple[TypeExpr, ...] = ()  # classes
    members: tuple[str, ...] = ()  # an enumeration's members, as written
    abstraction: Abstraction | None = None  # classes: a protocol or an abstract base class
    contract: bool = False  # it has a contract that is checked when it runs
    unmutated: tuple[Span, ...] = ()  # functions: lines marked not to be mutated, such as # pragma: no mutate
    declared_effects: tuple[Effect, ...] | None = None  # from @deal.has / @deal.pure; None means undeclared
    declared_errors: tuple[TypeExpr, ...] | None = None  # from @deal.raises / @deal.pure / @deal.safe

    @property
    def qualified(self) -> Qualified:
        return Qualified(f"{self.unit}.{self.name}")

    @property
    def declared_pure(self) -> bool:
        """Its code declares that it has no effects at all."""
        return self.declared_effects == ()

    @property
    def place(self) -> Place:
        """Where its code runs."""
        return Place(self.unit, self.name)

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)


@dataclass(frozen=True, order=True)
class Place:
    """Where code runs: a symbol in a unit, or the unit's own top-level code when symbol is None."""

    unit: CodePath
    symbol: SymbolName | None

    def __str__(self) -> str:
        return f"{self.unit}.{self.symbol}" if self.symbol else self.unit


class DependencyKind(enum.Enum):
    IMPORT = "import"
    REFERENCE = "reference"  # a use of a name: a call, an attribute, a type


@dataclass(frozen=True)
class Dependency:
    source: Place
    target: Qualified  # a unit, or a name inside one, or something outside the project
    kind: DependencyKind
    span: Span
    seen: TestId | None = None  # seen while this test ran, rather than read from the code


@dataclass(frozen=True)
class Call:
    caller: Place
    callee: Qualified
    span: Span
    seen: TestId | None = None


@dataclass(frozen=True)
class EffectStart:
    """An effect that starts here: the code calls or touches an API that has it."""

    at: Place
    effect: Effect
    via: str  # the API, as written: open, subprocess.run, print
    span: Span
    seen: TestId | None = None


@dataclass(frozen=True)
class TypeOf:
    """A value's type as far as an adapter can tell from one file: a named type, or what calling a name returns,
    then the fields read from it in turn. The core finishes the work with the whole model (CodeModel.type_of)."""

    root: Qualified
    called: bool  # the value is what a call to root returns: a constructor's object, or a function's result
    path: tuple[str, ...] = ()

    def field(self, name: str) -> TypeOf:
        return TypeOf(self.root, self.called, (*self.path, name))


class AccessKind(enum.Enum):
    CREATES = "creates"
    READS = "reads"
    UPDATES = "updates"
    DELETES = "deletes"


@dataclass(frozen=True)
class Access:
    """Code touching a value's field: reading it, or changing it."""

    at: Place
    value: TypeOf
    field: str | None  # None: the value as a whole
    kind: AccessKind
    in_place: bool  # changed through the field's own operations (order.lines.append), not by assigning it
    span: Span
    seen: TestId | None = None


class UseKind(enum.Enum):
    RELEASE = "release"  # made into plain text: converted, formatted, serialised
    EFFECT = "effect"  # passed straight to an API that has an effect


@dataclass(frozen=True)
class Use:
    """A value given to a release point or an effect (DESIGN2 §4.1, data-flow)."""

    at: Place
    value: TypeOf | None  # None: the adapter cannot tell its type
    kind: UseKind
    via: str  # str(), an f-string, print, json.dumps
    effect: Effect | None  # for an effect use, the effect
    span: Span


class Source(enum.Enum):
    """Where a value inside a function comes from (DESIGN2 §4.1, planned-effects)."""

    CONSTANT = "constant"  # a literal, or a name defined at the top of a module: a constant, a function, a class
    PARAMETER = "parameter"  # one of the function's parameters
    CALL = "call"  # what a call returns
    BUILT = "built"  # a standard container made of other values: a list, a tuple, a dictionary
    WORKED_OUT = "worked out"  # the result of a comparison, arithmetic or logic, worked out in place
    UNKNOWN = "unknown"  # a name the adapter cannot trace


@dataclass(frozen=True)
class ValueSource:
    kind: Source
    name: Qualified | None = None  # a call's callee, or a parameter's type, when it can be told
    receiver: TypeOf | None = None  # a method call's receiver, when its type can be told
    method: str | None = None  # a method call's name
    built_from: tuple[ValueSource, ...] = ()  # what a call or a container is made from: its arguments


class Need(enum.Enum):
    ARGUMENT = "argument"  # given to a call
    CONDITION = "condition"  # branched on: the test of an if or a while, the subject of a match


@dataclass(frozen=True)
class PlannedUse:
    """A value inside a function that must be a plan value unless the function is declared pure."""

    at: Place
    need: Need
    text: str  # the expression, as written
    sources: tuple[ValueSource, ...]
    span: Span
    call: ValueSource | None = None  # for an argument: the call it is given to


@dataclass(frozen=True)
class Computation:
    """A comparison, arithmetic or logic worked out inside a function."""

    at: Place
    text: str  # as written: total > 100
    span: Span


@dataclass(frozen=True)
class Unknown:
    """Code whose behaviour cannot be read statically: eval, exec, a dynamic import."""

    at: Place
    what: str
    span: Span


@dataclass(frozen=True)
class Raise:
    at: Place
    error: TypeExpr
    caught: bool  # caught by an enclosing handler in the same function
    span: Span


@dataclass(frozen=True)
class Link:
    target: str  # as written: fr#statement, or a constraint name
    span: Span


class Outcome(enum.Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Test:
    id: TestId
    links: tuple[Link, ...]
    evidence: EvidenceKind
    imports: tuple[Qualified, ...]  # what the test's module imports, to see which code it can run
    span: Span
    place: Place | None = None  # for a contract, the operation it is on


@dataclass(frozen=True)
class Run:
    """One test, as it was seen running."""

    test: TestId
    ran: frozenset[CodePath]  # the units whose code ran
    current: bool  # neither the test nor any code it ran has changed since
    processes: bool = False  # it started other processes, whose code could not be watched


class Verdict(enum.Enum):
    SAME = "same"
    DIFFERENT = "different"
    NOT_COPYABLE = "not copyable"


@dataclass(frozen=True)
class Replay:
    """A call into code that may have no effects, made again with a copy of its arguments (DESIGN2 §4.5)."""

    at: Place
    verdict: Verdict
    detail: str
    span: Span  # the operation
    seen: TestId  # the test whose call was replayed


@dataclass(frozen=True)
class Cases:
    """A contract's operation run on generated inputs."""

    at: Place
    outcome: Outcome
    detail: str
    span: Span


class MutantFate(enum.Enum):
    KILLED = "killed"  # a contract case or a test that runs the function failed on it: the change was noticed
    TIMED_OUT = "timed out"  # it never returned, which is noticed too
    SURVIVED = "survived"  # every contract case held and every test that runs the function passed
    EQUIVALENT = "equivalent"  # it survived, but a bounded search found no input it behaves differently on
    NOT_RUN = "not run"  # it could not be put in place of the function


_REMOVED, _ADDED, _HEADER = "-", "+", ("---", "+++", "@@")


@dataclass(frozen=True)
class Witness:
    """An input the function and its mutant behave differently on, which nothing noticed."""

    input: str  # the arguments, as written: a=3, b=1
    written: str  # what the function as written does with it: returns 2
    mutated: str  # what the mutant does with it: returns 4


@dataclass(frozen=True)
class Mutant:
    """One small edit to a function that has a contract, run against the contract's cases and the tests that run the
    function (DESIGN2 §4.5)."""

    at: Place  # the function edited
    of: Digest  # the function's source, as it was when edited: an answer about the mutant stands until it changes
    edit: str  # the change, as a unified diff of the function
    fate: MutantFate
    detail: str  # what killed it, or why it was not run
    span: Span  # the function
    unnoticed_by: tuple[TestId, ...] = ()  # for a survivor: the tests that ran the function and still passed
    witness: Witness | None = None  # for a survivor: an input it behaves differently on, when the search found one

    @property
    def summary(self) -> str:
        """The change in one line: what was written, and what it became."""
        lines = [line for line in self.edit.splitlines() if not line.startswith(_HEADER)]
        before = " ".join(line[1:].strip() for line in lines if line.startswith(_REMOVED))
        after = " ".join(line[1:].strip() for line in lines if line.startswith(_ADDED))
        return f"`{before}` became `{after}`" if after else f"`{before}` was removed"


@dataclass(frozen=True)
class Crossing:
    """A value seen crossing into an operation from another design parameter, or back out of it."""

    at: Place  # the operation
    where: str  # a parameter's name, or RETURNED
    expected: str | None  # its annotation, as written; None when it has none
    actual: Qualified  # the value's own type
    conforms: bool  # the value fits the annotation (a distinct named type is checked as its base type)
    span: Span  # the call
    seen: TestId


RETURNED = "return"  # a Crossing's `where` for the value an operation returns


@dataclass(frozen=True)
class Escape:
    """An error seen leaving an operation for code in another design parameter."""

    at: Place
    error: Qualified
    span: Span  # the call it escaped to
    seen: TestId


@dataclass(frozen=True)
class Leak:
    """The text of a protected value, seen written to an effect while a test ran."""

    data: Qualified  # the protected type
    effect: Effect
    where: str  # standard output, a log record, a file's path
    at: Place | None  # the code that wrote it, when it can be told
    span: Span | None
    seen: TestId


@dataclass(frozen=True)
class Observations:
    """What was seen while the tests ran (DESIGN2 §4.5), current with the code. Effects, imports, calls and changes
    seen are in the model's own lists, marked with the test they were seen in."""

    runs: Mapping[TestId, Run] = field(default_factory=dict)
    crossings: tuple[Crossing, ...] = ()
    escapes: tuple[Escape, ...] = ()
    leaks: tuple[Leak, ...] = ()
    replays: tuple[Replay, ...] = ()
    cases: tuple[Cases, ...] = ()
    mutants: tuple[Mutant, ...] = ()
    mutation_unavailable: str | None = None  # why no mutants were made, such as the tool not being installed
    unwatched: tuple[CodePath, ...] = ()  # units whose running the watcher cannot see: its own
    stale: int = 0  # observations left out because the code they were seen in has changed since

    def run_of(self, test: TestId) -> Run | None:
        return self.runs.get(test)

    def cases_of(self, place: Place | None) -> Cases | None:
        return next((c for c in self.cases if c.at == place), None)


@dataclass(frozen=True)
class Libraries:
    """Third-party packages: the ones the project declares, the ones it vendors, and the standard library."""

    declared: frozenset[str] | None  # import names; None when the project declares nothing readable
    vendored: frozenset[str]
    standard: frozenset[str]


@dataclass(frozen=True)
class CodeModel:
    units: Mapping[CodePath, Unit] = field(default_factory=dict)
    symbols: Mapping[Qualified, Symbol] = field(default_factory=dict)
    dependencies: tuple[Dependency, ...] = ()
    calls: tuple[Call, ...] = ()
    effects: tuple[EffectStart, ...] = ()
    unknowns: tuple[Unknown, ...] = ()
    raises: tuple[Raise, ...] = ()
    accesses: tuple[Access, ...] = ()
    uses: tuple[Use, ...] = ()
    planned_uses: tuple[PlannedUse, ...] = ()
    computations: tuple[Computation, ...] = ()
    tests: tuple[Test, ...] = ()
    results: Mapping[TestId, Outcome] = field(default_factory=dict)  # test id -> its latest result
    observed: Observations | None = None  # None until the tests have been run under observation
    reports_read: bool = False
    libraries: Libraries = field(default_factory=lambda: Libraries(None, frozenset(), frozenset()))
    supplied: frozenset[Part] = frozenset()
    problems: tuple[Finding, ...] = ()

    @property
    def adapters(self) -> frozenset[AdapterName]:
        """The adapters whose code this model holds."""
        return frozenset(u.adapter for u in self.units.values())

    def unit_at(self, path: str) -> Unit | None:
        """The unit read from a file: the most specific one, since a folder with no file of its own is placed at
        the first file inside it."""
        return max((u for u in self.units.values() if u.span.path == path), key=lambda u: u.path.count("."),
                   default=None)

    @property
    def files(self) -> Mapping[RecordPath, CodePath]:
        """Each file the units were read from, and the unit it is."""
        paths = sorted({u.span.path for u in self.units.values()})
        return {p: unit.path for p in paths if (unit := self.unit_at(p)) is not None}

    def members_of(self, cls: Symbol) -> list[Symbol]:
        """What using a class exposes: its public methods and its constructor."""
        prefix = f"{cls.qualified}."
        return [s for q, s in sorted(self.symbols.items()) if q.startswith(prefix) and s.kind is SymbolKind.METHOD
                and (s.public or s.name.endswith(CONSTRUCTOR)) and "." not in q[len(prefix):]]

    def unit_of(self, name: Qualified) -> CodePath | None:
        """The most specific unit a qualified name is in, or None when it is outside the project."""
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            candidate = CodePath(".".join(parts[:i]))
            if candidate in self.units:
                return candidate
        return None

    def type_of(self, value: TypeOf) -> Qualified | None:
        """The named type a value has, worked out through constructors, return types and fields; None when the code
        does not say."""
        symbol = self.symbols.get(value.root)
        if symbol is None:
            return None
        if not value.called or symbol.kind in (SymbolKind.CLASS, SymbolKind.NAMED_TYPE):
            current: Qualified | None = value.root
        elif symbol.signature is not None and symbol.signature.returns is not None:
            current = symbol.signature.returns.named
        else:
            return None
        for name in value.path:
            holder = self.symbols.get(current) if current else None
            found = holder.field(name) if holder is not None and holder.kind is SymbolKind.CLASS else None
            if found is None or found.type is None:
                return None
            current = found.type.named
        return current

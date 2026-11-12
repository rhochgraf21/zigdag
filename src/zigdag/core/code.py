"""The code model (DESIGN2 §5.1): what an adapter reads from a language, and the only thing checks see of code.

It is language-free. Names are qualified by the adapter (`zigdag.core.names.fr_name`, `subprocess.run`), and
every language-specific judgement, such as which types are standard containers, is made by the adapter.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NewType

import deal

from zigdag.core.effects import Effect
from zigdag.core.kinds.registry import Part
from zigdag.core.record.model import EvidenceKind
from zigdag.core.findings import Digest, Finding, RecordPath, Result, RuleName, Span, Subject, finding
from zigdag.core.names import AdapterName, CodePath
from zigdag.core.measures import Count, LineCount, Seconds
from zigdag.core.names import Api, Identifier, Library
from zigdag.core.texts import Say, Written

SymbolName = NewType("SymbolName", str)  # a name inside a unit: emit_module, Emitter, Emitter.emit_expr
CONSTRUCTOR_NAME = "__init__"  # a class's constructor
CONSTRUCTOR = f".{CONSTRUCTOR_NAME}"  # how a constructor ends its symbol name: Emitter.__init__
Qualified = NewType("Qualified", str)  # a fully qualified name, inside the project or not: subprocess.run
TestId = NewType("TestId", str)  # tests.test_names::test_fr_names_are_dotted (module, then function)


class Level(enum.IntEnum):
    """The levels of the design (DESIGN2 §2.3), outermost first: each sits inside the one before it."""

    SYSTEM = 0
    CONTAINER = 1
    COMPONENT = 2
    STRUCTURE = 3


class UnitKind(enum.Enum):
    PACKAGE = "package"
    MODULE = "module"
    TABLE = "table"  # stored data: its structures are stored structures
    RESOURCE = "resource"  # deployed: it runs code or stores data, so it is a container
    SUPPORT = "supporting resource"  # deployed for the sake of a container: a role, a policy, a security group


@dataclass(frozen=True)
class Unit:
    path: CodePath  # zigdag.core.names
    adapter: AdapterName
    kind: UnitKind
    public: bool  # its language marks it public: no part of its name starts with _
    span: Span
    size: LineCount  # lines
    level: Level = Level.COMPONENT  # the level of the design it can be: a deployed resource is a container


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
    @deal.ensure(lambda self, result: result.split(" ", 1) in (["a", self.value], ["an", self.value]))
    def with_article(self) -> Say:
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
    text: Written  # as written
    name: Qualified | None = None
    args: tuple[TypeExpr, ...] = ()
    values: tuple[Written, ...] = ()  # a literal's values, as written: paid, shipped

    @property
    @deal.ensure(lambda self, result: self.kind is not TypeKind.REF or result == self.name)
    @deal.ensure(lambda self, result: result is None or self.kind in (TypeKind.REF, TypeKind.UNION))
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
    name: Identifier
    type: TypeExpr | None  # None when it has no annotation
    span: Span
    branched_on: bool = False  # the body takes a branch by its value: if flag:, match kind:
    fields_read: tuple[Identifier, ...] = ()  # the fields of it the body reads, in order of first reading
    used_whole: bool = True  # the body also uses it as a whole: passes, returns, compares, changes or calls it


@dataclass(frozen=True)
class Signature:
    params: tuple[Param, ...]
    returns: TypeExpr | None
    span: Span


@dataclass(frozen=True)
class Field:
    name: Identifier
    type: TypeExpr | None
    description: Say | None
    span: Span
    key: bool = False  # the adapter marks it as its structure's identity: a primary key, or a field named id


@dataclass(frozen=True)
class Symbol:
    unit: CodePath
    name: SymbolName
    kind: SymbolKind
    public: bool
    span: Span
    size: LineCount
    description: Say | None  # a docstring's first line, or a comment at the end of the line
    signature: Signature | None = None  # functions and methods
    fields: tuple[Field, ...] = ()  # classes
    bases: tuple[TypeExpr, ...] = ()  # classes
    members: tuple[Identifier, ...] = ()  # an enumeration's members, as written
    abstraction: Abstraction | None = None  # classes: a protocol or an abstract base class
    contract: bool = False  # it has a contract that is checked when it runs
    unmutated: tuple[Span, ...] = ()  # functions: lines marked not to be mutated, such as # pragma: no mutate
    declared_effects: tuple[Effect, ...] | None = None  # from @deal.has / @deal.pure; None means undeclared
    declared_errors: tuple[TypeExpr, ...] | None = None  # from @deal.raises / @deal.pure / @deal.safe

    @property
    @deal.ensure(lambda self, result: result == f"{self.unit}.{self.name}")
    def qualified(self) -> Qualified:
        return Qualified(f"{self.unit}.{self.name}")

    @property
    @deal.ensure(lambda self, result: result == (self.declared_effects is not None and not self.declared_effects))
    def declared_pure(self) -> bool:
        """Its code declares that it has no effects at all."""
        return self.declared_effects == ()

    @property
    @deal.ensure(lambda self, result: str(result) == self.qualified)  # it runs where it is named
    def place(self) -> Place:
        """Where its code runs."""
        return Place(self.unit, self.name)

    @deal.ensure(lambda self, name, result: result is None or (result.name == name and result in self.fields))
    @deal.ensure(lambda self, name, result: result is not None or all(f.name != name for f in self.fields))
    def field(self, name: Identifier) -> Field | None:
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
    CONNECTION = "connection"  # for infrastructure: a network rule lets the source reach the target
    GRANT = "grant"  # for infrastructure: the source is granted access to the target


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
    via: Api  # the API, as written: open, subprocess.run, print
    span: Span
    seen: TestId | None = None


class ResourceAccess(enum.Enum):
    """What code does to a data container, and what infrastructure grants on one (DESIGN2 §3, resource effects)."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ResourceUse:
    """A call to a client of a deployed resource, such as a storage client's write (DESIGN2 §5.3). Which resource
    it is on is known only through the setting that carries the resource's name to the call."""

    at: Place
    access: ResourceAccess
    via: Api  # the call, as written: s3.put_object
    setting: Identifier | None  # the setting the resource's name comes from: RECEIPTS_BUCKET; None when not traced
    span: Span


@dataclass(frozen=True)
class Setting:
    """A setting the infrastructure gives a deployed unit, whose value names another resource: an environment
    variable set to a bucket's name or a database's address (DESIGN2 §5.3)."""

    at: CodePath  # the deployed unit that is given it
    name: Identifier  # DATABASE_URL
    target: CodePath  # the resource its value names
    span: Span


@dataclass(frozen=True)
class Grant:
    """Access the infrastructure grants on a resource (DESIGN2 §5.3): to a role, which is its container's."""

    to: CodePath  # the deployed unit that is granted: a role
    on: CodePath  # the resource it may act on
    access: ResourceAccess | None  # None when what is granted could not be read, so it may be either
    action: Written  # as granted: s3:PutObject
    span: Span


@dataclass(frozen=True)
class TypeOf:
    """A value's type as far as an adapter can tell from one file: a named type, or what calling a name returns,
    then the fields read from it in turn. The core finishes the work with the whole model (CodeModel.type_of)."""

    root: Qualified
    called: bool  # the value is what a call to root returns: a constructor's object, or a function's result
    path: tuple[Identifier, ...] = ()

    @deal.ensure(lambda self, name, result: (result.root, result.called) == (self.root, self.called))
    @deal.ensure(lambda self, name, result: result.path == (*self.path, name))  # one field further in
    def field(self, name: Identifier) -> TypeOf:
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
    field: Identifier | None  # None: the value as a whole
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
    via: Api  # str(), an f-string, print, json.dumps
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
    method: Identifier | None = None  # a method call's name
    built_from: tuple[ValueSource, ...] = ()  # what a call or a container is made from: its arguments


class Need(enum.Enum):
    ARGUMENT = "argument"  # given to a call
    CONDITION = "condition"  # branched on: the test of an if or a while, the subject of a match


@dataclass(frozen=True)
class PlannedUse:
    """A value inside a function that must be a plan value unless the function is declared pure."""

    at: Place
    need: Need
    text: Written  # the expression, as written
    sources: tuple[ValueSource, ...]
    span: Span
    call: ValueSource | None = None  # for an argument: the call it is given to


@dataclass(frozen=True)
class Computation:
    """A comparison, arithmetic or logic worked out inside a function."""

    at: Place
    text: Written  # as written: total > 100
    span: Span


@dataclass(frozen=True)
class Unknown:
    """Code whose behaviour cannot be read statically: eval, exec, a dynamic import."""

    at: Place
    what: Written
    span: Span


@dataclass(frozen=True)
class Raise:
    at: Place
    error: TypeExpr
    caught: bool  # caught by an enclosing handler in the same function
    span: Span


@dataclass(frozen=True)
class Link:
    target: Written  # as written: fr#statement, or a constraint name
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
    detail: Say
    span: Span  # the operation
    seen: TestId  # the test whose call was replayed


@dataclass(frozen=True)
class Cases:
    """A contract's operation run on generated inputs, and the tests that called it: the contract library checks a
    contract at every call, so those tests checked it too, on their own inputs (DESIGN2 §4.5)."""

    at: Place
    outcome: Outcome  # on the generated inputs: an error when none could be made, skipped for a method
    detail: Say
    span: Span
    called_by: tuple[TestId, ...] = ()  # empty when no contract library ran, since then no call checked it

    @property
    @deal.ensure(lambda self, result: result != (self.outcome in (Outcome.ERROR, Outcome.SKIPPED)))
    def generated(self) -> bool:
        """Whether the contract ran on generated inputs at all."""
        return self.outcome in (Outcome.PASSED, Outcome.FAILED)

    @property
    @deal.ensure(lambda self, result: result == (not self.generated and bool(self.called_by)))
    def checked_by_tests(self) -> bool:
        """Whether no inputs were generated, so the tests' own calls are all that checked the contract."""
        return not self.generated and bool(self.called_by)


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

    input: Written  # the arguments, as written: a=3, b=1
    written: Written  # what the function as written does with it: returns 2
    mutated: Written  # what the mutant does with it: returns 4


@dataclass(frozen=True)
class SearchBound:
    """How far the search for an input a mutant behaves differently on may go."""

    paths: Count  # at most this many paths through the code
    seconds: Seconds  # and for at most this long


@dataclass(frozen=True)
class Mutant:
    """One small edit to a function that has a contract, run against the contract's cases and the tests that run the
    function (DESIGN2 §4.5)."""

    at: Place  # the function edited
    of: Digest  # the function's source, as it was when edited: an answer about the mutant stands until it changes
    edit: Written  # the change, as a unified diff of the function
    fate: MutantFate
    detail: Say  # what killed it, or why it was not run
    span: Span  # the function
    unnoticed_by: tuple[TestId, ...] = ()  # for a survivor: the tests that ran the function and still passed
    witness: Witness | None = None  # for a survivor: an input it behaves differently on, when the search found one
    judged_by: tuple[TestId, ...] = ()  # the tests that ran the function: it stands while they are unchanged
    bound: SearchBound | None = None  # how far a survivor's search could go
    depends: Digest | None = None  # what its fate depended on besides the function: the code the function calls, and
    # the files of the tests that judged it; None for a mutant made before zigdag recorded it, which is made again

    @property
    @deal.post(lambda result: result.startswith("`") and (" became `" in result or result.endswith("` was removed")))
    def summary(self) -> Say:
        """The change in one line: what was written, and what it became."""
        lines = [line for line in self.edit.splitlines() if not line.startswith(_HEADER)]
        before = " ".join(line[1:].strip() for line in lines if line.startswith(_REMOVED))
        after = " ".join(line[1:].strip() for line in lines if line.startswith(_ADDED))
        return f"`{before}` became `{after}`" if after else f"`{before}` was removed"


@dataclass(frozen=True)
class Crossing:
    """A value seen crossing into an operation from another design parameter, or back out of it."""

    at: Place  # the operation
    where: Identifier  # a parameter's name, or RETURNED
    expected: Written | None  # its annotation, as written; None when it has none
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
    where: Say  # standard output, a log record, a file's path
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
    mutation_unavailable: Say | None = None  # why no mutants were made, such as the tool not being installed
    unwatched: tuple[CodePath, ...] = ()  # units whose running the watcher cannot see: its own
    stale: Count = 0  # observations left out because the code they were seen in has changed since

    @deal.ensure(lambda self, test, result: result is None or result.test == test)
    def run_of(self, test: TestId) -> Run | None:
        return self.runs.get(test)

    @deal.ensure(lambda self, place, result: result is None or result.at == place)
    @deal.ensure(lambda self, place, result: result is not None or all(c.at != place for c in self.cases))
    def cases_of(self, place: Place | None) -> Cases | None:
        return next((c for c in self.cases if c.at == place), None)


class Diagnosis(enum.Enum):
    """What a tool that reports on code checks it for. Each is its own part of the code model, since one tool can
    run while the other cannot."""

    LINT = "lint"
    TYPES = "types"
    SECURITY = "security"

    @property
    @deal.ensure(lambda self, result: result.value == f"{self.value.removesuffix('s')} diagnostics")
    def part(self) -> Part:
        """The part of the code model what it reports is."""
        return _DIAGNOSED_PARTS[self]


TOOL_FAILED = RuleName("tools")  # the rule that breaks when a tool could not report: about what it diagnoses
_DIAGNOSED_PARTS: Mapping[Diagnosis, Part] = {Diagnosis.LINT: Part.LINT_DIAGNOSTICS,
                                              Diagnosis.TYPES: Part.TYPE_DIAGNOSTICS,
                                              Diagnosis.SECURITY: Part.SECURITY_DIAGNOSTICS}


class Severity(enum.Enum):
    """How much a tool says a diagnostic matters. Which rules are which is the tool's configuration, not zigdag's."""

    ERROR = "error"
    WARNING = "warning"


ToolName = NewType("ToolName", str)  # the tool that reported, as people know it: ruff, ty
DiagnosticCode = NewType("DiagnosticCode", str)  # the tool's own name for the rule broken: E501, invalid-return-type


@dataclass(frozen=True)
class Diagnostic:
    """One thing a linter or a type checker reported about the code."""

    diagnosis: Diagnosis
    tool: ToolName
    code: DiagnosticCode
    say: Say  # the tool's message, without its code
    span: Span
    severity: Severity


@dataclass(frozen=True)
class Libraries:
    """Third-party packages: the ones the project declares, the ones it vendors, and the standard library."""

    declared: frozenset[Library] | None  # import names; None when the project declares nothing readable
    vendored: frozenset[Library]
    standard: frozenset[Library]


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
    diagnostics: tuple[Diagnostic, ...] = ()  # from the linters and type checkers that ran on the code as it is
    resource_uses: tuple[ResourceUse, ...] = ()  # the code's calls to clients of deployed resources
    settings: tuple[Setting, ...] = ()  # for infrastructure: which settings point at which resource
    grants: tuple[Grant, ...] = ()  # for infrastructure: who is granted what
    supplied: frozenset[Part] = frozenset()
    problems: tuple[Finding, ...] = ()

    @property
    @deal.ensure(lambda self, result: all(u.adapter in result for u in self.units.values()))
    @deal.ensure(lambda self, result: len(result) <= len(self.units))  # no adapter without code of its own
    def adapters(self) -> frozenset[AdapterName]:
        """The adapters whose code this model holds."""
        return frozenset(u.adapter for u in self.units.values())

    @deal.ensure(lambda self, path, result: result is None or result.span.path == path)
    @deal.ensure(lambda self, path, result: result is not None or all(u.span.path != path
                                                                       for u in self.units.values()))
    def unit_at(self, path: RecordPath) -> Unit | None:
        """The unit read from a file: the most specific one, since a folder with no file of its own is placed at
        the first file inside it."""
        return max((u for u in self.units.values() if u.span.path == path), key=lambda u: u.path.count("."),
                   default=None)

    @deal.ensure(lambda self, span, result: result is None or self.unit_of(Qualified(result)) is not None)
    @deal.ensure(lambda self, span, result: (result is None) == (self.unit_at(span.path) is None))
    def code_at(self, span: Span) -> Qualified | None:
        """The innermost symbol written over a place in a file, or the file's unit when no symbol is; None for a file
        that is no unit."""
        unit = self._unit_over(span)
        if unit is None:
            return None
        around = [s for s in self.symbols.values() if s.span.path == span.path
                  and s.span.line <= span.line < s.span.line + max(s.size, 1)]
        innermost = max(around, key=lambda s: (s.span.line, s.name.count(".")), default=None)
        return innermost.qualified if innermost is not None else Qualified(unit.path)

    def _unit_over(self, span: Span) -> Unit | None:
        """The unit written over a place in a file. A file may hold several, as a Terraform file holds resources:
        then the one whose lines the place is in, and otherwise the file's own unit."""
        over = [u for u in self.units.values() if u.span.path == span.path
                and u.span.line <= span.line < u.span.line + max(u.size, 1)]
        return max(over, key=lambda u: (u.span.line, u.path.count(".")), default=self.unit_at(span.path))

    @property
    @deal.ensure(lambda self, result: all(self.units[unit].span.path == path for path, unit in result.items()))
    def files(self) -> Mapping[RecordPath, CodePath]:
        """Each file the units were read from, and the unit it is."""
        paths = sorted({u.span.path for u in self.units.values()})
        return {p: unit.path for p in paths if (unit := self.unit_at(p)) is not None}

    @deal.ensure(lambda self, cls, result: all(s.kind is SymbolKind.METHOD and s.unit == cls.unit
                                                and s.name.rpartition(".")[0] == cls.name for s in result))
    @deal.ensure(lambda self, cls, result: [s.qualified for s in result] == sorted(s.qualified for s in result))
    def members_of(self, cls: Symbol) -> list[Symbol]:
        """What using a class exposes: its public methods and its constructor."""
        prefix = f"{cls.qualified}."
        return [s for q, s in sorted(self.symbols.items()) if q.startswith(prefix) and s.kind is SymbolKind.METHOD
                and (s.public or s.name.endswith(CONSTRUCTOR)) and "." not in q[len(prefix):]]

    @deal.ensure(lambda self, name, result: result is None or (result in self.units and (
        name == result or name.startswith(f"{result}."))))
    def unit_of(self, name: Qualified) -> CodePath | None:
        """The most specific unit a qualified name is in, or None when it is outside the project."""
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            candidate = CodePath(".".join(parts[:i]))
            if candidate in self.units:
                return candidate
        return None

    @deal.ensure(lambda self, value, result: result is None or value.root in self.symbols)
    @deal.ensure(lambda self, value, result: value.called or bool(value.path) or result == (
        value.root if value.root in self.symbols else None))  # a value of a named type, read whole, is of that type
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


ADAPTERS_RULE = RuleName("adapters")  # the rule that breaks when what two adapters read cannot be told apart


def _same_name(models: Sequence[CodeModel]) -> list[Finding]:
    """A break for each unit that two adapters name alike. The model names a unit by its path alone, so two such
    units would be read as one, and every check about either would be about both."""
    seen: dict[CodePath, Unit] = {}
    problems: list[Finding] = []
    for model in models:
        for path, unit in model.units.items():
            first = seen.setdefault(path, unit)
            if first.adapter != unit.adapter:
                problems.append(finding(Result.BREAKS, ADAPTERS_RULE, Subject(path), unit.span, Say(
                    f"{first.adapter} and {unit.adapter} both have code named {path}, which zigdag cannot tell "
                    f"apart yet: rename one of them")))
    return problems


def _libraries(models: Sequence[CodeModel]) -> Libraries:
    # An adapter that could read no declaration says None. One that could stands for the project here, so a second
    # language whose own declaration is missing goes unnoticed: Libraries has to be kept by adapter before two
    # languages that import are read together.
    declared = [m.libraries.declared for m in models if m.libraries.declared is not None]
    return Libraries(frozenset().union(*declared) if declared else None,
                     frozenset().union(*(m.libraries.vendored for m in models)),
                     frozenset().union(*(m.libraries.standard for m in models)))


@deal.pre(lambda models: bool(models))  # with no adapter's model there is no code, which is said as None, not as empty
@deal.ensure(lambda models, result: len(models) > 1 or result == models[0])  # one adapter's model is the whole of it
@deal.ensure(lambda models, result: all(set(m.units) <= set(result.units) and m.supplied <= result.supplied
                                        for m in models))
def joined(models: Sequence[CodeModel]) -> CodeModel:
    """What several adapters read, as one code model (DESIGN2 §5.1): each supplies the parts it can. The adapters
    know nothing of each other; what a container is and the code that runs in it are joined by the record, where one
    design parameter names both."""
    if len(models) == 1:
        return models[0]
    return CodeModel(
        units={path: unit for m in reversed(models) for path, unit in m.units.items()},  # the first to name it stays
        symbols={name: symbol for m in reversed(models) for name, symbol in m.symbols.items()},
        dependencies=tuple(d for m in models for d in m.dependencies),
        calls=tuple(c for m in models for c in m.calls),
        effects=tuple(e for m in models for e in m.effects),
        unknowns=tuple(u for m in models for u in m.unknowns),
        raises=tuple(r for m in models for r in m.raises),
        accesses=tuple(a for m in models for a in m.accesses),
        uses=tuple(u for m in models for u in m.uses),
        planned_uses=tuple(u for m in models for u in m.planned_uses),
        computations=tuple(c for m in models for c in m.computations),
        tests=tuple(t for m in models for t in m.tests),
        results={test: outcome for m in models for test, outcome in m.results.items()},
        # One adapter has a watcher today. When a second does, what each saw has to be joined run by run.
        observed=next((m.observed for m in models if m.observed is not None), None),
        reports_read=any(m.reports_read for m in models),
        libraries=_libraries(models),
        diagnostics=tuple(d for m in models for d in m.diagnostics),
        resource_uses=tuple(u for m in models for u in m.resource_uses),
        settings=tuple(s for m in models for s in m.settings),
        grants=tuple(g for m in models for g in m.grants),
        supplied=frozenset().union(*(m.supplied for m in models)),
        problems=(*(p for m in models for p in m.problems), *_same_name(models)),
    )

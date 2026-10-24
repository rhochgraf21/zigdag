"""What is true of the realization, in a language-neutral form.

Realizes arch.realize.facts: arch's main internal design rule. Adapters produce these records; every
other component consumes them and never reads source code itself.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import NewType, Protocol

SourcePath = NewType("SourcePath", str)  # '/'-separated, relative to the project root
UnitName = NewType("UnitName", str)  # dotted segments, defined by each adapter (e.g. a Python module path)
SymbolName = NewType("SymbolName", str)  # qualified within its unit, e.g. "Graph.resolve"
Language = NewType("Language", str)
SourceText = str
CommitId = NewType("CommitId", str)
VcsLog = NewType("VcsLog", str)  # raw `git log --numstat` output; arch.realize.history reads it
LineNo = NewType("LineNo", int)
FileSuffix = NewType("FileSuffix", str)  # e.g. ".py"
Text = NewType("Text", str)  # display text; facts depend on nothing else in arch, so adapters need only this module


class Capability(enum.Enum):
    """What an adapter analyzed for a unit. Absent capability means "not analyzed", never "nothing found"."""

    STRUCTURE = "structure"  # the unit and its imports
    API = "api"  # public symbols and their signatures
    CONTRACTS = "contracts"
    EFFECTS = "effects"
    LINKS = "links"  # links to design ids


class Effect(enum.Enum):
    """What code can do to the world beyond computing a result. `unknown`: arch could not tell."""

    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    SUBPROCESS = "subprocess"
    STDIO = "stdio"
    NETWORK = "network"
    TIME = "time"
    RANDOM = "random"
    ENV = "env"
    UNKNOWN = "unknown"


class Reach(enum.Enum):
    DIRECT = "direct"  # the code itself names the effectful API
    TRANSITIVE = "transitive"  # through a call to project code that has the effect


class UnitShape(enum.Enum):
    MODULE = "module"
    PACKAGE = "package"  # contains other units


class Role(enum.Enum):
    SOURCE = "source"
    TEST = "test"  # evidence for the design; never mapped to a component


@dataclass(frozen=True, order=True)
class SourceLocation:
    path: SourcePath
    line: LineNo

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Unit:
    name: UnitName
    path: SourcePath
    language: Language
    role: Role
    capabilities: frozenset[Capability]
    summary: Text | None = None  # first line of the unit's leading documentation, if any
    shape: UnitShape = UnitShape.MODULE


class ImportForm(enum.Enum):
    MODULE = "module"  # `import a.b`
    NAME = "name"  # `from a import b`: b may be a submodule or a name bound in a


@dataclass(frozen=True)
class Import:
    unit: UnitName
    target: UnitName  # the most specific name imported; may be outside the project
    location: SourceLocation
    form: ImportForm = ImportForm.MODULE


@dataclass(frozen=True)
class Alias:
    """A module-level name a unit re-exports from elsewhere (`from x import y as name`)."""

    unit: UnitName
    name: SymbolName
    target: Text  # dotted
    location: SourceLocation


@dataclass(frozen=True)
class TypeRef:
    """A type as written, with its leaves: the names that are not containers (`list[str]` -> {"str"})."""

    text: Text
    leaves: frozenset[Text]


@dataclass(frozen=True)
class Parameter:
    name: Text
    type: TypeRef | None  # None: not annotated


@dataclass(frozen=True)
class PublicSymbol:
    unit: UnitName
    name: SymbolName
    kind: Text  # display only, e.g. "function", "method", "class", "field", "value"
    signature: Text  # display only
    location: SourceLocation
    parameters: tuple[Parameter, ...] = ()
    returns: TypeRef | None = None  # for a field, its type


@dataclass(frozen=True)
class ContractDecl:
    unit: UnitName
    symbol: SymbolName
    kind: Text  # e.g. "pre", "post", "ensure", "inv", "has", "raises"
    expression: Text
    location: SourceLocation


@dataclass(frozen=True)
class EffectUse:
    """`symbol` has `effect`, directly or through a call to `via`."""

    unit: UnitName
    symbol: SymbolName  # "<module>" for code that runs at import
    effect: Effect
    reach: Reach
    location: SourceLocation
    via: Text | None = None


@dataclass(frozen=True)
class Call:
    """`symbol` calls (or passes as a callback) the dotted name `callee`, as far as the adapter resolved it."""

    unit: UnitName
    symbol: SymbolName
    callee: Text
    location: SourceLocation


@dataclass(frozen=True)
class ChangeEvent:
    """One commit, and the files it touched."""

    commit: CommitId
    paths: tuple[SourcePath, ...]


class Verdict(enum.Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"

    @property
    def fails(self) -> bool:
        return self in (Verdict.FAILED, Verdict.ERROR)


@dataclass(frozen=True)
class Evidence:
    """One test's outcome in a report. `test` is the dotted id `<unit>.<symbol>` design links use."""

    test: Text
    outcome: Verdict
    report: SourcePath


@dataclass(frozen=True)
class DesignLink:
    unit: UnitName
    symbol: SymbolName
    target: Text  # "<component id>" or "<component id>#ACn", as written
    location: SourceLocation


@dataclass(frozen=True)
class ParseError:
    path: SourcePath
    message: Text
    location: SourceLocation


@dataclass(frozen=True)
class Facts:
    units: tuple[Unit, ...] = ()
    imports: tuple[Import, ...] = ()
    symbols: tuple[PublicSymbol, ...] = ()
    contracts: tuple[ContractDecl, ...] = ()
    links: tuple[DesignLink, ...] = ()
    errors: tuple[ParseError, ...] = ()
    effects: tuple[EffectUse, ...] = ()
    calls: tuple[Call, ...] = ()
    aliases: tuple[Alias, ...] = ()
    changes: tuple[ChangeEvent, ...] = ()  # newest first, as the log lists them
    evidence: tuple[Evidence, ...] = ()  # test outcomes from reports
    _by_name: Mapping[UnitName, Unit] = field(default=None, init=False, repr=False, compare=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_name", {u.name: u for u in self.units})

    def unit(self, name: UnitName) -> Unit | None:
        return self._by_name.get(name)

    @staticmethod
    def merge(parts: Iterable[Facts]) -> Facts:
        parts = list(parts)

        def gather(attr: str) -> tuple:
            items = [x for p in parts for x in getattr(p, attr)]
            return tuple(items) if attr in ("changes", "evidence") else tuple(sorted(items, key=_sort_key))
        return Facts(*(gather(a) for a in ("units", "imports", "symbols", "contracts", "links", "errors", "effects", "calls", "aliases",
                                         "changes", "evidence")))


def _sort_key(fact: object) -> tuple:
    """Source order: path, then line as a number, then content for ties."""
    loc = getattr(fact, "location", None)
    return (loc.path, loc.line, repr(fact)) if loc else (getattr(fact, "path", ""), 0, repr(fact))


@dataclass(frozen=True)
class Roots:
    """Where units live, relative to the project root: source roots and test roots."""

    source: tuple[SourcePath, ...]
    test: tuple[SourcePath, ...]

    def role_of(self, path: SourcePath) -> Role:
        return Role.TEST if any(_under(path, r) for r in self.test) else Role.SOURCE

    def root_of(self, path: SourcePath) -> SourcePath | None:
        """The most specific root containing `path`."""
        matches = [r for r in (*self.source, *self.test) if _under(path, r)]
        return max(matches, key=len) if matches else None


def _under(path: str, root: str) -> bool:
    return root in ("", ".") or path == root or path.startswith(root.rstrip("/") + "/")


@dataclass(frozen=True)
class Snapshot:
    """Source files as data. The workspace builds it; realize never touches the filesystem."""

    files: Mapping[SourcePath, SourceText]
    roots: Roots
    log: VcsLog | None = None
    reports: Mapping[SourcePath, SourceText] = field(default_factory=dict)  # test reports (JUnit XML)


class Adapter(Protocol):
    """A language adapter. Built-in ones live in realize; others can be supplied by the caller."""

    language: Language
    suffixes: tuple[FileSuffix, ...]

    def unit_name(self, path: SourcePath, roots: Roots) -> UnitName | None: ...

    def extract(self, path: SourcePath, text: SourceText, unit: UnitName, role: Role) -> Facts: ...

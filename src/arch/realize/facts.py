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
LineNo = NewType("LineNo", int)
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


@dataclass(frozen=True)
class Import:
    unit: UnitName
    target: UnitName  # the most specific module named; may be outside the project
    location: SourceLocation


@dataclass(frozen=True)
class PublicSymbol:
    unit: UnitName
    name: SymbolName
    kind: Text  # display only, e.g. "function", "class", "value"
    signature: Text  # display only
    location: SourceLocation


@dataclass(frozen=True)
class ContractDecl:
    unit: UnitName
    symbol: SymbolName
    kind: Text  # e.g. "pre", "post", "ensure", "inv", "has", "raises"
    expression: Text
    location: SourceLocation


@dataclass(frozen=True)
class EffectUse:
    """`symbol` has `effect`: directly, or (direct=False) through a call to `via`."""

    unit: UnitName
    symbol: SymbolName  # "<module>" for code that runs at import
    effect: Effect
    direct: bool
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
    _by_name: Mapping[UnitName, Unit] = field(default=None, init=False, repr=False, compare=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_name", {u.name: u for u in self.units})

    def unit(self, name: UnitName) -> Unit | None:
        return self._by_name.get(name)

    @staticmethod
    def merge(parts: Iterable[Facts]) -> Facts:
        parts = list(parts)
        def gather(attr: str) -> tuple:
            return tuple(sorted((x for p in parts for x in getattr(p, attr)), key=_sort_key))
        return Facts(*(gather(a) for a in ("units", "imports", "symbols", "contracts", "links", "errors", "effects", "calls")))


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


class Adapter(Protocol):
    """A language adapter. Built-in ones live in realize; others can be supplied by the caller."""

    language: Language
    suffixes: tuple[str, ...]

    def unit_name(self, path: SourcePath, roots: Roots) -> UnitName | None: ...

    def extract(self, path: SourcePath, text: SourceText, unit: UnitName, role: Role) -> Facts: ...

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


class Exposure(enum.Enum):
    PUBLIC = "public"  # part of the unit's interface (for Python: listed in __all__)
    INTERNAL = "internal"  # imported for the unit's own use


@dataclass(frozen=True)
class Alias:
    """A module-level name a unit binds to something defined elsewhere (`from x import y as name`)."""

    unit: UnitName
    name: SymbolName
    target: Text  # dotted
    location: SourceLocation
    exposure: Exposure = Exposure.INTERNAL


@dataclass(frozen=True)
class TypeRef:
    """A type as written, with its leaves: the names that are not containers (`list[str]` -> {"str"})."""

    text: Text
    leaves: frozenset[Text]


class Optionality(enum.Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"  # has a default, or collects extra arguments (*args, **kwargs)


@dataclass(frozen=True)
class Parameter:
    name: Text
    type: TypeRef | None  # None: not annotated
    optionality: Optionality = Optionality.REQUIRED


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
    kind: Text  # e.g. "pre", "post", "ensure", "inv", "has", "raises", "pure"
    expression: Text
    location: SourceLocation
    literals: tuple[Text, ...] = ()  # string arguments, e.g. the markers of has("network", "io")


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


class MutantOutcome(enum.Enum):
    KILLED = "killed"  # a test failed on the mutant: the tests constrain this code
    SURVIVED = "survived"  # every test passed on the mutant
    NOT_CHECKED = "not checked"
    INCONCLUSIVE = "inconclusive"  # timeouts, crashes and other results


@dataclass(frozen=True)
class Mutant:
    """One mutation of a function, and whether the tests noticed it."""

    path: SourcePath
    symbol: SymbolName
    outcome: MutantOutcome


@dataclass(frozen=True)
class DesignLink:
    unit: UnitName
    symbol: SymbolName
    target: Text  # "<component id>" or "<component id>#ACn", as written
    location: SourceLocation


@dataclass(frozen=True)
class FileChange:
    """A file changed between two revisions, with its line counts (from `git diff --numstat`)."""

    path: SourcePath
    added: LineNo
    removed: LineNo


class DiffLineKind(enum.Enum):
    CONTEXT = " "
    ADDED = "+"
    REMOVED = "-"


@dataclass(frozen=True)
class DiffLine:
    kind: DiffLineKind
    text: Text
    old_line: LineNo | None  # None for added lines
    new_line: LineNo | None  # None for removed lines


@dataclass(frozen=True)
class Hunk:
    old_start: LineNo
    new_start: LineNo
    header: Text  # what git shows after @@, usually the enclosing definition
    lines: tuple[DiffLine, ...]

    @property
    def changed(self) -> tuple[DiffLine, ...]:
        return tuple(line for line in self.lines if line.kind is not DiffLineKind.CONTEXT)


class FileShape(enum.Enum):
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"


class Content(enum.Enum):
    TEXT = "text"
    BINARY = "binary"


@dataclass(frozen=True)
class FileDiff:
    """One file's change between two revisions, as hunks of lines."""

    path: SourcePath  # the new path (the old one for deletions)
    old_path: SourcePath | None  # set for renames
    shape: FileShape
    hunks: tuple[Hunk, ...]
    content: Content = Content.TEXT
    similarity: LineNo | None = None  # rename similarity, in percent

    @property
    def added(self) -> LineNo:
        return LineNo(sum(1 for h in self.hunks for line in h.lines if line.kind is DiffLineKind.ADDED))

    @property
    def removed(self) -> LineNo:
        return LineNo(sum(1 for h in self.hunks for line in h.lines if line.kind is DiffLineKind.REMOVED))


class PortChangeType(enum.Enum):
    ADDED = "added"
    REMOVED = "removed"
    SIGNATURE = "signature changed"
    CONTRACT = "contract changed"


class Compatibility(enum.Enum):
    """What a port change means for callers. In order of severity."""

    BREAKING = "breaking"
    NEEDS_REVIEW = "needs review"  # arch cannot tell (contract and return-type changes)
    COMPATIBLE = "compatible"


@dataclass(frozen=True)
class PortChange:
    unit: UnitName
    symbol: SymbolName
    type: PortChangeType
    compatibility: Compatibility
    before: Text | None
    after: Text | None


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
    mutants: tuple[Mutant, ...] = ()
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
            return tuple(items) if attr in ("changes", "evidence", "mutants") else tuple(sorted(items, key=_sort_key))
        return Facts(*(gather(a) for a in ("units", "imports", "symbols", "contracts", "links", "errors", "effects", "calls", "aliases",
                                         "changes", "evidence", "mutants")))


def _sort_key(fact: object) -> tuple:
    """Source order: path, then line as a number, then content for ties."""
    loc = getattr(fact, "location", None)
    return (loc.path, loc.line, repr(fact)) if loc else (getattr(fact, "path", ""), 0, repr(fact))


def port_changes(before: Facts, after: Facts) -> tuple[PortChange, ...]:
    """How public symbols and their contracts changed, each classified for callers. A name a unit still
    re-exports (a package facade importing it from a submodule) has not gone away."""
    old, contracts_old = _public(before)
    new, contracts_new = _public(after)
    out: list[PortChange] = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is None:
            out.append(PortChange(*key, PortChangeType.ADDED, Compatibility.COMPATIBLE, None, b.signature))
        elif b is None:
            out.append(PortChange(*key, PortChangeType.REMOVED, Compatibility.BREAKING, a.signature, None))
        elif a.parameters != b.parameters or a.returns != b.returns:
            out.append(PortChange(*key, PortChangeType.SIGNATURE, _signature_compatibility(a, b), a.signature, b.signature))
        if a is not None and b is not None and contracts_old.get(key, ()) != contracts_new.get(key, ()):
            out.append(PortChange(*key, PortChangeType.CONTRACT, Compatibility.NEEDS_REVIEW,
                                  Text("; ".join(contracts_old.get(key, ()))) or None,
                                  Text("; ".join(contracts_new.get(key, ()))) or None))
    return tuple(out)


def _public(facts: Facts) -> tuple[dict[tuple[UnitName, SymbolName], PublicSymbol],
                                   dict[tuple[UnitName, SymbolName], tuple[str, ...]]]:
    """Public names per unit, including names re-exported from elsewhere, with their contracts."""
    symbols = {(s.unit, s.name): s for s in facts.symbols}
    contracts: dict[tuple[UnitName, SymbolName], list[str]] = {}
    for c in facts.contracts:
        contracts.setdefault((c.unit, c.symbol), []).append(f"{c.kind}({c.expression})")
    by_dotted = {f"{s.unit}.{s.name}": s for s in facts.symbols}
    for a in facts.aliases:
        if a.exposure is not Exposure.PUBLIC:
            continue
        for dotted, s in by_dotted.items():  # the re-exported name, and the members of a re-exported class
            if dotted == a.target or dotted.startswith(a.target + "."):
                key = (a.unit, SymbolName(a.name + dotted[len(a.target):]))
                if key not in symbols:
                    symbols[key] = s
                    contracts[key] = contracts.get((s.unit, s.name), [])
    return symbols, {k: tuple(sorted(v)) for k, v in contracts.items()}


def _signature_compatibility(a: PublicSymbol, b: PublicSymbol) -> Compatibility:
    """Callers break when a parameter goes away, changes type, or a new one is required."""
    old = {p.name: p for p in a.parameters}
    new = {p.name: p for p in b.parameters}
    if any(n not in new or new[n].type != p.type for n, p in old.items()):
        return Compatibility.BREAKING
    if any(n not in old and p.optionality is Optionality.REQUIRED for n, p in new.items()):
        return Compatibility.BREAKING
    if [p.name for p in a.parameters] != [p.name for p in b.parameters][: len(a.parameters)]:
        return Compatibility.BREAKING  # positional order changed
    if a.returns != b.returns:
        return Compatibility.NEEDS_REVIEW
    return Compatibility.COMPATIBLE


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
    mutation_reports: Mapping[SourcePath, SourceText] = field(default_factory=dict)  # mutmut .meta files


class Adapter(Protocol):
    """A language adapter. Built-in ones live in realize; others can be supplied by the caller."""

    language: Language
    suffixes: tuple[FileSuffix, ...]

    def unit_name(self, path: SourcePath, roots: Roots) -> UnitName | None: ...

    def extract(self, path: SourcePath, text: SourceText, unit: UnitName, role: Role) -> Facts: ...

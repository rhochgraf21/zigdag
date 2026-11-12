"""How TypeScript names its modules, and what an import refers to (DESIGN2 §5.2).

A file is a module, named by its path without its extension: web/src/cart. A folder's index file is the folder
itself. An import is followed the way the compiler follows one written in a project: beside the importing file,
or through an alias that a tsconfig.json gives (`baseUrl`, `paths`). Anything else is a library, by the name of
its package.

What is not followed: a tsconfig's `extends`, and a package's own `exports` map. An import that neither names a
module of the project nor reads as a package's name is left as it is written.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import deal

from zigdag.adapters.typescript import apis
from zigdag.core.findings import RecordPath
from zigdag.core.names import CodePath, Library
from zigdag.core.texts import FileText

SUFFIXES = (".ts", ".tsx", ".mts", ".cts")
_WRITTEN_AS = (".js", ".jsx", ".mjs", ".cjs")  # how an import may name a module that is written in TypeScript
INDEX = "index"  # the file that is its folder's own module
_RELATIVE = ("./", "../")
_SCOPE = "@"  # a package in a scope has two parts to its name: @scope/name
_WILDCARD = "*"
_COMMENT = re.compile(r'("(?:[^"\\]|\\.)*")|//[^\n]*|/\*.*?\*/', re.S)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_DEPENDENCY_KEYS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def _stem(path: RecordPath) -> str:
    """A source file's path without its extension."""
    return next((path[:-len(suffix)] for suffix in SUFFIXES if path.endswith(suffix)), path)


@deal.pre(lambda path: path.endswith(SUFFIXES))
@deal.ensure(lambda path, result: path.startswith(result))
def unit_path(path: RecordPath) -> CodePath:
    """The module a source file is: its path without its extension, and its folder when it is the folder's index."""
    stem = _stem(path)
    folder, _, last = stem.rpartition("/")
    return CodePath(folder if last == INDEX and folder else stem)


@deal.pre(lambda path: path.endswith(SUFFIXES))
def is_index(path: RecordPath) -> bool:
    return _stem(path).rpartition("/")[2] == INDEX


@deal.ensure(lambda specifier, result: "/" not in result.removeprefix(_SCOPE) or result.startswith(_SCOPE))
def package_of(specifier: str) -> Library:
    """The package an import of a library names: its first part, or its first two when it is in a scope. A module
    that comes with Node is named without Node's own prefix."""
    parts = specifier.removeprefix(apis.NODE_SCHEME).split("/")
    return Library("/".join(parts[:2]) if parts[0].startswith(_SCOPE) and len(parts) > 1 else parts[0])


def _json(text: FileText) -> object:
    """A JSON file as tsconfig.json may be written: with comments, and with a comma after the last item."""
    plain = _COMMENT.sub(lambda found: found.group(1) or "", text)
    return json.loads(_TRAILING_COMMA.sub(r"\1", plain))


@dataclass(frozen=True)
class Aliases:
    """The aliases one tsconfig.json gives the imports of the files under its folder."""

    folder: RecordPath  # where the tsconfig.json is
    base: RecordPath | None  # its baseUrl, from the project's root: where a name that is not relative may start
    paths: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # a pattern -> where it leads, from the base

    @deal.ensure(lambda self, specifier, result: all(not r.startswith(_RELATIVE) for r in result))
    def candidates(self, specifier: str) -> tuple[str, ...]:
        """Where an import that is not relative may lead, from the project's root: through each pattern it fits,
        then from the base itself."""
        root = self.base if self.base is not None else self.folder
        found = []
        for pattern, targets in self.paths.items():
            head, star, tail = pattern.partition(_WILDCARD)
            fits = specifier.startswith(head) and specifier.endswith(tail) if star else specifier == pattern
            if fits:
                middle = specifier[len(head):len(specifier) - len(tail)] if star else ""
                found += [posixpath.normpath(posixpath.join(root, target.replace(_WILDCARD, middle)))
                          for target in targets]
        if self.base is not None:
            found.append(posixpath.normpath(posixpath.join(self.base, specifier)))
        return tuple(found)


@deal.ensure(lambda path, text, result: result is None or result.folder == posixpath.dirname(path))
def read_aliases(path: RecordPath, text: FileText) -> Aliases | None:
    """The aliases a tsconfig.json gives; None when it cannot be read."""
    try:
        raw = _json(text)
    except json.JSONDecodeError:
        return None
    options = raw.get("compilerOptions", {}) if isinstance(raw, Mapping) else {}
    options = options if isinstance(options, Mapping) else {}
    folder = RecordPath(posixpath.dirname(path))
    base, paths = options.get("baseUrl"), options.get("paths")
    return Aliases(folder,
                   RecordPath(posixpath.normpath(posixpath.join(folder, base))) if isinstance(base, str) else None,
                   {pattern: tuple(t for t in targets if isinstance(t, str))
                    for pattern, targets in (paths.items() if isinstance(paths, Mapping) else ())
                    if isinstance(targets, list)})


@deal.ensure(lambda text, result: result is None or all(name for name in result))
def declared_libraries(text: FileText) -> frozenset[Library] | None:
    """The packages a package.json declares, or None when it cannot be read. A package used only to build or to
    test is declared too: which of them the code that ships may import is the bundler's to say, not this file's."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, Mapping):
        return None
    return frozenset(Library(name) for key in _DEPENDENCY_KEYS
                     for name in (raw.get(key) if isinstance(raw.get(key), Mapping) else {}))


@dataclass(frozen=True)
class Target:
    """What an import refers to: a module of the project, or a library by its package."""

    unit: CodePath | None = None
    library: Library | None = None

    @property
    @deal.ensure(lambda self, result: result == (self.unit or self.library or ""))
    def name(self) -> str:
        return self.unit or self.library or ""


@dataclass(frozen=True)
class Resolver:
    """What the project's imports refer to."""

    stems: Mapping[str, CodePath]  # each source file's path without its extension -> the module it is
    aliases: tuple[Aliases, ...] = ()

    @staticmethod
    @deal.ensure(lambda sources, aliases=(), *, result: len(result.stems) == len(set(sources)))
    def of(sources: Iterable[RecordPath], aliases: Iterable[Aliases] = ()) -> Resolver:
        return Resolver({_stem(path): unit_path(path) for path in sources},
                        tuple(sorted(aliases, key=lambda a: len(a.folder), reverse=True)))  # the nearest first

    def _module(self, written: str) -> CodePath | None:
        """The module a path names, from the project's root: the file of that name, or the index of that folder. An
        import may name the JavaScript a file is built into."""
        bare = next((written[:-len(suffix)] for suffix in (*SUFFIXES, *_WRITTEN_AS) if written.endswith(suffix)),
                    written)
        return next((self.stems[stem] for stem in (written, bare, f"{written}/{INDEX}", f"{bare}/{INDEX}")
                     if stem in self.stems), None)

    @deal.ensure(lambda self, importer, specifier, result: result.unit is None or result.unit in self.stems.values())
    @deal.ensure(lambda self, importer, specifier, result: result.unit is None or result.library is None)
    def resolve(self, importer: RecordPath, specifier: str) -> Target:
        """What an import written in a file refers to. A relative import that names no module of the project refers
        to nothing zigdag read."""
        if specifier.startswith(_RELATIVE) or specifier in (".", ".."):
            return Target(self._module(posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))))
        nearest = next((a for a in self.aliases if not a.folder or importer.startswith(f"{a.folder}/")), None)
        for candidate in nearest.candidates(specifier) if nearest is not None else ():
            module = self._module(candidate)
            if module is not None:
                return Target(module)
        return Target(library=package_of(specifier))

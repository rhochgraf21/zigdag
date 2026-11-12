"""The names used in the record, and how each is written (DESIGN2 §7.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NewType

import deal

from zigdag.core.measures import Count
from zigdag.core.texts import SentenceText, Written

FrName = NewType("FrName", str)  # lowercase identifiers joined by dots, starting at the root: mojo2verus.core.emit
Slug = NewType("Slug", str)  # lowercase words joined by hyphens: wrong-proof-passes
AdapterName = NewType("AdapterName", str)  # the adapter a code name belongs to: python, terraform, ...
CodePath = NewType("CodePath", str)  # a name inside one adapter: emit.translator_names, aws_s3_bucket.site
CheckKindName = NewType("CheckKindName", str)  # effects, may-depend-on, max-lines, or a registered kind
RuleId = NewType("RuleId", str)  # the name of a constraint, process variable or built-in: pure-core, max-lines
Identifier = NewType("Identifier", str)  # a name in code, as written: a parameter, a field, a method
Library = NewType("Library", str)  # an importable top-level package that is not the project's own
Api = NewType("Api", str)  # an API as the code writes it: open, subprocess.run, print
Glob = NewType("Glob", str)  # a file pattern, such as .zigdag/*.xml
Revision = NewType("Revision", str)  # a git revision, such as main
BranchName = NewType("BranchName", str)  # a git branch, as git names it: main, part/shop.checkout
ShellCommand = NewType("ShellCommand", str)  # a command a shell runs, such as zigdag or uv run zigdag
Argument = NewType("Argument", str)  # one argument of a command line, as it was typed or as zigdag builds it
ParamName = NewType("ParamName", str)  # the name of a rule's parameter, such as allow
Key = NewType("Key", str)  # a key of a design file, as written
ProjectRoot = NewType("ProjectRoot", Path)  # the folder a project is in
FolderName = NewType("FolderName", str)  # the last part of a folder's path, as it is on disk
FilePath = NewType("FilePath", Path)  # a file's place on disk

PYTHON = AdapterName("python")
TERRAFORM = AdapterName("terraform")
SQL = AdapterName("sql")
TYPESCRIPT = AdapterName("typescript")
GO = AdapterName("go")
RUST = AdapterName("rust")
ADAPTERS: frozenset[AdapterName] = frozenset({PYTHON, TERRAFORM, SQL, TYPESCRIPT, GO, RUST})
INFRASTRUCTURE: frozenset[AdapterName] = frozenset({TERRAFORM})  # the adapters that read what is deployed

# How the parts of a code name are joined. A language joins its units its own way: Python's packages by dots, the
# folders of TypeScript and Go by slashes. A name inside a unit, such as a type's, is joined by a dot in each.
PART_SEPARATORS = (".", "/")
_PART = re.compile("[./]")


@deal.ensure(lambda name, result: result[0] == name and len(result) == nesting(name) + 1)
@deal.ensure(lambda name, result: all(is_inside(name, outer) for outer in result))
def enclosing(name: Written) -> tuple[Written, ...]:
    """A code name, then each name it is inside, the nearest first: web/src/cart.Order, web/src/cart, web/src,
    web."""
    cuts = [found.start() for found in _PART.finditer(name)]
    return (name, *(Written(name[:cut]) for cut in reversed(cuts)))


@deal.ensure(lambda name, outer, result: result == (name == outer or any(
    name.startswith(outer + separator) for separator in PART_SEPARATORS)))
def is_inside(name: Written, outer: Written) -> bool:
    """Whether a code name is another, or is inside it."""
    return name == outer or name.startswith(tuple(outer + separator for separator in PART_SEPARATORS))


@deal.ensure(lambda name, result: result >= 0)
def nesting(name: Written) -> Count:
    """How many names a code name is inside."""
    return Count(len(_PART.findall(name)))


@deal.ensure(lambda outer, name, result: all(is_inside(joined, outer) and joined.endswith(name) for joined in result))
def within(outer: Written, name: Written) -> tuple[Written, ...]:
    """The names a name written inside another could be, one for each way parts are joined: inside shop, api is
    shop.api or shop/api."""
    return tuple(Written(f"{outer}{separator}{name}") for separator in PART_SEPARATORS)


_FR = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
_SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_CODE_PATH = re.compile(r"[^\s:]+")


@deal.ensure(lambda text, result: result is None or result == text)  # a name is its text, never a changed one
@deal.ensure(lambda text, result: result is None or all(p[:1].isalpha() and p == p.lower() for p in result.split(".")))
def fr_name(text: Written) -> FrName | None:
    return FrName(text) if _FR.fullmatch(text) else None


@deal.ensure(lambda text, result: result is None or result == text)
@deal.ensure(lambda text, result: result is None or all(w and w == w.lower() for w in result.split("-")))
def slug(text: Written) -> Slug | None:
    return Slug(text) if _SLUG.fullmatch(text) else None


@deal.ensure(lambda name, result: result is None or (is_within(name, result) and depth(result) == depth(name) - 1))
@deal.ensure(lambda name, result: (result is None) == ("." not in name))  # only the root has no parent
def parent(name: FrName) -> FrName | None:
    head, dot, _ = name.rpartition(".")
    return FrName(head) if dot else None


@deal.ensure(lambda name, result: result == len(name.split(".")) - 1)
def depth(name: FrName) -> Count:
    """0 for the root, 1 for the first level below it."""
    return name.count(".")


@deal.ensure(lambda name, result: "." not in result and "_" not in result)
@deal.ensure(lambda name, result: name.endswith(result.replace(" ", "_")))  # the last part, read aloud
def subject(name: FrName) -> SentenceText:
    """The words an EARS statement uses for this name: its last part, with underscores read as spaces."""
    return name.rpartition(".")[2].replace("_", " ")


@deal.ensure(lambda name, ancestor, result: result == (name == ancestor or (
    (above := parent(name)) is not None and is_within(above, ancestor))))  # the name, or within its parent
def is_within(name: FrName, ancestor: FrName) -> bool:
    return name == ancestor or name.startswith(ancestor + ".")


PART_BRANCHES = "part/"  # what the name of the branch one part is built on starts with; the part's name follows


@deal.ensure(lambda part, result: part_built_on(result) == part)  # the branch says whose it is
def branch_of(part: FrName) -> BranchName:
    """The branch a part is built on. A part is one agent's at a time, and its branch is how everyone sees that."""
    return BranchName(f"{PART_BRANCHES}{part}")


@deal.ensure(lambda branch, result: result is None or branch == f"{PART_BRANCHES}{result}")
def part_built_on(branch: BranchName) -> FrName | None:
    """The part a branch is the branch of; None for any other branch."""
    return fr_name(Written(branch.removeprefix(PART_BRANCHES))) if branch.startswith(PART_BRANCHES) else None


@dataclass(frozen=True, order=True)
class OutcomeRef:
    """`job.outcome`, for example verify-programs.wrong-proof-passes."""

    job: Slug
    outcome: Slug

    def __str__(self) -> str:
        return f"{self.job}.{self.outcome}"

    @staticmethod
    @deal.ensure(lambda text, result: result is None or str(result) == text)  # it reads back as written
    def parse(text: Written) -> OutcomeRef | None:
        job, dot, outcome = text.partition(".")
        a, b = slug(job), slug(outcome)
        return OutcomeRef(a, b) if dot and a and b else None


STATEMENT_SEPARATOR = "#"  # between an FR's name and a statement's: mojo2verus.core.emit#same-output


@deal.ensure(lambda reference, result: STATEMENT_SEPARATOR not in result and reference.startswith(result))
def named_fr(reference: Written) -> Written:
    """The FR part of a name that may be a statement reference."""
    return reference.partition(STATEMENT_SEPARATOR)[0]


@dataclass(frozen=True, order=True)
class StatementRef:
    """`fr#statement`, for example mojo2verus.core.emit#same-output."""

    fr: FrName
    statement: Slug

    def __str__(self) -> str:
        return f"{self.fr}{STATEMENT_SEPARATOR}{self.statement}"


@dataclass(frozen=True, order=True)
class CodeName:
    """`adapter:path`. Without a prefix (adapter None), the project's default adapter is meant."""

    adapter: AdapterName | None
    path: CodePath

    def __str__(self) -> str:
        return f"{self.adapter}:{self.path}" if self.adapter else self.path

    @deal.ensure(lambda self, default, result: result == (default if self.adapter is None else self.adapter))
    def adapter_or(self, default: AdapterName | None) -> AdapterName | None:
        """The adapter it names, or the project's default when it names none."""
        return self.adapter or default

    @staticmethod
    @deal.ensure(lambda text, result: result is None or str(result) == text)  # it reads back as written
    @deal.ensure(lambda text, result: result is None or result.adapter is None or result.adapter in ADAPTERS)
    def parse(text: Written) -> CodeName | None:
        prefix, colon, rest = text.partition(":")
        if not colon:
            return CodeName(None, CodePath(text)) if _CODE_PATH.fullmatch(text) else None
        if AdapterName(prefix) not in ADAPTERS or not _CODE_PATH.fullmatch(rest):
            return None
        return CodeName(AdapterName(prefix), CodePath(rest))

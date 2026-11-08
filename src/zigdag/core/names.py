"""The names used in the record, and how each is written (DESIGN2 §7.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NewType

FrName = NewType("FrName", str)  # lowercase identifiers joined by dots, starting at the root: mojo2verus.core.emit
Slug = NewType("Slug", str)  # lowercase words joined by hyphens: wrong-proof-passes
AdapterName = NewType("AdapterName", str)  # the adapter a code name belongs to: python, terraform, ...
CodePath = NewType("CodePath", str)  # a name inside one adapter: emit.translator_names, aws_s3_bucket.site
CheckKindName = NewType("CheckKindName", str)  # effects, may-depend-on, max-lines, or a registered kind
RuleId = NewType("RuleId", str)  # the name of a constraint, process variable or built-in: pure-core, max-lines

PYTHON = AdapterName("python")
TERRAFORM = AdapterName("terraform")
SQL = AdapterName("sql")
TYPESCRIPT = AdapterName("typescript")
GO = AdapterName("go")
RUST = AdapterName("rust")
ADAPTERS: frozenset[AdapterName] = frozenset({PYTHON, TERRAFORM, SQL, TYPESCRIPT, GO, RUST})

_FR = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
_SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_CODE_PATH = re.compile(r"[^\s:]+")


def fr_name(text: str) -> FrName | None:
    return FrName(text) if _FR.fullmatch(text) else None


def slug(text: str) -> Slug | None:
    return Slug(text) if _SLUG.fullmatch(text) else None


def parent(name: FrName) -> FrName | None:
    head, dot, _ = name.rpartition(".")
    return FrName(head) if dot else None


def depth(name: FrName) -> int:
    """0 for the root, 1 for the first level below it."""
    return name.count(".")


def subject(name: FrName) -> str:
    """The words an EARS statement uses for this name: its last part, with underscores read as spaces."""
    return name.rpartition(".")[2].replace("_", " ")


def is_within(name: FrName, ancestor: FrName) -> bool:
    return name == ancestor or name.startswith(ancestor + ".")


@dataclass(frozen=True, order=True)
class OutcomeRef:
    """`job.outcome`, for example verify-programs.wrong-proof-passes."""

    job: Slug
    outcome: Slug

    def __str__(self) -> str:
        return f"{self.job}.{self.outcome}"

    @staticmethod
    def parse(text: str) -> OutcomeRef | None:
        job, dot, outcome = text.partition(".")
        a, b = slug(job), slug(outcome)
        return OutcomeRef(a, b) if dot and a and b else None


STATEMENT_SEPARATOR = "#"  # between an FR's name and a statement's: mojo2verus.core.emit#same-output


def named_fr(reference: str) -> str:
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

    def adapter_or(self, default: AdapterName | None) -> AdapterName | None:
        """The adapter it names, or the project's default when it names none."""
        return self.adapter or default

    @staticmethod
    def parse(text: str) -> CodeName | None:
        prefix, colon, rest = text.partition(":")
        if not colon:
            return CodeName(None, CodePath(text)) if _CODE_PATH.fullmatch(text) else None
        if AdapterName(prefix) not in ADAPTERS or not _CODE_PATH.fullmatch(rest):
            return None
        return CodeName(AdapterName(prefix), CodePath(rest))

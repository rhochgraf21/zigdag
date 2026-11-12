"""What the branch of one part is held to (DESIGN2 §4.8): it changes the part's own code, the tests and the log, and
nothing else, and it leaves what other parts are built against as it found it.

Parts are built at the same time, each on its own branch, by agents that cannot see each other. That is safe only
while what they share stays still: the design, and the names, types and fields that cross between parts. So both are
settled before any part is built, and a branch that moves one is stopped here, where it is made, rather than found
when two branches meet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import deal

from zigdag.core.checks.run import Analysis
from zigdag.core.code import Qualified, Symbol, SymbolKind
from zigdag.core.findings import Finding, RecordPath, Result, RuleName, Span, Subject, finding
from zigdag.core.log import GIT_ATTRIBUTES, LOG_FILE
from zigdag.core.measures import Column, Count, Line
from zigdag.core.names import BranchName, FrName, Identifier, is_within
from zigdag.core.record.read import DESIGN_DIR
from zigdag.core.texts import Say, Written

STAY_IN_PART = RuleName("stay-in-part")  # a part's branch changed a file that is not the part's
SETTLED_FIRST = RuleName("settled-first")  # a part's branch changed what other parts are built against
PART_RULES = frozenset({STAY_IN_PART, SETTLED_FIRST})
FOLDER_SEPARATOR = "/"  # between the folders of a record path
# What adding an event to the log writes: the log, and the line that has git merge it as a union. A part's branch
# raises what it finds, so it changes both.
_THE_LOGS = frozenset({LOG_FILE, GIT_ATTRIBUTES})


@dataclass(frozen=True)
class PartBranch:
    """The branch one part is built on, as git has it."""

    part: FrName
    line: BranchName  # the branch it lands on, which it tracks
    behind: Count  # how many commits of the line it does not have yet
    touched: tuple[RecordPath, ...]  # every file that is not as it was where the branch left the line


@dataclass(frozen=True)
class Shape:
    """What code that uses a name is built against: its parameters and what it returns, or its fields, bases and
    members, each as written. Where it is written, and what it does, are not part of it."""

    kind: SymbolKind
    parameters: tuple[tuple[Identifier, Written | None], ...]
    returns: Written | None
    fields: tuple[tuple[Identifier, Written | None], ...]
    bases: tuple[Written, ...]
    members: tuple[Identifier, ...]

    @staticmethod
    @deal.ensure(lambda symbol, result: result.kind is symbol.kind and len(result.fields) == len(symbol.fields))
    def of(symbol: Symbol) -> Shape:
        signature = symbol.signature
        return Shape(
            symbol.kind,
            tuple((p.name, p.type.text if p.type else None) for p in signature.params) if signature else (),
            signature.returns.text if signature and signature.returns else None,
            tuple((f.name, f.type.text if f.type else None) for f in symbol.fields),
            tuple(b.text for b in symbol.bases), symbol.members)


def _under(path: RecordPath, folder: RecordPath) -> bool:
    return path == folder or path.startswith(folder + FOLDER_SEPARATOR)


def _whose(path: RecordPath, start: Analysis, now: Analysis) -> FrName | None:
    """The part a file's code belongs to: as the design has it now, or as it had it for a file that is gone."""
    return now.dp_of_file(path) or start.dp_of_file(path)


def _outside(branch: PartBranch, start: Analysis, now: Analysis) -> Iterable[Finding]:
    part = branch.part
    allowed = f"on the branch of {part}, only its own code, the tests and the log change"
    for path in sorted(set(branch.touched)):
        owner = _whose(path, start, now)
        if owner is not None and is_within(owner, part):
            continue
        if owner is not None:
            said = f"{path} is the code of {owner}: {allowed}"
        elif path in _THE_LOGS or any(_under(path, r) for r in now.settings.test_roots):
            continue
        elif _under(path, RecordPath(DESIGN_DIR)):
            said = (f"{path} is the design, which is settled before a part is built: when it is wrong, raise that "
                    f"(zigdag raise), and stop")
        else:
            said = f"{path} is no part's code: {allowed}"
        yield finding(Result.BREAKS, STAY_IN_PART, Subject(path), Span(path, Line(1), Column(1)), Say(said))


def _symbol_of(a: Analysis, name: Qualified) -> Symbol | None:
    """The symbol a name written in code is, or is inside: an attribute read from a class is a use of the class."""
    if a.code is None:
        return None
    at = name
    while at and at not in a.code.symbols:
        at = Qualified(at.rpartition(".")[0])
    return a.code.symbols.get(at)


def _inside(a: Analysis, name: Qualified, part: FrName) -> bool:
    """Whether a name in the code belongs to a part, or to a part inside it."""
    owner = a.tree.owner(name) if a.tree is not None else None
    return owner is not None and is_within(owner, part)


@deal.ensure(lambda a, part, result: all(_inside(a, name, part) and not is_within(user, part)
                                         for name, user in result.items()))
def relied_on(a: Analysis, part: FrName) -> Mapping[Qualified, FrName]:
    """Each name of a part that code outside the part uses, with one part that uses it. Using a class is using what
    the class exposes, so its public methods and its constructor are relied on with it."""
    if a.code is None or a.tree is None or a.relations is None:
        return {}
    out: dict[Qualified, FrName] = {}
    for edge in a.relations.edges:
        symbol = _symbol_of(a, edge.target_name)
        if symbol is None or is_within(edge.source, part) or not _inside(a, symbol.qualified, part):
            continue
        exposed = a.code.members_of(symbol) if symbol.kind is SymbolKind.CLASS else []
        for s in (symbol, *exposed):
            if _inside(a, s.qualified, part):
                out.setdefault(s.qualified, edge.source)
    return out


def _held_for_others(branch: PartBranch, start: Analysis) -> Mapping[Qualified, FrName]:
    """Each name in the part's own files that is another part's, such as a structure written in the part's module,
    with the part that owns it."""
    if start.code is None or start.tree is None:
        return {}
    files = {path for path in branch.touched
             if (whose := start.dp_of_file(path)) is not None and is_within(whose, branch.part)}
    owners = {name: start.tree.owner(name) for name, symbol in start.code.symbols.items() if symbol.span.path in files}
    return {name: owner for name, owner in owners.items() if owner is not None and not is_within(owner, branch.part)}


def _moved(branch: PartBranch, start: Analysis, now: Analysis) -> Iterable[Finding]:
    if start.code is None or now.code is None:
        return
    settled = "what other parts are built against is settled before a part is built"
    said = {**{name: f"is used by {user}" for name, user in relied_on(start, branch.part).items()},
            **{name: f"is {owner}'s" for name, owner in _held_for_others(branch, start).items()}}
    for name, why in sorted(said.items()):
        was, is_now = start.code.symbols[name], now.code.symbols.get(name)
        if is_now is None:
            yield finding(Result.BREAKS, SETTLED_FIRST, Subject(name), was.span,
                          Say(f"{name} {why}, and the branch of {branch.part} removed it: {settled}"))
        elif Shape.of(is_now) != Shape.of(was):
            yield finding(Result.BREAKS, SETTLED_FIRST, Subject(name), is_now.span,
                          Say(f"{name} {why}, and the branch of {branch.part} changed its parameters, its fields or "
                              f"what it returns: {settled}"))


@deal.post(lambda found: found.result is Result.BREAKS and found.rule in PART_RULES)
def check_part(branch: PartBranch, start: Analysis, now: Analysis) -> Iterable[Finding]:
    """A break for each file a part's branch changed that is not the part's, and for each name other parts are built
    against that it changed. `start` is the project where the branch left the line it lands on."""
    yield from _outside(branch, start, now)
    yield from _moved(branch, start, now)

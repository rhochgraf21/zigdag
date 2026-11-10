"""Starting from existing code (DESIGN2 §7.9): a record of what is there, so the first check holds and anything
new breaks. Every known break goes under `except`, as visible debt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import deal

from zigdag.core.checks.run import ProjectFiles, analyse
from zigdag.core.kinds.registry import BUILT_IN_KINDS
from zigdag.core.record.builtins import BUILT_INS, UNRELATED_BREAKAGE
from zigdag.core.record.fmt import format_text
from zigdag.core.record.model import Domain
from zigdag.core.record.read import domain_file
from zigdag.core.relate import Where, classify
from zigdag.core.settings import DEFAULT_REPORT, DEFAULT_TEST_ROOTS, RULESET, SETTINGS_FILE, SOURCE_KEY, read_settings
from zigdag.core.code import CodeModel
from zigdag.core.findings import RecordPath, Result
from zigdag.core.names import PYTHON, CheckKindName, FrName, RuleId, fr_name, parent, subject
from zigdag.core.texts import FileText, Say

FUNCTIONAL = domain_file(Domain.FUNCTIONAL)
PROCESS = domain_file(Domain.PROCESS)
CUSTOMER = domain_file(Domain.CUSTOMER)
MAX_CHILDREN = BUILT_IN_KINDS[CheckKindName("max-children")].params["count"].default


def _toml_list(items: tuple[str, ...]) -> str:
    # A JSON string is a TOML basic string, with characters written as they are: TOML has no escape for half of
    # a character outside the basic plane, which is how JSON escapes one.
    return "[" + ", ".join(json.dumps(i, ensure_ascii=False) for i in items) + "]"


@deal.pre(lambda source_roots: all(r.isprintable() for r in source_roots))  # folder names, as found on disk
@deal.ensure(lambda source_roots, result: read_settings(result)[1] == ())  # what init writes reads back clean
def settings_text(source_roots: tuple[RecordPath, ...]) -> FileText:
    """A zigdag.toml for a project whose Python source is in the given folders."""
    return "\n".join([
        "[settings]",
        f"ruleset = {RULESET}",
        f"tests = {_toml_list(DEFAULT_TEST_ROOTS)}",
        f'test_command = "pytest --junitxml={DEFAULT_REPORT}"',
        "",
        "[adapters]",
        f'default = "{PYTHON}"',
        "",
        f"[adapters.{PYTHON}]",
        f"{SOURCE_KEY} = {_toml_list(source_roots)}",
        "",
    ])


def _frs(code: CodeModel) -> tuple[FrName | None, list[FrName]]:
    """The root and every FR below it: one per package and module whose name can be an FR name."""
    tops = sorted({u.split(".")[0] for u in code.units})
    if len(tops) != 1 or fr_name(tops[0]) is None:
        return None, []
    root = FrName(tops[0])
    names = [FrName(u) for u in sorted(code.units) if u != root and fr_name(u) is not None]
    return root, [n for n in names if parent(n) in (root, *names)]


def _slug(name: FrName) -> str:
    return name.rpartition(".")[2].replace("_", "-").strip("-") or "root"


def _effects_and_dependencies(files: ProjectFiles, code: CodeModel, first_level: list[FrName]):
    analysis = analyse(files, code)
    tree, relations = analysis.tree, analysis.relations
    effects: dict[FrName, set[str]] = {n: set() for n in first_level}
    depends: dict[FrName, set[str]] = {n: set() for n in first_level}
    for place, found in relations.effects.items():
        dp = relations.dp_of(place)
        top = next((n for n in first_level if dp and tree.within(dp, n)), None)
        if top:
            effects[top] |= set(found)
    for d in code.dependencies:
        source = relations.dp_of(d.source)
        top = next((n for n in first_level if source and tree.within(source, n)), None)
        if top is None:
            continue
        target = classify(code, tree, d.target)
        if target.where is Where.PROJECT and target.owner and not tree.within(target.owner, top):
            other = next((n for n in first_level if tree.within(target.owner, n)), None)
            if other:
                depends[top].add(other)
        elif target.where in (Where.THIRD_PARTY, Where.VENDORED):
            depends[top].add(target.top)
    return effects, depends


def _list(items) -> str:
    return "[" + ", ".join(sorted(items)) + "]"


def _functional(root: FrName, names: list[FrName], effects, depends, excepted: Mapping[RuleId, set[str]],
                spelled: frozenset[RuleId]) -> str:
    lines = ["frs:", f"  {root}: {{}}"]
    lines += [f"  {n}: {{}}" for n in names]
    lines.append("constraints:")
    for n in sorted(effects):
        lines += [f"  {_slug(n)}-effects:  # what {n} does today, recorded by zigdag init",
                  f"    on: {n}", f"    serves: [{UNRELATED_BREAKAGE}]", "    check: effects",
                  "    with:", f"      allow: {_list(effects[n])}"]
        lines += [f"  {_slug(n)}-dependencies:  # what {n} depends on today, recorded by zigdag init",
                  f"    on: {n}", f"    serves: [{UNRELATED_BREAKAGE}]", "    check: may-depend-on",
                  "    with:", f"      allow: {_list(depends[n])}"]
    lines += _tunings(Domain.FUNCTIONAL, excepted, indent=2, spelled=spelled, root=root if spelled else None)
    return "\n".join(lines) + "\n"


def _written(value: object) -> str:
    """A parameter's value as the record writes it: a whole number without a fraction."""
    return f"{value:g}" if isinstance(value, float) else str(value)


def _defaults(rule: RuleId) -> dict[str, object]:
    """The parameters a built-in rule has when the record says nothing, with the value of each."""
    return {name: spec.default for name, spec in BUILT_IN_KINDS[BUILT_INS[rule].kind].params.items()
            if spec.default is not None}


@deal.post(lambda result: all(not BUILT_INS[rule].always_on for rule in result))  # what cannot be tuned is not shown
def tunable() -> frozenset[RuleId]:
    """The built-in rules a project can tune: the ones a default setup writes out."""
    return frozenset(rule for rule, built_in in BUILT_INS.items() if not built_in.always_on)


def _tunings(domain: Domain, excepted: Mapping[RuleId, set[str]], indent: int,
             extra: Mapping[str, str] | None = None, spelled: frozenset[RuleId] = frozenset(),
             root: FrName | None = None) -> list[str]:
    """An entry for each built-in rule of the domain that has known breaks, a value of its own, or is spelled out.
    A rule that is spelled out is written with the values it has by default and the sentence it enforces, so a
    reader sees every rule in force without knowing zigdag, and tunes one by changing what is already there."""
    extra = extra or {}
    pad = " " * indent
    out = []
    for rule in sorted(set(excepted) | set(extra) | spelled):
        built_in = BUILT_INS.get(rule)
        if built_in is None or built_in.domain is not domain:
            continue
        values = [extra[rule]] if rule in extra else [
            f"{name}: {_written(value)}" for name, value in _defaults(rule).items()] if rule in spelled else []
        known = sorted(excepted.get(rule, ()))
        why = "known breaks when zigdag init ran: each is debt to pay down" if known or root is None else \
            BUILT_IN_KINDS[built_in.kind].sentence(subject(root), _defaults(rule), ())
        out.append(f"{pad}{rule}:{'' if values or known else ' {}'}  # {why}")
        if values:
            out += [f"{pad}  with:", *(f"{pad}    {value}" for value in values)]
        if known:
            out.append(f"{pad}  except:")
            out += [f"{pad}    - {code}" for code in known]
    return out


CUSTOMER_TEMPLATE = FileText("""\
# Who is this system for, and what are they trying to get done? Until this is written, zigdag lists it as a thing to do.
# One entry for each job, like this one:
#
# buy-products: {job: Buy a product online, performer: Shopper, outcomes: {lost-order: Minimize the likelihood that a placed order is lost}}
""")


@deal.ensure(lambda root, source_roots, result: {RecordPath(SETTINGS_FILE), FUNCTIONAL, PROCESS, CUSTOMER} == set(result))
def starter(root: FrName, source_roots: tuple[RecordPath, ...]) -> Mapping[RecordPath, FileText]:
    """A default setup for a project with no code yet: the settings, a root FR to write the function of, a place
    for the jobs, and every rule a project can tune, spelled out with its default values."""
    functional = "\n".join([
        "frs:", f"  {root}: {{}}", "constraints:", *_tunings(Domain.FUNCTIONAL, {}, 2, spelled=tunable(), root=root)])
    process = "\n".join(_tunings(Domain.PROCESS, {}, 0, spelled=tunable(), root=root))
    files = {FUNCTIONAL: functional + "\n", PROCESS: process + "\n", CUSTOMER: CUSTOMER_TEMPLATE}
    return {RecordPath(SETTINGS_FILE): settings_text(source_roots),
            **{path: format_text(path, text)[0] or text for path, text in files.items()}}


def _children_limit(root: FrName, names: list[FrName]) -> int:
    counts: dict[str, int] = {}
    for n in names:
        counts[parent(n)] = counts.get(parent(n), 0) + 1
    return max(counts.values(), default=0)


@deal.ensure(lambda files, code, spelled=frozenset(), *, result: bool(result[0]) or bool(result[1]))  # files, or why there are none
@deal.ensure(lambda files, code, spelled=frozenset(), *, result: not result[0] or FUNCTIONAL in result[0])
def init(files: ProjectFiles, code: CodeModel,
         spelled: frozenset[RuleId] = frozenset()) -> tuple[Mapping[RecordPath, FileText], list[Say]]:
    """The design files for the code as it is, and what could not be recorded. The rules in `spelled` are written
    out with their default values even where the code gives no reason to tune them."""
    root, names = _frs(code)
    if root is None:
        return {}, ["the code has no single top-level package to make the root FR"]
    first_level = [n for n in names if parent(n) == root]
    limit = _children_limit(root, names)
    extra_process = {"max-children": f"count: {limit}"} if limit > MAX_CHILDREN else {}

    def files_for(excepted: Mapping[RuleId, set[str]], effects, depends) -> dict[RecordPath, str]:
        functional = _functional(root, names, effects, depends, excepted, spelled)
        process = "\n".join(_tunings(Domain.PROCESS, excepted, 0, extra_process, spelled,
                                     root if spelled else None))
        out = {FUNCTIONAL: functional}
        if process:
            out[PROCESS] = process + "\n"
        return {path: format_text(path, text)[0] or text for path, text in out.items()}

    empty = {n: set() for n in first_level}
    draft = files_for({}, empty, empty)
    effects, depends = _effects_and_dependencies(ProjectFiles(files.settings, draft, None), code, first_level)
    first = files_for({}, effects, depends)
    report = analyse(ProjectFiles(files.settings, first, None), code).report
    excepted: dict[RuleId, set[str]] = {}
    left: list[str] = []
    for f in report.of_result(Result.BREAKS):
        if f.rule in BUILT_INS and "." in f.about and "#" not in f.about:
            excepted.setdefault(RuleId(f.rule), set()).add(f.about)
        else:
            left.append(f"{f.rule}: {f.say}")
    return files_for(excepted, effects, depends), sorted(set(left))

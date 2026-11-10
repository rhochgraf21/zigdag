"""Custom checks (DESIGN2 §4.2): a project's own rules, each a plain function in design/checks/.

Nothing is registered. A function's name is its check kind, the first line of its docstring is its description, and
its keyword arguments are its settings, so what a check is is written once, where the check is.
"""

from __future__ import annotations

import inspect
import types
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import NewType

import deal

from zigdag.core.checks.context import Context
from zigdag.core.checks.rules import RuleUse
from zigdag.core.findings import Finding, RecordPath, Result, RuleName, Span, Subject, finding
from zigdag.core.kinds.params import ParamSpec, ParamType
from zigdag.core.kinds.registry import BUILT_IN_KINDS
from zigdag.core.names import CheckKindName, Identifier, ParamName
from zigdag.core.record.read import DESIGN_DIR
from zigdag.core.measures import Column, Line
from zigdag.core.settings import CheckFunction, CustomCheck
from zigdag.core.texts import Say

CHECKS_DIR = f"{DESIGN_DIR}/checks"
CUSTOM_CHECKS = RuleName("custom-checks")  # the rule that reports what is wrong with a file of custom checks
ModuleName = NewType("ModuleName", str)  # the name a file of custom checks runs under
Names = NewType("Names", dict)  # what a Python file defines once it has run, by name: the namespace of a module
CompiledCode = NewType("CompiledCode", types.CodeType)  # a Python file, compiled and not yet run
Raised = NewType("Raised", Exception)  # what a file of custom checks raised when it was run
MODULE_NAME_KEY = "__name__"  # where Python keeps the name a module runs under
_FIRST = Line(1)
_START = Column(1)
_MODULE_PREFIX = "zigdag_custom_checks."
_PRIVATE = "_"
_GIVEN = 2  # what zigdag hands every check, before its own settings: what it reads, and the rule in force
# A setting's type is the type of its default. The record writes every value as text, and has no yes-or-no type: a
# setting with two values is a word, as edge-types' are (allowed, forbidden).
_SETTING_TYPES: Mapping[type, ParamType] = {int: ParamType.COUNT, float: ParamType.RATIO, str: ParamType.TEXT}


@dataclass(frozen=True)
class Loaded:
    """What running one file of custom checks gave: the checks it defines, or why it could not be run."""

    path: RecordPath
    functions: Mapping[Identifier, CheckFunction]
    error: Say | None = None


@dataclass(frozen=True)
class Loading:
    """One file of custom checks, ready to run: its code as Python compiled it, and the names it starts with."""

    path: RecordPath
    code: CompiledCode
    names: Names


@dataclass(frozen=True)
class CustomChecks:
    """The project's own checks, by the kind each is, and what is wrong with the files that should define them."""

    checks: Mapping[CheckKindName, CustomCheck]
    problems: tuple[Finding, ...] = ()


NO_CUSTOM_CHECKS = CustomChecks({})


@deal.post(lambda result: result.startswith(_MODULE_PREFIX))
def module_name(path: RecordPath) -> ModuleName:
    """The name a file of custom checks runs under, which tells its own functions from the ones it imports."""
    return ModuleName(_MODULE_PREFIX + path.rpartition("/")[2].removesuffix(".py"))


@deal.ensure(lambda path, result: result == {MODULE_NAME_KEY: module_name(path)})
def fresh_names(path: RecordPath) -> Names:
    """What a file of custom checks starts with when it is run: only the name it runs under."""
    return Names({MODULE_NAME_KEY: module_name(path)})


@deal.ensure(lambda path, names, result: result.error is None and set(result.functions) <= set(names))
def defined(path: RecordPath, names: Names) -> Loaded:
    """The checks a file defines, from what it left behind when it ran: every public function that is its own, and
    not one it imported."""
    module = module_name(path)
    return Loaded(path, {Identifier(name): value for name, value in names.items()
                         if isinstance(value, types.FunctionType) and value.__module__ == module
                         and not name.startswith(_PRIVATE)})


@deal.ensure(lambda path, error, result: result.error is not None and not result.functions)
def unloaded(path: RecordPath, error: Raised) -> Loaded:
    return Loaded(path, {}, Say(f"{type(error).__name__}: {error}"))


def _record_name(name: str) -> str:
    """A Python name as the record writes it: the record's names use hyphens."""
    return name.replace("_", "-")


def _problem(path: RecordPath, line: Line, say: Say) -> Finding:
    return finding(Result.BREAKS, CUSTOM_CHECKS, Subject(path), Span(path, line, _START), say)


def _line(function: CheckFunction) -> Line:
    """Where a check is written; the top of its file for something callable that is not a plain function."""
    return Line(function.__code__.co_firstlineno) if isinstance(function, types.FunctionType) else _FIRST


def _described(path: RecordPath, name: Identifier, function: CheckFunction) -> CustomCheck | Finding:
    line = _line(function)
    parameters = inspect.signature(function).parameters.values()
    given = [p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    settings = [p for p in parameters if p.kind is p.KEYWORD_ONLY]
    if len(given) != _GIVEN or len(given) + len(settings) != len(parameters):
        return _problem(path, line, Say(f"{name} must take what it reads and the rule, then its settings by keyword: "
                                        f"def {name}(context, rule, *, limit=10)"))
    params: dict[ParamName, ParamSpec] = {}
    for setting in settings:
        kind = _SETTING_TYPES.get(type(setting.default))
        if kind is None:
            return _problem(path, line, Say(f"{name}: the setting {setting.name} needs a default that is a whole "
                                            f"number, a number or text: its value when a rule does not set it"))
        params[ParamName(_record_name(setting.name))] = ParamSpec(kind, setting.default)
    description = Say((inspect.getdoc(function) or "").partition("\n")[0])
    return CustomCheck(description, params, function, path)


@deal.ensure(lambda loaded, refused, result: not set(result.checks) & set(BUILT_IN_KINDS))  # a built-in keeps its name
@deal.ensure(lambda loaded, refused, result: set(refused) <= set(result.problems))
def read_checks(loaded: Iterable[Loaded], refused: Iterable[Finding] = ()) -> CustomChecks:
    """The checks that the loaded files define: every public function a file defines itself."""
    checks: dict[CheckKindName, CustomCheck] = {}
    problems: list[Finding] = [*refused]
    for file in sorted(loaded, key=lambda f: f.path):
        if file.error is not None:
            problems.append(_problem(file.path, _FIRST, Say(f"{file.path} could not be loaded: {file.error}")))
            continue
        for name, value in sorted(file.functions.items()):
            kind = CheckKindName(_record_name(name))
            described = _described(file.path, name, value)
            if isinstance(described, Finding):
                problems.append(described)
            elif kind in BUILT_IN_KINDS or kind in checks:
                problems.append(_problem(file.path, _line(value),
                                         Say(f"{kind} is already a check kind: give {name} another name")))
            else:
                checks[kind] = described
    return CustomChecks(checks, tuple(problems))


@deal.ensure(lambda ctx, rule, check, result: all(isinstance(f, Finding) for f in result))
def run_custom(ctx: Context, rule: RuleUse, check: CustomCheck) -> list[Finding]:
    """What a custom check finds for one rule. A check that fails to run, or hands back something that is no
    finding, breaks: it is never skipped (DESIGN2 §1, principle 6)."""
    settings = {name.replace("-", "_"): value for name, value in rule.params.items()}
    try:
        found = list(check.run(ctx, rule, **settings))
    except Exception as e:  # noqa: BLE001 (whatever the project's own check raises, the run reports it and goes on)
        return [finding(Result.BREAKS, RuleName(rule.name), Subject(rule.on), rule.span, Say(
            f"the {rule.kind} check failed to run ({type(e).__name__}: {e}): fix it in {check.source}"))]
    if not all(isinstance(f, Finding) for f in found):
        return [finding(Result.BREAKS, RuleName(rule.name), Subject(rule.on), rule.span, Say(
            f"the {rule.kind} check in {check.source} gave back something that is not a finding: make each one "
            f"with broken(...) or asked(...) from zigdag.checks"))]
    return found

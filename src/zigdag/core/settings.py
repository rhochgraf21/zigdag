"""zigdag.toml (DESIGN2 §7.8): how zigdag runs here, and what it has been taught."""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

import deal

from zigdag.core.kinds.params import ParamSpec
from zigdag.core.effects import Effect
from zigdag.core.findings import Finding, RecordPath, Result, Span, finding
from zigdag.core.language.lexicons import LexiconName
from zigdag.core.names import ADAPTERS, AdapterName, CheckKindName
from zigdag.core.log import Actor
from zigdag.core.measures import Version
from zigdag.core.names import Api, Glob, Key, ParamName, ShellCommand
from zigdag.core.texts import FileText, Say, Word

SETTINGS_FILE = RecordPath("zigdag.toml")
SETTINGS_RULE = "settings"
RULESET = 1  # the rule set this version of zigdag implements


@dataclass(frozen=True)
class CustomEffect:
    description: str
    calls: tuple[str, ...]


# A check as its author wrote it: (what every check reads, the rule in force, then its own settings by keyword).
CheckFunction = Callable[..., Iterable[Finding]]


@dataclass(frozen=True)
class CustomCheck:
    """A check the project wrote (DESIGN2 §4.2): one function in design/checks/, as it was loaded."""

    description: Say  # the first line of the function's docstring
    params: Mapping[ParamName, ParamSpec]  # its settings: the function's keyword arguments, as the record names them
    run: CheckFunction
    source: RecordPath  # the file that defines it


@dataclass(frozen=True)
class Settings:
    ruleset: Version | None = None
    tests: tuple[RecordPath, ...] = ()
    test_command: ShellCommand | None = None
    test_reports: tuple[Glob, ...] = ()
    vendor: tuple[RecordPath, ...] = ()
    editor: ShellCommand | None = None
    people: tuple[Actor, ...] = ()  # who counts as a person for person-approves-design; everyone else is an agent
    default_adapter: AdapterName | None = None
    adapters: Mapping[AdapterName, Mapping[Key, object]] = field(default_factory=dict)
    lexicon: Mapping[LexiconName, tuple[tuple[Word, ...], tuple[Word, ...]]] = field(default_factory=dict)
    effects: Mapping[Effect, CustomEffect] = field(default_factory=dict)
    checks: Mapping[CheckKindName, CustomCheck] = field(default_factory=dict)

    @deal.ensure(lambda self, checks, result: result.checks == checks and replace(result, checks=self.checks) == self)
    def taught(self, checks: Mapping[CheckKindName, CustomCheck]) -> Settings:
        """These settings with the project's own checks. They are functions in design/checks/, not text in
        zigdag.toml, so they are loaded apart from it and joined here: the settings hold everything a project has
        taught zigdag."""
        return replace(self, checks=checks)

    @property
    @deal.ensure(lambda self, result: all(effect in self.effects for effect in result.values()))
    @deal.ensure(lambda self, result: all(call in result for e in self.effects.values() for call in e.calls))
    def custom_effect_calls(self) -> Mapping[Api, Effect]:
        """Each call that performs a custom effect, and the effect it performs."""
        return {call: name for name, effect in self.effects.items() for call in effect.calls}

    @property
    @deal.ensure(lambda self, result: bool(result) and (not self.tests or result == self.tests))
    def test_roots(self) -> tuple[RecordPath, ...]:
        """Where the tests are: as set, or the conventional folder."""
        return self.tests or DEFAULT_TEST_ROOTS

    @property
    @deal.ensure(lambda self, result: bool(result) and (not self.test_reports or result == self.test_reports))
    def report_patterns(self) -> tuple[Glob, ...]:
        """Where test reports are: as set, or zigdag's own folder."""
        return self.test_reports or DEFAULT_REPORTS

    @deal.ensure(lambda self, adapter, key, result: result is None or self.adapters[adapter][key] == result)
    def command(self, adapter: AdapterName, key: Key) -> ShellCommand | None:
        """A command an adapter's section gives, such as how to start a tool; None when it gives no text."""
        configured = self.adapters.get(adapter, {}).get(key)
        return ShellCommand(configured) if isinstance(configured, str) and configured.strip() else None

    @deal.ensure(lambda self, adapter, result: result is None or (adapter in self.adapters and not any(
        r.endswith("/") for r in result)))
    def source_roots(self, adapter: AdapterName) -> tuple[RecordPath, ...] | None:
        """The folders an adapter reads source from, as set; None when they are not set."""
        configured = self.adapters.get(adapter, {}).get(SOURCE_KEY)
        if not isinstance(configured, list) or not all(isinstance(r, str) for r in configured):
            return None
        return tuple(PROJECT_ROOT if r == CURRENT_FOLDER else r.rstrip("/") for r in configured)


WORK_DIR = ".zigdag"  # zigdag's own folder in a project: cached results, test reports, critique requests
DEFAULT_TEST_ROOTS = ("tests",)
DEFAULT_REPORTS = (f"{WORK_DIR}/*.xml",)
DEFAULT_REPORT = f"{WORK_DIR}/pytest.xml"  # where zigdag test has pytest write its JUnit report
PLAN_FILE = RecordPath(f"{WORK_DIR}/watch.json")  # what zigdag test hands a test watcher
OBSERVED_FILE = RecordPath(f"{WORK_DIR}/observed.json")  # what the watcher saw
PROFILE_FILE = RecordPath(f"{WORK_DIR}/profile.json")  # where zigdag profile keeps the latest profile
PROFILE_BEFORE = RecordPath(f"{WORK_DIR}/profile.before.json")  # and the one before it, to compare with
CARRIED_FILE = RecordPath(f"{WORK_DIR}/mutants.json")  # the mutants judged so far, kept while the watcher works
DEFAULT_TEST_COMMAND = "pytest"
SOURCE_KEY = "source"  # the key in an [adapters.<name>] table that lists source folders
PROJECT_ROOT = ""  # a source root that is the project itself
CURRENT_FOLDER = "."  # how zigdag.toml writes the project itself as a folder

_SECTIONS = {"settings", "adapters", "lexicon", "effects"}
_MOVED = {"checks": "a custom check is a function in design/checks/ now, and is not registered here"}
_SETTINGS_KEYS = {"ruleset", "tests", "test_command", "test_reports", "vendor", "editor", "people"}


def _texts(value: object) -> tuple[str, ...] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    return None


@deal.ensure(lambda text, result: text is not None or result[0] == Settings())  # no file: every default
@deal.ensure(lambda text, result: all(p.rule == SETTINGS_RULE for p in result[1]))
def read_settings(text: FileText | None) -> tuple[Settings, tuple[Finding, ...]]:
    """The settings, or the defaults with what is wrong. A missing file means every default."""
    if text is None:
        return Settings(), (_problem(Result.TODO, "no zigdag.toml: add one with [settings] ruleset = 1"),)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return Settings(), (_problem(Result.BREAKS, f"cannot be read: {e}"),)
    problems: list[Finding] = []
    for name in sorted(set(raw) - _SECTIONS):
        problems.append(_problem(Result.BREAKS, f"unknown section [{name}]" + (f": {_MOVED[name]}" if name in _MOVED else "")))

    section = _table(raw, "settings", problems)
    for name in sorted(set(section) - _SETTINGS_KEYS):
        problems.append(_problem(Result.BREAKS, f"unknown setting settings.{name}"))
    ruleset = section.get("ruleset")
    if ruleset is None:
        problems.append(_problem(Result.TODO, f"pin the rule set: [settings] ruleset = {RULESET}"))
    elif not isinstance(ruleset, int) or isinstance(ruleset, bool) or ruleset != RULESET:
        problems.append(_problem(Result.BREAKS, f"this zigdag implements rule set {RULESET}, not {ruleset!r}"))
        ruleset = None

    def texts(key: str) -> tuple[str, ...]:
        if key not in section:
            return ()
        value = _texts(section[key])
        if value is None:
            problems.append(_problem(Result.BREAKS, f"settings.{key} must be a list of text"))
        return value or ()

    def text_or_none(key: str) -> str | None:
        value = section.get(key)
        if value is not None and not isinstance(value, str):
            problems.append(_problem(Result.BREAKS, f"settings.{key} must be text"))
            return None
        return value

    adapters_raw = _table(raw, "adapters", problems)
    default = adapters_raw.get("default")
    if default is not None and AdapterName(str(default)) not in ADAPTERS:
        problems.append(_problem(Result.BREAKS, f"unknown adapter {default!r}; known: {', '.join(sorted(ADAPTERS))}"))
        default = None
    adapters: dict[AdapterName, Mapping[str, object]] = {}
    for name, value in adapters_raw.items():
        if name == "default":
            continue
        if AdapterName(name) not in ADAPTERS or not isinstance(value, dict):
            problems.append(_problem(Result.BREAKS, f"unknown adapter section [adapters.{name}]"))
            continue
        adapters[AdapterName(name)] = value

    settings = Settings(
        ruleset=ruleset,
        tests=texts("tests"),
        test_command=text_or_none("test_command"),
        test_reports=texts("test_reports"),
        vendor=texts("vendor"),
        editor=text_or_none("editor"),
        people=texts("people"),
        default_adapter=AdapterName(default) if default else None,
        adapters=adapters,
        lexicon=_lexicon(_table(raw, "lexicon", problems), problems),
        effects=_effects(_table(raw, "effects", problems), problems),
    )
    return settings, tuple(problems)


def _problem(result: Result, say: str) -> Finding:
    return finding(result, SETTINGS_RULE, SETTINGS_FILE, Span(SETTINGS_FILE, 1, 1), say)


def _table(raw: Mapping[str, object], name: str, problems: list[Finding]) -> Mapping[str, object]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        problems.append(_problem(Result.BREAKS, f"[{name}] must be a table"))
        return {}
    return value


def _lexicon(raw: Mapping[str, object], problems: list[Finding]):
    out = {}
    for name, value in raw.items():
        try:
            lexicon = LexiconName(name)
        except ValueError:
            known = ", ".join(n.value for n in LexiconName)
            problems.append(_problem(Result.BREAKS, f"unknown lexicon {name!r}; known: {known}"))
            continue
        if not isinstance(value, dict) or set(value) - {"add", "remove"}:
            problems.append(_problem(Result.BREAKS, f"[lexicon.{name}] takes only add and remove"))
            continue
        add, remove = _texts(value.get("add", [])), _texts(value.get("remove", []))
        if add is None or remove is None:
            problems.append(_problem(Result.BREAKS, f"[lexicon.{name}] add and remove are lists of text"))
            continue
        out[lexicon] = (add, remove)
    return out


def _effects(raw: Mapping[str, object], problems: list[Finding]) -> Mapping[Effect, CustomEffect]:
    out = {}
    for name, value in raw.items():
        calls = _texts(value.get("calls")) if isinstance(value, dict) else None
        description = value.get("description") if isinstance(value, dict) else None
        if not isinstance(description, str) or not calls:
            problems.append(_problem(Result.BREAKS, f'effect "{name}" needs a description and a list of calls'))
            continue
        out[Effect(name)] = CustomEffect(description, calls)
    return out

"""zigdag.toml (DESIGN2 §7.8): how zigdag runs here, and what it has been taught."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field

from zigdag.core.kinds.params import ParamSpec, ParamType
from zigdag.core.kinds.registry import Exactness, Part
from zigdag.core.effects import Effect
from zigdag.core.findings import Finding, RecordPath, Result, Span, finding
from zigdag.core.language.lexicons import LexiconName
from zigdag.core.names import ADAPTERS, AdapterName, CheckKindName

SETTINGS_FILE = RecordPath("zigdag.toml")
SETTINGS_RULE = "settings"
RULESET = 1  # the rule set this version of zigdag implements


@dataclass(frozen=True)
class CustomEffect:
    description: str
    calls: tuple[str, ...]


@dataclass(frozen=True)
class CustomCheck:
    description: str
    code: str
    params: Mapping[str, ParamSpec]
    reads: frozenset[Part]
    exactness: Exactness


@dataclass(frozen=True)
class Settings:
    ruleset: int | None = None
    tests: tuple[str, ...] = ()
    test_command: str | None = None
    test_reports: tuple[str, ...] = ()
    vendor: tuple[str, ...] = ()
    editor: str | None = None
    people: tuple[str, ...] = ()  # who counts as a person for person-approves-design; everyone else is an agent
    default_adapter: AdapterName | None = None
    adapters: Mapping[AdapterName, Mapping[str, object]] = field(default_factory=dict)
    lexicon: Mapping[LexiconName, tuple[tuple[str, ...], tuple[str, ...]]] = field(default_factory=dict)
    effects: Mapping[Effect, CustomEffect] = field(default_factory=dict)
    checks: Mapping[CheckKindName, CustomCheck] = field(default_factory=dict)

    @property
    def custom_effect_calls(self) -> Mapping[str, Effect]:
        """Each call that performs a custom effect, and the effect it performs."""
        return {call: name for name, effect in self.effects.items() for call in effect.calls}

    @property
    def test_roots(self) -> tuple[str, ...]:
        """Where the tests are: as set, or the conventional folder."""
        return self.tests or DEFAULT_TEST_ROOTS

    @property
    def report_patterns(self) -> tuple[str, ...]:
        """Where test reports are: as set, or zigdag's own folder."""
        return self.test_reports or DEFAULT_REPORTS

    def source_roots(self, adapter: AdapterName) -> tuple[str, ...] | None:
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
DEFAULT_TEST_COMMAND = "pytest"
SOURCE_KEY = "source"  # the key in an [adapters.<name>] table that lists source folders
PROJECT_ROOT = ""  # a source root that is the project itself
CURRENT_FOLDER = "."  # how zigdag.toml writes the project itself as a folder

_SECTIONS = {"settings", "adapters", "lexicon", "effects", "checks"}
_SETTINGS_KEYS = {"ruleset", "tests", "test_command", "test_reports", "vendor", "editor", "people"}


def _texts(value: object) -> tuple[str, ...] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    return None


def read_settings(text: str | None) -> tuple[Settings, tuple[Finding, ...]]:
    """The settings, or the defaults with what is wrong. A missing file means every default."""
    if text is None:
        return Settings(), (_problem(Result.TODO, "no zigdag.toml: add one with [settings] ruleset = 1"),)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return Settings(), (_problem(Result.BREAKS, f"cannot be read: {e}"),)
    problems: list[Finding] = []
    for name in sorted(set(raw) - _SECTIONS):
        problems.append(_problem(Result.BREAKS, f"unknown section [{name}]"))

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
        checks=_checks(_table(raw, "checks", problems), problems),
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


def _checks(raw: Mapping[str, object], problems: list[Finding]) -> Mapping[CheckKindName, CustomCheck]:
    out = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            problems.append(_problem(Result.BREAKS, f"[checks.{name}] must be a table"))
            continue
        description, code = value.get("description"), value.get("code")
        if not isinstance(description, str) or not isinstance(code, str) or ":" not in code:
            problems.append(_problem(Result.BREAKS, f'check "{name}" needs a description and code = "path.py:function"'))
            continue
        params: dict[str, ParamSpec] = {}
        for param, kind in (value.get("params") or {}).items():
            try:
                params[param] = ParamSpec(ParamType(kind))
            except ValueError:
                problems.append(_problem(Result.BREAKS, f'check "{name}": parameter {param} has unknown type {kind!r}'))
        reads = set()
        for part in _texts(value.get("reads", [])) or ():
            try:
                reads.add(Part(part))
            except ValueError:
                problems.append(_problem(Result.BREAKS, f'check "{name}": cannot read {part!r}'))
        exact = value.get("exact", True)
        out[CheckKindName(name)] = CustomCheck(
            description, code, params, frozenset(reads), Exactness.EXACT if exact is True else Exactness.GUESS
        )
    return out

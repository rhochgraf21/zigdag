"""Running every check on a project: settings, the record and its own rules, the code, the evidence, the log."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.core.checks.code_rules import check_code
from zigdag.core.checks.context import Context, declared_pure
from zigdag.core.checks.custom import NO_CUSTOM_CHECKS, CustomChecks
from zigdag.core.checks.data_rules import check_clauses
from zigdag.core.checks.evidence import check_evidence
from zigdag.core.checks.gates import check_gates
from zigdag.core.checks.record_rules import check_record, registry
from zigdag.core.checks.rules import RuleUse, rules_in_force
from zigdag.core.code import CodeModel, Qualified
from zigdag.core.data import DataModel, work_out
from zigdag.core.findings import Finding, RecordPath, Report, Result, Span, finding
from zigdag.core.kinds.registry import Part
from zigdag.core.language.lexicons import Lexicons
from zigdag.core.log import Log, read_log, without_answered
from zigdag.core.record.builtins import BUILT_INS
from zigdag.core.record.fmt import content, format_text
from zigdag.core.names import FrName, is_within, named_fr, subject
from zigdag.core.record.entries import Entry, entries
from zigdag.core.record.model import Record
from zigdag.core.record.read import read_record
from zigdag.core.relate import Relations, relate
from zigdag.core.resolve import Tree, resolve
from zigdag.core.settings import Settings, read_settings
from zigdag.core.findings import Subject
from zigdag.core.log import Actor
from zigdag.core.names import RuleId
from zigdag.core.texts import FileText, SentenceText, Written

FMT = "fmt"
EXCEPT = "except"


@dataclass(frozen=True)
class ProjectFiles:
    """The project's text, as the shell read it. None means the file is absent."""

    settings: FileText | None
    design: Mapping[RecordPath, FileText]
    log: FileText | None = None


@dataclass(frozen=True)
class Analysis:
    """Everything one run of zigdag worked out about a project."""

    record: Record
    settings: Settings
    log: Log
    report: Report  # answered questions already removed
    code: CodeModel | None = None
    tree: Tree | None = None
    relations: Relations | None = None
    data: DataModel | None = None
    rules: tuple[RuleUse, ...] = ()

    @property
    @deal.ensure(lambda self, result: result == entries(self.record))
    def entries(self) -> Mapping[Subject, Entry]:
        return entries(self.record)

    @property
    @deal.ensure(lambda self, result: (result is None) == any(
        x is None for x in (self.code, self.tree, self.relations, self.data)))
    @deal.ensure(lambda self, result: result is None or (result.model is self.code and result.record is self.record))
    def context(self) -> Context | None:
        """What the checks of the code saw; None when the code was not read."""
        if self.code is None or self.tree is None or self.relations is None or self.data is None:
            return None
        return Context(self.record, self.settings, self.code, self.tree, self.relations, self.data,
                       self.log.answered_questions, declared_pure(self.code, self.tree, self.rules))

    @property
    @deal.ensure(lambda self, result: result == self.settings.people)
    def people(self) -> tuple[Actor, ...]:
        return self.settings.people

    @property
    @deal.ensure(lambda self, result: set(result) <= {r.name for r in self.rules})
    @deal.ensure(lambda self, result: all(s.endswith(".") for s in result.values()))  # each one sentence
    def sentences(self) -> Mapping[RuleId, SentenceText]:
        """Each rule in force, as the EARS sentence zigdag renders for it."""
        kinds = registry(self.settings)
        return {r.name: kinds[r.kind].sentence(subject(r.on), r.params, tuple(str(e.code) for e in r.excepted))
                for r in self.rules if r.kind in kinds}

    @property
    @deal.ensure(lambda self, result: result <= {r.name for r in self.rules})
    def unchecked(self) -> frozenset[RuleId]:
        """The rules in force that this run could not check, since no adapter supplied what they read: on a revision
        read from git, for one, the rules that need a tool run on the code."""
        if self.code is None:
            return frozenset()
        kinds = registry(self.settings)
        return frozenset(r.name for r in self.rules if r.kind in kinds and kinds[r.kind].reads - self.code.supplied)

    @deal.ensure(lambda self, target, result: result is None or result in self.record.frs)
    def dp_of(self, target: Written) -> FrName | None:
        """The DP an FR name, a unit's name or a source file names."""
        if target in self.record.frs:
            return FrName(target)
        if self.code is None or self.tree is None:
            return None
        unit = self.code.unit_at(target)
        return self.tree.owner(unit.path if unit is not None else target)

    @deal.ensure(lambda self, path, result: result is None or result in self.record.frs)
    def dp_of_file(self, path: RecordPath) -> FrName | None:
        unit = self.code.unit_at(path) if self.code is not None else None
        return self.tree.owner(unit.path) if unit is not None and self.tree is not None else None

    @deal.ensure(lambda self, f, result: result is None or result in self.record.frs)
    def dp_of_finding(self, f: Finding) -> FrName | None:
        """The DP a finding is about: an FR, a statement's FR, or the owner of the code it names."""
        name = named_fr(f.about)
        if name in self.record.frs:
            return FrName(name)
        return self.tree.owner(Qualified(name)) if self.tree is not None else None

    @deal.ensure(lambda self, f, dp, result: not result or is_within(self.dp_of_finding(f), dp))
    def is_under(self, f: Finding, dp: FrName) -> bool:
        about = self.dp_of_finding(f)
        return about is not None and is_within(about, dp)

    @deal.ensure(lambda self, dp, result: all(f in self.report.findings and self.is_under(f, dp) for f in result))
    def under(self, dp: FrName) -> list[Finding]:
        """The findings about a DP or anything below it."""
        return [f for f in self.report.findings if self.is_under(f, dp)]

    @property
    @deal.ensure(lambda self, result: set(self.record.frs) <= result and set(BUILT_INS) <= result)
    def known_names(self) -> frozenset[Subject]:
        """Every name a log event can be about: FRs, statements, jobs, outcomes, rules and entries."""
        record = self.record
        return frozenset({
            *record.frs,
            *(str(s.ref) for fr in record.frs.values() for s in fr.statements),
            *(j.name for j in record.jobs),
            *(str(o) for o in record.outcomes),
            *record.constraints, *record.process, *BUILT_INS, *self.entries,
        })


def fmt_integrity(design: Mapping[RecordPath, str]) -> list[Finding]:
    """Record integrity (§4.4): formatting each file keeps what it says, and a second run changes nothing."""
    out = []
    for path, text in sorted(design.items()):
        once, _ = format_text(path, text)
        if once is None:
            continue  # the file cannot be read; that is reported where it is read
        twice, _ = format_text(path, once)
        at = Span(path, 1, 1)
        if content(path, once) != content(path, text):
            out.append(finding(Result.BREAKS, FMT, path, at,
                               "formatting this file would change its values or comments: this is a zigdag bug"))
        if twice != once:
            out.append(finding(Result.BREAKS, FMT, path, at,
                               "formatting this file twice gives different text: this is a zigdag bug"))
    return out


def _unresolved_excepts(rules: list[RuleUse], code: CodeModel, tree: Tree, settings: Settings) -> list[Finding]:
    out = []
    for rule in rules:
        for e in rule.excepted:
            if e.code.adapter_or(settings.default_adapter) not in code.adapters:
                continue  # code no adapter read: it cannot be resolved, and is not reported as unresolved
            single = RuleUse(rule.name, rule.kind, rule.params, rule.on, (e,), rule.span)
            if not any(single.skips(tree, name) for name in (*code.units, *code.symbols)):
                out.append(finding(Result.BREAKS, EXCEPT, rule.name, e.span,
                                   f'"{e.code}" under except names no code', str(e.code)))
    return out


@deal.ensure(lambda files, code=None, custom=NO_CUSTOM_CHECKS, *, result: (result.context is None) == (code is None))
@deal.ensure(lambda files, code=None, custom=NO_CUSTOM_CHECKS, *, result:
             result.report == without_answered(result.report, result.log))
@deal.ensure(lambda files, code=None, custom=NO_CUSTOM_CHECKS, *, result: result.settings.checks == custom.checks)
def analyse(files: ProjectFiles, code: CodeModel | None = None, custom: CustomChecks = NO_CUSTOM_CHECKS) -> Analysis:
    read, settings_problems = read_settings(files.settings)
    settings = read.taught(custom.checks)
    lexicons = Lexicons().tuned(settings.lexicon)
    record, record_problems = read_record(files.design)
    log, log_problems = read_log(files.log)
    supplied = code.supplied if code is not None else frozenset({Part.RECORD})
    found: list[Finding] = [*settings_problems, *custom.problems, *record_problems, *check_record(record, settings, lexicons, supplied),
                            *fmt_integrity(files.design), *log_problems]
    tree = relations = data = None
    rules: list[RuleUse] = []
    if code is not None:
        kinds = registry(settings)
        tree, resolve_problems = resolve(record, code, settings.default_adapter)
        relations = relate(code, tree, settings.custom_effect_calls)
        data = work_out(code, tree, relations)
        rules = rules_in_force(record, settings, kinds)
        supplied_kinds = frozenset(k for k, kind in kinds.items() if kind.reads <= supplied)
        found += [*code.problems, *resolve_problems, *_unresolved_excepts(rules, code, tree, settings),
                  *check_code(Context(record, settings, code, tree, relations, data, log.answered_questions,
                                      declared_pure(code, tree, rules)), rules, supplied_kinds),
                  *check_clauses(record, code, data, lexicons), *check_evidence(record, code, tree)]
    found += check_gates(record, log, settings.people, None, Report.of(found))
    report = without_answered(Report.of(found), log)
    return Analysis(record, settings, log, report, code, tree, relations, data, tuple(rules))


def check(files: ProjectFiles, code: CodeModel | None = None) -> Report:
    return analyse(files, code).report


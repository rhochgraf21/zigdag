"""Reading the four domain files (DESIGN2 §7.3 to §7.6) into a Record, with what is wrong with them.

Shape and name forms are checked here. Whether names resolve, and whether sentences fit their grammar, is
checked by the record rules, which see the whole record at once.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from zigdag.core.findings import Finding, RecordPath, Result, Span, finding
from zigdag.core.names import CheckKindName, CodeName, FrName, OutcomeRef, RuleId, StatementRef, fr_name, slug
from zigdag.core.record.builtins import BUILT_INS, MAINTAIN, MAINTAIN_JOB
from zigdag.core.record import tree as t
from zigdag.core.record.model import (
    At,
    Build,
    CheckUse,
    CodeRule,
    Constraint,
    Domain,
    EvidenceKind,
    Excepted,
    Fr,
    Gate,
    Job,
    Outcome,
    ParamValue,
    Placement,
    ProcessKind,
    ProcessVariable,
    Record,
    Sentence,
    Statement,
    Tuning,
    Validation,
    Verification,
    Workflow,
)

SCHEMA = "schema"
NAMES = "names"
DEFINED_ONCE = "defined-once"
DESIGN_FILES = "design-files"

DESIGN_DIR = "design"
DESIGN_SUFFIX = ".yaml"


def domain_file(domain: Domain) -> RecordPath:
    """The file a domain is written in, before it grows into a folder: design/functional.yaml."""
    return RecordPath(f"{DESIGN_DIR}/{domain.value}{DESIGN_SUFFIX}")


def domain_of(path: RecordPath) -> Domain | None:
    """design/<domain>.yaml, or any .yaml file in design/<domain>/."""
    parts = path.split("/")
    if len(parts) == 2 and parts[0] == DESIGN_DIR and parts[1].endswith(".yaml"):
        name = parts[1].removesuffix(".yaml")
    elif len(parts) == 3 and parts[0] == DESIGN_DIR and parts[2].endswith(".yaml"):
        name = parts[1]
    else:
        return None
    try:
        return Domain(name)
    except ValueError:
        return None


@dataclass
class _Reader:
    problems: list[Finding] = field(default_factory=list)

    def bad(self, rule: str, about: str, span: Span, say: str) -> None:
        self.problems.append(finding(Result.BREAKS, rule, about, span, say))

    def map(self, node: t.Node, what: str) -> t.Map | None:
        if isinstance(node, t.Map):
            return node
        self.bad(SCHEMA, what, node.span, f"{what} must be a mapping of names to entries")
        return None

    def keys(self, node: t.Map, what: str, allowed: Iterable[str], required: Iterable[str] = ()) -> None:
        allowed = set(allowed)
        for entry in node:
            if entry.key not in allowed:
                known = ", ".join(sorted(allowed))
                self.bad(SCHEMA, what, entry.key_span, f'{what} has no field "{entry.key}" (it takes: {known})')
        for key in required:
            if node.get(key) is None:
                self.bad(SCHEMA, what, node.span, f'{what} needs "{key}"')

    def text(self, node: t.Map, key: str, what: str) -> t.Text | None:
        entry = node.get(key)
        if entry is None:
            return None
        if isinstance(entry.value, t.Text) and entry.value.text.strip():
            return entry.value
        self.bad(SCHEMA, what, entry.key_span, f'{what}: "{key}" must be text')
        return None

    def texts(self, node: t.Map, key: str, what: str) -> tuple[t.Text, ...] | None:
        entry = node.get(key)
        if entry is None:
            return None
        if isinstance(entry.value, t.Seq) and all(isinstance(i, t.Text) and i.text.strip() for i in entry.value.items):
            return entry.value.items  # type: ignore[return-value]
        self.bad(SCHEMA, what, entry.key_span, f'{what}: "{key}" must be a list of text')
        return None

    def name(self, text: str, span: Span, parse: Callable[[str], object], form: str, what: str):
        value = parse(text)
        if value is None:
            self.bad(NAMES, what, span, f'"{text}" is not {form}')
        return value

    def fr(self, node: t.Text, what: str) -> At[FrName] | None:
        name = self.name(node.text, node.span, fr_name, "an FR name (lowercase identifiers joined by dots)", what)
        return At(name, node.span) if name else None

    def outcomes(self, node: t.Map, what: str) -> tuple[At[OutcomeRef], ...] | None:
        items = self.texts(node, "serves", what)
        if items is None:
            return None
        refs = (self.name(i.text, i.span, OutcomeRef.parse, "an outcome reference (job.outcome)", what) for i in items)
        return tuple(At(r, i.span) for r, i in zip(refs, items) if r)

    def params(self, node: t.Map, what: str) -> dict[str, At[ParamValue]]:
        entry = node.get("with")
        if entry is None:
            return {}
        if not isinstance(entry.value, t.Map):
            self.bad(SCHEMA, what, entry.key_span, f'{what}: "with" must be a mapping of parameters')
            return {}
        out: dict[str, At[ParamValue]] = {}
        for p in entry.value:
            if isinstance(p.value, t.Text):
                out[p.key] = At(p.value.text, p.key_span)
            elif isinstance(p.value, t.Seq) and all(isinstance(i, t.Text) for i in p.value.items):
                out[p.key] = At(tuple(i.text for i in p.value.items), p.key_span)  # type: ignore[union-attr]
            else:
                self.bad(SCHEMA, what, p.key_span, f'{what}: parameter "{p.key}" must be text or a list of text')
        return out

    def excepted(self, node: t.Map, what: str) -> tuple[Excepted, ...]:
        items = self.texts(node, "except", what) or ()
        out = []
        for i in items:
            code = self.name(i.text, i.span, CodeName.parse, "a code name (adapter:name, or a name)", what)
            if code:
                out.append(Excepted(code, i.reason, i.span))
        return tuple(out)

    def check_use(self, node: t.Map, what: str) -> CheckUse | None:
        kind = self.text(node, "check", what)
        if kind is None:
            return None
        return CheckUse(At(CheckKindName(kind.text), kind.span), self.params(node, what), self.excepted(node, what))


def _customer(r: _Reader, root: t.Map) -> list[Job]:
    jobs = []
    for entry in root:
        what = f"job {entry.key}"
        node = r.map(entry.value, what)
        name = r.name(entry.key, entry.key_span, slug, "a job name (lowercase words joined by hyphens)", what)
        if node is None or name is None:
            continue
        if name == MAINTAIN:
            r.keys(node, what, {"outcomes"})
        else:
            r.keys(node, what, {"job", "performer", "outcomes"}, {"job", "performer", "outcomes"})
        outcomes = []
        out_entry = node.get("outcomes")
        if out_entry is not None and (out_map := r.map(out_entry.value, f"{what} outcomes")) is not None:
            for o in out_map:
                oname = r.name(o.key, o.key_span, slug, "an outcome name (lowercase words joined by hyphens)", what)
                if oname is None:
                    continue
                if not isinstance(o.value, t.Text) or not o.value.text.strip():
                    r.bad(SCHEMA, what, o.key_span, f'outcome "{o.key}" must be a sentence')
                    continue
                outcomes.append(Outcome(OutcomeRef(name, oname), Sentence(o.value.text, o.value.span)))
        job, performer = r.text(node, "job", what), r.text(node, "performer", what)
        if name == MAINTAIN:
            jobs.append(Job(MAINTAIN, MAINTAIN_JOB.job, MAINTAIN_JOB.performer, tuple(outcomes), built_in=True))
        elif job and performer:
            jobs.append(Job(name, Sentence(job.text, job.span), Sentence(performer.text, performer.span),
                            tuple(outcomes)))
    return jobs


def _frs(r: _Reader, node: t.Map) -> list[Fr]:
    frs = []
    for entry in node:
        what = f"FR {entry.key}"
        body = r.map(entry.value, what)
        name = r.name(entry.key, entry.key_span, fr_name, "an FR name (lowercase identifiers joined by dots)", what)
        if body is None or name is None:
            continue
        r.keys(body, what, {"serves", "statements"})
        statements = []
        st_entry = body.get("statements")
        if st_entry is not None and (st_map := r.map(st_entry.value, f"{what} statements")) is not None:
            for s in st_map:
                sname = r.name(s.key, s.key_span, slug, "a statement name (lowercase words joined by hyphens)", what)
                if sname is None:
                    continue
                if not isinstance(s.value, t.Text) or not s.value.text.strip():
                    r.bad(SCHEMA, what, s.key_span, f'statement "{s.key}" must be a sentence')
                    continue
                statements.append(Statement(StatementRef(name, sname), Sentence(s.value.text, s.value.span)))
        serves_entry = body.get("serves")
        frs.append(Fr(name, r.outcomes(body, what) or (), serves_entry.key_span if serves_entry else None,
                      tuple(statements), entry.key_span))
    return frs


def _tuning(r: _Reader, entry: t.Entry, body: t.Map, what: str) -> Tuning:
    r.keys(body, what, {"with", "except", "on", "off"})
    on = r.text(body, "on", what)
    off = r.text(body, "off", what)
    if off is not None and off.text not in ("true", "false"):
        r.bad(SCHEMA, what, off.span, f'{what}: "off" is true or false')
    return Tuning(RuleId(entry.key), r.params(body, what), r.excepted(body, what), r.fr(on, what) if on else None,
                  off is not None and off.text == "true", entry.reason, entry.key_span)


def _rule_name(r: _Reader, entry: t.Entry, domain: Domain, what: str) -> tuple[RuleId | None, bool]:
    """The entry's name, and whether it tunes a built-in. A built-in of the other domain is a break."""
    built_in = BUILT_INS.get(RuleId(entry.key))
    if built_in is not None:
        if built_in.domain is not domain:
            r.bad(SCHEMA, what, entry.key_span,
                  f'"{entry.key}" is a built-in {built_in.domain.value} rule: tune it in design/{built_in.domain.value}.yaml')
            return None, False
        return RuleId(entry.key), True
    name = r.name(entry.key, entry.key_span, slug, "a rule name (lowercase words joined by hyphens)", what)
    return (RuleId(name) if name else None), False


def _constraints(r: _Reader, node: t.Map) -> tuple[list[Constraint], list[Tuning]]:
    constraints, tunings = [], []
    for entry in node:
        what = f"constraint {entry.key}"
        body = r.map(entry.value, what)
        name, tunes = _rule_name(r, entry, Domain.FUNCTIONAL, what)
        if body is None or name is None:
            continue
        if tunes:
            tunings.append(_tuning(r, entry, body, f"built-in {entry.key}"))
            continue
        r.keys(body, what, {"on", "serves", "check", "with", "statement", "except"}, {"on", "serves"})
        check, statement = body.get("check"), body.get("statement")
        if (check is None) == (statement is None):
            r.bad(SCHEMA, what, entry.key_span, f'{what} has exactly one of "check" or "statement"')
        if statement is not None and (body.get("with") or body.get("except")):
            r.bad(SCHEMA, what, entry.key_span, f'{what}: "with" and "except" go only with "check"')
        on = r.text(body, "on", what)
        stated = r.text(body, "statement", what)
        on_fr = r.fr(on, what) if on else None
        if on_fr is None:
            continue
        constraints.append(Constraint(
            name, on_fr, r.outcomes(body, what) or (), r.check_use(body, what),
            Sentence(stated.text, stated.span) if stated else None, entry.reason, entry.key_span))
    return constraints, tunings


def _functional(r: _Reader, root: t.Map) -> tuple[list[Fr], list[Constraint], list[Tuning]]:
    r.keys(root, "functional.yaml", {"frs", "constraints"})
    frs: list[Fr] = []
    constraints: list[Constraint] = []
    tunings: list[Tuning] = []
    if (e := root.get("frs")) is not None and (m := r.map(e.value, "frs")) is not None:
        frs = _frs(r, m)
    if (e := root.get("constraints")) is not None and (m := r.map(e.value, "constraints")) is not None:
        constraints, tunings = _constraints(r, m)
    return frs, constraints, tunings


def _physical(r: _Reader, root: t.Map) -> list[Placement]:
    out = []
    for entry in root:
        what = f"physical entry {entry.key}"
        name = r.name(entry.key, entry.key_span, fr_name, "an FR name (lowercase identifiers joined by dots)", what)
        if not isinstance(entry.value, t.Seq) or not all(isinstance(i, t.Text) for i in entry.value.items):
            r.bad(SCHEMA, what, entry.key_span, f"{what} must be a list of code names")
            continue
        units = []
        for i in entry.value.items:
            code = r.name(i.text, i.span, CodeName.parse, "a code name (adapter:name, or a name)", what)
            if code:
                units.append(At(code, i.span))
        if name:
            out.append(Placement(name, tuple(units), entry.key_span))
    return out


_KIND_KEYS: Mapping[str, tuple[set[str], set[str]]] = {
    "code-rule": ({"check", "with", "except"}, {"check"}),
    "verification": ({"evidence", "report"}, {"evidence"}),
    "validation": ({"measures", "report"}, {"measures", "report"}),
    "build": ({"step", "produces"}, {"step", "produces"}),
    "workflow": ({"gate"}, {"gate"}),
}


def _process_kind(r: _Reader, kind: str, body: t.Map, what: str) -> ProcessKind | None:
    if kind == "code-rule":
        check = r.check_use(body, what)
        return CodeRule(check) if check else None
    if kind == "verification":
        evidence = r.text(body, "evidence", what)
        report = r.text(body, "report", what)
        try:
            ev = EvidenceKind(evidence.text) if evidence else None
        except ValueError:
            r.bad(SCHEMA, what, evidence.span,
                  f'unknown evidence kind "{evidence.text}"; known: {", ".join(e.value for e in EvidenceKind)}')
            return None
        if ev is EvidenceKind.TEST_REPORT and report is None:
            r.bad(SCHEMA, what, body.span, f'{what}: test-report evidence needs "report"')
        return Verification(ev, report.text if report else None) if ev else None
    if kind == "validation":
        measures, report = r.text(body, "measures", what), r.text(body, "report", what)
        ref = r.name(measures.text, measures.span, OutcomeRef.parse, "an outcome reference", what) if measures else None
        return Validation(At(ref, measures.span), report.text) if ref and report else None
    if kind == "build":
        step, produces = r.text(body, "step", what), r.texts(body, "produces", what)
        return Build(step.text, tuple(p.text for p in produces)) if step and produces else None
    gate = r.text(body, "gate", what)
    if gate is None:
        return None
    try:
        return Workflow(Gate(gate.text))
    except ValueError:
        r.bad(SCHEMA, what, gate.span, f'unknown gate "{gate.text}"; known: {", ".join(g.value for g in Gate)}')
        return None


def _process(r: _Reader, root: t.Map) -> tuple[list[ProcessVariable], list[Tuning]]:
    variables, tunings = [], []
    for entry in root:
        what = f"process variable {entry.key}"
        body = r.map(entry.value, what)
        name, tunes = _rule_name(r, entry, Domain.PROCESS, what)
        if body is None or name is None:
            continue
        if tunes:
            tunings.append(_tuning(r, entry, body, f"built-in {entry.key}"))
            continue
        kind = r.text(body, "kind", what)
        if kind is None or kind.text not in _KIND_KEYS:
            r.bad(SCHEMA, what, entry.key_span, f'{what} needs "kind": one of {", ".join(_KIND_KEYS)}')
            continue
        own, required = _KIND_KEYS[kind.text]
        r.keys(body, what, {"kind", "on", "serves"} | own, {"on", "serves"} | required)
        on = r.text(body, "on", what)
        on_fr = r.fr(on, what) if on else None
        process_kind = _process_kind(r, kind.text, body, what)
        if on_fr and process_kind:
            variables.append(ProcessVariable(name, on_fr, r.outcomes(body, what) or (), process_kind,
                                             entry.reason, entry.key_span))
    return variables, tunings


def _once(r: _Reader, items: Iterable, key: Callable, span: Callable, what: str) -> dict:
    out: dict = {}
    for item in items:
        k = key(item)
        if k in out:
            first = span(out[k])
            r.bad(DEFINED_ONCE, str(k), span(item), f'{what} "{k}" is already defined at {first}')
            continue
        out[k] = item
    return out


def _span(item) -> Span:
    return item.span


def read_record(files: Mapping[RecordPath, str]) -> tuple[Record, tuple[Finding, ...]]:
    """The record from the design files, given as path to text. Paths are relative to the project root."""
    r = _Reader()
    jobs: list[Job] = []
    frs: list[Fr] = []
    constraints: list[Constraint] = []
    variables: list[ProcessVariable] = []
    tunings: list[Tuning] = []
    placements: list[Placement] = []
    for path in sorted(files):
        domain = domain_of(path)
        if domain is None:
            r.bad(DESIGN_FILES, path, Span(path, 1, 1),
                  "not a design file: use design/<domain>.yaml or design/<domain>/*.yaml, where the domain is "
                  "customer, functional, physical or process")
            continue
        root, problems = t.read_tree(path, files[path])
        r.problems.extend(problems)
        if root is None or (root := r.map(root, path)) is None:
            continue
        if domain is Domain.CUSTOMER:
            jobs += _customer(r, root)
        elif domain is Domain.FUNCTIONAL:
            f, c, tn = _functional(r, root)
            frs, constraints, tunings = frs + f, constraints + c, tunings + tn
        elif domain is Domain.PHYSICAL:
            placements += _physical(r, root)
        else:
            v, tn = _process(r, root)
            variables, tunings = variables + v, tunings + tn

    added = [o for j in jobs if j.name == MAINTAIN for o in j.outcomes]
    jobs = [j for j in jobs if j.name != MAINTAIN]
    maintain = Job(MAINTAIN, MAINTAIN_JOB.job, MAINTAIN_JOB.performer, MAINTAIN_JOB.outcomes + tuple(added), True)
    jobs_by_name = _once(r, jobs, lambda j: j.name, lambda j: j.job.span, "job")
    rules = _once(r, [*constraints, *variables], lambda x: x.name, _span, "rule")
    record = Record(
        jobs=(maintain, *jobs_by_name.values()),
        frs=_once(r, frs, lambda f: f.name, _span, "FR"),
        constraints={k: v for k, v in rules.items() if isinstance(v, Constraint)},
        process={k: v for k, v in rules.items() if isinstance(v, ProcessVariable)},
        tunings=_once(r, tunings, lambda x: x.name, _span, "built-in tuning"),
        placements=_once(r, placements, lambda p: p.dp, _span, "physical entry"),
    )
    _once(r, maintain.outcomes, lambda o: o.ref, lambda o: o.sentence.span, "outcome")
    return record, tuple(r.problems)

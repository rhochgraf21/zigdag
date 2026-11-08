"""The rules the record must keep on its own (DESIGN2 §4.4, record integrity and traceability; §6 grammars).

Everything here needs only the record and zigdag.toml. What also needs the code is counted, so the report can
say plainly what was not checked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from zigdag.core.effects import BUILT_IN as BUILT_IN_EFFECTS
from zigdag.core.effects import resource_container
from zigdag.core.kinds.params import Params, convert
from zigdag.core.kinds.registry import BUILT_IN_KINDS, CheckKind, Part
from zigdag.core.language import quality
from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.sentences import Pattern, Problem, parse_ears, parse_job, parse_outcome, parse_performer
from zigdag.core.language.tokens import tokenize, words
from zigdag.core.record.builtins import BUILT_INS, BuiltIn
from zigdag.core.record.model import At, CheckUse, CodeRule, Excepted, Record, Sentence, Validation
from zigdag.core.settings import Settings
from zigdag.core.findings import BUILT_IN_SPAN, Finding, Result, Span, finding
from zigdag.core.names import CheckKindName, FrName, OutcomeRef, RuleId, depth, is_within, parent, subject

ROOT = "root"
PARENTS = "parents"
REFERENCES = "references"
TRACEABILITY = "traceability"
SUBJECT = "ears.subject"
FUNCTION = "ears.function"
CHECK_KIND = "check-kind"
PARAMS = "params"
TUNING = "tuning"
RENDERED = "rendered-sentences"
MAX_CHILDREN = RuleId("max-children")
CODE_NOT_READ = "code-not-read"
ADAPTER = "adapter"


@dataclass
class _Waiting:
    """What could not be checked without the code."""

    supplied: frozenset[Part] = frozenset({Part.RECORD})
    rules: set[str] = field(default_factory=set)
    clauses: int = 0
    names: int = 0


def registry(settings: Settings) -> Mapping[CheckKindName, CheckKind]:
    custom = {
        name: CheckKind(name, c.params, c.reads, c.exactness,
                        lambda s, p, x, n=name: f"The {s} shall pass the {n} check{_except_text(x)}.")
        for name, c in settings.checks.items()
    }
    return {**BUILT_IN_KINDS, **custom}


def _except_text(excepted: tuple[str, ...]) -> str:
    return f", except in {', '.join(excepted)}" if excepted else ""


def _problems(problems: Iterable[Problem], about: str, span: Span, content: str) -> list[Finding]:
    return [finding(Result.BREAKS if p.exact else Result.QUESTION, p.rule, about, span, p.say, content)
            for p in problems]


def check_record(record: Record, settings: Settings, lexicons: Lexicons,
                 supplied: frozenset[Part] = frozenset({Part.RECORD})) -> tuple[Finding, ...]:
    out: list[Finding] = []
    waiting = _Waiting(supplied=supplied)
    kinds = registry(settings)
    out += _tree(record)
    out += _customer(record, lexicons)
    out += _statements(record, lexicons, waiting)
    out += _references(record)
    out += _rules(record, settings, lexicons, kinds, waiting)
    out += _placements(record, settings, waiting)
    out += _max_children(record, kinds, settings)
    if waiting.rules or waiting.clauses or waiting.names:
        out.append(_waiting_for(record, waiting))
    return tuple(out)


def _tree(record: Record) -> list[Finding]:
    out = []
    if not record.frs:
        return [finding(Result.TODO, ROOT, "design/functional.yaml", None,
                        "no FRs yet: write the root FR, the system itself, in design/functional.yaml")]
    roots = sorted(n for n in record.frs if "." not in n)
    if len(roots) != 1:
        for name in roots or sorted(record.frs)[:1]:
            out.append(finding(Result.BREAKS, ROOT, name, record.frs[name].span,
                               f"the record has exactly one root FR, not {len(roots)}: {', '.join(roots) or 'none'}"))
        return out
    root = roots[0]
    for name, fr in sorted(record.frs.items()):
        if not is_within(name, root):
            out.append(finding(Result.BREAKS, ROOT, name, fr.span, f'"{name}" does not start with the root, {root}'))
        elif (p := parent(name)) is not None and p not in record.frs:
            out.append(finding(Result.BREAKS, PARENTS, name, fr.span, f'"{name}" needs its parent, {p}, defined'))
        level = depth(name)
        if level == 1 and not fr.serves:
            out.append(finding(Result.TODO, TRACEABILITY, name, fr.span,
                               "say which outcomes this FR serves: it is on the first level below the root"))
        elif level != 1 and fr.serves_span is not None:
            where = "the root's are worked out" if level == 0 else "deeper FRs serve through their parent"
            out.append(finding(Result.BREAKS, TRACEABILITY, name, fr.serves_span,
                               f'"serves" belongs only on the first level below the root; {where}'))
    return out


def _customer(record: Record, lexicons: Lexicons) -> list[Finding]:
    out = []
    if not any(not j.built_in for j in record.jobs):
        out.append(finding(Result.TODO, "customer", "design/customer.yaml", None,
                           "no jobs yet: write who the system is for, and what they are trying to get done"))
    for job in record.jobs:
        if not job.built_in:
            j, p = job.job, job.performer
            out += _problems(parse_job(j.text, lexicons), job.name, j.span, j.text)
            out += _problems(quality.solution_words(j.text, lexicons), job.name, j.span, j.text)
            out += _problems(_second_verb(j.text, lexicons), job.name, j.span, j.text)
            out += _problems(quality.readable(j.text, quality.JOB_AND_OUTCOME_WORDS), job.name, j.span, j.text)
            out += _problems(parse_performer(p.text), job.name, p.span, p.text)
            out += _problems(quality.solution_words(p.text, lexicons), job.name, p.span, p.text)
        for o in job.outcomes:
            if o.sentence.span.built_in:
                continue
            s = o.sentence
            about = str(o.ref)
            out += _problems(parse_outcome(s.text), about, s.span, s.text)
            out += _problems(quality.solution_words(s.text, lexicons), about, s.span, s.text)
            out += _problems(quality.vague_words(s.text, lexicons), about, s.span, s.text)
            out += _problems(quality.readable(s.text, quality.JOB_AND_OUTCOME_WORDS), about, s.span, s.text)
    return out


def _second_verb(text: str, lexicons: Lexicons) -> list[Problem]:
    w = words(tokenize(text))
    return [Problem("job", False, f'"{a} {b}" may join a second job: one job per entry')
            for a, b in zip(w[1:], w[2:]) if a in ("and", "or") and b in lexicons.verbs]


def _statement(sentence: Sentence, name: FrName, about: str, lexicons: Lexicons, solution_free: bool,
               waiting: _Waiting) -> tuple[list[Finding], Pattern | None, bool]:
    """Findings for one EARS statement, its pattern, and whether it is negated."""
    ears, problems = parse_ears(sentence.text, lexicons)
    out = _problems(problems, about, sentence.span, sentence.text)
    if ears is None:
        return out, None, False
    expected = subject(name)
    if ears.subject != expected:
        out.append(finding(Result.BREAKS, SUBJECT, about, sentence.span,
                           f'the subject is "the {expected}", the last part of {name}, not "the {ears.subject}"',
                           sentence.text))
    out += _problems(quality.ears_quality(ears, lexicons), about, sentence.span, sentence.text)
    if solution_free:
        out += _problems(quality.named_solutions(ears, lexicons), about, sentence.span, sentence.text)
    if Part.STRUCTURES not in waiting.supplied:
        waiting.clauses += (ears.where is not None) + (ears.while_ is not None)
    return out, ears.pattern, ears.negated


def _statements(record: Record, lexicons: Lexicons, waiting: _Waiting) -> list[Finding]:
    out = []
    for name, fr in sorted(record.frs.items()):
        functions = 0
        for st in fr.statements:
            found, pattern, negated = _statement(st.sentence, name, str(st.ref), lexicons, depth(name) == 1, waiting)
            out += found
            functions += pattern is Pattern.UBIQUITOUS and not negated
        if not fr.statements:
            out.append(finding(Result.TODO, FUNCTION, name, fr.span,
                               f'write this FR\'s function: "The {subject(name)} shall ..."'))
        elif functions != 1:
            out.append(finding(Result.BREAKS, FUNCTION, name, fr.span,
                               f"an FR has exactly one ubiquitous statement without \"not\", its function; "
                               f"this one has {functions}"))
    for name, c in sorted(record.constraints.items()):
        if c.statement is not None and c.on.value in record.frs:
            found, _, _ = _statement(c.statement, c.on.value, name, lexicons, False, waiting)
            out += found
    return out


def _references(record: Record) -> list[Finding]:
    outcomes = record.outcomes
    out = []

    def outcome(ref: At[OutcomeRef], about: str) -> None:
        if ref.value not in outcomes:
            out.append(finding(Result.BREAKS, REFERENCES, about, ref.span, f'no outcome "{ref.value}"'))

    def fr(ref: At[FrName], about: str) -> None:
        if ref.value not in record.frs:
            out.append(finding(Result.BREAKS, REFERENCES, about, ref.span, f'no FR "{ref.value}"'))

    for name, f in record.frs.items():
        for ref in f.serves:
            outcome(ref, name)
    for name, c in record.constraints.items():
        fr(c.on, name)
        for ref in c.serves:
            outcome(ref, name)
        if not c.serves:
            out.append(finding(Result.BREAKS, TRACEABILITY, name, c.span, "a constraint serves at least one outcome"))
    for name, v in record.process.items():
        fr(v.on, name)
        for ref in v.serves:
            outcome(ref, name)
        if not v.serves:
            out.append(finding(Result.BREAKS, TRACEABILITY, name, v.span,
                               "a process variable serves at least one outcome"))
        if isinstance(v.kind, Validation):
            outcome(v.kind.measures, name)
    for name, tn in record.tunings.items():
        if tn.on is not None:
            fr(tn.on, name)
    return out


def _is_effect(record: Record, settings: Settings):
    def check(name: str) -> bool:
        if name in BUILT_IN_EFFECTS or name in settings.effects:
            return True
        container = resource_container(name)
        return container is not None and container in record.frs
    return check


def _use(use: CheckUse | BuiltIn, raw: Mapping, excepted: tuple[Excepted, ...], subject_of: FrName | None,
         about: str, span: Span, record: Record, settings: Settings, lexicons: Lexicons,
         kinds: Mapping[CheckKindName, CheckKind], waiting: _Waiting) -> list[Finding]:
    """Check one use of a check kind: the kind exists, its parameters convert, and its sentence is valid EARS."""
    kind_name = use.kind if isinstance(use, BuiltIn) else use.kind.value
    kind = kinds.get(kind_name)
    if kind is None:
        known = ", ".join(sorted(kinds))
        return [finding(Result.BREAKS, CHECK_KIND, about, span, f'no check kind "{kind_name}" (known: {known})')]
    out = []
    values = {k: v.value for k, v in raw.items()}
    params, problems = convert(kind.params, values, _is_effect(record, settings))
    for p in problems:
        at = raw[p.param].span if p.param in raw else span
        out.append(finding(Result.BREAKS, PARAMS, about, at, p.say))
    for e in excepted:
        if e.code.adapter_or(settings.default_adapter) is None:
            out.append(finding(Result.BREAKS, ADAPTER, about, e.span,
                               f'"{e.code}" has no adapter prefix, and zigdag.toml names no [adapters] default'))
    if Part.UNITS not in waiting.supplied:
        waiting.names += len(excepted)
    if kind.reads - waiting.supplied:
        waiting.rules.add(about)
    if not problems and subject_of is not None:
        out += _rendered(kind, params, excepted, subject_of, about, span, lexicons)
    return out


def _rendered(kind: CheckKind, params: Params, excepted: tuple[Excepted, ...], on: FrName, about: str, span: Span,
              lexicons: Lexicons) -> list[Finding]:
    text = kind.sentence(subject(on), params, tuple(str(e.code) for e in excepted))
    ears, problems = parse_ears(text, lexicons)
    problems = [*problems, *(quality.ears_quality(ears, lexicons) if ears else ())]
    return [finding(Result.BREAKS, RENDERED, about, span, f'its sentence "{text}" is not valid EARS: {p.say}', text)
            for p in problems if p.exact]


def _rules(record: Record, settings: Settings, lexicons: Lexicons, kinds: Mapping[CheckKindName, CheckKind],
           waiting: _Waiting) -> list[Finding]:
    out = []
    root = record.root.name if record.root else None
    for name, c in sorted(record.constraints.items()):
        if c.check is not None:
            on = c.on.value if c.on.value in record.frs else None
            out += _use(c.check, c.check.params, c.check.excepted, on, name, c.span, record, settings, lexicons,
                        kinds, waiting)
        elif c.statement is not None and Part.TESTS not in waiting.supplied:
            waiting.rules.add(name)  # its evidence comes from tests
    for name, v in sorted(record.process.items()):
        if isinstance(v.kind, CodeRule):
            on = v.on.value if v.on.value in record.frs else None
            out += _use(v.kind.check, v.kind.check.params, v.kind.check.excepted, on, name, v.span, record,
                        settings, lexicons, kinds, waiting)
    for name, b in sorted(BUILT_INS.items()):
        tn = record.tunings.get(name)
        if tn is not None and tn.off:
            if b.always_on:
                out.append(finding(Result.BREAKS, TUNING, name, tn.span,
                                   f"{name} is always on: it can be excepted, not switched off"))
            continue
        on = tn.on.value if tn and tn.on and tn.on.value in record.frs else root
        span = tn.span if tn else BUILT_IN_SPAN
        out += _use(b, tn.params if tn else {}, tn.excepted if tn else (), on, name, span, record, settings,
                    lexicons, kinds, waiting)
    return out


def _placements(record: Record, settings: Settings, waiting: _Waiting) -> list[Finding]:
    out = []
    for name, p in sorted(record.placements.items()):
        if name not in record.frs:
            out.append(finding(Result.BREAKS, REFERENCES, name, p.span, f'no FR "{name}" for this physical entry'))
        for unit in p.units:
            if unit.value.adapter_or(settings.default_adapter) is None:
                out.append(finding(Result.BREAKS, ADAPTER, name, unit.span,
                                   f'"{unit.value}" has no adapter prefix, and zigdag.toml names no [adapters] default'))
        if Part.UNITS not in waiting.supplied:
            waiting.names += len(p.units)
    return out


def _max_children(record: Record, kinds: Mapping[CheckKindName, CheckKind], settings: Settings) -> list[Finding]:
    tn = record.tunings.get(MAX_CHILDREN)
    if tn is not None and tn.off:
        return []
    params, problems = convert(kinds[CheckKindName("max-children")].params,
                               {k: v.value for k, v in (tn.params if tn else {}).items()}, lambda _: False)
    if problems:
        return []
    limit = params["count"]
    scope = tn.on.value if tn and tn.on else (record.root.name if record.root else None)
    children: dict[FrName, int] = {}
    for name in record.frs:
        if (p := parent(name)) is not None:
            children[p] = children.get(p, 0) + 1
    return [finding(Result.BREAKS, MAX_CHILDREN, name, record.frs[name].span,
                    f"{n} children; at most {limit} (split it into groups, or tune max-children)")
            for name, n in sorted(children.items())
            if n > limit and name in record.frs and scope is not None and is_within(name, scope)]


def _waiting_for(record: Record, waiting: _Waiting) -> Finding:
    rules = sorted(waiting.rules)
    statements = sum(len(fr.statements) for fr in record.frs.values()) if Part.TESTS not in waiting.supplied else 0
    parts = [f"{len(rules)} rules ({', '.join(rules)})"] if rules else []
    if statements:
        parts.append(f"the evidence for {statements} statements")
    if waiting.names:
        parts.append(f"{waiting.names} code names")
    if waiting.clauses:
        parts.append(f"{waiting.clauses} While and Where clauses")
    missing = ", ".join(p.value for p in Part if p not in waiting.supplied)
    say = ("the code was not read, so these wait for an adapter: " if waiting.supplied == {Part.RECORD} else
           f"no adapter supplied {missing}, so these wait: ")
    return finding(Result.QUESTION, CODE_NOT_READ, "code", None, say + "; ".join(parts),
                   *rules, str(statements), str(waiting.names), str(waiting.clauses))

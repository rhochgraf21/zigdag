"""Views (DESIGN2 §9), worked out from the record and the code, never written by hand.

- show: one level of the zigzag: the FR, its children, the design matrix, the rules in force, what is wrong.
- data: the data model: each structure, what it contains and refers to, and who creates, reads and changes it.
- context: what an agent needs before changing some code: why it exists, what limits it, what it may use.
- next: what is to do, in the order the design matrix allows building it.
"""

from __future__ import annotations

import deal

from zigdag.core.checks.evidence import EVIDENCE_RULES
from zigdag.core.checks.code_rules import CHECKS, RECORD_KINDS
from zigdag.core.checks.record_rules import registry
from collections.abc import Iterable, Mapping
from zigdag.core.effects import Effect
from zigdag.core.names import CheckKindName
from zigdag.core.kinds.registry import CheckKind, Exactness
from zigdag.core.settings import Settings
from zigdag.core.checks.rules import RuleUse
from zigdag.core.checks.run import Analysis
from zigdag.core.work import Delta, build_order
from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.sentences import Pattern, parse_ears
from zigdag.core.record.builtins import BUILT_INS
from zigdag.core.record.model import Domain, Gate
from zigdag.core.code import AccessKind, Qualified, SymbolKind
from zigdag.core.findings import Finding, Result, RuleName
from zigdag.core.names import FrName, is_within, parent, subject
from zigdag.core.texts import Say, Shown, Written

_LEXICONS = Lexicons()
NEXT_SHOWN = 10  # kinds of thing to do that `zigdag next` shows: enough to choose from, few enough to read
_ANY_SUBJECT = "…"  # stands for the name a finding is about, when two findings are compared by what they say


def _function(a: Analysis, name: FrName) -> str:
    fr = a.record.frs.get(name)
    for s in fr.statements if fr else ():
        ears, _ = parse_ears(s.sentence.text, _LEXICONS)
        if ears is not None and ears.pattern is Pattern.UBIQUITOUS and not ears.negated:
            return s.sentence.text
    return "(no function written yet)"


def _sentence(a: Analysis, rule: RuleUse) -> str:
    kind = registry(a.settings).get(rule.kind)
    return kind.sentence(subject(rule.on), rule.params, tuple(str(e.code) for e in rule.excepted)) if kind else rule.name


def _in_force(a: Analysis, name: FrName) -> tuple[list[str], list[str], int]:
    """The project's constraints and process variables that cover this FR, and how many built-ins also do."""
    constraints, process, built_in = [], [], 0
    for rule in a.rules:
        if not is_within(name, rule.on):
            continue
        if rule.name in BUILT_INS and rule.name not in a.record.tunings:
            built_in += 1
        elif rule.name in a.record.process or (rule.name in BUILT_INS and BUILT_INS[rule.name].domain is Domain.PROCESS):
            process.append(rule.name)
        else:
            constraints.append(_sentence(a, rule))
    for c in sorted(a.record.constraints.values(), key=lambda c: c.name):
        if c.statement is not None and is_within(name, c.on.value):
            constraints.append(c.statement.text)
    for pname, v in sorted(a.record.process.items()):
        if pname not in process and is_within(name, v.on.value):
            process.append(pname)
    return constraints, sorted(set(process)), built_in


def _code(a: Analysis, name: FrName) -> str:
    if a.tree is None or name not in a.tree.dps:
        return "code not read"
    dp = a.tree.dps[name]
    if dp.claims:
        return ", ".join(c.type or c.unit for c in dp.claims)
    return "a grouping of its children" if dp.children else "no code yet"


def _evidence(a: Analysis, ref: str) -> str:
    found = [f for f in a.report.findings if f.about == ref and f.rule in EVIDENCE_RULES]
    if any(f.result is Result.BREAKS for f in found):
        return "broken"
    if any(f.result is Result.OUT_OF_DATE for f in found):
        return Result.OUT_OF_DATE.value
    if any(f.result is Result.TODO for f in found):
        return "to do"
    return "passing" if a.code is not None else "not read"


@deal.ensure(lambda a, name=None, *, result: name is None or name not in a.record.frs or result.startswith(f"{name}:"))
def show(a: Analysis, name: FrName | None = None) -> Shown:
    root = a.record.root
    if root is None:
        return "no root FR yet: write it in design/functional.yaml"
    name = name or root.name
    if name not in a.record.frs:
        return f'no FR named "{name}"'
    fr = a.record.frs[name]
    level = a.tree.dps[name].level if a.tree and name in a.tree.dps else None
    lines = [f"{name}: {_function(a, name)}",
             f"  level: {level.name.lower() if level is not None else 'unknown'}    code: {_code(a, name)}"]
    if fr.serves:
        lines.append("  serves: " + ", ".join(str(s.value) for s in fr.serves))
    elif parent(name):
        lines.append(f"  serves: through {parent(name)}")
    lines.append("  statements:")
    for s in fr.statements:
        lines.append(f"    {s.ref.statement} [{_evidence(a, str(s.ref))}]: {s.sentence.text}")
    constraints, process, built_in = _in_force(a, name)
    if constraints:
        lines += ["  constraints in force:", *(f"    {c}" for c in constraints)]
    if process:
        lines.append("  process in force: " + ", ".join(process))
    lines.append(f"  and {built_in} built-in rules (zigdag checks lists them)")
    children = a.tree.dps[name].children if a.tree and name in a.tree.dps else tuple(
        n for n in a.record.frs if parent(n) == name)
    if children:
        lines += ["", "  children:"]
        lines += [f"    {c.rpartition('.')[2]}: {_function(a, c)}  ({_code(a, c)})" for c in children]
        if a.relations is not None and a.tree is not None:
            lines += ["", *_matrix(a, name)]
    found = a.under(name)
    counts = {r: sum(1 for f in found if f.result is r) for r in Result}
    lines += ["", f"  under {name}: {counts[Result.BREAKS]} breaks, {counts[Result.QUESTION]} questions, "
                  f"{counts[Result.OUT_OF_DATE]} results out of date, {counts[Result.TODO]} things to do"]
    lines += [f"    {f.result.value}: {f.rule}  {f.about}: {f.say}" for f in found
              if f.result is Result.BREAKS][:10]
    return "\n".join(lines)


def _matrix(a: Analysis, name: FrName) -> list[str]:
    order, cells = a.relations.matrix(a.tree, name)
    labels = [c.rpartition(".")[2] for c in order]
    width = max(len(x) for x in labels)
    head = " " * (width + 4) + "  ".join(x[:3].ljust(3) for x in labels)
    rows = []
    for c, label in zip(order, labels):
        marks = ["■".ljust(3) if c == d else ("x" if (c, d) in cells else ".").ljust(3) for d in order]
        rows.append(f"  {label.rjust(width)}  " + "  ".join(marks))
    return ["  design matrix (row depends on column):", head, *rows]


_CRUD = ((AccessKind.CREATES, "C"), (AccessKind.READS, "R"), (AccessKind.UPDATES, "U"), (AccessKind.DELETES, "D"))


@deal.ensure(lambda a, name=None, *, result: a.data is None or name is None or all(
    dp in result for dp in a.data.structures if is_within(dp, name)))  # every structure under it is shown
def data(a: Analysis, name: FrName | None = None) -> Shown:
    if a.data is None:
        return "the code was not read, so there is no data model"
    root = name or (a.record.root.name if a.record.root else None)
    if root is None:
        return "no root FR yet: write it in design/functional.yaml"
    structures = [s for dp, s in sorted(a.data.structures.items()) if is_within(dp, root)]
    if not structures:
        return f"no recorded structures under {root}: a structure is a DP whose code is a type"
    lines = [f"data under {root}: {len(structures)} structures"]
    for st in structures:
        where = ", ".join(f"{adapter}:{symbol.qualified}" for adapter, symbol in sorted(st.representations.items()))
        lines += ["", f"  {st.dp}: {where}{'  (stored)' if st.stored else ''}", f"    owned by {st.owner}"]
        lines += [f"    {f.name}: {f.type.text if f.type else '(no type)'}{'  (key)' if f.key else ''}"
                  for f in st.fields]
        for r in (r for r in a.data.relations if r.source == st.dp):
            lines.append(f"    {r.kind.value} {r.target or r.target_type + ' (not recorded)'}: {r.cardinality.value}, "
                         f"through {r.field.name}")
    names = {st.dp for st in structures}
    touched: dict[FrName, dict[FrName, set[AccessKind]]] = {}
    for x in a.data.accesses:
        if x.structure in names:
            touched.setdefault(x.dp, {}).setdefault(x.structure, set()).add(x.kind)
    if touched:
        labels = [st.dp.rpartition(".")[2] for st in structures]
        width = max(len(dp) for dp in touched)
        lines += ["", "  create, read, update, delete (row's code on column's structure):",
                  " " * (width + 4) + "  ".join(x[:4].ljust(4) for x in labels)]
        for dp, kinds in sorted(touched.items()):
            cells = ["".join(c for k, c in _CRUD if k in kinds.get(st.dp, ())) or "." for st in structures]
            lines.append(f"  {dp.ljust(width)}  " + "  ".join(c.ljust(4) for c in cells))
    return "\n".join(lines)


def _changed(delta: Delta) -> list[str]:
    """What a change says of a part: what it changed in the design that concerns the part, then what it asks of the
    part. This comes first in the part's context, since it is what whoever builds the part is there to do."""
    lines = [f"  changed since {delta.base}:", *(f"    {line}" for c in delta.changes for line in c.shown)] if (
        delta.changes) else [f"  nothing that concerns it changed since {delta.base}"]
    if delta.asked is not None:
        lines += ["", "  asked, and not given yet:", *(f"    {reason}" for reason in delta.asked.reasons)]
    return [*lines, ""]


@deal.ensure(lambda a, target, delta=None, *, result: (dp := a.dp_of(target)) is None or result.startswith(f"{dp}:"))
def context(a: Analysis, target: Written, delta: Delta | None = None) -> Shown:
    name = a.dp_of(target)
    if name is None:
        return f'no FR, and no code zigdag read, is "{target}"'
    lines = [f"{name}: {_function(a, name)}", f"  code: {_code(a, name)}", "",
             *(_changed(delta) if delta is not None else []), "  why it exists:"]
    chain = []
    n: FrName | None = name
    while n is not None:
        chain.append(n)
        n = parent(n)
    outcomes = a.record.outcomes
    served = [ref.value for n in chain for ref in (a.record.frs[n].serves if n in a.record.frs else ())]
    for job in a.record.jobs:
        mine = [outcomes[r] for r in served if r.job == job.name and r in outcomes]
        if mine:
            lines.append(f"    {job.performer.text} wants to: {job.job.text}")
            lines += [f"      {o.sentence.text}" for o in mine]
    lines.append("    through: " + " ← ".join(chain))
    fr = a.record.frs.get(name)
    if fr and fr.statements:
        lines += ["", "  it must:", *(f"    {s.sentence.text}  [{_evidence(a, str(s.ref))}]" for s in fr.statements)]
    constraints, process, built_in = _in_force(a, name)
    if constraints:
        lines += ["", "  limits:", *(f"    {c}" for c in constraints)]
    lines.append(f"    and {built_in} built-in rules")
    if process:
        lines += ["", "  process: " + ", ".join(process)]
    if a.relations is not None and a.tree is not None and a.code is not None:
        used: dict[FrName, set[Qualified]] = {}
        for edge in a.relations.edges:
            if a.tree.within(edge.source, name) and not a.tree.within(edge.target, name):
                q = edge.target_name
                while q and Qualified(q) not in a.code.symbols:
                    q = q.rpartition(".")[0]
                used.setdefault(edge.target, set()).update({Qualified(q)} if q else set())
        if used:
            lines += ["", "  it uses:"]
            for dp, names in sorted(used.items()):
                lines.append(f"    {dp}: {_function(a, dp)}")
                for q in sorted(names):
                    s = a.code.symbols[q]
                    sig = ""
                    if s.signature is not None and s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                        params = ", ".join(p.name + (f": {p.type.text}" if p.type else "") for p in s.signature.params)
                        sig = f"({params})" + (f" -> {s.signature.returns.text}" if s.signature.returns else "")
                    lines.append(f"      {s.name}{sig}" + (f"  # {s.description}" if s.description else ""))
    found = [f for f in a.under(name) if f.result is not Result.TODO]
    if found:
        lines += ["", "  open here:", *(f"    {f.result.value}: {f.rule}: {f.say}" for f in found[:15])]
    return "\n".join(lines)


def _kind_of(f: Finding) -> tuple[RuleName, Say]:
    """What makes two things to do the same kind of work: the rule that found them, and what it says once the name
    of what each is about is taken out."""
    return f.rule, Say(f.say.replace(f.about, _ANY_SUBJECT))


@deal.ensure(lambda a, result: len(result.splitlines()) <= NEXT_SHOWN + 2)  # a heading, the kinds, what is left out
@deal.ensure(lambda a, result: not a.report.of_result(Result.TODO) or result.startswith(
    f"{len(a.report.of_result(Result.TODO))} things to do"))
def next_steps(a: Analysis) -> Shown:
    """What is to do, in the order the design matrix allows. Things of one kind share a line, so that one kind with
    many cases cannot bury the rest, and only the first kinds are shown: what to do next is a short list."""
    order = {n: i for i, n in enumerate(build_order(a))}
    todo = [f for f in a.report.findings if f.result is Result.TODO]
    ranked = sorted(todo, key=lambda f: (order.get(a.dp_of_finding(f) or "", len(order)), f.about, f.say))
    if not ranked:
        return "nothing to do"
    kinds: dict[tuple[RuleName, Say], list[Finding]] = {}
    for f in ranked:  # a kind stands where its first case does
        kinds.setdefault(_kind_of(f), []).append(f)
    lines = [f"{len(ranked)} things to do, in the order the design matrix allows:"]
    for alike in list(kinds.values())[:NEXT_SHOWN]:
        first, more = alike[0], len(alike) - 1
        lines.append(f"  {first.about}{f' and {more} more like it' if more else ''}: {first.say}")
    if len(kinds) > NEXT_SHOWN:
        lines.append(f"and {len(kinds) - NEXT_SHOWN} more kinds: zigdag check --full")
    return "\n".join(lines)


# ---- the list of rules -------------------------------------------------------------------------------------------

_ANY_PROJECT = "project"  # the subject of a rule's sentence when no project is named: "The project shall ..."
_FAILS_AS = {Exactness.EXACT: "a break", Exactness.GUESS: "a question", Exactness.BOTH: "a break, or a question"}
# A rule whose settings must be given has no sentence until they are, so its row shows one made from these.
_EXAMPLES: Mapping[CheckKindName, Mapping[str, object]] = {
    CheckKindName("effects"): {"allow": (Effect("read"),)},
    CheckKindName("may-depend-on"): {"allow": ("project.core",)},
    CheckKindName("data-flow"): {"data": ("Email",), "never-reaches": (Effect("stdout"),)},
}
_GATES: Mapping[Gate, Say] = {
    Gate.CRITIQUE_BEFORE_REVIEW: Say("Every changed design entry is critiqued, at its current content, before it is "
                                     "approved."),
    Gate.PERSON_APPROVES_DESIGN: Say("Every changed design entry is approved by a person."),
    Gate.STOP_ON_ERROR: Say("A change is not accepted while any check breaks."),
    Gate.COUNTERMEASURE_ON_ESCAPE: Say("A defect that a person found, and no check did, is closed only together with "
                                       "the rule or requirement that will catch it next time."),
}
_ALWAYS_CHECKED = (
    Say("Every design file can be read, every sentence fits its grammar, and every name is defined once."),
    Say("Every module belongs to exactly one part of the design."),
    Say("Every requirement on the first level, and every rule, serves a goal someone has."),
    Say("A function that declares its effects has no others, and every contract holds on generated inputs."),
    Say("A test counts for a requirement only if it passed, ran that part's code, and ran against the code as it is."),
)


def _settings_of(kind: CheckKind) -> str:
    """A kind's settings with the value each has by default; one with none must be given by the rule."""
    return ", ".join(f"`{name}` = {spec.default:g}" if isinstance(spec.default, float) else
                     f"`{name}` = {spec.default}" if spec.default is not None else f"`{name}` (must be given)"
                     for name, spec in kind.params.items()) or "none"


def _rule_row(kind: CheckKind) -> str:
    example = _EXAMPLES.get(kind.name)
    values = example or {name: spec.default for name, spec in kind.params.items()}
    said = f"{'For example: ' if example else ''}{kind.sentence(_ANY_PROJECT, values, ())}"
    return f"| `{kind.name}` | {said} | {_settings_of(kind)} | {_FAILS_AS[kind.exactness]} |"


def _rule_table(kinds: Iterable[CheckKind]) -> list[str]:
    return ["| Rule | What it holds the code to | Settings | When it fails, it is |", "|---|---|---|---|",
            *(_rule_row(kind) for kind in sorted(kinds, key=lambda k: k.name))]


@deal.ensure(lambda settings, result: all(f"`{kind}`" in result for kind in registry(settings)))  # every rule is listed
@deal.ensure(lambda settings, result: all(f"`{gate.value}`" in result for gate in Gate))
def rules(settings: Settings) -> Shown:
    """Every rule zigdag has, as Markdown: what each holds a project to, its settings and their defaults, and whether
    failing it is a break or a question. It is made from the registry the checks run from, so it cannot list a rule
    that does not exist or leave out one that does."""
    kinds = registry(settings)
    by_default = {rule.kind: rule for rule in BUILT_INS.values()}
    always = [kinds[k] for k, rule in by_default.items() if rule.always_on]
    tunable = [kinds[k] for k, rule in by_default.items() if not rule.always_on]
    unbuilt = [kind for name, kind in kinds.items() if name not in CHECKS and name not in RECORD_KINDS
               and name not in settings.checks]
    chosen = [kind for name, kind in kinds.items() if name not in by_default and name not in settings.checks
              and kind not in unbuilt]
    lines = [
        "# The rules", "",
        "Every rule zigdag can hold a project to. This file is what `zigdag checks` prints, made from the same list "
        "the checks run from.", "",
        "## Always on", "", "These cannot be switched off. A known break can be listed under the rule's `except`.", "",
        *_rule_table(always), "",
        "These are checked always too, and have nothing to set:", "", *(f"- {said}" for said in _ALWAYS_CHECKED), "",
        "## On by default", "",
        "These are on without being written. To change one, write an entry with its name in the design file of its "
        "kind, with `with` for its settings, `except` for known breaks, `on` to narrow it, or `off: true`. "
        "`zigdag init --default` writes them all out.", "",
        *_rule_table(tunable), "",
        "## On when you write a rule for them", "",
        "Each of these is used by writing a rule that names it under `check`, and the part of the design it is `on`.",
        "", *_rule_table(chosen), "",
        "## Designed, and not built yet", "",
        "Nothing checks these in this version: no adapter reads infrastructure or git history yet. A rule that names "
        "one is asked about, never passed.", "", *_rule_table(unbuilt), "",
        "## Gates on a change", "", "A gate is on when a `workflow` rule names it. `zigdag check --base <revision>` and "
        "`zigdag ready --base <revision>` hold a change to them.", "",
        "| Gate | Holds when |", "|---|---|", *(f"| `{gate.value}` | {said} |" for gate, said in _GATES.items()),
    ]
    if settings.checks:
        lines += ["", "## This project's own rules", "", "Functions in `design/checks/`.", "",
                  "| Rule | What it says of itself | Settings | Written in |", "|---|---|---|---|",
                  *(f"| `{name}` | {check.description} | {_settings_of(kinds[name])} | `{check.source}` |"
                    for name, check in sorted(settings.checks.items()))]
    return Shown("\n".join(lines) + "\n")

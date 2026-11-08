"""Views (DESIGN2 §9), worked out from the record and the code, never written by hand.

- show: one level of the zigzag: the FR, its children, the design matrix, the rules in force, what is wrong.
- data: the data model: each structure, what it contains and refers to, and who creates, reads and changes it.
- context: what an agent needs before changing some code: why it exists, what limits it, what it may use.
- next: what is to do, in the order the design matrix allows building it.
"""

from __future__ import annotations

from zigdag.core.checks.evidence import EVIDENCE_RULES
from zigdag.core.checks.record_rules import registry
from zigdag.core.checks.rules import RuleUse
from zigdag.core.checks.run import Analysis
from zigdag.core.code import AccessKind, Qualified, SymbolKind
from zigdag.core.findings import Result
from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.sentences import Pattern, parse_ears
from zigdag.core.names import FrName, is_within, parent, subject
from zigdag.core.record.builtins import BUILT_INS
from zigdag.core.record.model import Domain

_LEXICONS = Lexicons()


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
    if any(f.result is Result.TODO for f in found):
        return "to do"
    return "passing" if a.code is not None else "not read"


def show(a: Analysis, name: FrName | None = None) -> str:
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
                  f"{counts[Result.TODO]} things to do"]
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


def data(a: Analysis, name: FrName | None = None) -> str:
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


def context(a: Analysis, target: str) -> str:
    name = a.dp_of(target)
    if name is None:
        return f'no FR, and no code zigdag read, is "{target}"'
    lines = [f"{name}: {_function(a, name)}", f"  code: {_code(a, name)}", "", "  why it exists:"]
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


def _build_order(a: Analysis) -> list[FrName]:
    """Every DP, after the siblings it depends on: the order the design matrix allows building in."""
    if a.tree is None or a.relations is None:
        return sorted(a.record.frs)
    out: list[FrName] = []

    def visit(name: FrName) -> None:
        out.append(name)
        order, cells = a.relations.matrix(a.tree, name)
        placed: list[FrName] = []
        remaining = list(order)
        while remaining:
            ready = [c for c in remaining if all((c, d) not in cells for d in remaining if d != c)] or remaining[:1]
            for c in ready:
                remaining.remove(c)
                placed.append(c)
        for c in placed:
            visit(c)

    if a.record.root is not None:
        visit(a.record.root.name)
    return out + sorted(set(a.record.frs) - set(out))


def next_steps(a: Analysis) -> str:
    order = {n: i for i, n in enumerate(_build_order(a))}
    todo = [f for f in a.report.findings if f.result is Result.TODO]
    ranked = sorted(todo, key=lambda f: (order.get(a.dp_of_finding(f) or "", len(order)), f.about, f.say))
    if not ranked:
        return "nothing to do"
    lines = [f"{len(ranked)} things to do, in the order the design matrix allows:"]
    lines += [f"  {f.about}: {f.say}" for f in ranked]
    return "\n".join(lines)

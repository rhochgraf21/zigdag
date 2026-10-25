"""Each review page as HTML, in plain words. Part of arch.review.page.

Every page opens with one sentence saying what it shows and what the reviewer decides. Every id is a link
with its meaning on hover. Files open in the reviewer's editor.
"""

from __future__ import annotations

import difflib
import enum
import html
from dataclasses import dataclass
from typing import NewType

from arch.model.ids import ComponentId, ConstraintId, NeedId, Text, short_name
from arch.realize.facts import Compatibility, FileShape, LineNo, SourcePath
from arch.review.items import (
    ArchitectureBody,
    BatchBody,
    Change,
    CodeBody,
    CriterionChange,
    ConstraintsBody,
    DesignBody,
    Glossary,
    Hunked,
    IntentBody,
    InterfaceNote,
    ItemId,
    InterfacesBody,
    OverviewBody,
    Readiness,
    ReviewItem,
)
from arch.review.explain import Doubt, HunkView, Question, Reason, Why
from arch.review.page import highlight
from arch.view.diagram import Diagram, Mark, svg
from arch.view.render import Count

PageHtml = NewType("PageHtml", str)  # one page of the deck
Fragment = NewType("Fragment", str)  # a piece of a page
Href = NewType("Href", str)  # where a link goes: a page of the deck, or a file in the editor
ProjectRoot = NewType("ProjectRoot", str)  # absolute path, for editor links


class Editor(enum.Enum):
    VSCODE = "vscode"
    CURSOR = "cursor"
    NONE = "none"


_EVIDENCE_TIPS = {
    "passed": "A linked test passed in the latest test report.",
    "failed": "A linked test failed in the latest test report.",
    "no evidence": "No test or contract is linked to this criterion yet.",
    "linked, no report": "A test is linked, but no test report was read.",
    "unchanged": "This criterion did not change.",
}
_EVIDENCE_WORDS = {"passed": "tests pass", "failed": "a test fails", "no evidence": "no test",
                   "linked, no report": "test not run", "unchanged": ""}
_DECISION_LABELS = {"Chose": "Chose", "Over": "Instead of", "Because": "Because", "Consequences": "As a result",
                    "Previously": "Before this", "Backed by": "Backed by"}
_CHANGE_WORDS = {Change.ADDED: "added", Change.REMOVED: "removed", Change.CHANGED: "changed", Change.MOVED: "moved",
                 Change.UNCHANGED: "unchanged"}


def _e(text: object) -> str:
    return html.escape(str(text)) if text is not None else ""


def _tip(text: str | None) -> str:
    return f' data-tip="{_e(text)}"' if text else ""


def _link(cls: str, href: Href | None, tip: str | None, label: str) -> Fragment:
    """A link when there is somewhere to go, plain text with the same hover text otherwise."""
    if href:
        return Fragment(f'<a class="{cls}" href="{href}"{_tip(tip)}>{_e(label)}</a>')
    return Fragment(f'<span class="{cls}"{_tip(tip)}>{_e(label)}</span>')


class Named(enum.Enum):
    """How a criterion chip is labelled."""

    SHORT = "short"  # AC2: on a page about its component
    WITH_COMPONENT = "with component"  # assess#AC2: where criteria of several components can meet


@dataclass(frozen=True)
class Refs:
    """Links and hover text for every id on the page."""

    glossary: Glossary
    root: ProjectRoot
    editor: Editor
    pages: frozenset[ItemId]

    def editor_link(self, path: Text, line: LineNo | None = None) -> Href | None:
        if self.editor is Editor.NONE or not path:
            return None
        suffix = f":{line}" if line else ""
        return Href(f"{self.editor.value}://file{_e(self.root)}/{_e(path)}{suffix}")

    def component(self, cid: ComponentId, label: Text | None = None) -> Fragment:
        tip = self.glossary.components.get(cid)
        page = self.glossary.pages.get(cid)
        href = Href(f"#{_e(page)}") if page else self.editor_link(self.glossary.files.get(Text(cid), Text("")))
        return _link("ref", href, f"{cid} must {_lower(tip)}" if tip else cid, label or cid)

    def component_path(self, cid: ComponentId) -> Fragment:
        parts = cid.split(".")
        crumbs = "".join(f"<span>{_e(p)}</span><span class=sep>›</span>" for p in parts[:-1])
        file = self.glossary.files.get(Text(cid))
        link = self.editor_link(file) if file else None
        opener = f' <a class="open" href="{link}" data-tip="Open the design file">↗</a>' if link else ""
        return Fragment(f'<span class="crumbs">{crumbs}{self.component(cid, Text(parts[-1]))}</span>{opener}')

    def need(self, nid: NeedId) -> Fragment:
        href = Href("#intent") if "intent" in self.pages else None
        return _link("chip need", href, self.glossary.needs.get(nid), nid)

    def criterion(self, cid: Text, verdict: Text | None = None, named: Named = Named.SHORT) -> Fragment:
        component, _, short = cid.partition("#")
        label = f"{short_name(ComponentId(component))}#{short}" if named is Named.WITH_COMPONENT and short else short or cid
        text = self.glossary.criteria.get(Text(cid))
        tip = " ".join(x for x in (f"{label}: {text}" if text else None, _EVIDENCE_TIPS.get(verdict or "")) if x)
        cls = f" ev-{_e((verdict or '').replace(' ', '-').replace(',', ''))}" if verdict else ""
        return Fragment(f'<span class="chip crit{cls}"{_tip(tip)}>{_e(label)}</span>')

    def interface(self, dotted: Text) -> Fragment:
        """A changed interface: its short name, how it reads now on hover, and a link to the page that shows it."""
        page = self.glossary.interface_pages.get(dotted)
        name = dotted.rsplit(".", 2)
        label = ".".join(name[-2:]) if len(name) > 2 and name[-2][:1].isupper() else name[-1]
        unit = dotted[: -len(label) - 1]
        tip = self.glossary.interfaces.get(dotted)
        return Fragment(f'<code>{_link("ref", Href(f"#{_e(page)}") if page else None, f"{unit}: {tip}" if tip else dotted, label)}</code>')

    def constraint(self, kid: ConstraintId) -> Fragment:
        link = self.editor_link(self.glossary.files.get(Text(kid), Text("")))
        return _link("chip rule", link, self.glossary.constraints.get(kid), kid)


def _badge(change: Change) -> str:
    return f'<span class="badge b-{change.value}">{_CHANGE_WORDS[change]}</span>'


def _lead(text: str) -> str:
    return f'<p class="lead">{text}</p>'


def _lower(text: str) -> str:
    """The sentence as it reads after "must": first letter lower case unless the word is an acronym."""
    text = text.rstrip(".")
    return text if text[1:2].isupper() else text[:1].lower() + text[1:]


def _text_diff(before: str | None, after: str | None) -> str:
    """Before and after, side by side, with changed lines marked."""
    if before == after:
        return f'<div class="tdiff single"><div class="col">{_e(after)}</div></div>'
    if before is None:
        return f'<div class="tdiff single"><div class="col"><div class="cap">new</div><div class="add">{_e(after)}</div></div></div>'
    if after is None:
        return f'<div class="tdiff single"><div class="col"><div class="cap">removed</div><div class="del">{_e(before)}</div></div></div>'
    a, b = before.split("\n"), after.split("\n")
    left, right = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        left += [f'<div class="{"same" if op == "equal" else "del"}">{_e(x)}</div>' for x in a[i1:i2]]
        right += [f'<div class="{"same" if op == "equal" else "add"}">{_e(x)}</div>' for x in b[j1:j2]]
    return (f'<div class="tdiff"><div class="col"><div class="cap">before</div>{"".join(left)}</div>'
            f'<div class="col"><div class="cap">after</div>{"".join(right)}</div></div>')


def page_html(item: ReviewItem, number: Count, total: Count, note: Text | None, refs: Refs) -> PageHtml:
    renderers = {OverviewBody: _overview, IntentBody: _intent, ArchitectureBody: _architecture,
                 ConstraintsBody: _constraints, DesignBody: _design, InterfacesBody: _interfaces, CodeBody: _code,
                 BatchBody: _batch}
    inner = renderers[type(item.body)](item.body, refs)
    note_html = f'<aside class="note"><div class="note-head">Note from the author</div>{_e(note)}</aside>' if note else ""
    return PageHtml(
        f'<section class="page" id="{_e(item.id)}" data-id="{_e(item.id)}" hidden>'
        f'<div class="page-head"><div class="eyebrow">Page {number} of {total} · {_e(item.stage.value)}</div>'
        f'<h1>{_e(item.title)}</h1><div class="meta"><span class="pill risk-{item.risk.value}">{_e(item.risk.value)} risk</span>'
        f'<span class="pill state" data-state></span></div></div>{note_html}{inner}</section>')


def _overview(b: OverviewBody, refs: Refs) -> str:
    ready = b.readiness is Readiness.READY
    tallies = "".join(f'<div class="stat"><div class="num">{t.count}</div><div class="lbl">{_e(t.label)}</div></div>'
                      for t in b.tallies if t.count)
    lines = (f'<div class="stat"><div class="num"><span class="plus">+{b.lines_added}</span> '
             f'<span class="minus">−{b.lines_removed}</span></div><div class="lbl">lines of code</div></div>')
    status = ('<div class="callout ok"><b>Machine checks pass.</b> The structure, the effects, the interface types and '
              'the linked tests show no problems.</div>' if ready else
              '<div class="callout bad"><b>Machine checks found problems.</b> They are listed below. '
              'You can review anyway, or send the change back.</div>')
    findings = "".join(f"<li>{_e(x)}</li>" for x in b.new_findings)
    tests = "".join(f"<li>{_e(x)}</li>" for x in b.failing_tests)
    return (_lead("This page summarises the change. The next pages go from what the system must do, to how it is built, "
                  "to the code.") + status + f'<div class="stats">{tallies}{lines}</div>'
            + (f'<div class="card"><h2>New problems found by the checks</h2><ul>{findings}</ul></div>' if findings else "")
            + (f'<div class="card"><h2>Failing tests</h2><ul>{tests}</ul></div>' if tests else "")
            + '<div class="card"><h2>Pages</h2><ol class="toc" id="toc"></ol></div>'
            + '<p class="hint">Press <kbd>→</kbd> for the next page and <kbd>←</kbd> to go back. Press <kbd>A</kbd> to '
              'approve a page, <kbd>R</kbd> to ask for changes, or <kbd>C</kbd> to comment.</p>')


def _intent(b: IntentBody, refs: Refs) -> str:
    needs = "".join(
        f'<div class="row" id="need-{_e(n.need)}"><div class="row-head">{_badge(n.change)}<b>{_e(n.need)}</b>'
        + (f'<span class="muted">for {_e(n.stakeholder)}</span>' if n.stakeholder else "")
        + f'</div>{_text_diff(n.before, n.after)}</div>' for n in b.needs)
    reqs = []
    for r in b.requirements:
        changed = [c for c in r.criteria if c.change is not Change.UNCHANGED]
        criteria = "".join(
            f'<li>{_badge(c.change)}{refs.criterion(Text(f"{r.component}#{c.label}"), _shown(c))}'
            f'<span class="ctext">{_e(c.after or c.before)}</span>{_evidence(c)}</li>' for c in changed)
        moved = f'<span class="muted">moved from {_e(r.moved_from)}</span>' if r.moved_from else ""
        serves = "".join(refs.need(n) for n in r.serves) or '<span class="muted">No need is listed. It serves the needs of its parent.</span>'
        reqs.append(
            f'<div class="row"><div class="row-head">{_badge(r.change)}{refs.component_path(r.component)}{moved}</div>'
            f'<div class="label">Must do</div>{_text_diff(r.before, r.after)}'
            f'<div class="label">Serves</div><div>{serves}</div>'
            + (f'<div class="label">Acceptance criteria that changed</div><ul class="crits">{criteria}</ul>' if criteria else "")
            + "</div>")
    return (_lead("These are the changes to what the system must do. Approve if each need and requirement is right, "
                  "and each criterion can be tested.")
            + (f'<div class="card"><h2>Customer needs</h2>{needs}</div>' if needs else "")
            + (f'<div class="card"><h2>Functional requirements</h2>{"".join(reqs)}</div>' if reqs else ""))


def _shown(c: CriterionChange) -> Text | None:
    """The evidence worth showing: none for a criterion that was removed."""
    return None if c.change is Change.REMOVED or c.evidence == "unchanged" else c.evidence


def _evidence(c: CriterionChange) -> str:
    shown = _shown(c)
    if shown is None:
        return ""
    return (f'<span class="ev ev-{_e(shown.replace(" ", "-").replace(",", ""))}"{_tip(_EVIDENCE_TIPS.get(shown))}>'
            f'{_e(_EVIDENCE_WORDS.get(shown, shown))}</span>')


def _marks(d: Diagram) -> set[str]:
    found = {n.mark.value for n in d.all_nodes() if n.mark is not Mark.UNCHANGED}
    return found | {e.mark.value for e in d.edges if e.mark is not Mark.UNCHANGED}


def _architecture(b: ArchitectureBody, refs: Refs) -> str:
    links = {c: svg.Address(f"#{p}") for c, p in refs.glossary.pages.items()}
    used: set[str] = set()
    panels = []
    for p in b.panels:
        left, right = svg.render_pair(p.before, p.after, links)
        used |= _marks(p.before) | _marks(p.after)
        if {n.id for n in p.before.nodes} != {n.id for n in p.after.nodes} and p.before.nodes and p.after.nodes:
            used.add("ghost")
        title = f"Inside {refs.component_path(p.parent)}" if p.parent else "The whole system"
        realizes = f'<div class="muted">It must {_e(_lower(p.realizes))}.</div>' if p.realizes else ""
        before = left if p.before.nodes else '<div class="empty">This part did not exist before.</div>'
        after = right if p.after.nodes else '<div class="empty">This part is removed.</div>'
        grouped: dict[tuple[ComponentId, Change], list[ComponentId]] = {}
        for o in p.outside:
            grouped.setdefault((o.component, o.change), []).append(o.target)
        outside = "".join(f'<li><b>{refs.component(c, short_name(c))}</b> '
                          f'{"now uses" if ch is Change.ADDED else "no longer uses"} '
                          f'{", ".join(refs.component(t) for t in sorted(targets))}</li>'
                          for (c, ch), targets in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1].value)))
        panels.append(
            f'<div class="card"><div class="panel-head"><h2>{title}</h2>{realizes}</div>'
            f'<div class="sides"><div class="side"><div class="cap">Before</div><div class="diagram">{before}</div></div>'
            f'<div class="side"><div class="cap">After</div><div class="diagram">{after}</div></div></div>'
            + (f'<div class="label">Uses that point outside this part</div><ul class="plain">{outside}</ul>' if outside else "")
            + "</div>")
    keys = [("added", "Added"), ("removed", "Removed"), ("changed", "Uses different parts"), ("ghost", "Not on this side")]
    legend = "".join(f'<span class="lg {k}">{label}</span>' for k, label in keys if k in used)
    rewiring = "".join(f'<li>{_badge(r.change)}{refs.component_path(r.component)} <span class="muted">{_e(r.detail)}</span></li>'
                       for r in b.rewiring)
    more = f'<p class="muted">{b.more} more parts changed. Run <code>arch diagram --diff</code> to see them.</p>' if b.more else ""
    return (_lead("These diagrams show the parts before and after the change. Each box says what the part must do. "
                  "Arrows point to the parts it uses. Approve if the new structure is right.")
            + (f'<div class="legend">{legend}</div>' if legend else "") + "".join(panels) + more
            + f'<div class="card"><h2>All changes to the structure</h2><ul class="plain">{rewiring}</ul></div>')


def _constraints(b: ConstraintsBody, refs: Refs) -> str:
    rows = []
    for c in b.constraints:
        before = "".join(refs.component(x) for x in c.scope_before)
        after = "".join(refs.component(x) for x in c.scope_after)
        scope = (f'{before} <span class="arrow">→</span> {after}'
                 if c.scope_before != c.scope_after and c.change is Change.CHANGED else after or before)
        rows.append(f'<div class="row"><div class="row-head">{_badge(c.change)}{refs.constraint(c.constraint)}</div>'
                    f'<div class="statement">{_e(c.statement.split(". ")[0].rstrip("."))}.</div>'
                    f'<div class="label">Applies to</div><div class="scope">{scope}</div>'
                    f'<div class="label">Rule</div>{_text_diff(c.rule_before, c.rule_after)}</div>')
    return (_lead("These are the rules the code must follow, and where they apply. Approve if each rule and its scope "
                  "is right.") + f'<div class="card">{"".join(rows)}</div>')


def _decision_text(text: str) -> str:
    lines = []
    for raw in text.split("\n"):
        label, _, rest = raw.removeprefix("- ").partition(": ")
        if rest:
            lines.append(f'<div class="dl"><span class="dlabel">{_e(_DECISION_LABELS.get(label, label))}</span>'
                         f'<span>{_e(rest)}</span></div>')
        elif raw.strip():
            lines.append(f"<div>{_e(raw)}</div>")
    return "".join(lines)


def _design(b: DesignBody, refs: Refs) -> str:
    rows = []
    for d in b.changes:
        solution = _text_diff(d.solution_before, d.solution_after) if d.solution_before != d.solution_after else ""
        hides = _text_diff(d.hides_before, d.hides_after) if d.hides_before != d.hides_after else ""
        decisions = "".join(f'<div class="decision"><div class="row-head">{_badge(ch)}<b>{_e(title)}</b></div>'
                            f"{_decision_text(text)}</div>" for title, ch, text in d.decisions)
        rows.append(f'<div class="row"><div class="row-head">{_badge(d.change)}{refs.component_path(d.component)}</div>'
                    f'<div class="muted">It must {_e(_lower(d.realizes))}.</div>'
                    + (f'<div class="label">Chosen solution</div>{solution}' if solution else "")
                    + (f'<div class="label">Keeps hidden</div>{hides}' if hides else "") + decisions + "</div>")
    return (_lead("These are the chosen solutions and the reasons for them. Approve if each choice is sound and its "
                  "reason is written down.") + f'<div class="card">{"".join(rows)}</div>')


_MEANING = {Compatibility.BREAKING: "Code that calls this may break.",
            Compatibility.NEEDS_REVIEW: "arch cannot tell whether callers break. Read the change.",
            Compatibility.COMPATIBLE: "Existing callers keep working."}


def _compat_badge(c: Compatibility) -> str:
    kind = {Compatibility.BREAKING: "removed", Compatibility.NEEDS_REVIEW: "changed", Compatibility.COMPATIBLE: "added"}[c]
    return f'<span class="badge b-{kind}">{_e(c.value)}</span>'


def _interfaces(b: InterfacesBody, refs: Refs) -> str:
    again: dict[str, list[str]] = {}
    for r in b.reexports:
        again.setdefault(r.reexport_of or "", []).append(r.unit)
    rows = "".join(
        f'<div class="row"><div class="row-head">{_compat_badge(p.compatibility)}{refs.interface(p.dotted)}'
        f'<span class="muted">{_e(p.type.value.capitalize())}. {_MEANING[p.compatibility]}</span></div>'
        + (f'<div class="muted small">Also re-exported by {_e(", ".join(sorted(set(again[p.dotted]))))}.</div>'
           if p.dotted in again else "")
        + f'{_text_diff(p.before, p.after)}</div>' for p in b.ports)
    return (_lead("These public interfaces changed in a way that can affect the code that calls them. Approve if each "
                  "change is intended.") + f'<div class="card">{rows}</div>')


def _code(b: CodeBody, refs: Refs) -> str:
    if b.component is not None:
        criteria = "".join(refs.criterion(c.criterion, c.verdict) for c in b.criteria) or '<span class="muted">none</span>'
        constraints = "".join(refs.constraint(ConstraintId(c.split(":")[0])) for c in b.constraints)
        serves = "".join(refs.need(n) for n in b.serves) or '<span class="muted">none</span>'
        head = (f'<div class="card component"><div class="label">Component</div><div class="big">{refs.component_path(b.component)}</div>'
                f'<div class="label">Must do</div><div class="big-fr">{_e(b.realizes)}</div>'
                + (f'<div class="label">Keeps hidden</div><div>{_e(b.hides)}</div>' if b.hides else "")
                + f'<div class="facts"><div><div class="label">Serves</div>{serves}</div>'
                f'<div><div class="label">Acceptance criteria</div>{criteria}</div></div>'
                + (f'<div class="label">Rules that apply here</div><div>{constraints}</div>' if constraints else "") + "</div>")
        lead = _lead("This is the code that changed in one component. Each change says why it was made. Approve if the "
                     "code does what its reason says.")
    else:
        head = ""
        lead = _lead("These files belong to no component in the design. Each change says why it was made. Approve if "
                     "that is intended.")
    away = "".join(
        f'<li>{_n(m.count, "change")} in <code>{_e(m.path)}</code> only {"updates" if m.count == 1 else "update"} calls to '
        f'{refs.interface(m.interface)}. {"It is" if m.count == 1 else "They are"} shown with that change on '
        f'{_link("ref", Href(f"#{_e(m.page)}"), None, m.page.removeprefix("code:"))}.</li>' for m in b.moved)
    interfaces = "".join(_interface(n, refs) for n in b.interfaces)
    tests = "".join(_file(h, refs) for h in b.tests)
    sources = "".join(_file(h, refs) for h in b.sources)
    return (lead + head
            + (f'<div class="callout plain"><ul class="plain">{away}</ul></div>' if away else "")
            + (f'<h2 class="section">Interfaces it changed <span class="muted">and the callers updated to match</span></h2>'
               f"{interfaces}" if interfaces else "")
            + (f'<h2 class="section">Tests <span class="muted">what the code should do</span></h2>{tests}' if tests else "")
            + (f'<h2 class="section">Code <span class="muted">how it does it</span></h2>{sources}' if sources else ""))


def _n(count: int, word: str) -> str:
    return f"{count} {word if count == 1 else word + 's'}"


def _interface(n: InterfaceNote, refs: Refs) -> str:
    p = n.change
    again = f'<div class="muted small">Also re-exported by {_e(", ".join(n.reexported_by))}.</div>' if n.reexported_by else ""
    callers = "".join(
        '<div class="caller"><div class="caller-head">'
        + (refs.component(f.component, short_name(f.component)) if f.component else '<span class="muted">no component</span>')
        + f' · {_file_link(f.path, refs)}</div>{_hunk(f.hunk, f.path, refs)}</div>' for f in n.callers)
    count = (f'<div class="label">{_n(len(n.callers), "caller")} updated to match</div>' if n.callers else "")
    return (f'<div class="card interface"><div class="row-head">{_compat_badge(p.compatibility)}<code>{_e(p.symbol)}</code>'
            f'<span class="muted">{_e(p.type.value.capitalize())}. {_MEANING[p.compatibility]}</span></div>{again}'
            f"{_text_diff(p.before, p.after)}{count}{callers}</div>")


_WHY_LABEL = {Why.TESTS: "Tests", Why.REALIZES: "Realizes", Why.EXERCISED: "Tested by", Why.FOLLOWS: "Follows",
              Why.NEW_COMPONENT: "New part", Why.IMPORTS: "Imports", Why.NONE: "No reason"}


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _criterion_order(cid: Text) -> tuple[str, int]:
    component, _, label = cid.partition("#")
    return component, int(label[2:]) if label[2:].isdigit() else 0


def _reason(r: Reason, refs: Refs) -> str:
    ordered = sorted(r.refs, key=_criterion_order) if r.why in (Why.TESTS, Why.REALIZES, Why.EXERCISED) else list(r.refs)
    chips = _and([refs.criterion(t, named=Named.WITH_COMPONENT) for t in ordered]) if ordered else ""
    many = len(r.refs) > 1
    if r.why is Why.TESTS:
        text = f"It tests {chips}, which this change {_e(r.detail)}."
    elif r.why is Why.REALIZES:
        text = f"It is linked to {chips}, which this change {_e(r.detail)}."
    elif r.why is Why.EXERCISED:
        how = f"calls <code>{_e(r.via)}</code>, which leads here" if r.via else "calls it"
        text = f"A test for {chips} {how}. This change {_e(r.detail)} {'those criteria' if many else 'that criterion'}."
    elif r.why is Why.FOLLOWS:
        names = _and([refs.interface(t) for t in r.refs])
        text = (f"It updates calls to {names}, which this change removed." if r.detail == "removed"
                else f"It updates calls to {names}, whose signature this change altered.")
    elif r.why is Why.IMPORTS:
        text = "It only changes imports or the names the module exports. The code that uses them says why."
    elif r.why is Why.NEW_COMPONENT:
        text = f"It is part of {refs.component(ComponentId(r.refs[0]))}, which this change adds."
    else:
        text = ("No reason given. It touches no changed criterion, follows no interface change and is not part of a "
                "new component.")
    cls = " none" if r.why is Why.NONE else ""
    return f'<div class="why{cls}"><span class="why-label">{_WHY_LABEL[r.why]}</span><span>{text}</span></div>'


def _question(q: Question) -> str:
    name = f"<code>{_e(q.name)}</code>"
    text = (f"The signature of {name} changed, but its description did not. Is the description still true?"
            if q.doubt is Doubt.STALE else
            f"{name} is part of the interface, and its name and type do not say what it is. It has no description.")
    return f'<div class="why ask"><span class="why-label">Check</span><span>{text}</span></div>'


def _hunk(v: HunkView, path: SourcePath, refs: Refs) -> str:
    color = highlight.python if path.endswith(".py") else highlight.plain
    rows = []
    for line, names in zip(v.hunk.lines, v.names):
        link = refs.editor_link(Text(path), line.new_line) if line.new_line else None
        number = f'<a href="{link}">{line.new_line}</a>' if link else (line.new_line or "")
        rows.append(f'<tr class="{line.kind.name.lower()}"><td class="ln">{line.old_line or ""}</td>'
                    f'<td class="ln">{number}</td><td class="code">{color(highlight.CodeLine(line.text), names)}</td></tr>')
    if v.enclosing is not None:
        about = f'<div class="muted">{_e(v.enclosing.summary)}</div>' if v.enclosing.summary else ""
        where = f'<div class="where">In <code class="sig">{_e(v.enclosing.signature)}</code>{about}</div>'
    else:
        where = '<div class="where">At module level</div>'
    reasons = "".join(_reason(r, refs) for r in v.reasons) + "".join(_question(q) for q in v.questions)
    return f'<div class="hunk"><div class="hunk-head">{where}{reasons}</div><table>{"".join(rows)}</table></div>'


def _file_link(path: SourcePath, refs: Refs) -> str:
    link = refs.editor_link(Text(path))
    return (f'<a class="fname" href="{link}"{_tip("Open in your editor")}>{_e(path)}</a>' if link
            else f'<span class="fname">{_e(path)}</span>')


def _file(h: Hunked, refs: Refs) -> str:
    d = h.diff
    shape = {FileShape.RENAMED: f"renamed from {_e(d.old_path)}", FileShape.ADDED: "new file",
             FileShape.DELETED: "deleted", FileShape.MODIFIED: ""}[d.shape]
    reasons = (f'<span class="reasons"{_tip("Why this file needs a close look")}>{_e(". ".join(h.risk.reasons))}.</span>'
               if h.risk and h.risk.reasons else "")
    body = "".join(_hunk(v, d.path, refs) for v in h.hunks) or '<p class="muted pad">No lines changed.</p>'
    return (f'<div class="file"><div class="file-head">{_file_link(d.path, refs)}'
            + (f'<span class="muted">{shape}</span>' if shape else "")
            + f'<span class="counts"><span class="plus">+{d.added}</span> <span class="minus">−{d.removed}</span></span>{reasons}'
            f'</div>{body}</div>')


def _batch(b: BatchBody, refs: Refs) -> str:
    rows = "".join(f'<div class="row"><div class="row-head"><span class="chip">{_e(why.value)}</span>'
                   f'<code>{_e(h.diff.path)}</code></div><details><summary class="muted">Show the change</summary>'
                   f"{_file(h, refs)}</details></div>" for h, why in b.files)
    return (_lead("These changes need no line-by-line reading. A machine checked why for each one. Approve them "
                  "together.") + f'<div class="card">{rows}</div>')

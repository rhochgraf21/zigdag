"""Each review page as HTML. Part of arch.review.page."""

from __future__ import annotations

import difflib
import html
from typing import NewType

from arch.model.ids import Text
from arch.realize.facts import Compatibility, FileShape
from arch.review.items import (
    ArchitectureBody,
    BatchBody,
    Change,
    CodeBody,
    ConstraintsBody,
    DesignBody,
    Hunked,
    IntentBody,
    InterfacesBody,
    OverviewBody,
    Readiness,
    ReviewItem,
)
from arch.review.page import highlight
from arch.view.diagram import svg
from arch.view.render import Count

PageHtml = NewType("PageHtml", str)  # one page of the deck


def _e(text: object) -> str:
    return html.escape(str(text)) if text is not None else ""


def _badge(change: Change) -> str:
    return f'<span class="badge b-{change.value}">{_e(change.value)}</span>'


def _chips(values, cls: str = "") -> str:
    return "".join(f'<span class="chip {cls}">{_e(v)}</span>' for v in values)


def _path(cid: str) -> str:
    parts = cid.split(".")
    return '<span class="crumbs">' + '<span class="sep">›</span>'.join(f"<span>{_e(p)}</span>" for p in parts) + "</span>"


def _text_diff(before: str | None, after: str | None) -> str:
    """Before and after, side by side, with changed lines marked."""
    a, b = (before or "").split("\n"), (after or "").split("\n")
    if before is None:
        return f'<div class="tdiff single"><div class="col after">{"".join(f"<div class=add>{_e(x)}</div>" for x in b)}</div></div>'
    if after is None:
        return f'<div class="tdiff single"><div class="col before">{"".join(f"<div class=del>{_e(x)}</div>" for x in a)}</div></div>'
    left, right = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        for x in a[i1:i2]:
            left.append(f'<div class="{"same" if op == "equal" else "del"}">{_e(x)}</div>')
        for x in b[j1:j2]:
            right.append(f'<div class="{"same" if op == "equal" else "add"}">{_e(x)}</div>')
    return (f'<div class="tdiff"><div class="col before"><div class="cap">before</div>{"".join(left)}</div>'
            f'<div class="col after"><div class="cap">after</div>{"".join(right)}</div></div>')


def page_html(item: ReviewItem, number: Count, total: Count, note: Text | None) -> PageHtml:
    body = item.body
    renderers = {OverviewBody: _overview, IntentBody: _intent, ArchitectureBody: _architecture,
                 ConstraintsBody: _constraints, DesignBody: _design, InterfacesBody: _interfaces, CodeBody: _code,
                 BatchBody: _batch}
    inner = renderers[type(body)](body)
    note_html = f'<aside class="note"><div class="note-head">Author\'s note</div>{_e(note)}</aside>' if note else ""
    return PageHtml(f'<section class="page" id="{_e(item.id)}" data-id="{_e(item.id)}" hidden>'
            f'<div class="page-head"><div class="eyebrow">{_e(item.stage.value)} · page {number} of {total}</div>'
            f'<h1>{_e(item.title)}</h1><div class="meta"><span class="pill risk-{item.risk.value}">{_e(item.risk.value)} risk</span>'
            f'<span class="pill state" data-state></span></div></div>{note_html}{inner}</section>')


def _overview(b: OverviewBody) -> str:
    ready = b.readiness is Readiness.READY
    tallies = "".join(f'<div class="stat"><div class="num">{t.count}</div><div class="lbl">{_e(t.label)}</div></div>'
                      for t in b.tallies if t.count)
    lines = f'<div class="stat"><div class="num"><span class="plus">+{b.lines_added}</span> <span class="minus">−{b.lines_removed}</span></div><div class="lbl">lines</div></div>'
    findings = "".join(f"<li>{_e(x)}</li>" for x in b.new_findings)
    tests = "".join(f"<li>{_e(x)}</li>" for x in b.failing_tests)
    status = ('<div class="callout ok"><b>Machine checks pass.</b> Boundaries, effects, typed interfaces and linked tests '
              'have nothing against this change, so you can spend your attention on intent and design.</div>' if ready else
              '<div class="callout bad"><b>Not ready.</b> Machines found problems. Send it back, or review knowing these are open.</div>')
    return (f'{status}<div class="stats">{tallies}{lines}</div>'
            + (f'<div class="card"><h2>New blocking findings</h2><ul>{findings}</ul></div>' if findings else "")
            + (f'<div class="card"><h2>Failing tests</h2><ul>{tests}</ul></div>' if tests else "")
            + '<p class="hint">Use <kbd>←</kbd> <kbd>→</kbd> to flip pages, <kbd>A</kbd> to approve a page, <kbd>R</kbd> to request changes.</p>')


def _intent(b: IntentBody) -> str:
    needs = "".join(
        f'<div class="row"><div class="row-head">{_badge(n.change)}<code>{_e(n.need)}</code>'
        f'{f"<span class=muted>for {_e(n.stakeholder)}</span>" if n.stakeholder else ""}</div>'
        f'{_text_diff(n.before, n.after) if n.change is not Change.UNCHANGED else ""}</div>' for n in b.needs)
    reqs = []
    for r in b.requirements:
        criteria = "".join(
            f'<li class="crit c-{c.change.value}">{_badge(c.change) if c.change is not Change.UNCHANGED else ""}'
            f'<code>{_e(c.label)}</code> <span class="ctext">{_e(c.after or c.before)}</span>'
            f'<span class="ev ev-{_e(c.evidence.replace(" ", "-").replace(",", ""))}">{_e(c.evidence)}</span></li>'
            for c in r.criteria if c.change is not Change.UNCHANGED)
        moved = f'<span class="muted">moved from <code>{_e(r.moved_from)}</code></span>' if r.moved_from else ""
        fr = _text_diff(r.before, r.after) if r.before != r.after else f'<div class="fr">{_e(r.after)}</div>'
        reqs.append(f'<div class="row"><div class="row-head">{_badge(r.change)}{_path(r.component)}{moved}</div>'
                    f'<div class="label">realizes</div>{fr}'
                    f'<div class="serves">serves {_chips(r.serves, "need") or "<span class=muted>no need named</span>"}</div>'
                    + (f'<ul class="crits">{criteria}</ul>' if criteria else "") + "</div>")
    return ((f'<div class="card"><h2>Customer needs</h2>{needs}</div>' if needs else "")
            + (f'<div class="card"><h2>Functional requirements</h2>{"".join(reqs)}</div>' if reqs else ""))


def _architecture(b: ArchitectureBody) -> str:
    panels = []
    for p in b.panels:
        left, right = svg.render_pair(p.before, p.after)
        label = f"inside {_path(p.parent)}" if p.parent else "the whole system"
        realizes = f'<div class="muted">{_e(p.realizes)}</div>' if p.realizes else ""
        before = left if p.before.nodes else '<div class="empty">did not exist</div>'
        after = right if p.after.nodes else '<div class="empty">removed</div>'
        panels.append(f'<div class="card"><div class="panel-head"><h2>{label}</h2>{realizes}</div>'
                      f'<div class="pair"><div><div class="cap">before</div><div class="diagram">{before}</div></div>'
                      f'<div><div class="cap">after</div><div class="diagram">{after}</div></div></div></div>')
    legend = ('<div class="legend"><span class="lg added">added</span><span class="lg removed">removed</span>'
              '<span class="lg changed">rewired</span><span class="lg ghost">not on this side</span>'
              '<span class="muted">Each box shows what the part realizes; arrows point from a part to what it uses.</span></div>')
    rewiring = "".join(f'<li>{_badge(r.change)}{_path(r.component)} <span class="muted">{_e(r.detail)}</span></li>'
                       for r in b.rewiring)
    more = f'<p class="muted">{b.more} more parts changed; see <code>arch diagram --diff</code>.</p>' if b.more else ""
    return legend + "".join(panels) + more + f'<div class="card"><h2>What changed</h2><ul class="plain">{rewiring}</ul></div>'


def _constraints(b: ConstraintsBody) -> str:
    rows = []
    for c in b.constraints:
        scope_changed = c.scope_before != c.scope_after and c.change is Change.CHANGED
        scope = (f'{_chips(c.scope_before, "scope")} <span class="arrow">→</span> {_chips(c.scope_after, "scope")}'
                 if scope_changed else _chips(c.scope_after or c.scope_before, "scope"))
        rows.append(f'<div class="row"><div class="row-head">{_badge(c.change)}<code>{_e(c.constraint)}</code></div>'
                    f'<div class="statement">{_e(c.statement.split(". ")[0])}.</div>'
                    f'<div class="label">applies to</div><div>{scope}</div>'
                    f'<div class="label">rule</div>{_text_diff(c.rule_before, c.rule_after)}</div>')
    return f'<div class="card">{"".join(rows)}</div>'


def _decision_text(text: str) -> str:
    lines = []
    for raw in text.split("\n"):
        label, _, rest = raw.removeprefix("- ").partition(": ")
        lines.append(f'<div class="dl"><span class="dlabel">{_e(label)}</span> {_e(rest)}</div>' if rest else f"<div>{_e(raw)}</div>")
    return "".join(lines)


def _design(b: DesignBody) -> str:
    rows = []
    for d in b.changes:
        solution = _text_diff(d.solution_before, d.solution_after) if d.solution_before != d.solution_after else ""
        hides = _text_diff(d.hides_before, d.hides_after) if d.hides_before != d.hides_after else ""
        decisions = "".join(f'<div class="decision"><div class="row-head">{_badge(ch)}<b>{_e(t)}</b></div>{_decision_text(x)}</div>'
                            for t, ch, x in d.decisions)
        rows.append(f'<div class="row"><div class="row-head">{_badge(d.change)}{_path(d.component)}</div>'
                    f'<div class="fr muted">{_e(d.realizes)}</div>'
                    + (f'<div class="label">solution</div>{solution}' if solution else "")
                    + (f'<div class="label">hides</div>{hides}' if hides else "") + decisions + "</div>")
    return f'<div class="card">{"".join(rows)}</div>'


def _interfaces(b: InterfacesBody) -> str:
    rows = "".join(
        f'<div class="row"><div class="row-head"><span class="badge b-{"removed" if p.compatibility is Compatibility.BREAKING else "changed"}">'
        f'{_e(p.compatibility.value)}</span><code>{_e(p.unit)}.{_e(p.symbol)}</code><span class="muted">{_e(p.type.value)}</span></div>'
        f'{_text_diff(p.before, p.after)}</div>' for p in b.ports)
    return f'<div class="card">{rows}</div>'


def _code(b: CodeBody) -> str:
    if b.component is not None:
        criteria = "".join(f'<span class="chip crit-chip ev-{_e(c.verdict.replace(" ", "-").replace(",", ""))}" '
                           f'title="{_e(c.verdict)}">{_e(c.criterion.partition("#")[2])}</span>' for c in b.criteria)
        constraints = "".join(f"<li>{_e(c)}</li>" for c in b.constraints)
        head = (f'<div class="card component"><div class="eyebrow">component</div><div class="big">{_path(b.component)}</div>'
                f'<div class="label">realizes</div><div class="fr big-fr">{_e(b.realizes)}</div>'
                + (f'<div class="label">hides</div><div>{_e(b.hides)}</div>' if b.hides else "")
                + f'<div class="facts"><div><div class="label">serves</div>{_chips(b.serves, "need") or "—"}</div>'
                f'<div><div class="label">criteria</div>{criteria or "—"}</div></div>'
                + (f'<details><summary>{len(b.constraints)} constraints in force</summary><ul>{constraints}</ul></details>'
                   if constraints else "") + "</div>")
    else:
        head = '<div class="callout warn">These files belong to no component in the design.</div>'
    tests = "".join(_file(h) for h in b.tests)
    sources = "".join(_file(h) for h in b.sources)
    return (head + (f'<h2 class="section">Tests <span class="muted">what it should do</span></h2>{tests}' if tests else "")
            + (f'<h2 class="section">Code <span class="muted">how it does it</span></h2>{sources}' if sources else ""))


def _file(h: Hunked) -> str:
    d = h.diff
    shape = {FileShape.RENAMED: f"renamed from {_e(d.old_path)}", FileShape.ADDED: "new file",
             FileShape.DELETED: "deleted", FileShape.MODIFIED: ""}[d.shape]
    reasons = f'<span class="reasons">{_e(" · ".join(h.risk.reasons))}</span>' if h.risk and h.risk.reasons else ""
    color = highlight.python if d.path.endswith(".py") else highlight.plain
    hunks = []
    for hunk, symbol, proves in zip(d.hunks, h.symbols, h.proves):
        rows = "".join(
            f'<tr class="{l.kind.name.lower()}"><td class="ln">{l.old_line or ""}</td><td class="ln">{l.new_line or ""}</td>'
            f'<td class="code">{color(highlight.CodeLine(l.text))}</td></tr>' for l in hunk.lines)
        where = f"in <code>{_e(symbol)}</code>" if symbol else (_e(hunk.header) or "")
        proof = "".join(f'<span class="chip crit-chip">{_e(t.partition("#")[2] or t)}</span>' for t in proves)
        hunks.append(f'<div class="hunk"><div class="hunk-head">{where}{" · proves " + proof if proof else ""}</div>'
                     f'<table>{rows}</table></div>')
    body = "".join(hunks) or '<p class="muted pad">no line changes</p>'
    return (f'<details class="file" open><summary><span class="fname">{_e(d.path)}</span>'
            + (f'<span class="muted">{shape}</span>' if shape else "")
            + f'<span class="counts"><span class="plus">+{d.added}</span> <span class="minus">−{d.removed}</span></span>{reasons}'
            f'</summary>{body}</details>')


def _batch(b: BatchBody) -> str:
    rows = "".join(f'<div class="row"><div class="row-head"><span class="chip">{_e(why.value)}</span>'
                   f'<code>{_e(h.diff.path)}</code></div><details><summary class="muted">show</summary>{_file(h)}</details></div>'
                   for h, why in b.files)
    return ('<div class="callout ok">Machines verified these need no line-by-line reading: '
            f'approve them together.</div><div class="card">{rows}</div>')

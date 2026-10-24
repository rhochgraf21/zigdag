"""The step-by-step review page: one item at a time, keyboard first, verdicts saved as you go.

Realizes arch.review.page. Every item is rendered to HTML here, in Python, so the page is deterministic
and testable; the small script only shows one item at a time, handles keys, and posts verdicts to the
local server. No external assets: it works offline.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import NewType

from arch.model.ids import Text
from arch.realize.facts import Compatibility, DiffLineKind, FileShape
from arch.review.items import (
    BatchBody,
    CodeBody,
    Hunked,
    NodeBody,
    PortBody,
    Readiness,
    ReadinessBody,
    ReviewItem,
    Stage,
    StructureBody,
)
from arch.review.session import Category, Decision, ItemState, Session, Weight
from arch.view.diagram import svg
from arch.view.render import JsonValue, Markdown

HtmlText = NewType("HtmlText", str)


@dataclass(frozen=True)
class Board:
    """The review as the page shows it: items and the verdicts given so far."""

    items: tuple[ReviewItem, ...]
    session: Session
    title: Text

    def to_html(self) -> HtmlText:
        return render(self.items, self.session, self.title)

    def to_json(self) -> JsonValue:
        return state(self.items, self.session)

    def to_markdown(self) -> Markdown:
        done, total = self.session.progress(self.items)
        return Markdown(f"{self.title}: {done} of {total} items decided")

_STAGE_TITLES = {Stage.READINESS: "Ready?", Stage.INTENT: "Intent", Stage.DESIGN: "Design", Stage.STRUCTURE: "Structure",
                 Stage.CONTRACTS: "Contracts", Stage.CODE: "Code", Stage.BATCH: "Mechanical"}


def _e(text: object) -> str:
    return html.escape(str(text)) if text is not None else ""


def state(items: tuple[ReviewItem, ...], session: Session) -> JsonValue:
    """What the page needs to know about verdicts; also the server's API answer."""
    done, total = session.progress(items)
    return {
        "progress": {"done": done, "total": total},
        "items": [{"id": i.id, "digest": i.digest, "stage": i.stage.value, "title": i.title, "risk": i.risk.value,
                   "state": session.state(i, items).value,
                   "verdict": _verdict_json(session, i), "note": session.notes.get(i.id)} for i in items],
    }


def _verdict_json(session: Session, item: ReviewItem) -> JsonValue:
    v = session.verdicts.get(item.id)
    if v is None:
        return None
    return {"decision": v.decision.value, "comment": v.comment, "category": v.category.value, "weight": v.weight.value}


def render(items: tuple[ReviewItem, ...], session: Session, title: Text) -> HtmlText:
    sections = "\n".join(_item(i, session, items) for i in items)
    data = json.dumps(state(items, session)).replace("</", "<\\/")
    options = {
        "decisions": [d.value for d in Decision], "categories": [c.value for c in Category],
        "weights": [w.value for w in Weight], "states": [s.value for s in ItemState],
    }
    page = _TEMPLATE.replace("{{TITLE}}", _e(title)).replace("{{SECTIONS}}", sections)
    page = page.replace("{{STATE}}", data).replace("{{OPTIONS}}", json.dumps(options))
    return HtmlText(page.replace("{{CSS}}", _CSS).replace("{{JS}}", _JS))


def _item(item: ReviewItem, session: Session, items: tuple[ReviewItem, ...]) -> str:
    body = item.body
    if isinstance(body, ReadinessBody):
        inner = _readiness(body)
    elif isinstance(body, NodeBody):
        inner = _node(body)
    elif isinstance(body, StructureBody):
        inner = _structure(body)
    elif isinstance(body, PortBody):
        inner = _port(body)
    elif isinstance(body, CodeBody):
        inner = _code(body)
    elif isinstance(body, BatchBody):
        inner = "".join(f'<p class="why">{_e(why.value)}</p>{_file(h)}' for h, why in body.files)
    else:
        inner = ""
    blockers = "".join(f'<li data-goto="{_e(b)}">{_e(b)}</li>' for b in item.blocked_by)
    note = session.notes.get(item.id)
    return (f'<section class="item" id="{_e(item.id)}" data-id="{_e(item.id)}" hidden>'
            f'<header><span class="stage">{_e(_STAGE_TITLES[item.stage])}</span>'
            f'<h1>{_e(item.title)}</h1><span class="risk risk-{item.risk.value}">{_e(item.risk.value)} risk</span>'
            f'<span class="state" data-state></span></header>'
            + (f'<aside class="note"><b>Author\'s note</b> {_e(note)}</aside>' if note else "")
            + (f'<div class="blockers">Depends on: <ul>{blockers}</ul></div>' if blockers else "")
            + f'<div class="body">{inner}</div></section>')


def _readiness(b: ReadinessBody) -> str:
    ok = b.state is Readiness.READY
    rows = "".join(f"<li>{_e(x)}</li>" for x in b.new_findings) or ("<li>none</li>" if ok else "")
    tests = "".join(f"<li>{_e(x)}</li>" for x in b.failing_tests)
    return (f'<p class="verdict-{"ok" if ok else "bad"}">{"Machines have nothing against this change." if ok else "Machines found problems. Review anyway only if you mean to."}</p>'
            f"<p>Blocking findings now: <b>{b.blocking}</b></p><h2>New since the base</h2><ul>{rows}</ul>"
            + (f"<h2>Failing tests</h2><ul>{tests}</ul>" if tests else ""))


def _delta(field: str, before: object, after: object) -> str:
    return (f'<div class="delta"><div class="field">{_e(field)}</div>'
            f'<div class="before">{_e(before) or "<i>none</i>"}</div><div class="after">{_e(after) or "<i>none</i>"}</div></div>')


def _node(b: NodeBody) -> str:
    c = b.change
    head = f'<p class="kind">{_e(c.kind.value)} <code>{_e(c.ident)}</code> {_e(c.type.value)}' + (
        f' (from <code>{_e(c.moved_from)}</code>)' if c.moved_from else "") + "</p>"
    context = f'<p class="context">Realizes: {_e(b.context)}</p>' if b.context else ""
    fields = "".join(_delta(f.field, f.before, f.after) for f in c.fields)
    return head + context + (f'<div class="deltas"><div class="cols"><span></span><span>before</span><span>after</span></div>{fields}</div>'
                             if fields else "")


def _structure(b: StructureBody) -> str:
    changes = "".join(f"<li><code>{_e(c.ident)}</code> {_e(c.type.value)}"
                      + "".join(f" · {_e(f.field)}: {_e(f.before)} → {_e(f.after)}" for f in c.fields if f.change_class.value == "structure")
                      + "</li>" for c in b.changes)
    return f'<div class="diagram">{svg.render(b.diagram)}</div><ul class="structure">{changes}</ul>'


def _port(b: PortBody) -> str:
    p = b.change
    meaning = {Compatibility.BREAKING: "Callers written against the old version can break.",
               Compatibility.NEEDS_REVIEW: "arch cannot tell whether callers are affected; read the change.",
               Compatibility.COMPATIBLE: "Existing callers keep working."}[p.compatibility]
    return (f"<p><code>{_e(p.unit)}.{_e(p.symbol)}</code>: {_e(p.type.value)}, <b>{_e(p.compatibility.value)}</b>. {_e(meaning)}</p>"
            + _delta("signature" if p.type.value != "contract changed" else "contracts", p.before, p.after))


def _code(b: CodeBody) -> str:
    card = ""
    if b.component is not None:
        crit = "".join(f'<li class="ev-{_e(c.verdict.replace(" ", "-").replace(",", ""))}"><code>{_e(c.criterion.partition("#")[2])}</code> '
                       f"{_e(c.verdict)}</li>" for c in b.criteria)
        cons = "".join(f"<li>{_e(c)}</li>" for c in b.constraints)
        card = (f'<div class="card"><p><b>Realizes</b> {_e(b.realizes)}</p>'
                + (f"<p><b>Hides</b> {_e(b.hides)}</p>" if b.hides else "")
                + (f"<details><summary>Constraints in force ({len(b.constraints)})</summary><ul>{cons}</ul></details>" if cons else "")
                + (f"<details open><summary>Criteria and their evidence</summary><ul>{crit}</ul></details>" if crit else "")
                + "</div>")
    tests = "".join(_file(h) for h in b.tests)
    sources = "".join(_file(h) for h in b.sources)
    return (card + (f'<h2>Tests <span class="hint">what it should do</span></h2>{tests}' if tests else "")
            + (f'<h2>Code <span class="hint">how it does it</span></h2>{sources}' if sources else ""))


def _file(h: Hunked) -> str:
    d = h.diff
    shape = {FileShape.RENAMED: f"renamed from {_e(d.old_path)}" + (f" ({d.similarity}% similar)" if d.similarity else ""),
             FileShape.ADDED: "new file", FileShape.DELETED: "deleted", FileShape.MODIFIED: ""}[d.shape]
    why = f'<span class="reasons">{_e("; ".join(h.risk.reasons))}</span>' if h.risk and h.risk.reasons else ""
    hunks = []
    for hunk, symbol in zip(d.hunks, h.symbols):
        rows = "".join(
            f'<tr class="{l.kind.name.lower()}"><td class="ln">{l.old_line or ""}</td><td class="ln">{l.new_line or ""}</td>'
            f'<td class="sign">{_e(l.kind.value if l.kind is not DiffLineKind.CONTEXT else "")}</td><td class="code">{_e(l.text)}</td></tr>'
            for l in hunk.lines)
        label = f"in <code>{_e(symbol)}</code>" if symbol else f"@@ {_e(hunk.header)}" if hunk.header else ""
        hunks.append(f'<div class="hunk"><div class="hunk-head">{label}</div><table>{rows}</table></div>')
    body = "".join(hunks) if hunks else '<p class="hint">no line changes</p>'
    return (f'<details class="file" open><summary><code>{_e(d.path)}</code> <span class="shape">{shape}</span>'
            f' <span class="counts">+{d.added} −{d.removed}</span> {why}</summary>{body}</details>')


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title><style>{{CSS}}</style></head>
<body>
<nav id="nav"><div class="top"><b>arch review</b><span id="progress"></span></div><div id="list"></div>
<p class="keys"><kbd>j</kbd>/<kbd>k</kbd> move · <kbd>n</kbd> next open · <kbd>a</kbd> approve · <kbd>r</kbd> request changes · <kbd>c</kbd> comment · <kbd>R</kbd> refresh</p></nav>
<main id="main">{{SECTIONS}}
<form id="verdict" autocomplete="off">
  <div class="buttons"><button type="button" data-decision="approved" class="approve">Approve <kbd>a</kbd></button>
  <button type="button" data-decision="changes requested" class="request">Request changes <kbd>r</kbd></button>
  <button type="button" data-decision="commented">Comment <kbd>c</kbd></button></div>
  <div id="details" hidden><select id="category"></select><select id="weight"></select>
  <textarea id="comment" rows="3" placeholder="What should change, and why? (Ctrl+Enter to send, Esc to cancel)"></textarea>
  <button type="button" id="send">Send</button></div>
</form></main>
<script id="state" type="application/json">{{STATE}}</script>
<script id="options" type="application/json">{{OPTIONS}}</script>
<script>{{JS}}</script></body></html>"""

_CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;--panel:#f2f2ef;--add:#e6f4ea;--add-fg:#1e6b34;
--del:#fde8e6;--del-fg:#a3261c;--accent:#1a5fd6;--warn:#b06000;--ok:#1e8e3e;--bad:#c5221f;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#ececec;--muted:#9a9aa0;--line:#2c2c30;--panel:#1f1f22;
--add:#14301d;--add-fg:#8fd3a3;--del:#3a1714;--del-fg:#f2a49c;--accent:#7aa7ff;--warn:#f0b35a;--ok:#5fca7d;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;display:grid;grid-template-columns:300px 1fr;min-height:100vh;background:var(--bg);
color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
nav{border-right:1px solid var(--line);padding:14px;position:sticky;top:0;height:100vh;overflow:auto;background:var(--panel)}
nav .top{display:flex;justify-content:space-between;margin-bottom:10px}#progress{color:var(--muted)}
.group{margin:12px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.entry{display:flex;gap:8px;align-items:baseline;padding:4px 6px;border-radius:6px;cursor:pointer;font-size:13.5px}
.entry:hover{background:var(--line)}.entry.current{outline:2px solid var(--accent)}
.dot{width:9px;height:9px;border-radius:50%;flex:none;border:1.5px solid var(--muted)}
.dot.approved{background:var(--ok);border-color:var(--ok)}.dot.changes-requested{background:var(--bad);border-color:var(--bad)}
.dot.commented{background:var(--accent);border-color:var(--accent)}.dot.changed-since-your-verdict{border-color:var(--warn);border-style:dashed}
.dot.blocked-by-a-change-request-upstream{background:var(--line)}
main{padding:22px 32px 160px;max-width:1150px}header{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline}
header h1{font-size:21px;margin:0;flex-basis:100%;order:2}.stage{color:var(--muted);text-transform:uppercase;font-size:12px;letter-spacing:.06em}
.risk{font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid var(--line)}.risk-high{color:var(--bad)}.risk-medium{color:var(--warn)}
.state{font-size:12px;color:var(--muted)}.note{margin:14px 0;padding:10px 14px;border-left:3px solid var(--accent);background:var(--panel)}
.blockers{color:var(--muted);font-size:13px}.blockers ul{display:inline;padding:0}.blockers li{display:inline;margin-right:8px;cursor:pointer;text-decoration:underline}
.card{background:var(--panel);border-radius:8px;padding:10px 16px;margin:14px 0}.card p{margin:6px 0}
.deltas .cols,.delta{display:grid;grid-template-columns:160px 1fr 1fr;gap:10px}.deltas .cols{color:var(--muted);font-size:12px}
.delta{padding:8px 0;border-top:1px solid var(--line)}.delta .before{background:var(--del);color:var(--del-fg);padding:6px 8px;border-radius:5px;white-space:pre-wrap}
.delta .after{background:var(--add);color:var(--add-fg);padding:6px 8px;border-radius:5px;white-space:pre-wrap}.field{font-family:ui-monospace,Menlo,monospace;font-size:13px}
.file{border:1px solid var(--line);border-radius:8px;margin:12px 0;overflow:hidden}.file>summary{padding:8px 12px;background:var(--panel);cursor:pointer}
.counts{color:var(--muted);font-size:13px}.reasons{color:var(--warn);font-size:12.5px}.shape{color:var(--muted);font-size:13px}
.hunk-head{padding:4px 12px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
td{padding:0 8px;vertical-align:top}td.ln{color:var(--muted);text-align:right;width:44px;user-select:none}td.sign{width:14px;user-select:none}
td.code{white-space:pre-wrap;word-break:break-word}tr.added{background:var(--add)}tr.added td.code,tr.added td.sign{color:var(--add-fg)}
tr.removed{background:var(--del)}tr.removed td.code,tr.removed td.sign{color:var(--del-fg)}
h2{font-size:15px;margin:22px 0 4px}.hint{color:var(--muted);font-weight:normal;font-size:13px}
.diagram{overflow:auto;padding:8px;background:var(--panel);border-radius:8px}
.arch-diagram .node rect{fill:var(--bg);stroke:var(--muted);stroke-width:1.2}.arch-diagram text{fill:var(--fg);font:12.5px ui-monospace,Menlo,monospace}
.arch-diagram .node.added rect{fill:var(--add);stroke:var(--ok);stroke-width:2}.arch-diagram .node.removed rect{fill:var(--del);stroke:var(--bad);stroke-dasharray:4 3}
.arch-diagram .node.changed rect{stroke:var(--accent);stroke-width:2}.arch-diagram .edge{fill:none;stroke:var(--muted);stroke-width:1.3}
.arch-diagram .edge.added{stroke:var(--ok);stroke-width:2.2}.arch-diagram .edge.removed{stroke:var(--bad);stroke-dasharray:5 4}
.arch-diagram .edge.undeclared{stroke:var(--bad)}.arch-diagram .edge.hidden{stroke:var(--warn);stroke-dasharray:4 3}.arch-diagram .arrowhead{fill:var(--muted)}
.verdict-ok{color:var(--ok)}.verdict-bad{color:var(--bad)}li.ev-failed{color:var(--bad)}li.ev-passed{color:var(--ok)}li.ev-no-evidence{color:var(--warn)}
#verdict{position:fixed;bottom:0;left:300px;right:0;background:var(--bg);border-top:1px solid var(--line);padding:12px 32px}
#verdict .buttons{display:flex;gap:10px}button{font:inherit;padding:6px 14px;border-radius:7px;border:1px solid var(--line);background:var(--panel);color:var(--fg);cursor:pointer}
button.approve{border-color:var(--ok)}button.request{border-color:var(--bad)}#details{display:grid;grid-template-columns:150px 120px 1fr auto;gap:8px;margin-top:10px}
textarea,select{font:inherit;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px}
kbd{font:11px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:0 4px;color:var(--muted)}.keys{font-size:12px;color:var(--muted)}
@media (max-width:820px){body{grid-template-columns:1fr}nav{position:static;height:auto}#verdict{left:0}.deltas .cols,.delta{grid-template-columns:1fr}}
"""

_JS = r"""
const STATE = JSON.parse(document.getElementById('state').textContent);
const OPT = JSON.parse(document.getElementById('options').textContent);
const STAGES = {readiness:'Ready?', intent:'Intent', design:'Design', structure:'Structure', contracts:'Contracts', code:'Code', batch:'Mechanical'};
let items = STATE.items, current = 0, pending = null;
const $ = s => document.querySelector(s);
const slug = s => s.replace(/[^a-z]+/g, '-');
function fill(sel, values) { $(sel).innerHTML = values.map(v => `<option>${v}</option>`).join(''); }
fill('#category', OPT.categories); fill('#weight', OPT.weights);
function drawList() {
  let html = '', stage = '';
  items.forEach((it, i) => {
    if (it.stage !== stage) { stage = it.stage; html += `<div class="group">${STAGES[stage]}</div>`; }
    html += `<div class="entry${i === current ? ' current' : ''}" data-i="${i}"><span class="dot ${slug(it.state)}"></span><span>${it.title.replace(/</g,'&lt;')}</span></div>`;
  });
  $('#list').innerHTML = html;
  $('#progress').textContent = `${STATE.progress.done} / ${STATE.progress.total}`;
  document.querySelectorAll('.entry').forEach(e => e.onclick = () => show(+e.dataset.i));
}
function show(i) {
  current = Math.max(0, Math.min(items.length - 1, i));
  document.querySelectorAll('section.item').forEach(s => s.hidden = s.dataset.id !== items[current].id);
  const sec = document.getElementById(items[current].id);
  sec.querySelector('[data-state]').textContent = items[current].state;
  history.replaceState(null, '', '#' + encodeURIComponent(items[current].id));
  closeDetails(); drawList(); window.scrollTo(0, 0);
}
function nextOpen() {
  for (let k = 1; k <= items.length; k++) {
    const i = (current + k) % items.length;
    if (['unreviewed', 'changed since your verdict'].includes(items[i].state)) return show(i);
  }
}
function openDetails(decision) {
  pending = decision; $('#details').hidden = false;
  $('#category').value = decision === 'changes requested' ? 'bug' : 'other';
  $('#weight').value = decision === 'changes requested' ? 'blocking' : 'nit';
  $('#comment').focus();
}
function closeDetails() { pending = null; $('#details').hidden = true; $('#comment').value = ''; }
async function send(decision, comment) {
  const it = items[current];
  const res = await fetch('/api/verdict', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({item: it.id, digest: it.digest, decision, comment: comment || null,
                          category: $('#category').value, weight: $('#weight').value})});
  if (!res.ok) { alert(await res.text()); return; }
  const next = await res.json(); items = next.items; STATE.progress = next.progress;
  closeDetails(); nextOpen(); drawList();
}
document.querySelectorAll('#verdict [data-decision]').forEach(b => b.onclick = () =>
  b.dataset.decision === 'approved' ? send('approved') : openDetails(b.dataset.decision));
$('#send').onclick = () => send(pending, $('#comment').value);
document.querySelectorAll('[data-goto]').forEach(e => e.onclick = () => show(items.findIndex(x => x.id === e.dataset.goto)));
document.addEventListener('keydown', ev => {
  if (ev.target.matches('textarea')) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) send(pending, $('#comment').value);
    if (ev.key === 'Escape') closeDetails();
    return;
  }
  if (ev.target.matches('select')) return;
  const k = ev.key;
  if (k === 'j') show(current + 1); else if (k === 'k') show(current - 1); else if (k === 'n') nextOpen();
  else if (k === 'a') send('approved'); else if (k === 'r') openDetails('changes requested'); else if (k === 'c') openDetails('commented');
  else if (k === 'R') fetch('/api/rebuild', {method: 'POST'}).then(() => location.reload());
  else return;
  ev.preventDefault();
});
const start = items.findIndex(x => '#' + encodeURIComponent(x.id) === location.hash);
show(start >= 0 ? start : 0);
"""

"""The page's markup, design system and behaviour. Part of arch.review.page; no external assets."""

from __future__ import annotations

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title><style>{{CSS}}</style></head>
<body>
<header class="topbar">
  <div class="brand"><span class="logo">◆</span><div><div class="product">arch review</div><div class="sub">{{TITLE}}</div></div></div>
  <nav id="stepper" aria-label="pages"></nav>
  <div id="progress" class="progress"></div>
</header>
<main id="deck">
{{PAGES}}
<section class="page" id="__finish" data-id="__finish" hidden>
  <div class="page-head"><div class="eyebrow">finish</div><h1 id="finish-title"></h1></div>
  <div id="finish-body"></div>
</section>
</main>
<footer class="actionbar">
  <button class="nav" id="prev" title="Previous page (←)">← <span>Previous</span></button>
  <div class="verdicts">
    <button class="approve" data-decision="approved">Approve <kbd>A</kbd></button>
    <button class="request" data-decision="changes requested">Request changes <kbd>R</kbd></button>
    <button class="comment" data-decision="commented">Comment <kbd>C</kbd></button>
  </div>
  <button class="nav" id="next" title="Next page (→)"><span>Next</span> →</button>
  <div id="drawer" hidden>
    <div class="drawer-row"><label>Kind <select id="category"></select></label><label>Weight <select id="weight"></select></label>
    <span class="muted">Ctrl+Enter to send · Esc to cancel</span></div>
    <textarea id="comment" rows="3" placeholder="What should change, and why?"></textarea>
    <div class="drawer-row end"><button id="cancel">Cancel</button><button id="send" class="primary">Send</button></div>
  </div>
</footer>
<script id="state" type="application/json">{{STATE}}</script>
<script id="options" type="application/json">{{OPTIONS}}</script>
<script>{{JS}}</script></body></html>"""

CSS = """
:root{
  --bg:#f6f6f3;--surface:#ffffff;--surface-2:#fafaf8;--border:#e6e4de;--border-strong:#d6d3cb;
  --text:#18181b;--muted:#71717a;--faint:#a1a1aa;--accent:#4f46e5;--accent-soft:#eef2ff;
  --add:#15803d;--add-bg:#ecfdf3;--add-line:#dcfce7;--del:#b91c1c;--del-bg:#fef2f2;--del-line:#fee2e2;
  --chg:#b45309;--chg-bg:#fffbeb;--mov:#7c3aed;--mov-bg:#f5f3ff;
  --shadow:0 1px 2px rgba(0,0,0,.04),0 4px 16px rgba(0,0,0,.04);
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --t-kw:#7c3aed;--t-str:#047857;--t-com:#8a8a93;--t-num:#b45309;--t-def:#1d4ed8;--t-dec:#be185d;--t-const:#c2410c;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f0f12;--surface:#17171b;--surface-2:#1c1c21;--border:#2a2a31;--border-strong:#3a3a42;
  --text:#ececf1;--muted:#9b9ba6;--faint:#6b6b75;--accent:#8b85ff;--accent-soft:#1f1d3a;
  --add:#4ade80;--add-bg:#0f2a1b;--add-line:#123321;--del:#f87171;--del-bg:#2c1214;--del-line:#3a1518;
  --chg:#fbbf24;--chg-bg:#2a2210;--mov:#a78bfa;--mov-bg:#221b38;--shadow:none;
  --t-kw:#c4b5fd;--t-str:#86efac;--t-com:#6b6b75;--t-num:#fcd34d;--t-def:#93c5fd;--t-dec:#f9a8d4;--t-const:#fdba74;
  color-scheme:dark;
}}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text)}
body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased;padding-bottom:120px}
code,kbd,.fname{font-family:var(--mono);font-size:.88em}
code{background:var(--surface-2);border:1px solid var(--border);border-radius:5px;padding:0 5px}
kbd{border:1px solid var(--border-strong);border-bottom-width:2px;border-radius:5px;padding:0 5px;color:var(--muted);background:var(--surface)}
.muted{color:var(--muted)}.hint{color:var(--muted);font-size:13.5px;margin-top:22px}
.topbar{position:sticky;top:0;z-index:5;display:grid;grid-template-columns:auto 1fr auto;gap:20px;align-items:center;
  padding:12px 28px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.brand{display:flex;gap:10px;align-items:center}.logo{color:var(--accent);font-size:20px}
.product{font-weight:650;letter-spacing:-.01em}.sub{color:var(--muted);font-size:12.5px;max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#stepper{display:flex;gap:14px;overflow-x:auto;padding:4px 0;scrollbar-width:thin}
.step-group{display:flex;flex-direction:column;gap:4px;flex:none}
.step-label{font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);white-space:nowrap}
.steps{display:flex;gap:4px}
.step{width:22px;height:22px;border-radius:7px;border:1px solid var(--border-strong);background:var(--surface);cursor:pointer;
  display:grid;place-items:center;font-size:10.5px;color:var(--muted);transition:transform .12s}
.step:hover{transform:translateY(-1px)}.step.current{outline:2px solid var(--accent);outline-offset:1px;color:var(--text)}
.step.approved{background:var(--add-bg);border-color:var(--add);color:var(--add)}
.step.changes-requested{background:var(--del-bg);border-color:var(--del);color:var(--del)}
.step.commented{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.step.changed-since-your-verdict{border-style:dashed;border-color:var(--chg);color:var(--chg)}
.step.blocked-by-a-change-request-upstream{opacity:.45}
.progress{font-size:13px;color:var(--muted);white-space:nowrap}.progress b{color:var(--text)}
.bar{height:4px;width:140px;background:var(--border);border-radius:4px;overflow:hidden;margin-top:5px}.bar span{display:block;height:100%;background:var(--accent)}
main{max-width:1240px;margin:0 auto;padding:30px 28px}
.page{animation:enter .18s ease-out}@keyframes enter{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.page-head{margin-bottom:22px}.eyebrow{font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}
h1{font-size:28px;letter-spacing:-.02em;margin:6px 0 10px;font-weight:680}
h2{font-size:15.5px;margin:0 0 12px;font-weight:650}h2.section{margin:28px 0 10px}
.meta{display:flex;gap:8px}.pill{font-size:12px;padding:2px 10px;border-radius:20px;border:1px solid var(--border);background:var(--surface);color:var(--muted)}
.pill.risk-high{color:var(--del);border-color:color-mix(in srgb,var(--del) 40%,var(--border))}.pill.risk-medium{color:var(--chg)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin:0 0 16px;box-shadow:var(--shadow)}
.row{padding:14px 0;border-top:1px solid var(--border)}.card>h2+.row,.card>.row:first-child{border-top:0;padding-top:4px}
.row-head{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:8px}
.badge{font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.05em;padding:2px 8px;border-radius:6px}
.b-added{background:var(--add-bg);color:var(--add)}.b-removed{background:var(--del-bg);color:var(--del)}
.b-changed{background:var(--chg-bg);color:var(--chg)}.b-moved{background:var(--mov-bg);color:var(--mov)}.b-unchanged{background:var(--surface-2);color:var(--muted)}
.crumbs{font-family:var(--mono);font-size:13.5px}.crumbs .sep{color:var(--faint);margin:0 5px}.crumbs span:last-child{font-weight:650}
.label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);margin:12px 0 4px}
.fr{font-size:15px}.big .crumbs{font-size:17px}.big-fr{font-size:18px;font-weight:550;letter-spacing:-.01em}
.chip{display:inline-block;font-size:12px;padding:2px 9px;border-radius:20px;background:var(--surface-2);border:1px solid var(--border);margin:2px 4px 2px 0;font-family:var(--mono)}
.chip.need{background:var(--accent-soft);border-color:transparent;color:var(--accent)}
.crit-chip.ev-passed{color:var(--add);border-color:var(--add)}.crit-chip.ev-failed{color:var(--del);border-color:var(--del)}.crit-chip.ev-no-evidence{color:var(--chg);border-color:var(--chg)}
.serves{margin-top:10px;font-size:13px;color:var(--muted)}
.crits{list-style:none;padding:0;margin:12px 0 0}.crit{display:flex;gap:10px;align-items:baseline;padding:6px 0;border-top:1px dashed var(--border)}
.ctext{flex:1}.ev{font-size:12px;color:var(--muted);white-space:nowrap}.ev-passed{color:var(--add)}.ev-failed{color:var(--del)}.ev-no-evidence{color:var(--chg)}
.tdiff{display:grid;grid-template-columns:1fr 1fr;gap:10px}.tdiff.single{grid-template-columns:1fr}
.tdiff .col{border-radius:9px;padding:8px 12px;background:var(--surface-2);border:1px solid var(--border);white-space:pre-wrap;font-size:14px}
.tdiff .cap,.pair .cap{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);margin-bottom:4px}
.tdiff .add{background:var(--add-line);border-radius:4px;padding:0 4px;margin:0 -4px}.tdiff .del{background:var(--del-line);border-radius:4px;padding:0 4px;margin:0 -4px;text-decoration:line-through;text-decoration-color:color-mix(in srgb,var(--del) 50%,transparent)}
.statement{color:var(--muted)}.scope{background:var(--surface-2)}.arrow{color:var(--faint);margin:0 6px}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin:18px 0}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:var(--shadow)}
.stat .num{font-size:26px;font-weight:680;letter-spacing:-.02em}.stat .lbl{color:var(--muted);font-size:13px}
.plus{color:var(--add)}.minus{color:var(--del)}
.callout{border-radius:12px;padding:14px 16px;margin-bottom:16px;border:1px solid var(--border)}
.callout.ok{background:var(--add-bg);border-color:color-mix(in srgb,var(--add) 30%,var(--border))}
.callout.bad{background:var(--del-bg);border-color:color-mix(in srgb,var(--del) 30%,var(--border))}
.callout.warn{background:var(--chg-bg)}
.note{background:var(--accent-soft);border-radius:12px;padding:12px 16px;margin-bottom:16px}.note-head{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin-bottom:2px}
.panel-head{margin-bottom:12px}.panel-head h2{margin-bottom:2px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.diagram{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:10px;overflow:auto;min-height:80px}
.diagram svg{display:block;max-width:100%;height:auto}.empty{color:var(--faint);font-style:italic;padding:24px;text-align:center}
.legend{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin-bottom:14px;font-size:12.5px}
.lg::before{content:"";display:inline-block;width:14px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px;border:1.5px solid var(--border-strong)}
.lg.added::before{background:var(--add-bg);border-color:var(--add)}.lg.removed::before{background:var(--del-bg);border-color:var(--del)}
.lg.changed::before{border-color:var(--chg)}.lg.ghost::before{border-style:dashed;opacity:.5}
.arch-diagram .node rect{fill:var(--surface);stroke:var(--border-strong);stroke-width:1.2}
.arch-diagram .node .name{fill:var(--text);font:600 13px var(--mono)}.arch-diagram .node .fr{fill:var(--muted);font:11.5px -apple-system,Inter,sans-serif}
.arch-diagram text{fill:var(--text);font:12.5px var(--mono)}
.arch-diagram .node.added rect{fill:var(--add-bg);stroke:var(--add);stroke-width:2}
.arch-diagram .node.removed rect{fill:var(--del-bg);stroke:var(--del);stroke-width:2}
.arch-diagram .node.changed rect{stroke:var(--chg);stroke-width:2}
.arch-diagram .node.ghost{opacity:.28}.arch-diagram .node.ghost rect{stroke-dasharray:4 3;fill:none}
.arch-diagram .edge{fill:none;stroke:var(--faint);stroke-width:1.3}.arch-diagram .edge.added{stroke:var(--add);stroke-width:2.2}
.arch-diagram .edge.removed{stroke:var(--del);stroke-width:2;stroke-dasharray:5 4}.arch-diagram .arrowhead{fill:var(--faint)}
ul.plain{list-style:none;padding:0;margin:0}ul.plain li{padding:6px 0;border-top:1px solid var(--border)}ul.plain li:first-child{border-top:0}
.decision{margin-top:12px;padding:12px 14px;background:var(--surface-2);border:1px solid var(--border);border-radius:10px}
.dl{margin:2px 0}.dlabel{display:inline-block;min-width:92px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint)}
.component .facts{display:grid;grid-template-columns:1fr 1fr;gap:12px}
details summary{cursor:pointer}.component details{margin-top:12px;color:var(--muted);font-size:13.5px}
.file{background:var(--surface);border:1px solid var(--border);border-radius:12px;margin:0 0 14px;overflow:hidden;box-shadow:var(--shadow)}
.file>summary{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:10px 14px;background:var(--surface-2);border-bottom:1px solid var(--border);list-style:none}
.file>summary::-webkit-details-marker{display:none}.fname{font-weight:600}.counts{font-size:13px}.reasons{font-size:12px;color:var(--chg)}
.hunk-head{padding:6px 14px;font-size:12.5px;color:var(--muted);border-top:1px solid var(--border);background:var(--surface)}
.hunk:first-child .hunk-head{border-top:0}
table{border-collapse:collapse;width:100%;font:12.8px/1.55 var(--mono)}
td{padding:0 10px;vertical-align:top}td.ln{color:var(--faint);text-align:right;width:46px;user-select:none;font-size:11.5px}
td.code{white-space:pre-wrap;word-break:break-word;padding-left:14px}
tr.added{background:var(--add-line)}tr.added td.code{box-shadow:inset 3px 0 0 var(--add)}
tr.removed{background:var(--del-line)}tr.removed td.code{box-shadow:inset 3px 0 0 var(--del)}
.t-keyword{color:var(--t-kw)}.t-string{color:var(--t-str)}.t-comment{color:var(--t-com);font-style:italic}.t-number{color:var(--t-num)}
.t-defname{color:var(--t-def);font-weight:600}.t-decorator{color:var(--t-dec)}.t-constant{color:var(--t-const)}
.pad{padding:12px 14px}
.actionbar{position:fixed;left:0;right:0;bottom:0;z-index:6;display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:center;
  padding:12px 28px;background:color-mix(in srgb,var(--surface) 92%,transparent);backdrop-filter:blur(10px);border-top:1px solid var(--border)}
.verdicts{display:flex;gap:10px;justify-content:center}
button{font:inherit;font-size:14px;padding:8px 16px;border-radius:10px;border:1px solid var(--border-strong);background:var(--surface);color:var(--text);cursor:pointer;transition:background .12s,transform .06s}
button:hover{background:var(--surface-2)}button:active{transform:translateY(1px)}
button.approve{border-color:var(--add);color:var(--add)}button.approve:hover{background:var(--add-bg)}
button.request{border-color:var(--del);color:var(--del)}button.request:hover{background:var(--del-bg)}
button.primary{background:var(--accent);border-color:var(--accent);color:white}button.nav{color:var(--muted)}
button kbd{margin-left:6px}
#drawer{grid-column:1/-1;display:grid;gap:8px}.drawer-row{display:flex;gap:14px;align-items:center;font-size:13px}.drawer-row.end{justify-content:flex-end}
select,textarea{font:inherit;font-size:14px;background:var(--surface-2);color:var(--text);border:1px solid var(--border-strong);border-radius:8px;padding:7px 9px}
textarea{width:100%;resize:vertical}
@media (max-width:900px){.topbar{grid-template-columns:1fr}.pair,.tdiff,.component .facts{grid-template-columns:1fr}.verdicts button kbd{display:none}main{padding:20px 16px}}
"""

JS = r"""
const STATE = JSON.parse(document.getElementById('state').textContent);
const OPT = JSON.parse(document.getElementById('options').textContent);
const $ = s => document.querySelector(s);
const slug = s => s.replace(/[^a-z]+/g, '-');
let items = STATE.items, current = 0, pending = null;
const FINISH = items.length;
const fill = (sel, values) => { $(sel).innerHTML = values.map(v => `<option>${v}</option>`).join(''); };
fill('#category', OPT.categories); fill('#weight', OPT.weights);

function drawStepper() {
  let html = '', stage = null, n = 0;
  items.forEach((it, i) => {
    if (it.stage !== stage) { if (stage !== null) html += '</div></div>'; stage = it.stage;
      html += `<div class="step-group"><div class="step-label">${stage}</div><div class="steps">`; }
    html += `<div class="step ${slug(it.state)}${i === current ? ' current' : ''}" data-i="${i}" title="${it.title.replace(/"/g, '&quot;')} · ${it.state}">${++n}</div>`;
  });
  html += `</div></div><div class="step-group"><div class="step-label">done</div><div class="steps"><div class="step${current === FINISH ? ' current' : ''}" data-i="${FINISH}" title="finish">✓</div></div></div>`;
  $('#stepper').innerHTML = html;
  document.querySelectorAll('.step').forEach(s => s.onclick = () => show(+s.dataset.i));
  const p = STATE.progress, pct = p.total ? Math.round(100 * p.done / p.total) : 0;
  $('#progress').innerHTML = `<b>${p.done}</b> of ${p.total} decided<div class="bar"><span style="width:${pct}%"></span></div>`;
  const cur = document.querySelector('.step.current'); if (cur) cur.scrollIntoView({block: 'nearest', inline: 'nearest'});
}
function drawFinish() {
  const open = items.filter(i => i.state === 'changes requested');
  const left = items.filter(i => ['unreviewed', 'changed since your verdict'].includes(i.state));
  $('#finish-title').textContent = open.length ? `${open.length} pages need changes` : left.length ? `${left.length} pages still to review` : 'Everything approved';
  const list = (title, rows) => rows.length ? `<div class="card"><h2>${title}</h2><ul class="plain">${rows.map(i =>
    `<li><a href="#${encodeURIComponent(i.id)}" data-go="${i.id}">${i.title}</a>${i.verdict && i.verdict.comment ? ` <span class="muted">— ${i.verdict.comment}</span>` : ''}</li>`).join('')}</ul></div>` : '';
  $('#finish-body').innerHTML = list('Changes requested', open) + list('Not yet reviewed', left) +
    `<p class="hint">The author sees requests with <code>arch review --feedback</code>. For the commit or PR: <code>arch review --record</code>.</p>`;
  document.querySelectorAll('[data-go]').forEach(a => a.onclick = ev => { ev.preventDefault(); show(items.findIndex(x => x.id === a.dataset.go)); });
}
function show(i) {
  current = Math.max(0, Math.min(FINISH, i));
  const id = current === FINISH ? '__finish' : items[current].id;
  document.querySelectorAll('section.page').forEach(s => s.hidden = s.dataset.id !== id);
  if (current === FINISH) drawFinish();
  else document.getElementById(id).querySelector('[data-state]').textContent = items[current].state;
  document.querySelector('.verdicts').style.visibility = current === FINISH ? 'hidden' : 'visible';
  history.replaceState(null, '', '#' + encodeURIComponent(id));
  closeDrawer(); drawStepper(); window.scrollTo({top: 0});
}
function nextOpen() {
  for (let k = 1; k <= items.length; k++) {
    const i = current + k; if (i >= items.length) break;
    if (['unreviewed', 'changed since your verdict'].includes(items[i].state)) return show(i);
  }
  show(FINISH);
}
function openDrawer(decision) {
  pending = decision; $('#drawer').hidden = false;
  $('#category').value = decision === 'changes requested' ? 'bug' : 'other';
  $('#weight').value = decision === 'changes requested' ? 'blocking' : 'nit';
  $('#comment').focus();
}
function closeDrawer() { pending = null; $('#drawer').hidden = true; $('#comment').value = ''; }
async function send(decision, comment) {
  if (current === FINISH) return;
  const it = items[current];
  const res = await fetch('/api/verdict', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({item: it.id, digest: it.digest, decision, comment: comment || null,
                          category: $('#category').value, weight: $('#weight').value})});
  if (!res.ok) { alert(await res.text()); return; }
  const next = await res.json(); items = next.items; STATE.progress = next.progress;
  closeDrawer(); decision === 'approved' ? nextOpen() : drawStepper();
}
document.querySelectorAll('.verdicts [data-decision]').forEach(b => b.onclick = () =>
  b.dataset.decision === 'approved' ? send('approved') : openDrawer(b.dataset.decision));
$('#send').onclick = () => send(pending, $('#comment').value);
$('#cancel').onclick = closeDrawer;
$('#prev').onclick = () => show(current - 1);
$('#next').onclick = () => show(current + 1);
document.addEventListener('keydown', ev => {
  if (ev.target.matches('textarea')) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) send(pending, $('#comment').value);
    if (ev.key === 'Escape') closeDrawer();
    return;
  }
  if (ev.target.matches('select, input') || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const k = ev.key;
  if (k === 'ArrowRight') show(current + 1); else if (k === 'ArrowLeft') show(current - 1);
  else if (k === 'Home') show(0); else if (k === 'End') show(FINISH);
  else if (k === 'a' || k === 'A') send('approved'); else if (k === 'r') openDrawer('changes requested');
  else if (k === 'c') openDrawer('commented'); else if (k === 'n') nextOpen();
  else if (k === 'R') fetch('/api/rebuild', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}).then(() => location.reload());
  else return;
  ev.preventDefault();
});
const start = items.findIndex(x => '#' + encodeURIComponent(x.id) === location.hash);
show(start >= 0 ? start : 0);
"""

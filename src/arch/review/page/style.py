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
  <div class="page-head"><div class="eyebrow">Finish</div><h1 id="finish-title"></h1></div>
  <div id="finish-body"></div>
</section>
</main>
<div class="dock">
  <div id="drawer" hidden>
    <div class="drawer-row"><label>Type <select id="category"></select></label>
    <label>Must it be fixed before merge? <select id="weight"></select></label></div>
    <textarea id="comment" rows="3" placeholder="What should change, and why?"></textarea>
    <div class="drawer-row end"><span class="muted">Ctrl+Enter sends. Esc cancels.</span>
    <button id="cancel">Cancel</button><button id="send" class="primary">Send</button></div>
  </div>
  <div class="toolbar" role="toolbar" aria-label="verdict">
    <button class="nav" id="prev" data-tip="Previous page (←)" aria-label="Previous page">←</button>
    <div class="verdicts">
      <button class="approve" data-decision="approved" data-tip="Approve this page and go to the next one (A)">Approve</button>
      <button class="request" data-decision="changes requested" data-tip="Ask the author to change this page (R)">Request changes</button>
      <button class="comment" data-decision="commented" data-tip="Leave a comment without a verdict (C)">Comment</button>
    </div>
    <button class="nav" id="next" data-tip="Next page (→)" aria-label="Next page">→</button>
  </div>
</div>
<div id="tip" role="tooltip" hidden></div>
<script id="state" type="application/json">{{STATE}}</script>
<script id="options" type="application/json">{{OPTIONS}}</script>
<script>{{JS}}</script></body></html>"""

CSS = """
:root{
  --bg:#f6f6f3;--surface:#ffffff;--surface-2:#fafaf8;--border:#e6e4de;--border-strong:#d6d3cb;
  --text:#18181b;--muted:#5f5f68;--faint:#8e8e98;--accent:#4f46e5;--accent-soft:#eef2ff;
  --add:#15803d;--add-bg:#e8f9ee;--add-line:#dcfce7;--del:#b91c1c;--del-bg:#fdecec;--del-line:#fee2e2;
  --chg:#b45309;--chg-bg:#fff6dc;--mov:#7c3aed;--mov-bg:#f5f3ff;
  --shadow:0 1px 2px rgba(0,0,0,.04),0 4px 16px rgba(0,0,0,.04);
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --t-kw:#7c3aed;--t-str:#047857;--t-com:#8a8a93;--t-num:#b45309;--t-def:#1d4ed8;--t-dec:#be185d;--t-const:#c2410c;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f0f12;--surface:#17171b;--surface-2:#1c1c21;--border:#2a2a31;--border-strong:#3a3a42;
  --text:#ececf1;--muted:#a6a6b0;--faint:#75757f;--accent:#8b85ff;--accent-soft:#1f1d3a;
  --add:#4ade80;--add-bg:#0f2a1b;--add-line:#123321;--del:#f87171;--del-bg:#2c1214;--del-line:#3a1518;
  --chg:#fbbf24;--chg-bg:#2a2210;--mov:#a78bfa;--mov-bg:#221b38;--shadow:none;
  --t-kw:#c4b5fd;--t-str:#86efac;--t-com:#6b6b75;--t-num:#fcd34d;--t-def:#93c5fd;--t-dec:#f9a8d4;--t-const:#fdba74;
  color-scheme:dark;
}}
[hidden]{display:none!important}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text)}
body{font:15.5px/1.6 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
code,kbd,.fname{font-family:var(--mono);font-size:.88em}
code{background:var(--surface-2);border:1px solid var(--border);border-radius:5px;padding:0 5px}
kbd{border:1px solid var(--border-strong);border-bottom-width:2px;border-radius:5px;padding:0 5px;color:var(--muted);background:var(--surface)}
.muted{color:var(--muted)}.hint{color:var(--muted);font-size:14px;margin-top:22px}
.topbar{position:sticky;top:0;z-index:5;display:grid;grid-template-columns:auto 1fr auto;gap:20px;align-items:center;
  padding:12px 28px;background:color-mix(in srgb,var(--bg) 90%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
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
.step.waiting-on-a-change-to-an-earlier-page{opacity:.45}
.progress{font-size:13px;color:var(--muted);white-space:nowrap}.progress b{color:var(--text)}
.bar{height:4px;width:140px;background:var(--border);border-radius:4px;overflow:hidden;margin-top:5px}.bar span{display:block;height:100%;background:var(--accent)}
main{max-width:1320px;margin:0 auto;padding:30px 28px 120px}
.page{animation:enter .18s ease-out}@keyframes enter{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.page-head{margin-bottom:10px}.eyebrow{font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}
h1{font-size:28px;letter-spacing:-.02em;margin:6px 0 10px;font-weight:680;line-height:1.25}
h2{font-size:16px;margin:0 0 12px;font-weight:650}h2.section{margin:28px 0 10px}
.lead{font-size:17px;max-width:72ch;margin:0 0 22px;color:var(--text)}
.meta{display:flex;gap:8px}.pill{font-size:12px;padding:2px 10px;border-radius:20px;border:1px solid var(--border);background:var(--surface);color:var(--muted)}
.pill.risk-high{color:var(--del);border-color:color-mix(in srgb,var(--del) 40%,var(--border))}.pill.risk-medium{color:var(--chg)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin:0 0 16px;box-shadow:var(--shadow)}
.row{padding:14px 0;border-top:1px solid var(--border)}.card>h2+.row,.card>.row:first-child{border-top:0;padding-top:4px}
.row-head{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:8px}
.badge{font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.05em;padding:2px 8px;border-radius:6px}
.b-added{background:var(--add-bg);color:var(--add)}.b-removed{background:var(--del-bg);color:var(--del)}
.b-changed{background:var(--chg-bg);color:var(--chg)}.b-moved{background:var(--mov-bg);color:var(--mov)}.b-unchanged{background:var(--surface-2);color:var(--muted)}
.crumbs{font-family:var(--mono);font-size:13.5px}.crumbs .sep{color:var(--faint);margin:0 5px}.crumbs .ref{font-weight:650}
.ref{text-decoration:underline dotted color-mix(in srgb,currentColor 45%,transparent);text-underline-offset:3px}
.ref:hover{color:var(--accent);text-decoration-style:solid}
.open{text-decoration:none;color:var(--faint);font-size:13px;margin-left:4px}.open:hover{color:var(--accent)}
.label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);margin:14px 0 4px}
.big .crumbs{font-size:17px}.big-fr{font-size:18px;font-weight:550;letter-spacing:-.01em}
.chip{display:inline-block;font-size:12px;padding:2px 9px;border-radius:20px;background:var(--surface-2);border:1px solid var(--border);
  margin:2px 4px 2px 0;font-family:var(--mono);text-decoration:none;cursor:help}
a.chip{cursor:pointer}.chip.need{background:var(--accent-soft);border-color:transparent;color:var(--accent)}
.chip.rule{border-color:var(--border-strong)}
.chip.crit.ev-passed{color:var(--add);border-color:var(--add)}.chip.crit.ev-failed{color:var(--del);border-color:var(--del)}
.chip.crit.ev-no-evidence{color:var(--chg);border-color:var(--chg)}
.crits{list-style:none;padding:0;margin:4px 0 0}.crits li{display:flex;gap:10px;align-items:baseline;padding:7px 0;border-top:1px dashed var(--border)}
.crits li:first-child{border-top:0}
.ctext{flex:1}.ev{font-size:12px;color:var(--muted);white-space:nowrap;cursor:help}.ev-passed{color:var(--add)}.ev-failed{color:var(--del)}.ev-no-evidence{color:var(--chg)}
.tdiff{display:grid;grid-template-columns:1fr 1fr;gap:10px}.tdiff.single{grid-template-columns:1fr}
.tdiff .col{border-radius:9px;padding:8px 12px;background:var(--surface-2);border:1px solid var(--border);white-space:pre-wrap;font-size:15px}
.cap{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--faint);margin:6px 0 4px}
.tdiff .add{background:var(--add-line);border-radius:4px;padding:0 4px;margin:0 -4px}
.tdiff .del{background:var(--del-line);border-radius:4px;padding:0 4px;margin:0 -4px;text-decoration:line-through;text-decoration-color:color-mix(in srgb,var(--del) 50%,transparent)}
.statement{color:var(--muted)}.arrow{color:var(--faint);margin:0 6px}.scope .ref{margin-right:10px;font-family:var(--mono);font-size:13.5px}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin:18px 0}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:var(--shadow)}
.stat .num{font-size:26px;font-weight:680;letter-spacing:-.02em}.stat .lbl{color:var(--muted);font-size:13px}
.plus{color:var(--add)}.minus{color:var(--del)}
.callout{border-radius:12px;padding:14px 16px;margin-bottom:16px;border:1px solid var(--border)}
.callout.ok{background:var(--add-bg);border-color:color-mix(in srgb,var(--add) 30%,var(--border))}
.callout.bad{background:var(--del-bg);border-color:color-mix(in srgb,var(--del) 30%,var(--border))}
.note{background:var(--accent-soft);border-radius:12px;padding:12px 16px;margin-bottom:16px}.note-head{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin-bottom:2px}
.toc{margin:0;padding-left:22px}.toc li{padding:4px 0}.toc a{text-decoration:none}.toc a:hover{color:var(--accent);text-decoration:underline}
.toc .state{font-size:12.5px;color:var(--muted);margin-left:8px}
.panel-head{margin-bottom:6px}.panel-head h2{margin-bottom:2px}
.sides{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}.side{flex:0 1 auto;max-width:100%;min-width:0}
.diagram{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:10px;overflow-x:auto;margin-bottom:6px}
.diagram svg{display:block;max-width:none;height:auto}.empty{color:var(--muted);font-style:italic;padding:24px;text-align:center}
.legend{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin:0 0 16px;font-size:13.5px}
.lg::before{content:"";display:inline-block;width:18px;height:12px;border-radius:3px;margin-right:7px;vertical-align:-1px;border:2px solid var(--border-strong)}
.lg.added::before{background:var(--add-bg);border-color:var(--add)}.lg.removed::before{background:var(--del-bg);border-color:var(--del)}
.lg.changed::before{background:var(--chg-bg);border-color:var(--chg)}.lg.ghost::before{border-style:dashed;opacity:.5}
.arch-diagram a{cursor:pointer}.arch-diagram a:hover rect{stroke:var(--accent);stroke-width:2}
.arch-diagram .node rect{fill:var(--surface);stroke:var(--border-strong);stroke-width:1.2}
.arch-diagram .node .name{fill:var(--text);font:600 14px var(--mono)}.arch-diagram .node .fr{fill:var(--muted);font:12.5px -apple-system,Inter,sans-serif}
.arch-diagram text{fill:var(--text);font:12.5px var(--mono)}
.arch-diagram .node.added rect{fill:var(--add-bg);stroke:var(--add);stroke-width:2.2}
.arch-diagram .node.removed rect{fill:var(--del-bg);stroke:var(--del);stroke-width:2.2}
.arch-diagram .node.changed rect{fill:var(--chg-bg);stroke:var(--chg);stroke-width:2.2}
.arch-diagram .node.ghost{opacity:.3}.arch-diagram .node.ghost rect{stroke-dasharray:5 4;fill:none}
.arch-diagram .edge{fill:none;stroke:var(--faint);stroke-width:1.4}.arch-diagram .edge.added{stroke:var(--add);stroke-width:2.4}
.arch-diagram .edge.removed{stroke:var(--del);stroke-width:2.2;stroke-dasharray:6 4}.arch-diagram .arrowhead{fill:var(--faint)}
ul.plain{list-style:none;padding:0;margin:0}ul.plain li{padding:7px 0;border-top:1px solid var(--border)}ul.plain li:first-child{border-top:0}
.decision{margin-top:12px;padding:12px 14px;background:var(--surface-2);border:1px solid var(--border);border-radius:10px}
.dl{display:grid;grid-template-columns:110px 1fr;gap:10px;margin:3px 0}.dlabel{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);padding-top:3px}
.component .facts{display:grid;grid-template-columns:1fr 1fr;gap:12px}
details summary{cursor:pointer}
.file{background:var(--surface);border:1px solid var(--border);border-radius:12px;margin:0 0 14px;box-shadow:var(--shadow)}
.file-head{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:10px 14px;background:var(--surface-2);border-bottom:1px solid var(--border);border-radius:12px 12px 0 0}
.fname{font-weight:600;text-decoration:none}a.fname:hover{color:var(--accent);text-decoration:underline}
.counts{font-size:13px}.reasons{font-size:12.5px;color:var(--chg);cursor:help}
.hunk-head{padding:10px 14px;font-size:13.5px;color:var(--text);border-top:1px solid var(--border);background:var(--surface);
  display:grid;gap:6px}
.where{color:var(--muted)}.where .muted{font-size:13px;margin-top:2px}code.sig{color:var(--text);white-space:pre-wrap}
.why{display:flex;gap:10px;align-items:baseline;line-height:1.5}
.why-label{flex:none;min-width:82px;font-size:10.5px;font-weight:650;text-transform:uppercase;letter-spacing:.07em;
  color:var(--add);padding-top:2px}
.why.none .why-label{color:var(--chg)}.why.none{color:var(--chg)}
.why.ask .why-label{color:var(--accent)}
.why .chip{margin:0 2px}
.name{border-bottom:1px dotted color-mix(in srgb,currentColor 35%,transparent)}.name:hover{background:var(--accent-soft);border-radius:3px}
.interface .label{margin-top:16px}.small{font-size:13px}
.caller{margin-top:10px;border:1px solid var(--border);border-radius:10px;overflow:hidden}
.caller-head{padding:8px 14px;background:var(--surface-2);border-bottom:1px solid var(--border);font-size:13.5px}
.callout.plain{background:var(--surface-2)}
.note-row{padding:8px 0}.note-row+.note-row{border-top:1px dashed var(--border)}
blockquote.quote{margin:6px 0;padding:4px 12px;border-left:3px solid var(--border-strong);color:var(--muted);font-family:var(--mono);font-size:13px}
.hunk:first-child .hunk-head{border-top:0}
.hunk{overflow-x:auto}
table{border-collapse:collapse;width:100%;font:13px/1.55 var(--mono)}
td{padding:0 10px;vertical-align:top}td.ln{color:var(--faint);text-align:right;width:46px;user-select:none;font-size:11.5px}
td.ln a{text-decoration:none}td.ln a:hover{color:var(--accent);text-decoration:underline}
td.code{white-space:pre-wrap;word-break:break-word;padding-left:14px}
tr.added{background:var(--add-line)}tr.added td.code{box-shadow:inset 3px 0 0 var(--add)}
tr.removed{background:var(--del-line)}tr.removed td.code{box-shadow:inset 3px 0 0 var(--del)}
.t-keyword{color:var(--t-kw)}.t-string{color:var(--t-str)}.t-comment{color:var(--t-com);font-style:italic}.t-number{color:var(--t-num)}
.t-defname{color:var(--t-def);font-weight:600}.t-decorator{color:var(--t-dec)}.t-constant{color:var(--t-const)}
.pad{padding:12px 14px}
.dock{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:6;display:flex;flex-direction:column;align-items:center;gap:10px;
  max-width:calc(100vw - 24px)}
.toolbar{display:flex;gap:6px;align-items:center;padding:6px;border-radius:999px;background:color-mix(in srgb,var(--surface) 94%,transparent);
  backdrop-filter:blur(10px);border:1px solid var(--border-strong);box-shadow:0 6px 24px rgba(0,0,0,.12)}
.verdicts{display:flex;gap:6px}
button{font:inherit;font-size:14px;padding:7px 15px;border-radius:999px;border:1px solid transparent;background:transparent;color:var(--text);
  cursor:pointer;transition:background .12s,transform .06s}
button:hover{background:var(--surface-2)}button:active{transform:translateY(1px)}
button.nav{color:var(--muted);padding:7px 12px;font-size:16px}
button.approve{background:var(--add);color:white}button.approve:hover{background:color-mix(in srgb,var(--add) 85%,black)}
button.request{color:var(--del);border-color:color-mix(in srgb,var(--del) 45%,transparent)}button.request:hover{background:var(--del-bg)}
button.comment{color:var(--muted)}
button.primary{background:var(--accent);color:white}
#drawer{width:min(560px,calc(100vw - 24px));display:grid;gap:10px;padding:14px;border-radius:14px;background:var(--surface);
  border:1px solid var(--border-strong);box-shadow:0 10px 40px rgba(0,0,0,.18)}
#drawer button{border:1px solid var(--border-strong)}#drawer button.primary{border-color:var(--accent)}
.drawer-row{display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:13px}.drawer-row.end{justify-content:flex-end}
select,textarea{font:inherit;font-size:14px;background:var(--surface-2);color:var(--text);border:1px solid var(--border-strong);border-radius:8px;padding:6px 8px}
textarea{width:100%;resize:vertical}
#tip{position:fixed;z-index:30;max-width:440px;white-space:pre-line;padding:8px 11px;border-radius:9px;background:var(--text);color:var(--bg);
  font:13.5px/1.45 -apple-system,BlinkMacSystemFont,"Inter",sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.2);pointer-events:none}
[data-tip]{cursor:help}a[data-tip],button[data-tip]{cursor:pointer}
@media (max-width:900px){.topbar{grid-template-columns:1fr}.tdiff,.component .facts{grid-template-columns:1fr}main{padding:20px 16px 120px}
  button.comment{display:none}}
"""

JS = r"""
const STATE = JSON.parse(document.getElementById('state').textContent);
const OPT = JSON.parse(document.getElementById('options').textContent);
const $ = s => document.querySelector(s);
const slug = s => s.replace(/[^a-z]+/g, '-');
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
let items = STATE.items, current = 0, pending = null;
const FINISH = items.length;
const fill = (sel, values) => { $(sel).innerHTML = values.map(v => `<option>${v}</option>`).join(''); };
fill('#category', OPT.categories); fill('#weight', OPT.weights);

const tip = $('#tip');
function showTip(el) {
  tip.textContent = el.dataset.tip; tip.hidden = false;
  const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  let y = r.bottom + 8; if (y + h > innerHeight - 90) y = r.top - h - 8;
  tip.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + 'px'; tip.style.top = Math.max(8, y) + 'px';
}
const onTip = ev => { const el = ev.target.closest && ev.target.closest('[data-tip]'); if (el) showTip(el); else tip.hidden = true; };
document.addEventListener('mouseover', onTip); document.addEventListener('focusin', onTip);
document.addEventListener('scroll', () => { tip.hidden = true; }, true);

function drawStepper() {
  let html = '', stage = null, n = 0;
  items.forEach((it, i) => {
    if (it.stage !== stage) { if (stage !== null) html += '</div></div>'; stage = it.stage;
      html += `<div class="step-group"><div class="step-label">${esc(stage)}</div><div class="steps">`; }
    html += `<div class="step ${slug(it.state)}${i === current ? ' current' : ''}" data-i="${i}" data-tip="${esc(it.title)}. ${esc(it.state)}.">${++n}</div>`;
  });
  html += `</div></div><div class="step-group"><div class="step-label">done</div><div class="steps"><div class="step${current === FINISH ? ' current' : ''}" data-i="${FINISH}" data-tip="Finish: what is left to do">✓</div></div></div>`;
  $('#stepper').innerHTML = html;
  document.querySelectorAll('.step').forEach(s => s.onclick = () => show(+s.dataset.i));
  const p = STATE.progress, pct = p.total ? Math.round(100 * p.done / p.total) : 0;
  $('#progress').innerHTML = `<b>${p.done}</b> of ${p.total} pages decided<div class="bar"><span style="width:${pct}%"></span></div>`;
  const cur = document.querySelector('.step.current'); if (cur) cur.scrollIntoView({block: 'nearest', inline: 'nearest'});
}
function drawToc() {
  const toc = $('#toc'); if (!toc) return;
  toc.innerHTML = items.map(it => `<li><a href="#${esc(it.id)}">${esc(it.title)}</a><span class="state">${esc(it.state)}</span></li>`).join('');
}
function drawFinish() {
  const open = items.filter(i => i.state === 'changes requested');
  const left = items.filter(i => ['unreviewed', 'changed since your verdict'].includes(i.state));
  $('#finish-title').textContent = open.length ? `${open.length} pages need changes` : left.length ? `${left.length} pages are not reviewed yet` : 'Every page is approved';
  const list = (title, rows) => rows.length ? `<div class="card"><h2>${title}</h2><ul class="plain">${rows.map(i =>
    `<li><a class="ref" href="#${esc(i.id)}">${esc(i.title)}</a>${i.verdict && i.verdict.comment ? ` <span class="muted">${esc(i.verdict.comment)}</span>` : ''}</li>`).join('')}</ul></div>` : '';
  $('#finish-body').innerHTML = list('Changes requested', open) + list('Not reviewed yet', left) +
    `<p class="hint">The author can list your requests with <code>arch review --feedback</code>. ` +
    `To add your verdicts to the commit or pull request, run <code>arch review --record</code>.</p>`;
}
function show(i) {
  current = Math.max(0, Math.min(FINISH, i));
  const id = current === FINISH ? '__finish' : items[current].id;
  document.querySelectorAll('section.page').forEach(s => s.hidden = s.dataset.id !== id);
  if (current === FINISH) drawFinish();
  else document.querySelector(`section.page[data-id="${CSS.escape(id)}"] [data-state]`).textContent = items[current].state;
  $('.verdicts').hidden = current === FINISH;
  history.replaceState(null, '', '#' + id);
  closeDrawer(); drawStepper(); drawToc(); tip.hidden = true; window.scrollTo({top: 0});
}
const pageOf = hash => {
  const id = decodeURIComponent(hash.slice(1));
  return id === '__finish' ? FINISH : items.findIndex(x => x.id === id);
};
window.addEventListener('hashchange', () => { const i = pageOf(location.hash); if (i >= 0 && i !== current) show(i); });
function nextOpen() {
  for (let k = 1; k <= items.length; k++) {
    const i = current + k; if (i >= items.length) break;
    if (['unreviewed', 'changed since your verdict'].includes(items[i].state)) return show(i);
  }
  show(FINISH);
}
function openDrawer(decision) {
  if (current === FINISH) return;
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
  closeDrawer(); decision === 'approved' ? nextOpen() : (drawStepper(), drawToc());
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
  else if (k === 'Escape') closeDrawer();
  else if (k === 'a' || k === 'A') send('approved'); else if (k === 'r') openDrawer('changes requested');
  else if (k === 'c') openDrawer('commented'); else if (k === 'n') nextOpen();
  else if (k === 'R') fetch('/api/rebuild', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}).then(() => location.reload());
  else return;
  ev.preventDefault();
});
const start = pageOf(location.hash);
show(start >= 0 ? start : 0);
"""

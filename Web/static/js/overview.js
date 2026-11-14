/* OVERVIEW (2026-11-13, the views' stage 3) — the realm's own facts, in tiles.

   A view under ATLAS (views.js shows `#view-overview` in the map's place).
   Its top half is drawn here into `#overview-body` (inside the tiles' sheet,
   beside the `Charts ↓` that views.js owns), and ONLY there: the lower
   half is the Deck's charts, which views.js lifts into the same view, so
   nothing in this file may write over the view or the sheet itself.

   The facts come from the server (`api/v2/overview`), built and redacted
   there for this viewer: a hidden place never reaches this file, and who
   changed what, and the map's drift from its sources, reach an admin only.
   The fullest address ranges are worked out here from the dataset already
   in the browser, with the Addresses scene's own maths (overview-model.js
   over ipam.js). The answer is read each time the view comes up and every
   30 seconds while it stays up; nothing runs while another view is up.

   It is made to be left on a wall: big counts, nothing that needs a pointer
   or a hover to read, a tile that has nothing to report saying so in one
   plain line, and a list cut short with "+N more" rather than scrolled. A
   place's name opens the map's own card; an event nobody has acknowledged
   opens the ANNALS, where acknowledging stays.

   The rules and every phrase are overview-model.js (OVERVIEW_TEXT, through
   the theme). The look is views.css. */

import { A, $, esc, themeText } from './config.js';
import * as M from './overview-model.js';

const POLL_MS = 30000;
const CAP = 4;

/** One phrase: the theme's, else the plain one, with `{name}` filled in. */
const t = (key, vars = {}) => M.fill(themeText(key, M.OVERVIEW_TEXT[key] || ''), vars);

const S = {
  body: null,        // the last good answer
  error: '',         // why the last read failed ('' when it did not)
  at: 0,             // when the last good answer arrived (ms)
};

let root = null;
let timer = 0;
let rangesTimer = 0;
let rangesTries = 0;   // 40 looks (24 s) for the map's data, then the tile says what it has
let gen = 0;            // bumped on every hide: a late answer from before is dropped
let inflight = null;
let firstDrawn = false;

const shown = () => A.VIEW === 'overview';

/* ── the data ────────────────────────────────────────────────────────────── */

async function fetchOverview() {
  const res = await fetch('api/v2/overview', { cache: 'no-store' });
  let body = null;
  try { body = await res.json(); } catch { /* an empty or non-JSON answer */ }
  if (!res.ok) throw new Error(body?.error || `${res.status} ${res.statusText}`);
  if (!body || typeof body !== 'object') throw new Error('not an answer');
  return body;
}

/** Read the answer and redraw. One read at a time; a read begun before the
    view was put away is left to finish and its answer is dropped. */
let inflightGen = -1;
function read() {
  if (inflight && inflightGen === gen) return inflight;
  const mine = gen;
  const me = (async () => {
    let body = null, error = '';
    try { body = await fetchOverview(); } catch (err) { error = err.message || String(err); }
    if (inflight === me) inflight = null;
    if (mine !== gen) return;
    if (body) { S.body = body; S.error = ''; S.at = Date.now(); } else S.error = error;
    if (shown()) draw();
  })();
  inflight = me;
  inflightGen = mine;
  return me;
}

/* ── drawing ─────────────────────────────────────────────────────────────── */

const DOT = { healthy: 'h-up', degraded: 'h-degraded', down: 'h-down', maintenance: 'h-maint', slumbering: 'h-slumber' };
const dot = (state) => `<span class="svc-health ${DOT[state] || ''}" aria-hidden="true"></span>`;
const place = (p) => `<button type="button" class="ov-place" data-open="${esc(p.id)}" title="${esc(t('ov_open'))}">${esc(p.name || p.id)}</button>`;
const line = (text, cls = '') => (text ? `<p class="ov-line${cls ? ` ${cls}` : ''}">${esc(text)}</p>` : '');
const more = (n) => (n > 0 ? `<li class="ov-more">${esc(t('ov_more', { n }))}</li>` : '');
const big = (n, tone = '') => `<span class="ov-big${tone ? ` ov-${tone}` : ''}">${esc(String(n))}</span>`;

/** A list cut to the wall's length, its rows drawn by `row`, and how many more. */
function rows(items, row, extra = 0) {
  const { shown: list, more: cut } = M.capped(items, CAP);
  if (!list.length && !(cut + extra)) return '';
  return `<ul class="ov-list">${list.map((x) => `<li class="ov-row">${row(x)}</li>`).join('')}${more(cut + extra)}</ul>`;
}

const TILE = {
  states(b) {
    const states = b.states || {};
    const counts = M.stateRows(states);
    const down = Number(states.down) || 0;
    return {
      tone: down ? 'down' : (Number(states.degraded) || 0) ? 'warn' : '',
      html: (counts.length ? `<div class="ov-states">${counts.map((r) => `
          <div class="ov-state ov-state-${r.state}">${big(r.n)}
            <span class="ov-state-name">${dot(r.state)}${esc(t(`ov_state_${r.state}`))}</span>
          </div>`).join('')}</div>` : '')
        + line(M.stateSummary(states, t), 'ov-say'),
    };
  },
  down(b) {
    const d = M.downTile(b.down, t);
    if (d.empty) return { html: line(d.empty, 'ov-calm') };
    return {
      // the server lists a degraded place here too: the tone is the worst one
      tone: d.items.some((x) => x.state === 'down') ? 'down' : 'warn',
      count: d.items.length,
      html: rows(d.items, (x) => `
          <div class="ov-row-head">${dot(x.state)}${place(x)}</div>
          ${x.downstream.length ? `<div class="ov-takes"><span class="ov-quiet">${esc(x.takes)}</span> ${x.downstream.map(place).join(' ')}</div>` : ''}
          ${x.line ? `<span class="ov-quiet">${esc(x.line)}</span>` : ''}`)
        + line(d.note, 'ov-quiet'),
    };
  },
  unacked(b) {
    const u = M.unackedTile(b.unacked, t);
    if (u.empty) return { html: line(u.empty, 'ov-calm') };
    const word = b.admin ? 'ov_unacked_open' : 'ov_unacked_see';
    return {
      tone: 'warn',
      count: u.count,
      html: line(u.line, 'ov-say')
        + rows(u.items, (x) => `
          <button type="button" class="ov-event" data-annals="${esc(String(x.id))}">
            <span class="ov-event-name">${esc(x.name)}</span>
            <span class="ov-mono">${esc(x.move)}</span>
            <span class="ov-quiet">${esc(x.when)}</span>
          </button>`, u.more)
        + `<button type="button" class="ov-go" data-annals="">${esc(t(word))}</button>`,
    };
  },
  maintenance(b) {
    const m = M.maintenanceTile(b.maintenance, t);
    if (m.empty) return { html: line(m.empty, 'ov-calm') };
    return {
      tone: m.items.some((w) => w.now) ? 'warn' : '',
      count: m.items.length,
      html: rows(m.items, (w) => `
          <div class="ov-row-head"><span class="ov-what">${esc(w.reason)}</span></div>
          <span class="ov-mono${w.now ? ' ov-warn' : ''}">${esc(w.when)}</span>
          ${w.places.length ? `<div class="ov-takes">${w.places.slice(0, 8).map(place).join(' ')}${w.places.length > 8 ? ` <span class="ov-quiet">${esc(t('ov_more', { n: w.places.length - 8 }))}</span>` : ''}</div>` : ''}`),
    };
  },
  certs(b) {
    const list = M.certRows(b.certs, t);
    if (!list.length) return { html: line(t('ov_certs_none'), 'ov-calm') };
    const worst = list[0].tone;
    return {
      tone: worst,
      count: list.length,
      html: rows(list, (c) => `
          <div class="ov-row-head"><span class="ov-mono ov-cert-name">${esc(c.name)}</span>
            <span class="ov-mono ov-days${c.tone ? ` ov-${c.tone}` : ''}">${esc(c.phrase)}</span></div>
          ${c.place ? `<div class="ov-takes">${place(c.place)}</div>` : ''}`),
    };
  },
  review(b) {
    const r = M.reviewTile(b.review, t);
    if (r.empty) return { html: line(r.empty, 'ov-calm') };
    return {
      tone: '',
      count: r.count || r.items.length,
      html: r.lines.map((x) => line(x, 'ov-say')).join('')
        + rows(r.items, (x) => `<div class="ov-row-head">${place(x)}<span class="ov-quiet">${esc(x.when)}</span></div>`, r.more),
    };
  },
  changes(b) {
    const c = M.changesTile(b.changes, t);
    if (!c.admin) return { count: Number(b.changes?.count_7d) || 0, html: line(c.line, 'ov-say') };
    if (c.empty) return { html: line(c.empty, 'ov-calm') };
    return {
      count: c.items.length,
      html: rows(c.items, (x) => `
          <span class="ov-what">${esc(x.summary)}</span>
          <span class="ov-quiet">${esc([x.by, x.when].filter(Boolean).join(' · '))}</span>`),
    };
  },
  sources(b) {
    const s = M.sourcesTile(b.sources, Boolean(b.admin), t);
    return {
      tone: s.tone,
      html: line(s.line, s.tone ? 'ov-say' : 'ov-calm')
        + rows(s.items, (x) => `
          <div class="ov-row-head">${dot(x.ok ? 'healthy' : 'down')}<span class="ov-mono">${esc(x.name)}</span>
            <span class="ov-quiet">${esc(x.state)}</span></div>
          <span class="ov-quiet">${esc(x.when)}</span>`),
    };
  },
  drift(b) {
    const d = M.driftTile(b.drift, t);
    return {
      tone: d.tone,
      count: d.items.length || undefined,
      html: line(d.line, d.tone ? 'ov-say' : 'ov-calm')
        + rows(d.items, (name) => `<span class="ov-mono">${esc(name)}</span>`, d.more),
    };
  },
  ranges() {
    const r = M.rangesTile(M.fullestRanges(A.DATA, 5), t);
    if (r.empty) return { html: line(r.empty, r.loading ? 'ov-quiet' : 'ov-calm') };
    return {
      html: `<ul class="ov-list">${r.items.map((x) => `
          <li class="ov-row">
            <div class="ov-row-head"><span class="ov-what">${esc(x.name)}</span>
              <span class="ov-mono ov-quiet ov-range-at">${esc(x.cidr)} · ${esc(x.line)}</span>
              <span class="ov-mono ov-pct${x.tone ? ` ov-${x.tone}` : ''}">${esc(String(Math.round(x.pct)))}%</span></div>
            <div class="ov-bar" role="presentation"><span style="width:${Math.min(100, Math.max(0, x.pct))}%"${x.tone ? ` class="ov-${x.tone}"` : ''}></span></div>
          </li>`).join('')}</ul>`,
    };
  },
};

function tile(key, b) {
  let out;
  if (!b && key !== 'ranges') {
    out = { html: line(S.error ? '—' : t('ov_loading'), 'ov-quiet') };
  } else {
    try { out = TILE[key](b || {}); } catch (err) {
      console.warn('overview tile', key, err);
      out = { html: line('—', 'ov-quiet') };
    }
  }
  const count = out.count !== undefined && out.count !== null
    ? `<span class="ov-count${out.tone ? ` ov-${out.tone}` : ''}">${esc(String(out.count))}</span>` : '';
  return `<article class="ov-tile${out.tone ? ` ov-tone-${out.tone}` : ''}" data-tile="${key}">
      <header class="ov-tile-head"><h3 class="ov-tile-title">${esc(t(`ov_t_${key}`))}</h3>${count}</header>
      <div class="ov-tile-body">${out.html}</div>
    </article>`;
}

const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function draw() {
  root = root || $('overview-body');
  if (!root) return;
  const b = S.body;
  const order = M.tileOrder(b);
  let msg = '';
  if (S.error && b) msg = t('ov_stale', { when: clock(S.at), why: S.error });
  else if (S.error) msg = t('ov_failed', { why: S.error });
  const stamp = b && !S.error ? t('ov_updated', { when: clock(S.at) }) : '';
  // a redraw every 30 s must not throw a keyboard reader out of the tiles:
  // note what has focus, and give it back to the same control after
  const had = root.contains(document.activeElement) ? document.activeElement : null;
  const again = had?.dataset.open !== undefined ? `[data-open="${CSS.escape(had.dataset.open)}"]`
    : had?.dataset.annals !== undefined ? `[data-annals="${CSS.escape(had.dataset.annals)}"]` : '';
  const inTile = had?.closest('[data-tile]')?.dataset.tile;
  root.innerHTML = `
    <header class="ov-head">
      <h2 class="ov-title">${esc(themeText('view_overview', 'OVERVIEW'))}</h2>
      <p class="ov-sub">${esc(t('ov_sub'))}</p>
      <span class="ov-stamp" aria-live="polite">${esc(stamp)}</span>
    </header>
    ${msg ? `<p class="ov-msg" role="status">${esc(msg)}</p>` : ''}
    <div class="ov-grid">${order.map((k) => tile(k, b)).join('')}</div>`;
  if (again) (root.querySelector(`[data-tile="${inTile}"] ${again}`) || root.querySelector(again))?.focus({ preventScroll: true });
  // the ranges come from the map's own data, which may not be read yet on a
  // page that opens here: look again shortly, while the view is up
  clearTimeout(rangesTimer);
  if (A.DATA) rangesTries = 0;
  else if (shown() && rangesTries < 40) rangesTimer = setTimeout(() => { rangesTries += 1; if (shown()) draw(); }, 600);
  // a page that landed on the charts keeps them in place until every tile
  // has its answer (the facts and the map's own data); later reads never scroll
  if (b && A.DATA && !firstDrawn) { firstDrawn = true; A.settleCharts?.(); }
}

/* ── what a press does ───────────────────────────────────────────────────── */

function openCard(id) {
  const node = A.DATA?.nodes?.find((n) => n.id === id);
  if (!node || typeof A.openCard !== 'function') { A.showToast?.(t('ov_not_drawn')); return; }
  A.openCard(node);
}

/** The ANNALS, opened the way the card opens THE CALENDAR (card.js). */
function openAnnals() {
  A.closeAllScenes?.();
  A.setSceneActive?.('annals');
  A.openAnnals?.();
}

function onClick(e) {
  const p = e.target.closest('[data-open]');
  if (p) { openCard(p.dataset.open); return; }
  if (e.target.closest('[data-annals]')) openAnnals();
}

/* ── showing ─────────────────────────────────────────────────────────────── */

function tick() {
  if (!shown()) { stop(); return; }
  if (document.hidden) return;   // a tab nobody is looking at reads nothing
  read();
}

function stop() {
  clearInterval(timer);
  clearTimeout(rangesTimer);
  timer = 0;
  gen++;
}

/** The view came up: draw what is known at once (the tiles' shells keep the
    charts where they will be), then read it fresh, and every 30 s after. */
function show() {
  root = $('overview-body');
  if (!root) return;
  if (!root.dataset.wired) {
    root.dataset.wired = '1';
    root.addEventListener('click', onClick);
  }
  draw();
  read();
  clearInterval(timer);
  timer = setInterval(tick, POLL_MS);
}

addEventListener('atlas:view', (e) => {
  if (e.detail?.view === 'overview') show();
  else if (e.detail?.prev === 'overview') stop();
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && shown() && timer) read(); });
// the first view is chosen at import, before this file listens (views.js)
if (A.VIEW === 'overview' || document.body.dataset.view === 'overview') show();

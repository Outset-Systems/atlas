/* OVERVIEW (2026-11-13, the views' stage 3; two faces since 2026-11-20).

   A view under ATLAS (views.js shows `#view-overview` in the map's place).
   Its sheet is drawn here into `#overview-body` (inside `#overview-tiles`),
   and ONLY there: the bands above and below are the Sky's and the Depths'
   charts, which views.js lifts into the same view, so nothing in this file
   may write over the view or the sheet itself.

   The facts come from the server (`api/v2/overview`), built and redacted
   there for this viewer: a hidden place never reaches this file, and who
   changed what, and which source is which, reach an admin only. The answer
   is read each time the view comes up and every 30 seconds while it stays
   up; nothing runs while another view is up.

   ONE SCREEN, TWO FACES (owner, 2026-11-20). The sheet is exactly as tall
   as the screen under the band (views.css), and nothing inside it scrolls:
   scrolling the page goes to the Sky or the Depths. Above the faces, one
   sentence says how the realm is and the counts by state; below them, one
   line says everything that has nothing to report. Between, one of two
   faces, changed by a swipe, a drag, the arrow keys or the two tabs:
     the watch list   what wants a reader, worst first, beside the doors
                      (the favourites, and a source's own console);
     the chart table  the map, small, with a lamp for every place lit by its
                      state, beside the same watch list.
   Both faces draw the rows overview-model.js `watchList` makes from the one
   answer, so they cannot disagree. A list is cut to the height it has, not
   to a fixed count (`fit`), and says how many more there are.

   A place's name or lamp opens the map's own card; the events nobody has
   acknowledged open the ANNALS; the places not checked open NODES. A
   favourite, and a source with a console of its own, is a link: it opens in
   THE VIEWING GLASS when the service allows framing and in a new tab when it
   does not (glass.js takes the click on any `a[data-glass]`).

   The rules and every phrase are overview-model.js (OVERVIEW_TEXT, through
   the theme). The look is views.css. */

import { A, $, esc, themeText, HEALTH_DOT, getJSON, glassAttrs } from './config.js';
import * as M from './overview-model.js';
import { swipeStep } from './views-model.js';

const POLL_MS = 30000;
const FACE_KEY = 'atlas-overview-face';
/* how few rows a list keeps when the sheet is short: the watch list always
   says its worst thing, a list of doors its first */
const KEEP = { watch: 1, doors: 1 };

/** One phrase: the theme's, else the plain one, with `{name}` filled in. */
const t = (key, vars = {}) => M.fill(themeText(key, M.OVERVIEW_TEXT[key] || ''), vars);

let store = null;
try { store = localStorage; } catch { /* blocked: the face simply is not remembered */ }
const stored = () => { try { return store?.getItem(FACE_KEY); } catch { return null; } };

const S = {
  body: null,        // the last good answer
  error: '',         // why the last read failed ('' when it did not)
  at: 0,             // when the last good answer arrived (ms)
  face: M.faceOr(stored()),
};
const faces = () => M.FACES;
const face = () => S.face;

let root = null;
let timer = 0;
let gen = 0;            // bumped on every hide: a late answer from before is dropped
let inflight = null;
let firstDrawn = false;
let dragging = false;   // a drag is under way: a redraw waits for it to end
let dirty = false;      // an answer arrived during a drag
let swallow = false;    // the click that ends a swipe is not a press

const shown = () => A.VIEW === 'overview';

/* ── the data ────────────────────────────────────────────────────────────── */

async function fetchOverview() {
  const body = await getJSON('api/v2/overview');
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

const dot = (state) => `<span class="svc-health ${HEALTH_DOT[state] || ''}" aria-hidden="true"></span>`;
const place = (p) => `<button type="button" class="ov-place" data-open="${esc(p.id)}" title="${esc(t('ov_open'))}">${esc(p.name || p.id)}</button>`;
const line = (text, cls = '') => (text ? `<p class="ov-line${cls ? ` ${cls}` : ''}">${esc(text)}</p>` : '');

/** A way out to a service: an anchor glass.js opens over the page when the
    service allows it, else in a new tab. The address is the link's own. */
const door = (url, openIn, title, sub, cls, inner) => `<a class="${cls}" href="${esc(url)}" target="_blank"
    rel="noopener" data-door="${esc(url)}" ${glassAttrs(title, sub, openIn)}>${inner}</a>`;

/** A list `fit` may cut: every row is drawn, and the last line (hidden until
    rows are cut) says how many more. */
const fitList = (kind, cls, items) => `<ul class="ov-list ${cls}" data-fit="${kind}">${items.join('')}
    <li class="ov-more" hidden>${kind === 'watch'
    ? '<button type="button" class="ov-go" data-go="nodes"></button>' : '<span></span>'}</li></ul>`;

/** A row's name: a place opens its card, a row that is a way somewhere goes
    there, a silent source with a console opens it. */
function rowName(x) {
  if (x.key.startsWith('place:')) return place(x.place);
  if (x.go) return `<button type="button" class="ov-place" data-go="${esc(x.go)}">${esc(x.name)}</button>`;
  const cls = x.mono ? 'ov-mono ov-cert-name' : x.plain ? 'ov-what' : 'ov-w-name';
  const name = `<span class="${cls}">${esc(x.name)}</span>`;
  return x.url ? door(x.url, x.openIn, x.name, t('ov_t_sources'), 'ov-source', name) : name;
}

/** The watch list: one row for each thing that wants a reader. */
function watchRows(list) {
  if (!list.length) return line(S.body ? t('ov_wants_none') : '', 'ov-calm');
  return fitList('watch', 'ov-watch-list', list.map((x) => `
      <li class="ov-row ov-w${x.tone ? ` ov-w-${x.tone}` : ''}" data-key="${esc(x.key)}">
        <div class="ov-row-head">${dot(x.state)}${rowName(x)}
          ${x.word ? `<span class="ov-mono ov-w-word">${esc(x.word)}</span>` : ''}</div>
        ${x.detail || (x.place && !x.key.startsWith('place:')) ? `<div class="ov-takes">${
    x.place && x.key.startsWith('cert:') ? place(x.place)
      : `<span class="ov-quiet">${esc(x.detail)}</span>`}</div>` : ''}
      </li>`));
}

function favourites(which, b) {
  const f = M.favTile(b.favourites?.[which], Boolean(b.admin), t);
  const head = `<h3 class="ov-tile-title">${esc(t(which === 'internal' ? 'ov_t_favin' : 'ov_t_favout'))}</h3>`;
  if (f.empty) return `<div class="ov-door-group">${head}${line(f.empty, 'ov-calm')}${line(f.how, 'ov-quiet')}</div>`;
  return `<div class="ov-door-group">${head}${fitList('doors', 'ov-favs', f.items.map((x) => `<li class="ov-row">${
    door(x.url, x.openIn, x.label, x.place?.name || x.host, 'ov-fav', `
          <span class="ov-fav-name">${esc(x.label)}</span>
          <span class="ov-mono ov-quiet ov-fav-at">${esc(x.host)}</span>`)}</li>`))}</div>`;
}

/** The sources that answer and have a console of their own: doors too. (A
    silent one is a row on the watch list.) */
function sourceDoors(b) {
  const s = M.sourcesTile(b.sources, Boolean(b.admin), t);
  const items = s.items.filter((x) => x.ok && x.url);
  if (!items.length) return '';
  return `<div class="ov-door-group"><h3 class="ov-tile-title">${esc(t('ov_t_sources'))}</h3>${
    fitList('doors', 'ov-favs', items.map((x) => `<li class="ov-row">${
      door(x.url, x.openIn, x.name, t('ov_t_sources'), 'ov-fav', `
          <span class="ov-fav-name">${esc(x.name)}</span>
          <span class="ov-quiet ov-fav-at">${esc(x.when)}</span>`)}</li>`))}</div>`;
}

/* the map's own picture and where each place stands on it: what the big map
   is showing now (the chosen style, a viewer's own moves) */
const ratios = new Map();   // a picture's width over its height, by address
function mapArt() {
  const img = $('map-base');
  return img ? (img.currentSrc || img.getAttribute('src') || '') : '';
}
function lamps(list) {
  const feed = A.signalsFeed?.nodes || {};
  const states = {};
  for (const [id, v] of Object.entries(feed)) if (v?.state) states[id] = v.state;
  const places = (A.DATA?.nodes || []).map((n) => {
    const at = (typeof A.mainPlace === 'function' ? A.mainPlace(n) : null) || n._home || n;
    return { id: n.id, name: n.name, x: at.x, y: at.y, off: n._realOff ?? n.off_map };
  });
  return M.chartLamps(places, states, list);
}
function chart(list) {
  const { lamps: all, off } = lamps(list);
  const art = mapArt();
  return `<div class="ov-chart"><div class="ov-chart-in">
      ${art ? `<img class="ov-chart-art" src="${esc(art)}" alt="${esc(t('ov_chart_alt'))}" draggable="false">` : ''}
      ${all.map((p) => `<button type="button" class="ov-lamp svc-health ${HEALTH_DOT[p.state] || ''}${p.named ? ' ov-lamp-named' : ''}"
          style="left:${p.x.toFixed(2)}%;top:${p.y.toFixed(2)}%" data-open="${esc(p.id)}"
          title="${esc(p.name)}" aria-label="${esc(`${p.name}: ${t(`ov_state_${p.state}`)}`)}"></button>`).join('')}
    </div>${off ? `<p class="ov-quiet ov-chart-off">${esc(t(off === 1 ? 'ov_chart_off_one' : 'ov_chart_off', { n: off }))}</p>` : ''}</div>`;
}

/* The lamps are lit from the map's places and the live feed, and the first
   drawing comes before either has arrived: without this they read "not known"
   until the next 30-second read. Look twice a second, for half a minute at
   most (an Atlas with no live source never gets a feed), and draw again when
   what was missing is there. */
let waiting = 0;
const lit = () => Boolean(A.signalsFeed) && Boolean(A.DATA?.nodes?.length);
function awaitLamps() {
  if (waiting || lit()) return;
  let tries = 60;
  waiting = setInterval(() => {
    if (!shown() || tries-- <= 0) { clearInterval(waiting); waiting = 0; return; }
    if (!lit()) return;
    clearInterval(waiting); waiting = 0;
    draw();
  }, 500);
}

const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function draw() {
  root = root || $('overview-body');
  if (!root) return;
  if (dragging) { dirty = true; return; }
  dirty = false;
  const b = S.body;
  let msg = '';
  if (S.error && b) msg = t('ov_stale', { when: clock(S.at), why: S.error });
  else if (S.error) msg = t('ov_failed', { why: S.error });
  const stamp = b && !S.error ? t('ov_updated', { when: clock(S.at) }) : '';
  let list = [], calm = [], counts = [], say = S.error ? '—' : t('ov_loading');
  if (b) {
    try {
      list = M.watchList(b, t);
      calm = M.quietLine(b, t);
      counts = M.stateRows(b.states);
      say = M.stateSummary(b.states, t);
    } catch (err) { console.warn('overview', err); say = '—'; }
  }
  const states = b?.states || {};
  const tone = Number(states.down) ? 'down' : Number(states.degraded) ? 'warn' : '';
  // a redraw every 30 s must not throw a keyboard reader out of the sheet:
  // note what has focus, and give it back to the same control after
  const had = root.contains(document.activeElement) ? document.activeElement : null;
  const again = ['open', 'go', 'door', 'face'].map((k) => (had?.dataset[k] !== undefined
    ? `[data-${k}="${CSS.escape(had.dataset[k])}"]` : '')).find(Boolean) || '';
  const now = face();
  const tab = (f) => `<button type="button" role="tab" class="ov-tab" data-face="${f}"
      aria-selected="${now === f}" tabindex="${now === f ? 0 : -1}">${esc(t(`ov_face_${f}`))}</button>`;
  const faceAttrs = (f) => `class="ov-face ov-face-${f}" data-face="${f}" role="tabpanel"
      aria-label="${esc(t(`ov_face_${f}`))}"${now === f ? '' : ' hidden inert'}`;
  const doors = b ? favourites('internal', b) + favourites('external', b) + sourceDoors(b) : '';
  const rows = watchRows(list);
  root.dataset.face = now;   // views.css: what a narrow screen keeps for the other face
  root.innerHTML = `
    <header class="ov-head">
      <h2 class="ov-title">${esc(themeText('view_overview', 'OVERVIEW'))}</h2>
      <p class="ov-sub">${esc(t('ov_sub'))}</p>
      <div class="ov-tabs" role="tablist" aria-label="${esc(t('ov_faces'))}">${faces().map(tab).join('')}</div>
      <span class="ov-stamp" aria-live="polite">${esc(stamp)}</span>
    </header>
    ${msg ? `<p class="ov-msg" role="status">${esc(msg)}</p>` : ''}
    <div class="ov-top">
      <p class="ov-verdict${tone ? ` ov-verdict-${tone}` : ''}">${esc(say)}</p>
      ${counts.length ? `<div class="ov-states">${counts.map((r) => `
        <span class="ov-state-name ov-state-${r.state}">${dot(r.state)}<b>${esc(String(r.n))}</b> ${esc(t(`ov_state_${r.state}`))}</span>`).join('')}</div>` : ''}
    </div>
    <div class="ov-faces">
      <section ${faceAttrs('list')}>
        <div class="ov-watch" data-col>${rows}</div>
        <aside class="ov-doors" data-col aria-label="${esc(t('ov_doors'))}">${doors}</aside>
      </section>
      <section ${faceAttrs('chart')}>
        ${chart(list)}
        <div class="ov-watch" data-col>${rows}</div>
      </section>
    </div>
    ${calm.length ? `<p class="ov-calmline"><b>${esc(t('ov_quiet_lead'))}</b> ${esc(calm.join(' · '))}.</p>` : ''}`;
  for (const img of root.querySelectorAll('.ov-chart-art')) {
    if (!img.complete) img.addEventListener('load', fit, { once: true });
  }
  fit();
  awaitLamps();
  if (again) root.querySelector(`.ov-face:not([hidden]) ${again}, .ov-head ${again}`)?.focus({ preventScroll: true });
  // a page that landed on the charts keeps them in place until the sheet
  // has its answer; later reads never scroll
  if (b && !firstDrawn) { firstDrawn = true; A.settleCharts?.(); }
}

/* ── one screen: cut each list to the height it has ──────────────────────── */

/** Size the map to its cell, then cut rows until nothing overflows: the
    doors first, then the watch list, never below KEEP. Every cut row is
    counted in the list's last line. */
function fit() {
  if (!root) return;
  const face = root.querySelector('.ov-face:not([hidden])');
  if (!face) return;
  const cell = face.querySelector('.ov-chart');
  const inner = cell?.querySelector('.ov-chart-in');
  if (cell && inner) {
    const img = inner.querySelector('img');
    if (img?.naturalWidth) ratios.set(img.src, img.naturalWidth / img.naturalHeight);
    const ratio = (img && ratios.get(img.src)) || 16 / 10;
    const off = cell.querySelector('.ov-chart-off');
    const w = Math.max(0, Math.min(cell.clientWidth, (cell.clientHeight - (off ? off.offsetHeight + 8 : 0)) * ratio));
    inner.style.width = `${Math.floor(w)}px`;
    inner.style.height = `${Math.floor(w / ratio)}px`;
  }
  for (const ul of face.querySelectorAll('[data-fit]')) {
    for (const li of ul.children) li.hidden = li.classList.contains('ov-more');
  }
  // side by side, each column is cut by itself; stacked, the face is one column
  const wide = getComputedStyle(face).display === 'grid'
    && getComputedStyle(face).gridTemplateColumns.split(' ').length > 1;
  const order = M.cutOrder(!wide);
  const rank = (ul) => order.indexOf(ul.dataset.fit);
  const live = (ul) => [...ul.children].filter((li) => !li.hidden && !li.classList.contains('ov-more'));
  for (const col of wide ? [...face.querySelectorAll('[data-col]')] : [face]) {
    const lists = [...col.querySelectorAll('[data-fit]')];
    let guard = 400;
    while (col.scrollHeight > col.clientHeight + 1 && guard-- > 0) {
      const ul = lists.filter((l) => live(l).length > (KEEP[l.dataset.fit] || 1))
        .sort((a, z) => (rank(a) - rank(z)) || (live(z).length - live(a).length))[0];
      if (!ul) break;
      const rows = live(ul);
      rows[rows.length - 1].hidden = true;
      const moreLi = ul.querySelector(':scope > .ov-more');
      const n = [...ul.children].filter((li) => li.hidden && !li.classList.contains('ov-more')).length;
      moreLi.hidden = false;
      const way = moreLi.firstElementChild;
      // stacked on the first face, the rest of the watch list is on the chart table
      const toChart = !wide && ul.dataset.fit === 'watch' && face.dataset.face === 'list';
      if (way.dataset.go !== undefined) way.dataset.go = toChart ? 'chart' : 'nodes';
      way.textContent = t(ul.dataset.fit !== 'watch' ? 'ov_more' : toChart ? 'ov_more_chart' : 'ov_more_nodes', { n });
    }
  }
}

/* ── the two faces ───────────────────────────────────────────────────────── */

/** Show a face. `step` says which side it comes in from (1: from the right). */
function setFace(to, step = 0) {
  const next = M.faceOr(to);
  if (next === face() || !root) return;
  S.face = next;
  root.dataset.face = next;
  try { store?.setItem(FACE_KEY, next); } catch { /* private mode: not remembered */ }
  for (const el of root.querySelectorAll('.ov-face')) {
    const on = el.dataset.face === next;
    el.hidden = !on;
    el.inert = !on;
    el.classList.remove('ov-from-left', 'ov-from-right');
    if (on && step) el.classList.add(step > 0 ? 'ov-from-right' : 'ov-from-left');
  }
  for (const b of root.querySelectorAll('.ov-tab')) {
    const on = b.dataset.face === next;
    b.setAttribute('aria-selected', String(on));
    b.tabIndex = on ? 0 : -1;
  }
  fit();
}
const stepFace = (step) => setFace(M.faceStep(face(), step), step);

/* a swipe or a drag across the sheet turns the face; the press that ends it
   opens nothing */
let x0 = 0, y0 = 0;
function onDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  dragging = true; x0 = e.clientX; y0 = e.clientY;
}
function onUp(e) {
  if (!dragging) return;
  dragging = false;
  const step = e.type === 'pointerup' ? swipeStep(e.clientX - x0, e.clientY - y0) : 0;
  if (step) {
    swallow = true;
    setTimeout(() => { swallow = false; }, 80);
    getSelection?.()?.removeAllRanges();
    stepFace(step);
  }
  if (dirty) draw();
}
function onKey(e) {
  // the sheet's own keys, and the page's while nothing else has the focus
  if (!shown() || !root || !(e.target === document.body || root.contains(e.target))) return;
  if (e.altKey || e.ctrlKey || e.metaKey || e.target.closest('input, textarea, select')) return;
  if (e.key === 'ArrowRight') stepFace(1);
  else if (e.key === 'ArrowLeft') stepFace(-1);
  else return;
  root.querySelector('.ov-tab[aria-selected="true"]')?.focus({ preventScroll: true });
  e.preventDefault();
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
  if (swallow) { swallow = false; e.preventDefault(); e.stopPropagation(); return; }
  const tab = e.target.closest('.ov-tab');
  if (tab) { setFace(tab.dataset.face, faces().indexOf(tab.dataset.face) > faces().indexOf(face()) ? 1 : -1); return; }
  const p = e.target.closest('[data-open]');
  if (p) { openCard(p.dataset.open); return; }
  const go = e.target.closest('[data-go]')?.dataset.go;
  if (go === 'annals') openAnnals();
  else if (go === 'chart') setFace('chart', 1);
  else if (go === 'nodes') A.setView?.('nodes', { remember: true });
}

/* ── showing ─────────────────────────────────────────────────────────────── */

function tick() {
  if (!shown()) { stop(); return; }
  if (document.hidden) return;   // a tab nobody is looking at reads nothing
  read();
}

function stop() {
  clearInterval(timer);
  timer = 0;
  gen++;
}

/** The view came up: draw what is known at once, then read it fresh, and
    every 30 s after. */
function show() {
  root = $('overview-body');
  if (!root) return;
  if (!root.dataset.wired) {
    root.dataset.wired = '1';
    root.addEventListener('click', onClick, true);
    root.addEventListener('pointerdown', onDown);
    root.addEventListener('pointerup', onUp);
    root.addEventListener('pointercancel', onUp);
    document.addEventListener('keydown', onKey);
    if (typeof ResizeObserver === 'function') new ResizeObserver(() => fit()).observe(root);
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


import { A, $, CFG, esc, themeText, HEALTH_DOT, getJSON, glassAttrs, postJSON } from './config.js';
import * as M from './overview-model.js';
import { obsidianHref } from './card-model.js';
import { swipeStep } from './views-model.js';

const POLL_MS = 30000;
const FACE_KEY = 'atlas-overview-face';
const DAYS_KEY = 'atlas-overview-critical-days';
const KEEP = { watch: 1, doors: 1, critical: 1 };

const t = (key, vars = {}) => M.fill(themeText(key, M.OVERVIEW_TEXT[key] || ''), vars);

let store = null;
try { store = localStorage; } catch {   }
const stored = (key = FACE_KEY) => { try { return store?.getItem(key); } catch { return null; } };

const S = {
  body: null,
  error: '',
  at: 0,
  face: M.faceOr(stored()),
  days: M.windowOr(stored(DAYS_KEY)),
};
const faces = () => M.FACES;
const face = () => S.face;

let root = null;
let timer = 0;
let gen = 0;
let inflight = null;
let firstDrawn = false;
let dragging = false;
let dirty = false;
let swallow = false;

const shown = () => A.VIEW === 'overview';


async function fetchOverview() {
  const body = await getJSON('api/v2/overview');
  if (!body || typeof body !== 'object') throw new Error('not an answer');
  return body;
}

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


const dot = (state) => `<span class="svc-health ${HEALTH_DOT[state] || ''}" aria-hidden="true"></span>`;
const place = (p) => `<button type="button" class="ov-place" data-open="${esc(p.id)}" title="${esc(t('ov_open'))}">${esc(p.name || p.id)}</button>`;
const line = (text, cls = '') => (text ? `<p class="ov-line${cls ? ` ${cls}` : ''}">${esc(text)}</p>` : '');

const door = (url, openIn, title, sub, cls, inner) => `<a class="${cls}" href="${esc(url)}" target="_blank"
    rel="noopener" data-door="${esc(url)}" ${glassAttrs(title, sub, openIn)}>${inner}</a>`;

const fitList = (kind, cls, items, pager = '') => `<ul class="ov-list ${cls}" data-fit="${kind}"${
  pager ? ` data-pager="${pager}"` : ''}>${items.join('')}
    <li class="ov-more" hidden>${kind === 'watch' || kind === 'critical'
    ? `<button type="button" class="ov-go" data-go="${kind === 'critical' ? 'annals' : 'nodes'}"></button>`
    : pager ? pagerHTML() : '<span></span>'}</li></ul>`;

const pagerHTML = () => `<span class="ov-pager">
    <button type="button" class="ov-page" data-page="-1" aria-label="${esc(t('ov_page_prev'))}">‹</button>
    <span class="ov-page-n" aria-live="polite"></span>
    <button type="button" class="ov-page" data-page="1" aria-label="${esc(t('ov_page_next'))}">›</button></span>`;

const PAGES = new Map();

function rowName(x) {
  if (x.key.startsWith('place:')) return place(x.place);
  if (x.go) return `<button type="button" class="ov-place" data-go="${esc(x.go)}">${esc(x.name)}</button>`;
  const cls = x.mono ? 'ov-mono ov-cert-name' : x.plain ? 'ov-what' : 'ov-w-name';
  const name = `<span class="${cls}">${esc(x.name)}</span>`;
  return x.url ? door(x.url, x.openIn, x.name, t('ov_t_sources'), 'ov-source', name) : name;
}

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
          <span class="ov-mono ov-quiet ov-fav-at">${esc(x.host)}</span>`)}</li>`), which)}</div>`;
}

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

function criticalFace(b) {
  const c = M.criticalTile(b?.critical, S.days, t);
  const chip = (n) => `<button type="button" class="ov-tab ov-days" data-days="${n}"
      aria-pressed="${S.days === n}">${esc(t('ov_crit_days', { n }))}</button>`;
  const head = `<div class="ov-crit-head"><h3 class="ov-tile-title">${esc(t('ov_crit_title', { n: S.days }))}</h3>
      <div class="ov-crit-days" role="group" aria-label="${esc(t('ov_crit_windows'))}">${
  M.CRITICAL_WINDOWS.map(chip).join('')}</div></div>`;
  let list = '';
  if (c.rows.length) {
    list = fitList('critical', 'ov-watch-list ov-crit-list', c.rows.map((x) => `
      <li class="ov-row ov-w${x.tone ? ` ov-w-${x.tone}` : ''}" data-key="${esc(x.key)}" title="${esc(x.when)}">
        <div class="ov-row-head">${dot(x.state)}${x.kind === 'node' && x.place ? place(x.place)
    : `<span class="${x.kind === 'tripwire' ? 'ov-mono ov-cert-name' : 'ov-w-name'}">${esc(x.name)}</span>`}
          <span class="ov-mono ov-w-word">${esc(x.word)}</span></div>
        <div class="ov-takes"><span class="ov-quiet">${esc(x.detail)}</span></div>
      </li>`));
  } else list = line(b ? c.empty : '', 'ov-calm');
  const side = b && c.rows.length ? `${c.lines.map((l) => line(l, 'ov-say')).join('')}${line(c.note, 'ov-quiet')}
      <button type="button" class="ov-go" data-go="annals">${esc(t('ov_crit_annals'))}</button>` : '';
  return `<div class="ov-watch ov-crit" data-col>${head}${list}</div>
      <aside class="ov-doors ov-crit-side" data-col>${side}</aside>`;
}

function notesDoor() {
  const n = M.notesLink(CFG.NOTES_HOME, CFG.SCROLL_ROOT, obsidianHref);
  if (!n) return '';
  const say = t('ov_notes', { vault: n.vault || 'the notebook' });
  return `<a class="ov-notes" href="${esc(n.href)}" title="${esc(say)}" aria-label="${esc(say)}">${
    NOTE_GLYPH}<span>${esc(n.vault || 'Notes')}</span></a>`;
}
const NOTE_GLYPH = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5h7.5a1.5 1.5 0 0 1 1.5 1.5v9.5H5.5A1.5 1.5 0 0 1 4 12V2.5z"/><path d="M4 12a1.5 1.5 0 0 1 1.5-1.5H13M6.5 5.5h4M6.5 8h3"/></svg>';

const ratios = new Map();
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
      calm = M.quietLine(b, t, Date.now(), S.days);
      counts = M.stateRows(b.states);
      say = M.stateSummary(b.states, t);
    } catch (err) { console.warn('overview', err); say = '—'; }
  }
  const states = b?.states || {};
  const tone = Number(states.down) ? 'down' : Number(states.degraded) ? 'warn' : '';
  const had = root.contains(document.activeElement) ? document.activeElement : null;
  const again = ['open', 'go', 'door', 'face', 'days'].map((k) => (had?.dataset[k] !== undefined
    ? `[data-${k}="${CSS.escape(had.dataset[k])}"]` : '')).find(Boolean) || '';
  const now = face();
  const crit = b ? M.criticalCount(b.critical, S.days) : 0;
  const tab = (f) => `<button type="button" role="tab" class="ov-tab" data-face="${f}"
      aria-selected="${now === f}" tabindex="${now === f ? 0 : -1}">${esc(f === 'critical' && crit
    ? t('ov_face_critical_n', { n: crit }) : t(`ov_face_${f}`))}</button>`;
  const faceAttrs = (f) => `class="ov-face ov-face-${f}" data-face="${f}" role="tabpanel"
      aria-label="${esc(t(`ov_face_${f}`))}"${now === f ? '' : ' hidden inert'}`;
  const doors = b ? favourites('internal', b) + favourites('external', b) + sourceDoors(b) : '';
  const rows = watchRows(list);
  root.dataset.face = now;
  root.innerHTML = `
    <header class="ov-head">
      <h2 class="ov-title">${esc(themeText('view_overview', 'OVERVIEW'))}</h2>
      <p class="ov-sub">${esc(t('ov_sub'))}</p>
      <div class="ov-tabs" role="tablist" aria-label="${esc(t('ov_faces'))}">${faces().map(tab).join('')}</div>
      <span class="ov-stamp" aria-live="polite">${esc(stamp)}</span>
      ${notesDoor()}
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
      <section ${faceAttrs('critical')}>${criticalFace(b)}</section>
    </div>
    ${calm.length ? `<p class="ov-calmline"><b>${esc(t('ov_quiet_lead'))}</b> ${esc(calm.join(' · '))}.</p>` : ''}`;
  for (const img of root.querySelectorAll('.ov-chart-art')) {
    if (!img.complete) img.addEventListener('load', fit, { once: true });
  }
  fit();
  awaitLamps();
  if (again) root.querySelector(`.ov-face:not([hidden]) ${again}, .ov-head ${again}`)?.focus({ preventScroll: true });
  if (b && !firstDrawn) { firstDrawn = true; A.settleCharts?.(); }
}


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
      if (ul.dataset.pager !== undefined) continue;
      const toChart = !wide && ul.dataset.fit === 'watch' && face.dataset.face === 'list';
      if (way.dataset.go !== undefined && ul.dataset.fit === 'watch') way.dataset.go = toChart ? 'chart' : 'nodes';
      way.textContent = t(ul.dataset.fit === 'critical' ? 'ov_more_annals'
        : ul.dataset.fit !== 'watch' ? 'ov_more' : toChart ? 'ov_more_chart' : 'ov_more_nodes', { n });
    }
  }
  pageLists(face);
}

function pageLists(face) {
  for (const ul of face.querySelectorAll('[data-pager]')) {
    const rows = [...ul.children].filter((li) => !li.classList.contains('ov-more'));
    const more = ul.querySelector(':scope > .ov-more');
    const kept = rows.filter((li) => !li.hidden).length;
    if (!more || kept >= rows.length) continue;
    const at = M.pageSlice(rows.length, kept, PAGES.get(ul.dataset.pager) || 0);
    PAGES.set(ul.dataset.pager, at.page);
    rows.forEach((li, i) => { li.hidden = i < at.start || i >= at.end; });
    more.hidden = false;
    more.querySelector('.ov-page-n').textContent = t('ov_page_of', { n: at.page + 1, m: at.pages });
  }
}

function countOpen(e) {
  const a = e.target.closest?.('[data-pager] a[data-door]');
  if (!a || document.body.dataset.demo === '1') return;
  postJSON('api/v2/favourites/open', { url: a.dataset.door }).catch(() => {});
}


function setFace(to, step = 0) {
  const next = M.faceOr(to);
  if (next === face() || !root) return;
  S.face = next;
  root.dataset.face = next;
  try { store?.setItem(FACE_KEY, next); } catch {   }
  for (const el of root.querySelectorAll('.ov-face')) {
    const on = el.dataset.face === next;
    el.hidden = !on;
    el.inert = !on;
    el.classList.remove('ov-from-left', 'ov-from-right');
    if (on && step) el.classList.add(step > 0 ? 'ov-from-right' : 'ov-from-left');
  }
  for (const b of root.querySelectorAll('.ov-tab[data-face]')) {
    const on = b.dataset.face === next;
    b.setAttribute('aria-selected', String(on));
    b.tabIndex = on ? 0 : -1;
  }
  fit();
}
const stepFace = (step) => setFace(M.faceStep(face(), step), step);

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
  if (!shown() || !root || !(e.target === document.body || root.contains(e.target))) return;
  if (e.altKey || e.ctrlKey || e.metaKey || e.target.closest('input, textarea, select')) return;
  if (e.key === 'ArrowRight') stepFace(1);
  else if (e.key === 'ArrowLeft') stepFace(-1);
  else return;
  root.querySelector('.ov-tab[aria-selected="true"]')?.focus({ preventScroll: true });
  e.preventDefault();
}


function openCard(id) {
  const node = A.DATA?.nodes?.find((n) => n.id === id);
  if (!node || typeof A.openCard !== 'function') { A.showToast?.(t('ov_not_drawn')); return; }
  A.openCard(node);
}

function openAnnals() {
  A.closeAllScenes?.();
  A.setSceneActive?.('annals');
  A.openAnnals?.();
}

function onClick(e) {
  if (swallow) { swallow = false; e.preventDefault(); e.stopPropagation(); return; }
  const days = e.target.closest('[data-days]');
  if (days) {
    S.days = M.windowOr(days.dataset.days);
    try { store?.setItem(DAYS_KEY, String(S.days)); } catch {   }
    draw();
    return;
  }
  const page = e.target.closest('[data-page]');
  if (page) {
    const key = page.closest('[data-pager]')?.dataset.pager;
    if (key) { PAGES.set(key, (PAGES.get(key) || 0) + Number(page.dataset.page)); fit(); }
    return;
  }
  countOpen(e);
  const tab = e.target.closest('.ov-tab');
  if (tab) { setFace(tab.dataset.face, faces().indexOf(tab.dataset.face) > faces().indexOf(face()) ? 1 : -1); return; }
  const p = e.target.closest('[data-open]');
  if (p) { openCard(p.dataset.open); return; }
  const go = e.target.closest('[data-go]')?.dataset.go;
  if (go === 'annals') openAnnals();
  else if (go === 'chart') setFace('chart', 1);
  else if (go === 'nodes') A.setView?.('nodes', { remember: true });
}


function tick() {
  if (!shown()) { stop(); return; }
  if (document.hidden) return;
  read();
}

function stop() {
  clearInterval(timer);
  timer = 0;
  gen++;
}

function show() {
  root = $('overview-body');
  if (!root) return;
  if (!root.dataset.wired) {
    root.dataset.wired = '1';
    root.addEventListener('click', onClick, true);
    root.addEventListener('auxclick', (e) => { if (e.button === 1) countOpen(e); });
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
if (A.VIEW === 'overview' || document.body.dataset.view === 'overview') show();

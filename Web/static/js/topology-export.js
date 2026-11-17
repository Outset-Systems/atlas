/* TOPOLOGY, taking the canvas out (2026-11-17): four buttons in ARRANGE AND
   EXPORT, for everyone who may see the view (each is a read), on a phone too.

     SVG             the WHOLE drawing (every card and cable of the graph on
                     screen, not only the part in view), as one file that
                     opens the same in a browser, an image viewer or a vector
                     editor: the canvas's own sheet written in with every
                     `--tp-*` value resolved (and also set on the root), the
                     faces it uses embedded as woff2 `data:` addresses, the
                     emblems as the symbols they are, a title and the date,
                     the ground as a rect, and no reference out of the file
                     (checked before it is offered). The scheme on screen.
     PNG             that file painted to a canvas at twice its size through
                     a `data:` address (the page's img-src allows no blob:),
                     scaled down to fit when a canvas could not hold it, and
                     saying so.
     Connections CSV the server's sheet, cut for this viewer
                     (/api/v2/topology/connections.csv).
     Site report     a print page (the browser's own Save as PDF): the map on
                     paper, the connections, what is down now and the
                     certificates near their end. The print rules are
                     topology.css's last block; they apply only while the
                     report prints, so an ordinary print is unchanged.

   A part of the view: it reaches the canvas through the doors in
   topology-state.js, and draws the whole graph through the canvas's own
   `draw()` with the view set wide for one synchronous moment (there is no
   door yet that draws the whole graph off screen), then puts the view back.
   It never imports the conductor (topology.js), which imports it. Every
   rule and sum is topology-export-model.js's. */

import { A, esc } from './config.js';
import * as M from './topology-model.js';
import * as X from './topology-export-model.js';
import { T, t, addTool, shownGraph, positions, svgEl } from './topology-state.js';
// the canvas's own exports, as the brief allows until a door draws the whole graph
// off screen: draw() with the view set wide, and the svg's size on screen
import { draw as drawCanvas, size as canvasSize } from './topology-canvas.js';
import { watcherWords } from './nodes-cells.js';

const XLINK = 'http://www.w3.org/1999/xlink';
const LOGO_SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;
/** How long the export waits for emblems first wanted by its own drawing. */
const LOGO_WAIT_MS = 2500;
/** The title's face, as the view's own title (the design notes: Cinzel). */
const DISPLAY = "'Cinzel', serif";
const CSV_URL = 'api/v2/topology/connections.csv';

let busy = false;

/* ── small things ─────────────────────────────────────────────────────────── */

const pause = (ms) => new Promise((res) => { setTimeout(res, ms); });
const nextFrame = () => new Promise((res) => { requestAnimationFrame(() => res()); });

function base64(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(out);
}
const utf8Base64 = (text) => base64(new TextEncoder().encode(text));

function mapTitle() {
  const title = (T.data || A.DATA)?.meta?.title;
  return typeof title === 'string' && title.trim() ? title.trim() : 'Atlas';
}

function stamp(now = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${X.dateText(now)} ${p(now.getHours())}:${p(now.getMinutes())}`;
}

/** Save a blob as a file. (A download, not an image: img-src does not apply.) */
function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.rel = 'noopener';
  a.hidden = true;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

/* ── the note that says what happened ─────────────────────────────────────── */

let noteTimer = 0;
/** A line over the canvas's top corner saying what an export did or why it
    did not: never silent. */
function say(text, { long = false } = {}) {
  const stage = svgEl()?.parentElement;
  if (!stage) return;
  let note = stage.querySelector('.tp-x-note');
  if (!note) {
    note = document.createElement('p');
    note.className = 'tp-x-note';
    note.setAttribute('role', 'status');
    note.setAttribute('aria-live', 'polite');
    stage.append(note);
  }
  clearTimeout(noteTimer);
  note.textContent = text;
  note.hidden = !text;
  if (text) noteTimer = setTimeout(() => { note.hidden = true; }, long ? 12000 : 6000);
}

/* ── reading the page's own sheets ────────────────────────────────────────── */

function* rulesOf(list) {
  for (const r of list || []) {
    yield r;
    if (r.cssRules) yield* rulesOf(r.cssRules);
  }
}

function sheetsWhere(test) {
  const out = [];
  for (const sheet of document.styleSheets) {
    let rules = null;
    try { rules = sheet.cssRules; } catch { continue; }   // another origin: not ours
    if (test(sheet)) out.push([sheet, rules]);
  }
  return out;
}

const sheetFile = (name) => (sheet) => String(sheet.href || '').split('?')[0].endsWith(`/${name}`);

/** A sheet's text, from the page's CSSOM (no request), else fetched. */
async function sheetText(name) {
  const found = sheetsWhere(sheetFile(name))[0];
  if (found) return [...found[1]].map((r) => r.cssText).join('\n');
  const res = await fetch(`static/${name}`, { cache: 'force-cache' });
  if (!res.ok) throw new Error(`${name}: ${res.status}`);
  return res.text();
}

/** Custom properties a rule sets, as written ({'--x': 'var(--y)'}). */
function customProps(rule) {
  const out = {};
  for (let i = 0; i < rule.style.length; i++) {
    const p = rule.style[i];
    if (p.startsWith('--')) out[p] = rule.style.getPropertyValue(p).trim();
  }
  return out;
}

/** The drawing's values for paper: the light scheme's tokens through
    topology.css's mapping, the white ground (topology-export-model.js). */
function paperValues(live) {
  let mapping = {};
  let light = {};
  for (const [, rules] of sheetsWhere(() => true)) {
    for (const r of rulesOf(rules)) {
      const sel = r.selectorText || '';
      if (!sel) continue;
      if (sel.trim() === 'svg.tp-canvas' && r.style?.getPropertyValue('--tp-ground')) mapping = { ...mapping, ...customProps(r) };
      else if (sel.includes('data-scheme="light"') && sel.includes('#topology-sheet')) light = { ...light, ...customProps(r) };
    }
  }
  return X.paperValues(mapping, light, live);
}

/* ── the fonts ────────────────────────────────────────────────────────────── */

const fontData = new Map();   // file -> base64, kept for the next export
async function fontBase64(file) {
  if (!fontData.has(file)) {
    const res = await fetch(`static/fonts/${encodeURIComponent(file)}`, { cache: 'force-cache' });
    if (!res.ok) throw new Error(`${file}: ${res.status}`);
    fontData.set(file, base64(new Uint8Array(await res.arrayBuffer())));
  }
  return fontData.get(file);
}

/** The faces the drawn text computes to (read while the whole drawing is in
    the page), each once. */
function usedFonts(svg) {
  const seen = new Map();
  for (const el of svg.querySelectorAll('.tp-world text')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    const key = `${cs.fontFamily}|${cs.fontWeight}|${cs.fontStyle}`;
    if (!seen.has(key)) seen.set(key, { family: cs.fontFamily, weight: cs.fontWeight, style: cs.fontStyle });
  }
  return [...seen.values()];
}

/* ── the whole drawing ────────────────────────────────────────────────────── */

/** The emblem symbols the shown places want and the canvas does not hold yet. */
function missingLogos(svg) {
  const shown = shownGraph();
  if (!shown || typeof A.nodeLogo !== 'function') return [];
  const nodes = new Map(((T.data || A.DATA)?.nodes || []).filter((n) => n && typeof n.id === 'string').map((n) => [n.id, n]));
  const out = [];
  for (const th of shown.things) {
    if (th.type !== 'place' || !nodes.has(th.id)) continue;
    let slug = '';
    try { slug = String(A.nodeLogo(nodes.get(th.id)) || ''); } catch { slug = ''; }
    if (LOGO_SLUG.test(slug) && !svg.querySelector(`defs > symbol[id="tp-l-${slug}"]`) && !out.includes(slug)) out.push(slug);
  }
  return out;
}

/** Draw every card and cable of the shown graph into the live svg, copy it,
    and put the view back, all in one synchronous moment (nothing is painted
    between). Returns {clone, fonts}, or null when there is nothing drawn. */
function drawWhole() {
  const svg = svgEl();
  const shown = shownGraph();
  const pos = positions();
  if (!svg || !shown?.things.length || !pos) return null;
  const bounds = wholeBounds();
  if (!bounds) return null;
  const { w, h } = canvasSize();
  const keep = T.view;
  let shot;
  try {
    T.view = X.wideView(bounds, w || 800, h || 600);
    drawCanvas();
    shot = { clone: svg.cloneNode(true), fonts: usedFonts(svg), bounds };
  } finally {
    T.view = keep;
    drawCanvas();
  }
  // every card of the graph on screen, or no file: never a part passed off as the whole
  const want = shown.things.filter((th) => pos[th.id]).length;
  const got = shot.clone.querySelectorAll('.tp-cards .tp-card').length;
  if (got !== want) throw new Error(t('tp_x_partial', { got, want }));
  return shot;
}

/** The box round every card where it is now (a card dragged on screen
    included), read from the positions themselves. */
function wholeBounds() {
  const shown = shownGraph();
  return X.boundsOf(positions(), M.CARD_W, M.CARD_H, (id) => shown?.byId.get(id)?.type === 'group');
}

/** drawWhole, after waiting (a little) for the emblems its first pass asked
    for: a card first drawn by the export may want one the canvas has never
    read. */
async function captureWhole() {
  let shot = drawWhole();
  if (!shot) return null;
  const svg = svgEl();
  if (missingLogos(svg).length) {
    const until = performance.now() + LOGO_WAIT_MS;
    while (performance.now() < until && missingLogos(svg).length) await pause(120);
    shot = drawWhole() || shot;
  }
  return shot;
}

/** What the page's own hands need and a file does not (every data-* goes too). */
const DROP_ATTRS = ['tabindex', 'role', 'aria-label', 'aria-hidden', 'focusable', 'visibility'];
const STATE_CLASSES = ['tp-sel', 'tp-found'];
const LIT_CLASSES = ['tp-lit', 'tp-dim', 'tp-failed'];

/** The copy as markup: its layers (not the dotted grid, whose pattern is a
    url() the file may not carry) and the symbols they use. */
function markupOf(clone, { unlit = false } = {}) {
  const world = clone.querySelector('.tp-world');
  if (!world) return null;
  const drop = unlit ? [...STATE_CLASSES, ...LIT_CLASSES] : STATE_CLASSES;
  for (const el of world.querySelectorAll('*')) {
    for (const a of el.getAttributeNames()) if (DROP_ATTRS.includes(a) || a.startsWith('data-')) el.removeAttribute(a);
    if (el.classList.length) el.classList.remove(...drop);
  }
  const wanted = new Set();
  for (const use of world.querySelectorAll('use')) {
    const ref = use.getAttribute('href') || use.getAttributeNS(XLINK, 'href') || '';
    if (!ref.startsWith('#')) { use.remove(); continue; }
    wanted.add(ref.slice(1));
    use.setAttribute('href', ref);
    use.setAttributeNS(XLINK, 'xlink:href', ref);
  }
  const ser = new XMLSerializer();
  // the root declares both namespaces once; each fragment need not
  const plain = (el) => ser.serializeToString(el)
    .replace(/ xmlns="http:\/\/www\.w3\.org\/2000\/svg"/g, '')
    .replace(/ xmlns:xlink="http:\/\/www\.w3\.org\/1999\/xlink"/g, '');
  // not the dotted grid, and not what drawing lays over the canvas while it
  // works (`tp-draw-*`: the cables' hit paths, the cable being drawn)
  const body = [...world.children].filter((el) => !el.classList.contains('tp-grid')
    && ![...el.classList].some((c) => c.startsWith('tp-draw-'))).map(plain).join('');
  const defs = [...clone.querySelectorAll('defs > symbol')].filter((s) => wanted.has(s.id)).map(plain).join('');
  return { body, defs, cls: clone.getAttribute('class') || 'tp-canvas' };
}

/** The file: {text, box, now}. `paper` gives the site report's values (the
    light scheme's tokens on a white ground, nothing lit); otherwise the
    scheme on screen, as it is. */
async function buildFile({ paper = false } = {}) {
  const svg = svgEl();
  if (!svg) throw new Error(t('tp_x_empty'));
  const css = await sheetText('topology-canvas.css');
  const names = X.cssVarNames(css);
  const computed = getComputedStyle(svg);
  const live = {};
  for (const n of names) live[n] = computed.getPropertyValue(n).trim();
  const values = paper ? paperValues(live) : live;

  const shot = await captureWhole();
  if (!shot) throw new Error(t('tp_x_empty'));
  const parts = markupOf(shot.clone, { unlit: paper });
  if (!parts) throw new Error(t('tp_x_empty'));

  const faces = X.parseFaces(await sheetText('fonts.css'));
  const want = X.pickFaces([...shot.fonts, { family: DISPLAY, weight: 700, style: 'normal' }], faces);
  const fonts = (await Promise.all(want.map(async (f) => X.fontFaceCss(f, await fontBase64(f.file))))).join('\n');

  const box = X.exportBox(shot.bounds);
  const now = new Date();
  const text = X.svgDocument({
    box, cls: parts.cls, values, css: X.resolveCss(css, values), fonts, defs: parts.defs, body: parts.body,
    title: t('tp_x_title', { map: mapTitle() }), date: t('tp_x_date', { date: stamp(now) }),
    ground: values['--tp-ground'] || '', ink: values['--tp-ink'], dim: values['--tp-ink-dim'], gilt: values['--tp-gilt'],
    display: DISPLAY, mono: values['--tp-mono'] || "'JetBrains Mono', monospace",
  });
  const out = X.externalRefs(text);
  if (out.length) throw new Error(t('tp_x_external'));
  return { text, box, now };
}

/* ── the four ─────────────────────────────────────────────────────────────── */

/** Run one export at a time, and say what came of it. */
async function run(job) {
  if (busy) { say(t('tp_x_busy')); return; }
  busy = true;
  say(t('tp_x_working'));
  try {
    await job();
  } catch (e) {
    say(t('tp_x_failed', { why: e?.message || String(e) }), { long: true });
  } finally {
    busy = false;
  }
}

async function saveSvg() {
  const file = await buildFile();
  const name = X.fileName(mapTitle(), 'svg', file.now);
  saveBlob(new Blob([file.text], { type: 'image/svg+xml' }), name);
  say(t('tp_x_saved', { file: name }));
}

/** An <img> of the file through a `data:` address, decoded. */
async function imageOf(text) {
  const img = new Image();
  img.decoding = 'sync';
  img.src = `data:image/svg+xml;base64,${utf8Base64(text)}`;
  await img.decode();
  return img;
}

async function savePng() {
  const file = await buildFile();
  const plan = X.pngPlan(file.box.w, file.box.h);
  const img = await imageOf(file.text);
  const canvas = document.createElement('canvas');
  canvas.width = plan.width;
  canvas.height = plan.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error(t('tp_x_png_canvas'));
  // paint once and let the embedded faces settle, then paint for keeps
  ctx.drawImage(img, 0, 0, plan.width, plan.height);
  await pause(150);
  await nextFrame();
  ctx.clearRect(0, 0, plan.width, plan.height);
  ctx.drawImage(img, 0, 0, plan.width, plan.height);
  const blob = await new Promise((res) => { canvas.toBlob(res, 'image/png'); });
  if (!blob) throw new Error(t('tp_x_png_canvas'));
  const name = X.fileName(mapTitle(), 'png', file.now);
  saveBlob(blob, name);
  say(plan.reduced ? t('tp_x_png_reduced', { file: name, pct: Math.max(1, Math.round(plan.scale * 100)) })
    : t('tp_x_saved', { file: name }), { long: plan.reduced });
}

async function saveCsv() {
  const res = await fetch(CSV_URL, { credentials: 'same-origin', cache: 'no-store' });
  if (!res.ok) throw new Error(t('tp_x_csv_refused', { status: res.status }));
  const given = (res.headers.get('Content-Disposition') || '').match(/filename="([A-Za-z0-9._-]+)"/);
  const name = given ? given[1] : X.fileName(mapTitle(), 'csv', new Date()).replace('-topology-', '-connections-');
  saveBlob(await res.blob(), name);
  say(t('tp_x_saved', { file: name }));
}

/* ── the site report ──────────────────────────────────────────────────────── */

const td = (v, cls = '') => `<td${cls ? ` class="${cls}"` : ''}>${esc(v === '' || v === null || v === undefined ? '' : v)}</td>`;
const th = (key) => `<th scope="col">${esc(t(key))}</th>`;
const table = (heads, rows) => `<table><thead><tr>${heads.map(th).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;

function connectionsSection(data) {
  const rows = M.connections(M.buildGraph(data)).map((r) => `<tr>${td(r.name)}${td(r.to)}${td(r.port, 'tp-rp-mono')}` +
    `${td(r.farPort, 'tp-rp-mono')}${td(r.vlan, 'tp-rp-mono')}${td(r.poe === '' ? '' : String(r.poe), 'tp-rp-mono')}${td(r.path)}</tr>`);
  return `<section class="tp-rp-sec"><h2>${esc(t('tp_x_rp_conn'))}</h2>` +
    (rows.length ? table(['tp_x_col_device', 'tp_x_col_to', 'tp_x_col_port', 'tp_x_col_far', 'tp_x_col_vlan',
      'tp_x_col_poe', 'tp_x_col_path'], rows) : `<p>${esc(t('tp_x_rp_conn_none'))}</p>`) + '</section>';
}

function downSection(data) {
  const feed = A.signalsFeed;
  let body;
  if (!feed) body = `<p>${esc(t('tp_x_rp_down_nofeed'))}</p>`;
  else {
    const rows = X.downRows(data, feed).map((r) => {
      const note = r.kind === 'service' ? t('tp_x_down_on', { name: r.on }) : r.cause ? t('tp_x_down_behind', { name: r.cause }) : '';
      const by = r.kind === 'place' && r.by ? watcherWords(r.by) : '';
      return `<tr>${td(r.name)}${td(t(r.kind === 'service' ? 'tp_x_down_service' : 'tp_x_down_place'))}${td(note)}${td(by)}</tr>`;
    });
    body = rows.length ? table(['tp_x_col_name', 'tp_x_col_kind', 'tp_x_col_note', 'tp_x_col_by'], rows)
      : `<p>${esc(t('tp_x_rp_down_none'))}</p>`;
  }
  return `<section class="tp-rp-sec"><h2>${esc(t('tp_x_rp_down'))}</h2>${body}</section>`;
}

function daysWords(days) {
  if (days < -1) return t('tp_x_days_lapsed', { n: -days });
  if (days === -1) return t('tp_x_day_lapsed');
  if (days === 0) return t('tp_x_days_today');
  if (days === 1) return t('tp_x_day_left');
  return t('tp_x_days_left', { n: days });
}

function certsSection(data) {
  const rows = X.nearCerts(data?.certs, Date.now()).map((c) => `<tr>${td(c.name)}${td(c.host)}${td(c.expires, 'tp-rp-mono')}` +
    `${td(daysWords(c.days))}${td(c.renews || t('tp_x_renews_none'))}</tr>`);
  return `<section class="tp-rp-sec"><h2>${esc(t('tp_x_rp_certs'))}</h2>` +
    (rows.length ? table(['tp_x_col_name', 'tp_x_col_host', 'tp_x_col_expires', 'tp_x_col_days', 'tp_x_col_renews'], rows)
      : `<p>${esc(t('tp_x_rp_certs_none'))}</p>`) + '</section>';
}

let report = null;
function endReport() {
  document.documentElement.classList.remove('tp-printing');
  report?.remove();
  report = null;
  removeEventListener('afterprint', endReport);
}

async function siteReport() {
  endReport();
  const data = T.data || A.DATA;
  const file = await buildFile({ paper: true });
  const img = await imageOf(file.text);
  img.className = 'tp-rp-map';
  img.alt = t('tp_x_title', { map: mapTitle() });
  const sec = document.createElement('section');
  sec.className = 'tp-report';
  sec.innerHTML = '<header class="tp-rp-head">' +
    `<h1>${esc(t('tp_x_rp_head'))}</h1>` +
    `<p class="tp-rp-map-name">${esc(mapTitle())}</p>` +
    `<p class="tp-rp-when">${esc(t('tp_x_rp_when', { when: stamp(file.now) }))}</p></header>` +
    `<figure class="tp-rp-fig"><figcaption>${esc(t('tp_x_rp_map'))}</figcaption></figure>` +
    connectionsSection(data) + downSection(data) + certsSection(data);
  sec.querySelector('figure').prepend(img);
  document.body.append(sec);
  report = sec;
  addEventListener('afterprint', endReport);
  document.documentElement.classList.add('tp-printing');
  say('');
  await nextFrame();
  window.print();
}

/* ── the buttons ──────────────────────────────────────────────────────────── */

addTool({ id: 'export-svg', label: t('tp_x_svg'), title: t('tp_x_svg_title'), onPress: () => run(saveSvg) });
addTool({ id: 'export-png', label: t('tp_x_png'), title: t('tp_x_png_title'), onPress: () => run(savePng) });
addTool({ id: 'export-csv', label: t('tp_x_csv'), title: t('tp_x_csv_title'), onPress: () => run(saveCsv) });
addTool({ id: 'export-report', label: t('tp_x_report'), title: t('tp_x_report_title'), onPress: () => run(siteReport) });

/** The doors this part adds, for a test in the page or another stage. */
A.topologyExport = { buildFile, saveSvg, savePng, saveCsv, siteReport };

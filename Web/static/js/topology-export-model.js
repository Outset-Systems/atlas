/* TOPOLOGY, taking it out: the rules, with no DOM (2026-11-17). Pure, so
   node can test them (tests/test_topology_export_model.mjs); the page's half
   is topology-export.js, which reads the live drawing and hands it here.

     dateText(date)                 -> 'YYYY-MM-DD' in the reader's own day
     slug(text)                     -> 'test-realm' (ASCII, at most 40)
     fileName(title, ext, date)     -> 'test-realm-wiring-2026-11-17.svg'
     boundsOf(positions, w, h, g)   -> the box round every card, or null
     wideView(bounds, w, h)         -> the view that shows all of it at once
     exportBox(bounds, opts)        -> the file's viewBox {x, y, w, h}
     stripComments(css)             -> css without its comments
     cssVarNames(css)               -> ['--tp-ground', ...] the values it reads
     resolveCss(css, values)        -> every var(--x) put in as its value
     parseFaces(fontsCss)           -> [{family, style, min, max, file}]
     firstFamily(fontFamily)        -> 'Alegreya Sans'
     pickFaces(used, faces)         -> only the faces the drawing uses
     fontFaceCss(face, base64)      -> one @font-face with its woff2 written in
     svgDocument(parts)             -> the whole file, as text
     externalRefs(svgText)          -> every reference out of the file ([] is clean)
     pngPlan(w, h, opts)            -> {scale, width, height, reduced}
     daysLeft(iso, now)             -> SEALS's days to an expiry, or null
     nearCerts(certs, now)          -> the certificates SEALS counts near
     downRows(data, feed)           -> what the feed says is down now
     paperValues(map, light, live)  -> the drawing's values for paper

   Nothing here changes what it is given. */

import { serviceKey } from './alerts-model.js';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const list = (v) => (Array.isArray(v) ? v : []);
const words = (v) => (typeof v === 'string' ? v.trim() : '');
const pad2 = (n) => String(n).padStart(2, '0');

/* ── names and dates ──────────────────────────────────────────────────────── */

/** A date as 'YYYY-MM-DD', in the reader's own day (not UTC's). */
export function dateText(date) {
  const d = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** A map's title as a file name's first part: lower-case ASCII letters and
    digits, every other run one hyphen, at most 40, 'atlas' when nothing is
    left. The server's twin is api/v2/topology_sheet.py `slug`. */
export function slug(text) {
  const s = String(text ?? '').normalize('NFKD').replace(/\p{M}/gu, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
  return s || 'atlas';
}

/** The file a drawing is saved as: '<map>-wiring-<date>.<ext>', the word its
    title wears (the view is WIRING wherever a person reads it, and a file's
    name is read). */
export function fileName(title, ext, date) {
  const e = String(ext || '').toLowerCase().replace(/[^a-z0-9]/g, '') || 'svg';
  return `${slug(title)}-wiring-${dateText(date)}.${e}`;
}

/* ── the file's frame ─────────────────────────────────────────────────────── */

/** Room round the drawing, the band over it for the title and the date, and
    the narrowest a file is (so the title fits over a map of one card). */
export const MARGIN = 32;
export const HEAD = 64;
export const MIN_WIDTH = 440;

/** The viewBox of the file: the drawing's bounds with `margin` round them and
    `head` above for the title, at least `minW` wide (centred), whole units. */
export function exportBox(bounds, options = {}) {
  const margin = Number.isFinite(options.margin) ? options.margin : MARGIN;
  const head = Number.isFinite(options.head) ? options.head : HEAD;
  const minW = Number.isFinite(options.minW) ? options.minW : MIN_WIDTH;
  const b = isObj(bounds) ? bounds : {};
  const bx = Number.isFinite(b.x) ? b.x : 0;
  const by = Number.isFinite(b.y) ? b.y : 0;
  const bw = Number.isFinite(b.w) && b.w > 0 ? b.w : 0;
  const bh = Number.isFinite(b.h) && b.h > 0 ? b.h : 0;
  let x = bx - margin;
  let w = bw + 2 * margin;
  if (w < minW) { x -= (minW - w) / 2; w = minW; }
  const y = by - margin - head;
  const h = bh + 2 * margin + head;
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  return { x: x0, y: y0, w: Math.ceil(x + w) - x0, h: Math.ceil(y + h) - y0 };
}

/** The box round every card at `positions` (top-left corners, {id: {x, y}}),
    each `w` x `h`, a folded group's back card (5 up and 5 right) included
    when `isGroup(id)` says so. Read from the positions themselves, so a card
    dragged on screen is inside it. Null when there is no card. */
export function boundsOf(positions, w, h, isGroup = () => false) {
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const [id, p] of Object.entries(isObj(positions) ? positions : {})) {
    if (!isObj(p) || !Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
    const back = isGroup(id) ? 5 : 0;
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y - back);
    x1 = Math.max(x1, p.x + w + back); y1 = Math.max(y1, p.y + h);
  }
  return x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

/** The view ({k, x, y}: a world point p is drawn at p * k + (x, y)) that
    puts all of `bounds` inside a w x h window, centred, however small that
    makes it: what the canvas is set to for the moment it draws everything. */
export function wideView(bounds, w, h) {
  const W = Number(w) > 0 ? Number(w) : 800;
  const H = Number(h) > 0 ? Number(h) : 600;
  const bw = Math.max(1, bounds.w);
  const bh = Math.max(1, bounds.h);
  const k = Math.min(W / bw, H / bh);
  return { k, x: (W - bw * k) / 2 - bounds.x * k, y: (H - bh * k) / 2 - bounds.y * k };
}

/* ── the styles ───────────────────────────────────────────────────────────── */

export function stripComments(css) {
  return String(css ?? '').replace(/\/\*[\s\S]*?\*\//g, '');
}

/** The custom properties a sheet reads, each once, in the order first read. */
export function cssVarNames(css) {
  const out = [];
  for (const m of stripComments(css).matchAll(/var\(\s*(--[\w-]+)/g)) if (!out.includes(m[1])) out.push(m[1]);
  return out;
}

/** The sheet with every `var(--x)` (or `var(--x, fallback)`) put in as its
    value from `values` ({'--x': value}), else its fallback, else `initial`.
    So the file reads the same in a reader that knows no custom properties
    (most image viewers and vector editors). */
export function resolveCss(css, values) {
  const v = isObj(values) ? values : {};
  let out = stripComments(css);
  // innermost first, so a fallback that is itself a var() is resolved too
  for (let guard = 0; guard < 8 && /var\(/.test(out); guard++) {
    out = out.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)/g, (m, name, fallback) => {
      const got = typeof v[name] === 'string' ? v[name].trim() : '';
      if (got) return got;
      const fb = typeof fallback === 'string' ? fallback.trim() : '';
      return fb || 'initial';
    });
  }
  return out.replace(/\n{3,}/g, '\n\n').trim();
}

/* ── the fonts ────────────────────────────────────────────────────────────── */

/** Every @font-face in a sheet (fonts.css): its family, style, the weights it
    covers and its file's name. A face whose source is not one of our woff2
    files is skipped. */
export function parseFaces(fontsCss) {
  const out = [];
  for (const m of stripComments(fontsCss).matchAll(/@font-face\s*\{([^}]*)\}/g)) {
    const body = m[1];
    const get = (prop) => (body.match(new RegExp(`(?:^|;|\\s)${prop}\\s*:\\s*([^;]+)`)) || [])[1]?.trim() || '';
    const family = firstFamily(get('font-family'));
    // as fonts.css writes it ('fonts/X.woff2') or as the page's CSSOM gives it back (an absolute address)
    const file = (get('src').match(/url\(\s*['"]?[^'")]*?\bfonts\/([A-Za-z0-9._-]+\.woff2)['"]?\s*\)/) || [])[1];
    if (!family || !file) continue;
    const weights = (get('font-weight') || '400').split(/\s+/).map((w) => (w === 'normal' ? 400 : w === 'bold' ? 700 : Number(w)))
      .filter(Number.isFinite);
    const style = /italic|oblique/i.test(get('font-style')) ? 'italic' : 'normal';
    out.push({ family, style, min: Math.min(...weights), max: Math.max(...weights), file });
  }
  return out;
}

/** The first family of a `font-family` value, without its quotes. */
export function firstFamily(fontFamily) {
  const first = String(fontFamily ?? '').split(',')[0] || '';
  return first.trim().replace(/^['"]|['"]$/g, '').trim();
}

/** The faces that draw what is used: `used` is [{family, weight, style}] as
    the page computed them. Per use, the face of that family and style (a
    normal face when there is no italic one) whose weights cover it, else the
    nearest weight. Each file once, in the order of `faces`. A family we do
    not hold (a fallback such as sans-serif) takes nothing. */
export function pickFaces(used, faces) {
  const all = list(faces);
  const want = new Set();
  for (const u of list(used)) {
    if (!isObj(u)) continue;
    const family = firstFamily(u.family).toLowerCase();
    const weight = Number(u.weight) || 400;
    const style = /italic|oblique/i.test(String(u.style || '')) ? 'italic' : 'normal';
    let pool = all.filter((f) => f.family.toLowerCase() === family && f.style === style);
    if (!pool.length) pool = all.filter((f) => f.family.toLowerCase() === family);
    if (!pool.length) continue;
    const dist = (f) => (weight < f.min ? f.min - weight : weight > f.max ? weight - f.max : 0);
    const best = pool.reduce((a, f) => (dist(f) < dist(a) ? f : a));
    want.add(best.file);
  }
  return all.filter((f, i) => want.has(f.file) && all.findIndex((g) => g.file === f.file) === i);
}

/** One face, its file written in as a `data:` address. */
export function fontFaceCss(face, base64) {
  const weight = face.min === face.max ? `${face.min}` : `${face.min} ${face.max}`;
  return `@font-face { font-family: '${String(face.family).replace(/['\\]/g, '')}'; font-style: ${face.style}; ` +
    `font-weight: ${weight}; src: url(data:font/woff2;base64,${String(base64).replace(/[^A-Za-z0-9+/=]/g, '')}) format('woff2'); }`;
}

/* ── the file ─────────────────────────────────────────────────────────────── */

const XML_ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
/** Text made safe for XML, in an element or an attribute. */
export const xml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => XML_ESC[c]);
const n1 = (v) => Math.round(v * 10) / 10;

/** The whole file:
      box      {x, y, w, h}, the viewBox (exportBox); also its width and height
      cls      the drawing's classes (the labels turned off travel as classes)
      values   {'--tp-x': value}, the drawing's values resolved; written on the root
      css      the canvas's sheet, already resolved (resolveCss)
      fonts    the @font-face rules (fontFaceCss), joined
      defs     the symbols the drawing uses, as markup
      body     the drawing's layers, as markup
      title    the file's title (the map's name and the view)
      date     the date line
      ground   the ground's colour, as a rect under everything
      ink, dim, gilt, sans, mono, display: the title's colours and fonts
   Every value is escaped here; `css`, `fonts`, `defs` and `body` are markup
   the caller made safe. */
export function svgDocument(p) {
  const box = p.box;
  const values = isObj(p.values) ? p.values : {};
  const style = Object.entries(values).filter(([k, v]) => /^--[\w-]+$/.test(k) && typeof v === 'string' && v.trim())
    .map(([k, v]) => `${k}: ${v.trim()}`).join('; ');
  const cls = ['tp-canvas', ...String(p.cls || '').split(/\s+/).filter((c) => /^tp-[\w-]+$/.test(c) && c !== 'tp-canvas')];
  const head = `svg.tp-canvas .tp-x-title { font-family: ${p.display || 'serif'}; font-size: 18px; font-weight: 700; ` +
    `letter-spacing: 5px; fill: ${p.gilt || p.ink || 'black'}; }\n` +
    `svg.tp-canvas .tp-x-date { font-family: ${p.mono || 'monospace'}; font-size: 11px; fill: ${p.dim || p.ink || 'black'}; }`;
  const tx = n1(box.x + MARGIN);
  return '<?xml version="1.0" encoding="UTF-8"?>\n' +
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" class="${xml(cls.join(' '))}" ` +
    `viewBox="${box.x} ${box.y} ${box.w} ${box.h}" width="${box.w}" height="${box.h}" ` +
    `role="img" aria-label="${xml(p.title)}"${style ? ` style="${xml(style)}"` : ''}>\n` +
    `<title>${xml(p.title)}</title>\n` +
    `<desc>${xml(p.date)}</desc>\n` +
    `<style><![CDATA[\n${p.fonts ? `${p.fonts}\n` : ''}${String(p.css || '').replace(/\]\]>/g, '')}\n${head}\n]]></style>\n` +
    `<defs>${p.defs || ''}</defs>\n` +
    `<rect class="tp-ground" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" fill="${xml(p.ground || 'white')}"/>\n` +
    `<text class="tp-x-title" x="${tx}" y="${n1(box.y + 34)}">${xml(p.title)}</text>\n` +
    `<text class="tp-x-date" x="${tx}" y="${n1(box.y + 52)}">${xml(p.date)}</text>\n` +
    `<g class="tp-world">${p.body || ''}</g>\n</svg>\n`;
}

/** Every reference the file makes out of itself: an href (or xlink:href, or
    src) that is not '#…', a url( that is not a `data:` address, and any
    @import. A clean file gives []. */
export function externalRefs(svgText) {
  const text = String(svgText ?? '');
  // Only markup can point anywhere: the tags (their attributes) and the
  // style sheets. The words between tags are a name's or a note's own, and a
  // place called "see url(wiki)" is not a reference (it blocked every export,
  // 2026-11-17). A tag is read whole, quotes respected, so a `>` inside an
  // attribute does not end it early.
  const SHEET = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
  const sheets = [...text.matchAll(SHEET)].map((m) => m[1]).join('\n');
  // the sheets are read on their own, so they are taken out before the tags
  // are (a CDATA section would otherwise read as one more tag)
  const tags = (text.replace(SHEET, '').match(/<(?:[^<>"']|"[^"]*"|'[^']*')*>/g) || []).join('\n');
  const out = [];
  for (const m of tags.matchAll(/\b(?:xlink:href|href|src)\s*=\s*("([^"]*)"|'([^']*)')/gi)) {
    const v = (m[2] ?? m[3] ?? '').trim();
    if (!v.startsWith('#')) out.push(m[0]);
  }
  for (const m of `${tags}\n${sheets}`.matchAll(/url\(\s*(['"]?)([^)'"]*)/gi)) {
    if (!/^data:/i.test(m[2].trim())) out.push(m[0]);
  }
  for (const m of sheets.matchAll(/@import\b[^;]*/gi)) out.push(m[0]);
  return out;
}

/* ── the picture ──────────────────────────────────────────────────────────── */

/** A canvas larger than this fails in one browser or another (Safari on a
    phone stops at 16.7 million pixels; every browser at 16,384 a side in
    practice): the PNG is scaled down to fit, and says so. */
export const PNG_MAX_SIDE = 16384;
export const PNG_MAX_AREA = 16777216;

/** How a w x h drawing is painted: at `scale` (2) unless that breaks a limit,
    then at the largest scale that fits both. `reduced` says it was cut. */
export function pngPlan(w, h, options = {}) {
  const want = Number.isFinite(options.scale) && options.scale > 0 ? options.scale : 2;
  const maxSide = Number.isFinite(options.maxSide) ? options.maxSide : PNG_MAX_SIDE;
  const maxArea = Number.isFinite(options.maxArea) ? options.maxArea : PNG_MAX_AREA;
  const W = Math.max(1, Number(w) || 1);
  const H = Math.max(1, Number(h) || 1);
  let scale = Math.min(want, maxSide / W, maxSide / H, Math.sqrt(maxArea / (W * H)));
  // whole pixels never past a limit
  const fits = (s) => Math.ceil(W * s) <= maxSide && Math.ceil(H * s) <= maxSide && Math.ceil(W * s) * Math.ceil(H * s) <= maxArea;
  for (let i = 0; i < 20 && !fits(scale); i++) scale *= 0.999;
  return { scale, width: Math.max(1, Math.ceil(W * scale)), height: Math.max(1, Math.ceil(H * scale)), reduced: scale < want };
}

/* ── the site report's rows ───────────────────────────────────────────────── */

const DAY = 86400000;

/** Days from `now` (ms) to an expiry date, as SEALS counts them: the date at
    midnight UTC, rounded to whole days. Null without a date it can read. */
export function daysLeft(iso, now) {
  if (!iso || typeof iso !== 'string') return null;
  const t = Date.parse(`${iso}T00:00:00Z`);
  if (Number.isNaN(t)) return null;
  return Math.round((t - now) / DAY);
}

/** SEALS's "near": lapsed, or 14 days or fewer left. */
export const NEAR_DAYS = 14;

/** The certificates near their end, soonest first: [{name, host, kind,
    issuer, renews, expires, days}]. A certificate with no date is not near. */
export function nearCerts(certs, now) {
  const out = [];
  for (const c of list(certs)) {
    if (!isObj(c)) continue;
    const days = daysLeft(c.expires, now);
    if (days === null || days > NEAR_DAYS) continue;
    out.push({ name: words(c.name), host: words(c.host), kind: words(c.kind), issuer: words(c.issuer),
      renews: words(c.renews), expires: c.expires, days });
  }
  return out.sort((a, b) => (a.days - b.days) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

/** What the feed says is down now, among what this viewer's map holds:
    places, then services, each by name. A place: {kind: 'place', id, name,
    cause (the name of the place it is down behind, when that is on the map),
    by (who watches it, the feed's key)}. A service: {kind: 'service', id,
    name (its label), on (its place's name)}. */
export function downRows(data, feed) {
  const nodes = list(isObj(data) ? data.nodes : null).filter((n) => isObj(n) && typeof n.id === 'string' && n.id);
  const f = isObj(feed) ? feed : {};
  const live = isObj(f.nodes) ? f.nodes : {};
  const services = isObj(f.services) ? f.services : {};
  const by = isObj(f.confirmed_by) ? f.confirmed_by : {};
  const nameOf = new Map(nodes.map((n) => [n.id, words(n.name) || n.id]));
  const places = [];
  const svc = [];
  const seen = new Set();
  for (const n of nodes) {
    const info = live[n.id];
    if (isObj(info) && info.state === 'down') {
      const cause = typeof info.cause === 'string' && nameOf.has(info.cause) ? nameOf.get(info.cause) : '';
      places.push({ kind: 'place', id: n.id, name: nameOf.get(n.id), cause, by: typeof by[n.id] === 'string' ? by[n.id] : '' });
    }
    for (const link of list(n.links)) {
      if (!isObj(link)) continue;
      const key = serviceKey(n.id, link);
      if (seen.has(key)) continue;
      seen.add(key);
      const s = services[key];
      if (isObj(s) && s.state === 'down') svc.push({ kind: 'service', id: key, name: words(link.label) || key, on: nameOf.get(n.id) });
    }
  }
  const byName = (a, b) => {
    const ka = a.name.toLowerCase();
    const kb = b.name.toLowerCase();
    return ka < kb ? -1 : ka > kb ? 1 : (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  };
  return [...places.sort(byName), ...svc.sort(byName)];
}

/* ── the drawing on paper ─────────────────────────────────────────────────── */

/** Paper's ground: white, so a printed report spends no ink on it. */
export const PAPER_GROUND = '#ffffff';

/** The drawing's values for the site report: each `--tp-*` value as the
    light scheme gives it (`mapping` is topology.css's {'--tp-x': 'var(--tok)'},
    `light` the light scheme's {'--tok': value}), else the value on screen
    (`live`), with the ground white. A value that is not one token stays as
    it is on screen. */
export function paperValues(mapping, light, live) {
  const m = isObj(mapping) ? mapping : {};
  const l = isObj(light) ? light : {};
  const out = { ...(isObj(live) ? live : {}) };
  for (const [name, raw] of Object.entries(m)) {
    const tok = String(raw).trim().match(/^var\(\s*(--[\w-]+)\s*\)$/);
    if (tok && typeof l[tok[1]] === 'string' && l[tok[1]].trim()) out[name] = l[tok[1]].trim();
  }
  out['--tp-ground'] = PAPER_GROUND;
  return out;
}

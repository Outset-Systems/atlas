
import { serviceKey } from './alerts-model.js';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const list = (v) => (Array.isArray(v) ? v : []);
const words = (v) => (typeof v === 'string' ? v.trim() : '');
const pad2 = (n) => String(n).padStart(2, '0');


export function dateText(date) {
  const d = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export function slug(text) {
  const s = String(text ?? '').normalize('NFKD').replace(/\p{M}/gu, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
  return s || 'atlas';
}

export function fileName(title, ext, date) {
  const e = String(ext || '').toLowerCase().replace(/[^a-z0-9]/g, '') || 'svg';
  return `${slug(title)}-wiring-${dateText(date)}.${e}`;
}


export const MARGIN = 32;
export const HEAD = 64;
export const MIN_WIDTH = 440;

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

export function wideView(bounds, w, h) {
  const W = Number(w) > 0 ? Number(w) : 800;
  const H = Number(h) > 0 ? Number(h) : 600;
  const bw = Math.max(1, bounds.w);
  const bh = Math.max(1, bounds.h);
  const k = Math.min(W / bw, H / bh);
  return { k, x: (W - bw * k) / 2 - bounds.x * k, y: (H - bh * k) / 2 - bounds.y * k };
}


export function stripComments(css) {
  return String(css ?? '').replace(/\/\*[\s\S]*?\*\//g, '');
}

export function cssVarNames(css) {
  const out = [];
  for (const m of stripComments(css).matchAll(/var\(\s*(--[\w-]+)/g)) if (!out.includes(m[1])) out.push(m[1]);
  return out;
}

export function resolveCss(css, values) {
  const v = isObj(values) ? values : {};
  let out = stripComments(css);
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


export function parseFaces(fontsCss) {
  const out = [];
  for (const m of stripComments(fontsCss).matchAll(/@font-face\s*\{([^}]*)\}/g)) {
    const body = m[1];
    const get = (prop) => (body.match(new RegExp(`(?:^|;|\\s)${prop}\\s*:\\s*([^;]+)`)) || [])[1]?.trim() || '';
    const family = firstFamily(get('font-family'));
    const file = (get('src').match(/url\(\s*['"]?[^'")]*?\bfonts\/([A-Za-z0-9._-]+\.woff2)['"]?\s*\)/) || [])[1];
    if (!family || !file) continue;
    const weights = (get('font-weight') || '400').split(/\s+/).map((w) => (w === 'normal' ? 400 : w === 'bold' ? 700 : Number(w)))
      .filter(Number.isFinite);
    const style = /italic|oblique/i.test(get('font-style')) ? 'italic' : 'normal';
    out.push({ family, style, min: Math.min(...weights), max: Math.max(...weights), file });
  }
  return out;
}

export function firstFamily(fontFamily) {
  const first = String(fontFamily ?? '').split(',')[0] || '';
  return first.trim().replace(/^['"]|['"]$/g, '').trim();
}

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

export function fontFaceCss(face, base64) {
  const weight = face.min === face.max ? `${face.min}` : `${face.min} ${face.max}`;
  return `@font-face { font-family: '${String(face.family).replace(/['\\]/g, '')}'; font-style: ${face.style}; ` +
    `font-weight: ${weight}; src: url(data:font/woff2;base64,${String(base64).replace(/[^A-Za-z0-9+/=]/g, '')}) format('woff2'); }`;
}


const XML_ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const xml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => XML_ESC[c]);
const n1 = (v) => Math.round(v * 10) / 10;

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

export function externalRefs(svgText) {
  const text = String(svgText ?? '');
  const SHEET = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
  const sheets = [...text.matchAll(SHEET)].map((m) => m[1]).join('\n');
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


export const PNG_MAX_SIDE = 16384;
export const PNG_MAX_AREA = 16777216;

export function pngPlan(w, h, options = {}) {
  const want = Number.isFinite(options.scale) && options.scale > 0 ? options.scale : 2;
  const maxSide = Number.isFinite(options.maxSide) ? options.maxSide : PNG_MAX_SIDE;
  const maxArea = Number.isFinite(options.maxArea) ? options.maxArea : PNG_MAX_AREA;
  const W = Math.max(1, Number(w) || 1);
  const H = Math.max(1, Number(h) || 1);
  let scale = Math.min(want, maxSide / W, maxSide / H, Math.sqrt(maxArea / (W * H)));
  const fits = (s) => Math.ceil(W * s) <= maxSide && Math.ceil(H * s) <= maxSide && Math.ceil(W * s) * Math.ceil(H * s) <= maxArea;
  for (let i = 0; i < 20 && !fits(scale); i++) scale *= 0.999;
  return { scale, width: Math.max(1, Math.ceil(W * scale)), height: Math.max(1, Math.ceil(H * scale)), reduced: scale < want };
}


const DAY = 86400000;

export function daysLeft(iso, now) {
  if (!iso || typeof iso !== 'string') return null;
  const t = Date.parse(`${iso}T00:00:00Z`);
  if (Number.isNaN(t)) return null;
  return Math.round((t - now) / DAY);
}

export const NEAR_DAYS = 14;

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


export const PAPER_GROUND = '#ffffff';

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

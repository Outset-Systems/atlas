
import { CARD_W, CARD_H, vlanLabel } from './topology-model.js';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const words = (v) => (typeof v === 'string' ? v.trim() : (typeof v === 'number' && Number.isFinite(v) ? String(v) : ''));

export const LANE_GAP = 14;
export const MONO_ADVANCE = 0.6;
export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 3;
export const FIT_FLOOR = 0.002;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const num = (v, fallback) => (Number.isFinite(v) ? v : fallback);

export function cableGeometry(pa, pb, lane = 0, lanes = 1, ends = null) {
  const ax = pa.x + CARD_W / 2;
  const ay = pa.y + CARD_H / 2;
  const bx = pb.x + CARD_W / 2;
  const by = pb.y + CARD_H / 2;
  const off = (num(lane, 0) - (Math.max(1, num(lanes, 1)) - 1) / 2) * LANE_GAP;
  const offA = isObj(ends) ? num(ends.a, off) : off;
  const offB = isObj(ends) ? num(ends.b, off) : off;
  const vertical = Math.abs(by - ay) >= CARD_H;
  let x1; let y1; let x2; let y2; let c1x; let c1y; let c2x; let c2y;
  if (vertical) {
    const s = by > ay ? 1 : -1;
    x1 = ax + offA; y1 = s > 0 ? pa.y + CARD_H : pa.y;
    x2 = bx + offB; y2 = s > 0 ? pb.y : pb.y + CARD_H;
    const bend = Math.max(24, Math.abs(y2 - y1) / 2);
    c1x = x1; c1y = y1 + s * bend; c2x = x2; c2y = y2 - s * bend;
  } else {
    const s = bx >= ax ? 1 : -1;
    x1 = s > 0 ? pa.x + CARD_W : pa.x; y1 = ay + offA;
    x2 = s > 0 ? pb.x : pb.x + CARD_W; y2 = by + offB;
    const bend = Math.max(24, Math.abs(x2 - x1) / 2);
    c1x = x1 + s * bend; c1y = y1; c2x = x2 - s * bend; c2y = y2;
  }
  return { x1, y1, x2, y2, c1x, c1y, c2x, c2y, vertical };
}

export const EDGE_INSET = 16;
export const SIDE_INSET = 10;
export const PORT_REACH = 64;
const PORT_SHARE = 0.45;
const PORT_STEP = 3;
const MID_TRIES = [0.5, 0.42, 0.58, 0.34, 0.66];
const CHIP_AIR = 2;

const at = (positions, id) => {
  const p = positions instanceof Map ? positions.get(id) : positions && Object.prototype.hasOwnProperty.call(positions, id) ? positions[id] : null;
  return isObj(p) && Number.isFinite(p.x) && Number.isFinite(p.y) ? p : null;
};

function edgesOf(pa, pb) {
  const dy = pb.y - pa.y;
  if (Math.abs(dy) >= CARD_H) return dy > 0 ? ['bottom', 'top'] : ['top', 'bottom'];
  return pb.x >= pa.x ? ['right', 'left'] : ['left', 'right'];
}

export function spreadEnds(graph, positions) {
  const sides = new Map();
  const out = new Map();
  graph.links.forEach((link, index) => {
    if (link.layer !== 'cable') return;
    const pa = at(positions, link.a);
    const pb = at(positions, link.b);
    if (!pa || !pb) return;
    const [ea, eb] = edgesOf(pa, pb);
    out.set(link.id, { a: 0, b: 0 });
    for (const [id, edge, end, near, far] of [[link.a, ea, 'a', pa, pb], [link.b, eb, 'b', pb, pa]]) {
      const key = `${id}\u0000${edge}`;
      if (!sides.has(key)) sides.set(key, { edge, list: [] });
      const across = edge === 'top' || edge === 'bottom';
      sides.get(key).list.push({
        link, end, index,
        along: across ? far.x - near.x : far.y - near.y,
        off: across ? Math.abs(far.y - near.y) : Math.abs(far.x - near.x),
      });
    }
  });
  for (const { edge, list } of sides.values()) {
    list.sort((p, q) => (p.along - q.along) || (p.off - q.off) || (p.link.lane - q.link.lane) || (p.index - q.index));
    const half = edge === 'top' || edge === 'bottom' ? CARD_W / 2 - EDGE_INSET : CARD_H / 2 - SIDE_INSET;
    const n = list.length;
    const step = n > 1 ? Math.min(LANE_GAP, (2 * half) / (n - 1)) : 0;
    list.forEach((e, i) => { out.get(e.link.id)[e.end] = (i - (n - 1) / 2) * step; });
  }
  return out;
}

function boxGrid(cell = 96) {
  const cells = new Map();
  const span = (b, fn) => {
    for (let i = Math.floor(b.x / cell); i <= Math.floor((b.x + b.w) / cell); i++) {
      for (let j = Math.floor(b.y / cell); j <= Math.floor((b.y + b.h) / cell); j++) fn(`${i},${j}`);
    }
  };
  return {
    add(b) { span(b, (k) => { if (!cells.has(k)) cells.set(k, []); cells.get(k).push(b); }); },
    hits(b) {
      let hit = false;
      span(b, (k) => { if (!hit && (cells.get(k) || []).some((o) => boxesMeet(o, b))) hit = true; });
      return hit;
    },
  };
}

export function boxesMeet(p, q) {
  return p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h;
}

export function cardBox(thing, p) {
  const back = thing && thing.type === 'group' ? 5 : 0;
  return { x: p.x, y: p.y - back, w: CARD_W + back, h: CARD_H + back };
}

function polyline(g) {
  const pts = [];
  let run = 0;
  let prev = null;
  for (let i = 0; i <= 48; i++) {
    const p = pointOn(g, i / 48);
    if (prev) run += Math.hypot(p.x - prev.x, p.y - prev.y);
    pts.push({ x: p.x, y: p.y, run });
    prev = p;
  }
  return pts;
}

function along(pts, d) {
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].run >= d) {
      const a = pts[i - 1];
      const b = pts[i];
      const f = b.run > a.run ? (d - a.run) / (b.run - a.run) : 0;
      return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f };
    }
  }
  return { x: pts[pts.length - 1].x, y: pts[pts.length - 1].y };
}

export function cableLayout(graph, positions, options = {}) {
  const size = num(options && options.size, 9);
  const midText = options && typeof options.midText === 'function'
    ? options.midText
    : (l) => [vlanLabel(l), l.poe ? `${l.poe} W` : ''].filter(Boolean).join(' · ');
  const ends = spreadEnds(graph, positions);
  const cards = boxGrid();
  for (const t of graph.things) {
    const p = at(positions, t.id);
    if (!p) continue;
    const b = cardBox(t, p);
    cards.add({ x: b.x - CHIP_AIR, y: b.y - CHIP_AIR, w: b.w + 2 * CHIP_AIR, h: b.h + 2 * CHIP_AIR });
  }
  const chips = boxGrid();
  const free = (box) => !cards.hits(box) && !chips.hits(box);
  const out = new Map();
  const cables = [];
  graph.links.forEach((link, index) => {
    if (!ends.has(link.id)) return;
    const pa = at(positions, link.a);
    const pb = at(positions, link.b);
    const geom = cableGeometry(pa, pb, link.lane, link.lanes, ends.get(link.id));
    const entry = { geom, a: null, b: null, mid: null };
    out.set(link.id, entry);
    cables.push({ link, index, geom, entry, len: Math.hypot(pb.x - pa.x, pb.y - pa.y), pts: null });
  });

  for (const c of cables) {
    const text = clip(words(midText(c.link)), 28);
    if (!text) continue;
    for (const t of MID_TRIES) {
      const p = pointOn(c.geom, t);
      const box = chipBox(text, p.x, p.y, size);
      if (!free(box)) continue;
      c.entry.mid = { text, x: p.x, y: p.y, box };
      chips.add(box);
      break;
    }
  }

  const want = [];
  for (const c of cables) {
    if (c.link.aPort) want.push({ c, end: 'a', text: clip(c.link.aPort, 12) });
    if (c.link.bPort) want.push({ c, end: 'b', text: clip(c.link.bPort, 12) });
  }
  want.sort((p, q) => (p.c.len - q.c.len) || (p.c.index - q.c.index) || (p.end === q.end ? 0 : p.end === 'a' ? -1 : 1));
  for (const { c, end, text } of want) {
    if (!c.pts) c.pts = polyline(c.geom);
    const total = c.pts[c.pts.length - 1].run;
    const reach = Math.min(PORT_REACH, total * PORT_SHARE);
    for (let d = 0; d <= reach; d += PORT_STEP) {
      const p = along(c.pts, end === 'a' ? d : total - d);
      const box = chipBox(text, p.x, p.y, size);
      if (!free(box)) continue;
      c.entry[end] = { text, x: p.x, y: p.y, box };
      chips.add(box);
      break;
    }
  }
  return out;
}

const r1 = (v) => Math.round(v * 10) / 10;

export function cablePath(g) {
  return `M${r1(g.x1)} ${r1(g.y1)}C${r1(g.c1x)} ${r1(g.c1y)} ${r1(g.c2x)} ${r1(g.c2y)} ${r1(g.x2)} ${r1(g.y2)}`;
}

export function pointOn(g, t) {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  return { x: a * g.x1 + b * g.c1x + c * g.c2x + d * g.x2, y: a * g.y1 + b * g.c1y + c * g.c2y + d * g.y2 };
}

export function nearEnd(g, px) {
  const len = Math.hypot(g.x2 - g.x1, g.y2 - g.y1);
  return len > 0 ? Math.min(1 / 3, px / len) : 0.5;
}

export function chipBox(text, x, y, size = 9) {
  const chars = [...String(text ?? '')].length;
  const w = chars * size * MONO_ADVANCE + 6;
  const h = size + 4;
  return { x: x - w / 2, y: y - h / 2, w, h };
}

export function clip(text, max) {
  const chars = [...String(text ?? '')];
  if (chars.length <= max) return chars.join('');
  return chars.slice(0, Math.max(0, max - 1)).join('') + '…';
}

export function textWidth(text, size, bold = false) {
  let em = 0;
  for (const ch of String(text ?? '')) {
    if (/[MWmw@]/.test(ch)) em += 0.85;
    else if (/[IJfijlrt]/.test(ch)) em += 0.32;
    else if (/[A-Z]/.test(ch)) em += 0.62;
    else if (/[0-9]/.test(ch)) em += 0.53;
    else if (/[a-z]/.test(ch)) em += 0.51;
    else if (/[\s.,:;'|!·]/.test(ch)) em += 0.27;
    else em += 0.58;
  }
  return em * size * (bold ? 1.05 : 1);
}

export function clipTo(text, px, size, bold = false) {
  const chars = [...String(text ?? '')];
  if (textWidth(chars.join(''), size, bold) <= px) return chars.join('');
  let n = chars.length - 1;
  while (n > 0 && textWidth(`${chars.slice(0, n).join('')}…`, size, bold) > px) n--;
  return n > 0 ? `${chars.slice(0, n).join('').trimEnd()}…` : '';
}

export function fitView(bounds, w, h, options = {}) {
  const max = num(options.max, 1.25);
  const min = num(options.min, FIT_FLOOR);
  if (!(w > 0) || !(h > 0) || !isObj(bounds)) return { k: 1, x: 0, y: 0 };
  const pad = Math.max(0, num(options.pad, 40));
  const bw = Math.max(1, num(bounds.w, 0));
  const bh = Math.max(1, num(bounds.h, 0));
  const room = (side) => side - 2 * Math.min(pad, side / 4);
  const k = clamp(Math.min(room(w) / bw, room(h) / bh), min, max);
  return { k, x: (w - bw * k) / 2 - num(bounds.x, 0) * k, y: (h - bh * k) / 2 - num(bounds.y, 0) * k };
}

export function zoomAt(view, px, py, factor, options = {}) {
  const lo = Math.min(num(options.min, MIN_ZOOM), view.k > 0 ? view.k : MIN_ZOOM);
  const k = clamp(view.k * factor, lo, num(options.max, MAX_ZOOM));
  const wx = (px - view.x) / view.k;
  const wy = (py - view.y) / view.k;
  return { k, x: px - wx * k, y: py - wy * k };
}

export function centreOn(view, x, y, w, h) {
  return { k: view.k, x: w / 2 - x * view.k, y: h / 2 - y * view.k };
}

export function viewBox(view, w, h) {
  return { x: -view.x / view.k, y: -view.y / view.k, w: w / view.k, h: h / view.k };
}

export function linkSeen(pa, pb, box) {
  if (!isObj(pa) || !isObj(pb) || !isObj(box)) return false;
  const x0 = Math.min(pa.x, pb.x);
  const y0 = Math.min(pa.y, pb.y);
  const x1 = Math.max(pa.x, pb.x) + CARD_W;
  const y1 = Math.max(pa.y, pb.y) + CARD_H;
  return x0 <= box.x + box.w && x1 >= box.x && y0 <= box.y + box.h && y1 >= box.y;
}

export function neighbour(positions, id, dir) {
  if (!['left', 'right', 'up', 'down'].includes(dir)) return null;
  const entries = positions instanceof Map ? [...positions] : Object.entries(positions || {});
  const from = entries.find(([key]) => key === id);
  if (!from) return null;
  let win = null;
  let best = Infinity;
  for (const [key, p] of entries) {
    if (key === id || !isObj(p)) continue;
    const dx = p.x - from[1].x;
    const dy = p.y - from[1].y;
    const along = { right: dx, left: -dx, down: dy, up: -dy }[dir];
    const across = dir === 'left' || dir === 'right' ? dy : dx;
    if (along <= 0) continue;
    const score = along + 2 * Math.abs(across);
    if (score < best) { best = score; win = key; }
  }
  return win;
}

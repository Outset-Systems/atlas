/* TOPOLOGY's drawing geometry, with no DOM (2026-11-17): where a cable runs
   between two cards, where its ends and its middle words sit, how text is
   sized and cut, and the view's sums (fit, zoom, centre, what is on screen,
   the card next door). Moved unchanged out of topology-model.js, which keeps
   the graph, the layout and the questions the canvas asks; from it this file
   reads only the card's size and `vlanLabel`. Pure, so node can test it
   (tests/test_topology_model.mjs).

   The contract the drawing codes against:

     cableGeometry(pa, pb, l, n, ends) -> {x1, y1, x2, y2, c1x, c1y, c2x, c2y, vertical}
     spreadEnds(graph, positions)  -> Map cable id -> {a, b} along each end's edge
     cableLayout(graph, positions, opts) -> Map cable id -> {geom, a, b, mid}
     cablePath(geom)               -> an svg path `d`
     pointOn(geom, t)              -> {x, y} on the cable
     nearEnd(geom, px)             -> t about px from each end
     chipBox(text, x, y, size)     -> {x, y, w, h} round mono text
     boxesMeet(p, q), cardBox(thing, p) -> boxes meet; a card's box as drawn
     clip(text, max)               -> text cut to max characters with an ellipsis
     textWidth(text, size, bold), clipTo(text, px, size, bold) -> sans text sized and cut
     fitView(bounds, w, h, opts)   -> {k, x, y}
     zoomAt(view, px, py, f, opts) -> {k, x, y}
     centreOn(view, x, y, w, h)    -> {k, x, y}
     viewBox(view, w, h)           -> the world box {x, y, w, h} on screen
     linkSeen(pa, pb, box)         -> boolean
     neighbour(positions, id, dir) -> the nearest card that way, or null

   Positions are the TOP-LEFT corner of a card, as in topology-model.js. */

import { CARD_W, CARD_H, vlanLabel } from './topology-model.js';

/* the model's two lenient readers, copied here (it exports neither) */
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const words = (v) => (typeof v === 'string' ? v.trim() : (typeof v === 'number' && Number.isFinite(v) ? String(v) : ''));

/** How far apart two cables between the same two cards are drawn. */
export const LANE_GAP = 14;
/** JetBrains Mono's advance, as a share of its size: a chip's width is
    characters x size x this, so nothing needs measuring in the page. */
export const MONO_ADVANCE = 0.6;
/** The closest and furthest the canvas zooms by hand. */
export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 3;
/** The furthest Fit goes (2026-11-17): below MIN_ZOOM, so Fit always shows
    everything; only there so a zoom is never 0. */
export const FIT_FLOOR = 0.002;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const num = (v, fallback) => (Number.isFinite(v) ? v : fallback);

/** Where a cable runs between two cards (their top-left corners), as one
    cubic curve. Cards in different rows join bottom edge to top edge; cards
    side by side join side to side. `lane` of `lanes` moves it across, so
    parallel cables stand LANE_GAP apart. `ends` (2026-11-17), when given, is
    `{a, b}`: how far along its edge, from the middle, each end leaves (what
    spreadEnds answers), in place of the lane. */
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

/** How far in from each corner a cable may leave a card: along the top and
    bottom edges, and along the sides. */
export const EDGE_INSET = 16;
export const SIDE_INSET = 10;
/** A port chip stays this near its end of the cable, and within this share
    of the cable's length; the mid-cable label tries these points along it. */
export const PORT_REACH = 64;
const PORT_SHARE = 0.45;
const PORT_STEP = 3;
const MID_TRIES = [0.5, 0.42, 0.58, 0.34, 0.66];
/** The air kept between a chip and a card. */
const CHIP_AIR = 2;

const at = (positions, id) => {
  const p = positions instanceof Map ? positions.get(id) : positions && Object.prototype.hasOwnProperty.call(positions, id) ? positions[id] : null;
  return isObj(p) && Number.isFinite(p.x) && Number.isFinite(p.y) ? p : null;
};

/** The edge each end of a cable leaves by, as cableGeometry draws it. */
function edgesOf(pa, pb) {
  const dy = pb.y - pa.y;
  if (Math.abs(dy) >= CARD_H) return dy > 0 ? ['bottom', 'top'] : ['top', 'bottom'];
  return pb.x >= pa.x ? ['right', 'left'] : ['left', 'right'];
}

/** Where along its card's edge each cable end leaves (2026-11-17), so the
    cables meeting one card do not all leave from one point.

    Takes the graph and positions (top-left corners, an object or a Map).
    Returns a Map of cable id -> `{a, b}`: each end's distance from the middle
    of the edge it leaves by (cableGeometry's `ends`). Only cables whose two
    ends have a position are in it. On each edge of each card the ends are
    ordered by where their far card is along that edge (its middle; then how
    far off it is, then the lane, then the cable's order), so they do not
    cross on the way out; two parallel cables keep their lanes in the same
    order at both ends. N ends on one edge stand LANE_GAP apart about its
    middle, closer when that would pass EDGE_INSET (SIDE_INSET on a side) from
    the corner: so one cable leaves from the middle, and two parallel ones
    alone LANE_GAP apart, as before. */
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

/** Boxes kept in a coarse grid, to ask quickly whether a new one meets any. */
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

/** Do two boxes `{x, y, w, h}` overlap (touching edges do not)? */
export function boxesMeet(p, q) {
  return p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h;
}

/** A card's box as drawn: a folded group's back card stands 5 up and right. */
export function cardBox(thing, p) {
  const back = thing && thing.type === 'group' ? 5 : 0;
  return { x: p.x, y: p.y - back, w: CARD_W + back, h: CARD_H + back };
}

/** A cable's curve as a few dozen points with the length run so far. */
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

/** The point `d` along a polyline from its start. */
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

/** Every cable's curve and where its words go (2026-11-17).

    Takes the graph, positions, and `{midText, size}`: `midText(link)` the
    words midway (default its vlanLabel and its watts, ' · ' between),
    `size` the chips' text size (9). Returns a Map of cable id -> `{geom, a,
    b, mid}`, for every cable whose two ends have a position: `geom` from
    cableGeometry with the ends spreadEnds gives; `a`, `b` and `mid` each
    `{text, x, y, box}` (the chip's middle and chipBox), or null.

    Nothing overlaps: a chip is kept only where its box meets no card (with
    2 units of air) and no chip already placed. The mid-cable labels go first,
    in cable order, each at the middle or the first of a few points either
    side that is free; none free (a cable too short to hold it, say between
    two cards side by side) and it is left off. Then the port chips, nearest
    cables first (by the distance between their cards' middles, then cable
    order, then end A): each walks out along its cable from its end, 3 units
    at a time, to PORT_REACH or 45% of the cable, and sits at the first free
    place; none free and it is left off (the port is still in the cable's
    title). So on a crowded switch the nearest cables keep their port chips
    and it is the far ones that lose theirs, and every cable keeps its
    mid-cable label where it has room. The whole graph is laid at once, so a
    chip does not move as the view pans. */
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

/** The svg path `d` of a cable's geometry, to a tenth of a unit. */
export function cablePath(g) {
  return `M${r1(g.x1)} ${r1(g.y1)}C${r1(g.c1x)} ${r1(g.c1y)} ${r1(g.c2x)} ${r1(g.c2y)} ${r1(g.x2)} ${r1(g.y2)}`;
}

/** The point at `t` (0 at end A, 1 at end B) on a cable's curve. */
export function pointOn(g, t) {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  return { x: a * g.x1 + b * g.c1x + c * g.c2x + d * g.x2, y: a * g.y1 + b * g.c1y + c * g.c2y + d * g.y2 };
}

/** The `t` about `px` units in from end A (end B is 1 - t), never past a
    third of the way, so a short cable's two chips do not meet. */
export function nearEnd(g, px) {
  const len = Math.hypot(g.x2 - g.x1, g.y2 - g.y1);
  return len > 0 ? Math.min(1 / 3, px / len) : 0.5;
}

/** The box round a line of mono text of `size` px centred on x, y, with 3
    units of air each side: what a port chip or a VLAN label sits on. */
export function chipBox(text, x, y, size = 9) {
  const chars = [...String(text ?? '')].length;
  const w = chars * size * MONO_ADVANCE + 6;
  const h = size + 4;
  return { x: x - w / 2, y: y - h / 2, w, h };
}

/** Text cut to `max` characters, the last one an ellipsis when it was cut. */
export function clip(text, max) {
  const chars = [...String(text ?? '')];
  if (chars.length <= max) return chars.join('');
  return chars.slice(0, Math.max(0, max - 1)).join('') + '…';
}

/** About how wide a line of Alegreya Sans is at `size` px (2026-11-17), a
    little generous so a clipped line never runs into what is beside it:
    each character by its shape, as a share of the size. `bold` is a touch
    wider. Nothing is measured in the page, so the same text always clips the
    same way, on screen and in a file. */
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

/** Text cut so it is no wider than `px` at `size` (textWidth), the last
    character an ellipsis when it was cut. */
export function clipTo(text, px, size, bold = false) {
  const chars = [...String(text ?? '')];
  if (textWidth(chars.join(''), size, bold) <= px) return chars.join('');
  let n = chars.length - 1;
  while (n > 0 && textWidth(`${chars.slice(0, n).join('')}…`, size, bold) > px) n--;
  return n > 0 ? `${chars.slice(0, n).join('').trimEnd()}…` : '';
}

/** The zoom and pan that fit a box in a w x h window with `pad` round it:
    `{k, x, y}`, where a world point p is drawn at p * k + (x, y). Never
    closer than `max` (a small map is not blown up). Fit always shows
    everything (2026-11-17): it may go below MIN_ZOOM, the hand's limit, down
    to `min` (default FIT_FLOOR, only so a zoom is never 0), and a window
    narrower than twice the pad keeps a quarter of each side as its pad. */
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

/** Zoom by `factor` about the screen point px, py, which keeps the world
    point under it in place. The zoom stays between `min` (MIN_ZOOM unless
    given) and `max`; a view already further out than `min` (a Fit of a big
    map) may zoom in, and never jumps in when it zooms out (2026-11-17). */
export function zoomAt(view, px, py, factor, options = {}) {
  const lo = Math.min(num(options.min, MIN_ZOOM), view.k > 0 ? view.k : MIN_ZOOM);
  const k = clamp(view.k * factor, lo, num(options.max, MAX_ZOOM));
  const wx = (px - view.x) / view.k;
  const wy = (py - view.y) / view.k;
  return { k, x: px - wx * k, y: py - wy * k };
}

/** The same zoom, moved so the world point x, y is in the middle of a
    w x h screen. */
export function centreOn(view, x, y, w, h) {
  return { k: view.k, x: w / 2 - x * view.k, y: h / 2 - y * view.k };
}

/** The part of the world a w x h window shows. */
export function viewBox(view, w, h) {
  return { x: -view.x / view.k, y: -view.y / view.k, w: w / view.k, h: h / view.k };
}

/** Is a link between two cards (their top-left corners) on screen? True when
    the box round both cards meets `box`, so a long cable whose ends are both
    off screen is still drawn while it crosses it. */
export function linkSeen(pa, pb, box) {
  if (!isObj(pa) || !isObj(pb) || !isObj(box)) return false;
  const x0 = Math.min(pa.x, pb.x);
  const y0 = Math.min(pa.y, pb.y);
  const x1 = Math.max(pa.x, pb.x) + CARD_W;
  const y1 = Math.max(pa.y, pb.y) + CARD_H;
  return x0 <= box.x + box.w && x1 >= box.x && y0 <= box.y + box.h && y1 >= box.y;
}

/** The card an arrow key moves to: of the cards whose top-left lies that way
    (`left`, `right`, `up`, `down`) from this one's, the nearest, counting
    distance across the arrow twice. Ties go to the card listed first. */
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

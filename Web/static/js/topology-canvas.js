/* TOPOLOGY, the drawing (2026-11-17): ONE <svg class="tp-canvas"> holding
   everything, the cards included, so what is on screen is what a later stage
   can take out as a picture. Pure SVG: no HTML inside it, the emblems are
   <symbol>s in its own <defs> (the place's own emblem is read from
   static/icons once and kept as shapes only), the dotted ground is a
   <pattern>. Every rule that styles it is topology-canvas.css, which reads
   only the `--tp-*` values on the svg; a zone's hue rides on the element.

   What is drawn: a card per thing (emblem, name, address in mono, the state
   dot and "Watched by" from the feed the page already polls; a stub quieter,
   its kind in words; a folded group as a stack), each cable with a port chip
   at each end and its VLANs and PoE midway (the zone's hue, a stripe per
   VLAN on a trunk, cut into dashes when assumed, parallel cables apart), and
   routes and hosts as a second, quieter layer (a route a cable already
   carries is not drawn). Only what is near the screen is drawn: the part of
   the world in view and half as much again each side, drawn again when the
   view leaves it.

   Every sum (where a cable runs, where a chip sits, what is on screen, what
   is lit) is topology-model.js's; this file only writes the markup. It
   imports the state and the model, never topology.js. */

import { A, esc } from './config.js';
import * as M from './topology-model.js';
import { T, t, stubWords } from './topology-state.js';
import { watcherWords } from './nodes-cells.js';
import { t as nodesWord } from './nodes-text.js';

export const SVG = 'http://www.w3.org/2000/svg';
const W = M.CARD_W;
const H = M.CARD_H;

/** The feed's state as the card's class, and its word for a reader. */
const STATE_CLASS = {
  healthy: 'tp-st-up', degraded: 'tp-st-warn', down: 'tp-st-down',
  maintenance: 'tp-st-maint', slumbering: 'tp-st-slumber',
};
const STATE_WORD = { healthy: 'tp_lg_up', degraded: 'tp_lg_warn', down: 'tp_lg_down', maintenance: 'tp_lg_maint' };
const CABLE_KINDS = ['copper', 'fibre', 'dac', 'wireless', 'virtual'];

/* The emblems a card falls back to, by kind: line glyphs in the hand of the
   page's own icons (24 units, round caps). */
const G = 'class="tp-glyph"';
const GLYPHS = {
  network: `<rect ${G} x="2.5" y="8" width="19" height="8" rx="1.5"/><path ${G} d="M6 12h.01M9 12h.01M12 12h.01M15 12h.01M18 12h.01"/>`,
  physical: `<rect ${G} x="4" y="3.5" width="16" height="7" rx="1.2"/><rect ${G} x="4" y="13.5" width="16" height="7" rx="1.2"/><path ${G} d="M7.5 7h.01M7.5 17h.01M11 7h5M11 17h5"/>`,
  vm: `<path ${G} d="M12 3l8 4.5v9L12 21l-8-4.5v-9Z"/><path ${G} d="M4 7.5L12 12l8-4.5M12 12v9"/>`,
  internet: `<circle ${G} cx="12" cy="12" r="9"/><path ${G} d="M12 3a13.5 13.5 0 0 0 0 18a13.5 13.5 0 0 0 0-18M3 12h18"/>`,
  patch: `<rect ${G} x="3" y="7" width="18" height="10" rx="1"/><path ${G} d="M7 10v4M10.5 10v4M13.5 10v4M17 10v4"/>`,
  outlet: `<rect ${G} x="5" y="3.5" width="14" height="17" rx="2"/><path ${G} d="M10 9v2.5M14 9v2.5M10 15.5h4"/>`,
  group: `<rect ${G} x="7" y="3" width="13" height="9" rx="1.5"/><rect ${G} x="4" y="8" width="13" height="9" rx="1.5"/><path ${G} d="M4 21h13"/>`,
  other: `<circle ${G} cx="12" cy="12" r="3"/><path ${G} d="M12 3.5v5M12 15.5v5M3.5 12h5M15.5 12h5"/>`,
};
GLYPHS.switch = GLYPHS.network;
GLYPHS.container = GLYPHS.vm;

/* ── the place's own emblem, read once and kept as shapes ─────────────────── */

const LOGO_SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;
const SHAPES = new Set(['path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'ellipse', 'g']);
const GEOMETRY = ['d', 'cx', 'cy', 'r', 'rx', 'ry', 'x', 'y', 'width', 'height', 'x1', 'y1', 'x2', 'y2',
  'points', 'fill-rule', 'clip-rule', 'transform'];
const logos = new Map();   // slug -> 'loading' | 'ready' | 'failed'
let logoRedraw = 0;

function copyShapes(from, to, filled, rule) {
  for (const child of from.children) {
    const name = child.localName;
    if (!SHAPES.has(name)) continue;
    const el = document.createElementNS(SVG, name);
    for (const a of GEOMETRY) {
      const v = child.getAttribute(a);
      if (v !== null && !/url\(|javascript:/i.test(v)) el.setAttribute(a, v);
    }
    if (rule && !el.hasAttribute('fill-rule')) el.setAttribute('fill-rule', rule);
    if (name === 'g') copyShapes(child, el, filled, rule);
    else el.setAttribute('class', filled ? 'tp-glyph-fill' : 'tp-glyph');
    to.append(el);
  }
}

/** Start reading an emblem; the cards draw again once it is in. */
function wantLogo(slug) {
  if (logos.has(slug) || !T.svg) return;
  logos.set(slug, 'loading');
  fetch(`static/icons/${slug}.svg`).then((res) => (res.ok ? res.text() : Promise.reject(new Error(res.status))))
    .then((text) => {
      const root = new DOMParser().parseFromString(text, 'image/svg+xml').documentElement;
      if (!root || root.localName !== 'svg') throw new Error('not an svg');
      const sym = document.createElementNS(SVG, 'symbol');
      sym.id = `tp-l-${slug}`;
      const box = root.getAttribute('viewBox') || '';
      sym.setAttribute('viewBox', /^[\d.\s,-]+$/.test(box) ? box : '0 0 24 24');
      const filled = (root.getAttribute('fill') || '').toLowerCase() !== 'none';
      copyShapes(root, sym, filled, root.getAttribute('fill-rule'));
      if (!sym.children.length) throw new Error('no shapes');
      T.svg.querySelector('defs').append(sym);
      logos.set(slug, 'ready');
      cancelAnimationFrame(logoRedraw);
      logoRedraw = requestAnimationFrame(() => draw());
    })
    .catch(() => logos.set(slug, 'failed'));
}

/* ── reading the dataset ──────────────────────────────────────────────────── */

let nodesFor = null;
let nodeMap = new Map();
let zonesFor = null;
let hueMap = new Map();
function nodeOf(id) {
  if (nodesFor !== T.data) {
    nodesFor = T.data;
    nodeMap = new Map((T.data?.nodes || []).filter((n) => n && typeof n.id === 'string').map((n) => [n.id, n]));
  }
  return nodeMap.get(id) || null;
}
export const zones = () => (Array.isArray(T.data?.zones) ? T.data.zones : []);
const HEX = /^#[0-9a-f]{3,8}$/i;
function zoneHue(zoneId) {
  if (zonesFor !== T.data) {
    zonesFor = T.data;
    hueMap = new Map(zones().filter((z) => z && HEX.test(String(z.hue || ''))).map((z) => [z.id, z.hue]));
  }
  return zoneId ? hueMap.get(zoneId) || '' : '';
}

/** What the feed says of a thing: its state class and word, and who watches
    it. Nothing watching it (2026-11-17) draws no chip (the state dot already
    says there is no word) and is `unwatched`, for the reader's label. */
function liveOf(th) {
  const none = { cls: 'tp-st-none', state: '', by: '', unwatched: false };
  if (th.type !== 'place') return none;
  const feed = A.signalsFeed;
  if (!feed) return none;
  if (Array.isArray(feed.unmanaged) && feed.unmanaged.includes(th.id)) return { ...none, cls: 'tp-st-none tp-unmanaged' };
  const state = feed.nodes?.[th.id]?.state || '';
  const raw = feed.confirmed_by?.[th.id];
  const by = raw ? watcherWords(raw) : '';
  return { cls: STATE_CLASS[state] || 'tp-st-none', state, by, unwatched: !by };
}

/** The line under the address: a place's kind and role, a stub's kind in words. */
function kindLine(th) {
  if (th.type === 'stub') return stubWords(th.kind);
  if (th.type === 'group') return t('tp_group_open');
  const n = nodeOf(th.id);
  return [th.kind, n && typeof n.role === 'string' ? n.role : ''].filter(Boolean).join(' · ');
}

function glyphFor(th) {
  if (th.type === 'place') {
    const n = nodeOf(th.id);
    const slug = n && typeof A.nodeLogo === 'function' ? String(A.nodeLogo(n) || '') : '';
    if (LOGO_SLUG.test(slug)) {
      if (logos.get(slug) === 'ready') return `tp-l-${slug}`;
      wantLogo(slug);
    }
  }
  if (th.type === 'group') return 'tp-e-group';
  return `tp-e-${Object.prototype.hasOwnProperty.call(GLYPHS, th.kind) ? th.kind : 'other'}`;
}

/** A thing's name for a reader and for the find box's answer. */
export function readerLabel(th) {
  const live = liveOf(th);
  const name = th.type === 'group' ? t('tp_group', { n: th.count, kind: th.kind || t('tp_group_things') }) : th.name;
  return [name, th.ip, kindLine(th), live.state ? t(STATE_WORD[live.state] || 'tp_lg_none') : '',
    live.by ? t('tp_watched', { by: live.by }) : live.unwatched ? nodesWord('nodes_menu_unwatched') : ''].filter(Boolean).join(', ');
}

/* ── the svg ──────────────────────────────────────────────────────────────── */

let world = null;
let layer = {};

/** Make the one svg inside `stage`, with its defs and its layers. */
export function build(stage) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'tp-canvas');
  svg.setAttribute('tabindex', '0');
  svg.setAttribute('role', 'group');
  svg.innerHTML =
    '<defs><pattern id="tp-dots" width="24" height="24" patternUnits="userSpaceOnUse">' +
    '<circle class="tp-dot" cx="1" cy="1" r="1"/></pattern>' +
    Object.entries(GLYPHS).map(([k, body]) => `<symbol id="tp-e-${k}" viewBox="0 0 24 24">${body}</symbol>`).join('') +
    '</defs><rect class="tp-ground" width="100%" height="100%"/>' +
    '<g class="tp-world"><rect class="tp-grid" fill="url(#tp-dots)"/>' +
    '<g class="tp-ties"></g><g class="tp-cables"></g><g class="tp-chips"></g><g class="tp-cards"></g></g>';
  stage.prepend(svg);
  world = svg.querySelector('.tp-world');
  layer = {
    grid: svg.querySelector('.tp-grid'), ties: svg.querySelector('.tp-ties'),
    cables: svg.querySelector('.tp-cables'), chips: svg.querySelector('.tp-chips'),
    cards: svg.querySelector('.tp-cards'),
  };
  T.svg = svg;
  T.stage = stage;
  labels();
  return svg;
}

/** The labels the panel turns off, as classes on the svg (so they travel). */
export function labels() {
  if (!T.svg) return;
  T.svg.classList.toggle('tp-no-address', !T.labels.address);
  T.svg.classList.toggle('tp-no-kind', !T.labels.kind);
  T.svg.classList.toggle('tp-no-ports', !T.labels.ports);
}

/** The svg's size on screen. */
export function size() {
  const r = T.svg?.getBoundingClientRect();
  return { w: r?.width || 0, h: r?.height || 0 };
}

let rbox = null;   // the part of the world drawn now

function setTransform() {
  const { k, x, y } = T.view;
  world?.setAttribute('transform', `translate(${Math.round(x * 100) / 100} ${Math.round(y * 100) / 100}) scale(${Math.round(k * 10000) / 10000})`);
  layer.grid?.setAttribute('visibility', k < 0.35 ? 'hidden' : 'visible');
}

/** After a pan or a zoom: move the drawing, and draw again only when the
    screen has left the part already drawn. */
export function move() {
  setTransform();
  const { w, h } = size();
  const box = M.viewBox(T.view, w, h);
  if (!rbox || box.x < rbox.x || box.y < rbox.y || box.x + box.w > rbox.x + rbox.w || box.y + box.h > rbox.y + rbox.h) draw();
}

/** What is lit now: a VLAN from the panel, or a chain from lightPath. */
function marks() {
  if (!T.shown) return null;
  if (T.vlan !== null) {
    const lit = M.vlanLit(T.shown, T.vlan, zones());
    return { things: new Set(lit.things), links: new Set(lit.links), failedThing: null, failedLink: null };
  }
  if (T.path) {
    const m = M.pathMarks(T.path.things, T.path.links, T.path.failedAt);
    return { things: new Set(m.things), links: new Set(m.links), failedThing: m.failedThing, failedLink: m.failedLink };
  }
  return null;
}

const litClass = (lit, id, failed) => {
  if (!lit) return '';
  if (id === failed) return ' tp-lit tp-failed';
  return lit.has(id) ? ' tp-lit' : ' tp-dim';
};
const num = (v) => Math.round(v * 10) / 10;

function chip(text, x, y, cls) {
  const b = M.chipBox(text, x, y, 9);
  return `<rect class="tp-chip" x="${num(b.x)}" y="${num(b.y)}" width="${num(b.w)}" height="${num(b.h)}" rx="2"/>` +
    `<text class="${cls}" x="${num(x)}" y="${num(y)}">${esc(text)}</text>`;
}

function cableMarkup(l, g, cls) {
  const d = M.cablePath(g);
  const hues = M.stripes(l, zones()).filter((h) => HEX.test(h));
  const kind = CABLE_KINDS.includes(l.kind) ? l.kind : 'copper';
  const a = T.shown.byId.get(l.a);
  const b = T.shown.byId.get(l.b);
  const vl = M.vlanLabel(l);
  const title = [`${a?.name || l.a}${l.aPort ? ` ${l.aPort}` : ''} ↔ ${b?.name || l.b}${l.bPort ? ` ${l.bPort}` : ''}`,
    vl, l.poe ? t('tp_poe', { w: l.poe }) : '', l.speed, t(`tp_lg_${kind}`), l.state === 'assumed' ? t('tp_lg_assumed') : ''].filter(Boolean).join(', ');
  let s = `<g class="tp-link tp-cable tp-k-${kind}${l.state === 'assumed' ? ' tp-assumed' : ''}${hues.length > 1 ? ' tp-trunk' : ''}${cls}" data-link="${esc(l.id)}">` +
    `<title>${esc(title)}</title>`;
  // a zone's hue rides on a casing, as a map draws a road, so a pale hue
  // still reads on a pale ground (2026-11-17); the neutral ink needs none
  s += hues.length ? `<path class="tp-casing" d="${d}"/><path class="tp-wire" d="${d}" stroke="${hues[0]}"/>` : `<path class="tp-wire tp-wire-plain" d="${d}"/>`;
  for (let i = 1; i < hues.length; i++) {
    s += `<path class="tp-stripe" d="${d}" stroke="${hues[i]}" stroke-dasharray="10 ${10 * (hues.length - 1)}" stroke-dashoffset="${-10 * i}"/>`;
  }
  if (kind === 'fibre') s += `<path class="tp-core" d="${d}"/>`;
  if (l.state === 'assumed') s += `<path class="tp-gap" d="${d}"/>`;
  return `${s}</g>`;
}

/** A cable's words where cableLayout put them (2026-11-17): a port chip at
    each end, clear of every card and chip or left off, and the VLANs and
    watts midway, left off when the cable is too short to hold them. */
function chipsMarkup(lay, cls) {
  let s = '';
  for (const end of [lay.a, lay.b]) if (end) s += `<g class="tp-chip-g">${chip(end.text, end.x, end.y, 'tp-port')}</g>`;
  if (lay.mid) s += chip(lay.mid.text, lay.mid.x, lay.mid.y, 'tp-vl');
  return s ? `<g class="tp-labels${cls}">${s}</g>` : '';
}

const midWords = (l) => [M.vlanLabel(l), l.poe ? t('tp_poe', { w: l.poe }) : ''].filter(Boolean).join(' · ');

/* Every cable's curve and chips, laid for the whole graph at once so they do
   not move as the view pans; laid again only when the cards move. */
let laidFor = { graph: null, positions: null, sig: '', layout: null };
function cablesOf(shown, pos) {
  let sig = 0;
  for (const id in pos) sig = (sig * 31 + pos[id].x * 7 + pos[id].y * 13) % 1e15;
  const key = `${sig}|${t('tp_poe', { w: 1 })}`;
  if (laidFor.graph !== shown || laidFor.positions !== pos || laidFor.sig !== key) {
    laidFor = { graph: shown, positions: pos, sig: key, layout: M.cableLayout(shown, pos, { midText: midWords }) };
  }
  return laidFor.layout;
}

/** Every cable as it is drawn now: M.cableLayout's Map of id -> {geom, a, b,
    mid}, or null before there is a layout. A part that picks a cable by
    where it runs reads `geom` here: since 2026-11-17 the ends of cables
    meeting one card are spread along its edge, so cableGeometry from the
    lane alone is not where such a cable is drawn. */
export function cableShapes() {
  const pos = T.layout?.positions;
  return T.shown && pos ? cablesOf(T.shown, pos) : null;
}

/* Where a card's lines run out (2026-11-17): the name stops short of the
   state dot, the kind line short of the "Watched by" chip beside it. */
const TEXT_X = 46;
const NAME_ROOM = { place: W - 15.5 - 4 - TEXT_X, other: W - 8 - TEXT_X };

function cardMarkup(th, p, cls, tab) {
  const live = liveOf(th);
  const group = th.type === 'group';
  const name = group ? t('tp_group', { n: th.count, kind: th.kind || t('tp_group_things') }) : th.name;
  const kind = kindLine(th);
  const hue = th.type === 'stub' ? '' : zoneHue(th.zone);
  const word = live.by;
  const wordW = word ? M.chipBox(M.clip(word, 12), 0, 0, 8.5).w : 0;
  // the kind line shares the chip's height only when the address is above it
  const kindRoom = (word && th.ip ? W - 8 - wordW - 6 : W - 8) - TEXT_X;
  const label = esc(readerLabel(th));
  let s = `<g class="tp-card tp-${th.type} ${live.cls}${cls}" data-id="${esc(th.id)}" transform="translate(${num(p.x)} ${num(p.y)})" ` +
    `tabindex="${tab}" role="button" aria-label="${label}"><title>${label}</title>` +
    `<rect class="tp-ring" x="-4" y="-4" width="${W + 8}" height="${H + 8}" rx="7"/>`;
  if (group) s += `<rect class="tp-back" x="5" y="-5" width="${W}" height="${H}" rx="4"/>`;
  s += `<rect class="tp-box" width="${W}" height="${H}" rx="4"/>` +
    `<circle class="tp-disc-ground" cx="24" cy="${H / 2}" r="15"/>` +
    (hue ? `<circle class="tp-disc" cx="24" cy="${H / 2}" r="15" fill="${hue}"/>` : '') +
    `<use href="#${glyphFor(th)}" x="14" y="${H / 2 - 10}" width="20" height="20"/>` +
    `<text class="tp-name" x="${TEXT_X}" y="23">${esc(M.clipTo(name, th.type === 'place' ? NAME_ROOM.place : NAME_ROOM.other, 13, true))}</text>`;
  if (th.ip) s += `<text class="tp-addr" x="${TEXT_X}" y="38">${esc(M.clip(th.ip, 19))}</text>`;
  if (kind) s += `<text class="tp-kind" x="${TEXT_X}" y="${th.ip ? 53 : 38}">${esc(M.clipTo(kind, kindRoom, 10.5))}</text>`;
  if (th.type === 'place') s += `<circle class="tp-state" cx="${W - 11}" cy="12" r="4.5"/>`;
  if (word) {
    const b = M.chipBox(M.clip(word, 12), W - 8 - wordW / 2, 50, 8.5);
    s += `<g class="tp-watch"><rect x="${num(b.x)}" y="${num(b.y)}" width="${num(b.w)}" height="${num(b.h)}" rx="2"/>` +
      `<text x="${num(b.x + b.w / 2)}" y="${num(b.y + b.h / 2)}" text-anchor="middle" dominant-baseline="central">${esc(M.clip(word, 12))}</text></g>`;
  }
  return `${s}</g>`;
}

/** Draw the part of the world near the screen, from the state in T. */
export function draw() {
  if (!T.svg || !world) return;
  setTransform();
  const shown = T.shown;
  const pos = T.layout?.positions;
  if (!shown || !pos) {
    for (const g of [layer.ties, layer.cables, layer.chips, layer.cards]) g.innerHTML = '';
    T.drawn = new Set();
    rbox = null;
    return;
  }
  const { w, h } = size();
  const box = M.viewBox(T.view, w || 800, h || 600);
  const pad = Math.max(box.w, box.h) * 0.5;
  rbox = { x: box.x - pad, y: box.y - pad, w: box.w + 2 * pad, h: box.h + 2 * pad };
  for (const [k, v] of Object.entries(rbox)) layer.grid.setAttribute(k === 'w' ? 'width' : k === 'h' ? 'height' : k, num(v));

  const lit = marks();
  const laid = cablesOf(shown, pos);
  const ties = [];
  const cables = [];
  const chips = [];
  for (const l of shown.links) {
    if (l.shadowed) continue;
    const pa = pos[l.a];
    const pb = pos[l.b];
    if (!pa || !pb || !M.linkSeen(pa, pb, rbox)) continue;
    const cls = litClass(lit?.links, l.id, lit?.failedLink);
    const lay = l.layer === 'cable' ? laid.get(l.id) : null;
    const g = lay ? lay.geom : M.cableGeometry(pa, pb, l.lane, l.lanes);
    if (lay) {
      cables.push(cableMarkup(l, g, cls));
      chips.push(chipsMarkup(lay, cls));
    } else {
      ties.push(`<path class="tp-link tp-tie tp-${l.layer === 'parent' ? 'parent' : 'route'}${cls}" data-link="${esc(l.id)}" d="${M.cablePath(g)}"/>`);
    }
  }
  const ids = M.seen(pos, rbox, 0);
  const seenSet = new Set(ids);
  const order = shown.things.filter((th) => seenSet.has(th.id));
  const tabTo = seenSet.has(T.focusId) ? T.focusId : order[0]?.id;
  const cards = order.map((th) => {
    let cls = litClass(lit?.things, th.id, lit?.failedThing);
    if (T.selected === th.id) cls += ' tp-sel';
    if (T.matches.includes(th.id)) cls += ' tp-found';
    return cardMarkup(th, pos[th.id], cls, th.id === tabTo ? 0 : -1);
  });

  // a card that had the keyboard keeps it through the redraw
  const had = document.activeElement?.closest?.('.tp-card')?.dataset.id;
  layer.ties.innerHTML = ties.join('');
  layer.cables.innerHTML = cables.join('');
  layer.chips.innerHTML = chips.join('');
  layer.cards.innerHTML = cards.join('');
  T.drawn = seenSet;
  if (had && seenSet.has(had)) cardEl(had)?.focus({ preventScroll: true });
}

/** A drawn card's element, or null. */
export function cardEl(id) {
  return layer.cards?.querySelector(`.tp-card[data-id="${CSS.escape(id)}"]`) || null;
}

/** Make `id` the card Tab reaches, without drawing again. */
export function setTabStop(id) {
  T.focusId = id;
  for (const el of layer.cards?.querySelectorAll('.tp-card[tabindex="0"]') || []) el.setAttribute('tabindex', '-1');
  cardEl(id)?.setAttribute('tabindex', '0');
}

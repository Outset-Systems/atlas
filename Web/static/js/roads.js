
import { A, REDUCED, $, esc, zoneById, nodeById, FALLBACK_HUE } from './config.js';
import * as M from './world-model.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const overlay = $('overlay');
const markersEl = $('markers');

export function buildRoutes() {
  const g = document.createElementNS(SVGNS, 'g');
  g.id = 'routes';
  for (const r of A.DATA.routes || []) {
    const a = nodeById(r.from), b = nodeById(r.to);
    if (!a || !b || a.off_map || b.off_map) continue;
    const x1 = a.x / 100 * A.MAPW, y1 = a.y / 100 * A.MAPH;
    const x2 = b.x / 100 * A.MAPW, y2 = b.y / 100 * A.MAPH;
    const toVoid = b.y > 100 || a.y > 100;
    const p = document.createElementNS(SVGNS, 'path');
    if (toVoid) {
      p.setAttribute('d', `M ${x1} ${y1} C ${x1 + (x2 - x1) * 0.7} ${y1 + (y2 - y1) * 0.15}, ${x2} ${y1 + (y2 - y1) * 0.45}, ${x2} ${y2}`);
    } else {
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - Math.hypot(x2 - x1, y2 - y1) * 0.1;
      p.setAttribute('d', `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`);
    }
    p.setAttribute('class', `route route-${esc(r.kind)}${toVoid ? ' route-void' : ''}`);
    p.dataset.from = r.from;
    p.dataset.to = r.to;
    p.dataset.base = routeBaseHue(b);
    g.appendChild(p);
  }
  buildExits(g);
  overlay.appendChild(g);
  A.paintRoutes();
}

function buildExits(g) {
  const PAD = 14;
  for (const ex of A.levelExits?.() || []) {
    const a = nodeById(ex.from), far = nodeById(ex.to), dest = nodeById(ex.road?.to);
    if (!a || !far || !dest || a.off_map) continue;
    const x1 = a.x / 100 * A.MAPW, y1 = a.y / 100 * A.MAPH;
    const x2 = ex.at.x / 100 * A.MAPW, y2 = ex.at.y / 100 * A.MAPH;
    const p = document.createElementNS(SVGNS, 'path');
    p.setAttribute('d', `M ${x1} ${y1} L ${x2} ${y2}`);
    p.setAttribute('class', `route route-${esc(ex.kind)} route-exit`);
    p.dataset.from = ex.road.from;
    p.dataset.to = ex.road.to;
    p.dataset.exit = ex.to;
    p.dataset.base = routeBaseHue(dest);
    g.appendChild(p);

    const tag = document.createElementNS(SVGNS, 'text');
    const east = ex.at.x >= 99.9, west = ex.at.x <= 0.1;
    const anchor = east || (!west && ex.at.x > 85) ? 'end' : west || ex.at.x < 15 ? 'start' : 'middle';
    const tx = east ? x2 - PAD : west ? x2 + PAD : x2;
    const ty = Math.max(40, Math.min(A.MAPH - 16, ex.at.y <= 0.1 ? 40 : y2 - 12));
    tag.setAttribute('x', String(tx));
    tag.setAttribute('y', String(ty));
    tag.setAttribute('class', 'territory-tag route-exit-tag');
    tag.setAttribute('fill', routeBaseHue(far));
    tag.style.textAnchor = anchor;
    tag.dataset.to = ex.to;
    tag.setAttribute('role', 'button');
    tag.setAttribute('tabindex', '0');
    const more = ex.ids.length - 1;
    tag.setAttribute('aria-label', `Route out to ${ex.label.replace(/ \+\d+$/, '')}` +
      (ex.ids.length > 2 ? ` and ${ex.ids.length - 2} more` : '') + `. Go to ${far.name}` +
      (more ? ', the first of them.' : '.'));
    tag.textContent = ex.label;
    const go = (e) => { e.stopPropagation(); A.focusNode(ex.to); };
    tag.addEventListener('click', go);
    tag.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(e); }
    });
    g.appendChild(tag);
  }
}

export function routeBaseHue(node) {
  const z = zoneById(node.zone);
  return z?.net_hue || node.hue || (z ? z.hue : FALLBACK_HUE);
}

function paintReachLine(p) {
  const base = p.dataset.base || FALLBACK_HUE;
  const st = A.signalsFeed?.nodes?.[p.dataset.to]?.state;
  const hue = (st === 'down' || st === 'degraded')
    ? `color-mix(in srgb, ${base} 42%, var(--sem-warn))`
    : base;
  p.style.setProperty('--route-hue', hue);
  p.classList.toggle('reach-alarm', st === 'down');
}

A.paintRoutes = function paintRoutes() {
  const nodes = A.signalsFeed?.nodes || {};
  for (const p of overlay.querySelectorAll('path.route')) {
    const base = p.dataset.base || FALLBACK_HUE;
    const st = nodes[p.dataset.to]?.state;
    const hue = (st === 'down' || st === 'degraded')
      ? `color-mix(in srgb, ${base} 42%, var(--sem-warn))`
      : base;
    p.style.setProperty('--route-hue', hue);
    p.classList.toggle('route-alarm', st === 'down');
  }
  if (reachG) for (const p of reachG.querySelectorAll('path.reach-line')) paintReachLine(p);
};

export function buildTerritories() {
  const g = document.createElementNS(SVGNS, 'g');
  g.id = 'territories';
  for (const z of A.DATA.zones) {
    const pts = A.DATA.nodes
      .filter(n => n.zone === z.id && n.y >= -5 && n.y <= 105 && !n.off_map)
      .map(n => [n.x / 100 * A.MAPW, n.y / 100 * A.MAPH]);
    if (pts.length < 3) continue;
    const { cx, cy, points: d } = M.paddedHull(pts, A.MAPW * 0.045);
    const hue = z.net_hue || z.hue;
    const poly = document.createElementNS(SVGNS, 'polygon');
    poly.setAttribute('points', d);
    poly.setAttribute('class', 'territory');
    poly.style.setProperty('--zt-hue', hue);
    poly.dataset.zone = z.id;
    poly.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!A.netOn()) return;
      if (selectedZone === z.id) { A.clearHighlight(); A.closeCard?.(); }
      else A.highlightZone(z.id);
    });
    g.appendChild(poly);
    const tag = document.createElementNS(SVGNS, 'text');
    tag.setAttribute('x', String(cx));
    tag.setAttribute('y', String(cy));
    tag.setAttribute('class', 'territory-tag');
    tag.setAttribute('fill', hue);
    tag.textContent = `${z.name} · vlan ${z.vlan} · ${z.subnet}`;
    g.appendChild(tag);
  }
  overlay.insertBefore(g, overlay.firstChild);
}

let reachG = null;
function ensureReachG() {
  if (!reachG) { reachG = document.createElementNS(SVGNS, 'g'); reachG.id = 'reach'; overlay.appendChild(reachG); }
  return reachG;
}

let selectedId = null;
let selectedZone = null;
A.netSelected = () => selectedId;

function reachTargets(n) {
  return M.reachTargets(n, A.DATA.routes, (id) => nodeById(id)?.off_map);
}

function reachSegment(x1, y1, x2, y2, target) {
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - Math.hypot(x2 - x1, y2 - y1) * 0.14;
  const p = document.createElementNS(SVGNS, 'path');
  p.setAttribute('d', `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`);
  p.setAttribute('class', 'reach-line');
  p.dataset.to = target.id;
  p.dataset.base = routeBaseHue(target);
  paintReachLine(p);
  return p;
}

function revealSegment(p, delay) {
  if (REDUCED) return;
  const L = p.getTotalLength();
  p.style.strokeDasharray = String(L);
  p.style.strokeDashoffset = String(L);
  if (delay) p.style.transitionDelay = `${delay}ms`;
  p.getBoundingClientRect();
  p.style.strokeDashoffset = '0';
}

function litMarkers(originId, ids) {
  for (const mk of markersEl.children) {
    mk.classList.toggle('reach-lit', mk.dataset.id === originId || ids.has(mk.dataset.id));
    mk.classList.toggle('net-selected', mk.dataset.id === originId);
  }
}

function drawReach(n, targets, origin) {
  const g = ensureReachG();
  g.innerHTML = '';
  overlay.classList.add('reach-mode');
  const from = origin || n;
  const x1 = from.x / 100 * A.MAPW, y1 = from.y / 100 * A.MAPH;
  targets.forEach((tid) => {
    const t = nodeById(tid);
    if (!t) return;
    const p = reachSegment(x1, y1, t.x / 100 * A.MAPW, t.y / 100 * A.MAPH, t);
    g.appendChild(p);
    revealSegment(p, 0);
  });
  litMarkers(n.id, targets);
}

function drawChain(n, hops, origin, aside) {
  const g = ensureReachG();
  g.innerHTML = '';
  overlay.classList.add('reach-mode');
  const from = origin || n;
  const ox = from.x / 100 * A.MAPW, oy = from.y / 100 * A.MAPH;
  const stops = hops.map(nodeById).filter((t) => t && !t.off_map);
  let px = ox, py = oy;
  stops.forEach((t, i) => {
    const x = t.x / 100 * A.MAPW, y = t.y / 100 * A.MAPH;
    const p = reachSegment(px, py, x, y, t);
    g.appendChild(p);
    revealSegment(p, i * 220);
    px = x; py = y;
  });

  const onRoad = new Set(stops.map((t) => t.id));
  const asides = (aside || []).map(nodeById)
    .filter((t) => t && !t.off_map && !onRoad.has(t.id) && t.id !== n.id);
  asides.forEach((t, i) => {
    const p = reachSegment(ox, oy, t.x / 100 * A.MAPW, t.y / 100 * A.MAPH, t);
    p.classList.add('reach-aside');
    g.appendChild(p);
    revealSegment(p, (stops.length + i) * 220);
  });

  litMarkers(n.id, new Set([...onRoad, ...asides.map((t) => t.id)]));
}

A.highlightNode = function highlightNode(id) {
  const n = nodeById(id);
  if (!n) return;
  selectedId = id;
  drawReach(n, reachTargets(n));
};

A.highlightService = function highlightService(node, link) {
  const constellation = A.splitRing();
  const ci = constellation ? constellation.entries.findIndex((en) => en.link === link) : -1;
  const origin = ci >= 0 ? constellation.points[ci] : null;
  selectedId = node.id;
  const hops = Array.isArray(link.path) ? link.path.filter(Boolean) : [];
  if (hops.length) { drawChain(node, hops, origin, link.connects || []); return; }
  drawReach(node, M.serviceWeb(node, link, A.DATA.routes, (id) => nodeById(id)?.off_map).ids, origin);
};

A.highlightZone = function highlightZone(zoneId) {
  A.clearHighlight();
  selectedZone = zoneId;
  const members = new Set(A.DATA.nodes.filter((n) => n.zone === zoneId).map((n) => n.id));
  overlay.classList.add('reach-mode', 'zone-mode');
  for (const p of overlay.querySelectorAll('path.route')) {
    p.classList.toggle('zone-lit', members.has(p.dataset.to) || members.has(p.dataset.from));
  }
  for (const poly of overlay.querySelectorAll('.territory')) {
    poly.classList.toggle('territory-selected', poly.dataset.zone === zoneId);
  }
  for (const mk of markersEl.children) mk.classList.toggle('reach-lit', members.has(mk.dataset.id));
};

A.clearHighlight = function clearHighlight() {
  A.collapseConstellation();
  selectedId = null;
  selectedZone = null;
  if (reachG) reachG.innerHTML = '';
  overlay.classList.remove('reach-mode', 'zone-mode');
  for (const p of overlay.querySelectorAll('path.route')) p.classList.remove('zone-lit');
  for (const poly of overlay.querySelectorAll('.territory')) poly.classList.remove('territory-selected');
  for (const mk of markersEl.children) mk.classList.remove('reach-lit', 'net-selected');
};

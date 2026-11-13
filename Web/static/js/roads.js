/* Atlas — roads.js: the lines of the network layer.

   The roads between places and the exits that leave a region, each network's
   territory, and the reach web a click lights: a place's star, a service's
   chain, a whole network's roads. They share one alarm language: a line whose
   far end is dark takes on amber.

   Split out of world.js, which imports it and still says whether the layer is
   up (`A.netOn`, `A.toggleNet`); everything else reaches it through `A`, as it
   always did. */

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
    // routes are drawn from node x/y, not from the marker, so an off_map
    // place would otherwise leave its roads converging on empty ground
    if (!a || !b || a.off_map || b.off_map) continue;
    const x1 = a.x / 100 * A.MAPW, y1 = a.y / 100 * A.MAPH;
    const x2 = b.x / 100 * A.MAPW, y2 = b.y / 100 * A.MAPH;
    const toVoid = b.y > 100 || a.y > 100;   // one end lies beyond the table
    const p = document.createElementNS(SVGNS, 'path');
    if (toVoid) {
      // dive: run outward, then bend to descend near-vertically into the black
      p.setAttribute('d', `M ${x1} ${y1} C ${x1 + (x2 - x1) * 0.7} ${y1 + (y2 - y1) * 0.15}, ${x2} ${y1 + (y2 - y1) * 0.45}, ${x2} ${y2}`);
    } else {
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - Math.hypot(x2 - x1, y2 - y1) * 0.1;
      p.setAttribute('d', `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`);
    }
    p.setAttribute('class', `route route-${esc(r.kind)}${toVoid ? ' route-void' : ''}`);
    p.dataset.from = r.from;
    // each line takes the colour of the subnet/VLAN it reaches; painted live so it
    // picks up amber when its destination goes dark
    p.dataset.to = r.to;
    p.dataset.base = routeBaseHue(b);
    g.appendChild(p);
  }
  buildExits(g);
  overlay.appendChild(g);
  A.paintRoutes();
}

/* Exits (2026-11-11): inside a region, a road to a place out on a map above
   runs to the edge of the picture and is named there. regions.js says which
   (`A.levelExits`: none on the main map), already merged where several leave
   one place through the same spot. The line is the road's own `.route
   route-<kind>` with `route-exit`, and carries the road's real from/to and
   hue, so the feed's amber, the zone light and the layer toggle treat it as
   the road it is. The name is a `.territory-tag`; a click goes to the far
   place through `A.focusNode`, the one regions.js taught to leave the region. */
function buildExits(g) {
  const PAD = 14;                          // the name keeps this far inside the edge, map px
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
    // the name reads inward from the edge it stands on, and stays on the picture
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

/** ONE colour language for the network layer (2026-07-11): a road takes the
    net_hue of the VLAN it reaches — the same colour as that VLAN's territory
    hull, so ground and road read as one vocabulary. */
export function routeBaseHue(node) {
  const z = zoneById(node.zone);
  return z?.net_hue || node.hue || (z ? z.hue : FALLBACK_HUE);
}

/** A line (road or reach-line) whose destination is down/degraded takes on amber
    while keeping its VLAN tint — the one alarm language shared by the whole map. */
function paintReachLine(p) {
  const base = p.dataset.base || FALLBACK_HUE;
  const st = A.signalsFeed?.nodes?.[p.dataset.to]?.state;
  const hue = (st === 'down' || st === 'degraded')
    ? `color-mix(in srgb, ${base} 42%, var(--sem-warn))`
    : base;
  p.style.setProperty('--route-hue', hue);
  p.classList.toggle('reach-alarm', st === 'down');
}

/** Recolour every road from the live feed: a line whose destination is down (or
    degraded) takes on amber so you can trace trouble back through the network.
    The lit reach-web is repainted the same way, so a place that goes dark turns
    its connection yellow even while you're mid-inspection. */
A.paintRoutes = function paintRoutes() {
  const nodes = A.signalsFeed?.nodes || {};
  for (const p of overlay.querySelectorAll('path.route')) {
    const base = p.dataset.base || FALLBACK_HUE;
    const st = nodes[p.dataset.to]?.state;
    const hue = (st === 'down' || st === 'degraded')
      ? `color-mix(in srgb, ${base} 42%, var(--sem-warn))`   // some amber, but keep the VLAN's tint
      : base;
    p.style.setProperty('--route-hue', hue);
    p.classList.toggle('route-alarm', st === 'down');
  }
  if (reachG) for (const p of reachG.querySelectorAll('path.reach-line')) paintReachLine(p);
};

/* VLAN territories — a translucent colored hull around each zone's on-table nodes,
   revealed with the network layer so you can see how the realm is sectioned. */
export function buildTerritories() {
  const g = document.createElementNS(SVGNS, 'g');
  g.id = 'territories';
  for (const z of A.DATA.zones) {
    const pts = A.DATA.nodes
      .filter(n => n.zone === z.id && n.y >= -5 && n.y <= 105)   // on the table (exclude the void)
      .map(n => [n.x / 100 * A.MAPW, n.y / 100 * A.MAPH]);
    if (pts.length < 3) continue;
    const { cx, cy, points: d } = M.paddedHull(pts, A.MAPW * 0.045);
    const hue = z.net_hue || z.hue;
    const poly = document.createElementNS(SVGNS, 'polygon');
    poly.setAttribute('points', d);
    poly.setAttribute('class', 'territory');
    poly.style.setProperty('--zt-hue', hue);
    poly.dataset.zone = z.id;
    // click a territory (net mode) → light every road of that VLAN; again → release
    poly.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!A.netOn()) return;
      if (selectedZone === z.id) { A.clearHighlight(); A.closeCard?.(); }
      else A.highlightZone(z.id);
    });
    g.appendChild(poly);
    // the hull explains itself: a compact tag at its heart (top-anchored tags
    // from neighbouring hulls collided at the map's crown)
    const tag = document.createElementNS(SVGNS, 'text');
    tag.setAttribute('x', String(cx));
    tag.setAttribute('y', String(cy));
    tag.setAttribute('class', 'territory-tag');
    tag.setAttribute('fill', hue);
    tag.textContent = `${z.name} · vlan ${z.vlan} · ${z.subnet}`;
    g.appendChild(tag);
  }
  overlay.insertBefore(g, overlay.firstChild);   // behind the routes
}

/* ── Reachability — click a place (with the network layer on) to see what it
   can talk to: its roads light up, others dim, and its cross-links are drawn. ── */
let reachG = null;
function ensureReachG() {
  if (!reachG) { reachG = document.createElementNS(SVGNS, 'g'); reachG.id = 'reach'; overlay.appendChild(reachG); }
  return reachG;
}

let selectedId = null;    // the marker whose web is currently drawn (net mode)
let selectedZone = null;  // the VLAN whose roads are currently lit
A.netSelected = () => selectedId;

/** everything a place is charted to talk to: its declared reaches plus
    whatever a route wires it to, in either direction. The one definition —
    the ordinary click and the constellation's satellites both read it, so
    a new edge source can't be added to one and forgotten in the other. */
function reachTargets(n) {
  // an undrawn place cannot be the end of a lit road either
  return M.reachTargets(n, A.DATA.routes, (id) => nodeById(id)?.off_map);
}

/** one lit segment, from a point to a charted place. The star and the chain
    both draw with this, so a change to how a reach line looks or alarms is one
    edit rather than two that drift. */
function reachSegment(x1, y1, x2, y2, target) {
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - Math.hypot(x2 - x1, y2 - y1) * 0.14;
  const p = document.createElementNS(SVGNS, 'path');
  p.setAttribute('d', `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`);
  p.setAttribute('class', 'reach-line');
  p.dataset.to = target.id;
  p.dataset.base = routeBaseHue(target);
  paintReachLine(p);   // amber if the target is dark — one alarm language, map-wide
  return p;
}

/** ink a segment in. `delay` staggers a chain so the road is drawn hop by hop
    in the order the traffic takes it — the whole reason a chain is not a star.
    Under prefers-reduced-motion the line is simply there, as everywhere else. */
function revealSegment(p, delay) {
  if (REDUCED) return;
  const L = p.getTotalLength();
  p.style.strokeDasharray = String(L);
  p.style.strokeDashoffset = String(L);
  if (delay) p.style.transitionDelay = `${delay}ms`;
  p.getBoundingClientRect();
  p.style.strokeDashoffset = '0';
}

/** light the markers on a web: the origin is `net-selected`, everything the
    web touches is `reach-lit`, and the CSS dims the rest. */
function litMarkers(originId, ids) {
  for (const mk of markersEl.children) {
    mk.classList.toggle('reach-lit', mk.dataset.id === originId || ids.has(mk.dataset.id));
    mk.classList.toggle('net-selected', mk.dataset.id === originId);
  }
}

/** draw reach lines from node n to a set of target ids (shared by node- and
    service-level highlighting). `origin` (map %) lets a scattered service dot
    draw its own web from where *it* sits rather than from its host's marker —
    the whole point of THE CONSTELLATION is that the lines separate. */
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

/** draw a service's road as an ordered CHAIN of hops instead of a star.

   A star answers "what does this talk to?" — which is the right question for a
   place. For a service that is reached from outside it is the wrong one: it
   draws Jellyfin touching the gateway, the tunnel and the world as three
   equal spokes, when what is actually true is that they are consecutive. The
   traffic goes through each to get to the next, and a picture that cannot say
   "through" cannot show a path at all.

   So each hop is drawn from the previous one and inked in order, which is also
   the honest failure mode: if a hop's place is dark, exactly one segment of the
   road goes amber and you can see where the road stops. */
function drawChain(n, hops, origin, aside) {
  const g = ensureReachG();
  g.innerHTML = '';
  overlay.classList.add('reach-mode');
  const from = origin || n;
  const ox = from.x / 100 * A.MAPW, oy = from.y / 100 * A.MAPH;
  // an undrawn place cannot be a hop on a drawn road — same rule reachTargets
  // applies, for the same reason
  const stops = hops.map(nodeById).filter((t) => t && !t.off_map);
  let px = ox, py = oy;
  stops.forEach((t, i) => {
    const x = t.x / 100 * A.MAPW, y = t.y / 100 * A.MAPH;
    const p = reachSegment(px, py, x, y, t);
    g.appendChild(p);
    revealSegment(p, i * 220);
    px = x; py = y;
  });

  /* Things the service touches that are NOT hops on its road. CLOUDFLARE is
     the whole reason this exists: it answers for every public name in the
     realm, so it belongs in the picture — but no traffic of the realm passes
     through it (Pangolin was chosen precisely so there is no third-party data
     path), and drawing it as a hop would put a road on the map that does not
     carry anything. It gets a dashed aside from the origin instead: touched,
     not travelled. */
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

/** narrow the web to a single service. Three answers, most specific first:

      link.path      an ordered road — drawn as a chain, hop through hop
      link.connects  an unordered set — drawn as a star, the old behaviour
      (neither)      fall back to the host's own web

    When THE CONSTELLATION is open on this host, the web is drawn from the
    service's own scattered dot — derived here, from the ring constellation.js
    keeps, so the card layer never has to ferry map geometry through its signature. */
A.highlightService = function highlightService(node, link) {
  const constellation = A.splitRing();   // the ring standing now, if any (constellation.js)
  // matched by ENTRY, not by links.indexOf on the split node: a pass-through's
  // owning host is not the split place, but its dot is still in the ring
  const ci = constellation ? constellation.entries.findIndex((en) => en.link === link) : -1;
  const origin = ci >= 0 ? constellation.points[ci] : null;
  selectedId = node.id;
  const hops = Array.isArray(link.path) ? link.path.filter(Boolean) : [];
  if (hops.length) { drawChain(node, hops, origin, link.connects || []); return; }
  const targets = Array.isArray(link.connects) && link.connects.length
    ? new Set(link.connects) : reachTargets(node);
  drawReach(node, targets, origin);
};

/** light every road that touches a VLAN: its territory brightens, its roads +
    places lift out of the dim, everything else recedes (2026-07-11). */
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
  // the split is part of the transient selection layer: anything that clears
  // the highlight (a zone click, net-off, closing the card, a deselect)
  // gathers it too — one seam, instead of a hook remembered at every call
  // site. The first pass remembered four of five and territory clicks left
  // orphaned satellites, which is the whole argument.
  A.collapseConstellation();
  selectedId = null;
  selectedZone = null;
  if (reachG) reachG.innerHTML = '';
  overlay.classList.remove('reach-mode', 'zone-mode');
  for (const p of overlay.querySelectorAll('path.route')) p.classList.remove('zone-lit');
  for (const poly of overlay.querySelectorAll('.territory')) poly.classList.remove('territory-selected');
  for (const mk of markersEl.children) mk.classList.remove('reach-lit', 'net-selected');
};

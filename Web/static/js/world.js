/* Atlas — the world on the stage: zone labels, markers, the
   floating vision orb, the network layer, and the Depths/sky transitions. */

import { A, CFG, REDUCED, $, esc, zoneById } from './config.js';
import { unproject } from './project.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const overlay = $('overlay');
const zoneLabelsEl = $('zone-labels');
const markersEl = $('markers');
// THE CONSTELLATION's satellite dots live in their own layer, so every loop
// over #markers keeps meaning "the charted places" — the signals painter, the
// label fade and the reach painter never have to ask "is this a real place?"
const satsEl = $('satellites');

const nodeById = (id) => A.DATA.nodes.find(n => n.id === id);

/* ── Zone labels ─────────────────────────────────────── */
function buildZoneLabels() {
  for (const z of A.DATA.zones) {
    if (z.hide_label) continue;   // some VLANs keep their territory but drop the map text
    const kin = z.id === 'depths';
    const el = document.createElement('div');
    el.className = 'zone-label' + (kin ? ' depths-kin' : '');
    el.style.left = z.label_x + '%';
    el.style.top = z.label_y + '%';
    el.style.color = z.hue;
    // THE DEPTHS headline is scenery, not a label — it alone takes ~2.6× the
    // size (its opacity/tracking/data-line live with the .depths-kin CSS)
    el.style.fontSize = (kin ? Math.round(CFG.ZONE_LABEL_PX * 2.6) : CFG.ZONE_LABEL_PX) + 'px';
    el.innerHTML = `${esc(z.name)}<small>vlan ${esc(z.vlan)} · ${esc(z.subnet)}</small>`;
    zoneLabelsEl.appendChild(el);
  }
}

/* Every camera frame used to rewrite the opacity of every zone label and toggle
   a class on every marker, whether or not anything had changed — 1.6 ms of
   style invalidation per move, measured 2026-07-31. Both outputs are coarse:
   the opacity is invisible below ~2% steps and the label class is a single
   threshold. So quantize, remember, and write only on a real change. */
let lastDim = null, lastLabeled = null;

function updateZoneLabelFade() {
  // zone names read at survey zoom and fade as you fly closer; location labels
  // take over past the close-up threshold. With the network layer up the VLAN
  // labels hide (the territory hulls carry compact tags) — but THE DEPTHS is a
  // region marker for the descent, not a VLAN tag, so it stays.
  const t = Math.max(0, Math.min(1, (A.cam.k / A.fitScale() - 1) / 1.2));
  if (inDepths) {
    // Down in the dark the CSS owns the labels (`body.depths .zone-label`,
    // 0.28): an inline zoom-fade written here outranks that rule — which is
    // exactly what happened when the 07-31 perf pass moved the fade to
    // per-label inline styles, and the surface labels stopped sleeping.
    // Clearing the cache makes the first workstation-side move rewrite them.
    if (lastDim !== null) {
      lastDim = null;
      for (const el of zoneLabelsEl.children) el.style.opacity = '';
    }
  } else {
    const dim = netOn ? '0' : (CFG.ZONE_LABEL_MAX_OPACITY * (1 - t)).toFixed(2);
    if (dim !== lastDim) {
      lastDim = dim;
      zoneLabelsEl.style.opacity = '';   // fade per-label now, not the whole layer
      for (const el of zoneLabelsEl.children) {
        el.style.opacity = el.classList.contains('depths-kin') ? '' : dim;
      }
    }
  }
  const labeled = t > CFG.CLOSEUP_T;
  if (labeled !== lastLabeled) {
    lastLabeled = labeled;
    for (const mk of markersEl.children) mk.classList.toggle('labeled', labeled);
  }
}

/** Forget the cached fade state — the world was rebuilt underneath it, so the
    new labels and markers have never been written to. */
function resetFadeCache() { lastDim = null; lastLabeled = null; }

/* ── The Depths: scroll south past the table's edge ───── */
let inDepths = false;
let shoreSnap = false;   // one-shot: zoomed-in scroll into a shore settles the camera once

function toggleDepths(force) {
  const next = force ?? !inDepths;
  if (next === inDepths) return;   // stating a state you're in is a no-op, not a re-toast
  inDepths = next;
  document.body.classList.toggle('depths', inDepths);
  $('btn-depths').classList.toggle('lit', inDepths);
  A.showToast(inDepths
    ? 'You descend into the Depths — nothing down here leaves…'
    : 'You workstation. The sun returns to the sand.');
}

/** The viewport's edges in image-y — the projection every Depths decision
    hinges on, spelled once for checkVoid, updateShades and atSurvey. */
function viewBand() {
  return { top: (0 - A.cam.y) / A.cam.k, bottom: (innerHeight - A.cam.y) / A.cam.k };
}

// `userMove` is deliberately required everywhere it appears: the default
// would have to pick a side, and the safe-looking one (true) is the
// privileged one — a future caller that forgot the flag would silently
// regain the right to auto-descend, the exact bug this gate closed.
function checkVoid(userMove) {
  // wide hysteresis so the mode can't oscillate (rapid re-toggling of the
  // full-screen filter transition is what reads as flicker at the boundary)
  if (!A.MAPH) return;
  const bottomImgY = viewBand().bottom;
  // ENGAGING requires the user's own hand: a programmatic glide can carry the
  // view-bottom past the threshold in passing (splitting the app host frames a
  // ring whose bottom crosses it), and arriving in the black because the app
  // framed a view is never right. Deliberate descents state themselves
  // (centerDepths). RELEASE stays open to any move, so a glide back to the
  // table — home, a focus, a scene switch — always surfaces you.
  if (userMove && !inDepths && bottomImgY > A.MAPH * CFG.DEPTHS_ENGAGE) toggleDepths(true);
  else if (inDepths && bottomImgY < A.MAPH * CFG.DEPTHS_RELEASE) toggleDepths(false);
}

const _clamp01 = (v) => Math.max(0, Math.min(1, v));

/* The shade variables are written to the two elements that read them, never to
   `<body>`.

   Measured 2026-07-31: setting `--depth-t`/`--sky-t` on `<body>` and forcing a
   recalc cost **9.5 ms**; the same write on the two consumers cost **9.7 µs** —
   about 970× less. A custom property on `<body>` invalidates the inherited
   style of every element beneath it, and here that is the whole document (1083
   elements) so that two gradients can fade. This ran on every camera move, and
   it is the single reason scrolling was choppy.

   These are also the elements' *own* properties now, so `var(--depth-t)` in
   `#depth-map-shade`'s `opacity: calc(...)` resolves from itself rather than by
   inheritance. Nothing else in the CSS ever read them. */
const shadeEl = () => $('depth-map-shade');
const skyLightEl = () => $('sky-map-light');
let lastDepthQ = null, lastSkyQ = null;
let fadeTargets = null;

function updateShades(userMove) {
  if (!A.MAPH) return;
  const { top: topImgY, bottom: bottomImgY } = viewBand();
  const depthT = _clamp01((bottomImgY / A.MAPH - 0.98) / 0.20);   // 0 at table bottom → 1 into the void
  const skyT = _clamp01((-topImgY / A.MAPH) / (CFG.SKY_NORTH * 0.85)); // 0 at table top → 1 up in the sky

  // two decimals is finer than the eye can read on a 0–1 opacity ramp
  const depthQ = depthT.toFixed(2), skyQ = skyT.toFixed(2);
  if (depthQ !== lastDepthQ) { lastDepthQ = depthQ; shadeEl()?.style.setProperty('--depth-t', depthQ); }
  if (skyQ !== lastSkyQ) { lastSkyQ = skyQ; skyLightEl()?.style.setProperty('--sky-t', skyQ); }

  // table UI belongs to the table — anything OPEN (the ◈ legend, the ivory
  // card, THE INDEX, the scene flyout) fades out as the camera leaves for the
  // Upper Deck or the Depths, and returns when you do. Inline opacity is set
  // only while the element is open, so each one's own show/hide transition
  // keeps owning the off state.
  // Deliberately NOT skipped when the fade is unchanged: a card can be opened
  // while the camera is already off-table, and then the fade it needs never
  // changed value. Three cached elements and two string compares is nothing —
  // the cost here was only ever the `<body>` write above.
  const fade = 1 - _clamp01(Math.max(skyT, depthT) * 1.8);
  const fadeQ = fade.toFixed(2);
  if (!fadeTargets) fadeTargets = ['card', 'index-drawer'].map($).filter(Boolean);
  for (const el of fadeTargets) {
    // The split's card is its control surface, so while THE CONSTELLATION is
    // open it never fades: the ring's own framing parks a south host's
    // view-bottom inside the shore band (the app host sits at y=74.5), and past
    // half-fade the card also loses pointer-events — a ⁘ that cannot be
    // clicked in the very view it created (2026-08-01).
    if (el.id === 'card' && constellation) {
      if (el.style.opacity !== '') { el.style.opacity = ''; el.style.pointerEvents = ''; }
      continue;
    }
    const open = el.classList.contains('show') || el.classList.contains('open')
              || el.classList.contains('visible');
    if (open && fade < 1) {
      if (el.style.opacity !== fadeQ) el.style.opacity = fadeQ;
      el.style.pointerEvents = fade < 0.5 ? 'none' : '';
    } else if (el.style.opacity !== '') {
      el.style.opacity = '';
      el.style.pointerEvents = '';
    }
  }
  // scrolling into a shore while zoomed-in settles the camera back to the
  // framed default view for that shore, once per visit (2026-07-12).
  // User moves only — the snap is a response to *scrolling* into a shore; a
  // glide that grazes one is the app's own framing and must stand as aimed.
  // The depth gate sits at 0.75 (was 0.35) so the snap waits for the charts
  // to truly arrive rather than firing the moment the table's edge shows.
  const fit = A.fitScale();
  if (userMove && !shoreSnap && A.cam.k > fit * 1.06) {
    if (depthT > 0.75)    { shoreSnap = true; centerDepths(true); }
    else if (skyT > 0.35) { shoreSnap = true; A.ascend(); }
  }
  if (shoreSnap && depthT < 0.05 && skyT < 0.05) shoreSnap = false;
}

// checkVoid runs FIRST: on the move that crosses the engage threshold the
// label fade must already see `inDepths`, or it writes an inline opacity the
// depths CSS can't beat until the NEXT camera event — a stale bright frame
// exactly at the descent.
A.onCameraMove = (userMove) => { checkVoid(userMove); updateZoneLabelFade(); updateShades(userMove); };

/** center on the Depths (fit-zoom, horizontally centered) — the mirror of home */
function centerDepths(gliding = true) {
  // Going to the abyss IS the Depths — stated, not inferred from a threshold
  // this glide no longer trips (checkVoid ignores programmatic moves). Same
  // idiom as the 07-31 surfacing fix, pointed the other way.
  toggleDepths(true);
  A.cam.k = A.fitScale();
  A.cam.x = (innerWidth - A.MAPW * A.cam.k) / 2;
  A.cam.y = innerHeight * 0.5 - A.MAPH * CFG.DESCEND_TO * A.cam.k;
  A.clampCam();
  A.apply(gliding);
}

/** Context-aware recenter: back to the full survey — but if you're down in the
    Depths it recenters you *within* the Depths, not up on the sand. Used by the
    card/scene × buttons, the compass, and the network layer. */
A.recenter = function recenter(gliding = true) {
  if (inDepths) centerDepths(gliding);
  else A.home(gliding);
};

/** ⊖ (on the card) — zoom out around whatever is selected instead of around the
    middle of the screen.

    The +/− chrome zooms at the viewport centre, which is not where you are
    looking: the card sits low-right and `glideTo` deliberately parks the marker
    above centre, so two presses of − and the place you were reading has drifted
    off. This keeps it framed while the roads around it come into view — the
    move you want the moment a place is split into its services.

    **It stops at the survey, not at the camera's floor.** `cam.min` lets the
    table shrink inside the window, and the moment it does, the view bottom is
    past the southern edge and `checkVoid()` correctly drops you into the
    Depths — you asked to stay on a place and arrived in the black. So this
    button's floor is `fitScale()`: the whole table, framed, with your place
    still centred. Getting off the table is what ☾ is for.

    Returns 'floor' when there is nothing left to give back. */
A.pullBack = function pullBack() {
  const id = markersEl.querySelector('.mk.active')?.dataset.id || A.netSelected();
  const n = id ? nodeById(id) : null;
  const floor = Math.max(A.cam.min, A.fitScale());
  const atFloor = A.cam.k <= floor * 1.001;
  const k = Math.max(floor, A.cam.k / CFG.ZOOM_PULLBACK);  // at the floor, this IS the floor
  if (n) A.glideTo(n.x, n.y, k);            // still recentres, even with nothing left to give
  else if (!atFloor) A.zoomAt(innerWidth / 2, innerHeight / 2, k / A.cam.k);
  return atFloor ? 'floor' : 'ok';
};

/** ☾ — over the table's south edge into the black (and back) */
A.descend = function descend() {
  if (inDepths) {
    A.closeCard();
    A.home(true);
    // Say so outright rather than waiting for `checkVoid` to infer it. On a
    // portrait window the fitted table is exactly the window's height, so the
    // home position sits *inside* the engage/release hysteresis band and the
    // threshold never fires — pressing ☾ to come back up left you in the dark.
    // A deliberate surfacing is an intent, not something to re-derive.
    toggleDepths(false);
    return;
  }
  centerDepths(true);
};

/** rise to the realm above — clouds, the Upper Deck, the Chronicle.
    Fit-zoom + horizontally centered so the sky always frames cleanly. */
A.ascend = function ascend() {
  A.closeCard();
  A.cam.k = A.fitScale();
  A.cam.x = (innerWidth - A.MAPW * A.cam.k) / 2;
  A.cam.y = innerHeight * 0.5 + A.MAPH * CFG.ASCEND_TO * A.cam.k;
  A.clampCam();
  A.apply(true);
};

/* ── The vision orb (cloned mesa, floats — scenery, not a control) ──
   It rose to the sky on click until 2026-08-15. ☁ and the wheel both
   still do that, and the island stopped being the only route the moment the
   map tools grew a permanent one. */
function buildSkyIsland() {
  const island = $('sky-island');
  const shadow = $('sky-shadow');
  if (!island || !shadow) return;   // a theme without a sky island (themes/*.json "sky_island")
  const w = A.MAPW * CFG.MESA_W, h = A.MAPH * CFG.MESA_H;
  const px = (CFG.MESA_POS.x / 100) * A.MAPW, py = (CFG.MESA_POS.y / 100) * A.MAPH;
  island.style.width = w + 'px';
  island.style.height = h + 'px';
  island.style.left = px + 'px';
  island.style.top = py + 'px';
  // the cloud/islet visual is pure CSS now (no map-chunk blur) — light + flicker-free
  shadow.style.width = w * 0.9 + 'px';
  shadow.style.height = h * 0.7 + 'px';
  shadow.style.left = px + 'px';
  shadow.style.top = py + h * 0.5 + 'px';
}

/* The code-side record of the 2026-08-15 sky retirement (the design notes has the
   full row): `A.openSkyCard` and the `#sky-title` button that was its only
   caller both went — the sky's name was painted twice (a zone label over the
   clouds, since silenced with `hide_label`, plus the title) and the islet was
   a third route to the same idea. The region is named ONCE now, by the
   heading over the carousel, which nameRegionHeads() (ui.js) stamps from the
   zone's own dataset entry. The zone's lore survives in the dataset for the
   Desk; the islet is scenery. */

/* ── Network layer — the realm's roads, drawn in ink ──── */
let netOn = false;

function buildRoutes() {
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
  overlay.appendChild(g);
  A.paintRoutes();
}

/** ONE colour language for the network layer (2026-07-11): a road takes the
    net_hue of the VLAN it reaches — the same colour as that VLAN's territory
    hull, so ground and road read as one vocabulary. */
function routeBaseHue(node) {
  const z = zoneById(node.zone);
  return z?.net_hue || node.hue || (z ? z.hue : '#C9A554');
}

/** A line (road or reach-line) whose destination is down/degraded takes on amber
    while keeping its VLAN tint — the one alarm language shared by the whole map. */
function paintReachLine(p) {
  const base = p.dataset.base || '#C9A554';
  const st = A.signalsFeed?.nodes?.[p.dataset.to]?.state;
  const hue = (st === 'down' || st === 'degraded')
    ? `color-mix(in srgb, ${base} 42%, #FABD2F)`
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
    const base = p.dataset.base || '#C9A554';
    const st = nodes[p.dataset.to]?.state;
    const hue = (st === 'down' || st === 'degraded')
      ? `color-mix(in srgb, ${base} 42%, #FABD2F)`   // some amber, but keep the VLAN's tint
      : base;
    p.style.setProperty('--route-hue', hue);
    p.classList.toggle('route-alarm', st === 'down');
  }
  if (reachG) for (const p of reachG.querySelectorAll('path.reach-line')) paintReachLine(p);
};

/* VLAN territories — a translucent colored hull around each zone's on-table nodes,
   revealed with the network layer so you can see how the realm is sectioned. */
function convexHull(pts) {
  if (pts.length < 3) return pts;
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const q of p) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop(); lower.push(q); }
  const upper = [];
  for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop(); upper.push(q); }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

function buildTerritories() {
  const g = document.createElementNS(SVGNS, 'g');
  g.id = 'territories';
  for (const z of A.DATA.zones) {
    const pts = A.DATA.nodes
      .filter(n => n.zone === z.id && n.y >= -5 && n.y <= 105)   // on the table (exclude the void)
      .map(n => [n.x / 100 * A.MAPW, n.y / 100 * A.MAPH]);
    if (pts.length < 3) continue;
    const h = convexHull(pts);
    const cx = h.reduce((s, p) => s + p[0], 0) / h.length;
    const cy = h.reduce((s, p) => s + p[1], 0) / h.length;
    const pad = A.MAPW * 0.045;
    const d = h.map(([x, y]) => {
      const dx = x - cx, dy = y - cy, len = Math.hypot(dx, dy) || 1;
      return `${(x + dx / len * pad).toFixed(0)},${(y + dy / len * pad).toFixed(0)}`;
    }).join(' ');
    const hue = z.net_hue || z.hue;
    const poly = document.createElementNS(SVGNS, 'polygon');
    poly.setAttribute('points', d);
    poly.setAttribute('class', 'territory');
    poly.style.setProperty('--zt-hue', hue);
    poly.dataset.zone = z.id;
    // click a territory (net mode) → light every road of that VLAN; again → release
    poly.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!netOn) return;
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
  const targets = new Set(n.reaches || []);
  for (const r of A.DATA.routes || []) {
    if (r.from === n.id) targets.add(r.to);
    if (r.to === n.id) targets.add(r.from);
  }
  // an undrawn place cannot be the end of a lit road either
  for (const id of [...targets]) {
    if (nodeById(id)?.off_map) targets.delete(id);
  }
  return targets;
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
    service's own scattered dot — derived here, from this module's own state,
    so the card layer never has to ferry map geometry through its signature. */
A.highlightService = function highlightService(node, link) {
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

/* ── THE CONSTELLATION — one place broken into the services it carries ────────
   A host that runs seventeen things is one dot on this map, and that dot hides
   seventeen different network paths behind a single point. The ⁘ button on a
   place's card scatters its services into a ring of their own dots, draws a
   spoke to each, and draws each service's charted `connects` as its own faint
   road. Click one and the card becomes that service while its roads light and
   the rest recede — which is the question you actually had: *what does THIS
   service talk to?* (2026-07-31)

   Drawn in map coordinates inside #markers and #overlay, so the ring scales
   and pans with everything else and needs no per-frame work. */
let constellation = null;   // { id, entries: [{host, link, passing}], points: [{x,y}] }
const conLines = () => overlay.querySelector('#constellation');

/* A split ring is greyscale, and colour means health (2026-08-09).

   The dots used to wear each service's own charted hue, which made a ring of
   seventeen a colour wheel where every colour said only "this is a different
   service" — a thing the label beside it already said, better. Spending colour
   on identity leaves none for the one thing that changes, so the ring is now a
   spread of greys and red is reserved for a service that is actually down.
   the design notes's own rule, applied to a scene that had drifted from it: if
   everything glows, nothing does.

   The greys are the palette's warm neutrals rather than neutral #888. The sand
   table is a night map in BOTH themes — light mode reskins the chrome and never
   the render — so these read against warm sand in either, and a true-neutral
   grey would go faintly blue on it. Ordered light/dark/light so that adjacent
   dots in a ring separate instead of shading into one another. */
const SAT_GREYS = ['#DBD6CB', '#8E877C', '#C3BDB2', '#A49D92', '#CFC9BE', '#7F7A70',
                   '#B6B0A5', '#989187'];
const satGrey = (i) => SAT_GREYS[i % SAT_GREYS.length];

/** Every service a split of this place should ring: its own links, then every
    link of any OTHER place whose `connects` names this one — the services that
    PASS THROUGH it (a road, not a residence). Transit places (PANGOLIN,
    CLOUDFLARE, THE WILD) carry little or nothing of their own; what they ARE
    is what crosses them. One list, shared with the card's ⁘ existence check,
    so the two can never disagree about whether a place has anything to
    scatter. */
/* One marker click asks this three times in the same synchronous beat — the
   willSplit test, then openCard, then openConstellation — each scanning every
   node × every link. Memoize per id, keyed on the dataset's identity so it
   self-clears when the Desk swaps A.DATA (buildWorld runs on every edit-save).
   Callers only read the list (build DOM, take .length); none mutate it, so the
   shared reference is safe. */
let _svcEntriesData = null, _svcEntriesCache = new Map();
A.serviceEntriesFor = function serviceEntriesFor(id) {
  if (_svcEntriesData !== A.DATA) { _svcEntriesData = A.DATA; _svcEntriesCache = new Map(); }
  const hit = _svcEntriesCache.get(id);
  if (hit) return hit;
  const own = nodeById(id);
  if (!own) return [];
  const entries = (own.links || []).map((link) => ({ host: own, link, passing: false }));
  for (const other of A.DATA.nodes) {
    if (other.id === id) continue;
    for (const link of other.links || []) {
      if ((link.connects || []).includes(id)) entries.push({ host: other, link, passing: true });
    }
  }
  _svcEntriesCache.set(id, entries);
  return entries;
};

/** Where each service dot sits: a ring around the host, in map %, clockwise
    from due north.

    Past `CONSTELLATION_TWO_RING` services the dots **alternate between two
    radii**. One ring cannot hold them: arc spacing is 2πr/n, and the app host's
    fourteen services put adjacent labels 48 px apart when the labels are
    60–90 px wide — measured, four collisions. Pushing every other dot outward
    doubles the effective spacing without doubling the ring, which a single
    bigger radius would (and would then run the constellation off the table). */
function ringPoints(n, count) {
  const grow = 1 + Math.max(0, count - 6) * 0.045;
  const r = CFG.CONSTELLATION_R * grow;
  const two = count > CFG.CONSTELLATION_TWO_RING;
  const yScale = A.MAPW / (A.MAPH || A.MAPW);   // keep the ring round on a non-square map
  return Array.from({ length: count }, (_, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / count;
    const ri = r * (two && i % 2 ? CFG.CONSTELLATION_OUTER : 1);
    return { x: n.x + ri * Math.cos(a), y: n.y + ri * Math.sin(a) * yScale };
  });
}

/** A road is 2px of ink, which is not a click target — a pointer within a few
    pixels of a line reads as "on it" to the person aiming, and as a miss to
    `pointer-events: stroke`. So every drawn road gets an invisible twin on the
    same `d` with a fat stroke, carrying the click. Added BEFORE its visible
    line so it can never paint over one, and pointer-events lives on the twin
    only — the ink itself stays untouchable, and #constellation stays
    pointer-events:none for everything that is not a deliberate target. */
function hitTwin(d, svcIndex, title) {
  const hit = document.createElementNS(SVGNS, 'path');
  hit.setAttribute('d', d);
  hit.setAttribute('class', 'con-hit');
  hit.dataset.svc = String(svcIndex);
  hit.addEventListener('click', (e) => { e.stopPropagation(); focusService(svcIndex, true); });
  if (title) {
    const t = document.createElementNS(SVGNS, 'title');
    t.textContent = title;
    hit.appendChild(t);
  }
  return hit;
}

/** `auto` draws the ring's own structure and nothing else (2026-08-11).
    The spokes are the ring — host to each of its services — but each service's
    charted `connects` was ALSO drawn, as a faint curve reaching out to other
    places, and five services meant five more lines across the map. That is a
    network web by any other name, and it is the third thing a plain dot click
    was drawing unasked (after the network layer in v1.10.11 and the host's own
    reach in v1.10.13). The ⁘ split still draws them — asking for the split IS
    asking to see what its services touch — and either way a road inks the
    moment you pick a service, from its dot or its spoke. */
function drawConstellationLines(n, entries, points, auto) {
  const g = document.createElementNS(SVGNS, 'g');
  g.id = 'constellation';
  const hx = n.x / 100 * A.MAPW, hy = n.y / 100 * A.MAPH;
  points.forEach((p, i) => {
    const { host, link, passing } = entries[i];
    const sx = p.x / 100 * A.MAPW, sy = p.y / 100 * A.MAPH;
    // clicking any road of a service asks the same question its dot does —
    // "follow THIS one" — so both land on focusService, which draws the full
    // charted chain hop through hop (2026-08-09)
    const hops = Array.isArray(link.path) ? link.path.filter(Boolean).length : 0;
    const tip = `${link.label} — ${hops ? `follow its road, ${hops} hop${hops === 1 ? '' : 's'}`
                                        : 'follow its roads'}`;
    const spokeD = `M ${hx} ${hy} L ${sx} ${sy}`;
    g.appendChild(hitTwin(spokeD, i, tip));
    const spoke = document.createElementNS(SVGNS, 'path');
    spoke.setAttribute('d', spokeD);
    // a pass-through's spoke whispers — the road is borrowed, not owned
    spoke.setAttribute('class', 'con-spoke' + (passing ? ' con-pass' : ''));
    spoke.dataset.svc = String(i);
    // greyed with its dot, and repainted with it: the spoke and the satellite
    // are one mark, so they must never disagree about the service's state
    spoke.style.setProperty('--con-hue', satGrey(i));
    g.appendChild(spoke);
    // each service's own charted reach, drawn quiet until it is the one asked about
    for (const tid of (auto ? [] : link.connects || [])) {
      const t = nodeById(tid);
      if (!t) continue;
      const tx = t.x / 100 * A.MAPW, ty = t.y / 100 * A.MAPH;
      const mx = (sx + tx) / 2, my = (sy + ty) / 2 - Math.hypot(tx - sx, ty - sy) * 0.14;
      const d = `M ${sx} ${sy} Q ${mx} ${my} ${tx} ${ty}`;
      g.appendChild(hitTwin(d, i, tip));
      const line = document.createElementNS(SVGNS, 'path');
      line.setAttribute('d', d);
      line.setAttribute('class', 'con-line');
      line.dataset.svc = String(i);
      line.style.setProperty('--con-hue', routeBaseHue(t));
      g.appendChild(line);
    }
  });
  overlay.appendChild(g);
}

function drawSatellites(entries, points) {
  entries.forEach(({ host, link, passing }, i) => {
    const p = points[i];
    const el = document.createElement('div');
    el.className = 'mk mk-sat';
    el.dataset.sat = String(i);
    el.style.left = p.x + '%';
    el.style.top = p.y + '%';
    el.dataset.grey = satGrey(i);       // its resting colour, for the repaint
    el.style.setProperty('--mk-hue', satGrey(i));
    el.style.setProperty('--breathe-delay', (i * 0.18).toFixed(2) + 's');
    el.innerHTML =
      `<div class="mk-dot"><div class="mk-ring"></div><div class="mk-core"></div></div>` +
      `<div class="mk-label sat-label">` +
      `<span class="svc-health"${link.kuma ? ` data-kuma="${esc(link.kuma)}"` : ''}></span>` +
      // a passing service names the place it actually lives
      `${esc(link.label)}${passing ? `<span class="sat-host"> · ${esc(host.name.toLowerCase())}</span>` : ''}</div>`;
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      focusService(i);
    });
    satsEl.appendChild(el);
  });
  A.paintServiceHealth?.(satsEl);
  A.paintConstellationHealth();
}

/** Repaint a split ring: grey at rest, the alarm colour when in trouble.

    Runs on every signals poll as well as at draw time, so a service that falls
    over while its ring is open turns red where it stands rather than waiting
    for the ring to be redrawn.

    A service's own monitor decides when it has one; otherwise it inherits its
    HOST's state, which is the same fallback the service pane uses — a service
    on a dark host is not reachable whatever its own monitor last said.
    Degraded keeps the map-wide amber rather than staying grey: this is the one
    alarm language, and a scene where a faltering service looked perfectly well
    would be the only place on the map that hid one. */
A.paintConstellationHealth = function paintConstellationHealth() {
  if (!constellation) return;
  const svcs = A.signalsFeed?.services || {};
  const nodes = A.signalsFeed?.nodes || {};
  const g = conLines();
  constellation.entries.forEach(({ host, link }, i) => {
    const state = (link.kuma && svcs[link.kuma]?.state) || nodes[host.id]?.state;
    const alarm = (state === 'down' || state === 'degraded') ? A.stateHue?.(state) : null;
    const hue = alarm || satGrey(i);
    const dot = satsEl.querySelector(`.mk-sat[data-sat="${i}"]`);
    if (dot) {
      dot.style.setProperty('--mk-hue', hue);
      dot.style.setProperty('--mk-glow', hue + (alarm ? '66' : '33'));
      dot.classList.toggle('sat-down', state === 'down');
    }
    if (g) {
      for (const p of g.querySelectorAll(`.con-spoke[data-svc="${i}"]`)) {
        p.style.setProperty('--con-hue', hue);
      }
    }
  });
};

/** A service dot was chosen: the card becomes that service — on its OWN host,
    which for a pass-through is not the split place — and its roads light. */
function focusService(i, fromRoad) {
  if (!constellation) return;
  const { host, link } = constellation.entries[i];
  for (const el of satsEl.querySelectorAll('.mk-sat')) {
    el.classList.toggle('sat-active', el.dataset.sat === String(i));
  }
  const g = conLines();
  if (g) {
    g.classList.add('con-focus');
    for (const p of g.children) p.classList.toggle('con-lit', p.dataset.svc === String(i));
  }
  // the card is already open on this place — the split cannot exist otherwise.
  // Rebuilding it here tore down and reloaded its two Grafana vitals gauges
  // per satellite click, under an opaque service pane nobody could see through.
  // The pane goes up BEFORE the un-minimize: expanding first would re-arm the
  // parked vitals in the one tick where the pane hasn't covered them yet.
  A.showServiceDetail?.(host, link);   // highlightService finds the dot itself
  // A click on the DOT asks who this service is; a click on its ROAD asks where
  // it goes, and only the second draws (2026-08-11). showServiceDetail stopped
  // drawing for either, so the road click says so here rather than relying on a
  // side effect — and the pane's ◈ FOLLOW ITS ROAD is the same request made
  // after the fact.
  if (fromRoad) A.highlightService?.(host, link);
  A.setCardMinimized?.(false);
}

/** Scatter a place into its services — idempotent, so the automatic split can
    call it on every place click without gathering the ring it just drew.

    `auto` marks the split nobody asked for out loud (2026-08-09: clicking a
    dot should open its services). It differs from the ⁘ split in exactly two
    ways, and both follow from who started it:

      · the card stays EXPANDED. The ⁘ split folds it because the ring is what
        you asked for; an automatic one is a side effect of asking for the
        PLACE, and hiding the thing you clicked to read is a poor trade.
      · no toast. It would fire on every dot click, which is the definition of
        chrome nobody reads.

    Returns true when a ring is standing afterwards, so callers can tell a real
    split from a place that had nothing to scatter. */
A.openConstellation = function openConstellation(id, { auto = false } = {}) {
  if (constellation && constellation.id === id) return true;   // already standing
  A.collapseConstellation();
  const n = nodeById(id);
  const entries = A.serviceEntriesFor(id);
  if (!n || !entries.length) return false;

  // The ⁘ split raises the network layer (without the recenter ◈ does, because
  // the whole point is to stay on this place). The AUTOMATIC one does not, and
  // must not: raising it is a change to the WHOLE map — every VLAN road, every
  // territory fill and tag — and that is far too much to happen as a side
  // effect of clicking one dot (2026-08-10).
  //
  // The ring loses nothing by it. `.net-on` gates only `path.route`, the
  // territories and their tags; `#constellation` (the spokes and each service's
  // own roads) and `#reach` (the traced chain) carry no such rule, so the split
  // still draws, still reads, and its roads are still clickable with the layer
  // down. What goes away is the base-map spaghetti behind it.
  if (!auto && !netOn) A.toggleNet(true);

  const points = ringPoints(n, entries.length);
  constellation = { id, entries, points };
  drawConstellationLines(n, entries, points, auto);
  drawSatellites(entries, points);
  document.body.classList.add('constellation');
  // The host's own reach web is the ⁘ split's backdrop, and NOT drawn for the
  // automatic one (2026-08-10). Clicking a dot asks what this place
  // carries; answering with every line the place touches is a different, louder
  // question, and it puts a star on screen that the ring's own roads then have
  // to compete with. A service's road still draws the moment you ask for one —
  // click a satellite or one of its roads — which is the same rule as the
  // network layer: shown when asked for, not as a side effect of a click.
  if (!auto) A.highlightNode(id);
  // frame the ring: pull back enough that the widest satellite has room. Done
  // for the automatic split too — without it a ring opened at focus zoom hangs
  // its outer satellites off the edge of the screen.
  const k = Math.max(A.cam.min, A.fitScale() * CFG.CONSTELLATION_ZOOM);
  if (auto) {
    // the card stays up in this mode, so the ring has to be offset into the
    // screen the card leaves free — the same anchoring focusNode does for a
    // lone dot. Centring here would park half the satellites under 320px of
    // parchment, which is exactly the complaint the ⁘ split's fold answers.
    const a = A.focusAnchor?.(n.x, k);
    if (a) { A.setCardSide?.(a.cardLeft); A.glideTo(n.x, n.y, k, a.x); }
    else A.glideTo(n.x, n.y, k);
    A.setCardMinimized?.(false);
  } else {
    A.glideTo(n.x, n.y, k);
    // the ring is the subject now: the card folds to its headline so satellites
    // near the screen's edge aren't hiding under 320px of parchment. A satellite
    // click expands it again (focusService); the bar itself restores on click.
    A.setCardMinimized?.(true);
    const passing = entries.filter((e) => e.passing).length;
    A.showToast(`${n.name} split into ${entries.length} ${entries.length === 1 ? 'service' : 'services'}` +
      (passing ? ` (${passing} passing through)` : '') + ` — click a service or one of its roads to follow it.`);
  }
  return true;
};

/** Scatter a place into its services (or gather them back) — the ⁘ button. */
A.toggleConstellation = function toggleConstellation(id) {
  // gathering leaves the card exactly as it is — the ⁘ label flips via
  // body.constellation in CSS, so there is nothing to redraw
  if (constellation && constellation.id === id) {
    A.collapseConstellation();
    A.setCardMinimized?.(false);   // the ring is gathered — the card is the subject again
    return;
  }
  A.openConstellation(id);
};


A.collapseConstellation = function collapseConstellation() {
  if (!constellation) return;
  constellation = null;
  conLines()?.remove();
  satsEl.innerHTML = '';
  document.body.classList.remove('constellation');
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
A.netOn = () => netOn;

/** Is the camera already at the survey — the whole-table frame the roads are
    drawn for? Away means: zoomed in past ~1.1× fit, showing the sky or the
    void past the table's edges, or down in the Depths (whose home position
    can sit inside the engage/release band on a portrait window, so the flag
    is checked outright rather than inferred from coordinates). */
function atSurvey() {
  if (inDepths) return false;
  if (A.cam.k > A.fitScale() * 1.1) return false;
  const { top, bottom } = viewBand();
  const slack = A.MAPH * 0.02;
  return top > -slack && bottom < A.MAPH + slack;
}

/** ◈ — raise or drop the network layer.

    Raising it is two-stage when you are somewhere other than the survey: the
    roads are drawn for the whole-table frame, so the first press only travels
    there — from the Depths that is a stated surfacing (the underworld is
    deliberately roadless), anywhere else the usual recentre — and the second
    press, now at the survey, raises the lines with the ink reveal. At the
    survey already, one press raises them. Pressing with the lines up always
    lowers them, from anywhere.

    `force` pins the state (THE CONSTELLATION needs the roads up and does not
    want a toggle if they already are); with it, the two-stage rise is skipped
    and the camera is left alone, because a split is *about* a place and
    pulling back to the whole table would throw that place away. */
A.toggleNet = function toggleNet(force) {
  const forced = typeof force === 'boolean';
  if (forced && force === netOn) return;
  if (!forced && !netOn && !atSurvey()) {
    if (inDepths) A.descend();                    // up to the sand, stated
    else { A.closeCard?.(); A.recenter(true); }   // the ◈ pull-back, lines still down
    return;
  }
  netOn = forced ? force : !netOn;
  $('btn-net').classList.toggle('lit', netOn);
  if (!netOn) A.clearHighlight();   // which gathers any split too
  if (netOn && !forced) { A.closeCard?.(); A.recenter(true); }   // pull back so the whole web of roads is in frame
  if (netOn && !REDUCED) {
    // living ink: each road draws itself from the gateway outward
    overlay.querySelectorAll('path.route').forEach((p, i) => {
      const L = p.getTotalLength();
      p.style.transition = 'none';
      p.style.strokeDasharray = String(L);
      p.style.strokeDashoffset = String(L);
      p.getBoundingClientRect(); // reflow
      p.style.transition = '';
      setTimeout(() => { p.style.strokeDashoffset = '0'; }, 40 + i * 90);
    });
  }
  overlay.classList.toggle('net-on', netOn);
  updateZoneLabelFade();
  // the legend paragraph is gone (2026-07-12) — the territory edge tags
  // and the worded THE NETWORK button carry the explanation now
};

/* ── Markers ────────────────────────────────────────── */
/* ── Place editor: drag the dots (Settings → Move the dots) ─────────────
   Positions are overridden per-browser in localStorage so the canonical
   dataset is never touched; "copy" exports the moved coords to bake in. */
const POS_KEY = 'atlas-pos-overrides';
function posOverrides() {
  try { return JSON.parse(localStorage.getItem(POS_KEY) || '{}'); } catch { return {}; }
}
function applyOverrides() {
  const o = posOverrides();
  for (const n of A.DATA.nodes) {
    if (o[n.id]) { n.x = o[n.id].x; n.y = o[n.id].y; }
  }
}
A.editMode = false;
A.setEditMode = function setEditMode(on) {
  A.editMode = !!on;
  document.body.classList.toggle('editing-map', A.editMode);
  if (A.editMode) { A.closeCard?.(); }
};
A.copyPositions = function copyPositions() {
  const o = posOverrides();
  const rounded = Object.fromEntries(Object.entries(o).map(
    ([id, p]) => [id, { x: +p.x.toFixed(1), y: +p.y.toFixed(1) }]));
  const txt = JSON.stringify(rounded, null, 1);
  navigator.clipboard?.writeText(txt).catch(() => {});
  return Object.keys(rounded).length;
};
A.resetPositions = function resetPositions() {
  localStorage.removeItem(POS_KEY);
  location.reload();
};
/* persist the moved dots server-side — permanent + shared to every viewer */
A.savePositions = async function savePositions() {
  const o = posOverrides();
  if (!Object.keys(o).length) return { saved: 0 };
  const r = await fetch('api/v2/positions', {
    method: 'POST',
    // X-Atlas-Write proves the request came from the Atlas itself, not from
    // another origin riding the Hub's session cookie (see Web/security.py)
    headers: { 'Content-Type': 'application/json', 'X-Atlas-Write': '1' },
    body: JSON.stringify(o),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  const res = await r.json();
  localStorage.removeItem(POS_KEY);   // now canonical; drop the local overlay
  return res;
};

/* screen px → dataset percent, undoing the camera transform.

   🔴 Unproject FIRST. This is the edit-mode marker drag, and unlike pan or
   zoom it does not merely look wrong while tilted — it WRITES `n.x`/`n.y` into
   the dataset, so a marker dropped on a tilted table would be persisted at
   coordinates the surveyor never chose, and would look correct again the moment
   the table went flat. Flat, `unproject` is identity and this is the arithmetic
   it always was. (Arc T step two) */
function screenToPct(clientX, clientY) {
  const p = unproject(clientX, clientY);
  return {
    x: ((p.x - A.cam.x) / A.cam.k) / A.MAPW * 100,
    y: ((p.y - A.cam.y) / A.cam.k) / A.MAPH * 100,
  };
}

function buildMarkers() {
  applyOverrides();
  A.DATA.nodes.forEach((n, i) => {
    if (n.off_map) return;   // charted, not drawn — see schema `off_map`
    const zone = zoneById(n.zone);
    const hue = n.hue || (zone ? zone.hue : '#C9A554');   // per-node override (e.g. The GPU box's ember)
    const mk = document.createElement('div');
    const kin = n.zone === 'depths' || n.id === 'the-wild'; // the-wild glows out in the black
    mk.className = 'mk' + (kin ? ' depths-kin' : '') + (n.planned ? ' mk-planned' : '');
    mk.dataset.id = n.id;
    mk.dataset.kind = n.kind || 'vm';
    mk.dataset.shape = n.shape || ({ physical: 'square', network: 'square' }[n.kind] || 'circle');
    mk.dataset.hue = hue;              // base hue, so signals can swap it fully by state
    mk.style.left = n.x + '%';
    mk.style.top = n.y + '%';
    mk.style.setProperty('--mk-hue', hue);
    mk.style.setProperty('--mk-glow', hue + '55');
    mk.style.setProperty('--breathe-delay', (i * 0.35 % CFG.BREATHE_S).toFixed(2) + 's');
    mk.innerHTML = `
      <div class="mk-dot">
        <div class="mk-ring"></div>
        <div class="mk-core"></div>
      </div>
      <div class="mk-label">${esc(n.name)}</div>`;
    mk.addEventListener('click', (e) => {
      if (mk.dataset.dragged) { delete mk.dataset.dragged; return; }  // a drag isn't a click
      e.stopPropagation();
      /* A click on the MAP puts the Index away (2026-08-12) — the same
         reading as the wheel closing it in v1.10.16: you have stopped browsing
         a list and started working the map, and the drawer covers a third of
         what you just asked to look at. Scoped to this handler on purpose: it
         is the only place a click means "a marker on the map". Every other
         route into focusNode already closes whatever it came from (the Index
         list calls toggleDrawer(false) itself; the palette and the scenes each
         close()), so putting it here rather than inside focusNode leaves those
         seven call sites saying exactly what they already said. */
      A.toggleDrawer?.(false);
      focusNode(n.id, true, true);
    });
    // edit-mode drag
    mk.addEventListener('pointerdown', (e) => {
      if (!A.editMode) return;
      e.stopPropagation(); e.preventDefault();
      mk.setPointerCapture(e.pointerId);
      mk.classList.add('dragging');
      const move = (ev) => {
        const p = screenToPct(ev.clientX, ev.clientY);
        n.x = Math.max(0, Math.min(100, p.x));
        n.y = Math.max(-40, Math.min(140, p.y));
        mk.style.left = n.x + '%';
        mk.style.top = n.y + '%';
        mk.dataset.dragged = '1';
      };
      const up = () => {
        mk.classList.remove('dragging');
        mk.removeEventListener('pointermove', move);
        mk.removeEventListener('pointerup', up);
        const o = posOverrides();
        o[n.id] = { x: n.x, y: n.y };
        localStorage.setItem(POS_KEY, JSON.stringify(o));
        A.redrawLines?.();   // routes + territories follow the moved dot
      };
      mk.addEventListener('pointermove', move);
      mk.addEventListener('pointerup', up);
    });
    markersEl.appendChild(mk);
  });
}

function focusNode(id, glide = true, toggle = false) {
  const n = nodeById(id);
  if (!n) return;
  // a split belongs to one place; going anywhere else gathers it back in
  if (constellation && constellation.id !== id) A.collapseConstellation();
  // net mode: clicking the SELECTED place again deselects it — web + card close
  if (netOn && A.netSelected() === id) {
    A.clearHighlight();
    A.closeCard?.();
    return;
  }
  // atlas mode: clicking the SELECTED marker again releases it — the card closes
  // and the camera pulls back to the survey (marker clicks only; the Index and
  // palette always focus)
  if (toggle && !netOn && markersEl.querySelector('.mk.active')?.dataset.id === id) {
    A.closeCard?.();
    A.recenter(true);
    return;
  }
  for (const mk of markersEl.children) mk.classList.toggle('active', mk.dataset.id === id);
  // Clicking a dot opens what it carries (2026-08-09). The split owns the
  // camera when it happens — it frames a ring, which needs a wider shot than a
  // lone dot — so the focus glide below stands down rather than firing a
  // FOCUS_ZOOM move that a CONSTELLATION_ZOOM move overwrites in the same tick.
  // The automatic split leaves the network layer alone (2026-08-10), so this
  // reads the same either way; it stays here because the branch below needs it.
  const willSplit = (A.serviceEntriesFor?.(id) || []).length > 0;
  // with the network layer up, a click reveals reachability (stay at survey so the
  // web is in frame); otherwise fly to the place as usual
  if (netOn) A.highlightNode(id);
  else if (glide && !willSplit) {
    // the dot takes the share of the screen the card leaves free; when the
    // clamp can't grant it (east-edge places), the card crosses over instead
    const k = Math.max(A.fitScale() * CFG.FOCUS_ZOOM, 1.4);
    const a = A.focusAnchor(n.x, k);
    A.setCardSide?.(a.cardLeft);
    A.glideTo(n.x, n.y, k, a.x);
  }
  A.openCard(n);
  // after the card, so the ring's own camera framing is the last word and the
  // card is already sized when focusAnchor measures around it
  if (willSplit) A.openConstellation(id, { auto: true });
}
A.focusNode = focusNode;

/* Idempotent by construction: the Desk can change the dataset at any moment,
   and redrawing the world is how that becomes visible. Every builder appends,
   so the containers are emptied first — calling this twice used to give you
   two of every marker. */
A.buildWorld = function buildWorld() {
  A.collapseConstellation();   // its dots live in #satellites, its lines in #overlay
  resetFadeCache();            // the labels/markers about to be built are unwritten
  zoneLabelsEl.innerHTML = '';
  markersEl.innerHTML = '';
  overlay.querySelector('#routes')?.remove();
  overlay.querySelector('#territories')?.remove();
  applyOverrides();   // saved dot positions apply before lines/hulls are drawn
  buildZoneLabels();
  buildSkyIsland();
  buildTerritories();
  buildRoutes();
  buildMarkers();
  updateZoneLabelFade();   // the fresh labels/markers have never been written to
};

/* after a dot moves, rebuild the lines + hulls so they follow it (editor) */
A.redrawLines = function redrawLines() {
  overlay.querySelector('#routes')?.remove();
  overlay.querySelector('#territories')?.remove();
  buildTerritories();
  buildRoutes();
  if (netOn) { overlay.classList.add('net-on'); }   // keep them visible while editing
  A.paintRoutes?.();
};

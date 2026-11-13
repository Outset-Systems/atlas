/* Atlas — constellation.js: one place scattered into the services it carries,
   each as its own dot with its own roads (the long note below says why).

   Split out of world.js, which imports it; everything else reaches it through
   `A`, as it always did. `A.splitRing()` is the ring standing now, for the
   modules that only need to ask. */

import { A, CFG, $, esc, nodeById, svcKey } from './config.js';
import * as M from './world-model.js';
import { routeBaseHue } from './roads.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const overlay = $('overlay');
// THE CONSTELLATION's satellite dots live in their own layer, so every loop
// over #markers keeps meaning "the charted places" — the signals painter, the
// label fade and the reach painter never have to ask "is this a real place?"
const satsEl = $('satellites');

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
/** The ring standing now, or null: for the modules that only need to ask. */
A.splitRing = () => constellation;
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
  if (!nodeById(id)) return [];
  const entries = M.serviceEntries(A.DATA.nodes, id);
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
  return M.ringPoints(n, count, {
    radius: CFG.CONSTELLATION_R,
    twoRing: CFG.CONSTELLATION_TWO_RING,
    outer: CFG.CONSTELLATION_OUTER,
    yScale: A.MAPW / (A.MAPH || A.MAPW),   // keep the ring round on a non-square map
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
    const { link, passing } = entries[i];
    const sx = p.x / 100 * A.MAPW, sy = p.y / 100 * A.MAPH;
    // clicking any road of a service asks the same question its dot does —
    // "follow THIS one" — so both land on focusService, which draws the full
    // charted chain hop through hop (2026-08-09)
    const hops = Array.isArray(link.path) ? link.path.filter(Boolean).length : 0;
    const tip = `${link.label} — ${hops ? `follow its route, ${hops} hop${hops === 1 ? '' : 's'}`
                                        : 'follow its routes'}`;
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
      `<span class="svc-health" data-kuma="${esc(svcKey(link, host.id))}"></span>` +
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
    const state = svcs[svcKey(link, host.id)]?.state || nodes[host.id]?.state;
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
  A.showServiceDetail?.(host, link);   // highlightService finds the dot itself
  // A click on the DOT asks who this service is; a click on its ROAD asks where
  // it goes, and only the second draws (2026-08-11). showServiceDetail stopped
  // drawing for either, so the road click says so here rather than relying on a
  // side effect — and the pane's ◈ FOLLOW ITS ROAD is the same request made
  // after the fact.
  if (fromRoad) A.highlightService?.(host, link);
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
export const ringZoom = () => Math.max(A.cam.min, A.fitScale() * CFG.CONSTELLATION_ZOOM);

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
  if (!auto && !A.netOn()) A.toggleNet(true);

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
  const k = ringZoom();
  // The card stays up, as it is, so the ring is offset into the screen the card
  // leaves free: the same anchoring focusNode does for a lone dot. The ⁘ button
  // used to fold the card to its headline instead (the old card was 320px of
  // parchment); on the pull-tab card that hid the button just pressed, and the
  // owner asked for the button to split and gather and nothing else (2026-11-11).
  const a = A.focusAnchor?.(n.x, k);
  if (a) { A.setCardSide?.(a.cardLeft); A.glideTo(n.x, n.y, k, a.x); }
  else A.glideTo(n.x, n.y, k);
  if (!auto) {
    const passing = entries.filter((e) => e.passing).length;
    A.showToast(`${n.name} split into ${entries.length} ${entries.length === 1 ? 'service' : 'services'}` +
      (passing ? ` (${passing} passing through)` : '') + ` — click a service or one of its routes to follow it.`);
  }
  return true;
};

/** Scatter a place into its services (or gather them back) — the ⁘ button. */
A.toggleConstellation = function toggleConstellation(id) {
  // gathering leaves the card exactly as it is — the ⁘ label flips via
  // body.constellation in CSS, so there is nothing to redraw
  if (constellation && constellation.id === id) {
    A.collapseConstellation();
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

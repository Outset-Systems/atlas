/* Atlas — the world on the stage: zone labels, markers, the
   floating vision orb, the network layer, and the Depths/sky transitions.

   Three parts of it are files of their own, which this one imports (none of
   them imports this one): places.js is where each place stands and the drag that
   moves it, roads.js the routes, territories and reach web, constellation.js a
   place split into its services. This file keeps the labels, the Depths and
   the sky, whether the network layer is up, the markers, and the build. */

import { A, CFG, REDUCED, $, esc, zoneById, nodeById, FALLBACK_HUE } from './config.js';
import { placeLabels } from './label-model.js';
import { applyOverrides, onStyleArt, dragOnMap, keepSpot } from './places.js';
import { buildRoutes, buildTerritories } from './roads.js';
import { ringZoom } from './constellation.js';

const overlay = $('overlay');
const zoneLabelsEl = $('zone-labels');
const markersEl = $('markers');

/* ── Zone labels ─────────────────────────────────────── */
/* On a map style a network's name stands beside the places it names, on this
   level, wherever they are now (label-model.js): above the group, or on the
   side that is clear of other places, other names and the roads. A network with
   no place drawn here is not named here. A name dragged in Move places, or
   pinned in the style's file, stays where it was put on the main map. */
function autoZoneSpots() {
  const at = {};
  for (const n of A.DATA.nodes) if (!n.off_map) at[n.id] = { x: n.x, y: n.y };
  const charPx = CFG.ZONE_LABEL_PX * 1.14;        // a Cinzel cap and its 0.42em of letterspacing
  const groups = A.DATA.zones.map((z) => ({
    id: z.id,
    ids: A.DATA.nodes.filter((n) => n.zone === z.id && at[n.id]).map((n) => n.id),
    hw: Math.max(3, String(z.name || '').length * charPx / A.MAPW * 50),
    hh: CFG.ZONE_LABEL_PX * 1.9 / A.MAPH * 50,
  }));
  const roads = (A.DATA.routes || []).map((r) => [r.from, r.to]);
  return placeLabels(groups, at, roads);
}

function buildZoneLabels() {
  const styled = onStyleArt();
  if (A.levelPlaces && !styled) return;      // zone names are placed on the realm's own map
  const auto = styled ? autoZoneSpots() : {};
  for (const z of A.DATA.zones) {
    // some VLANs keep their territory but drop the map text. The Depths never
    // draw theirs: the section below the map carries the name in its own heading.
    // A style names a network where it was pinned, else where its places are.
    const pin = A.levelPlaces ? null : A.styleDraft().zones[z.id] || A.styleZones?.[z.id];
    const at = pin || auto[z.id];
    if (!at && (styled || z.hide_label || z.id === 'depths')) continue;
    const el = document.createElement('div');
    el.className = 'zone-label';
    // on a map style the network's names move with its places (Settings → Move places)
    el.addEventListener('pointerdown', (e) => {
      if (!A.editMode || !onStyleArt() || A.levelPlaces) return;   // a pin is the main map's
      let spot = null;
      dragOnMap(e, el, (p) => (spot = { x: Math.max(0, Math.min(100, p.x)), y: Math.max(-40, Math.min(140, p.y)) }),
        () => A.draftStyleSpot('zones', z.id, spot));
    });
    el.style.left = (at ? at.x : z.label_x) + '%';
    el.style.top = (at ? at.y : z.label_y) + '%';
    el.style.color = z.hue;
    el.style.fontSize = CFG.ZONE_LABEL_PX + 'px';
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
  // labels hide (the territory hulls carry compact tags).
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
        el.style.opacity = dim;
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
let inSky = false;       // ☁ lit, the sky's half of the descent's lit ☾
let onCentre = true;     // the view is on the map's middle; returning wakes the drift note
let shoreSnap = false;   // one-shot: zoomed-in scroll into a shore settles the camera once

function toggleDepths(force) {
  const next = force ?? !inDepths;
  if (next === inDepths) return;   // stating a state you're in is a no-op
  inDepths = next;
  document.body.classList.toggle('depths', inDepths);
  $('btn-depths').classList.toggle('lit', inDepths);
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
  if (inSky ? skyT < CFG.SKY_RELEASE : skyT > CFG.SKY_ENGAGE) {
    inSky = !inSky;
    $('btn-sky').classList.toggle('lit', inSky);
    document.body.classList.toggle('in-sky', inSky);   // the map's own tools step back (atlas.css)
  }
  const offCentre = Math.abs((topImgY + bottomImgY) / 2 / A.MAPH - 0.5);
  if (onCentre ? offCentre > CFG.CENTRE_LEAVE : offCentre < CFG.CENTRE_ENTER) {
    onCentre = !onCentre;
    if (onCentre) A.wakeDrift?.();
  }

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
    if (el.id === 'card' && A.splitRing()) {
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
  A.cam.y = A.landOn('abyss');
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
  A.cam.y = A.landOn('chronicle');
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
    // living ink: each road draws itself from the gateway outward (an exit
    // keeps its own dashes, which the inline dash here would overwrite)
    overlay.querySelectorAll('path.route:not(.route-exit)').forEach((p, i) => {
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
  document.body.classList.toggle('net-on', netOn);
  updateZoneLabelFade();
  // the legend paragraph is gone (2026-07-12) — the territory edge tags
  // and the worded THE NETWORK button carry the explanation now
};

/* ── Markers ────────────────────────────────────────── */
function buildMarkers() {
  applyOverrides();
  A.DATA.nodes.forEach((n, i) => {
    if (n.off_map) return;   // charted, not drawn — see schema `off_map`
    const zone = zoneById(n.zone);
    const hue = n.hue || (zone ? zone.hue : FALLBACK_HUE);   // per-node override (e.g. The GPU box's ember)
    const mk = document.createElement('div');
    // anything charted below the table (the edge, the internet) lives in the
    // black band, so it glows there; dimming it left a pin nobody could read
    const kin = n.zone === 'depths' || n.y > 100;
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
    // A map style may give a place its own sigil (`logos` in its sidecar): the
    // marker wears the emblem the card shows. Slug-checked here and on the server.
    const sigil = String(A.styleLogos?.[n.id] || '');
    if (/^[a-z0-9][a-z0-9-]{0,39}$/.test(sigil)) {
      mk.classList.add('mk-sigil');
      const core = mk.querySelector('.mk-core');
      core.style.webkitMaskImage = core.style.maskImage = `url("static/icons/${sigil}.svg")`;
    }
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
      if (A.levelPlaces) { A.pinDrag?.(e, mk, n); return; }   // a pin on this region, not a move
      if (!A.editMode) return;
      const styled = onStyleArt();
      // on the realm's art a style's spot is not the one a drag would save
      if (!styled && A.stylePlaces?.[n.id]) return;
      dragOnMap(e, mk, (p) => {
        n.x = Math.max(0, Math.min(100, p.x));
        n.y = Math.max(-40, Math.min(140, p.y));
        return n;
      }, () => {
        if (styled) A.draftStyleSpot('places', n.id, n);
        else keepSpot(n.id, n);
        A.redrawLines?.();   // routes + territories follow the moved dot
      });
    });
    markersEl.appendChild(mk);
  });
}

function focusNode(id, glide = true, toggle = false) {
  const n = nodeById(id);
  if (!n) return;
  // a split belongs to one place; going anywhere else gathers it back in
  if (A.splitRing() && A.splitRing().id !== id) A.collapseConstellation();
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
    const k = A.focusScale();        // the scale the zoom ceiling is measured from
    const a = A.focusAnchor(n.x, k);
    A.setCardSide?.(a.cardLeft);
    A.glideTo(n.x, n.y, k, a.x);
  }
  // the ring frames the card's side after it opens, so state that side first, or
  // a card that lands on the other edge crosses the screen on its way in
  if (willSplit) A.setCardSide?.(A.focusAnchor(n.x, ringZoom()).cardLeft);
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

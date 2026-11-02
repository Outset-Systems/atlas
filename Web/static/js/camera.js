/* Atlas — camera: pan/zoom/glide over the stage, plus the
   overscroll bounds that make the sky (north) and the Depths (south) real.

   ⚑ **The maths is not here.** It lives in `camera-model.js`, which has no
   imports and no DOM, so `tests/test_camera.mjs` can exercise it in plain node
   — the split `project.js` already had. This file is the SHELL: it owns the
   live `cam`, reads the browser (`innerWidth`, the CSS tokens, the media
   query), feeds those to the model as a view descriptor, and writes the result
   back to the DOM. The three bugs of 2026-08-21 were all statements about
   numbers that no test could reach from in here.

   The rule for anything added below: if it can be written as "given this
   window and this camera, where does the camera go", it belongs in the model. */

import { A, CFG, REDUCED, $ } from './config.js';
import { unproject } from './project.js';
import * as model from './camera-model.js';

const viewport = $('viewport');
const stage = $('stage');

const cam = { x: 0, y: 0, k: 1, min: 0.5, max: CFG.ZOOM_MAX };
A.cam = cam;

/* The card's on-screen share: its width plus a breathing inset each side, read
   from the ONE place the width lives (--card-w / --card-edge in atlas.css,
   which #card and .card-left also read) so it can no longer drift from them —
   it used to be a third hardcoding, 368 against the CSS's 320 and 344 (ALIVE
   #19). Read once, as the constant was; the tokens never change at runtime.
   Declared HERE, above `view()`, rather than beside the anchor code that wants
   it: `view()` closes over both, and a const declared further down the module
   is in the temporal dead zone for anything that calls view() early. */
const _cardCss = getComputedStyle(document.documentElement);
const _cardPx = (name) => parseFloat(_cardCss.getPropertyValue(name)) || 0;

/* The world ends at the abyss's own foot (owner, 2026-11-01). A fixed depth left
   a black spacer under it, as tall as the carousel was short: a realm whose
   watchings are all buttons stood 176px high over 1500px of nothing. Measured,
   and cached, because `view()` runs on every camera move and this must not read
   layout there. Refreshed when a section changes height, the window changes or the
   map loads.

   Both sections undo the camera's fit scale (`--fit`, atlas.css), so a section is
   `height / fit` tall in map pixels. The sky's grows upward from just over the
   clouds, and the sky only ever gains room: it has clouds to show, not a spacer. */
let voidDepth = CFG.VOID_DEPTH, skyNorth = CFG.SKY_NORTH;
function measureWorld() {
  const abyss = $('abyss'), sky = $('chronicle');
  if (!A.MAPH) return;
  if (A.levelPlaces) {            // a region has edges: no sky above it, no Depths below
    voidDepth = 0; skyNorth = 0;
    if (A.apply) { A.clampCam(); A.apply(false); }
    return;
  }
  const fit = model.fitScale(view());
  abyss?.style.setProperty('--fit', fit);
  sky?.style.setProperty('--fit', fit);
  if (abyss?.offsetHeight) {
    voidDepth = (abyss.offsetTop + (abyss.offsetHeight + CFG.VOID_FOOT_PX) / fit) / A.MAPH - 1;
  }
  if (sky?.offsetHeight) {
    const top = Math.max(CFG.SKY_TOP, sky.offsetHeight / fit / A.MAPH + CFG.SKY_GAP);
    sky.style.top = `${(-top * 100).toFixed(2)}%`;
    skyNorth = Math.max(CFG.SKY_NORTH, top + CFG.VOID_FOOT_PX / fit / A.MAPH);
  }
  if (A.apply) { A.clampCam(); A.apply(false); }
}
A.measureWorld = measureWorld;

/** Where a journey leaves the camera: the section framed below the band, centred in
    the room if it is short. Its height is already true pixels (`--fit`). */
A.landOn = (id) => {
  const section = $(id), crown = $('scenes-list').getBoundingClientRect().bottom + 8;
  const air = Math.max(0, (innerHeight - crown - section.offsetHeight) / 2);
  return crown + air - section.offsetTop * cam.k;
};
const sectionWatch = new ResizeObserver(measureWorld);
sectionWatch.observe($('abyss'));
sectionWatch.observe($('chronicle'));
addEventListener('resize', measureWorld);
const CARD_SHARE_PX = _cardPx('--card-w') + 2 * _cardPx('--card-edge');
const narrowScreen = matchMedia('(max-width: 720px)');

/** The world as the model wants it — built fresh per call, because every part
    of it (the window, the map size, the zoom floor, the card token, the
    breakpoint) can change between one frame and the next. */
function view() {
  return {
    vw: innerWidth, vh: innerHeight,
    mapW: A.MAPW, mapH: A.MAPH,
    kMin: cam.min, kMax: cam.max,
    voidDepth, skyNorth,
    cardSharePx: CARD_SHARE_PX, narrow: narrowScreen.matches,
  };
}

/** Move the live camera onto a target the model computed. One place that
    writes `cam`, so "the model decided" and "the camera moved" cannot part. */
function adopt(target) {
  cam.x = target.x; cam.y = target.y; cam.k = target.k;
}

function fitScale() { return model.fitScale(view()); }
A.fitScale = fitScale;

function clampCam() { adopt(model.clampCam(cam, view())); }
A.clampCam = clampCam;

/* ── Committing the camera ───────────────────────────────────────────────────
   One DOM write per animation frame, never one per input event.

   A trackpad emits wheel events far faster than the screen refreshes, and each
   one used to run the whole chain — transform write, label fade, depths check,
   shade update — so a single frame could pay for it five or six times over.
   Now the input handlers only move `cam` and ask for a commit; the commit runs
   once, on the next frame, with whatever the newest values are. That is the
   difference between "scrolling is choppy" and it not being. (2026-07-31)

   A **glide** commits immediately and on purpose: the `gliding` class and the
   destination transform have to land in the same style flush or the CSS
   transition has nothing to animate from. */
let frameQueued = false;
let committing = false;

function commit(gliding) {
  stage.classList.toggle('gliding', gliding && !REDUCED);
  stage.style.transform = `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})`;
  if (committing) return;              // onCameraMove can re-enter (the shore snap)
  committing = true;
  // A glide is the app moving the camera; everything else is the user's hand.
  // The distinction matters downstream: only user moves may auto-descend or
  // shore-snap — a glide that frames a low-sitting node must never end in the
  // Depths (splitting the app host used to).
  try { A.onCameraMove?.(!gliding); } finally { committing = false; }
}

function apply(gliding = false) {
  if (gliding) { commit(true); return; }
  if (frameQueued) return;
  frameQueued = true;
  requestAnimationFrame(() => { frameQueued = false; commit(false); });
}
A.apply = apply;

/** Where most places sit on this picture, in % (a style moves them): the
    median, so a map with a few places across the water opens on the many. */
function placesMidX() {
  const xs = (A.DATA?.nodes || []).filter((n) => !n.off_map && Number.isFinite(n.x))
    .map((n) => n.x).sort((a, z) => a - z);
  return xs.length ? xs[Math.floor(xs.length / 2)] : undefined;
}

function home(gliding = true) {
  adopt(model.homeTarget(view(), placesMidX()));
  apply(gliding);
}
A.home = home;

/** glide so map point (nx,ny in %) sits just above center at zoom k.
    `anchorX` (screen px) parks the point off-centre instead — the focus glide
    uses it to give the dot the share of the screen the card leaves free.
    Omitted = centred, exactly as before. */
function glideTo(nx, ny, k, anchorX = innerWidth / 2) {
  adopt(model.glideTarget(nx, ny, k, anchorX, view()));
  apply(true);
}
A.glideTo = glideTo;

/* ── Sharing the screen with the card ────────────────────────────────────────
   A focused dot used to glide to the screen's centre, which is where the card
   pinned to one side overlaps it at common window sizes — the thing you
   clicked hid behind the thing describing it. `model.focusAnchor` decides
   where the dot lands and which side the card takes, analytically from
   clampCam's own bounds and never by peeking at pixels after the glide; the
   reasoning and its two regressions live with the maths, in camera-model.js.

   The two browser readings it needs — the card's share and the narrow
   breakpoint — are read once at the top of this file and handed over by
   `view()`. */

const focusAnchor = (nx, k) => model.focusAnchor(nx, k, view());
A.focusAnchor = focusAnchor;

function zoomAt(sx, sy, factor) {
  // `sx, sy` arrive in SCREEN space (a pointer, or a window centre). `cam`
  // lives in PLANE space. Flat, those are the same thing and this is the same
  // arithmetic it always was; tilted, they are not, and zooming "at the
  // cursor" without unprojecting first zooms at a point that drifts further
  // from the pointer the nearer the horizon you go. (Arc T step two)
  const target = model.zoomTarget(cam, unproject(sx, sy), factor, view());
  if (!target) return;                 // the clamp swallowed it — do not repaint
  adopt(target);
  apply(false);
}
A.zoomAt = zoomAt;

/* ── drag pan with light inertia ─────────────────────────────────────────
   Capture the pointer only once a real drag starts: capturing on pointerdown
   retargets the eventual click to the viewport and markers never receive it. */
let drag = null, vel = { x: 0, y: 0 }, inertiaRAF = 0;
A.lastWasDrag = false;

viewport.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  cancelAnimationFrame(inertiaRAF);
  drag = { px: e.clientX, py: e.clientY, moved: false, id: e.pointerId };
});

viewport.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.px, dy = e.clientY - drag.py;
  if (!drag.moved && Math.abs(dx) + Math.abs(dy) > CFG.DRAG_THRESHOLD_PX) {
    drag.moved = true;
    viewport.classList.add('dragging');
    try { viewport.setPointerCapture(drag.id); } catch {}
  }
  if (!drag.moved) return;
  // A screen delta is NOT a plane delta once the table tilts: the same finger
  // movement covers more of the map near the horizon than near the front edge.
  // Unproject both ends of the movement and pan by the difference, so the
  // point under the finger stays under the finger. Flat, `unproject` is
  // identity and this reduces to `cam.x += dx` exactly as before.
  const from = unproject(drag.px, drag.py);
  const to = unproject(e.clientX, e.clientY);
  const pdx = to.x - from.x, pdy = to.y - from.y;
  drag.px = e.clientX; drag.py = e.clientY;
  vel = { x: pdx, y: pdy };
  cam.x += pdx; cam.y += pdy;
  clampCam(); apply(false);
});

function endDrag() {
  if (!drag) return;
  A.lastWasDrag = drag.moved;
  drag = null;
  viewport.classList.remove('dragging');
  if (A.lastWasDrag && !REDUCED) {
    const decay = () => {
      vel.x *= CFG.INERTIA_DECAY; vel.y *= CFG.INERTIA_DECAY;
      if (Math.abs(vel.x) + Math.abs(vel.y) < 0.5) return;
      cam.x += vel.x; cam.y += vel.y;
      clampCam(); apply(false);
      inertiaRAF = requestAnimationFrame(decay);
    };
    inertiaRAF = requestAnimationFrame(decay);
  }
}
viewport.addEventListener('pointerup', endDrag);
viewport.addEventListener('pointercancel', endDrag);

/* The wheel means two different things depending on how far out you already
   are (2026-08-10): pushed in, it ZOOMS — wheel down pulls back, wheel up
   pushes in, which is what a wheel does on every map anyone has used. Only once
   the view is all the way out does it go back to TRAVELLING: sky above the
   table, the Depths below it.

   `model.atSurveyOrBeyond` is the gate, and it carries the story of why it
   compares against the SURVEY and not the camera's floor — the 2026-08-21 bug
   that could not be scrolled out of. It is testable now; it was not when it
   lived here.

   Both directions travel once out there, deliberately. Gating only the downward
   one would strand the Upper Deck: at full zoom-out, an upward wheel would
   push back in instead of rising, and the sky would be unreachable by wheel. */
/** May the wheel move the view away from this edge? Asked of the clamp itself. */
function canTravel() {
  const y = cam.y;
  cam.y -= 1;
  clampCam();
  const moved = cam.y !== y;
  cam.y = y;
  return moved;
}

viewport.addEventListener('wheel', (e) => {
  e.preventDefault();
  /* Moving the map puts the Index away (2026-08-11) — travelling and
     browsing a list are different intents, and the drawer covers a third of
     what you just started moving. Scoped to the VIEWPORT's own wheel, so the
     drawer's internal scrolling is untouched: it is a sibling of #viewport, not
     a child, and its wheel events never reach here. Re-open with ☰ or M. */
  A.toggleDrawer?.(false);
  const zoomFactor = e.deltaY < 0 ? CFG.ZOOM_WHEEL : 1 / CFG.ZOOM_WHEEL;
  if (e.ctrlKey) {
    // Ctrl+wheel always zooms, at any scale (and pinch-zoom on trackpads sends ctrlKey)
    zoomAt(e.clientX, e.clientY, zoomFactor);
  } else if (!model.atSurveyOrBeyond(cam.k, view())) {
    // pushed in past the survey → the wheel pulls back toward it
    zoomAt(e.clientX, e.clientY, zoomFactor);
  } else {
    // all the way out → travel up/down through the sky → table → Depths
    const y = cam.y;
    cam.y -= e.deltaY * CFG.WHEEL_PAN;
    autoFrameSky();   // rising above the table gently recenters + frames the sky
    clampCam();
    apply(false);
    // a region has no sky or Depths. Its top edge just stops (owner, 2026-11-01),
    // its bottom edge arms leaving, and only a region with no room to travel at
    // all still zooms in, or the wheel would do nothing there
    if (A.inRegion?.() && cam.y === y) {
      if (e.deltaY > 0) A.regionFloor();
      else if (!canTravel()) zoomAt(e.clientX, e.clientY, zoomFactor);
    }
  }
}, { passive: false });

/* As the view rises above the table's top edge, ease the camera toward a
   horizontally-centered, fit-zoom frame so the Upper Deck + Chronicle sit
   composed no matter where/how zoomed you were on the sand. (The easing itself
   is `model.skyFrame`; over the table it returns the camera untouched.) */
function autoFrameSky() {
  const framed = model.skyFrame(cam, view());
  cam.x = framed.x; cam.k = framed.k;   // Y is the wheel's to move, not ours
}

/* background click closes the card (but never right after a pan) */
viewport.addEventListener('click', () => {
  if (A.lastWasDrag) { A.lastWasDrag = false; return; }
  A.closeCard?.();
});

viewport.addEventListener('dblclick', (e) => zoomAt(e.clientX, e.clientY, CFG.ZOOM_DBLCLICK));

/* keyboard */
addEventListener('keydown', (e) => {
  // `/` summons the command palette from anywhere on the map (H1)
  if (e.key === '/' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
    e.preventDefault(); A.openPalette?.(); return;
  }
  // a field or an editable keeps its own keys; so does any modifier chord
  // (ctrl+minus is the browser's zoom, not the map's — editor/index.js wireKeys
  // guards the same way). Escape alone stays reachable from everywhere.
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName || '') || e.target.isContentEditable) return;
  if (e.key !== 'Escape' && (e.ctrlKey || e.metaKey || e.altKey)) return;
  const pan = CFG.PAN_KEY_PX;
  switch (e.key) {
    // the glass sits over everything, so it swallows the first Escape alone —
    // otherwise closing the pane also threw away the card that opened it
    case 'Escape': {
      if (A.glassOpen?.()) { A.closeGlass(); break; }
      // Escape is the keyboard ×, and a × leaves AND recentres — so Escape must
      // too, but only when it actually closed a scene or the card (both glide
      // the camera off-centre; the drawer/palette/max do not). It also lowers
      // the decoy watch, the one overlay that had no Escape route before.
      // The scenes still close through ONE list
      // (ui.js closeAllScenes), not a copy enumerated here.
      const leaving = A.sceneOpen || A.cardOpen?.();
      A.closeMax?.(); A.closePalette?.(); A.closeAllScenes?.(); A.closeCard?.();
      A.toggleDecoys?.(false); A.toggleDrawer?.(false);
      if (leaving) A.recenter?.(true);
      break;
    }
    case 'ArrowLeft': cam.x += pan; clampCam(); apply(false); break;
    case 'ArrowRight': cam.x -= pan; clampCam(); apply(false); break;
    case 'ArrowUp': cam.y += pan; clampCam(); apply(false); break;
    case 'ArrowDown': cam.y -= pan; clampCam(); apply(false); break;
    case '+': case '=': zoomAt(innerWidth / 2, innerHeight / 2, CFG.ZOOM_KEY); break;
    case '-': zoomAt(innerWidth / 2, innerHeight / 2, 1 / CFG.ZOOM_KEY); break;
    case 'Home': case 'h': A.closeCard?.(); home(true); break;
    case 'm': A.toggleDrawer?.(); break;
    case 'd': A.descend?.(); break;
    case 's': A.ascend?.(); break;
    case 'n': A.toggleNet?.(); break;
    case 'g': A.toggleDecoys?.(); break;   // the decoys' watch, drawn in place
  }
});

/* The zoom floor is re-derived from the window — but a zero-sized window is
   not a size (see `model.panFloor`, which keeps the last real floor and holds
   the 2026-08-21 story). */
addEventListener('resize', () => {
  cam.min = model.panFloor(innerWidth, A.MAPW, cam.min);
  clampCam(); apply(false);
});

/* Atlas — the camera's maths, with the DOM taken out of it.

   `camera.js` was one file: the arithmetic that decides where the camera goes
   AND the listeners that feed it. The arithmetic read `innerWidth`,
   `innerHeight`, `A.MAPW` and the live `cam` object straight out of the module
   scope, so there was no way to ask it a question without a browser — and the
   suite therefore could not see any of the three bugs that shipped on
   2026-08-21:

     · the wheel gate compared against `cam.min` (the width-fit floor) while
       every stated journey lands at `fitScale()` (cover) — the same number on
       a landscape window and a DIFFERENT one on anything taller than wide, so
       a ☾ descent arrived at a scale the wheel still called "pushed in";
     · `clampCam` centred Y the way it centres X, pinning `cam.y` on a portrait
       window where the fitted map is exactly the window's height;
     · the resize handler cached a floor of `0` from a zero-width window, and a
       floor of 0 makes every scale "pushed in".

   Every one of those is a statement about numbers. Split out, they are ten
   lines of test each; left in place they were only visible by squinting at a
   screen in the right window shape. This module is the split — the same shape
   `project.js` already has: **no imports and no DOM**, so `tests/test_camera.mjs`
   can exercise it in plain node.

   ── The view descriptor ──────────────────────────────────────────────────────
   Every function here takes the world as an argument instead of reading it:

     v = {
       vw, vh,          the window (innerWidth / innerHeight)
       mapW, mapH,      the map image (A.MAPW / A.MAPH)
       kMin, kMax,      the zoom floor and ceiling (cam.min / cam.max)
       voidDepth,       scrollable world below the table: the abyss's measured foot
       skyNorth,        scrollable sky above it, grown to fit the Chronicle
       cardSharePx,     the card's on-screen width + its two insets
       narrow,          the <=720px bottom-sheet case
     }

   `camera.js` builds one of these per call from the live browser; a test builds
   one from literals. Neither knows anything the other does not. */

/** The survey: the whole table framed, cover-fit. Every stated journey — ☾, ☁,
    Home, the ◈ pull-back — lands here, which is why the wheel gate must too. */
export function fitScale(v) {
  return Math.max(v.vw / v.mapW, v.vh / v.mapH);
}

/** One spelling of the zoom clamp. `glideTarget`, `zoomTarget` and
    `focusAnchor` all PREDICT what `clampCam` will enforce, and a private copy
    in each is how a prediction and an enforcement start to disagree. */
export function clampK(k, v) {
  return Math.max(v.kMin, Math.min(v.kMax, k));
}

/** The western pan bound. `Math.min(0, …)` because a map narrower than the
    window has no westward travel at all — `clampCam` centres it instead. */
export function minCamX(w, v) {
  return Math.min(0, v.vw - w);
}

/** Hold the camera inside the world: X centred or bounded, Y free to climb into
    the sky and fall into the Depths.

    ⚑ Y is deliberately NOT centred the way X is. Centring it pinned `cam.y`
    outright on a portrait window — where `fitScale` is height-driven, so the
    fitted map is exactly the window's height — and with it pinned, ☁ and ☾ did
    nothing and a descent could not be reversed, because the release threshold
    sat on the far side of a camera that could not move. Vertically there is
    always somewhere to go, even when the table itself fits on screen: the sky
    is above it and the Depths are below. X keeps the centring; there is
    genuinely nothing east or west of the table. (2026-07-31) */
export function clampCam(cam, v) {
  const w = v.mapW * cam.k;
  const south = v.mapH * (1 + v.voidDepth) * cam.k;
  const north = v.mapH * v.skyNorth * cam.k;
  const minY = Math.min(0, v.vh - south);
  return {
    x: w <= v.vw ? (v.vw - w) / 2
                 : Math.max(minCamX(w, v), Math.min(0, cam.x)),
    y: Math.max(minY, Math.min(north, cam.y)),
    k: cam.k,
  };
}

/** Home: the survey, centred both ways. */
export function homeTarget(v, focusX) {
  const k = fitScale(v);
  const w = v.mapW * k;
  // A window narrower than the map at this zoom (a phone) centres on the middle
  // of where the places are, `focusX` in %: a map whose places sit to one side
  // otherwise opens on empty sea.
  const x = Number.isFinite(focusX) && w > v.vw ? v.vw / 2 - (focusX / 100) * w : (v.vw - w) / 2;
  return clampCam({ x, y: (v.vh - v.mapH * k) / 2, k }, v);
}

/** True when `cam` already stands at `target`, within a pixel or so and a
    hair of zoom. THE ATLAS asks it: centred, a press puts the map away;
    anywhere else, the press centres it (owner, 2026-11-05). */
export function sameView(cam, target, px = 2) {
  return Math.abs(cam.x - target.x) <= px && Math.abs(cam.y - target.y) <= px &&
    Math.abs(cam.k / target.k - 1) <= 0.005;
}

/** Put map point (nx, ny — percentages) just above centre at zoom k. `anchorX`
    parks it off-centre instead; the 0.44 bias lifts it because the card sits
    low. Omit `anchorX` for the centre, exactly as before. */
export function glideTarget(nx, ny, k, anchorX, v) {
  const kk = clampK(k, v);
  const ax = anchorX === undefined ? v.vw / 2 : anchorX;
  return clampCam({
    x: ax - (nx / 100) * v.mapW * kk,
    y: v.vh * 0.44 - (ny / 100) * v.mapH * kk,
    k: kk,
  }, v);
}

/** Where a focused dot should sit so the card does not cover it, and which
    side the card takes. See camera.js's own history note: the card lives on the
    LEFT and crosses right only when a place is far enough west that it would
    otherwise sit on top of it.

    The test is where the dot actually LANDS, not whether the ideal anchor is
    reachable — asking the latter flipped the internal host (dead centre at
    nx≈54.5) because the constellation's wider shot leaves almost no pan room. */
export function focusAnchor(nx, k, v) {
  const kk = clampK(k, v);
  const w = v.mapW * kk;
  if (v.narrow || w <= v.vw)
    return { x: v.vw / 2, cardLeft: false };   // bottom sheet / clampCam centres X anyway

  const half = (v.vw - v.cardSharePx) / 2;
  const anchorRight = v.vw - half;             // dot centred in the RIGHT share
  const desired = anchorRight - (nx / 100) * w;
  if (desired <= 0 && desired >= minCamX(w, v))
    return { x: anchorRight, cardLeft: true };

  /* Unreachable splits TWO ways and they need OPPOSITE answers. Answering both
     with the west stop sent a click on the edge or the NAS — the two
     easternmost places — gliding to the map's west side with the dot off
     screen entirely (2026-08-11, fixed 2026-08-15). */
  if (desired < minCamX(w, v)) {
    // too far EAST: the camera stops at the eastern stop; hand back the landing
    const atEastStop = (nx / 100) * w + minCamX(w, v);
    return { x: atEastStop, cardLeft: atEastStop >= v.cardSharePx };
  }
  // too far WEST: the camera stops at cam.x = 0
  const atWestStop = (nx / 100) * w;
  if (atWestStop >= v.cardSharePx)
    return { x: atWestStop, cardLeft: true };
  return { x: half, cardLeft: false };         // the card crosses right
}

/** Zoom by `factor` about plane point `p`, keeping `p` under the pointer.
    Returns null when the clamp swallows the change — the caller must not
    repaint for a camera that did not move.

    `p` is PLANE space: the caller unprojects the pointer first (project.js).
    Flat, plane == screen and this is the arithmetic it always was. */
export function zoomTarget(cam, p, factor, v) {
  const k2 = clampK(cam.k * factor, v);
  if (k2 === cam.k) return null;
  return clampCam({
    x: p.x - ((p.x - cam.x) / cam.k) * k2,
    y: p.y - ((p.y - cam.y) / cam.k) * k2,
    k: k2,
  }, v);
}

/** THE WHEEL GATE. Pushed in, the wheel ZOOMS; all the way out, it TRAVELS —
    sky above the table, the Depths below.

    "All the way out" is the SURVEY (`fitScale`), not the camera's floor
    `kMin`. They are the same number on a landscape window, which is why the
    gate was first written against `kMin` (2026-08-10) and why the bug hid: on
    any window taller than it is wide, `fitScale` is height-driven and sits
    ABOVE the width-fit floor, so a ☾ descent landed at a scale the wheel still
    called "pushed in" — wheel UP zoomed in, wheel DOWN zoomed out and then
    kept descending, and the Depths could not be scrolled out of.

    The 0.1% slack is not decoration: a glide lands on a float sum that is
    `fitScale()` plus or minus an ulp, and an exact `<=` makes the gate flicker
    at exactly the scale every journey ends on. */
export function atSurveyOrBeyond(k, v) {
  return k <= fitScale(v) * 1.001;
}

/** Rising above the table's top edge eases the camera toward a centred,
    fit-zoom frame, so the Upper Deck and the Chronicle sit composed however
    you were sitting on the sand. Returns the eased {x, k}; over the table it
    returns the camera unchanged. */
export function skyFrame(cam, v) {
  const topImgY = (0 - cam.y) / cam.k;          // image-y at the screen top
  if (topImgY >= 0) return { x: cam.x, k: cam.k };   // still over the table
  const into = Math.min(1, -topImgY / (v.mapH * 0.42));  // 0 at the seam -> 1 in the sky
  const k = cam.k + (fitScale(v) - cam.k) * 0.16 * into;
  const centerX = (v.vw - v.mapW * k) / 2;
  return { x: cam.x + (centerX - cam.x) * 0.18 * into, k };
}

/** The zoom floor after a resize. A zero-sized window is not a size — it is a
    tab that is not being shown (minimised, hidden, mid-relayout). Caching
    `vw / mapW` from it writes a floor of 0, and a floor of 0 makes EVERY scale
    "pushed in": the wheel zooms forever and never travels, and − shrinks the
    table to nothing (seen 2026-08-21 with `cam.min === 0` after a viewport
    reset). Keep the last real floor until there is a real width. */
export function panFloor(vw, mapW, previous) {
  if (!(vw > 0) || !mapW) return previous;
  return vw / mapW;
}

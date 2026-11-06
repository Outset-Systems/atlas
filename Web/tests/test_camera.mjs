/* The camera's maths, in plain node — the test THE LIST #13 asked for.

   Run:  node tests/test_camera.mjs        (from Web/, same as test_project.mjs)

   Three camera bugs shipped on 2026-08-21 and none of them was visible to the
   suite, because the arithmetic read `innerWidth` and a module-scoped `cam`
   straight out of camera.js and could not be asked a question without a
   browser. Every one of them was a statement about numbers. Now that
   camera-model.js takes the world as an argument, each is ten lines here — and
   each has a test below named for it, so a regression is loud instead of being
   something you have to reproduce by resizing a window into the right shape.

   Deliberately more than a round-trip: the interesting cases are the WINDOW
   SHAPES (portrait vs landscape), where fitScale, cam.min and the clamp all
   stop agreeing with each other. */

import assert from 'node:assert/strict';
import {
  atSurveyOrBeyond, clampCam, clampK, fitScale, focusAnchor, glideTarget,
  homeTarget, minCamX, panFloor, sameView, skyFrame, zoomTarget,
} from '../static/js/camera-model.js';

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok  ${name}`); }
  catch (e) { console.log(`  FAIL ${name}\n       ${e.message}`); process.exitCode = 1; }
}

/* The map is the real one's shape (4000×2400, a 5:3 landscape), because the
   whole point of these tests is that window shape vs MAP shape is what decides
   whether fitScale is width- or height-driven. */
const MAP = { mapW: 4000, mapH: 2400 };
const CFG = { voidDepth: 0.90, skyNorth: 0.60 };

/** A view descriptor for a window of the given size. `kMin` defaults to the
    width-fit floor, which is what camera.js's resize handler caches. */
function view(vw, vh, extra = {}) {
  return {
    vw, vh, ...MAP, ...CFG,
    kMin: vw / MAP.mapW, kMax: 4,
    cardSharePx: 368, narrow: false,
    ...extra,
  };
}

const LANDSCAPE = view(1920, 1080);   // 16:9 — wider than the map's 5:3
const PORTRAIT = view(900, 1600);     // taller than wide — where the bugs lived

console.log('camera-model — fitScale and the floor');

test('fitScale COVERS the window (max), it does not fit inside it', () => {
  // 1920/4000 = 0.48, 1080/2400 = 0.45 → width-driven on a 16:9 window
  assert.equal(fitScale(LANDSCAPE), 0.48);
  // 900/4000 = 0.225, 1600/2400 = 0.667 → HEIGHT-driven on a portrait window
  assert.ok(Math.abs(fitScale(PORTRAIT) - 2 / 3) < 1e-12);
});

test('BUG 2026-08-21: fitScale and the width-fit floor part on a tall window', () => {
  // The premise of the wheel-gate bug. On landscape they agree...
  assert.equal(fitScale(LANDSCAPE), LANDSCAPE.kMin);
  // ...and on portrait fitScale sits far ABOVE the floor. Anything that treats
  // the two as interchangeable is broken on exactly this window.
  assert.ok(fitScale(PORTRAIT) > PORTRAIT.kMin * 2.9);
});

test('clampK holds the floor and the ceiling', () => {
  assert.equal(clampK(0.001, LANDSCAPE), LANDSCAPE.kMin);
  assert.equal(clampK(99, LANDSCAPE), 4);
  assert.equal(clampK(1.5, LANDSCAPE), 1.5);
});

test('minCamX is never positive — a narrow map has no westward travel', () => {
  assert.equal(minCamX(4000, LANDSCAPE), 1920 - 4000);
  assert.equal(minCamX(500, LANDSCAPE), 0);
});

console.log('camera-model — the wheel gate (THE LIST #13, bug 1)');

test('pushed in past the survey, the wheel is NOT travelling', () => {
  assert.equal(atSurveyOrBeyond(2.0, LANDSCAPE), false);
});

test('at the survey exactly, the wheel IS travelling', () => {
  assert.equal(atSurveyOrBeyond(fitScale(LANDSCAPE), LANDSCAPE), true);
});

test('the 0.1% slack absorbs a glide landing on a float sum', () => {
  const k = fitScale(LANDSCAPE);
  // a glide's arithmetic lands an ulp or two above the exact value; an exact
  // `<=` would make the gate flicker at the scale every journey ends on
  assert.equal(atSurveyOrBeyond(k * 1.0005, LANDSCAPE), true);
  assert.equal(atSurveyOrBeyond(k * 1.02, LANDSCAPE), false);   // but not a real zoom
});

test('BUG: a descent on a PORTRAIT window lands travelling, not "pushed in"', () => {
  /* The bug itself. ☾ / ☁ / Home / ◈ all land at fitScale(). The old gate
     compared against cam.min, so on a portrait window — where fitScale is
     0.667 and cam.min is 0.225 — the camera arrived at 0.667, the gate said
     "still pushed in", wheel UP zoomed in, wheel DOWN zoomed out and kept
     descending, and the Depths could not be scrolled out of. */
  const landed = fitScale(PORTRAIT);
  assert.equal(atSurveyOrBeyond(landed, PORTRAIT), true, 'the gate must agree with the journey');
  // and the old, wrong comparison is demonstrably the other answer
  assert.equal(landed <= PORTRAIT.kMin * 1.001, false, 'cam.min would have said "pushed in"');
});

console.log('camera-model — clampCam (THE LIST #13, bug 2)');

test('X is centred when the map is narrower than the window', () => {
  const v = view(1920, 1080);
  const out = clampCam({ x: 999, y: 0, k: 0.1 }, v);   // 4000*0.1 = 400px wide
  assert.equal(out.x, (1920 - 400) / 2);
});

test('X is bounded, not centred, when the map overflows', () => {
  const v = LANDSCAPE, k = 1;
  assert.equal(clampCam({ x: 500, y: 0, k }, v).x, 0);              // no travel east of 0
  assert.equal(clampCam({ x: -99999, y: 0, k }, v).x, 1920 - 4000); // west stop
  assert.equal(clampCam({ x: -1000, y: 0, k }, v).x, -1000);        // in between, untouched
});

test('BUG: Y is NOT centred on a portrait window — the camera can still move', () => {
  /* Centring Y the way X is centred pinned cam.y outright on a portrait window,
     where fitScale is height-driven so the fitted map is exactly the window's
     height. With it pinned, ☁ and ☾ did nothing and a descent could not be
     reversed: the release threshold sat on the far side of a camera that could
     not move. */
  const v = PORTRAIT, k = fitScale(PORTRAIT);
  assert.equal(v.mapH * k, v.vh, 'premise: the fitted map is exactly the window height');
  const up = clampCam({ x: 0, y: 300, k }, v);
  const down = clampCam({ x: 0, y: -300, k }, v);
  assert.notEqual(up.y, down.y, 'Y must still be free to move');
  assert.equal(up.y, 300);
  assert.equal(down.y, -300);
});

test('the sky is above the table and the Depths below it', () => {
  const v = LANDSCAPE, k = 1;
  const north = v.mapH * v.skyNorth * k;                       // 1440
  assert.equal(clampCam({ x: 0, y: 99999, k }, v).y, north);   // cannot rise past the sky
  const south = v.mapH * (1 + v.voidDepth) * k;                // 4560
  assert.equal(clampCam({ x: 0, y: -99999, k }, v).y, v.vh - south);
});

console.log('camera-model — the resize floor (THE LIST #13, bug 3)');

test('BUG: a zero-width window must not write a floor of 0', () => {
  /* A floor of 0 makes EVERY scale "pushed in": the wheel zooms forever and
     never travels, and − shrinks the table to nothing. Seen 2026-08-21 with
     cam.min === 0 after a viewport reset. */
  assert.equal(panFloor(0, 4000, 0.48), 0.48, 'the last real floor is kept');
  assert.equal(panFloor(-5, 4000, 0.48), 0.48);
  assert.equal(panFloor(NaN, 4000, 0.48), 0.48);
});

test('a real width does write a new floor', () => {
  assert.equal(panFloor(2000, 4000, 0.48), 0.5);
});

test('a map that has not loaded yet is not a size either', () => {
  assert.equal(panFloor(1920, 0, 0.48), 0.48);
  assert.equal(panFloor(1920, undefined, 0.48), 0.48);
});

console.log('camera-model — journeys');

test('home frames the survey, centred', () => {
  const out = homeTarget(LANDSCAPE);
  assert.equal(out.k, fitScale(LANDSCAPE));
  assert.equal(out.x, (1920 - 4000 * out.k) / 2);
  // and it lands exactly where the wheel gate says "travelling"
  assert.equal(atSurveyOrBeyond(out.k, LANDSCAPE), true);
});

test('a narrow window opens on the places, a wide one on the picture', () => {
  assert.ok(homeTarget(PORTRAIT, 20).x > homeTarget(PORTRAIT).x);
  assert.equal(homeTarget(LANDSCAPE, 20).x, homeTarget(LANDSCAPE).x);
  assert.equal(homeTarget(PORTRAIT, undefined).x, homeTarget(PORTRAIT).x);
});

test('sameView: home is home, a pan or a zoom away is not', () => {
  const home = homeTarget(LANDSCAPE);
  assert.equal(sameView({ ...home }, home), true);
  assert.equal(sameView({ ...home, x: home.x + 1.5 }, home), true);   // rounding, not a move
  assert.equal(sameView({ ...home, x: home.x + 40 }, home), false);
  assert.equal(sameView({ ...home, y: home.y - 40 }, home), false);
  assert.equal(sameView({ ...home, k: home.k * 1.18 }, home), false); // one wheel notch
});

test('glideTarget puts the point at the anchor, biased up', () => {
  const v = LANDSCAPE, k = 1;
  const out = glideTarget(50, 50, k, 960, v);
  // x is clamped, so check the unclamped intent on a point that is reachable
  const wanted = 960 - 0.5 * v.mapW * k;
  assert.equal(out.x, Math.max(minCamX(v.mapW * k, v), Math.min(0, wanted)));
  assert.equal(out.y, Math.max(Math.min(v.vh - v.mapH * (1 + v.voidDepth) * k,
                                        0 * 1),
                               Math.min(v.mapH * v.skyNorth * k,
                                        v.vh * 0.44 - 0.5 * v.mapH * k)));
});

test('glideTarget clamps k the way clampCam will', () => {
  assert.equal(glideTarget(50, 50, 99, undefined, LANDSCAPE).k, 4);
  assert.equal(glideTarget(50, 50, 0.0001, undefined, LANDSCAPE).k, LANDSCAPE.kMin);
});

test('zoomTarget keeps the plane point under the pointer', () => {
  const v = LANDSCAPE;
  const cam = { x: -500, y: -200, k: 1 };
  const p = { x: 1000, y: 700 };
  const out = zoomTarget(cam, p, 1.18, v);
  // the screen offset of p must scale with k: (p - cam) / k is invariant
  const before = { x: (p.x - cam.x) / cam.k, y: (p.y - cam.y) / cam.k };
  const after = { x: (p.x - out.x) / out.k, y: (p.y - out.y) / out.k };
  assert.ok(Math.abs(before.x - after.x) < 1e-9, 'x drifted');
  assert.ok(Math.abs(before.y - after.y) < 1e-9, 'y drifted');
});

test('zoomTarget returns null when the clamp swallows the change', () => {
  const v = LANDSCAPE;
  assert.equal(zoomTarget({ x: 0, y: 0, k: 4 }, { x: 0, y: 0 }, 1.18, v), null);
  assert.equal(zoomTarget({ x: 0, y: 0, k: v.kMin }, { x: 0, y: 0 }, 1 / 1.18, v), null);
  assert.notEqual(zoomTarget({ x: 0, y: 0, k: 1 }, { x: 0, y: 0 }, 1.18, v), null);
});

test('skyFrame leaves the camera alone while it is over the table', () => {
  const cam = { x: -500, y: -200, k: 1 };      // y < 0 → looking DOWN the map
  const out = skyFrame(cam, LANDSCAPE);
  assert.equal(out.x, cam.x);
  assert.equal(out.k, cam.k);
});

test('skyFrame eases toward centred-and-fitted once above the seam', () => {
  const v = LANDSCAPE;
  const cam = { x: -1500, y: 600, k: 1.6 };    // risen into the sky, zoomed in, off-centre
  const out = skyFrame(cam, v);
  assert.ok(out.k < cam.k, 'must ease toward fitScale, which is below 1.6');
  assert.ok(out.k > fitScale(v), 'and only PART of the way — it is an ease, not a jump');
  const centerX = (v.vw - v.mapW * out.k) / 2;
  assert.ok(Math.abs(out.x - centerX) < Math.abs(cam.x - centerX), 'must ease toward centre');
});

console.log('camera-model — focusAnchor: sharing the screen with the card');

test('a narrow window is a bottom sheet — no share to split', () => {
  const v = view(600, 900, { narrow: true });
  assert.deepEqual(focusAnchor(50, 1, v), { x: 300, cardLeft: false });
});

test('a map narrower than the window centres anyway', () => {
  const v = view(1920, 1080);
  assert.deepEqual(focusAnchor(50, 0.1, v), { x: 960, cardLeft: false });
});

test('a reachable anchor puts the dot in the RIGHT share, card left', () => {
  const v = LANDSCAPE;
  const out = focusAnchor(50, 1, v);          // dead centre of the map, k = 1
  const half = (v.vw - v.cardSharePx) / 2;
  assert.deepEqual(out, { x: v.vw - half, cardLeft: true });
});

test('REGRESSION: the easternmost places do not glide off screen', () => {
  /* 2026-08-11 answered both unreachable cases with the west stop, which sent a
     click on the edge or the NAS to the map's WEST side with the dot off screen
     entirely (fixed 2026-08-15). The east case must hand back the EAST stop. */
  const v = LANDSCAPE, k = 1, w = v.mapW * k;
  const out = focusAnchor(97, k, v);           // far east
  const atEastStop = 0.97 * w + minCamX(w, v);
  assert.equal(out.x, atEastStop);
  assert.ok(out.x > 0 && out.x < v.vw, `the dot must land ON screen, got ${out.x}`);
});

test('a far-WESTERN place makes the card cross right', () => {
  const v = LANDSCAPE, k = 1;
  const out = focusAnchor(1, k, v);            // hard against the western edge
  assert.equal(out.cardLeft, false, 'the card must get out of the way');
  assert.ok(out.x > 0 && out.x < v.vw);
});

test('the anchor is always on screen, for every place on the map', () => {
  /* The property the two regressions above are instances of. Sweep the whole
     map at several zooms and window shapes: a dot you clicked must never glide
     somewhere you cannot see. */
  for (const v of [LANDSCAPE, PORTRAIT, view(1280, 800), view(2560, 1440)]) {
    for (const k of [v.kMin, fitScale(v), 1, 2, 4]) {
      for (let nx = 0; nx <= 100; nx += 2.5) {
        const { x } = focusAnchor(nx, k, v);
        assert.ok(x >= 0 && x <= v.vw,
          `anchor ${x} off screen at nx=${nx} k=${k} vw=${v.vw}x${v.vh}`);
      }
    }
  }
});

console.log(`\n${passed} passed`);
if (process.exitCode) console.log('SOME TESTS FAILED');

/* The projection seam for THE TILTED TABLE — run with `node tests/test_project.mjs`.

   Arc T v1 tilted the table with one CSS rule and left the camera's maths
   untouched, so pointing at the map while tilted was admittedly approximate.
   Step two inverts the transform properly. The whole claim is "unproject is the
   exact inverse of the browser's own projection", and a claim like that is
   either tested or it is a hope — this repo has just spent a week finding gates
   that looked fine and did nothing.

   Plain node, no framework, same shape as test_ipam.mjs: the front-end has no
   test runner and adding one to assert twenty numbers would be the larger
   change. */

import assert from 'node:assert/strict';
import {
  TILT, tiltForward, tiltInverse, tiltScaleAt,
} from '../static/js/project.js';

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
  } catch (err) {
    console.error(`FAIL  ${name}\n      ${err.message}`);
    process.exitCode = 1;
  }
}

const close = (a, b, eps = 1e-6) =>
  assert.ok(Math.abs(a - b) < eps, `expected ${b}, got ${a} (Δ${Math.abs(a - b)})`);

/* ── the round trip: the only property that actually matters ──────────── */

test('forward → inverse returns the original plane point', () => {
  for (const dx of [-800, -120, 0, 37, 640]) {
    for (const dy of [-500, -90, 0, 45, 380]) {
      const s = tiltForward(dx, dy);
      const p = tiltInverse(s.x, s.y);
      close(p.x, dx, 1e-6);
      close(p.y, dy, 1e-6);
    }
  }
});

test('inverse → forward returns the original screen point', () => {
  for (const sx of [-700, -55, 0, 210, 540]) {
    for (const sy of [-320, -40, 0, 88, 300]) {
      const p = tiltInverse(sx, sy);
      const s = tiltForward(p.x, p.y);
      close(s.x, sx, 1e-6);
      close(s.y, sy, 1e-6);
    }
  }
});

/* ── the geometry is the RIGHT geometry, not merely self-consistent ─────
   A round trip passes just as happily for a wrong-but-invertible transform,
   so pin the actual CSS semantics too. */

test('the origin is the fixed point', () => {
  const s = tiltForward(0, 0);
  close(s.x, 0); close(s.y, 0); close(s.scale, 1);
});

test('rotateX foreshortens vertically and leaves the axis alone', () => {
  // A point level with the origin has z=0, so no perspective scaling at all,
  // and its horizontal offset must survive untouched.
  const s = tiltForward(100, 0);
  close(s.x, 100);
  close(s.y, 0);
});

test('the far half of the table shrinks, the near half grows', () => {
  // CSS rotateX(+26deg) tips the TOP of the plane away from the viewer: a
  // negative dy (above the origin, i.e. north) gains negative z and so
  // recedes; positive dy comes toward the camera and magnifies.
  assert.ok(tiltScaleAt(-300) < 1, 'north of the origin should recede');
  assert.ok(tiltScaleAt(+300) > 1, 'south of the origin should magnify');
  assert.ok(tiltScaleAt(-300) < tiltScaleAt(-100), 'further north, smaller still');
});

test('a vertical screen delta covers more map near the horizon', () => {
  // This is precisely the "aim is approximate" complaint: the same pointer
  // movement must NOT mean the same map distance everywhere once tilted.
  const nearFront = tiltInverse(0, 200).y - tiltInverse(0, 180).y;
  const nearBack = tiltInverse(0, -180).y - tiltInverse(0, -200).y;
  assert.ok(nearBack > nearFront,
    `20px near the horizon should cover more map than 20px at the front ` +
    `(${nearBack.toFixed(2)} vs ${nearFront.toFixed(2)})`);
});

/* ── the guards ───────────────────────────────────────────────────────── */

test('the vanishing line never yields NaN', () => {
  // Solve for the screen Y where the denominator vanishes, then sit on it.
  const th = (TILT.deg * Math.PI) / 180;
  const sy = -(TILT.perspective * Math.cos(th)) / Math.sin(th);
  const p = tiltInverse(0, sy);
  assert.equal(p.horizon, true, 'should report hitting the horizon');
  assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y), 'must stay finite');
});

test('no input produces NaN in cam-space', () => {
  for (const v of [-1e7, -1e4, 0, 1e4, 1e7]) {
    const p = tiltInverse(v, v);
    assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y), `NaN at ${v}`);
  }
});

test('a zero tilt is the identity', () => {
  // The flat path short-circuits before reaching here, but the maths itself
  // must degrade cleanly — otherwise the short-circuit is load-bearing and
  // removing it one day would silently bend the map.
  const flat = { ...TILT, deg: 0 };
  const s = tiltForward(123, -456, flat);
  close(s.x, 123); close(s.y, -456); close(s.scale, 1);
  const p = tiltInverse(123, -456, flat);
  close(p.x, 123); close(p.y, -456);
});

test('TILT still matches atlas.css', () => {
  // If someone retunes the angle in CSS and not here, every projection is
  // quietly wrong and nothing throws. This test is a tripwire, not maths.
  assert.equal(TILT.deg, 26, 'atlas.css says rotateX(26deg)');
  assert.equal(TILT.perspective, 1300, 'atlas.css says perspective(1300px)');
  assert.equal(TILT.originY, 0.58, 'atlas.css says transform-origin 50% 58%');
});

console.log(`${passed} passed`);

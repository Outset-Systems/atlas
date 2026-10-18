/* Atlas — the projection seam (Arc T, step two).

   Everything that draws on the map goes through `cam {x, y, k}` and one CSS
   transform. That was true while the table was flat, and it quietly stopped
   being true when the table learned to tilt: `body.tilted #viewport` adds
   `perspective(1300px) rotateX(26deg)`, so the pixels the user points at stop
   being the pixels the camera thinks in. Arc T v1 shipped anyway and was honest
   about it — the toggle warned that aim was "approximate". This is the version
   that no longer has to warn.

   Two spaces, and confusing them IS the bug:

     PLANE  — the untilted stage plane. `cam.x`, `cam.y` and every marker
              position live here. While flat, plane == screen.
     SCREEN — what the eye and the pointer see, after the tilt.

   ⚑ **Only pointer input needs this.** Markers, labels and roads are DOM
   children of the transformed element, so the browser already projects them —
   there is nothing to route. What broke under tilt is the other direction:
   turning a click or a drag back into a map position. The tilt plan lists
   marker layout and road drawing as needing the seam too; that becomes true for
   a later arc, where a WebGL camera owns the projection and CSS no longer does it for
   us. Doing it now would be five files of churn for zero behaviour change.

   No imports and no DOM at load, so `tests/test_project.mjs` can exercise the
   maths in plain node. Given this repo's recent history — three sign-in gates
   that were decorative under a green suite — geometry that can only be checked
   by squinting at a screen is not good enough. */

/** The tilt exactly as `atlas.css` spells it. Two spellings of one angle is how
    a projection and its inverse start to disagree — change both or neither. */
export const TILT = {
  deg: 26,             // rotateX(26deg)
  perspective: 1300,   // perspective(1300px)
  originX: 0.5,        // transform-origin: 50% ...
  originY: 0.58,       //                   ... 58%
};

/* ── the maths, pure ─────────────────────────────────────────────────────────
   CSS applies `perspective(P) rotateX(θ)` about the transform-origin. For a
   point on the z=0 plane at offset (X, Y) from that origin:

       rotateX:      y' = Y·cosθ        z = Y·sinθ
       perspective:  s  = P / (P − z)          (the foreshortening scale)
       screen:       (X·s, y'·s)

   The inverse is not a numeric solve — it falls out in closed form. Given a
   screen offset (Sx, Sy):

       Sy = Y·cosθ · P/(P − Y·sinθ)
     ⇒ Y  = Sy·P / (P·cosθ + Sy·sinθ)

   and once Y is known, s follows and X = Sx/s. That one line is the whole of
   "unproject() earning its keep" from the tilt plan. */

const rad = (d) => (d * Math.PI) / 180;

/** Foreshortening scale at a plane point sitting `dy` below the origin. */
export function tiltScaleAt(dy, t = TILT) {
  return t.perspective / (t.perspective - dy * Math.sin(rad(t.deg)));
}

/** PLANE offset → SCREEN offset. */
export function tiltForward(dx, dy, t = TILT) {
  const s = tiltScaleAt(dy, t);
  return { x: dx * s, y: dy * Math.cos(rad(t.deg)) * s, scale: s };
}

/** SCREEN offset → PLANE offset. The exact inverse of `tiltForward`. */
export function tiltInverse(sx, sy, t = TILT) {
  const th = rad(t.deg);
  const P = t.perspective;
  const denom = P * Math.cos(th) + sy * Math.sin(th);
  // Guard the horizon. As the denominator approaches zero the plane point runs
  // to infinity — geometrically the vanishing line, visually the far edge of
  // the table. Returning a finite value keeps one stray pointer event from
  // writing NaN into `cam`, which would blank the map until a reload.
  if (Math.abs(denom) < 1e-6) return { x: 0, y: 0, scale: 1, horizon: true };
  const dy = (sy * P) / denom;
  const s = tiltScaleAt(dy, t);
  return { x: sx / s, y: dy, scale: s, horizon: false };
}

/* ── the DOM-aware seam ──────────────────────────────────────────────────────
   Flat is the overwhelmingly common case and must cost nothing: every entry
   point below short-circuits to identity before touching geometry. */

export const isTilted = () =>
  typeof document !== 'undefined' && document.body.classList.contains('tilted');

function originPx() {
  // Read the live box rather than assuming the viewport fills the window. It
  // does today — and an assumption like that is exactly what stops being true
  // one release later without anything failing loudly.
  const el = document.getElementById('viewport');
  const r = el.getBoundingClientRect();
  return { ox: r.left + r.width * TILT.originX, oy: r.top + r.height * TILT.originY };
}

/** SCREEN (client) point → PLANE point. Identity when flat. */
export function unproject(sx, sy) {
  if (!isTilted()) return { x: sx, y: sy, scale: 1 };
  const { ox, oy } = originPx();
  const p = tiltInverse(sx - ox, sy - oy);
  return { x: ox + p.x, y: oy + p.y, scale: p.scale };
}

/** PLANE point → SCREEN (client) point. Identity when flat. */
export function project(px, py) {
  if (!isTilted()) return { x: px, y: py, scale: 1 };
  const { ox, oy } = originPx();
  const p = tiltForward(px - ox, py - oy);
  return { x: ox + p.x, y: oy + p.y, scale: p.scale };
}

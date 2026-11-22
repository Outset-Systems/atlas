
export const TILT = {
  deg: 26,
  perspective: 1300,
  originX: 0.5,
  originY: 0.58,
};


const rad = (d) => (d * Math.PI) / 180;

export function tiltScaleAt(dy, t = TILT) {
  return t.perspective / (t.perspective - dy * Math.sin(rad(t.deg)));
}

export function tiltForward(dx, dy, t = TILT) {
  const s = tiltScaleAt(dy, t);
  return { x: dx * s, y: dy * Math.cos(rad(t.deg)) * s, scale: s };
}

export function tiltInverse(sx, sy, t = TILT) {
  const th = rad(t.deg);
  const P = t.perspective;
  const denom = P * Math.cos(th) + sy * Math.sin(th);
  if (Math.abs(denom) < 1e-6) return { x: 0, y: 0, scale: 1, horizon: true };
  const dy = (sy * P) / denom;
  const s = tiltScaleAt(dy, t);
  return { x: sx / s, y: dy, scale: s, horizon: false };
}


const isTilted = () =>
  typeof document !== 'undefined' && document.body.classList.contains('tilted');

function originPx() {
  const el = document.getElementById('viewport');
  const r = el.getBoundingClientRect();
  return { ox: r.left + r.width * TILT.originX, oy: r.top + r.height * TILT.originY };
}

export function unproject(sx, sy) {
  if (!isTilted()) return { x: sx, y: sy, scale: 1 };
  const { ox, oy } = originPx();
  const p = tiltInverse(sx - ox, sy - oy);
  return { x: ox + p.x, y: oy + p.y, scale: p.scale };
}

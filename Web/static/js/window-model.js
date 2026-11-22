
export const WINDOW_MIN = 150;
export const OVERSCAN = 20;
export const EDGE = 6;
export const GUESS = 52;

const ok = (h) => typeof h === 'number' && Number.isFinite(h) && h > 0;

export function guess(heights) {
  let sum = 0, n = 0;
  for (const h of heights || []) if (ok(h)) { sum += h; n++; }
  return n ? sum / n : GUESS;
}

export function rowWindow({ count, heights = [], top = 0, viewport = 0, overscan = OVERSCAN }) {
  const n = Math.max(0, count | 0);
  if (!n) return { start: 0, end: 0, first: 0, last: -1, before: 0, after: 0, total: 0 };
  const g = guess(heights);
  const h = (i) => (ok(heights[i]) ? heights[i] : g);
  const visTop = Math.max(0, Number(top) || 0);
  const visBottom = Math.max(visTop, (Number(top) || 0) + Math.max(0, Number(viewport) || 0));
  let y = 0, first = -1, last = -1;
  for (let i = 0; i < n; i++) {
    const bottom = y + h(i);
    if (first < 0 && bottom > visTop) first = i;
    if (y < visBottom) last = i;
    y = bottom;
  }
  const total = y;
  if (first < 0) first = n - 1;
  if (last < first) last = first;
  const start = Math.max(0, first - overscan);
  const end = Math.min(n, last + 1 + overscan);
  let before = 0, after = 0;
  for (let i = 0; i < start; i++) before += h(i);
  for (let i = end; i < n; i++) after += h(i);
  return { start, end, first, last, before, after, total };
}

export function needsRedraw(drawn, want, count, edge = EDGE) {
  if (!drawn || !want) return true;
  const n = Math.max(0, count | 0);
  if (drawn.end > n) return true;
  const lo = drawn.start <= 0 ? 0 : drawn.start + edge;
  const hi = drawn.end >= n ? n - 1 : drawn.end - 1 - edge;
  return want.first < lo || want.last > hi;
}

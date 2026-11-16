/* THE TABLE'S WINDOW, with no DOM (2026-11-15, stage 5 of the NODES plan).

   Stage 1 measured the wall: a NODES keystroke costs about 0.3 ms of style
   and layout for every row drawn, whatever the stylesheets say (with all CSS
   off it costs the same), so 2,000 rows are over half a second and 100 rows
   about 35 ms. So past WINDOW_MIN rows the table draws only the rows on
   screen and OVERSCAN more each side, with a spacer for the rest above and
   below; scrolling near a drawn edge draws again.

   Rows are not one height (an address list or the collections wrap, an open
   services row adds its own), so each drawn row's height is measured and
   kept; a row not yet drawn is guessed at the average of those measured.

   nodes.js does the drawing; this file only counts.
   Unit-tested by tests/test_window_model.mjs under plain node. */

/** Fewer rows than this: draw them all, as before (find-in-page sees them). */
export const WINDOW_MIN = 150;
/** Rows drawn beyond the screen, above and below. */
export const OVERSCAN = 20;
/** Within this many rows of a drawn edge (that is not the table's own), draw again. */
export const EDGE = 6;
/** A row's height before any has been measured, in px. */
export const GUESS = 52;

const ok = (h) => typeof h === 'number' && Number.isFinite(h) && h > 0;

/** The height to assume for a row not yet measured: the average of those
    that were, else GUESS. */
export function guess(heights) {
  let sum = 0, n = 0;
  for (const h of heights || []) if (ok(h)) { sum += h; n++; }
  return n ? sum / n : GUESS;
}

/** Which rows to draw. `heights[i]` is row i's measured height or nothing;
    `top` is how far the screen's top is below the table body's top (negative
    while the body starts lower down the page); `viewport` is the screen's
    height. Returns the rows to draw [start, end), the first and last on
    screen, and the spacers' heights before and after. Never empty while
    there are rows: scrolled past the end (a filter shrank the list), the
    window sits at the end. */
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
  if (first < 0) first = n - 1;              // scrolled past the end
  if (last < first) last = first;
  const start = Math.max(0, first - overscan);
  const end = Math.min(n, last + 1 + overscan);
  let before = 0, after = 0;
  for (let i = 0; i < start; i++) before += h(i);
  for (let i = end; i < n; i++) after += h(i);
  return { start, end, first, last, before, after, total };
}

/** True when the rows on screen (`want.first`..`want.last`) have come within
    EDGE rows of what is drawn (`drawn.start`..`drawn.end`), or outside it. An
    edge that is the table's own first or last row needs no margin. */
export function needsRedraw(drawn, want, count, edge = EDGE) {
  if (!drawn || !want) return true;
  const n = Math.max(0, count | 0);
  if (drawn.end > n) return true;
  const lo = drawn.start <= 0 ? 0 : drawn.start + edge;
  const hi = drawn.end >= n ? n - 1 : drawn.end - 1 - edge;
  return want.first < lo || want.last > hi;
}

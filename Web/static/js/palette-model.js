/* Atlas — palette-model.js: how the finding-glass matches and orders what it
   finds, with no DOM and no imports, so tests/test_palette_model.mjs can ask
   it questions in plain node. palette.js builds the index, reads the box, asks
   this module, and draws the rows. */

/** Subsequence fuzzy match with a light score (contiguous + word-start win).
    -1 when `q` is not a subsequence of `hay`; 0 for an empty `q`. Both are
    expected in lower case. */
export function score(hay, q) {
  if (!q) return 0;
  let hi = 0, s = 0, streak = 0;
  for (const ch of q) {
    const at = hay.indexOf(ch, hi);
    if (at === -1) return -1;              // not a subsequence → drop
    if (at === hi) streak++; else streak = 0;
    s += 1 + streak * 2 + (at === 0 || hay[at - 1] === ' ' ? 3 : 0);
    hi = at + 1;
  }
  return s;
}

/** The first `max` of `items` ({hay, label, …}) that match `q`, best first; a
    tie goes to the shorter label, then to the order they were given in. An
    empty `q` is everything, in the order given. Never the same array. */
export function rank(items, q, max) {
  return (q
    ? items.map((it) => ({ it, sc: score(it.hay, q) }))
        .filter((r) => r.sc >= 0)
        .sort((a, b) => b.sc - a.sc || a.it.label.length - b.it.label.length)
        .map((r) => r.it)
    : items.slice()                        // empty query → everything (places first)
  ).slice(0, max);
}

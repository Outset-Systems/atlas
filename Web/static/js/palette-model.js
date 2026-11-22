
export function score(hay, q) {
  if (!q) return 0;
  let hi = 0, s = 0, streak = 0;
  for (const ch of q) {
    const at = hay.indexOf(ch, hi);
    if (at === -1) return -1;
    if (at === hi) streak++; else streak = 0;
    s += 1 + streak * 2 + (at === 0 || hay[at - 1] === ' ' ? 3 : 0);
    hi = at + 1;
  }
  return s;
}

export function rank(items, q, max) {
  return (q
    ? items.map((it) => ({ it, sc: score(it.hay, q) }))
        .filter((r) => r.sc >= 0)
        .sort((a, b) => b.sc - a.sc || a.it.label.length - b.it.label.length)
        .map((r) => r.it)
    : items.slice()
  ).slice(0, max);
}

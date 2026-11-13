/* Atlas — world-model.js: the arithmetic behind what world.js draws, with no
   DOM and no imports, so tests/test_world_model.mjs can ask it questions in
   plain node. The drawing modules read the page, the config and the dataset,
   ask this module, and write the answer to the page. */

/** The convex hull of `pts` ([[x, y], …]), without its closing point. Fewer
    than three points come back as they were. */
export function convexHull(pts) {
  if (pts.length < 3) return pts;
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const q of p) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop(); lower.push(q); }
  const upper = [];
  for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop(); upper.push(q); }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

/** A territory's outline: the hull of `pts`, each corner pushed `pad` away
    from the hull's centre. `points` is ready for a polygon's `points`
    attribute (whole pixels); `cx`, `cy` is the centre the push was measured
    from, unrounded, where the territory's tag stands. */
export function paddedHull(pts, pad) {
  const h = convexHull(pts);
  const cx = h.reduce((s, p) => s + p[0], 0) / h.length;
  const cy = h.reduce((s, p) => s + p[1], 0) / h.length;
  const d = h.map(([x, y]) => {
    const dx = x - cx, dy = y - cy, len = Math.hypot(dx, dy) || 1;
    return `${(x + dx / len * pad).toFixed(0)},${(y + dy / len * pad).toFixed(0)}`;
  }).join(' ');
  return { cx, cy, points: d };
}

/** Where each service dot sits: a ring of `count` points around `centre`
    ({x, y} in map %), clockwise from due north. `opts.radius` is the ring's
    base radius (it grows past six dots), past `opts.twoRing` dots every other
    one stands `opts.outer` times further out, and `opts.yScale` keeps the ring
    round on a map that is not square. */
export function ringPoints(centre, count, opts) {
  const grow = 1 + Math.max(0, count - 6) * 0.045;
  const r = opts.radius * grow;
  const two = count > opts.twoRing;
  const yScale = opts.yScale;
  return Array.from({ length: count }, (_, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / count;
    const ri = r * (two && i % 2 ? opts.outer : 1);
    return { x: centre.x + ri * Math.cos(a), y: centre.y + ri * Math.sin(a) * yScale };
  });
}

/** Everything a place is charted to talk to: its declared reaches plus
    whatever a route wires it to, in either direction, less any place
    `isOff(id)` says is not drawn. A Set of place ids. */
export function reachTargets(node, routes, isOff) {
  const targets = new Set(node.reaches || []);
  for (const r of routes || []) {
    if (r.from === node.id) targets.add(r.to);
    if (r.to === node.id) targets.add(r.from);
  }
  // an undrawn place cannot be the end of a lit road either
  for (const id of [...targets]) {
    if (isOff(id)) targets.delete(id);
  }
  return targets;
}

/** Every service a split of place `id` should ring: its own links, then every
    link of any other place whose `connects` names this one (`passing`). An
    unknown id has none. */
export function serviceEntries(nodes, id) {
  const own = nodes.find((n) => n.id === id);
  if (!own) return [];
  const entries = (own.links || []).map((link) => ({ host: own, link, passing: false }));
  for (const other of nodes) {
    if (other.id === id) continue;
    for (const link of other.links || []) {
      if ((link.connects || []).includes(id)) entries.push({ host: other, link, passing: true });
    }
  }
  return entries;
}

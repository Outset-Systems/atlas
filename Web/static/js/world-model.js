
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

export function reachTargets(node, routes, isOff) {
  const targets = new Set(node.reaches || []);
  for (const r of routes || []) {
    if (r.from === node.id) targets.add(r.to);
    if (r.to === node.id) targets.add(r.from);
  }
  for (const id of [...targets]) {
    if (isOff(id)) targets.delete(id);
  }
  return targets;
}

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

export function serviceWeb(node, link, routes, isOff = () => false) {
  const listed = (v) => (Array.isArray(v) ? v.filter(Boolean) : []);
  const hops = listed(link?.path);
  if (hops.length) {
    const chain = hops.filter((id) => !isOff(id));
    return { chain, ids: new Set(chain) };
  }
  const connects = listed(link?.connects);
  if (connects.length) return { chain: [], ids: new Set(connects.filter((id) => !isOff(id))) };
  return { chain: [], ids: reachTargets(node || {}, routes, isOff) };
}

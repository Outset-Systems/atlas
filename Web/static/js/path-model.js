/* TOPOLOGY, the model: which tier a place stands on, where it is drawn, which
   edges join the places, and which charted service roads cross a hop.

   Pure functions over the dataset's rows — no DOM, no `A` — so
   tests/test_path_model.mjs can pin them under node. path.js draws what these
   return. */

/** Every charted service road that crosses a given hop, each with the WHOLE
    road it belongs to.

    A road is `[the service's host, ...link.path]` — the same chain `open()`
    lights when a service card hands one over, built the same way here so the
    two can never disagree about where a road begins. A hop is crossed when the
    chain names both ends CONSECUTIVELY: an unordered "contains both" would
    claim Jellyfin crosses gateway→pangolin, two stops that are on its road
    but not adjacent on it, and a picture that cannot tell "next to" from
    "somewhere along" is the starburst this whole chain drawing replaced.

    Direction is not checked. The edge is drawn once for a pair, and traffic on
    it is answered in both directions; a road that runs b→a still runs over this
    hop. Services with no charted `path` are skipped rather than guessed at —
    39 of the realm's 49 have none, and inventing roads for them would fill the
    map with lines nobody surveyed. */
export function servicesCrossing(nodes, a, b) {
  const out = [];
  for (const n of nodes || []) {
    for (const link of n.links || []) {
      const hops = Array.isArray(link.path) ? link.path.filter(Boolean) : [];
      if (!hops.length) continue;
      const chain = [n.id, ...hops];
      for (let i = 0; i < chain.length - 1; i++) {
        if ((chain[i] === a && chain[i + 1] === b) || (chain[i] === b && chain[i + 1] === a)) {
          out.push({ host: n, link, chain });
          break;                       // a road crossing a hop twice is still one road
        }
      }
    }
  }
  return out;
}

export function tierOf(n) {
  if (n.id === 'the-wild' || n.id === 'cloudflare') return 0;
  if (['gateway', 'traefik', 'tailscale', 'pangolin'].includes(n.id)) return 1;  // the ways in
  if (n.parent) return 3;
  return 2;                       // physical iron + remaining network gear
}

/** Lay the tiers out on a normalized 100×100 grid. Returns the four tiers and
    `pos`, each place's {x, y} by id.

    Wide (the default) the tiers are rows down the page and a tier's places
    spread across it. `narrow` (a phone, 2026-11-18) turns the picture a quarter:
    the tiers that hold anything are columns across the page, left to right in
    tier order, and a tier's places stack down from the top, every tier on the
    same rows. A phone has room downward and none across, and a name needs a
    column's width to be read. `rows` is the busiest tier's count (what the
    narrow picture's height is cut by) and `cols` the number of columns it has. */
export function layout(nodes, narrow = false) {
  const tiers = [[], [], [], []];
  for (const n of nodes) tiers[tierOf(n)].push(n);
  const TIER_Y = [8, 30, 55, 82];
  const pos = {};
  if (!narrow) {
    tiers.forEach((tier, t) => {
      tier.forEach((n, i) => {
        pos[n.id] = { x: (100 * (i + 1)) / (tier.length + 1), y: TIER_Y[t] };
      });
    });
    return { tiers, pos };
  }
  const held = tiers.filter((tier) => tier.length);
  const cols = Math.max(held.length, 1);
  const rows = Math.max(...tiers.map((tier) => tier.length), 1);
  held.forEach((tier, c) => {
    tier.forEach((n, i) => {
      pos[n.id] = { x: (100 * (c + 0.5)) / cols, y: (100 * (i + 0.5)) / rows };
    });
  });
  return { tiers, pos, rows, cols };
}

/** The curve between two places, as an SVG path's `d` on the same grid. Wide,
    it leaves and arrives vertically (the tiers are rows); narrow, horizontally
    (the tiers are columns). Narrow, two places in one column would be joined
    by a straight line down through every name between them, so that curve
    bows out into the gap beside the column instead: toward the column before
    it, or after it for the first. `cols` is the narrow layout's column count. */
export function edgePath(a, b, narrow = false, cols = 1) {
  if (!narrow) {
    const my = (a.y + b.y) / 2;
    return `M ${a.x} ${a.y} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
  }
  if (a.x === b.x) {
    const width = 100 / Math.max(cols, 1);
    const bx = a.x + (a.x < width ? 0.62 : -0.62) * width;
    return `M ${a.x} ${a.y} C ${bx} ${a.y}, ${bx} ${b.y}, ${b.x} ${b.y}`;
  }
  const mx = (a.x + b.x) / 2;
  return `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`;
}

/** edges: routes[] + parent containment (drawn quieter). A route is kept only
    when both of its ends have a position. */
export function edgesOf(routes, nodes, pos) {
  const edges = [];
  for (const r of routes || []) {
    if (pos[r.from] && pos[r.to]) edges.push({ a: r.from, b: r.to, kind: r.kind || 'road' });
  }
  for (const n of nodes) {
    if (n.parent && pos[n.parent]) edges.push({ a: n.parent, b: n.id, kind: 'vassal' });
  }
  return edges;
}

/** Every consecutive pair of a chain, both ways round, as `a<sep>b` — an edge
    is drawn once for a pair, so a lookup must match it in either direction. */
export function chainPairs(chain, sep = ' ') {
  const pairs = new Set();
  for (let i = 0; i < chain.length - 1; i++) {
    pairs.add(`${chain[i]}${sep}${chain[i + 1]}`);
    pairs.add(`${chain[i + 1]}${sep}${chain[i]}`);
  }
  return pairs;
}
